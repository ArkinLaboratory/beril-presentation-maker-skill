"""Tests for v0.8 Tier A orchestrator wiring: stage_curate_figures
runs the per-substory floor + check_curator_figure_floor.py (D-093).

Source-level inspection only — these don't shell-out to the
orchestrator (that's covered by the live smoke harness). The aim is
to pin the wiring so a future refactor that drops --substories-path
or removes the validator-invocation block breaks a test, not the
pipeline. Mirrors the test_orchestrator_resume_cascade.py pattern.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def _extract_stage_curate_body(text: str) -> str:
    """Extract stage_curate_figures function body."""
    fn_start = text.find("stage_curate_figures() {")
    if fn_start < 0:
        raise AssertionError("stage_curate_figures function missing")
    lines = text[fn_start:].splitlines(keepends=True)
    out_lines = [lines[0]]
    in_heredoc = False
    for line in lines[1:]:
        out_lines.append(line)
        if not in_heredoc:
            if "<<EOF" in line:
                in_heredoc = True
            elif line.rstrip("\n") == "}":
                break
        else:
            if line.rstrip("\n") == "EOF":
                in_heredoc = False
    return "".join(out_lines)


# ---------------------------------------------------------------------------
# v0.8 Tier A — per-substory floor wiring (D-093)
# ---------------------------------------------------------------------------

def test_stage_curate_passes_substories_path_when_present():
    """stage_curate_figures must forward --substories-path to
    curate_figures.py when narrative/02_substories.md exists.
    Without this, curate_for_mode's per-substory floor never engages."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_curate_body(text)
    # Stage must reference the substories path
    assert "$NARRATIVE_DIR/02_substories.md" in body, (
        "stage_curate_figures must check for "
        "$NARRATIVE_DIR/02_substories.md to enable the v0.8/D-093 "
        "per-substory floor")
    # Stage must pass the --substories-path flag
    assert "--substories-path" in body, (
        "stage_curate_figures must pass --substories-path to "
        "curate_figures.py per D-093")


def test_stage_curate_substories_check_is_conditional():
    """The substories-path forwarding must be conditional on the file
    existing. Hard-failing when 02_substories.md is missing would
    break the smoke runs + paper-writer-parity fallback path."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_curate_body(text)
    # The conditional must guard the --substories-path block
    assert 'if [[ -f "$NARRATIVE_DIR/02_substories.md" ]]; then' in body, (
        "stage_curate_figures must guard --substories-path on the file "
        "existing; missing 02_substories.md should not break curation")


# ---------------------------------------------------------------------------
# v0.8 Tier A — check_curator_figure_floor.py invocation (D-093)
# ---------------------------------------------------------------------------

def test_stage_curate_invokes_check_curator_figure_floor():
    """After curation, stage_curate_figures must run
    check_curator_figure_floor.py to emit audit/curator_figure_floor.json
    so the cascade reader can lift findings into Tier-1."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_curate_body(text)
    assert "check_curator_figure_floor.py" in body, (
        "stage_curate_figures must invoke check_curator_figure_floor.py "
        "per D-093 to emit audit/curator_figure_floor.json")
    # Required CLI flags
    assert "--substories" in body, (
        "check_curator_figure_floor.py invocation must pass "
        "--substories")
    assert "--curated-figures" in body, (
        "check_curator_figure_floor.py invocation must pass "
        "--curated-figures")
    assert "--draft-dir" in body, (
        "check_curator_figure_floor.py invocation must pass --draft-dir "
        "so the audit JSON lands at DRAFT_DIR/audit/curator_figure_floor.json")


def test_check_curator_figure_floor_invocation_is_advisory():
    """The validator invocation must NOT fail the stage; it's
    advisory per D-093. Stage continues on validator non-zero exit
    (mirrors the curate_figures.py error handling already in place)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_curate_body(text)
    # The validator failure branch must echo a warning, not return
    # non-zero from the stage
    cff_pos = body.find("check_curator_figure_floor.py")
    assert cff_pos > 0, "check_curator_figure_floor invocation missing"
    # Look for "warning:" pattern in the body AFTER the cff invocation
    # (the stage's error-handling block)
    after = body[cff_pos:]
    # There should be a `warning: check_curator_figure_floor.py exited` message
    assert "warning: check_curator_figure_floor.py exited" in after, (
        "validator failure must emit a warning, not fail the stage "
        "(advisory P1 per D-093)")


def test_check_curator_figure_floor_invocation_is_conditional_on_inputs():
    """The validator invocation must be guarded on the required
    inputs (02_substories.md + curated_figures.md) existing —
    invoking with missing inputs would emit a useless error.

    Specifically, the invocation must sit inside an `if [[ ... ]]`
    block that tests for BOTH inputs (single combined check; the
    orchestrator uses one `if [[ A && B ]]` pattern, not nested
    conditionals)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_curate_body(text)
    cff_pos = body.find("check_curator_figure_floor.py")
    assert cff_pos > 0
    # Look for an `if [[` line in the body that mentions BOTH
    # 02_substories.md AND $CURATED_FIGURES. The orchestrator
    # uses a single combined-condition guard.
    has_combined_guard = False
    for line in body.splitlines():
        if (line.strip().startswith("if [[")
                and "02_substories.md" in line
                and "$CURATED_FIGURES" in line):
            has_combined_guard = True
            break
    assert has_combined_guard, (
        "expected a single `if [[ ... 02_substories.md ... && ... "
        "$CURATED_FIGURES ... ]]; then` guard immediately preceding "
        "the check_curator_figure_floor.py invocation; without it, "
        "the validator runs with missing inputs and emits useless "
        "errors")


def test_check_curator_figure_floor_prefers_inventory_when_present():
    """When figures_inventory.md exists, the validator invocation
    should pass --inventory so the validator uses the richer-signal
    inventory MD instead of falling back to a filesystem scan."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_curate_body(text)
    assert "figures_inventory.md" in body, (
        "stage_curate_figures should check for figures_inventory.md "
        "to pass --inventory to check_curator_figure_floor.py")
    assert "--inventory" in body, (
        "check_curator_figure_floor.py invocation should accept "
        "--inventory when figures_inventory.md exists")
