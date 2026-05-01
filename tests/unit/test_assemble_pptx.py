"""Tests for assemble_pptx.py — slide_spec.json → .pptx rendering.

Coverage targets:
- Round-trip: example_slide_spec → 15 slides on output.
- Each layout: handler runs without error; placeholders filled.
- Figure path resolution: relative paths resolve against draft_dir.
- Missing figure: warning collected, slide still renders.
- Speaker notes: written to slide.notes_slide.
- Validator pre-flight: invalid spec → AssemblyError before any slide writes.
- Master template: defaults to the shipped one; can be overridden.
- CLI surface: validate, --out, --strict, --format pdf fallback.
"""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
import zlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SLIDE_SPEC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                 / "tools" / "slide_spec.py")
ASSEMBLE_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "tools" / "assemble_pptx.py")
MASTER_PPTX = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "references" / "templates" / "kbase-presentation-master.pptx")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ss():
    return _import("slide_spec", SLIDE_SPEC_PY)


@pytest.fixture(scope="module")
def asm():
    # Ensure slide_spec is loaded first (assemble_pptx imports it via
    # its own importlib).
    _import("slide_spec", SLIDE_SPEC_PY)
    return _import("assemble_pptx", ASSEMBLE_PY)


requires_master = pytest.mark.skipif(
    not MASTER_PPTX.is_file(),
    reason=f"Master not built; run build_master.py first ({MASTER_PPTX})",
)


def _make_tiny_png(path: Path, size: int = 16) -> Path:
    """Write a minimal valid PNG (single-color square) for figure-asset tests."""
    # 8-byte signature + IHDR + IDAT + IEND
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR",
                 struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))  # 8-bit RGB
    raw = b"".join(b"\x00" + b"\xa0\xc0\xe0" * size for _ in range(size))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    path.write_bytes(sig + ihdr + idat + iend)
    return path


# ---------------------------------------------------------------------------
# Smoke-level: example_slide_spec → assembled .pptx
# ---------------------------------------------------------------------------

@requires_master
def test_assemble_example_spec_smoke(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))

    out = tmp_path / "slides.pptx"
    result = asm.assemble(spec_path, out)

    from pptx import Presentation
    assert result.n_slides == 16  # v0.3.2: + data_table
    assert out.is_file()
    prs = Presentation(out)
    assert len(prs.slides) == 16  # v0.3.2: + data_table
    layouts_used = {s.slide_layout.name for s in prs.slides}
    # data_table is aliased to data_figure's master layout — so the master-
    # layout names cover 15 of the 16 spec layouts (data_table reuses
    # data_figure's master).
    expected_master_layouts = set(ss.LAYOUTS) - {"data_table"}
    assert layouts_used == expected_master_layouts


