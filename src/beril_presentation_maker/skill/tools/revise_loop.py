#!/usr/bin/env python3
"""revise_loop.py — review-rewrite loop driver for v0.3.0.

Orchestration layer between `audit/adversarial_review.json` (produced by
`beril-adversarial --type presentation`) and the deck's `slide_spec.json`.
For each P0 finding, dispatches to `revise_slide.v1.md` or `add_slide.v1.md`
(via `claude -p`), merges the revised slide back into the deck spec,
re-runs the validator, and emits a `next_actions.md` summary at the end.

Why this lives in Python (not bash):
  - Parsing the review JSON, splitting by class, and updating the slide
    spec all benefit from real types + structured iteration.
  - The bounded-retry + cost-cap semantics are easier to reason about
    in a single function than scattered across bash conditionals.
  - The bash orchestrator (presentation_maker.sh) calls this once via
    subprocess; bash stays focused on stage dispatch + claude -p
    invocation patterns it already handles.

Pipeline (per-loop iteration):
  1. Load adversarial_review.json
  2. Filter findings by severity (P0 by default; configurable)
  3. For each finding:
     a. Look up the original slide in slide_spec.json (by slide_id)
     b. Write a single-finding JSON to <draft_dir>/audit/revisions/F00X.finding.json
     c. Write a single-slide JSON to <draft_dir>/audit/revisions/F00X.slide.json
     d. Invoke `claude -p` with revise_slide.v1 or add_slide.v1
     e. Read the revised/added slide JSON output
     f. Merge back into slide_spec.json (update existing or insert new)
     g. Track cost; halt loop if --max-cost-usd exceeded
  4. Re-run slide_spec.py validate; if fails, surface and abort revisions
     (rollback to pre-loop spec)
  5. Write next_actions.md summarizing P1/P2 findings + revision_log

Bounded retry semantics:
  - Per-slide retry: max 2 attempts per slide_id per loop run. If the
    second attempt's revised slide STILL produces the same finding when
    re-reviewed, we treat the finding as unfixable at this layer and
    surface to next_actions.md.
  - Loop-level cap: max --max-revisions findings revised per run
    (default 6). Beyond this, surface remaining to next_actions.md.
  - Cost cap: --max-cost-usd terminates the loop early if cumulative
    revise/add cost exceeds the budget.

State persistence:
  - <draft_dir>/audit/revisions/ — per-finding artifacts (input + output
    JSON, claude -p stream logs, metadata)
  - <draft_dir>/slide_spec.pre_revise.json — backup of the pre-loop spec
    (rollback target if validator fails)
  - <draft_dir>/audit/revise_loop_metadata.json — cumulative cost,
    findings revised, retries per slide
  - <draft_dir>/next_actions.md — human-readable summary of what was
    fixed + what remains

CLI:
    revise_loop.py <draft_dir> [--review-path PATH]
                   [--severity-floor P0|P1|P2]
                   [--max-revisions N] [--max-cost-usd N.NN]
                   [--model MODEL] [--no-stream]
                   [--dry-run]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Findings of these classes route to revise_slide.v1; everything else
# either routes to add_slide.v1 (missing_slide) or is surfaced-only.
REVISE_CLASSES = (
    "register_drift",
    "claim_evidence",
    "qa_softball",
    "substory_arc",
)
ADD_CLASSES = ("missing_slide",)
# These classes don't have a per-slide fix; surface in next_actions only.
SURFACE_ONLY_CLASSES = (
    "throughline",         # spine-level; substory_design.v1 territory
    "narrative_weakness",  # info-level; speaker awareness, not slide fix
    "unbacked_quantitative",  # check_quantitative_grounding handles this
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """One finding from adversarial_review.json findings[]."""
    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return self.raw.get("id", "F???")

    @property
    def cls(self) -> str:
        return self.raw.get("class", "unknown")

    @property
    def severity(self) -> str:
        return self.raw.get("severity", "P2")

    @property
    def slide_id(self) -> Optional[int]:
        sid = self.raw.get("slide_id")
        return sid if isinstance(sid, int) else None

    @property
    def fix_target(self) -> str:
        return self.raw.get("fix_target", "")

    @property
    def is_revisable(self) -> bool:
        """True if this finding routes to revise_slide.v1."""
        return self.cls in REVISE_CLASSES and self.slide_id is not None

    @property
    def is_addable(self) -> bool:
        """True if this finding routes to add_slide.v1."""
        return self.cls in ADD_CLASSES

    @property
    def is_surface_only(self) -> bool:
        """True if this finding is reported but not actioned by the loop."""
        return self.cls in SURFACE_ONLY_CLASSES or (
            not self.is_revisable and not self.is_addable
        )


@dataclass
class LoopState:
    """Cumulative state across the loop's iteration."""
    findings_revised: list[str] = field(default_factory=list)  # finding ids
    findings_added: list[str] = field(default_factory=list)
    findings_skipped: list[str] = field(default_factory=list)  # surface-only
    findings_failed: list[str] = field(default_factory=list)   # revise/add error
    retries_per_slide: dict[int, int] = field(default_factory=dict)
    cost_usd_cumulative: float = 0.0
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "findings_revised": self.findings_revised,
            "findings_added": self.findings_added,
            "findings_skipped": self.findings_skipped,
            "findings_failed": self.findings_failed,
            "retries_per_slide": {str(k): v for k, v in self.retries_per_slide.items()},
            "cost_usd_cumulative": round(self.cost_usd_cumulative, 4),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _draft_paths(draft_dir: Path, review_path: Optional[Path] = None) -> dict[str, Path]:
    """Build the canonical paths the loop reads/writes.

    v0.3.1: 4-zone layout. Reads from working/, snapshots to
    audit/snapshots/, writes intermediate state to working/, and
    audit metadata to audit/.
    """
    project_dir = draft_dir.parent.parent  # talks/draft_N → ../..
    audit_dir = draft_dir / "audit"
    snapshots_dir = audit_dir / "snapshots"
    revisions_dir = audit_dir / "revisions"
    working_dir = draft_dir / "working"
    narrative_dir = draft_dir / "narrative"
    return {
        "draft_dir": draft_dir,
        "project_dir": project_dir,
        "report": project_dir / "REPORT.md",
        "spec": working_dir / "slide_spec.json",
        # Pre-revise backup is now a snapshot under audit/snapshots/.
        "spec_backup": snapshots_dir / "slide_spec.pre_revise.json",
        "throughline": narrative_dir / "00_throughline.md",
        "substories": narrative_dir / "02_substories.md",
        "citation_pool": working_dir / "citation_pool.json",
        "curated_figures": working_dir / "curated_figures.md",
        "review": review_path or (audit_dir / "adversarial_review.json"),
        "audit_dir": audit_dir,
        "snapshots_dir": snapshots_dir,
        "revisions_dir": revisions_dir,
        "metadata": audit_dir / "revise_loop_metadata.json",
        "next_actions": working_dir / "next_actions.md",
    }


