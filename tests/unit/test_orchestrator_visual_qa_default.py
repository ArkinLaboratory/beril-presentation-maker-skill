"""Tests for v0.8 Tier D orchestrator wiring: mode-aware visual-QA
default-on for STRONG talk-30/talk-15 runs + --no-visual-qa opt-out
(D-096).

Source-level inspection AND runtime exec (via `bash -c` extraction)
mirrors the test_orchestrator_image_provider.py pattern — extract the
auto-on shell snippet from presentation_maker.sh and run it in a
fresh bash subshell with synthetic MODE/TIER/VISUAL_QA/NO_VISUAL_QA
values; assert the resolved VISUAL_QA value matches D-096's
mode-coverage table.

Decision pin for "BRIEF" tier (per session-time DQ):
  D-096's mode-coverage table mentions `talk-15 BRIEF`, but the
  orchestrator's TIER validator only accepts STRONG/THIN/EXPLORATORY.
  Treated as a stale spec note; auto-on fires when TIER=STRONG AND
  MODE in {talk-30, talk-15}. If BRIEF is added later as a real
  tier, the auto-on guard will need extending.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


# ---------------------------------------------------------------------------
# Source-level pin: --no-visual-qa flag + default-init + auto-on logic
# ---------------------------------------------------------------------------

def test_no_visual_qa_flag_defined_in_parser():
    """Pin presence of --no-visual-qa CLI flag in the argument parser."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "--no-visual-qa)" in text, (
        "v0.8/D-096: --no-visual-qa CLI flag must be defined in the "
        "argument-parser case statement")
    # And it must set NO_VISUAL_QA=1
    assert "NO_VISUAL_QA=1" in text, (
        "--no-visual-qa handler must set NO_VISUAL_QA=1")


def test_no_visual_qa_default_initialized_to_0():
    """Pin the default-init value of NO_VISUAL_QA (must start at 0
    so the auto-on default applies unless operator opts out)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # The init line (must be at the default-block area, near VISUAL_QA=0)
    assert "NO_VISUAL_QA=0" in text, (
        "NO_VISUAL_QA must be initialized to 0 (default-allows-auto-on)")


def test_visual_qa_default_initialized_to_0():
    """Pin VISUAL_QA initial value at 0. The auto-on logic flips it
    to 1 conditionally after MODE+TIER validation."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert re.search(r"^VISUAL_QA=0\b", text, re.MULTILINE), (
        "VISUAL_QA must be initialized to 0; the v0.8/D-096 auto-on "
        "logic flips it conditionally based on MODE+TIER")


def test_auto_on_block_present_after_tier_validation():
    """Pin the mode-aware auto-on block sits AFTER the TIER case
    validation (otherwise an invalid TIER would slip past)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    tier_case_pos = text.find('case "$TIER" in')
    assert tier_case_pos > 0
    auto_on_pos = text.find("v0.8/D-096", tier_case_pos)
    assert auto_on_pos > 0, (
        "v0.8/D-096 auto-on block must appear AFTER `case \"$TIER\" in` "
        "validation so an invalid TIER fails fast before the auto-on "
        "logic runs")


def test_auto_on_block_references_strong_and_audience_modes():
    """The auto-on guard must check TIER=STRONG AND
    (MODE=talk-30 OR MODE=talk-15) — per D-096 mode-coverage table
    (with the in-session DQ: BRIEF tier treated as stale spec note)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Extract the v0.8/D-096 block
    start = text.find("# v0.8/D-096 — mode-aware visual-QA auto-on")
    assert start > 0
    end = text.find("# v0.4 M2:", start)
    block = text[start:end] if end > 0 else text[start:start + 2000]
    assert '"$TIER" == "STRONG"' in block, (
        "auto-on guard must check TIER == STRONG")
    assert '"$MODE" == "talk-30"' in block, (
        "auto-on guard must include talk-30 mode")
    assert '"$MODE" == "talk-15"' in block, (
        "auto-on guard must include talk-15 mode")
    # Must NOT include talk-45 / lightning-5 / poster (those are
    # OFF per D-096 mode-coverage table)
    assert '"$MODE" == "talk-45"' not in block, (
        "auto-on guard must NOT include talk-45 (OFF per D-096)")
    assert '"$MODE" == "lightning-5"' not in block, (
        "auto-on guard must NOT include lightning-5 (OFF per D-096)")