@requires_master
def test_assemble_returns_warnings_for_missing_figures(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    result = asm.assemble(spec_path, out)
    # data_figure and concept_illustration's figures aren't present in the
    # example spec → 2 missing-asset warnings. (Earlier expected ≥3 — that
    # was implicitly counting the workflow_diagram NoneType crash dressed
    # up as a warning. The 2026-04-26 fix to assemble_pptx.py registers
    # diagram_render in sys.modules before exec_module, so the diagram
    # now renders cleanly and emits no warning.)
    assert len(result.warnings) >= 2
    warning_text = " | ".join(result.warnings)
    assert "data_figure" in warning_text
    assert "concept_illustration" in warning_text
    # The diagram render bug from before should NOT appear
    assert "diagram render failed" not in warning_text
    # Slide still renders
    assert out.is_file()


@requires_master
def test_strict_mode_raises_on_warning(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    with pytest.raises(asm.AssemblyError):
        asm.assemble(spec_path, out, strict=True)


# ---------------------------------------------------------------------------
# Validator pre-flight — refuse to render bad spec
# ---------------------------------------------------------------------------

@requires_master
def test_invalid_spec_rejected_before_render(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec["mode"] = "talk-90"   # invalid
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    with pytest.raises(asm.AssemblyError) as exc:
        asm.assemble(spec_path, out)
    assert "schema validation" in str(exc.value)
    assert not out.exists()   # nothing written on failure


def test_missing_slide_spec_file_raises(asm, tmp_path):
    with pytest.raises(asm.AssemblyError):
        asm.assemble(tmp_path / "nope.json", tmp_path / "out.pptx")


# ---------------------------------------------------------------------------
# Figure path resolution
# ---------------------------------------------------------------------------

@requires_master
def test_relative_figure_path_resolves_against_draft_dir(ss, asm, tmp_path):
    # Place the PNG at <tmp>/figures/fig01.png
    fig_dir = tmp_path / "figures"
    fig_dir.mkdir(exist_ok=True)
    _make_tiny_png(fig_dir / "fig01.png")

    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [
            ss.example_slide("data_figure", slide_id=1, substory_id=None),
        ],
    }
    spec["slides"][0]["content"]["figure"] = "figures/fig01.png"

    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    result = asm.assemble(spec_path, out)
    # Relative path must have resolved successfully — no asset warning
    asset_warnings = [w for w in result.warnings if "asset not found" in w]
    assert asset_warnings == []


@requires_master
def test_absolute_figure_path_works(ss, asm, tmp_path):
    fig = _make_tiny_png(tmp_path / "fig.png")

    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [ss.example_slide("data_figure", slide_id=1, substory_id=None)],
    }
    spec["slides"][0]["content"]["figure"] = str(fig.resolve())

    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"
    result = asm.assemble(spec_path, out)
    asset_warnings = [w for w in result.warnings if "asset not found" in w]
    assert asset_warnings == []


# ---------------------------------------------------------------------------
# Per-layout placeholder filling
# ---------------------------------------------------------------------------

@requires_master
@pytest.mark.parametrize("layout", [
    "title", "section_divider", "big_idea", "big_number",
    "claim_evidence", "two_column_compare", "data_figure",
    "workflow_diagram", "methods_summary", "concept_illustration",
    "cross_tenant_integration", "implications", "acknowledgments",
    "references", "qa_anticipated",
])
def test_each_layout_renders(ss, asm, tmp_path, layout):
    """Build a one-slide spec per layout. Assert it renders without raising
    and that a non-empty title is set on the output slide."""
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [ss.example_slide(layout, slide_id=1, substory_id=None)],
    }
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    result = asm.assemble(spec_path, out)
    assert result.n_slides == 1

    from pptx import Presentation
    prs = Presentation(out)
    assert len(prs.slides) == 1
    rendered = prs.slides[0]
    assert rendered.slide_layout.name == layout
    # Title placeholder always set (acknowledgments/references hard-code it,
    # the rest pull from content).
    if rendered.shapes.title:
        assert rendered.shapes.title.text != ""


@requires_master
def test_slide_level_title_autofit_landed(ss, asm, tmp_path):
    """2026-04-26 fix #63: slide-level normAutofit must be set on title
    placeholders (layout-level autofit alone doesn't trigger at render).
    Verify every slide except big_number/big_idea has slide-level
    normAutofit fontScale=80000 + anchor=t on its title placeholder.
    """
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"
    asm.assemble(spec_path, out)

    from pptx import Presentation
    P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
    A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

    prs = Presentation(out)
    failures = []
    intentional_no_autofit = {"big_number", "big_idea"}

    for i, slide in enumerate(prs.slides, 1):
        if slide.slide_layout.name in intentional_no_autofit:
            continue
        if not slide.shapes.title:
            continue
        title = slide.shapes.title
        body_pr = title.element.find(f"{{{P_NS}}}txBody/{{{A_NS}}}bodyPr")
        if body_pr is None:
            failures.append(
                f"slide {i} ({slide.slide_layout.name}): title has no bodyPr"
            )
            continue
        norm = body_pr.find(f"{{{A_NS}}}normAutofit")
        if norm is None:
            failures.append(
                f"slide {i} ({slide.slide_layout.name}): "
                f"missing slide-level <a:normAutofit/>"
            )
            continue
        if norm.get("fontScale") != "80000":
            failures.append(
                f"slide {i} ({slide.slide_layout.name}): "
                f"fontScale={norm.get('fontScale')!r}, expected '80000'"
            )
        if body_pr.get("anchor") != "t":
            failures.append(
                f"slide {i} ({slide.slide_layout.name}): "
                f"anchor={body_pr.get('anchor')!r}, expected 't'"
            )

    assert not failures, "\n  ".join(failures)


