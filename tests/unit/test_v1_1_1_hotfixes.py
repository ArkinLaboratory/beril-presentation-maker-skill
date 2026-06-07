"""v1.1.1 hotfix coverage.

Four root-caused defects from the caulobacter hub run (2026-06-07):

  DP4 — assemble_pptx._add_picture stretched every figure (both width and
        height passed to python-pptx). Fix: width-only + clamp + center.
  DP3 — ai_image_prompt wrote 05_image_requests/<sid>_request.json but
        image_client never produced 05_images/<sid>.png AND no manifest
        reject/skip entry was written. Fail-loud cross-check added in
        image_gen_orchestrate.assert-requests-resolved.
  DP9 — `continue --resume-from image_gen` without --mode silently
        defaulted MODE=talk-30 on top of a talk-45 draft. Fix: shell
        recovers MODE from working/slide_spec.json on resume + new
        mode_consistency.py asserts mode is uniform across artifacts.
  Fix4 — `assemble <draft_dir>` only read <draft_dir>/slide_spec.json
         (flat), forcing a manual copy out of working/. Fix: resolve
         working/slide_spec.json first; fall back to flat.

Each test sits at the right tier (unit, mockable, no LLM, no live
gemini). The live re-assemble + the hub re-run are Cowork's + Adam's
gates per the brief.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Module loaders — tests run against the in-tree skill/tools/ tree
# without requiring the package to be reinstalled (same pattern as
# tests/unit/test_image_gen_orchestrate.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_TOOLS = (
    _REPO_ROOT / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import draft_paths as dp  # noqa: E402
import image_gen_orchestrate as igo  # noqa: E402
import mode_consistency as mc  # noqa: E402

# ---------------------------------------------------------------------------
# DP4 — _add_picture fit-within-box preserving aspect
# ---------------------------------------------------------------------------
#
# Tested with a lightweight stub for the slide.shapes.add_picture call;
# the real pptx round-trip is covered indirectly via tests/unit/test_
# assemble_pptx.py's existing renders. The math here is the load-bearing
# piece — pre-v1.1.1 it stretched; v1.1.1 it preserves source aspect +
# centers.


class _StubPicture:
    """Mimics the minimal pptx Picture surface: width + height + left + top
    are integer EMUs (English Metric Units; python-pptx's Inches helper
    returns ints in EMU). The shapes.add_picture stub creates one of
    these with an initial height computed from the source aspect ratio
    + the caller's width."""

    def __init__(self, native_w: int, native_h: int, requested_width: int):
        # Preserve native aspect when only width is supplied — this is
        # exactly what python-pptx does.
        self.width = requested_width
        self.height = int(requested_width * native_h / native_w)
        self.left = 0
        self.top = 0


class _StubShapes:
    def __init__(self, native_w: int, native_h: int):
        self._native_w = native_w
        self._native_h = native_h
        self.last_call_kwargs: dict | None = None

    def add_picture(self, _path, _left, _top, *, width):
        # v1.1.1 contract: add_picture is called with width= ONLY.
        # Height is intentionally omitted so python-pptx preserves the
        # source aspect. The stub records the kwargs so the test can
        # assert the no-height invariant.
        self.last_call_kwargs = {"width": width}
        return _StubPicture(self._native_w, self._native_h, width)


class _StubSlide:
    def __init__(self, shapes: _StubShapes):
        self.shapes = shapes


def _load_assemble_pptx():
    """Import the in-tree assemble_pptx as `_v111_assemble_pptx`.

    Loaded from the file path so the module's _DEFAULT_MASTER constant
    resolves correctly. Cached on sys.modules under a private name so
    repeated tests reuse one import.
    """
    if "_v111_assemble_pptx" in sys.modules:
        return sys.modules["_v111_assemble_pptx"]
    from importlib.util import module_from_spec, spec_from_file_location
    asm_py = _SKILL_TOOLS / "assemble_pptx.py"
    spec = spec_from_file_location("_v111_assemble_pptx", asm_py)
    mod = module_from_spec(spec)
    sys.modules["_v111_assemble_pptx"] = mod
    spec.loader.exec_module(mod)
    return mod


def _emu_per_inch():
    asm = _load_assemble_pptx()
    return int(asm.Inches(1.0))


