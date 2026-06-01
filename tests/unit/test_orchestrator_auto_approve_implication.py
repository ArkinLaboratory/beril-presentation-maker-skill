"""Tests for v0.8 Tier G.3: --auto-advance implies --auto-approve-images.

Live discovery on ibd_phage_targeting draft_8 2026-05-31: operator
passed --auto-advance (unattended intent) without
--auto-approve-images. ai_image_prompt ran for intro-pos0 ($0.27,
clean prompt produced), then the per-slide approval gate hit
EOFError on stdin (background bash, no TTY), returned
Verdict.QUIT, and the loop broke after 1 slide. Result: 1 of 2
emit=true slides processed, 0 images generated, $0.27 wasted in
ai_image_prompt cost.

Fix: when AUTO_ADVANCE=1 AND AUTO_APPROVE_IMAGES=0 AND NO_IMAGES=0,
auto-set AUTO_APPROVE_IMAGES=1. Operators who want unattended +
no images pass --no-images explicitly.

Source-level pins + runtime exec of extracted snippet via bash -c.
Mirror pattern: test_orchestrator_visual_qa_default.py.
"""
from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


# ---------------------------------------------------------------------------
# Source-level pins
# ---------------------------------------------------------------------------

def test_auto_advance_implication_block_present():
    """Pin the v0.8 Tier G.3 block exists in the orchestrator at the
    post-validation init area (after --auto-advance / NO_IMAGES /
    AUTO_APPROVE_IMAGES are parsed but before stages run)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "v0.8 Tier G.3 — --auto-advance implies --auto-approve-images" in text, (
        "v0.8 Tier G.3 implication block must be present in the "
        "orchestrator (comment marker)")


def test_auto_advance_implication_block_after_visual_qa_auto_on():
    """The Tier G.3 block must appear AFTER the D-096 visual-QA
    auto-on block (parallel post-validation init pattern)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    visual_qa_pos = text.find("v0.8/D-096 — mode-aware visual-QA auto-on")
    auto_approve_pos = text.find(
        "v0.8 Tier G.3 — --auto-advance implies --auto-approve-images")
    assert visual_qa_pos > 0 and auto_approve_pos > 0
    assert visual_qa_pos < auto_approve_pos, (
        "Tier G.3 block must come AFTER the D-096 visual-QA auto-on "
        "block (parallel post-validation init layering)")


def test_auto_advance_implication_block_guards_on_three_flags():
    """The implication guard must check ALL THREE: AUTO_ADVANCE=1
    AND AUTO_APPROVE_IMAGES=0 AND NO_IMAGES=0. Missing any of these
    creates incorrect semantics."""
    text = ORCH_SH.read_text(encoding="utf-8")
    start = text.find("v0.8 Tier G.3 — --auto-advance")
    assert start > 0
    end = text.find("# v0.4 M2:", start)
    block = text[start:end] if end > 0 else text[start:start + 3000]
    assert '"$AUTO_ADVANCE" -eq 1' in block, (
        "guard must check AUTO_ADVANCE -eq 1")
    assert '"$AUTO_APPROVE_IMAGES" -eq 0' in block, (
        "guard must check AUTO_APPROVE_IMAGES -eq 0 (only fire when "
        "operator hasn't already opted in explicitly)")
    assert '"$NO_IMAGES" -eq 0' in block, (
        "guard must check NO_IMAGES -eq 0 (only fire when operator "
        "hasn't opted out of images entirely)")


def test_auto_advance_implication_announces_to_stderr():
    """When implication fires, the orchestrator must emit a stderr
    line so operators understand why the gate was bypassed + know
    --no-images is the way to opt out."""
    text = ORCH_SH.read_text(encoding="utf-8")
    start = text.find("v0.8 Tier G.3 — --auto-advance")
    end = text.find("# v0.4 M2:", start)
    block = text[start:end] if end > 0 else text[start:start + 3000]
    assert "[v0.8 Tier G.3] --auto-advance implies --auto-approve-images" in block, (
        "implication firing must emit a [v0.8 Tier G.3] stderr line "
        "naming both flags involved")
    assert "--no-images" in block, (
        "stderr message must name --no-images as the opt-out path")