def _now_iso() -> str:
    return (datetime.now(timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


# ---------------------------------------------------------------------------
# Spec read/write helpers
# ---------------------------------------------------------------------------

def _load_spec(spec_path: Path) -> dict[str, Any]:
    return json.loads(spec_path.read_text(encoding="utf-8"))


def _save_spec(spec: dict[str, Any], spec_path: Path) -> None:
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")


def _find_slide_in_spec(spec: dict[str, Any], slide_id: int) -> Optional[dict[str, Any]]:
    for s in spec.get("slides", []):
        if s.get("id") == slide_id:
            return s
    return None


def _replace_slide_in_spec(spec: dict[str, Any],
                           slide_id: int,
                           new_slide: dict[str, Any]) -> bool:
    """Replace the slide with id=slide_id in spec.slides[] with new_slide.
    Preserves ordering. Returns True on success."""
    for i, s in enumerate(spec.get("slides", [])):
        if s.get("id") == slide_id:
            # Preserve id/position/substory_id (revise_slide.v1 should already
            # do this, but defense in depth)
            new_slide["id"] = slide_id
            if "position" not in new_slide and "position" in s:
                new_slide["position"] = s["position"]
            if "substory_id" not in new_slide and "substory_id" in s:
                new_slide["substory_id"] = s["substory_id"]
            spec["slides"][i] = new_slide
            return True
    return False


def _insert_slide_into_spec(spec: dict[str, Any],
                            new_slide: dict[str, Any],
                            position: int) -> int:
    """Insert new_slide at the given position. Subsequent slides shift +1.
    Assigns the next-available id. Returns the assigned id.

    v0.3.1 wrinkle A1 fix: when existing slides lack `position` fields
    (the `merge_compose_fragments.py` output is array-ordered but does
    not always populate `position`), the original "find insertion idx by
    comparing positions" loop fell through to "append at end" silently.
    Live test draft_10 F003: new slide had position=9, but it landed at
    end-of-deck (~position 27) because no existing slide had position
    populated.

    Fallback chain:
      1. If any existing slides have integer position fields → use the
         position-comparison path (original behavior; works when merge
         emits positions).
      2. Else if new_slide has substory_id → find the substory's last
         slide by array order and insert immediately after it.
      3. Else if 1 ≤ position ≤ len(slides) → use position as a literal
         array index (caller-trusts-the-position interpretation).
      4. Else → append at end with stderr warning surfacing the drift.
    """
    slides = spec.get("slides", [])
    # Next-available id = max existing + 1
    existing_ids = [s.get("id", 0) for s in slides if isinstance(s.get("id"), int)]
    next_id = max(existing_ids) + 1 if existing_ids else 1
    new_slide["id"] = next_id

    # Detect whether existing slides have positions populated.
    has_positions = any(isinstance(s.get("position"), int) for s in slides)

    insert_idx: Optional[int] = None
    fallback_reason = ""

    if has_positions:
        # Path 1: original position-comparison logic.
        insert_idx = len(slides)
        for i, s in enumerate(slides):
            if s.get("position", -1) >= position:
                insert_idx = i
                break
    else:
        # Path 2: substory_id-anchored fallback.
        target_substory = new_slide.get("substory_id")
        if target_substory:
            last_match = None
            for i, s in enumerate(slides):
                if s.get("substory_id") == target_substory:
                    last_match = i
            if last_match is not None:
                insert_idx = last_match + 1
                fallback_reason = (
                    f"siblings lack position fields; anchored after last "
                    f"slide of substory {target_substory!r} (idx {last_match})"
                )

        # Path 3: position-as-array-index.
        if insert_idx is None and isinstance(position, int) and 1 <= position <= len(slides):
            insert_idx = position - 1  # position is 1-based; idx is 0-based
            fallback_reason = (
                f"siblings lack position fields and substory_id anchor "
                f"failed; using position {position} as array index"
            )

        # Path 4: append-at-end with warning.
        if insert_idx is None:
            insert_idx = len(slides)
            fallback_reason = (
                f"siblings lack position fields, substory_id anchor failed, "
                f"position {position} out of array range — appending at end "
                f"(this drifts from the finding's intended position)"
            )

    if fallback_reason:
        print(f"  [revise_loop] _insert_slide_into_spec fallback: "
              f"{fallback_reason}", file=sys.stderr)

    # Shift positions of subsequent slides (only meaningful when
    # has_positions is True; otherwise this is a no-op).
    for s in slides[insert_idx:]:
        if isinstance(s.get("position"), int):
            s["position"] += 1

    slides.insert(insert_idx, new_slide)
    return next_id


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------

def _resolve_python_bin() -> Path:
    """Resolve the Python interpreter the orchestrator uses (mirrors
    presentation_maker.sh's discover_python_bin)."""
    # When invoked from the orchestrator, BERIL_PRESENTATION_MAKER_PYTHON
    # is set. Fall back to sys.executable.
    env_py = os.environ.get("BERIL_PRESENTATION_MAKER_PYTHON")
    if env_py and Path(env_py).is_file():
        return Path(env_py)
    return Path(sys.executable)


def _resolve_prompts_dir() -> Path:
    """Locate the shipped prompts/ dir."""
    # When this module is bundled in the package, prompts live alongside
    # tools/ at ../prompts.
    here = Path(__file__).resolve().parent
    prompts = here.parent / "prompts"
    if not prompts.is_dir():
        raise FileNotFoundError(
            f"prompts/ directory not found at {prompts}. "
            "revise_loop.py must run from a deployed skill tree."
        )
    return prompts


def _invoke_claude(system_prompt_path: Path,
                   user_prompt: str,
                   expected_write_path: Path,
                   *,
                   model: str,
                   stream: bool,
                   metadata_out: Path,
                   stream_log: Path,
                   label: str,
                   tools_dir: Path) -> tuple[int, float]:
    """Invoke `claude -p` for a revise/add prompt.

    Returns (exit_code, cost_usd). Cost is parsed from the stream-progress
    metadata if --stream is on; falls back to 0 if not.

    Mirrors presentation_maker.sh's invoke_claude_with_retry pattern but
    is called from Python instead of bash. Single attempt per call; the
    loop driver handles retries.
    """
    if shutil.which("claude") is None:
        print("error: 'claude' CLI not on PATH", file=sys.stderr)
        return 3, 0.0

    sys_prompt_text = system_prompt_path.read_text(encoding="utf-8")
    metadata_out.parent.mkdir(parents=True, exist_ok=True)

    if stream:
        stream_progress_py = tools_dir / "stream_progress.py"
        if not stream_progress_py.is_file():
            print(f"warning: stream_progress.py not found at {stream_progress_py}; "
                  f"falling back to non-stream mode", file=sys.stderr)
            stream = False

    if stream:
        claude_cmd = [
            "claude", "-p",
            "--model", model,
            "--system-prompt", sys_prompt_text,
            "--allowedTools", "Read,Write,Grep,Glob",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
            user_prompt,
        ]
        env = {**os.environ, "CLAUDECODE": ""}
        claude = subprocess.Popen(
            claude_cmd,
            stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=env,
        )
        parser_cmd = [
            str(_resolve_python_bin()), str(stream_progress_py),
            "--expected-write-path", str(expected_write_path),
            "--log", str(stream_log),
            "--model", model,
            "--metadata-out", str(metadata_out),
            "--label", label,
        ]
        parser = subprocess.Popen(
            parser_cmd,
            stdin=claude.stdout,
            stdout=subprocess.DEVNULL,
        )
        if claude.stdout is not None:
            claude.stdout.close()
        rc = parser.wait()
        claude.wait()
    else:
        rc = subprocess.run(
            [
                "claude", "-p",
                "--model", model,
                "--system-prompt", sys_prompt_text,
                "--allowedTools", "Read,Write,Grep,Glob",
                "--dangerously-skip-permissions",
                user_prompt,
            ],
            stdin=subprocess.DEVNULL,
        ).returncode

    # Parse cost from metadata if available
    cost = 0.0
    if metadata_out.is_file():
        try:
            md = json.loads(metadata_out.read_text(encoding="utf-8"))
            cost = float(md.get("cost_usd", 0.0))
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    return rc, cost


# ---------------------------------------------------------------------------
# Per-finding dispatch
# ---------------------------------------------------------------------------

def _build_user_prompt_revise(finding_path: Path,
                              slide_path: Path,
                              out_path: Path,
                              paths: dict[str, Path],
                              tier: str,
                              today: str) -> str:
    return f"""Run revise_slide.v1 to produce a revised slide content fragment.

## Inputs

- `FINDING_JSON_PATH` = `{finding_path}`
- `SLIDE_JSON_PATH` = `{slide_path}`
- `OUT_PATH` = `{out_path}`
- `THROUGHLINE_PATH` = `{paths['throughline']}`
- `SUBSTORY_PATH` = `{paths['substories']}`
- `REPORT_PATH` = `{paths['report']}`
- `CITATION_POOL_PATH` = `{paths['citation_pool']}`
- `TIER` = `{tier}`
- `TODAY` = `{today}`

Read the inputs in the order specified by your system prompt. Verify
the reviewer's report_evidence against REPORT.md. Apply the per-class
revision guidance. Run the discipline + self-review passes. Write
OUT_PATH via the Write tool. Emit the closing-message template."""


def _build_user_prompt_add(finding_path: Path,
                           out_path: Path,
                           paths: dict[str, Path],
                           tier: str,
                           today: str) -> str:
    return f"""Run add_slide.v1 to produce a new slide content fragment.

## Inputs

- `FINDING_JSON_PATH` = `{finding_path}`
- `OUT_PATH` = `{out_path}`
- `SLIDE_SPEC_PATH` = `{paths['spec']}`
- `THROUGHLINE_PATH` = `{paths['throughline']}`
- `SUBSTORY_PATH` = `{paths['substories']}`
- `REPORT_PATH` = `{paths['report']}`
- `CITATION_POOL_PATH` = `{paths['citation_pool']}`
- `CURATED_FIGURES_PATH` = `{paths['curated_figures']}`
- `TIER` = `{tier}`
- `TODAY` = `{today}`

Read inputs in order. Verify report_evidence. Determine layout +
position + substory_id. Compose content per the discipline. Write
OUT_PATH. Emit the closing-message template."""


def _process_finding(finding: Finding,
                     spec: dict[str, Any],
                     paths: dict[str, Path],
                     state: LoopState,
                     *,
                     tier: str,
                     model: str,
                     stream: bool,
                     prompts_dir: Path,
                     tools_dir: Path,
                     dry_run: bool) -> str:
    """Process one finding. Returns one of:
      - "revised" — revise_slide ran successfully and merged
      - "added"   — add_slide ran successfully and merged
      - "skipped" — finding is surface-only (P1/P2/info or unsupported class)
      - "failed"  — revise/add failed; surface to next_actions
      - "retried_failed" — second retry also failed; mark unfixable
    """
    revisions_dir = paths["revisions_dir"]
    revisions_dir.mkdir(parents=True, exist_ok=True)
    finding_path = revisions_dir / f"{finding.id}.finding.json"
    out_path = revisions_dir / f"{finding.id}.revised_slide.json"
    metadata_out = revisions_dir / f"{finding.id}.metadata.json"
    stream_log = revisions_dir / f"{finding.id}.stream.log"

    # Write the finding to a single-finding JSON file
    finding_path.write_text(
        json.dumps(finding.raw, indent=2) + "\n", encoding="utf-8")

    today = _now_iso().split("T")[0]

    # Surface-only classes
    if finding.is_surface_only:
        state.findings_skipped.append(finding.id)
        return "skipped"

    if finding.is_addable:
        if dry_run:
            print(f"  [dry-run] would invoke add_slide.v1 for {finding.id}",
                  file=sys.stderr)
            state.findings_added.append(finding.id)
            return "added"
        prompt_path = prompts_dir / "add_slide.v1.md"
        user_prompt = _build_user_prompt_add(
            finding_path, out_path, paths, tier, today)
        rc, cost = _invoke_claude(
            prompt_path, user_prompt, out_path,
            model=model, stream=stream, metadata_out=metadata_out,
            stream_log=stream_log, label=f"add_slide-{finding.id}",
            tools_dir=tools_dir)
        state.cost_usd_cumulative += cost
        if rc != 0 or not out_path.is_file():
            state.findings_failed.append(finding.id)
            return "failed"
        try:
            new_slide = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state.findings_failed.append(finding.id)
            return "failed"
        position = new_slide.get("position", len(spec.get("slides", [])))
        _insert_slide_into_spec(spec, new_slide, position)
        state.findings_added.append(finding.id)
        return "added"

    if finding.is_revisable:
        slide_id = finding.slide_id
        slide_obj = _find_slide_in_spec(spec, slide_id)  # type: ignore[arg-type]
        if slide_obj is None:
            state.findings_failed.append(finding.id)
            return "failed"
        slide_path = revisions_dir / f"{finding.id}.slide.json"
        slide_path.write_text(
            json.dumps(slide_obj, indent=2) + "\n", encoding="utf-8")

        # Retry tracking
        retries = state.retries_per_slide.get(slide_id, 0)
        if retries >= 2:
            state.findings_failed.append(finding.id)
            return "retried_failed"

        if dry_run:
            print(f"  [dry-run] would invoke revise_slide.v1 for {finding.id} "
                  f"(slide_id={slide_id}, retry={retries})", file=sys.stderr)
            state.findings_revised.append(finding.id)
            state.retries_per_slide[slide_id] = retries + 1
            return "revised"
        prompt_path = prompts_dir / "revise_slide.v1.md"
        user_prompt = _build_user_prompt_revise(
            finding_path, slide_path, out_path, paths, tier, today)
        rc, cost = _invoke_claude(
            prompt_path, user_prompt, out_path,
            model=model, stream=stream, metadata_out=metadata_out,
            stream_log=stream_log, label=f"revise_slide-{finding.id}",
            tools_dir=tools_dir)
        state.cost_usd_cumulative += cost
        if rc != 0 or not out_path.is_file():
            state.findings_failed.append(finding.id)
            state.retries_per_slide[slide_id] = retries + 1
            return "failed"
        try:
            new_slide = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state.findings_failed.append(finding.id)
            state.retries_per_slide[slide_id] = retries + 1
            return "failed"
        if not _replace_slide_in_spec(spec, slide_id, new_slide):  # type: ignore[arg-type]
            state.findings_failed.append(finding.id)
            return "failed"
        state.findings_revised.append(finding.id)
        state.retries_per_slide[slide_id] = retries + 1
        return "revised"

    # Fallthrough — finding doesn't route anywhere
    state.findings_skipped.append(finding.id)
    return "skipped"


# ---------------------------------------------------------------------------
# Validator gate
# ---------------------------------------------------------------------------

def _validate_spec(spec_path: Path, tools_dir: Path) -> tuple[bool, str]:
    """Run slide_spec.py validate against the spec. Returns (ok, message)."""
    py = _resolve_python_bin()
    slide_spec_tool = tools_dir / "slide_spec.py"
    if not slide_spec_tool.is_file():
        return False, f"slide_spec.py not found at {slide_spec_tool}"
    result = subprocess.run(
        [str(py), str(slide_spec_tool), "validate", str(spec_path)],
        capture_output=True, text=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


# ---------------------------------------------------------------------------
# next_actions.md
# ---------------------------------------------------------------------------

def _render_next_actions(review: dict[str, Any],
                         state: LoopState,
                         paths: dict[str, Path]) -> str:
    """Human-readable summary of what was fixed and what remains."""
    findings = review.get("findings", [])
    by_id = {f.get("id"): f for f in findings}

    lines = []
    lines.append("# Next Actions")
    lines.append("")
    lines.append(f"**Reviewer:** beril-adversarial --type presentation "
                 f"({review.get('reviewer_model', '?')})")
    lines.append(f"**Reviewed at:** {review.get('reviewed_at', '?')}")
    lines.append(f"**Loop run:** {state.started_at} → {state.finished_at}")
    lines.append(f"**Total findings:** {len(findings)}")
    lines.append(f"**Revised:** {len(state.findings_revised)} "
                 f"({', '.join(state.findings_revised) or 'none'})")
    lines.append(f"**Added:** {len(state.findings_added)} "
                 f"({', '.join(state.findings_added) or 'none'})")
    lines.append(f"**Skipped (surface-only):** {len(state.findings_skipped)}")
    lines.append(f"**Failed (manual fix needed):** {len(state.findings_failed)}")
    lines.append(f"**Cost:** ~${state.cost_usd_cumulative:.2f}")
    lines.append("")

    # Section 1: what was fixed
    if state.findings_revised or state.findings_added:
        lines.append("## Fixed by the loop")
        lines.append("")
        for fid in state.findings_revised + state.findings_added:
            f = by_id.get(fid, {})
            sev = f.get("severity", "?")
            cls = f.get("class", "?")
            slide_id = f.get("slide_id", "n/a")
            issue = f.get("issue", "")[:160]
            lines.append(f"- **{fid}** ({sev} {cls}, slide {slide_id}): {issue}...")
        lines.append("")

    # Section 2: failed (need manual attention)
    if state.findings_failed:
        lines.append("## Failed automatic revision (manual fix needed)")
        lines.append("")
        for fid in state.findings_failed:
            f = by_id.get(fid, {})
            sev = f.get("severity", "?")
            cls = f.get("class", "?")
            slide_id = f.get("slide_id", "n/a")
            issue = f.get("issue", "")
            fix_hint = f.get("fix_hint", "")
            lines.append(f"- **{fid}** ({sev} {cls}, slide {slide_id}):")
            lines.append(f"  - **Issue:** {issue}")
            if fix_hint:
                lines.append(f"  - **Suggested fix:** {fix_hint}")
            lines.append(f"  - **Action:** open slide_spec.json, locate slide_id="
                         f"{slide_id}, apply the fix manually, then re-run "
                         f"`beril-presentation-maker assemble`.")
        lines.append("")

    # Section 3: surface-only (P1/P2 + info)
    surface = [by_id[fid] for fid in state.findings_skipped if fid in by_id]
    by_severity = {"P0": [], "P1": [], "P2": [], "info": []}
    for f in surface:
        by_severity.setdefault(f.get("severity", "?"), []).append(f)

    for sev in ("P1", "P2", "info"):
        if not by_severity.get(sev):
            continue
        label = {"P1": "P1 — quality regressions",
                 "P2": "P2 — polish",
                 "info": "Info — speaker awareness"}[sev]
        lines.append(f"## {label}")
        lines.append("")
        for f in by_severity[sev]:
            cls = f.get("class", "?")
            slide_id = f.get("slide_id", "n/a")
            issue = f.get("issue", "")
            lines.append(f"- **{f.get('id')}** ({cls}, slide {slide_id}): {issue}")
        lines.append("")

    # Section 4: deck's biggest narrative weakness
    nw = [f for f in findings if f.get("class") == "narrative_weakness"]
    if nw:
        lines.append("## The deck's biggest narrative weakness")
        lines.append("")
        for f in nw:
            lines.append(f.get("issue", ""))
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Top-level loop
# ---------------------------------------------------------------------------

def run_revise_loop(draft_dir: Path,
                    *,
                    review_path: Optional[Path] = None,
                    severity_floor: str = "P0",
                    max_revisions: int = 6,
                    max_cost_usd: float = 5.00,
                    model: str = "claude-sonnet-4-20250514",
                    stream: bool = True,
                    dry_run: bool = False) -> dict[str, Any]:
    """Top-level entry point. Returns metadata dict."""
    paths = _draft_paths(draft_dir, review_path)

    if not paths["spec"].is_file():
        raise FileNotFoundError(f"slide_spec.json not found at {paths['spec']}")
    if not paths["review"].is_file():
        raise FileNotFoundError(
            f"adversarial_review.json not found at {paths['review']}. "
            f"Run `beril-adversarial --type presentation {draft_dir}` first.")

    review = json.loads(paths["review"].read_text(encoding="utf-8"))
    spec = _load_spec(paths["spec"])

    # Backup pre-loop spec
    paths["spec_backup"].write_text(
        json.dumps(spec, indent=2) + "\n", encoding="utf-8")

    state = LoopState(started_at=_now_iso())
    tier = review.get("tier", "STRONG")
    prompts_dir = _resolve_prompts_dir()
    tools_dir = Path(__file__).resolve().parent

    sev_order = {"P0": 0, "P1": 1, "P2": 2, "info": 3}
    floor = sev_order.get(severity_floor, 0)

    findings_to_process = []
    for raw in review.get("findings", []):
        f = Finding(raw=raw)
        if sev_order.get(f.severity, 99) <= floor:
            findings_to_process.append(f)
        else:
            state.findings_skipped.append(f.id)

    print(f"  loop: processing {len(findings_to_process)} findings at "
          f"severity-floor={severity_floor}", file=sys.stderr)

    revisions_attempted = 0
    # Save the initial pre-revise spec to disk so the validator-gate
    # below has something to validate against per-finding.
    _save_spec(spec, paths["spec"])

    for finding in findings_to_process:
        if revisions_attempted >= max_revisions:
            print(f"  loop: hit max-revisions cap ({max_revisions}); "
                  f"surfacing remaining findings", file=sys.stderr)
            for f in findings_to_process[revisions_attempted:]:
                state.findings_skipped.append(f.id)
            break
        if state.cost_usd_cumulative >= max_cost_usd:
            print(f"  loop: hit max-cost-usd cap (${max_cost_usd}); "
                  f"surfacing remaining findings", file=sys.stderr)
            for f in findings_to_process[revisions_attempted:]:
                state.findings_skipped.append(f.id)
            break

        # 2026-04-29 v0.3.0 patch: per-finding validation + rollback.
        # Snapshot the spec BEFORE this finding's revision. If the
        # revision produces an invalid spec, rollback ONLY this finding's
        # change instead of nuking all prior valid revisions.
        spec_before_finding = copy.deepcopy(spec)

        result = _process_finding(
            finding, spec, paths, state,
            tier=tier, model=model, stream=stream,
            prompts_dir=prompts_dir, tools_dir=tools_dir,
            dry_run=dry_run)
        revisions_attempted += 1
        print(f"  finding {finding.id} ({finding.severity} {finding.cls}): "
              f"{result}; cost ~${state.cost_usd_cumulative:.2f}",
              file=sys.stderr)

        # Per-finding validate + rollback. Skip in dry-run (no real changes).
        if not dry_run and result in ("revised", "added"):
            _save_spec(spec, paths["spec"])
            ok, msg = _validate_spec(paths["spec"], tools_dir)
            if not ok:
                print(f"  finding {finding.id}: post-revise validation FAILED",
                      file=sys.stderr)
                # Truncate + indent the validator message for readability
                for line in msg.splitlines()[:10]:
                    print(f"    {line}", file=sys.stderr)
                print(f"  finding {finding.id}: rolling back THIS revision; "
                      f"prior revisions preserved", file=sys.stderr)
                # Rollback in-memory + on-disk spec
                spec.clear()
                spec.update(spec_before_finding)
                _save_spec(spec, paths["spec"])
                # Move the finding from revised/added → failed
                if finding.id in state.findings_revised:
                    state.findings_revised.remove(finding.id)
                if finding.id in state.findings_added:
                    state.findings_added.remove(finding.id)
                state.findings_failed.append(finding.id)

    state.finished_at = _now_iso()

    # Write metadata + next_actions
    paths["metadata"].write_text(
        json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    paths["next_actions"].write_text(
        _render_next_actions(review, state, paths), encoding="utf-8")

    return state.to_dict()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="revise_loop.py",
        description=__doc__.split("\n\n")[0] if __doc__ else "",
    )
    p.add_argument("draft_dir", type=Path,
                   help="Path to talks/draft_N/ containing slide_spec.json + audit/adversarial_review.json")
    p.add_argument("--review-path", type=Path, default=None,
                   help="Override audit/adversarial_review.json path")
    p.add_argument("--severity-floor", choices=["P0", "P1", "P2"], default="P0",
                   help="Process findings at this severity and above (default: P0)")
    p.add_argument("--max-revisions", type=int, default=6,
                   help="Max findings to process per loop run (default: 6)")
    p.add_argument("--max-cost-usd", type=float, default=5.00,
                   help="Cost cap; loop terminates early if exceeded (default: $5.00)")
    p.add_argument("--model", default="claude-sonnet-4-20250514",
                   help="Claude model for revise/add prompts")
    p.add_argument("--no-stream", action="store_true",
                   help="Disable stream_progress.py wrapper")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't invoke claude; just plan dispatch")
    args = p.parse_args(argv)

    try:
        meta = run_revise_loop(
            args.draft_dir,
            review_path=args.review_path,
            severity_floor=args.severity_floor,
            max_revisions=args.max_revisions,
            max_cost_usd=args.max_cost_usd,
            model=args.model,
            stream=not args.no_stream,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # Exit 0 if at least one revision landed AND validation passed
    # Exit 1 if no revisions landed (still wrote next_actions but nothing fixed)
    if meta["findings_revised"] or meta["findings_added"]:
        return 0
    if meta["findings_failed"]:
        return 1
    return 0  # all surface-only — nothing failed


if __name__ == "__main__":
    sys.exit(main())