def test_dp4_add_picture_width_only_call_no_height():
    """The single load-bearing invariant: _add_picture MUST NOT pass
    height to add_picture. Pre-v1.1.1 stretched because both were set."""
    asm = _load_assemble_pptx()
    shapes = _StubShapes(native_w=1000, native_h=500)  # 2:1 wide source
    slide = _StubSlide(shapes)
    asm._add_picture(slide, Path("/dev/null"),
                     left_in=0.5, top_in=1.3, width_in=9.0, height_in=2.85)
    assert shapes.last_call_kwargs == {"width": asm.Inches(9.0)}, (
        "v1.1.1 contract: add_picture MUST be called with width= only. "
        f"Got: {shapes.last_call_kwargs}"
    )


def test_dp4_wide_source_fits_width_unconstrained():
    """Wide-and-shallow source (≈3.16:1 — matches the FIGURE_REGIONS
    data_figure box) into the same box: width-only sets height to the
    matching value, which lands at-or-below box_h → letterboxed (or
    nearly exact-fit) with no rescale. This is the only case where
    pic.width == Inches(width_in) holds."""
    asm = _load_assemble_pptx()
    # Native 3.16:1 → at width 9.0in the natural height is ≈2.85in.
    # Use 3160 × 1000 so width/height = 3.16; at width=9.0 the natural
    # height is 9.0 / 3.16 = 2.848 in — just under the 2.85 box, so no
    # clamp.
    shapes = _StubShapes(native_w=3160, native_h=1000)
    slide = _StubSlide(shapes)
    pic = asm._add_picture(slide, Path("/dev/null"),
                           left_in=0.5, top_in=1.3,
                           width_in=9.0, height_in=2.85)
    # Width fit: 9.0 in exactly (no rescale).
    assert pic.width == asm.Inches(9.0)
    # Height a hair below the box → no clamp.
    assert pic.height <= asm.Inches(2.85)
    # Centered horizontally (zero offset when width == box_w) +
    # vertically (small positive offset when pic.height < box_h).
    assert pic.left == asm.Inches(0.5) + (asm.Inches(9.0) - pic.width) // 2
    assert pic.top == asm.Inches(1.3) + (asm.Inches(2.85) - pic.height) // 2


def test_dp4_overflowing_wide_source_clamps_to_box_height():
    """Wide-but-taller-than-box-AR source (2:1) into the wide-short
    box: width-only would give a 4.5in-tall picture that overflows
    the 2.85in box. v1.1.1 clamps height to 2.85 and rescales width
    proportionally to 5.7in (2 × 2.85). Letterboxing applies."""
    asm = _load_assemble_pptx()
    shapes = _StubShapes(native_w=2000, native_h=1000)
    slide = _StubSlide(shapes)
    pic = asm._add_picture(slide, Path("/dev/null"),
                           left_in=0.5, top_in=1.3,
                           width_in=9.0, height_in=2.85)
    assert pic.height == asm.Inches(2.85)
    # Aspect preserved at new height: 2 × 2.85 = 5.7 in (within
    # EMU rounding).
    assert abs(pic.width - asm.Inches(5.7)) < 10
    # Centered.
    assert pic.left == asm.Inches(0.5) + (asm.Inches(9.0) - pic.width) // 2
    assert pic.top == asm.Inches(1.3) + (asm.Inches(2.85) - pic.height) // 2


def test_dp4_tall_source_pillarboxed():
    """Portrait source (1:2) into a wide-short box: width-only would
    give a hugely tall picture; v1.1.1 rescales to height=box_h and
    pillarboxes (centers horizontally with smaller width)."""
    asm = _load_assemble_pptx()
    shapes = _StubShapes(native_w=1000, native_h=2000)
    slide = _StubSlide(shapes)
    pic = asm._add_picture(slide, Path("/dev/null"),
                           left_in=0.5, top_in=1.3,
                           width_in=9.0, height_in=2.85)
    # Height-limited: box_h is the cap.
    assert pic.height == asm.Inches(2.85)
    # Width preserves the 1:2 source aspect at height=2.85 → 1.425 in.
    assert pic.width == asm.Inches(1.425)
    # Centered.
    assert pic.left == asm.Inches(0.5) + (asm.Inches(9.0) - pic.width) // 2
    assert pic.top == asm.Inches(1.3) + (asm.Inches(2.85) - pic.height) // 2


def test_dp4_square_source_into_wide_box_letterboxed():
    """A square source (1:1) into wide box: width-only gives a square at
    width=9.0 → height=9.0 (overflows the 2.85 box). v1.1.1 clamps to
    height=2.85, width=2.85, centered."""
    asm = _load_assemble_pptx()
    shapes = _StubShapes(native_w=1000, native_h=1000)
    slide = _StubSlide(shapes)
    pic = asm._add_picture(slide, Path("/dev/null"),
                           left_in=0.5, top_in=1.3,
                           width_in=9.0, height_in=2.85)
    assert pic.height == asm.Inches(2.85)
    assert pic.width == asm.Inches(2.85)


