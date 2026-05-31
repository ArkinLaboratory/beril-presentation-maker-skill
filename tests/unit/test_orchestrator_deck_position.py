"""Tests for v0.8 Tier E orchestrator wiring: DECK_POSITION input
passed to ai_image_prompt.v1 (D-097).

The orchestrator computes DECK_POSITION from the slide_id format:
  - "pos{N}"       → "intro"   (no substory_id; opener slides)
  - "S{N}-pos{M}"  → "body"    (substory-attributed; arc-internal)
  - "closer"       → reserved for forward-compat; closer-class slides
    (deck_close, acks, refs, qa_anticipated) are in
    _STRUCTURAL_NO_IMAGE today and never reach stage_image_gen.

The wiring is in stage_image_gen's user_prompt construction (around
line ~2620 of presentation_maker.sh). Source-level pins + runtime
exec of the extracted snippet.

Decision pin per D-097 spec:
  Channel A intro slides MUST NOT include result-level statistics
  from later substories. The orchestrator's job is to PASS the
  DECK_POSITION value; the prompt-author (ai_image_prompt.v1) enforces
  the content rule. These tests cover the orchestrator-side wiring;
  the prompt-side rule is in ai_image_prompt.v1.md §4 + PA-9.
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
AI_PROMPT = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
             / "prompts" / "ai_image_prompt.v1.md")


# ---------------------------------------------------------------------------
# Source-level pins — orchestrator wiring
# ---------------------------------------------------------------------------

def test_orchestrator_computes_deck_position_in_stage_image_gen():
    """The DECK_POSITION computation block must live in
    stage_image_gen's user_prompt construction. Pin by searching for
    the comment marker + the regex check."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "v0.8/D-097" in text, (
        "stage_image_gen must reference v0.8/D-097 to mark the "
        "DECK_POSITION computation block")
    # The deck_position regex must reflect the intro-slide format
    assert 'if [[ "$slide_id" =~ ^pos[0-9]+$ ]]' in text, (
        "DECK_POSITION computation must detect intro slides via "
        "the ^pos{N}$ regex (no substory prefix)")
    # Default value is body (the regex flips to intro if matched)
    assert 'local deck_position="body"' in text, (
        "DECK_POSITION must default to 'body' (the regex flips to "
        "'intro' if the slide_id matches ^pos{N}$)")


def test_orchestrator_forwards_deck_position_to_ai_image_prompt():
    """The user_prompt passed to ai_image_prompt.v1 must include
    DECK_POSITION=<value>. Without this the prompt-author can't apply
    the §4 spoiler rule."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "DECK_POSITION=$deck_position" in text, (
        "user_prompt sent to ai_image_prompt.v1 must include "
        "DECK_POSITION=$deck_position")


def test_orchestrator_inline_explains_intro_spoiler_rule():
    """The user_prompt must inline-explain the DECK_POSITION semantics
    so the prompt-author has the context even if it skips reading the
    full ai_image_prompt.v1.md §4. Pin the load-bearing phrase."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Look for the literal phrase in the user_prompt block
    assert "MUST NOT include result-level" in text, (
        "user_prompt must inline-explain the intro-slide spoiler "
        "rule so the prompt-author has context even without reading "
        "the full §4 of ai_image_prompt.v1.md")
    assert "PA-9" in text, (
        "user_prompt must cite PA-9 anti-pattern for traceability")


# ---------------------------------------------------------------------------
# Source-level pins — ai_image_prompt.v1.md prompt updates
# ---------------------------------------------------------------------------

def test_ai_image_prompt_lists_deck_position_input():
    """ai_image_prompt.v1.md "Inputs the user prompt will pass"
    section must include DECK_POSITION with the three valid values
    and the intro/body/closer mapping."""
    text = AI_PROMPT.read_text(encoding="utf-8")
    assert "`DECK_POSITION`" in text, (
        "ai_image_prompt.v1.md Inputs section must document "
        "DECK_POSITION as a new input")
    # The three values must be enumerated
    for val in ('"intro"', '"body"', '"closer"'):
        assert val in text, (
            f"DECK_POSITION input documentation must enumerate the "
            f"{val} value")


def test_ai_image_prompt_has_intro_spoiler_rule_section():
    """Channel A authoring discipline must include the §4 intro-slide
    spoiler rule per D-097."""
    text = AI_PROMPT.read_text(encoding="utf-8")
    assert "### 4. Intro-slide spoiler rule (v0.8/D-097)" in text, (
        "ai_image_prompt.v1.md must have a §4 Channel A discipline "
        "section for the intro-slide spoiler rule")
    # Acceptable + unacceptable lists must be present so the
    # prompt-author has concrete guidance, not just abstract advice
    assert "Acceptable intro-image content" in text
    assert "Unacceptable intro-image content" in text


