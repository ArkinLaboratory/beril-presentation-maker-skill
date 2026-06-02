"""v0.8.0 Tier G.10-B: geometry-aware fontScale tests.

The old `_fontscale_for_chars` helper mapped char count to a fixed
ladder (200→100%, 400→90%, 700→80%, 1100→70%, else 60%). It didn't
see the box width × height or base pt size, so a long title in a
short band would be committed at 80% even though it visibly
overflows — leading to the "touch the textbox to refit" symptom
Adam reported on lanthanide_methylotrophy_atlas/draft_1.

The new `_fontscale_for_geometry` helper computes:
  required_area = chars × avg_glyph × line_height × base_pt²
  scale²       = box_area / required_area
  scale        = sqrt(...)

Tests pin the algorithm + edge cases.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)
sys.path.insert(0, str(TOOLS_DIR))

import assemble_pptx as asm  # noqa: E402
from assemble_pptx import (  # noqa: E402
    _fontscale_for_geometry, FONTSCALE_FLOOR, FONTSCALE_FULL,
    _EMU_PER_INCH,
)


def _in_to_emu(inches: float) -> int:
    return int(inches * _EMU_PER_INCH)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_zero_chars_returns_full() -> None:
    """No content → no shrink needed."""
    assert _fontscale_for_geometry(
        0, box_width_emu=_in_to_emu(5), box_height_emu=_in_to_emu(3),
        base_pt=14,
    ) == FONTSCALE_FULL


def test_short_content_in_big_box_returns_full() -> None:
    """50 chars at 14pt in a 9.32×3.15 in box has plenty of room
    → no shrink."""
    scale = _fontscale_for_geometry(
        50, box_width_emu=_in_to_emu(9.32),
        box_height_emu=_in_to_emu(3.15), base_pt=14,
    )
    assert scale == FONTSCALE_FULL


def test_very_long_content_clamps_at_floor() -> None:
    """Pathological content that needs sub-60% shrink → clamped at
    FONTSCALE_FLOOR (caller can detect via warning channel)."""
    # 5000 chars at 28pt in a tiny 1×0.5 in box — way too much
    scale = _fontscale_for_geometry(
        5000, box_width_emu=_in_to_emu(1), box_height_emu=_in_to_emu(0.5),
        base_pt=28,
    )
    assert scale == FONTSCALE_FLOOR


# ---------------------------------------------------------------------------
# Real lanthanide deck slide-25 case — the Adam-flagged "touch to refit"
# ---------------------------------------------------------------------------

def test_lanthanide_title_at_28pt_in_06h_band_clamps_at_floor() -> None:
    """The lanthanide_methylotrophy_atlas/draft_1 slide-25 title
    (337 chars, methods_summary layout, base 28pt, title band
    ~9.32×0.63 in) is the load-bearing case for G.10-B. The
    geometry sizer should compute a sub-floor scale + clamp at the
    floor — which is the right answer: a 337-char title CANNOT
    legibly fit in a 0.63in band at any rendering. The downstream
    G.10-C content_overflow finding then fires so revise_loop can
    rewrite shorter."""
    scale = _fontscale_for_geometry(
        337, box_width_emu=_in_to_emu(9.32),
        box_height_emu=_in_to_emu(0.63), base_pt=28,
    )
    # Clamps at floor because required_area >> target_area
    assert scale == FONTSCALE_FLOOR


def test_lanthanide_bullets_in_body_band_render_at_full() -> None:
    """The same slide's 3 bullets (341 chars total) at base 14pt in
    a 9.32×2.85 in box has plenty of room. Sizer should return
    FULL (100%)."""
    scale = _fontscale_for_geometry(
        341, box_width_emu=_in_to_emu(9.32),
        box_height_emu=_in_to_emu(2.85), base_pt=14,
    )
    assert scale == FONTSCALE_FULL


# ---------------------------------------------------------------------------
# Monotonicity properties (sanity)
# ---------------------------------------------------------------------------

def test_more_chars_means_smaller_or_equal_scale() -> None:
    """Doubling chars in a fixed box → scale shrinks or stays
    pegged at floor."""
    box_w = _in_to_emu(6)
    box_h = _in_to_emu(1)
    s100 = _fontscale_for_geometry(
        100, box_width_emu=box_w, box_height_emu=box_h, base_pt=18,
    )
    s400 = _fontscale_for_geometry(
        400, box_width_emu=box_w, box_height_emu=box_h, base_pt=18,
    )
    assert s400 <= s100


def test_bigger_box_means_larger_or_equal_scale() -> None:
    """Same content in a bigger box → scale grows or stays full."""
    s_small = _fontscale_for_geometry(
        300, box_width_emu=_in_to_emu(3),
        box_height_emu=_in_to_emu(1), base_pt=14,
    )
    s_big = _fontscale_for_geometry(
        300, box_width_emu=_in_to_emu(9),
        box_height_emu=_in_to_emu(3), base_pt=14,
    )
    assert s_big >= s_small


def test_larger_base_pt_means_smaller_or_equal_scale() -> None:
    """Same chars + box, but bigger base font → scale shrinks
    (text takes more room at the bigger base)."""
    box_w = _in_to_emu(6)
    box_h = _in_to_emu(2)
    s14 = _fontscale_for_geometry(
        500, box_width_emu=box_w, box_height_emu=box_h, base_pt=14,
    )
    s28 = _fontscale_for_geometry(
        500, box_width_emu=box_w, box_height_emu=box_h, base_pt=28,
    )
    assert s28 <= s14


# ---------------------------------------------------------------------------
# Helpers exist with the public API the renderer depends on
# ---------------------------------------------------------------------------

def test_fit_textbox_by_geometry_is_exported() -> None:
    """The geometry-aware textbox fitter must be importable from
    assemble_pptx (the renderer's main entry into the new
    machinery)."""
    assert hasattr(asm, "_fit_textbox_by_geometry")
    assert callable(asm._fit_textbox_by_geometry)


def test_enable_normautofit_by_geometry_is_exported() -> None:
    """The geometry-aware placeholder fitter is the placeholder-side
    sibling of _fit_textbox_by_geometry."""
    assert hasattr(asm, "_enable_normautofit_by_geometry")
    assert callable(asm._enable_normautofit_by_geometry)


def test_set_title_accepts_warnings_kwarg() -> None:
    """_set_title gained a `warnings` parameter so geometry-derived
    floor-clamp warnings can flow up to the renderer's warnings list
    (G.10-C content_overflow handoff)."""
    import inspect
    sig = inspect.signature(asm._set_title)
    assert "warnings" in sig.parameters


# ---------------------------------------------------------------------------
# Constants pinned
# ---------------------------------------------------------------------------

def test_fontscale_constants_unchanged() -> None:
    """FLOOR + FULL constants must stay 60000 / 100000 — they're
    referenced in the OOXML emit + downstream cascade readers."""
    assert FONTSCALE_FLOOR == 60000
    assert FONTSCALE_FULL == 100000


def test_emu_per_inch_pin() -> None:
    """1 inch = 914400 EMU per OOXML spec — pinned because the
    geometry sizer uses this to convert box dimensions."""
    assert _EMU_PER_INCH == 914400
