"""Tests for v0.8 Tier G.6: orchestrator's revise-loop severity-floor
default is P1 (was P0 in v0.7).

Live discovery on draft_11 2026-06-01: orchestrator hard-pinned
`--severity-floor P0` when invoking revise_loop.py, so only P0
findings reached the loop. The single P0 (F001) had class
unbacked_quantitative which is SURFACE_ONLY by design → all 11
findings ended in `state.findings_skipped`, zero revisions applied.

Fix: extract severity floor to a configurable orchestrator variable
REVISE_SEVERITY_FLOOR defaulting to P1, add --revise-severity-floor
CLI flag, validate via case statement, document in --help.

Source-level pins only — runtime exec would require a real
revise_loop invocation against synthetic adversarial output, more
complex than necessary for this regression guard.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def test_revise_severity_floor_default_is_p1():
    """v0.8 Tier G.6: default severity floor is P1, not P0.

    Pin so a future change to the default surfaces in code review.
    """
    text = ORCH_SH.read_text(encoding="utf-8")
    # The default-init line should set REVISE_SEVERITY_FLOOR=P1
    assert re.search(r"^REVISE_SEVERITY_FLOOR=P1\b", text, re.MULTILINE), (
        "REVISE_SEVERITY_FLOOR must default to P1 per v0.8 Tier G.6 "
        "(was hard-pinned P0 in v0.7; live discovery on draft_11 "
        "showed P0-only filtering skipped all revisable P1 findings)")


def test_revise_severity_floor_passed_to_revise_loop():
    """Orchestrator must pass the variable to revise_loop.py, not the
    hard-coded P0 string. Pin so a future refactor that re-hardcodes
    P0 breaks a test, not a draft."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Must NOT contain `--severity-floor P0` as a literal anywhere in
    # the revise_loop invocation (the only literal P0 should be in
    # the help docs or comments, which aren't shell-executed).
    revise_invoke = re.search(
        r'"\$TOOLS_DIR/revise_loop\.py"[^\n]*\n(?:[^\n]*\n){0,8}',
        text,
    )
    assert revise_invoke is not None, (
        "could not find revise_loop.py invocation block in orchestrator")
    block = revise_invoke.group(0)
    assert '--severity-floor "$REVISE_SEVERITY_FLOOR"' in block, (
        "revise_loop invocation must use the configurable "
        "REVISE_SEVERITY_FLOOR variable, not a hard-coded value")
    assert "--severity-floor P0" not in block, (
        "v0.7's hard-pinned `--severity-floor P0` must be gone "
        "(blocks all revisions on cycles whose only P0 is surface-only)")


def test_revise_severity_floor_flag_parses():
    """--revise-severity-floor CLI flag is in the case statement."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "--revise-severity-floor)" in text, (
        "v0.8 Tier G.6: --revise-severity-floor flag must be in the "
        "argument parser case statement")
    # Must set the right variable
    assert (
        '--revise-severity-floor) REVISE_SEVERITY_FLOOR="$2"' in text
    ), "flag handler must set REVISE_SEVERITY_FLOOR=$2"


def test_revise_severity_floor_validated():
    """Invalid values must be rejected via case-statement validation."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Look for the validation block: case "$REVISE_SEVERITY_FLOOR" in P0|P1|P2
    validation = re.search(
        r'case "\$REVISE_SEVERITY_FLOOR" in[^\n]*\n[^\n]*P0\|P1\|P2',
        text,
    )
    assert validation is not None, (
        "REVISE_SEVERITY_FLOOR value must be validated via case "
        "statement (P0|P1|P2 only)")


def test_revise_severity_floor_documented_in_help():
    """--help must document the new flag."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    # Flag entry must appear in the comment-block flag list
    m = re.search(
        r"^#\s+--revise-severity-floor\s",
        help_text, re.MULTILINE,
    )
    assert m is not None, (
        "--revise-severity-floor entry must appear in --help output")
    # Section must mention the v0.8 default change
    section = help_text[m.start():m.start() + 800]
    assert "v0.8 Tier G.6" in section or "default P1" in section, (
        "--help section for --revise-severity-floor must cite "
        "the v0.8 default change so operators understand the "
        "behavior shift from v0.7")


def test_revise_loop_invocation_logs_floor_value():
    """The stderr line announcing revise_loop invocation must include
    the severity-floor value so operators see what's being applied."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # The invocation echo line should mention severity-floor
    echo_line = re.search(
        r'echo "  invoking revise_loop\.py[^\n]*severity-floor[^\n]*\$REVISE_SEVERITY_FLOOR',
        text,
    )
    assert echo_line is not None, (
        "stderr announcement for revise_loop must include the "
        "configured severity-floor value (so operators see what's "
        "being applied on each run)")