def test_auto_on_block_respects_no_visual_qa_opt_out():
    """The auto-on guard must skip when NO_VISUAL_QA=1 (operator opt-out)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    start = text.find("# v0.8/D-096 — mode-aware visual-QA auto-on")
    assert start > 0
    end = text.find("# v0.4 M2:", start)
    block = text[start:end] if end > 0 else text[start:start + 2000]
    assert '"$NO_VISUAL_QA" -eq 0' in block, (
        "auto-on guard must check NO_VISUAL_QA -eq 0 so "
        "--no-visual-qa suppresses the auto-on default")


# ---------------------------------------------------------------------------
# Help-text pins
# ---------------------------------------------------------------------------

def test_help_documents_no_visual_qa_flag():
    """`--help` must document the new --no-visual-qa flag per D-096."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--no-visual-qa" in help_text, (
        "v0.8/D-096: --help must document the --no-visual-qa flag")
    # And cite the decision so future operators can trace the rationale
    assert "D-096" in help_text, (
        "--help must cite D-096 for the auto-on behavior + opt-out flag")


def test_help_documents_visual_qa_auto_on_default():
    """`--help` for --visual-qa must mention the v0.8 auto-on default
    so operators reading the existing docs don't assume the v0.7
    opt-in-only behavior is still in force."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "AUTO-ON" in help_text or "auto-on" in help_text, (
        "--help must mention auto-on behavior for v0.8/D-096")


# ---------------------------------------------------------------------------
# Runtime auto-on logic via extracted bash snippet
# ---------------------------------------------------------------------------

def _extract_auto_on_block() -> str:
    """Extract the v0.8/D-096 auto-on block from presentation_maker.sh.

    Spans from the `# v0.8/D-096 — mode-aware visual-QA auto-on`
    comment through the closing `fi`. Re-extracting from source keeps
    the test honest — if the snippet moves or the comment is renamed,
    the extractor fails loudly rather than silently testing a stale
    copy."""
    text = ORCH_SH.read_text(encoding="utf-8")
    start_marker = "# v0.8/D-096 — mode-aware visual-QA auto-on"
    end_marker = "# v0.4 M2:"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise AssertionError(
            f"could not locate v0.8/D-096 auto-on block in {ORCH_SH} "
            f"(start={start}, end={end}). Comment markers may have "
            f"been renamed.")
    return text[start:end]


def _run_auto_on(mode: str, tier: str,
                 visual_qa: int = 0,
                 no_visual_qa: int = 0) -> int:
    """Run the auto-on block in a fresh bash subshell with the given
    MODE/TIER/VISUAL_QA/NO_VISUAL_QA values. Returns the RESOLVED
    VISUAL_QA value (0 or 1).
    """
    block = _extract_auto_on_block()
    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        MODE={mode!r}
        TIER={tier!r}
        VISUAL_QA={visual_qa}
        NO_VISUAL_QA={no_visual_qa}
        {block}
        echo "RESOLVED_VISUAL_QA=$VISUAL_QA"
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"auto-on block failed: stderr={result.stderr!r}")
    m = re.search(r"RESOLVED_VISUAL_QA=(\d+)", result.stdout)
    assert m, f"could not parse output: {result.stdout!r}"
    return int(m.group(1))


# D-096 mode-coverage table (BRIEF tier excluded per in-session DQ):
#   talk-30 STRONG → ON
#   talk-30 THIN/EXPLORATORY → OFF
#   talk-15 STRONG → ON
#   talk-15 THIN/EXPLORATORY → OFF
#   talk-45 any → OFF
#   lightning-5 any → OFF


@pytest.mark.parametrize("mode,tier,expected", [
    # Auto-on cases (STRONG + audience-facing modes)
    ("talk-30", "STRONG", 1),
    ("talk-15", "STRONG", 1),
    # Auto-off cases (non-STRONG tier; D-096 keeps OFF)
    ("talk-30", "THIN", 0),
    ("talk-30", "EXPLORATORY", 0),
    ("talk-15", "THIN", 0),
    ("talk-15", "EXPLORATORY", 0),
    # Auto-off cases (non-audience-facing modes; D-096 keeps OFF
    # regardless of tier)
    ("talk-45", "STRONG", 0),
    ("talk-45", "THIN", 0),
    ("lightning-5", "STRONG", 0),
    ("lightning-5", "THIN", 0),
])
def test_auto_on_per_d096_mode_coverage_table(mode, tier, expected):
    """Parametrized over the full D-096 mode/tier matrix (with BRIEF
    excluded per in-session DQ). Resolved VISUAL_QA must match the
    expected default for each combination."""
    resolved = _run_auto_on(mode, tier,
                            visual_qa=0, no_visual_qa=0)
    assert resolved == expected, (
        f"mode={mode}, tier={tier}: expected VISUAL_QA={expected} "
        f"per D-096; got {resolved}")


def test_explicit_visual_qa_forces_on_for_excluded_modes():
    """`--visual-qa` sets VISUAL_QA=1 upstream of the auto-on block;
    the auto-on logic must not flip it back to 0 even for modes where
    the auto-on default is OFF."""
    # lightning-5 STRONG is OFF by default per D-096; --visual-qa
    # should still force ON.
    resolved = _run_auto_on("lightning-5", "STRONG",
                            visual_qa=1, no_visual_qa=0)
    assert resolved == 1, (
        "--visual-qa must force ON even on excluded modes; got "
        f"VISUAL_QA={resolved}")


def test_no_visual_qa_suppresses_auto_on_for_strong_audience_modes():
    """`--no-visual-qa` (NO_VISUAL_QA=1) must suppress the auto-on
    default. Both STRONG audience modes (talk-30, talk-15) must stay
    at VISUAL_QA=0 when NO_VISUAL_QA=1."""
    resolved_30 = _run_auto_on("talk-30", "STRONG",
                               visual_qa=0, no_visual_qa=1)
    assert resolved_30 == 0, (
        f"--no-visual-qa must suppress auto-on for talk-30 STRONG; "
        f"got VISUAL_QA={resolved_30}")
    resolved_15 = _run_auto_on("talk-15", "STRONG",
                               visual_qa=0, no_visual_qa=1)
    assert resolved_15 == 0, (
        f"--no-visual-qa must suppress auto-on for talk-15 STRONG; "
        f"got VISUAL_QA={resolved_15}")


def test_no_visual_qa_no_op_when_default_is_already_off():
    """`--no-visual-qa` is a no-op when the auto-on default doesn't
    fire (lightning-5, talk-45, or non-STRONG tier). Defensive pin
    to ensure the flag doesn't cause subtle behavior changes on
    modes it's not meant to affect."""
    # talk-30 THIN: default is OFF; --no-visual-qa shouldn't change it
    resolved = _run_auto_on("talk-30", "THIN",
                            visual_qa=0, no_visual_qa=1)
    assert resolved == 0
    # lightning-5 STRONG: default is OFF; --no-visual-qa shouldn't change it
    resolved = _run_auto_on("lightning-5", "STRONG",
                            visual_qa=0, no_visual_qa=1)
    assert resolved == 0


