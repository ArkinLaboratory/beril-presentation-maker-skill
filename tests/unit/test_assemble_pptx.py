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
    assert result.n_slides == 15
    assert out.is_file()
    prs = Presentation(out)
    assert len(prs.slides) == 15
    layouts_used = {s.slide_layout.name for s in prs.slides}
    assert layouts_used == set(ss.LAYOUTS)


@requires_master
def test_assemble_returns_warnings_for_missing_figures(ss, asm, tmp_path):
    spec = ss.example_slide_spec()
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    out = tmp_path / "slides.pptx"

    result = asm.assemble(spec_path, out)
    # data_figure and concept_illustration's figures aren't present;
    # workflow_diagram emits a stub warning. Total ≥ 3 expected.
    assert len(result.warnings) >= 3
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
    assert result.n_slides == 15


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
