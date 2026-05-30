"""Unit tests for v0.7 Tier D.2 — approval-count cap in stage_image_gen
(per D-088).

D-088 widens image-gen eligibility to claim_evidence slides with >=3
distinct bullets (alongside the existing concept_illustration scope).
With the wider eligibility, an approval-count cap bounds visual
density independently of the existing dollar cap. The cap is
implemented in the orchestrator's stage_image_gen loop because that's
where the per-slide approval counter (`n_approved`) lives + where
the budget check pre-flight already runs.

These tests are source-level pins on the orchestrator (no live
subprocess) — the actual cap behavior is tested via the bash
function extraction pattern used by other orchestrator tests.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


# ---------------------------------------------------------------------------
# Defaults + CLI flag
# ---------------------------------------------------------------------------

def test_max_image_approvals_default_is_4():
    """Per D-088: default cap is 4 approvals per deck."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the default-init line. Use an anchored match so we hit
    # the variable initializer, not the comment block.
    m = re.search(r"^MAX_IMAGE_APPROVALS=(\d+)", text, re.MULTILINE)
    assert m is not None, "MAX_IMAGE_APPROVALS default not found"
    assert int(m.group(1)) == 4, (
        f"D-088 specifies default cap=4 approvals/deck; "
        f"orchestrator initializes to {m.group(1)}")


def test_cli_flag_max_image_approvals_documented_in_usage():
    """`--help` output documents the new flag so operators discover
    the cap (and the disable mechanism = 0)."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--max-image-approvals" in help_text, (
        "--help must document --max-image-approvals")
    # The D-088 attribution + the "0 disables" mechanism both visible
    assert "D-088" in help_text or "approval" in help_text.lower()


def test_cli_flag_max_image_approvals_parsed():
    """The arg-parser case statement recognizes --max-image-approvals
    and assigns to MAX_IMAGE_APPROVALS."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "--max-image-approvals)" in text, (
        "arg-parser missing --max-image-approvals case")
    # Should assign to MAX_IMAGE_APPROVALS variable
    parser_line = [
        line for line in text.splitlines()
        if "--max-image-approvals)" in line
    ][0]
    assert "MAX_IMAGE_APPROVALS=" in parser_line


# ---------------------------------------------------------------------------
# Cap check inside stage_image_gen loop
# ---------------------------------------------------------------------------

def _extract_stage_image_gen_body(text: str) -> str:
    """Extract stage_image_gen's body. The function contains nested
    heredocs (cat > stub files inside helper calls), so reuse the
    same heredoc-aware extraction pattern from Tier A.2's
    test_orchestrator_resume_cascade.py."""
    start = text.find("stage_image_gen() {")
    if start < 0:
        raise AssertionError("stage_image_gen function missing")
    lines = text[start:].splitlines(keepends=True)
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


def test_cap_check_references_max_image_approvals():
    """The cap check inside the loop must read MAX_IMAGE_APPROVALS."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    # Look for the cap-check guard pattern
    assert "MAX_IMAGE_APPROVALS" in body, (
        "stage_image_gen must check MAX_IMAGE_APPROVALS for the "
        "D-088 Tier D.2 approval-count cap")


def test_cap_check_compares_against_n_approved():
    """The cap check must compare against the n_approved counter
    (which is the orchestrator-local approval tally)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    # The guard pattern: "$n_approved" -ge "$MAX_IMAGE_APPROVALS"
    assert re.search(
        r'"\$n_approved"\s*-ge\s*"\$MAX_IMAGE_APPROVALS"',
        body), (
            "stage_image_gen must compare n_approved >= MAX_IMAGE_APPROVALS "
            "to enforce the cap")


def test_cap_zero_disables_the_check():
    """MAX_IMAGE_APPROVALS=0 disables the cap (so the dollar cap is
    the only limit, preserving pre-D-088 behavior for operators
    that explicitly opt out)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    # The guard must short-circuit when MAX_IMAGE_APPROVALS <= 0
    # so the cap is disabled
    assert re.search(
        r'"\$MAX_IMAGE_APPROVALS"\s*-gt\s*0',
        body), (
            "stage_image_gen cap check must include MAX_IMAGE_APPROVALS > 0 "
            "so 0 disables the cap (preserves pre-D-088 behavior)")


def test_cap_check_runs_after_budget_check():
    """The approval-count cap is checked AFTER the budget cap
    (so a slide skipped for budget reasons doesn't also count
    toward the approval cap's drain logic). Pin the order."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    budget_pos = body.find("budget exhausted")
    cap_pos = body.find("approval cap")
    assert budget_pos > 0 and cap_pos > 0
    assert budget_pos < cap_pos, (
        "the budget check must precede the approval-count cap in the "
        "loop body (so a budget-exhausted skip doesn't also drain the "
        "approval queue)")


def test_cap_emits_record_skipped_for_capped_slides():
    """When the cap trips, the orchestrator records a skip for the
    current slide AND drains the remaining queue with skips (so
    the manifest stays complete + downstream stages don't think
    those slides were just dropped)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    # The cap block must reference record-skipped (the orchestrator
    # subcommand that writes a skip record to the image manifest)
    cap_section_start = body.find("approval cap")
    assert cap_section_start > 0
    cap_section = body[cap_section_start:cap_section_start + 2000]
    # record-skipped invoked at least twice: once for the current
    # slide, once inside the drain loop
    n_record_skipped = cap_section.count("record-skipped")
    assert n_record_skipped >= 2, (
        f"cap block must record-skipped both the current slide AND "
        f"drain remaining queue; got {n_record_skipped} calls")


def test_cap_block_breaks_out_of_per_slide_loop():
    """After draining the remaining queue, the cap block breaks out
    of the per-slide while loop (otherwise we'd try to evaluate
    more slides after the cap)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    cap_section_start = body.find("approval cap")
    cap_section = body[cap_section_start:cap_section_start + 2000]
    assert "\n      break\n" in cap_section, (
        "cap block must `break` out of the per-slide loop after "
        "draining; otherwise the loop continues evaluating slides "
        "after the cap was hit")


def test_cap_cites_d088_in_skip_reason():
    """The skip reason recorded in the manifest cites D-088 so
    post-mortem operators understand why the slide was skipped."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_image_gen_body(text)
    cap_section_start = body.find("approval cap")
    cap_section = body[cap_section_start:cap_section_start + 2000]
    assert "D-088" in cap_section, (
        "cap-block skip records must cite D-088 in the reason field "
        "so the manifest carries the rationale forward")