@requires_master
def test_methods_summary_renders_tools_versions(ss, asm, tmp_path):
    """2026-04-26 fix #59: tools_versions now renders as a footer band
    (was silently dropped before). Build a methods_summary slide with
    real tool/version pairs and assert the formatted footer text appears
    on the rendered slide.
    """
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{
            "id": 1,
            "layout": "methods_summary",
            "content": {
                "title": "Methods overview",
                "bullets": [
                    "Quality-trim with fastp at Q20",
                    "Annotate with RAST default parameters",
                    "Cross-validate against Morgan Price gold standard",
                    "FDR correction via Benjamini-Hochberg",
                    "Recovery rate computed across n=142 loci",
                ],
                "tools_versions": [
                    {"tool": "RAST", "version": "2.0"},
                    {"tool": "fastp", "version": "0.23"},
                    {"tool": "DRAM", "version": "1.4"},
                ],
            },
        }],
    }
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    asm.assemble(spec_path, out)

    from pptx import Presentation
    prs = Presentation(out)
    slide = prs.slides[0]

    # Walk all text-bearing shapes; check for the tools_versions footer
    all_text = " | ".join(
        shape.text_frame.text for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "RAST 2.0" in all_text, f"RAST version missing; got: {all_text}"
    assert "fastp 0.23" in all_text, f"fastp version missing; got: {all_text}"
    assert "DRAM 1.4" in all_text, f"DRAM version missing; got: {all_text}"
    # The "see speaker notes" fallback should NOT appear when tools_versions present
    assert "see speaker notes" not in all_text, (
        "fallback footer should be suppressed when tools_versions populated"
    )


@requires_master
def test_methods_summary_falls_back_to_speaker_notes_hint(ss, asm, tmp_path):
    """When tools_versions is absent, the see-notes footer renders."""
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{
            "id": 1,
            "layout": "methods_summary",
            "content": {
                "title": "Methods overview",
                "bullets": ["b1", "b2", "b3", "b4", "b5"],
                # No tools_versions
            },
        }],
    }
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    asm.assemble(spec_path, out)
    from pptx import Presentation
    slide = Presentation(out).slides[0]
    all_text = " | ".join(
        shape.text_frame.text for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "see speaker notes" in all_text


# ---------------------------------------------------------------------------
# Speaker notes
# ---------------------------------------------------------------------------

@requires_master
def test_speaker_notes_written_to_notes_slide(ss, asm, tmp_path):
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [ss.example_slide("claim_evidence", slide_id=1, substory_id=None)],
    }
    notes_text = "Speaker notes for slide 1: Smith 2023 showed 90% accuracy."
    spec["slides"][0]["speaker_notes"] = notes_text

    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    asm.assemble(spec_path, out)

    from pptx import Presentation
    prs = Presentation(out)
    notes = prs.slides[0].notes_slide.notes_text_frame.text
    assert notes_text in notes


# ---------------------------------------------------------------------------
# Title-rule exemptions: acknowledgments + references hard-code their titles
# ---------------------------------------------------------------------------

@requires_master
def test_acknowledgments_title_hardcoded(ss, asm, tmp_path):
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [ss.example_slide("acknowledgments", slide_id=1, substory_id=None)],
    }
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"
    asm.assemble(spec_path, out)

    from pptx import Presentation
    prs = Presentation(out)
    assert prs.slides[0].shapes.title.text == "Acknowledgments"


@requires_master
def test_references_title_hardcoded(ss, asm, tmp_path):
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [ss.example_slide("references", slide_id=1, substory_id=None)],
    }
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"
    asm.assemble(spec_path, out)

    from pptx import Presentation
    prs = Presentation(out)
    assert prs.slides[0].shapes.title.text == "References"


# ---------------------------------------------------------------------------
# Master override
# ---------------------------------------------------------------------------

@requires_master
def test_master_path_override(ss, asm, tmp_path):
    """Custom master_path is honored. Use the shipped master copied to a
    side path so we know the override is active."""
    custom = tmp_path / "custom_master.pptx"
    custom.write_bytes(MASTER_PPTX.read_bytes())

    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    result = asm.assemble(spec_path, out, master_path=custom)
    assert result.n_slides == 16  # v0.3.2: + data_table


def test_default_master_path_resolves(asm):
    p = asm.default_master_path()
    assert p.is_file()
    assert p.name == "kbase-presentation-master.pptx"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

@requires_master
def test_cli_assemble_clean(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    rc = asm.main([str(spec_path), "--out", str(out)])
    assert rc == 0
    assert out.is_file()


@requires_master
def test_cli_assemble_invalid_spec_returns_2(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec["mode"] = "talk-90"
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    rc = asm.main([str(spec_path), "--out", str(out)])
    assert rc == 2


@requires_master
def test_cli_pdf_fallback_when_no_libreoffice(ss, asm, tmp_path, monkeypatch):
    """If soffice not on PATH, --format pdf must emit pptx + clear message,
    not crash."""
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    # Force render_pdf to return None (simulates missing soffice)
    monkeypatch.setattr(asm, "render_pdf", lambda p: None)
    rc = asm.main([str(spec_path), "--out", str(out), "--format", "pdf"])
    assert rc == 0
    assert out.is_file()  # pptx still emitted


# ---------------------------------------------------------------------------
# Empty / minimal handling
# ---------------------------------------------------------------------------

@requires_master
def test_layout_handlers_dispatch_covers_full_vocabulary(ss, asm):
    """Every named layout has a handler registered. Pins the dispatch
    table so a future layout addition can't slip through unnoticed."""
    assert set(asm.LAYOUT_HANDLERS.keys()) == set(ss.LAYOUTS)