def test_dp4_aspect_preserved_within_pixel_rounding():
    """The display aspect ratio must match the native aspect ratio
    (within EMU pixel-rounding tolerance ~1%). This is the property
    the caulobacter aspect-check script asserts (skew within 0.92-1.08).
    Pre-v1.1.1 every figure was forced to box AR; v1.1.1 preserves AR.
    """
    asm = _load_assemble_pptx()
    cases = [
        (1600, 900),   # 16:9 native (≈ 1.78)
        (1200, 900),   # 4:3
        (900, 1200),   # 3:4 portrait
        (2000, 800),   # 2.5:1 very wide
    ]
    for native_w, native_h in cases:
        native_ar = native_w / native_h
        shapes = _StubShapes(native_w=native_w, native_h=native_h)
        slide = _StubSlide(shapes)
        pic = asm._add_picture(slide, Path("/dev/null"),
                               left_in=0.5, top_in=1.3,
                               width_in=9.0, height_in=2.85)
        display_ar = pic.width / pic.height
        # Within 1.5% — EMU rounding is the only source of slack.
        ratio = display_ar / native_ar
        assert 0.985 <= ratio <= 1.015, (
            f"aspect skew {ratio:.4f} on native {native_w}x{native_h} "
            f"(display {pic.width}x{pic.height})"
        )


# ---------------------------------------------------------------------------
# DP3 — fail-loud on request-with-no-output
# ---------------------------------------------------------------------------


