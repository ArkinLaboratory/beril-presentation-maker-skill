"""Tests for v0.8 Tier G.7 orchestrator wiring: stage_visual_qa_final
runs after stage_revise_slides and performs the post-revise
visual-QA gate + second revise pass.

Source-level pins only — runtime exec of the full stage would require
a real visual_qa.py invocation against a real .pptx (expensive).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def test_stage_visual_qa_final_function_defined():
    """The stage_visual_qa_final() function must exist in the
    orchestrator."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "stage_visual_qa_final() {" in text, (
        "stage_visual_qa_final function must be defined per Tier G.7")


def test_stage_visual_qa_final_invoked_after_stage_revise_slides():
    """Main-flow dispatch must call stage_visual_qa_final AFTER
    stage_revise_slides (the post-revise visual-QA semantic)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the main-flow block where revise_slides is invoked.
    # stage_visual_qa_final should appear in the same conditional
    # block, AFTER the stage_revise_slides invocation.
    revise_pos = text.rfind("stage_revise_slides ||")
    assert revise_pos > 0, (
        "stage_revise_slides invocation must exist in main flow")
    # stage_visual_qa_final must be invoked NEXT in the same conditional
    vq_final_pos = text.find("stage_visual_qa_final", revise_pos)
    assert vq_final_pos > revise_pos, (
        "stage_visual_qa_final must be invoked AFTER stage_revise_slides "
        "(visual-QA judges the POST-revise deck per Tier G.7)")
    # Check that nothing else intervenes — the two calls should be
    # in the same conditional block. Search for a standalone `fi`
    # keyword between them (lone word on a line, not part of a
    # comment or longer identifier).
    between = text[revise_pos:vq_final_pos]
    has_closing_fi = bool(
        re.search(r"^\s*fi\s*$", between, re.MULTILINE))
    assert not has_closing_fi, (
        "stage_visual_qa_final must be in the SAME conditional block "
        "as stage_revise_slides (must run only when adversarial review "
        "produced findings)")


def test_stage_visual_qa_final_skips_when_visual_qa_disabled():
    """The stage must respect the existing VISUAL_QA flag so
    --no-visual-qa runs don't try to invoke visual_qa.py."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # The stage's body must include a VISUAL_QA -ne 1 short-circuit
    body = _extract_stage_body(text, "stage_visual_qa_final")
    assert '"$VISUAL_QA" -ne 1' in body, (
        "stage_visual_qa_final must skip when VISUAL_QA != 1 "
        "(operator opted out via --no-visual-qa or non-audience mode)")


def test_stage_visual_qa_final_writes_distinct_audit_paths():
    """The final pass must write visual_qa_final.{json,md} so the
    early-warning cascade output at visual_qa.{json,md} isn't
    overwritten."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    assert "visual_qa_final.json" in body, (
        "stage_visual_qa_final must write to visual_qa_final.json "
        "(distinct from the cascade's pre-revise visual_qa.json)")
    assert "--out-json" in body, (
        "stage_visual_qa_final must use visual_qa.py's --out-json flag "
        "to write the final pass's output to a distinct path")


def test_stage_visual_qa_final_invokes_merge_tool():
    """The stage must invoke merge_visual_qa_into_review.py to
    append synthetic adversarial-shape findings before the second
    revise pass."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    assert "merge_visual_qa_into_review.py" in body, (
        "stage_visual_qa_final must invoke the merge tool to fold "
        "visual-QA findings into adversarial_review.json before the "
        "second revise pass")


def test_stage_visual_qa_final_invokes_second_revise_loop():
    """After merging, the stage must invoke revise_loop.py again
    (the 2nd revise pass)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    # Look for the revise_loop.py invocation block inside the stage
    assert "revise_loop.py" in body, (
        "stage_visual_qa_final must invoke revise_loop.py for the "
        "2nd revise pass on visual-QA findings")
    # Same severity floor as the first pass
    assert "$REVISE_SEVERITY_FLOOR" in body, (
        "2nd revise pass must use the same REVISE_SEVERITY_FLOOR as "
        "the first (consistent operator policy)")


def test_stage_visual_qa_final_reassembles_when_revise_makes_changes():
    """After the 2nd revise pass, if revisions were applied, the
    deck must be re-assembled."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    assert "assemble_pptx.py" in body, (
        "stage_visual_qa_final must re-assemble the deck after the "
        "2nd revise pass applies changes")
    assert "re-assembled deck" in body, (
        "operator-visible stderr must announce the re-assemble step")


def _extract_stage_body(text: str, fn_name: str) -> str:
    """Extract a shell function body from the orchestrator source.
    Returns text from the opening brace through the matching closing
    brace (heredocs handled — only column-0 `}` outside a heredoc
    counts as the end)."""
    fn_start = text.find(f"{fn_name}() {{")
    if fn_start < 0:
        raise AssertionError(f"function {fn_name} not found")
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
# visual_qa.py --out-json / --out-md flags (v0.8 Tier G.7 enabler)
# ---------------------------------------------------------------------------

