"""Tests for tools/build_master.py — derived master template integrity.

These tests verify the v0.1.0-master-draft phase output:

- Build is reproducible (idempotency).
- 15 named layouts present in the derived master.
- Exactly 1 slide master in the output (no Google Slides duplicate).
- Brand-tokens JSON has the expected schema and the canonical Style
  Guide June 2022 values.
- Every named layout has at least one TITLE placeholder.
- Round-trip: a deck assembled using each layout opens cleanly.

Source .potx is gitignored (user-supplied). Tests skip with a clear
message when source is absent.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_POTX = REPO_ROOT / "reference" / "master-template-source" / "KBase 2026 and beyond.potx"
DEST_PPTX = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
             / "references" / "templates" / "kbase-presentation-master.pptx")
BRAND_JSON = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
              / "references" / "kbase-brand-tokens.json")
BUILD_SCRIPT = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                / "tools" / "build_master.py")


def _import_build_master():
    """Import build_master.py as a module (it lives outside the package
    Python namespace so we load it by file path)."""
    spec = importlib.util.spec_from_file_location("build_master", BUILD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load build_master from {BUILD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures + skip-marks
# ---------------------------------------------------------------------------

requires_source = pytest.mark.skipif(
    not SOURCE_POTX.is_file(),
    reason=f"Source .potx absent at {SOURCE_POTX} — gitignored, user-supplied",
)

requires_built_master = pytest.mark.skipif(
    not DEST_PPTX.is_file(),
    reason=f"Built master absent at {DEST_PPTX} — run build_master.py first",
)


# ---------------------------------------------------------------------------
# Constant tests (no .potx required)
# ---------------------------------------------------------------------------

def test_named_vocabulary_is_15_unique():
    bm = _import_build_master()
    assert len(bm.NAMED_VOCABULARY) == 15
    assert len(set(bm.NAMED_VOCABULARY)) == 15


def test_layout_renames_keys_match_vocabulary_size():
    bm = _import_build_master()
    assert len(bm.LAYOUT_RENAMES) == 15
    assert set(bm.LAYOUT_RENAMES.values()) == set(bm.NAMED_VOCABULARY)


def test_brand_tokens_constant_has_expected_keys():
    bm = _import_build_master()
    bt = bm.BRAND_TOKENS
    assert bt["version"] == "1.0"
    assert "KBase Style Guide" in bt["source"] or "Style Guidelines" in bt["source"]
    assert set(bt["palette"]["primary"].keys()) == {
        "microbe_orange", "grass_green", "freshwater_blue",
        "golden_yellow", "spring_green", "ocean_blue",
    }
    assert set(bt["palette"]["secondary"].keys()) == {
        "cyanobacteria_teal", "lupine_purple", "frost_blue",
        "rainier_cherry_red", "graphite_gray",
    }
    # Spot-check a canonical hex from KBase Style Guide June 2022
    assert bt["palette"]["primary"]["microbe_orange"]["hex"] == "#F78E1E"
    assert bt["palette"]["primary"]["freshwater_blue"]["hex"] == "#007DC3"
    # Forbidden contrast pair documented per Style Guide §5
    pairs = [tuple(w["pair"]) for w in bt["palette"]["contrast_warnings"]]
    assert ("spring_green", "golden_yellow") in pairs


def test_brand_tokens_typography_min_sizes():
    """SPEC §6.3 mandates 24-pt body and 36-pt content title minima.
    Brand tokens must reflect those sizes."""
    bm = _import_build_master()
    sizes = bm.BRAND_TOKENS["typography"]["sizes_pt"]
    assert sizes["body"] >= 24
    assert sizes["content_title"] >= 36


# ---------------------------------------------------------------------------
# Built-master tests (require build to have run successfully)
# ---------------------------------------------------------------------------

@requires_built_master
def test_derived_master_has_one_slide_master():
    from pptx import Presentation
    prs = Presentation(DEST_PPTX)
    assert len(prs.slide_masters) == 1, (
        f"derived master should have exactly 1 slide master "
        f"(Google Slides duplicate removed), got {len(prs.slide_masters)}"
    )


@requires_built_master
def test_derived_master_has_15_named_layouts():
    from pptx import Presentation
    bm = _import_build_master()
    prs = Presentation(DEST_PPTX)
    layouts = list(prs.slide_masters[0].slide_layouts)
    found = sorted(l.name for l in layouts)
    expected = sorted(bm.NAMED_VOCABULARY)
    assert found == expected, (
        f"layout name set mismatch:\n"
        f"  found:    {found}\n"
        f"  expected: {expected}"
    )


@requires_built_master
def test_every_layout_has_title_placeholder():
    from pptx import Presentation
    prs = Presentation(DEST_PPTX)
    failures = []
    for layout in prs.slide_masters[0].slide_layouts:
        has_title = any(
            ph.placeholder_format.idx == 0
            for ph in layout.placeholders
        )
        if not has_title:
            failures.append(layout.name)
    assert not failures, f"layouts missing TITLE placeholder: {failures}"


@requires_built_master
def test_derived_master_ships_no_slides():
    """The master ships as a template with 0 slides; the assembler creates
    fresh slides per draft. SPEC §14 / D-007."""
    from pptx import Presentation
    prs = Presentation(DEST_PPTX)
    assert len(prs.slides) == 0, (
        f"derived master should ship empty (0 slides), found {len(prs.slides)}"
    )


@requires_built_master
def test_brand_tokens_json_on_disk_matches_constant():
    bm = _import_build_master()
    on_disk = json.loads(BRAND_JSON.read_text(encoding="utf-8"))
    # JSON-roundtrip the constant for comparison
    expected = json.loads(json.dumps(bm.BRAND_TOKENS))
    assert on_disk == expected


@requires_built_master
def test_big_number_title_is_centered_and_large():
    """Adam's 2026-04-26 visual review surfaced that the source .potx places
    big_number's TITLE in a tiny strip at the top. The fix in build_master.py
    repositions the TITLE to a large centered area with bold 66pt centered text.

    See LAYOUT_FIXES['big_number'] for rationale. This test pins the fix so
    a future regenerated master can't silently drift back to the source's
    tiny-header-strip default.
    """
    from pptx import Presentation
    bm = _import_build_master()

    A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
    P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"

    prs = Presentation(DEST_PPTX)
    layouts = {l.name: l for l in prs.slide_masters[0].slide_layouts}
    big = layouts["big_number"]

    # Find the TITLE shape (placeholder type=title or idx=0)
    title_sp = None
    for sp in big.element.iter(f"{{{P_NS}}}sp"):
        ph = sp.find(f".//{{{P_NS}}}nvSpPr/{{{P_NS}}}nvPr/{{{P_NS}}}ph")
        if ph is not None and (ph.get("type") == "title" or ph.get("idx", "0") == "0"):
            title_sp = sp
            break
    assert title_sp is not None, "big_number layout has no TITLE placeholder"

    # 1. Position: large centered area (~0.7, 1.0, 8.6 × 3.6 in)
    off = title_sp.find(f".//{{{A_NS}}}xfrm/{{{A_NS}}}off")
    ext = title_sp.find(f".//{{{A_NS}}}xfrm/{{{A_NS}}}ext")
    assert off is not None and ext is not None
    expected = bm.LAYOUT_FIXES["big_number"]["title_xfrm"]
    assert int(off.get("x")) == expected["off_x"]
    assert int(off.get("y")) == expected["off_y"]
    assert int(ext.get("cx")) == expected["ext_cx"]
    assert int(ext.get("cy")) == expected["ext_cy"]

    # 2. Body anchor + autofit
    body_pr = title_sp.find(f".//{{{P_NS}}}txBody/{{{A_NS}}}bodyPr")
    assert body_pr is not None
    assert body_pr.get("anchor") == "ctr"
    # Has noAutofit, not normAutofit
    has_noautofit = body_pr.find(f"{{{A_NS}}}noAutofit") is not None
    has_normautofit = body_pr.find(f"{{{A_NS}}}normAutofit") is not None
    assert has_noautofit and not has_normautofit, (
        "big_number TITLE must use <a:noAutofit/>, not <a:normAutofit/>"
    )

    # 3. Horizontal alignment
    lvl1 = title_sp.find(f".//{{{A_NS}}}lstStyle/{{{A_NS}}}lvl1pPr")
    assert lvl1 is not None
    assert lvl1.get("algn") == "ctr"

    # 4. Font size + bold
    def_rpr = lvl1.find(f"{{{A_NS}}}defRPr")
    assert def_rpr is not None
    assert def_rpr.get("sz") == "6600"  # 66pt
    assert def_rpr.get("b") == "1"      # bold


@requires_built_master
def test_two_column_compare_has_two_body_placeholders():
    """The two_column_compare layout is the only one with 2 BODY placeholders;
    failure here means we mapped the wrong source layout."""
    from pptx import Presentation
    prs = Presentation(DEST_PPTX)
    layouts = {l.name: l for l in prs.slide_masters[0].slide_layouts}
    layout = layouts["two_column_compare"]
    body_count = sum(
        1 for ph in layout.placeholders
        if ph.placeholder_format.type is not None
        and "BODY" in str(ph.placeholder_format.type)
    )
    assert body_count == 2, (
        f"two_column_compare should have exactly 2 BODY placeholders, got {body_count}"
    )


# ---------------------------------------------------------------------------
# Idempotency (requires source .potx — skipped in CI without it)
# ---------------------------------------------------------------------------

@requires_source
def test_build_is_idempotent(tmp_path: Path):
    """Two builds from the same source .potx produce byte-identical zip
    contents (modulo zip-internal timestamps; we compare unzipped XML)."""
    bm = _import_build_master()
    out1 = tmp_path / "build1.pptx"
    out2 = tmp_path / "build2.pptx"
    bt1 = tmp_path / "tokens1.json"
    bt2 = tmp_path / "tokens2.json"

    bm.build_master(SOURCE_POTX, out1, bt1, verbose=False)
    bm.build_master(SOURCE_POTX, out2, bt2, verbose=False)

    import zipfile
    with zipfile.ZipFile(out1) as z1, zipfile.ZipFile(out2) as z2:
        names1 = sorted(z1.namelist())
        names2 = sorted(z2.namelist())
        assert names1 == names2, "zip member set differs across rebuilds"
        # Compare each member's contents
        for name in names1:
            assert z1.read(name) == z2.read(name), (
                f"member '{name}' differs across rebuilds"
            )

    # JSON outputs are also byte-identical
    assert bt1.read_bytes() == bt2.read_bytes()


@requires_source
def test_build_emits_expected_report_keys(tmp_path: Path):
    bm = _import_build_master()
    out = tmp_path / "build.pptx"
    bt = tmp_path / "tokens.json"
    report = bm.build_master(SOURCE_POTX, out, bt, verbose=False)
    assert set(report.keys()) >= {
        "source", "dest_master", "dest_brand_tokens",
        "renamed_layouts", "deleted_layouts", "deleted_masters",
        "deleted_slides_count", "applied_fixes",
        "dest_master_sha256", "dest_master_size_bytes",
    }
    # Must rename exactly 15 layouts and delete the 17 unused ones
    assert len(report["renamed_layouts"]) == 15
    assert len(report["deleted_layouts"]) == 17
    # The Google Slides duplicate master should have been removed
    assert len(report["deleted_masters"]) == 1
    # The big_number layout fix must have been applied
    assert "big_number" in report["applied_fixes"]


@requires_source
def test_build_strips_all_source_slides(tmp_path: Path):
    """The source .potx contains 32 example slides (the Gazi 2026 deck);
    the derived master must ship zero slides."""
    bm = _import_build_master()
    out = tmp_path / "build.pptx"
    bt = tmp_path / "tokens.json"
    report = bm.build_master(SOURCE_POTX, out, bt, verbose=False)
    # The .potx Adam supplied has 32 slides
    assert report["deleted_slides_count"] >= 30, (
        f"expected ≥30 slides stripped from .potx (Gazi 2026 deck), "
        f"got {report['deleted_slides_count']}"
    )


# ---------------------------------------------------------------------------
# Round-trip: assemble a sample deck using each layout
# ---------------------------------------------------------------------------

@requires_built_master
def test_round_trip_one_slide_per_layout(tmp_path: Path):
    """Programmatically build a sample deck that uses every named layout
    once. Verify it saves and re-opens without error.

    This is the foundational test for the assembler that v0.1.0-extractors
    will build on. If a layout is structurally broken, this test catches it."""
    from pptx import Presentation
    bm = _import_build_master()

    prs = Presentation(DEST_PPTX)
    layouts = {l.name: l for l in prs.slide_masters[0].slide_layouts}

    for name in bm.NAMED_VOCABULARY:
        assert name in layouts, f"layout '{name}' missing in derived master"
        layout = layouts[name]
        slide = prs.slides.add_slide(layout)
        # Set the title placeholder if available
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text = f"Sample slide for layout '{name}'"
                break

    out = tmp_path / "round_trip.pptx"
    prs.save(out)
    # Re-open to confirm the file is structurally valid
    prs2 = Presentation(out)
    assert len(prs2.slides) == 15
    assert {s.slide_layout.name for s in prs2.slides} == set(bm.NAMED_VOCABULARY)
