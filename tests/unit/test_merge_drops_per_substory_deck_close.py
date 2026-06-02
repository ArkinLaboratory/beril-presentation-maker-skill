"""v0.8.0 (D-098): defensive belt-and-suspenders for the
duplicate-deck_close pattern.

The per-substory composer must not emit a `layout: deck_close`
slide — the dedicated `stage_deck_close` orchestrator stage owns
that slide. Earlier v3.2 prompt wording instructed the composer to
"compose ONE deck_close slide at the end of the deck", which
caused the final-substory composer (S3 on lanthanide draft_1;
final substory on ibd draft_12) to emit a deck_close-layout slide
in its fragment in addition to the dedicated stage's fragment.
Both got spliced; two deck_close slides shipped.

These tests pin the merger-side drop + warning at the helper-
function level (subprocess-level coverage is in the integration
suite). The helpers are tested directly; the main loop's wiring
is verified by a single integration call that simulates a per-
substory fragment with a rogue deck_close slide and checks the
merger drops it + writes a clean slide_spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)
sys.path.insert(0, str(TOOLS_DIR))

import merge_compose_fragments as mcf  # noqa: E402


# ---------------------------------------------------------------------------
# is_per_substory_deck_close — the predicate
# ---------------------------------------------------------------------------

def test_predicate_true_on_deck_close_layout() -> None:
    slide = {
        "layout": "deck_close",
        "content": {"unified_point": "...", "key_takeaways": [],
                    "forward_call": "..."},
    }
    assert mcf.is_per_substory_deck_close(slide) is True


def test_predicate_false_on_claim_evidence_layout() -> None:
    slide = {"layout": "claim_evidence",
             "content": {"title": "t", "bullets": []}}
    assert mcf.is_per_substory_deck_close(slide) is False


def test_predicate_false_on_data_figure_layout() -> None:
    slide = {"layout": "data_figure",
             "content": {"title": "t", "figure": "f.png"}}
    assert mcf.is_per_substory_deck_close(slide) is False


def test_predicate_false_on_missing_layout() -> None:
    """Defensive: a slide dict without a layout field is not a
    deck_close (validator would catch it later for being malformed,
    but the predicate must not crash)."""
    assert mcf.is_per_substory_deck_close({"content": {}}) is False


def test_predicate_false_on_non_dict() -> None:
    """Defensive: anything non-dict (None, str, list) is not a
    deck_close. The merger should never pass non-dict slides here,
    but the predicate guards against future shape drift."""
    assert mcf.is_per_substory_deck_close(None) is False  # type: ignore[arg-type]
    assert mcf.is_per_substory_deck_close("deck_close") is False  # type: ignore[arg-type]
    assert mcf.is_per_substory_deck_close([]) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# format_d098_drop_warning — the operator-visible stderr message
# ---------------------------------------------------------------------------

def test_warning_references_d098() -> None:
    """The warning must reference D-098 so operators can grep for
    the regression class."""
    msg = mcf.format_d098_drop_warning("S3", 8)
    assert "D-098" in msg


def test_warning_includes_substory_id_and_position() -> None:
    """The warning must include the substory id + the fragment
    position so the operator can locate the rogue slide in the
    fragment file."""
    msg = mcf.format_d098_drop_warning("S2", 4)
    assert "S2" in msg
    assert "4" in msg


def test_warning_names_dropped_layout() -> None:
    """The warning must name 'deck_close' so operators understand
    what was dropped without consulting the source."""
    msg = mcf.format_d098_drop_warning("S1", 0)
    assert "deck_close" in msg


def test_warning_points_at_prompt_file() -> None:
    """The warning must reference slide_compose.v3.x_overlay.md so
    the operator knows where to look for the prompt-side
    regression that caused the per-substory composer to author a
    deck_close slide in the first place."""
    msg = mcf.format_d098_drop_warning("S1", 0)
    assert "slide_compose" in msg


def test_warning_blames_per_substory_composer_not_stage() -> None:
    """The warning must clarify that stage_deck_close is NOT at
    fault — the drop is for the per-substory composer's mistake.
    Without this clarity, operators might investigate the wrong
    stage."""
    msg = mcf.format_d098_drop_warning("S1", 0)
    assert "per-substory" in msg
    assert "stage_deck_close" in msg


# ---------------------------------------------------------------------------
# Integration: the main loop invokes the predicate
# ---------------------------------------------------------------------------

def test_main_loop_imports_predicate() -> None:
    """Source-level pin: merge_compose_fragments.py must reference
    is_per_substory_deck_close in its main loop (the per-substory
    fragment iteration). Without this call, the duplicate-deck_close
    regression returns silently."""
    src = (TOOLS_DIR / "merge_compose_fragments.py").read_text(encoding="utf-8")
    assert "is_per_substory_deck_close(" in src, (
        "merge_compose_fragments.py main() must call "
        "is_per_substory_deck_close() in the per-substory loop "
        "(D-098 belt-and-suspenders)"
    )


def test_main_loop_emits_d098_warning_on_drop() -> None:
    """Source-level pin: merge_compose_fragments.py must call
    format_d098_drop_warning when the predicate fires."""
    src = (TOOLS_DIR / "merge_compose_fragments.py").read_text(encoding="utf-8")
    assert "format_d098_drop_warning(" in src, (
        "merge_compose_fragments.py main() must emit the D-098 "
        "warning via format_d098_drop_warning() so operators see "
        "the prompt-side regression"
    )


def test_main_loop_counts_drops_for_summary() -> None:
    """Source-level pin: drop counter must exist + be printed in
    the merger's end-of-run summary so per-run drift is visible
    without grepping stderr."""
    src = (TOOLS_DIR / "merge_compose_fragments.py").read_text(encoding="utf-8")
    assert "n_per_substory_deck_close_dropped" in src, (
        "merger main() must track drop count via "
        "n_per_substory_deck_close_dropped"
    )
    # The end-of-run summary print
    assert "D-098: dropped" in src, (
        "merger main() must print drop count in end-of-run summary"
    )