def test_visual_qa_py_accepts_out_json_flag():
    """visual_qa.py --help must document --out-json + --out-md per
    v0.8 Tier G.7 (the orchestrator stage uses them to write the
    post-revise pass output to a distinct path)."""
    result = subprocess.run(
        ["python", str(REPO_ROOT / "src" / "beril_presentation_maker"
                       / "skill" / "tools" / "visual_qa.py"),
         "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--out-json" in help_text, (
        "visual_qa.py must accept --out-json per v0.8 Tier G.7")
    assert "--out-md" in help_text, (
        "visual_qa.py must accept --out-md per v0.8 Tier G.7")


# ---------------------------------------------------------------------------
# v0.8 Tier G.8 — 2nd revise pass reads VQ-only review (not full review)
# ---------------------------------------------------------------------------

def test_g8_stage_invokes_2nd_revise_with_vq_only_review_path():
    """The orchestrator's 2nd revise invocation must use
    --review-path adversarial_review_vq_only.json so it only
    iterates VQ findings (not re-iterating F-prefixed adversarial
    findings + exhausting max_revisions before any VQ runs)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    # The 2nd revise invocation block must reference the VQ-only
    # review file path
    assert "adversarial_review_vq_only.json" in body, (
        "v0.8 Tier G.8: stage_visual_qa_final must reference "
        "adversarial_review_vq_only.json (the standalone VQ findings "
        "file) for the 2nd revise pass — without this, the 2nd pass "
        "re-iterates F-prefixed adversarial findings and exhausts "
        "max_revisions before reaching any VQ finding")
    # The revise_loop.py invocation must use --review-path with the
    # VQ-only file
    assert "--review-path" in body, (
        "2nd revise pass must use revise_loop.py --review-path to "
        "point at the standalone VQ-only review file")


def test_g8_stage_skips_2nd_revise_if_vq_only_missing():
    """Defensive: if the merger didn't write the VQ-only review file
    (e.g., 0 visual-QA findings), the stage must skip the 2nd revise
    pass cleanly rather than crashing revise_loop.py."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    # Look for the existence check
    assert "_vq_only_review" in body, (
        "stage_visual_qa_final must capture the VQ-only review path "
        "in a variable for the existence check + revise invocation")
    # Skip-when-missing pattern
    assert "no adversarial_review_vq_only.json written" in body, (
        "stage_visual_qa_final must skip the 2nd revise pass when "
        "no VQ-only review file exists (defensive against merger "
        "writing zero findings)")


# ---------------------------------------------------------------------------
# v0.8.0 Tier G.10-A: layout-overlap detector runs in stage_visual_qa_final
# ---------------------------------------------------------------------------

def test_stage_visual_qa_final_invokes_layout_overlap_check():
    """Source-level pin: stage_visual_qa_final must invoke
    check_slide_layout_overlaps.py per Tier G.10-A. The detector
    runs BEFORE visual-QA so its findings join the same revise
    channel."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    assert "check_slide_layout_overlaps.py" in body, (
        "stage_visual_qa_final must invoke check_slide_layout_overlaps.py "
        "(Tier G.10-A: deterministic overlap detector replaces visual-"
        "QA's overlap-class findings)"
    )


def test_stage_visual_qa_final_overlap_check_runs_before_visual_qa():
    """Source-level pin: the overlap check must precede the
    visual-QA invocation so visual-QA can be narrowed in future
    iterations + the overlap findings flow through the same merge
    pipeline."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    overlap_pos = body.find("check_slide_layout_overlaps.py")
    vq_pos = body.find("visual_qa.py")
    assert overlap_pos > 0
    assert vq_pos > 0
    assert overlap_pos < vq_pos, (
        "Tier G.10-A: layout-overlap check must run BEFORE visual_qa.py "
        "(detector is cheaper + its findings can inform what visual-QA "
        "still needs to flag)"
    )


# ---------------------------------------------------------------------------
# C1-B — env-missing skip records skipped-with-reason (not silent completed)
# ---------------------------------------------------------------------------

def test_visual_qa_final_records_skipped_when_stub_flagged():
    """C1-B: when visual_qa.py writes a stub with `"skipped": true`
    (missing host toolchain — soffice/pdftoppm), stage_visual_qa_final
    must record `skipped` in the run-record, NOT a silent `completed`.
    An auto-on stage that can't run is a P1, not a silent pass."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_body(text, "stage_visual_qa_final")
    # detects the skipped flag from the stub JSON
    assert "d.get('skipped')" in body or "get(\"skipped\")" in body, (
        "stage_visual_qa_final must read the `skipped` flag from the "
        "visual_qa stub JSON")
    # records skipped (not completed) on that branch
    assert "_record_stage visual_qa_final skipped" in body, (
        "a missing-toolchain skip must record `skipped`, not `completed`")


def test_visual_qa_py_writes_skipped_reason_on_missing_toolchain():
    """C1-B: visual_qa.py's missing-toolchain path stamps a
    skipped_reason into the stub (so the orchestrator can record it) and
    emits a LOUD (non-quiet-suppressible) P1 message."""
    vq_py = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
             / "tools" / "visual_qa.py").read_text(encoding="utf-8")
    assert "skipped_reason" in vq_py, (
        "visual_qa.py must stamp a skipped_reason on the missing-toolchain "
        "stub")
    # the loud message is printed unconditionally (not gated on `not quiet`)
    assert "missing host dependencies" in vq_py
    assert 'P1' in vq_py