def test_ai_image_prompt_has_pa9_anti_pattern():
    """Anti-patterns section must include PA-9 covering the intro-
    slide spoiler class per D-097."""
    text = AI_PROMPT.read_text(encoding="utf-8")
    assert "PA-9 (v0.8/D-097): intro-slide spoiler" in text, (
        "ai_image_prompt.v1.md must have a PA-9 anti-pattern for "
        "the intro-slide spoiler class")
    # Cross-reference back to §4 for the full content rule
    assert "§4 (intro-slide spoiler rule)" in text


def test_ai_image_prompt_self_review_includes_spoiler_check():
    """Self-review checklist must include the spoiler check so the
    prompt-author actually runs it before the Write step."""
    text = AI_PROMPT.read_text(encoding="utf-8")
    # Check #12 added per D-097
    assert "12. **Intro-slide spoiler (v0.8/D-097; PA-9).**" in text, (
        "self-review section must include check #12 for the "
        "intro-slide spoiler class")


# ---------------------------------------------------------------------------
# Runtime exec — DECK_POSITION computation via extracted bash
# ---------------------------------------------------------------------------

def _extract_deck_position_block() -> str:
    """Extract the DECK_POSITION computation block from
    presentation_maker.sh. Spans from the v0.8/D-097 comment marker
    through the closing fi of the regex check."""
    text = ORCH_SH.read_text(encoding="utf-8")
    start_marker = "# v0.8/D-097: compute DECK_POSITION from slide_id format."
    start = text.find(start_marker)
    if start < 0:
        raise AssertionError(
            f"could not locate DECK_POSITION block in {ORCH_SH}; the "
            f"v0.8/D-097 comment marker may have been renamed")
    # The block ends at the next 'fi' AFTER the deck_position=intro
    # assignment. Search forward for the regex-match + closing fi.
    intro_assign = text.find('deck_position="intro"', start)
    assert intro_assign > 0
    closing_fi = text.find("\n      fi\n", intro_assign)
    assert closing_fi > 0
    return text[start:closing_fi + len("\n      fi\n")]


def _run_deck_position_with_slide_id(slide_id: str) -> str:
    """Run the DECK_POSITION block in a fresh bash subshell with the
    given slide_id. Returns the resolved deck_position.

    The block uses `local`, which only works inside a function. We
    wrap it in a synthetic function to mimic the real call-site
    inside stage_image_gen()."""
    block = _extract_deck_position_block()
    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        compute_position() {{
          local slide_id="$1"
          {block}
          echo "$deck_position"
        }}
        result=$(compute_position {slide_id!r})
        echo "RESOLVED_DECK_POSITION=$result"
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"deck_position block failed: stderr={result.stderr!r}")
    m = re.search(r"RESOLVED_DECK_POSITION=(\w+)", result.stdout)
    assert m, f"could not parse output: {result.stdout!r}"
    return m.group(1)


@pytest.mark.parametrize("slide_id,expected", [
    # Intro slides: no substory prefix
    ("pos1", "intro"),
    ("pos2", "intro"),
    ("pos10", "intro"),
    ("pos99", "intro"),
    # Body slides: substory-attributed
    ("S1-pos1", "body"),
    ("S1-pos4", "body"),
    ("S2-pos1", "body"),
    ("S12-pos7", "body"),
    # Edge cases — strict regex prevents accidental classification
    # of malformed slide_ids as intro
    ("intro-pos1", "body"),  # has prefix; not bare 'pos{N}'
    ("S1_pos1", "body"),     # underscore separator; not 'S{N}-pos{M}'
                              # but also not '^pos{N}$' → stays body
    ("position1", "body"),    # 'position' word; not 'pos{N}'
    ("pos1-extra", "body"),   # extra suffix; not '^pos{N}$'
])
def test_deck_position_computation_per_slide_id_format(slide_id, expected):
    """Parametrized over slide_id formats. The orchestrator's regex
    must correctly classify intro (no substory) vs body (with
    substory) slides + treat malformed slide_ids as 'body' (the safer
    default — body has no spoiler restriction)."""
    resolved = _run_deck_position_with_slide_id(slide_id)
    assert resolved == expected, (
        f"slide_id={slide_id!r}: expected deck_position={expected!r}; "
        f"got {resolved!r}")


def test_deck_position_safer_default_is_body():
    """The default value (before the regex check) must be 'body'.
    This is the safer fallback — body has no spoiler restriction, so
    a misclassified intro slide just gets the same treatment as v0.7
    (no enforcement). The opposite default ('intro') would falsely
    block body slides from showing legitimate quantitative anchors."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # The default-assignment must appear BEFORE the regex check
    default_pos = text.find('local deck_position="body"')
    regex_pos = text.find('if [[ "$slide_id" =~ ^pos[0-9]+$ ]]')
    assert default_pos > 0 and regex_pos > 0
    assert default_pos < regex_pos, (
        "DECK_POSITION default must be assigned BEFORE the regex "
        "check; the 'body' default is the safer fallback (body has "
        "no spoiler restriction; a misclassified intro slide just "
        "behaves like the v0.7 no-enforcement default)")
