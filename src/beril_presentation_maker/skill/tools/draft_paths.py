#!/usr/bin/env python3
"""draft_paths.py — canonical path layout for a presentation-maker draft.

Introduced in v0.3.1. Replaces the v0.3.0 chaos where every tool computed
its own per-file paths against `draft_dir/` directly, mixing deliverables,
narrative, intermediate state, and audit debris at a single level.

# The 4-zone layout

```
projects/<id>/talks/draft_N/
├── deliverable/   what the user opens. only the rendered talk.
├── narrative/     human-readable story artifacts. throughline, substories,
│                  references. user can edit between revision cycles.
├── working/       intermediate pipeline state. each file is the input to a
│                  downstream stage. user rarely reads directly.
└── audit/         provenance + debug. snapshots before mutation. per-stage
                   logs. prior-run artifacts.
```

Top-level of `draft_N/` has exactly four entries. Anything else is a bug.

# Usage

```python
from beril_presentation_maker.skill.tools.draft_paths import DraftPaths

paths = DraftPaths.from_draft_dir("/path/to/draft_5")
paths.init_layout()                           # create skeleton if missing

with paths.slide_spec.open() as f:            # working/slide_spec.json
    spec = json.load(f)

paths.snapshot("pre_revise", spec)            # audit/snapshots/slide_spec.pre_revise.json
paths.write_stage_log("revise", "stderr", err_text)  # audit/stage-logs/revise.stderr
```

# Mirror in shell

`tools/presentation_maker.sh` hardcodes the same layout via simple
variable assignments (no Python startup per stage). The Python test
`tests/unit/test_draft_paths.py` asserts shell + Python agree on the
schema; if the shell drifts, the test fails.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------
# Layout constants — the single source of truth
# --------------------------------------------------------------------------

# Top-level zones, in declaration order.
ZONES = ("deliverable", "narrative", "working", "audit")

# Subdirectories that must exist after init_layout(). Top-level zones
# implied; these are the second-level dirs that tools assume exist.
LAYOUT_SUBDIRS = (
    # narrative/ has only flat files; no subdirs
    "working/03_slides",
    "working/04_speaker_notes",
    "working/05_image_requests",   # v0.3.3 image-gen Channel A staging
    "working/05_images",           # v0.3.3 generated PNGs (draft-local)
    "audit/stage-logs",
    "audit/snapshots",
    "audit/snapshots/03_slides_pre_image_gen",   # v0.3.3: fragment snapshots
                                                 # before image-gen mutation
    "audit/manual-edits",
    "audit/runs",
)


# --------------------------------------------------------------------------
# DraftPaths — the path-resolver class
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DraftPaths:
    """Authoritative path layout for a draft directory.

    Frozen so callers can't accidentally mutate the layout. Every per-file
    path is a property; every helper is a method. No file I/O at construction
    time — call init_layout() to materialize the skeleton.
    """

    draft_dir: Path

    # ---- top-level zones ----

    @property
    def deliverable(self) -> Path:
        return self.draft_dir / "deliverable"

    @property
    def narrative(self) -> Path:
        return self.draft_dir / "narrative"

    @property
    def working(self) -> Path:
        return self.draft_dir / "working"

    @property
    def audit(self) -> Path:
        return self.draft_dir / "audit"

    # ---- deliverable/ ----

    @property
    def deck_pptx(self) -> Path:
        return self.deliverable / "draft.pptx"

    @property
    def deck_pdf(self) -> Path:
        return self.deliverable / "draft.pdf"

    @property
    def speaker_notes_pdf(self) -> Path:
        return self.deliverable / "speaker-notes.pdf"

    # ---- narrative/ ----

    @property
    def throughline(self) -> Path:
        return self.narrative / "00_throughline.md"

    @property
    def substories(self) -> Path:
        return self.narrative / "02_substories.md"

    @property
    def references_md(self) -> Path:
        return self.narrative / "references.md"

    @property
    def bibliography(self) -> Path:
        return self.narrative / "bibliography.bib"

    @property
    def citation_map(self) -> Path:
        return self.narrative / "citation_map.md"

    # ---- working/ ----

    @property
    def plan(self) -> Path:
        return self.working / "00_plan.md"

    @property
    def throughline_candidates(self) -> Path:
        return self.working / "00_throughline_candidates.md"

    @property
    def slides_dir(self) -> Path:
        return self.working / "03_slides"

    @property
    def speaker_notes_dir(self) -> Path:
        return self.working / "04_speaker_notes"

    @property
    def image_requests_dir(self) -> Path:
        return self.working / "05_image_requests"

    @property
    def images_dir(self) -> Path:
        return self.working / "05_images"

    @property
    def citation_pool(self) -> Path:
        return self.working / "citation_pool.json"

    @property
    def cross_tenant_md(self) -> Path:
        return self.working / "cross_tenant_signal.md"

    @property
    def cross_tenant_json(self) -> Path:
        return self.working / "cross_tenant_signal.json"

    @property
    def curated_figures(self) -> Path:
        """The CANONICAL curated figures path. v0.3.1 killed the
        `figures_curated.md` duplicate."""
        return self.working / "curated_figures.md"

    @property
    def figures_inventory(self) -> Path:
        return self.working / "figures_inventory.md"

    @property
    def diagram_repair(self) -> Path:
        return self.working / "diagram_repair_report.md"

    @property
    def next_actions(self) -> Path:
        return self.working / "next_actions.md"

    @property
    def slide_spec(self) -> Path:
        """The LIVE spec. Mutates during the run; snapshots in audit/snapshots/
        before each mutation."""
        return self.working / "slide_spec.json"

    @property
    def image_decisions_json(self) -> Path:
        """v0.3.3: per-slide decision-layer output.

        Each entry says emit=True/False + reason for that slide's
        layout. Consumed by the image-gen orchestrator stage to drive
        the per-slide LLM-prompt loop.
        """
        return self.working / "05_image_decisions.json"

    @property
    def image_manifest_json(self) -> Path:
        """v0.3.3: per-image manifest. Records every approved /
        rejected / budget-skipped slide_id → image_path binding plus
        provenance metadata.

        Lives inside images_dir so the manifest travels with the PNGs
        when the user copies the dir somewhere else for review.
        """
        return self.images_dir / "manifest.json"

    # ---- working/ slide-fragment helpers (per-substory + per-image) ----

    def slide_fragment(self, fragment_id: str) -> Path:
        """A per-slide compose fragment, e.g. 'intro', 'cross_tenant',
        'qa_anticipated', 'S1_slides'."""
        return self.slides_dir / f"{fragment_id}.json"

    def speaker_notes(self, fragment_id: str) -> Path:
        """Per-slide speaker notes."""
        return self.speaker_notes_dir / f"{fragment_id}.md"

    def image_request(self, slide_id: str) -> Path:
        """v0.3.3 image-gen request JSON for a slide."""
        return self.image_requests_dir / f"{slide_id}_request.json"

    def generated_image(self, slide_id: str, ext: str = "png") -> Path:
        """v0.3.3 generated PNG for a slide."""
        return self.images_dir / f"{slide_id}.{ext}"

    # ---- audit/ ----

    @property
    def state(self) -> Path:
        return self.audit / "state.json"

    @property
    def cost_log(self) -> Path:
        return self.audit / "cost-log.jsonl"

    @property
    def stage_metadata(self) -> Path:
        """Consolidated provenance, replacing v0.3.0's 13 scattered
        `*.metadata.json` files at draft-root."""
        return self.audit / "stage-metadata.json"

    @property
    def stage_logs_dir(self) -> Path:
        return self.audit / "stage-logs"

    @property
    def snapshots_dir(self) -> Path:
        return self.audit / "snapshots"

    @property
    def manual_edits_dir(self) -> Path:
        return self.audit / "manual-edits"

    @property
    def runs_dir(self) -> Path:
        return self.audit / "runs"

    @property
    def adversarial_review_json(self) -> Path:
        return self.audit / "adversarial_review.json"

    @property
    def adversarial_review_md(self) -> Path:
        return self.audit / "adversarial_review.md"

    @property
    def adversarial_review_original_summary(self) -> Path:
        """v0.4.1 sidecar from beril-adversarial validator auto-correct."""
        return self.audit / "adversarial_review.original-summary.json"

    @property
    def quantitative_grounding_json(self) -> Path:
        return self.audit / "quantitative_grounding.json"

    @property
    def quantitative_grounding_md(self) -> Path:
        return self.audit / "quantitative_grounding.md"

    @property
    def revise_loop_metadata(self) -> Path:
        return self.audit / "revise_loop_metadata.json"

    @property
    def image_provenance_json(self) -> Path:
        """v0.3.3: append-only provenance log for image_client.py.

        Schema documented in image_client.append_provenance(). Each
        entry records model + prompt + cost + elapsed + channel +
        approved_at + quant_content_score for one image-generation
        call. Survives across re-runs in the same draft (orchestrator
        appends; never truncates).
        """
        return self.audit / "image_provenance.json"

    @property
    def pre_image_gen_snapshots_dir(self) -> Path:
        """v0.3.3: where slide_compose fragments are snapshotted before
        the image-gen stage mutates them (writing real image_path /
        provenance over the {TBD} placeholders).

        Used by R6's Option-A rejection path: a rejected concept_illustration
        slide is dropped from the live fragment, but the pre-mutation
        version remains here for recovery if the user changes their mind.
        """
        return self.snapshots_dir / "03_slides_pre_image_gen"

    def pre_image_gen_snapshot(self, fragment_id: str) -> Path:
        """Per-fragment pre-image-gen snapshot path.

        fragment_id matches slide_fragment(): 'S1_slides', 'intro',
        'cross_tenant', etc. The snapshot is a verbatim copy of the
        fragment JSON before image-gen mutates it.
        """
        return self.pre_image_gen_snapshots_dir / f"{fragment_id}.json"

    @property
    def last_render_hash(self) -> Path:
        """Stores the sha256 of deliverable/draft.pptx after the last
        successful assemble. Used by the manual-edit hash guard."""
        return self.audit / "last-render.json"

    @property
    def last_render_pptx(self) -> Path:
        """Immutable copy of deliverable/draft.pptx after the last
        successful assemble. Compared against the live deck on next
        assemble to detect manual edits."""
        return self.snapshots_dir / "last-render.pptx"

    # ---- audit/ helper methods ----

    def slide_spec_snapshot(self, label: str) -> Path:
        """Snapshot path for slide_spec.json mutations.

        Standard labels: 'raw' (right after merge), 'pre_revise' (before
        revise loop), 'post_assemble' (right after final assemble),
        'run-N' (per orchestrator invocation).
        """
        return self.snapshots_dir / f"slide_spec.{label}.json"

    def stage_log(self, stage: str, kind: str = "stdout") -> Path:
        """Per-stage log file.

        kind: 'stdout' | 'stderr' | 'stream.log'
        """
        if kind not in ("stdout", "stderr", "stream.log"):
            raise ValueError(f"unknown log kind: {kind!r}")
        return self.stage_logs_dir / f"{stage}.{kind}"

    def manual_edit_archive(self, timestamp: Optional[datetime] = None) -> Path:
        """Where to stash a user-edited draft.pptx before the orchestrator
        clobbers it. Filename uses UTC ISO timestamp."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        # Filesystem-safe ISO: 2026-05-01T18-22-14Z
        ts = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")
        return self.manual_edits_dir / f"{ts}.pptx"

    def run_archive_dir(self, run_n: int) -> Path:
        """Per-run archive directory under audit/runs/."""
        return self.runs_dir / f"run-{run_n}"

    # ---- mutators ----

    def init_layout(self) -> None:
        """Create the 4-zone skeleton if missing. Idempotent."""
        for zone in ZONES:
            (self.draft_dir / zone).mkdir(parents=True, exist_ok=True)
        for sub in LAYOUT_SUBDIRS:
            (self.draft_dir / sub).mkdir(parents=True, exist_ok=True)

    def is_initialized(self) -> bool:
        """True when all 4 top-level zones exist."""
        return all((self.draft_dir / z).is_dir() for z in ZONES)

    def assert_initialized(self) -> None:
        """Raise FileNotFoundError if the layout doesn't look like v0.3.1+.

        Used by tools that must NOT silently create-on-write into a draft
        that hasn't been initialized yet.
        """
        if not self.is_initialized():
            missing = [z for z in ZONES if not (self.draft_dir / z).is_dir()]
            raise FileNotFoundError(
                f"draft directory at {self.draft_dir} does not have v0.3.1+ "
                f"layout (missing zones: {missing}). "
                f"Run `beril-presentation-maker draft <project>` to start a "
                f"fresh draft, or this is an old-layout draft from v0.3.0 "
                f"or earlier (no migration tool — start fresh)."
            )

    # ---- snapshot helpers ----

    def snapshot_slide_spec(self, label: str, *, source: Optional[Path] = None) -> Path:
        """Copy slide_spec.json to audit/snapshots/slide_spec.<label>.json.

        Returns the snapshot path. Source defaults to self.slide_spec.
        Raises FileNotFoundError if source doesn't exist.
        """
        src = source if source is not None else self.slide_spec
        dst = self.slide_spec_snapshot(label)
        if not src.is_file():
            raise FileNotFoundError(f"cannot snapshot — source missing: {src}")
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    # ---- manual-edit hash-guard helpers ----

    def record_render_hash(self) -> str:
        """Compute sha256 of deliverable/draft.pptx and persist to
        audit/last-render.json. Also copy the pptx to
        audit/snapshots/last-render.pptx as the diff baseline.

        Returns the hex digest. Raises FileNotFoundError if the deck
        doesn't exist (caller should have run assemble first).
        """
        deck = self.deck_pptx
        if not deck.is_file():
            raise FileNotFoundError(f"deck not found: {deck}")

        digest = _sha256_file(deck)
        payload = {
            "schema_version": "last-render.v1",
            "draft_pptx": str(deck.relative_to(self.draft_dir)),
            "sha256": digest,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.audit.mkdir(parents=True, exist_ok=True)
        self.last_render_hash.write_text(json.dumps(payload, indent=2))

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deck, self.last_render_pptx)
        return digest

    def detect_manual_edit(self) -> Optional[str]:
        """Compare current deck against the last-render hash.

        Returns:
          None       — no prior render recorded, OR hash matches (no edit)
          str digest — the current deck's hash, when it differs from stored

        Caller decides what to do (typically: archive + warn).
        """
        if not self.deck_pptx.is_file():
            return None  # no deck yet → no edit possible
        if not self.last_render_hash.is_file():
            return None  # no prior render → can't detect edit

        try:
            stored = json.loads(self.last_render_hash.read_text())
            stored_digest = stored.get("sha256")
        except (json.JSONDecodeError, KeyError):
            # Corrupt last-render.json → treat as no-prior-render (safe default)
            return None

        current_digest = _sha256_file(self.deck_pptx)
        if current_digest == stored_digest:
            return None
        return current_digest

    def archive_manual_edit(self) -> Path:
        """Copy the current deliverable/draft.pptx to
        audit/manual-edits/<UTC-timestamp>.pptx. Returns the archive path.

        Caller should have already detected a manual edit. This function
        just performs the archival.
        """
        if not self.deck_pptx.is_file():
            raise FileNotFoundError(f"no deck to archive: {self.deck_pptx}")
        self.manual_edits_dir.mkdir(parents=True, exist_ok=True)
        dst = self.manual_edit_archive()
        shutil.copy2(self.deck_pptx, dst)
        return dst

    # ---- factories ----

    @classmethod
    def from_draft_dir(cls, draft_dir) -> "DraftPaths":
        """Construct from a string or Path. Resolves to absolute path.

        Does NOT verify the layout exists; caller decides whether to
        init_layout() or assert_initialized().
        """
        return cls(draft_dir=Path(draft_dir).resolve())


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _sha256_file(path: Path, *, chunk_size: int = 65536) -> str:
    """Compute sha256 hex digest of a file. Streams to avoid loading
    multi-MB pptx into memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Shell-export helper (used by integration tests + ad-hoc)
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# CLI — used by the shell orchestrator
# --------------------------------------------------------------------------

def _cli_record_render_hash(draft_dir: str) -> int:
    """Used by presentation_maker.sh after assemble_pptx.py succeeds.
    Records the rendered deck's hash + snapshots it as the diff baseline.
    """
    paths = DraftPaths.from_draft_dir(draft_dir)
    try:
        digest = paths.record_render_hash()
    except FileNotFoundError as e:
        print(f"record-render-hash: {e}", flush=True)
        return 1
    print(f"render-hash recorded: sha256={digest[:12]}... -> {paths.last_render_hash}",
          flush=True)
    return 0


def _cli_detect_manual_edit(draft_dir: str) -> int:
    """Used by presentation_maker.sh before assemble_pptx.py overwrites the
    deck. If the user has manually edited deliverable/draft.pptx since the
    last render, archive their edited copy to audit/manual-edits/ and warn.
    Always exits 0 — this is a non-blocking advisory step.
    """
    paths = DraftPaths.from_draft_dir(draft_dir)
    detected = paths.detect_manual_edit()
    if detected is None:
        return 0  # no edit (or no prior render)

    archive = paths.archive_manual_edit()
    import sys
    print("", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print("MANUAL EDIT DETECTED on deliverable/draft.pptx", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print(f"  The deck was modified since the last render.", file=sys.stderr)
    print(f"  Your edited copy has been preserved at:", file=sys.stderr)
    print(f"    {archive}", file=sys.stderr)
    print(f"  before the orchestrator regenerates the deck.", file=sys.stderr)
    print(f"  See SKILL.md §manual-edits for guidance on edit workflows", file=sys.stderr)
    print(f"  that survive re-runs.", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print("", file=sys.stderr)
    return 0


def main() -> int:
    """CLI entry point. Subcommands:

      record-render-hash <draft_dir>
      detect-manual-edit <draft_dir>

    Both used by presentation_maker.sh; always callable directly for debug.
    """
    import sys
    if len(sys.argv) < 2:
        print("usage: draft_paths.py {record-render-hash|detect-manual-edit} <draft_dir>",
              file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "record-render-hash":
        if len(sys.argv) != 3:
            print("usage: draft_paths.py record-render-hash <draft_dir>", file=sys.stderr)
            return 2
        return _cli_record_render_hash(sys.argv[2])
    elif cmd == "detect-manual-edit":
        if len(sys.argv) != 3:
            print("usage: draft_paths.py detect-manual-edit <draft_dir>", file=sys.stderr)
            return 2
        return _cli_detect_manual_edit(sys.argv[2])
    else:
        print(f"unknown subcommand: {cmd!r}", file=sys.stderr)
        print("supported: record-render-hash, detect-manual-edit", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


def shell_exports(paths: DraftPaths) -> str:
    """Emit shell variable assignments for the layout.

    Used by the integration test to verify presentation_maker.sh's
    hardcoded paths agree with this module's schema. Not intended for
    runtime use (Python startup overhead per stage is ~100ms).
    """
    pairs = [
        ("DELIVERABLE_DIR", paths.deliverable),
        ("NARRATIVE_DIR", paths.narrative),
        ("WORKING_DIR", paths.working),
        ("AUDIT_DIR", paths.audit),
        # deliverable/
        ("DECK_PPTX", paths.deck_pptx),
        ("DECK_PDF", paths.deck_pdf),
        # narrative/
        ("THROUGHLINE_PATH", paths.throughline),
        ("SUBSTORIES_PATH", paths.substories),
        ("REFERENCES_MD", paths.references_md),
        ("BIBLIOGRAPHY", paths.bibliography),
        ("CITATION_MAP", paths.citation_map),
        # working/
        ("PLAN_PATH", paths.plan),
        ("THROUGHLINE_CANDIDATES", paths.throughline_candidates),
        ("SLIDES_DIR", paths.slides_dir),
        ("SPEAKER_NOTES_DIR", paths.speaker_notes_dir),
        ("IMAGE_REQUESTS_DIR", paths.image_requests_dir),
        ("IMAGES_DIR", paths.images_dir),
        ("CITATION_POOL_PATH", paths.citation_pool),
        ("CROSS_TENANT_MD", paths.cross_tenant_md),
        ("CROSS_TENANT_JSON", paths.cross_tenant_json),
        ("CURATED_FIGURES", paths.curated_figures),
        ("FIGURES_INVENTORY", paths.figures_inventory),
        ("DIAGRAM_REPAIR", paths.diagram_repair),
        ("NEXT_ACTIONS", paths.next_actions),
        ("SLIDE_SPEC", paths.slide_spec),
        # v0.3.3 image-gen
        ("IMAGE_DECISIONS_JSON", paths.image_decisions_json),
        ("IMAGE_MANIFEST_JSON", paths.image_manifest_json),
        # audit/
        ("STATE_JSON", paths.state),
        ("COST_LOG", paths.cost_log),
        ("STAGE_METADATA", paths.stage_metadata),
        ("STAGE_LOGS_DIR", paths.stage_logs_dir),
        ("SNAPSHOTS_DIR", paths.snapshots_dir),
        ("MANUAL_EDITS_DIR", paths.manual_edits_dir),
        ("RUNS_DIR", paths.runs_dir),
        ("ADVERSARIAL_REVIEW_JSON", paths.adversarial_review_json),
        ("ADVERSARIAL_REVIEW_MD", paths.adversarial_review_md),
        ("QUANT_GROUNDING_JSON", paths.quantitative_grounding_json),
        ("QUANT_GROUNDING_MD", paths.quantitative_grounding_md),
        ("REVISE_LOOP_METADATA", paths.revise_loop_metadata),
        ("IMAGE_PROVENANCE_JSON", paths.image_provenance_json),
        ("PRE_IMAGE_GEN_SNAPSHOTS_DIR", paths.pre_image_gen_snapshots_dir),
        ("LAST_RENDER_HASH", paths.last_render_hash),
        ("LAST_RENDER_PPTX", paths.last_render_pptx),
    ]
    return "\n".join(f'{name}="{path}"' for name, path in pairs)