def test_auto_on_does_not_re_enable_when_visual_qa_already_1():
    """When VISUAL_QA is already 1 (operator passed --visual-qa), the
    auto-on logic must skip the conditional (it only fires when
    VISUAL_QA -eq 0). Defensive: ensures no double-enable / re-print
    of the auto-on stderr line on a STRONG mode where both --visual-qa
    is set AND the auto-on would have fired."""
    # talk-30 STRONG, but VISUAL_QA already 1 from --visual-qa:
    # resolution stays 1, and the auto-on stderr line must NOT print
    # (we check stderr by running the snippet directly with stderr
    # capture).
    block = _extract_auto_on_block()
    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        MODE="talk-30"
        TIER="STRONG"
        VISUAL_QA=1
        NO_VISUAL_QA=0
        {block}
        echo "RESOLVED_VISUAL_QA=$VISUAL_QA"
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "RESOLVED_VISUAL_QA=1" in result.stdout
    # Auto-on stderr message must NOT appear (the block's outer if
    # gates on VISUAL_QA -eq 0)
    assert "visual-QA auto-on" not in result.stderr, (
        "auto-on stderr line must NOT print when VISUAL_QA is "
        "already 1 (avoids confusing operators who explicitly "
        "passed --visual-qa)")


def test_auto_on_emits_stderr_announcement_when_triggered():
    """When auto-on fires (STRONG + audience mode + not opted-out),
    the orchestrator must emit a stderr line so the operator knows
    visual-QA will run (and what flag to use to skip it next time)."""
    block = _extract_auto_on_block()
    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        MODE="talk-30"
        TIER="STRONG"
        VISUAL_QA=0
        NO_VISUAL_QA=0
        {block}
        echo "RESOLVED_VISUAL_QA=$VISUAL_QA"
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "RESOLVED_VISUAL_QA=1" in result.stdout
    # Verify the operator sees what happened
    assert "visual-QA auto-on" in result.stderr, (
        "auto-on must emit a stderr announcement so operators "
        "understand why visual-QA is running")
    assert "--no-visual-qa" in result.stderr, (
        "auto-on stderr must mention --no-visual-qa as the opt-out "
        "so operators know how to skip it")