def test_help_text_documents_implication_on_auto_advance():
    """`--help` for --auto-advance must mention the v0.8 Tier G.3
    implication so operators reading docs understand the coupling.

    The flag's help entry is in the # comment-block flag list, not
    in the v0.1.0 prose intro. Match the specific flag-entry shape
    (lookup the entry that BEGINS the line, not anywhere it appears)."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    # The flag entry line starts with "  --auto-advance " (two
    # spaces of indent + the flag, then trailing space before
    # the description column). Find that anchored shape, not the
    # first arbitrary substring match.
    # Flag entries in --help are formatted "#   --flag-name ..." in
    # the orchestrator's leading comment block (which is what --help
    # echoes back). Match that anchored shape.
    m = re.search(r"^#\s+--auto-advance\s", help_text, re.MULTILINE)
    assert m is not None, "--auto-advance flag entry not found in --help"
    aa_idx = m.start()
    aa_section = help_text[aa_idx:aa_idx + 800]
    assert "Tier G.3" in aa_section or "auto-approve-images" in aa_section, (
        "--auto-advance --help text must mention the v0.8 Tier G.3 "
        "implication (links --auto-advance to --auto-approve-images "
        f"behavior); section was:\n{aa_section}")


def test_help_text_documents_implication_on_auto_approve_images():
    """--help for --auto-approve-images must also note the
    implication so operators reading from the image-gen-flags side
    understand the auto-set behavior."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    m = re.search(r"^#\s+--auto-approve-images\s", help_text, re.MULTILINE)
    assert m is not None, (
        "--auto-approve-images flag entry not found in --help")
    aa_idx = m.start()
    aa_section = help_text[aa_idx:aa_idx + 600]
    assert "Tier G.3" in aa_section or "auto-set" in aa_section, (
        "--auto-approve-images --help text must mention the auto-set "
        f"behavior triggered by --auto-advance; section was:\n{aa_section}")


# ---------------------------------------------------------------------------
# Runtime exec via extracted bash snippet
# ---------------------------------------------------------------------------

def _extract_implication_block() -> str:
    """Extract the v0.8 Tier G.3 implication block."""
    text = ORCH_SH.read_text(encoding="utf-8")
    start_marker = "# v0.8 Tier G.3 — --auto-advance implies --auto-approve-images."
    end_marker = "# v0.4 M2:"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise AssertionError(
            f"could not locate v0.8 Tier G.3 block (start={start}, "
            f"end={end}); the comment marker may have been renamed.")
    return text[start:end]


def _run_implication(
    auto_advance: int,
    auto_approve_images: int = 0,
    no_images: int = 0,
) -> tuple[int, str]:
    """Run the implication block with given flags. Returns
    (resolved AUTO_APPROVE_IMAGES, stderr-text)."""
    block = _extract_implication_block()
    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        AUTO_ADVANCE={auto_advance}
        AUTO_APPROVE_IMAGES={auto_approve_images}
        NO_IMAGES={no_images}
        {block}
        echo "RESOLVED_AUTO_APPROVE_IMAGES=$AUTO_APPROVE_IMAGES"
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"implication block failed: stderr={result.stderr!r}")
    m = re.search(r"RESOLVED_AUTO_APPROVE_IMAGES=(\d+)", result.stdout)
    assert m, f"could not parse output: {result.stdout!r}"
    return int(m.group(1)), result.stderr


@pytest.mark.parametrize("aa,aai,ni,expected", [
    # The trigger case: --auto-advance only, default flags otherwise
    # → implication fires, AUTO_APPROVE_IMAGES flips to 1
    (1, 0, 0, 1),
    # --auto-advance + --auto-approve-images already set → no change,
    # already 1
    (1, 1, 0, 1),
    # --auto-advance + --no-images → implication skipped, stays 0
    # (no images to approve anyway)
    (1, 0, 1, 0),
    # No --auto-advance → implication doesn't fire regardless
    (0, 0, 0, 0),
    (0, 1, 0, 1),
    (0, 0, 1, 0),
])
def test_implication_logic_per_flag_matrix(aa, aai, ni, expected):
    """Parametrized over the 6-cell decision matrix. Implication
    only fires when AUTO_ADVANCE=1 AND AUTO_APPROVE_IMAGES=0 AND
    NO_IMAGES=0."""
    resolved, _ = _run_implication(aa, aai, ni)
    assert resolved == expected, (
        f"AUTO_ADVANCE={aa}, AUTO_APPROVE_IMAGES={aai}, NO_IMAGES={ni}: "
        f"expected AUTO_APPROVE_IMAGES={expected}; got {resolved}")


def test_implication_emits_announcement_when_triggered():
    """The stderr announcement must fire only on the implication
    case (AUTO_ADVANCE=1 + other two unset)."""
    _, stderr = _run_implication(1, 0, 0)
    assert "[v0.8 Tier G.3]" in stderr, (
        "implication firing must emit the [v0.8 Tier G.3] stderr line")
    assert "--no-images" in stderr, (
        "stderr must name --no-images as opt-out")


def test_implication_quiet_when_not_triggered():
    """When the implication doesn't fire, no stderr announcement."""
    # AUTO_ADVANCE=0 → no announcement
    _, stderr1 = _run_implication(0, 0, 0)
    assert "[v0.8 Tier G.3]" not in stderr1
    # NO_IMAGES=1 → no announcement (correct: images skipped, no
    # gate to bypass)
    _, stderr2 = _run_implication(1, 0, 1)
    assert "[v0.8 Tier G.3]" not in stderr2
    # AUTO_APPROVE_IMAGES already 1 → no announcement (already in
    # the desired state)
    _, stderr3 = _run_implication(1, 1, 0)
    assert "[v0.8 Tier G.3]" not in stderr3