@pytest.fixture
def initialized_draft(tmp_path):
    """A tmp_path with v0.3.1+ layout initialized."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    return paths


def _write_request(paths: dp.DraftPaths, slide_id: str) -> None:
    """Write a minimal request.json for `slide_id`."""
    paths.image_requests_dir.mkdir(parents=True, exist_ok=True)
    (paths.image_requests_dir / f"{slide_id}_request.json").write_text(
        json.dumps({"slide_id_target": slide_id, "image_prompt": "x",
                    "worst_case_cost_usd": 0.04}),
        encoding="utf-8",
    )


def _write_png(paths: dp.DraftPaths, slide_id: str) -> None:
    paths.images_dir.mkdir(parents=True, exist_ok=True)
    (paths.images_dir / f"{slide_id}.png").write_bytes(b"\x89PNG\r\n\x1a\n")


def test_dp3_no_requests_passes(initialized_draft):
    """No requests → no orphans → empty unresolved list."""
    assert igo.find_unresolved_requests(initialized_draft) == []


def test_dp3_request_with_png_passes(initialized_draft):
    """Request + matching PNG → resolved (the success path)."""
    _write_request(initialized_draft, "S4-pos3")
    _write_png(initialized_draft, "S4-pos3")
    assert igo.find_unresolved_requests(initialized_draft) == []


def test_dp3_request_with_manifest_reject_passes(initialized_draft):
    """Request + manifest-recorded rejection → resolved (explicit
    rejection is fine; the PNG missing is by design)."""
    _write_request(initialized_draft, "S4-pos3")
    igo.record_rejected(initialized_draft, slide_id="S4-pos3",
                        reason="user-rejected via approval gate")
    assert igo.find_unresolved_requests(initialized_draft) == []


def test_dp3_request_with_manifest_skip_passes(initialized_draft):
    """Request + manifest-recorded budget skip → resolved."""
    _write_request(initialized_draft, "S4-pos3")
    igo.record_skipped(initialized_draft, slide_id="S4-pos3",
                       reason="budget cap reached")
    assert igo.find_unresolved_requests(initialized_draft) == []


def test_dp3_orphan_request_fails_loud(initialized_draft):
    """The caulobacter failure mode: request written, no PNG, no
    manifest entry. MUST surface as unresolved."""
    _write_request(initialized_draft, "S4-pos3")
    assert igo.find_unresolved_requests(initialized_draft) == ["S4-pos3"]


def test_dp3_mixed_resolved_and_orphan(initialized_draft):
    """Multiple requests — only the orphan reports."""
    _write_request(initialized_draft, "S1-pos2")
    _write_png(initialized_draft, "S1-pos2")
    _write_request(initialized_draft, "S2-pos5")
    igo.record_rejected(initialized_draft, slide_id="S2-pos5",
                        reason="user-rejected")
    _write_request(initialized_draft, "S4-pos3")  # orphan
    assert igo.find_unresolved_requests(initialized_draft) == ["S4-pos3"]


# ---------------------------------------------------------------------------
# DP9 — mode_consistency.resolve + check
# ---------------------------------------------------------------------------


def _write_slide_spec(paths: dp.DraftPaths, mode: str) -> None:
    paths.working.mkdir(parents=True, exist_ok=True)
    (paths.working / "slide_spec.json").write_text(
        json.dumps({"schema_version": "slide_spec.v1",
                    "mode": mode, "slides": []}),
        encoding="utf-8",
    )


def _write_image_decisions(paths: dp.DraftPaths, mode: str) -> None:
    paths.working.mkdir(parents=True, exist_ok=True)
    (paths.working / "05_image_decisions.json").write_text(
        json.dumps({"schema_version": "image-decisions.v1",
                    "tier": "STRONG", "mode": mode, "decisions": []}),
        encoding="utf-8",
    )


def _write_qa_anticipated(paths: dp.DraftPaths, mode: str, *,
                          nested: bool = False) -> None:
    paths.slides_dir.mkdir(parents=True, exist_ok=True)
    if nested:
        envelope = {"kind": "qa_anticipated_set",
                    "qa_anticipated_set": {"mode": mode, "items": []}}
    else:
        envelope = {"kind": "qa_anticipated_set",
                    "mode": mode, "items": []}
    (paths.slides_dir / "qa_anticipated.json").write_text(
        json.dumps(envelope), encoding="utf-8",
    )


def test_dp9_resolve_mode_from_slide_spec(initialized_draft):
    _write_slide_spec(initialized_draft, "talk-45")
    assert mc.resolve_mode_from_slide_spec(initialized_draft.draft_dir) == \
        "talk-45"


def test_dp9_resolve_mode_missing_returns_none(initialized_draft):
    assert mc.resolve_mode_from_slide_spec(initialized_draft.draft_dir) is None


def test_dp9_resolve_mode_invalid_returns_none(initialized_draft, tmp_path):
    # Write a slide_spec.json carrying a mode not in MODES.
    initialized_draft.working.mkdir(parents=True, exist_ok=True)
    (initialized_draft.working / "slide_spec.json").write_text(
        json.dumps({"mode": "talk-bogus"}), encoding="utf-8",
    )
    assert mc.resolve_mode_from_slide_spec(initialized_draft.draft_dir) is None


def test_dp9_consistency_no_artifacts_passes(initialized_draft):
    """Nothing on disk → nothing to compare → consistent."""
    assert mc.check_mode_consistency(
        initialized_draft.draft_dir, run_mode="talk-30") == []


def test_dp9_consistency_all_matching_passes(initialized_draft):
    _write_slide_spec(initialized_draft, "talk-45")
    _write_image_decisions(initialized_draft, "talk-45")
    _write_qa_anticipated(initialized_draft, "talk-45")
    assert mc.check_mode_consistency(
        initialized_draft.draft_dir, run_mode="talk-45") == []


def test_dp9_consistency_image_decisions_mismatch_fails(initialized_draft):
    """The caulobacter failure: slide_spec.json is talk-45 but
    05_image_decisions.json (written by a resumed image_gen stage that
    silently defaulted MODE=talk-30) records talk-30."""
    _write_slide_spec(initialized_draft, "talk-45")
    _write_image_decisions(initialized_draft, "talk-30")
    findings = mc.check_mode_consistency(
        initialized_draft.draft_dir, run_mode="talk-45")
    assert len(findings) == 1
    assert "05_image_decisions.json" in findings[0]
    assert "'talk-30'" in findings[0]
    assert "'talk-45'" in findings[0]


def test_dp9_consistency_qa_anticipated_mismatch_fails(initialized_draft):
    _write_slide_spec(initialized_draft, "talk-45")
    _write_qa_anticipated(initialized_draft, "talk-30")
    findings = mc.check_mode_consistency(
        initialized_draft.draft_dir, run_mode="talk-45")
    assert len(findings) == 1
    assert "qa_anticipated.json" in findings[0]


def test_dp9_consistency_qa_nested_mode_also_caught(initialized_draft):
    """The qa fragment shape sometimes nests mode under
    qa_anticipated_set; the check looks one level deep."""
    _write_slide_spec(initialized_draft, "talk-45")
    _write_qa_anticipated(initialized_draft, "talk-30", nested=True)
    findings = mc.check_mode_consistency(
        initialized_draft.draft_dir, run_mode="talk-45")
    assert len(findings) == 1
    assert "qa_anticipated.json" in findings[0]


def test_dp9_consistency_multiple_mismatches_all_surface(initialized_draft):
    _write_slide_spec(initialized_draft, "talk-30")  # wrong vs run
    _write_image_decisions(initialized_draft, "talk-30")
    _write_qa_anticipated(initialized_draft, "talk-30")
    findings = mc.check_mode_consistency(
        initialized_draft.draft_dir, run_mode="talk-45")
    assert len(findings) == 3


def test_dp9_cli_resolve_prints_persisted_mode(initialized_draft, capsys):
    _write_slide_spec(initialized_draft, "talk-45")
    rc = mc.main(["resolve-mode", str(initialized_draft.draft_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "talk-45"


def test_dp9_cli_resolve_prints_fallback_when_missing(
        initialized_draft, capsys):
    rc = mc.main(["resolve-mode", str(initialized_draft.draft_dir),
                  "--fallback", "talk-30"])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "talk-30"


def test_dp9_cli_check_consistency_passes_on_match(
        initialized_draft, capsys):
    _write_slide_spec(initialized_draft, "talk-45")
    rc = mc.main(["check-consistency", str(initialized_draft.draft_dir),
                  "--run-mode", "talk-45"])
    assert rc == 0


def test_dp9_cli_check_consistency_fails_on_mismatch(
        initialized_draft, capsys):
    _write_slide_spec(initialized_draft, "talk-45")
    _write_image_decisions(initialized_draft, "talk-30")
    rc = mc.main(["check-consistency", str(initialized_draft.draft_dir),
                  "--run-mode", "talk-45"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "05_image_decisions.json" in err


def test_dp9_cli_check_consistency_invalid_run_mode_exits_2(
        initialized_draft, capsys):
    rc = mc.main(["check-consistency", str(initialized_draft.draft_dir),
                  "--run-mode", "talk-bogus"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Fix 4 — assemble path resolution prefers working/slide_spec.json
# ---------------------------------------------------------------------------


def _load_assemble_command():
    """Import the `beril_presentation_maker.commands.assemble` module
    by path so the test doesn't depend on the package being installed
    in the test env."""
    if "_v111_assemble_cmd" in sys.modules:
        return sys.modules["_v111_assemble_cmd"]
    from importlib.util import module_from_spec, spec_from_file_location
    cmd_py = (_REPO_ROOT / "src" / "beril_presentation_maker"
              / "commands" / "assemble.py")
    spec = spec_from_file_location("_v111_assemble_cmd", cmd_py)
    mod = module_from_spec(spec)
    sys.modules["_v111_assemble_cmd"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_fix4_prefers_working_path(tmp_path):
    """working/slide_spec.json exists → resolver picks it (the 4-zone
    layout)."""
    asm_cmd = _load_assemble_command()
    (tmp_path / "working").mkdir()
    working_spec = tmp_path / "working" / "slide_spec.json"
    working_spec.write_text("{}")
    resolved = asm_cmd._resolve_spec_path(tmp_path)
    assert resolved == working_spec


def test_fix4_falls_back_to_flat(tmp_path):
    """No working/ — flat path still works (backward-compat)."""
    asm_cmd = _load_assemble_command()
    flat_spec = tmp_path / "slide_spec.json"
    flat_spec.write_text("{}")
    resolved = asm_cmd._resolve_spec_path(tmp_path)
    assert resolved == flat_spec


def test_fix4_prefers_working_even_when_flat_exists(tmp_path):
    """Both exist (legacy + 4-zone side by side) → working/ wins.
    The 4-zone path is what the pipeline writes; the flat one may be
    a stale manual copy."""
    asm_cmd = _load_assemble_command()
    (tmp_path / "working").mkdir()
    working_spec = tmp_path / "working" / "slide_spec.json"
    working_spec.write_text('{"mode": "talk-45"}')
    flat_spec = tmp_path / "slide_spec.json"
    flat_spec.write_text('{"mode": "talk-30"}')
    resolved = asm_cmd._resolve_spec_path(tmp_path)
    assert resolved == working_spec


def test_fix4_returns_none_when_neither_exists(tmp_path):
    asm_cmd = _load_assemble_command()
    assert asm_cmd._resolve_spec_path(tmp_path) is None
