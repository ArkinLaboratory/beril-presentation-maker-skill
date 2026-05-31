#!/usr/bin/env python3
"""merge_compose_fragments.py — assemble per-substory slide_compose
fragments into a single slide_spec.json.

Reads:
  - throughline.md         → throughline_id + punchline + tier
  - substories.md          → ordered (substory_id, punchline) list
  - 03_slides/{S?}_slides.json  → per-substory slide_compose fragments

Produces:
  - slide_spec.json conformant to slide_spec.py's v1 schema, with:
      * stub title slide (id=1)
      * per-substory slides (renumbered, substory_id-tagged)
      * stub acknowledgments slide
      * stub references slide
      * top-level substories[] list with collected slide_ids
      * top-level throughline metadata

Smoke-only behavior:
  - Title / acknowledgments / references slides are STUBS (presenter
    "TBD", contributors ["TBD"], refs_short ["TBD - smoke run"]).
    Production orchestrator will populate these from the project's
    metadata + citation pool.
  - Speaker notes: a v0.3.x `compose-fragment.v1` fragment carries a
    raw `speaker_notes_seed` (dropped on merge); the v0.3.x path runs
    `speaker_notes.v1` before merge and merge injects the parsed
    result from `--speaker-notes-dir`. A v0.4 `compose-fragment.v2`
    fragment carries the FINISHED `speaker_notes` inline per slide
    (D-033 fusion) — merge keeps it, and derives
    `working/04_speaker_notes/{sid}_notes.json` from it so
    beril-adversarial's `--type presentation` reviewer still finds
    the notes.
  - evidence_anchors (orchestrator metadata, not slide_spec.json
    fields) is dropped on merge.
  - cross_tenant_integration / qa_anticipated slides are NOT spliced
    in v1 smoke (those prompts run in production but not smoke).
  - concept_illustration slides retain the {TBD} placeholders from
    slide_compose and pass through; the orchestrator's downstream
    ai_image_prompt path is also skipped in smoke. Validators may
    flag these — that's expected for the smoke output.

CLI:
    python3 merge_compose_fragments.py \
        --outdir <draft_N>/ \
        --project-id <id> \
        --mode <mode> \
        --tier <tier> \
        --audience peer \
        --throughline-path <draft_N>/00_throughline.md \
        --substory-path <draft_N>/02_substories.md \
        --fragments-dir <draft_N>/03_slides/ \
        --out <draft_N>/slide_spec.json

Exit codes:
  0 — slide_spec.json written
  1 — input file missing / unreadable
  2 — fragment-shape mismatch (e.g., fragment lacks expected fields)
  3 — schema mismatch (fragment_id absent from substories.md)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

# slide_spec.py for SCHEMA_VERSION; if running from source, sys.path
# may not include the tools dir, so we resolve relative to this file.
_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))
import slide_spec  # noqa: E402  (sibling tool)
# M4a Tier E round 4 (2026-05-24): pull the assembler's acronym fix-up
# so the title written to slide_spec.json on disk matches the rendered
# title. Without this, the spec carries "Ibd Phage Targeting" while the
# assembler renders "IBD Phage Targeting" — confuses the visual-QA
# vision pass (it reads the spec AND the PNG; sees a mismatch that
# isn't really there). One module-level import; only this helper is
# pulled, not the renderer itself.
import importlib.util as _importlib_util
_ASSEMBLE_PATH = _TOOLS_DIR / "assemble_pptx.py"
_assemble_spec = _importlib_util.spec_from_file_location(
    "_assemble_for_acronym", _ASSEMBLE_PATH
)
_assemble_mod = _importlib_util.module_from_spec(_assemble_spec)
sys.modules["_assemble_for_acronym"] = _assemble_mod
_assemble_spec.loader.exec_module(_assemble_mod)
_fix_acronyms_in_title = _assemble_mod._fix_acronyms_in_title


# v0.3.2.1: regex to strip JSON-trailing-commas. Matches `,` followed by
# zero-or-more whitespace (incl newlines) and a `}` or `]`. Used by
# `_load_json_lenient` to repair LLM-emitted fragment JSON.
#
# This handles trailing commas — the most common LLM JSON malformation.
# Unescaped quotes inside strings are NOT auto-repairable (per the
# v0.1.8/v0.1.9 hub experience); those still surface as JSONDecodeError.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _load_json_lenient(path: Path) -> dict:
    """Load JSON from a file, with one repair pass for trailing commas.

    LLM-emitted fragment JSON occasionally has a stray trailing comma
    before a closing `}` or `]`. Python's json module rejects these
    (correctly per spec). This helper:
      1. Tries strict json.loads first.
      2. On JSONDecodeError, strips trailing commas via regex and tries
         again. If the repaired text parses, returns the dict.
      3. On second failure, raises the ORIGINAL error so debug output
         points at the actual location of malformation.

    Logs a stderr note when the repair pass fires (so we can track
    how often LLM JSON malformation hits in production — if it's
    frequent, the right answer is to tighten the prompt's JSON
    discipline rules + a worked example, per the v0.1.9 pattern in
    `feedback_llm_json_unfixable_in_parser.md`).

    Tool-emitted JSON (parse_speaker_notes.py output, etc) should
    never trigger the repair branch; it's there as a safety net for
    LLM-emitted fragments.
    """
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        repaired = _TRAILING_COMMA_RE.sub(r"\1", text)
        if repaired == text:
            # Nothing to repair → original error stands.
            raise
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            # Repair didn't fix it — raise the ORIGINAL error.
            raise e
        # Repair fixed it. Note the repair so it's visible in the
        # orchestrator log (without flooding output).
        print(
            f"  [merge] note: stripped trailing comma(s) from {path.name} "
            f"(LLM JSON malformation; original error at line "
            f"{e.lineno} col {e.colno})",
            file=sys.stderr,
        )
        return data


THROUGHLINE_ID_RE = re.compile(r"<!--\s*chosen:\s*(TL\d+)\s*-->")
THROUGHLINE_PUNCHLINE_RE = re.compile(r"<!--\s*punchline:\s*(.+?)\s*-->")
TIER_RE = re.compile(r"^\*\*Tier:\*\*\s*([A-Z]+)", re.MULTILINE)


def parse_throughline(path: Path) -> dict:
    """Pull throughline_id, punchline, and tier from 00_throughline.md.

    The smoke orchestrator's parse_throughline_candidates.py writes
    HTML-comment metadata at the top of the file; tier comes from the
    candidate body (Tier line).
    """
    text = path.read_text(encoding="utf-8")
    tl_id_m = THROUGHLINE_ID_RE.search(text)
    pl_m = THROUGHLINE_PUNCHLINE_RE.search(text)
    tier_m = TIER_RE.search(text)

    if not tl_id_m:
        raise ValueError(
            f"throughline file missing 'chosen' metadata comment: {path}"
        )

    return {
        "id": tl_id_m.group(1),
        "punchline": pl_m.group(1).strip() if pl_m else "TBD",
        "tier_evidence": tier_m.group(1).strip() if tier_m else "STRONG",
    }


def parse_substories(path: Path) -> list[dict]:
    """Walk substory_design output for the ordered (id, punchline) list.

    Mirrors parse_substories.py's substory_punchlines field but inlined
    here so the merge can be self-contained.
    """
    text = path.read_text(encoding="utf-8")
    header_re = re.compile(
        r"^### (S\d+)\s*[—–-]\s*(.+?)\s*$", re.MULTILINE
    )
    punchline_re = re.compile(
        r"^\*\*Punchline:\*\*\s*(.+?)\s*$", re.MULTILINE
    )

    out: list[dict] = []
    headers = list(header_re.finditer(text))
    for i, m in enumerate(headers):
        sid = m.group(1)
        section_start = m.end()
        section_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[section_start:section_end]
        pm = punchline_re.search(section)
        punchline = pm.group(1).strip() if pm else f"({sid} punchline TBD)"
        out.append({"id": sid, "punchline": punchline, "slide_ids": []})
    return out


def load_fragments(fragments_dir: Path,
                   substory_ids: list[str]) -> dict[str, dict]:
    """Load each {Sn}_slides.json fragment. Returns {sid: fragment}.

    Raises if a fragment is missing for a declared substory or if a
    fragment has unexpected shape.
    """
    fragments: dict[str, dict] = {}
    for sid in substory_ids:
        path = fragments_dir / f"{sid}_slides.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"fragment missing for substory {sid}: {path}"
            )
        try:
            # v0.3.2.1: lenient loader — strips trailing commas before
            # parsing. Surfaces a stderr note when repair fires.
            data = _load_json_lenient(path)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"fragment {path} is not valid JSON: {e}"
            ) from e
        # Defensive: smoke fragments may not have schema_version or may
        # have placeholder content from the orchestrator's claim_file.
        if "slides" not in data or not isinstance(data["slides"], list):
            raise ValueError(
                f"fragment {path} missing slides[] array"
            )
        fragments[sid] = data
    return fragments


def strip_orchestrator_metadata(slide: dict) -> dict:
    """Remove fields that are orchestrator-internal and not in slide_spec.

    - speaker_notes_seed → dropped (smoke skips speaker_notes)
    - evidence_anchors → dropped (orchestrator metadata)
    - position → replaced by global id at merge
    """
    cleaned = {
        k: v for k, v in slide.items()
        if k not in ("speaker_notes_seed", "evidence_anchors", "position")
    }
    return cleaned


# v0.3.3: image-manifest binding. The image-gen stage (between
# speaker_notes and merge per V0_3_3_ARCHITECTURE.md §3) writes a
# manifest at working/05_images/manifest.json; merge consumes it
# here to bind approved image_path + provenance onto the matching
# concept_illustration slide, and to drop slides for rejected /
# budget-skipped entries (R6 Option A).
#
# Backwards-compat: when the manifest is absent (pre-v0.3.3 drafts,
# or `--no-images` runs), apply_image_manifest is a no-op.

def apply_image_manifest(
    slide_dict: dict,
    manifest,
    slide_id_target: str,
):
    """Apply manifest binding to one slide.

    Args:
      slide_dict: the cleaned slide dict (post strip_orchestrator_metadata).
        Mutated in place when an approved entry is bound.
      manifest: an image_gen_manifest.Manifest, or None (no-op).
      slide_id_target: "S2-pos4" pattern matching the manifest entry's slide_id.

    Returns:
      The slide dict (possibly mutated) when approved or no manifest entry.
      None when the slide is rejected or budget-skipped (caller drops it).
    """
    if manifest is None:
        return slide_dict
    entry = manifest.get(slide_id_target)
    if entry is None:
        return slide_dict
    if not entry.get("approved"):
        # Rejected (user choice) or budget-skipped — caller drops.
        return None

    # Approved: bind image_path + provenance into content. The
    # concept_illustration validator (slide_spec._check_concept_illustration)
    # requires both, so we populate them from the manifest entry's fields.
    content = slide_dict.setdefault("content", {})
    content["image_path"] = entry["image_path"]
    content["provenance"] = {
        "model": entry["model"],
        "cost_usd": entry["cost_usd"],
        "channel": entry["channel"],
        "approved_at": entry["approved_at"],
    }
    return slide_dict


def load_image_manifest(path: Optional[Path]):
    """Load the image manifest at `path`. Defensive: missing /
    malformed → returns None with a stderr warning, so merge can
    proceed without binding (legacy v0.3.2 behavior preserved).

    Returned object is an image_gen_manifest.Manifest (lazy-imported
    to keep merge runnable when the package isn't installed).
    """
    if path is None or not path.is_file():
        return None
    try:
        # Lazy-import: the sibling module path-resolves the same way
        # merge does. Keeps the test isolation clean.
        import image_gen_manifest as igm  # noqa: PLC0415
    except ImportError:
        # Package layout drift would surface here. Warn but don't
        # crash merge — the pipeline can proceed without binding.
        print(
            f"  [merge] warning: image_gen_manifest module not importable; "
            f"skipping manifest binding from {path}",
            file=sys.stderr,
        )
        return None
    try:
        return igm.Manifest.load(path)
    except Exception as e:  # noqa: BLE001 — defensive
        print(
            f"  [merge] warning: image manifest at {path} not loadable: {e}; "
            f"proceeding without image binding",
            file=sys.stderr,
        )
        return None


def build_title_slide(slide_id: int, throughline_punchline: str,
                      project_id: str) -> dict:
    """Build the title slide.

    2026-04-26 visual review found the prior version used the full
    throughline punchline (often 200-300 chars) as the title, causing
    catastrophic overrun on the title placeholder (5x oversize) — text
    spilled over the KBase logo. The fix:

      - Title  = project_id rendered title-case (e.g. `functional_dark_matter`
                 → `Functional Dark Matter`). Short, fits the placeholder
                 cleanly.
      - Subtitle = throughline punchline (the full claim). Larger
                 placeholder + autofit on the master handles longer text.

    Production orchestrator will eventually replace this with a project-
    metadata-driven title (RESEARCH_PLAN-derived short title), but the
    project_id title-case is the reasonable v0.1 stub.
    """
    today = dt.date.today().isoformat()

    # Render project_id as a human-readable title:
    # `functional_dark_matter` → `Functional Dark Matter`
    # `cf-formulation-design`  → `Cf Formulation Design`
    title_text = project_id.replace("_", " ").replace("-", " ").title().strip()
    if not title_text:
        title_text = f"BERDL project: {project_id}"
    # M4a Tier E round 4 (2026-05-24): acronym-aware fix-up. Python's
    # .title() lowercases letters after the first in each word — so
    # `ibd_phage_targeting` → "Ibd Phage Targeting" instead of "IBD
    # Phage Targeting". Apply the shared assembler helper so the spec
    # on disk matches what the renderer + visual-QA see.
    title_text = _fix_acronyms_in_title(title_text)

    # Subtitle carries a TRUNCATED version of the throughline punchline.
    # 2026-04-26 followup: full punchline (200-300 chars) overflowed the
    # subtitle placeholder even with autofit (which fontScale=80% can't
    # rescue at 30%-required shrink). Truncate at the last word boundary
    # ≤120 chars + ellipsis — the full claim lives in 00_throughline.md
    # for the speaker; the subtitle is just an audience teaser.
    SUBTITLE_CAP = 120
    if not throughline_punchline or throughline_punchline == "TBD":
        subtitle = ""
    elif len(throughline_punchline) <= SUBTITLE_CAP:
        subtitle = throughline_punchline
    else:
        # Truncate at last word boundary ≤ cap-3 (room for "...")
        cut = throughline_punchline.rfind(" ", 0, SUBTITLE_CAP - 3)
        if cut < 0:
            cut = SUBTITLE_CAP - 3
        subtitle = throughline_punchline[:cut].rstrip(" ,;") + "…"

    content = {
        "title": title_text,
        "presenter": "TBD",
        "date": today,
        "affiliation": "TBD",
    }
    if subtitle:
        content["subtitle"] = subtitle

    return {
        "id": slide_id,
        "layout": "title",
        "content": content,
    }


def build_acknowledgments_slide(slide_id: int) -> dict:
    return {
        "id": slide_id,
        "layout": "acknowledgments",
        "content": {
            "contributors": ["TBD - populated by production orchestrator"],
            "tenant_attribution": "TBD",
        },
    }


def build_references_slide(slide_id: int,
                           citation_pool_path: Path | None = None) -> dict:
    """Build the references slide.

    2026-04-27 #72: if citation_pool.json exists, populate refs_short
    with the top-N (≤8) entries formatted as compact citation strings.
    Falls back to the TBD stub if pool is absent or malformed.
    """
    refs_short: list[str] = []
    if citation_pool_path is not None and citation_pool_path.is_file():
        try:
            # v0.3.2.1: lenient loader (LLM-emitted via citation_pool stage)
            pool = _load_json_lenient(citation_pool_path)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: cannot parse citation pool at "
                  f"{citation_pool_path}: {e}", file=sys.stderr)
            pool = None
        if isinstance(pool, list):
            entries = pool
        elif isinstance(pool, dict):
            entries = pool.get("entries", []) or []
        else:
            entries = []
        # Take up to 8 entries; format as "{authors} ({year}). {title}.
        # {venue}." compact form. Tolerate missing fields.
        for entry in entries[:8]:
            if not isinstance(entry, dict):
                continue
            authors = entry.get("authors") or entry.get("author") or "?"
            if isinstance(authors, list):
                authors = (authors[0] + " et al."
                           if len(authors) > 1 else authors[0])
            year = entry.get("year") or "?"
            title = entry.get("title") or "?"
            venue = entry.get("venue") or entry.get("journal") or ""
            short = f"{authors} ({year}). {title}."
            if venue:
                short += f" {venue}."
            refs_short.append(short[:200])  # cap per-entry length

    if not refs_short:
        refs_short = ["TBD - citation_pool not available"]
    return {
        "id": slide_id,
        "layout": "references",
        "content": {
            "refs_short": refs_short,
            "full_pool_in_speaker_notes": True if refs_short[0] != "TBD - citation_pool not available" else False,
        },
    }


def load_speaker_notes_for_substory(
    notes_dir: Path | None, substory_id: str
) -> dict[int, str]:
    """Load parsed speaker notes for a substory.

    Reads `{notes_dir}/{substory_id}_notes.json` (the parsed output
    from parse_speaker_notes.py). Returns a dict mapping per-substory
    position (0-indexed within the substory's slides) → notes text.

    Returns {} if the file is absent (speaker_notes stage skipped) or
    malformed (warns and proceeds without notes).
    """
    if notes_dir is None:
        return {}
    notes_path = notes_dir / f"{substory_id}_notes.json"
    if not notes_path.is_file():
        return {}
    try:
        data = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: cannot parse speaker notes at {notes_path}: {e}",
              file=sys.stderr)
        return {}
    raw = data.get("notes_by_position", {}) or {}
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


def derive_speaker_notes_files(
    fragments: dict,
    substories: list[dict],
    speaker_notes_dir: Path | None,
) -> int:
    """v0.4 (D-033 fusion): write `{sid}_notes.json` from inline notes.

    A `compose-fragment.v2` fragment carries the finished `speaker_notes`
    inline on each slide. The separate `speaker_notes` stage is retired
    on the v0.4 path, but beril-adversarial's `--type presentation`
    reviewer still reads `working/04_speaker_notes/{sid}_notes.json`.
    This derives those files from the fused fragments, in the exact
    `notes_by_position` shape `parse_speaker_notes.py` emits, so the
    cross-skill contract holds.

    No-op (returns 0) when `speaker_notes_dir` is None or no fragment
    declares `schema_version == "compose-fragment.v2"` (the v0.3.x
    path, where `speaker_notes.v1` already wrote those files).
    """
    if speaker_notes_dir is None:
        return 0
    written = 0
    for substory in substories:
        sid = substory["id"]
        fragment = fragments.get(sid)
        if not isinstance(fragment, dict):
            continue
        if fragment.get("schema_version") != "compose-fragment.v2":
            continue
        notes_by_position: dict[str, str] = {}
        for pos, slide in enumerate(fragment.get("slides", []) or []):
            notes = slide.get("speaker_notes") if isinstance(slide, dict) else None
            if isinstance(notes, str) and notes.strip():
                notes_by_position[str(pos)] = notes
        speaker_notes_dir.mkdir(parents=True, exist_ok=True)
        out_path = speaker_notes_dir / f"{sid}_notes.json"
        out_path.write_text(
            json.dumps(
                {"substory_id": sid, "notes_by_position": notes_by_position},
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        written += 1
    return written


def load_intro_fragment(path: Path | None) -> list[dict]:
    """Load the intro fragment (intro.json) if present and non-empty.

    Returns the list of intro slide objects (may be empty for
    lightning-5 / posters). Returns [] if the path is None or the
    file doesn't exist (intro stage was skipped).

    Defensive against malformed JSON: logs a warning and returns []
    rather than crashing the merge — intro is non-load-bearing in
    smoke mode, so a parse error shouldn't break the whole pipeline.
    """
    if path is None or not path.is_file():
        return []
    try:
        # v0.3.2.1: lenient loader (LLM-emitted via intro / cross_tenant /
        # qa_anticipated stages all dispatch through this helper).
        data = _load_json_lenient(path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: cannot parse intro fragment at {path}: {e}",
              file=sys.stderr)
        print("  proceeding without intro slides", file=sys.stderr)
        return []
    slides = data.get("slides", [])
    if not isinstance(slides, list):
        print(f"Warning: intro fragment {path} has non-list slides; "
              f"proceeding without intro", file=sys.stderr)
        return []
    return slides


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--mode", required=True)
    ap.add_argument("--tier", required=True)
    ap.add_argument("--audience", default="peer")
    ap.add_argument("--throughline-path", required=True)
    ap.add_argument("--substory-path", required=True)
    ap.add_argument("--fragments-dir", required=True)
    ap.add_argument("--intro-fragment-path", default=None,
                    help="Optional path to intro.json (intro stage output). "
                         "If absent or empty, no intro slides are spliced.")
    ap.add_argument("--speaker-notes-dir", default=None,
                    help="Optional directory containing parsed speaker "
                         "notes JSON files ({substory_id}_notes.json). "
                         "If present, speaker_notes are injected into "
                         "per-substory slides at merge time. Absent → "
                         "slides ship without speaker notes.")
    ap.add_argument("--citation-pool-path", default=None,
                    help="Optional path to citation_pool.json. If "
                         "present and non-empty, the references slide "
                         "is populated with the top ≤8 entries. Absent "
                         "or empty → slide ships with TBD stub.")
    ap.add_argument("--cross-tenant-fragment-path", default=None,
                    help="Optional path to cross_tenant_integration "
                         "slide JSON fragment. If present, splice as a "
                         "deck-level slide before acknowledgments.")
    ap.add_argument("--qa-fragment-path", default=None,
                    help="Optional path to qa_anticipated.json fragment "
                         "(qa_prep stage output). If present, splice "
                         "qa_anticipated slides at deck end before "
                         "acknowledgments.")
    ap.add_argument("--deck-close-fragment-path", default=None,
                    help="v0.7/D-086 Tier C.3: optional path to "
                         "deck_close.json fragment (stage_deck_close "
                         "output). If present and non-empty, splice "
                         "as the deck's narrative closer between the "
                         "final substory's last slide and the "
                         "cross_tenant / qa / acks / refs metadata "
                         "block. Empty slides[] (no_signal_fallback "
                         "from extract_deck_close) → nothing spliced; "
                         "validate_slide_spec's mode-gated soft-warning "
                         "surfaces the absent slide on talk-30 STRONG.")
    ap.add_argument("--image-manifest-path", default=None,
                    help="Optional path to working/05_images/manifest.json "
                         "(v0.3.3 image-gen stage output). If present, "
                         "approved entries bind image_path + provenance "
                         "onto matching concept_illustration slides; "
                         "rejected/skipped entries drop the slide from "
                         "the deck (R6 Option A). Absent → no binding "
                         "(v0.3.2-and-earlier behavior preserved).")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    throughline_path = Path(args.throughline_path)
    substory_path = Path(args.substory_path)
    fragments_dir = Path(args.fragments_dir)
    out_path = Path(args.out)

    if not throughline_path.is_file():
        print(f"Error: throughline file not found: {throughline_path}",
              file=sys.stderr)
        return 1
    if not substory_path.is_file():
        print(f"Error: substory file not found: {substory_path}",
              file=sys.stderr)
        return 1
    if not fragments_dir.is_dir():
        print(f"Error: fragments dir not found: {fragments_dir}",
              file=sys.stderr)
        return 1

    try:
        throughline = parse_throughline(throughline_path)
    except (ValueError, OSError) as e:
        print(f"Error parsing throughline: {e}", file=sys.stderr)
        return 2

    try:
        substories = parse_substories(substory_path)
    except OSError as e:
        print(f"Error reading substory file: {e}", file=sys.stderr)
        return 1

    if not substories:
        print(f"Error: no substories parsed from {substory_path}",
              file=sys.stderr)
        return 2

    substory_ids = [s["id"] for s in substories]
    try:
        fragments = load_fragments(fragments_dir, substory_ids)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading fragments: {e}", file=sys.stderr)
        return 3

    intro_path = (Path(args.intro_fragment_path)
                  if args.intro_fragment_path else None)
    intro_slides = load_intro_fragment(intro_path)

    # v0.3.3: load the image manifest (defensive — None when absent).
    # Drives both image-binding (approved entries) and slide-drop
    # (rejected/skipped entries) below.
    manifest_path = (Path(args.image_manifest_path)
                     if args.image_manifest_path else None)
    image_manifest = load_image_manifest(manifest_path)
    n_images_bound = 0
    n_slides_dropped = 0

    # Build the merged slide list with global IDs.
    slides: list[dict] = []
    next_id = 1

    # 1. Title stub
    slides.append(build_title_slide(next_id, throughline["punchline"],
                                    args.project_id))
    next_id += 1

    # 2. Intro slides (deck-level; no substory_id; not in any substory's
    #    slide_ids list; spliced between title and S1 divider).
    for intro_position, intro_slide in enumerate(intro_slides):
        cleaned = strip_orchestrator_metadata(intro_slide)
        # intro slides also have an `intro_role` field that's
        # orchestrator metadata, not in slide_spec — strip it.
        cleaned.pop("intro_role", None)
        # Intro slides have no substory_id; clear if present (defensive)
        cleaned.pop("substory_id", None)
        # v0.3.3: image-manifest binding for intro slides. Slide_id
        # uses 'intro-pos{N}' convention (matches image_gen_decision).
        slide_id_target = f"intro-pos{intro_position}"
        bound = apply_image_manifest(cleaned, image_manifest, slide_id_target)
        if bound is None:
            # Rejected / budget-skipped → drop slide.
            n_slides_dropped += 1
            continue
        cleaned = bound
        if image_manifest is not None and image_manifest.get(slide_id_target):
            n_images_bound += 1
        cleaned["id"] = next_id
        slides.append(cleaned)
        next_id += 1

    # 3. Per-substory slides (in declared order)
    speaker_notes_dir = (Path(args.speaker_notes_dir)
                         if args.speaker_notes_dir else None)
    n_notes_injected = 0
    for substory in substories:
        sid = substory["id"]
        fragment = fragments[sid]
        # 2026-04-27 #70: load parsed speaker notes for this substory
        # (if speaker_notes stage ran). Notes are keyed by per-substory
        # position (0-indexed within fragment.slides).
        notes_for_substory = load_speaker_notes_for_substory(
            speaker_notes_dir, sid
        )
        for fragment_position, slide in enumerate(fragment["slides"]):
            cleaned = strip_orchestrator_metadata(slide)
            # v0.3.3: image-manifest binding (approve / drop). Must
            # happen before global-id assignment so dropped slides
            # don't consume an id. slide_id matches image_gen_decision.
            slide_id_target = f"{sid}-pos{fragment_position}"
            bound = apply_image_manifest(cleaned, image_manifest, slide_id_target)
            if bound is None:
                n_slides_dropped += 1
                continue
            cleaned = bound
            if image_manifest is not None and image_manifest.get(slide_id_target):
                if image_manifest.get(slide_id_target).get("approved"):
                    n_images_bound += 1
            cleaned["id"] = next_id
            cleaned["substory_id"] = sid
            substory["slide_ids"].append(next_id)
            # Inject speaker_notes for this position if available
            if fragment_position in notes_for_substory:
                cleaned["speaker_notes"] = notes_for_substory[fragment_position]
                n_notes_injected += 1
            slides.append(cleaned)
            next_id += 1

    # v0.4 (D-033 fusion): a compose-fragment.v2 fragment carries the
    # speaker_notes inline (kept by strip_orchestrator_metadata, which
    # only drops speaker_notes_seed). The separate speaker_notes stage
    # is retired on the v0.4 path, so derive the
    # working/04_speaker_notes/{sid}_notes.json files that
    # beril-adversarial's --type presentation reviewer still reads.
    n_notes_derived = derive_speaker_notes_files(
        fragments, substories, speaker_notes_dir
    )

    # 3.5. Deck-close slide (v0.7/D-086 Tier C.3 — optional, deck-
    #      level, between final substory and the metadata block).
    #      Per D-086 the deck_close is the deck's narrative closer:
    #      unified_point + 3-5 key_takeaways + forward_call +
    #      data_source synthesized from substory C-slots + REPORT
    #      Future-directions. Goes BEFORE cross_tenant + qa +
    #      acks + refs so the closing synthesis is the last
    #      narrative beat before the metadata slides.
    #
    #      Mode-gated upstream (orchestrator only invokes
    #      stage_deck_close on talk-30 STRONG); below STRONG the
    #      fragment file may not exist, OR it exists with empty
    #      slides[] (no_signal_fallback case). Both shapes are
    #      handled here: missing-file → skip silently; empty
    #      slides[] → splice nothing. The mode-gated soft-warning
    #      in validate_slide_spec catches the talk-30 case where
    #      the slide SHOULD have landed but didn't.
    deck_close_path = (Path(args.deck_close_fragment_path)
                       if args.deck_close_fragment_path else None)
    if deck_close_path is not None and deck_close_path.is_file():
        try:
            dc_data = _load_json_lenient(deck_close_path)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: cannot parse deck_close fragment at "
                  f"{deck_close_path}: {e}", file=sys.stderr)
            dc_data = None
        if isinstance(dc_data, dict):
            dc_slides = dc_data.get("slides", [])
            for dc_slide in dc_slides:
                # Promote speaker_notes_seed → speaker_notes per the
                # deck_close.v1 contract (parallel to cross_tenant's
                # pattern; the speaker_notes stage runs only on
                # substory slides).
                #
                # v0.8/D-094: also promote content.data_source into
                # the speaker_notes pane as a **Sources:** appendix.
                # The v0.7 Tier-I read found the renderer was drawing
                # data_source as on-slide body text (fdm slide-32);
                # D-094 reclassifies it as audit-trail metadata —
                # presenter sees the citation in notes, audit pipeline
                # still reads it from content, audience doesn't see it.
                # Schema preserved: content.data_source remains
                # required per D-086; validator unchanged. Only the
                # rendered surface changes (face → notes).
                seed = dc_slide.get("speaker_notes_seed")
                content = dc_slide.get("content") or {}
                data_source = (content.get("data_source") or "").strip() \
                    if isinstance(content, dict) else ""
                cleaned = strip_orchestrator_metadata(dc_slide)
                if "speaker_notes" not in cleaned:
                    notes_parts = []
                    if isinstance(seed, str) and seed.strip():
                        notes_parts.append(seed.strip())
                    if data_source:
                        notes_parts.append(f"**Sources:** {data_source}")
                    if notes_parts:
                        cleaned["speaker_notes"] = "\n\n".join(notes_parts)
                cleaned["id"] = next_id
                cleaned.pop("substory_id", None)
                slides.append(cleaned)
                next_id += 1

    # 4. Cross-tenant slide (optional, deck-level — between last substory
    #    and acknowledgments). Per cross_tenant.v1.md, this is a single
    #    slide describing the project's K-BERDL platform integration if
    #    signals were detected.
    cross_tenant_path = (Path(args.cross_tenant_fragment_path)
                         if args.cross_tenant_fragment_path else None)
    if cross_tenant_path is not None and cross_tenant_path.is_file():
        try:
            # v0.3.2.1: lenient loader (LLM-emitted via cross_tenant.v1)
            ct_data = _load_json_lenient(cross_tenant_path)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: cannot parse cross_tenant fragment at "
                  f"{cross_tenant_path}: {e}", file=sys.stderr)
            ct_data = None
        if isinstance(ct_data, dict):
            ct_slides = ct_data.get("slides", [])
            for ct_slide in ct_slides:
                # 2026-04-27 #75: promote speaker_notes_seed → speaker_notes
                # for cross_tenant slides. The speaker_notes stage runs only
                # on substory slides; the cross_tenant slide is deck-level
                # and otherwise ships with no notes. Honour cross_tenant.v1's
                # contract that speaker_notes_seed becomes the slide's notes.
                seed = ct_slide.get("speaker_notes_seed")
                cleaned = strip_orchestrator_metadata(ct_slide)
                # Strip cross_tenant.v1-specific orchestrator metadata
                cleaned.pop("kbase_platform_frame", None)
                if isinstance(seed, str) and seed.strip() and "speaker_notes" not in cleaned:
                    cleaned["speaker_notes"] = seed.strip()
                cleaned["id"] = next_id
                cleaned.pop("substory_id", None)
                slides.append(cleaned)
                next_id += 1

    # 5. Q&A anticipated slides (optional, deck-level — at end before
    #    acknowledgments). Per qa_prep.v1.md, 0-4 slides depending on
    #    QA_SLIDE_BUDGET (mode-default).
    qa_path = (Path(args.qa_fragment_path)
               if args.qa_fragment_path else None)
    if qa_path is not None and qa_path.is_file():
        try:
            # v0.3.2.1: lenient loader (LLM-emitted via qa_prep.v1)
            qa_data = _load_json_lenient(qa_path)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: cannot parse qa fragment at {qa_path}: {e}",
                  file=sys.stderr)
            qa_data = None
        if isinstance(qa_data, dict):
            qa_slides = qa_data.get("slides", [])
            for qa_slide in qa_slides:
                cleaned = strip_orchestrator_metadata(qa_slide)
                # Strip qa_prep-specific orchestrator metadata
                cleaned.pop("weakness_target", None)
                cleaned.pop("tier_evidence_at_risk", None)
                cleaned["id"] = next_id
                cleaned.pop("substory_id", None)
                slides.append(cleaned)
                next_id += 1

    # 6. Acknowledgments stub
    slides.append(build_acknowledgments_slide(next_id))
    next_id += 1

    # 4. References stub
    citation_pool_path = (Path(args.citation_pool_path)
                          if args.citation_pool_path else None)
    slides.append(build_references_slide(next_id, citation_pool_path))

    # v0.3.2.1: populate `position` fields by array index. The downstream
    # revise loop (Stream A) needs these to perform surgical insertion
    # via _insert_slide_into_spec; without them, A1's fallback chain runs
    # for every revision. Use 1-based indexing to match human-readable
    # slide numbering ("slide 1, slide 2, ...").
    for idx, slide in enumerate(slides, start=1):
        slide["position"] = idx

    # Build the top-level spec object
    spec = {
        "schema_version": slide_spec.SCHEMA_VERSION,
        "project_id": args.project_id,
        "mode": args.mode,
        "audience": args.audience,
        "tier": args.tier,
        "throughline": throughline,
        "substories": substories,
        "slides": slides,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"  -> merged {len(slides)} slides "
          f"({len(intro_slides)} intro + per-substory across "
          f"{len(substories)} substories)", file=sys.stderr)
    if n_notes_injected > 0:
        print(f"  -> injected speaker_notes on {n_notes_injected} slide(s)",
              file=sys.stderr)
    if n_notes_derived > 0:
        print(f"  -> v0.4 fused notes: derived {n_notes_derived} "
              f"{{sid}}_notes.json file(s) for the adversarial reviewer",
              file=sys.stderr)
    if image_manifest is not None:
        print(f"  -> image-manifest: bound {n_images_bound} approved image(s); "
              f"dropped {n_slides_dropped} rejected/skipped slide(s)",
              file=sys.stderr)
    print(f"     wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
