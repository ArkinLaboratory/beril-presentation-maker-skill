#!/usr/bin/env python3
"""assemble_pptx.py — render a validated slide_spec.json to a .pptx file.

Consumes slide_spec.json (per the contract in slide_spec.py) and writes
slides.pptx using the shipped KBase-branded master with 15 named layouts.

Pipeline:
  1. Load slide_spec.json.
  2. Validate against slide_spec.py (pre-flight; refuse to render invalid).
  3. Open the master template (kbase-presentation-master.pptx).
  4. For each slide in spec.slides:
       - Look up layout by name.
       - Add a new slide using that layout.
       - Dispatch to the layout-specific handler that fills placeholders +
         freeform shapes (figures, captions, footers).
       - Set speaker notes if present.
  5. Save to <out_path>.

PDF render (--format pdf) is delegated to LibreOffice (`soffice
--headless --convert-to pdf`). If LibreOffice is absent, the assembler
emits .pptx only and prints a clear message — pure-Python deps stay
the same. (D-016 pattern.)

Diagram rendering (workflow_diagram, cross_tenant_integration's optional
data_flow_diagram) is a STUB in this commit. The full implementation
ships in v0.1.0-extractors-c via diagram_render.py. The stub emits a
placeholder text box that says what the diagram should be — preserves
the slide structure and lets validators run end-to-end.

CLI:

    python3 assemble_pptx.py <slide_spec.json> --out <out.pptx>
                             [--master <override.pptx>]
                             [--format pptx|pdf]
                             [--strict]   # fail on any warning

Library:

    from assemble_pptx import assemble, AssemblyResult
    result = assemble("path/to/slide_spec.json", "out.pptx")
    print(result.warnings)

References:
  - SPEC §6 (slide vocabulary), §14.2 (slide_spec contract)
  - LAYOUT_FIXES in build_master.py for layout placeholder positions
  - slide_spec.py for the validator + types
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor


# ---------------------------------------------------------------------------
# Master template discovery
# ---------------------------------------------------------------------------

# When this module is imported as a library, the master ships under
# `references/templates/kbase-presentation-master.pptx` next to it. When
# executed as a script, we resolve via the file path.
_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_MASTER = (_THIS_DIR.parent / "references" / "templates"
                   / "kbase-presentation-master.pptx")


def default_master_path() -> Path:
    """Path to the shipped master template."""
    if not _DEFAULT_MASTER.is_file():
        raise FileNotFoundError(
            f"Master template not found at {_DEFAULT_MASTER}. "
            f"Run tools/build_master.py to regenerate."
        )
    return _DEFAULT_MASTER


# ---------------------------------------------------------------------------
# slide_spec.py loader (sibling module)
# ---------------------------------------------------------------------------

def _load_slide_spec_module():
    """Load slide_spec.py from the same directory.

    We don't import via the package namespace because the skill/ tree
    ships as package_data and these tools are invoked as standalone
    scripts (per the orchestrator pattern in
    presentation_maker.sh — Phase 3).
    """
    path = _THIS_DIR / "slide_spec.py"
    spec = importlib.util.spec_from_file_location("slide_spec", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load slide_spec from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["slide_spec"] = module  # for dataclass forward refs
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class AssemblyResult:
    """Returned by assemble(). Holds the output path + any non-fatal warnings."""
    out_path: Path
    n_slides: int
    warnings: list[str] = field(default_factory=list)


class AssemblyError(Exception):
    """Raised when the assembler cannot proceed (e.g., master missing,
    layout not in master, validation failed)."""


# ---------------------------------------------------------------------------
# Placeholder helpers
# ---------------------------------------------------------------------------

def _get_layout_by_name(prs: Presentation, name: str):
    """Look up a layout by name in master 0. Raises AssemblyError if absent."""
    for layout in prs.slide_masters[0].slide_layouts:
        if layout.name == name:
            return layout
    available = sorted(l.name for l in prs.slide_masters[0].slide_layouts)
    raise AssemblyError(
        f"layout '{name}' not in master template. Available: {available}"
    )


def _set_title(slide, text: str) -> None:
    if not slide.shapes.title:
        return
    slide.shapes.title.text = text


def _find_placeholder(slide, idx: int):
    """Return the placeholder with given idx, or None."""
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == idx:
            return ph
    return None


def _set_placeholder_text(slide, idx: int, text: str) -> bool:
    """Set a placeholder's text. Returns True if found, False otherwise."""
    ph = _find_placeholder(slide, idx)
    if ph is None:
        return False
    ph.text = text
    return True


def _set_placeholder_bullets(slide, idx: int, bullets: list[str]) -> bool:
    """Set placeholder text frame to the given list of bullets (one per
    paragraph). Returns True if placeholder found."""
    ph = _find_placeholder(slide, idx)
    if ph is None or not bullets:
        return False
    tf = ph.text_frame
    tf.text = bullets[0]
    for b in bullets[1:]:
        p = tf.add_paragraph()
        p.text = b
    return True


def _remove_placeholder(slide, idx: int) -> bool:
    """Remove a placeholder from the slide entirely (not just clear its text).

    Setting `ph.text = ""` does NOT suppress an empty placeholder's "Click to
    add text" prompt in PowerPoint — the prompt is layout-defined and shows
    whenever the placeholder shape is on the slide. The only reliable way
    to hide it is to remove the placeholder element from the slide's spTree.

    Returns True if a placeholder with the given idx was removed, False if
    none was found.

    Use this for layouts where the body placeholder's region is occupied by
    a freeform figure (data_figure, concept_illustration) — the placeholder
    serves no purpose and its empty prompt visually overlaps the figure.
    """
    ph = _find_placeholder(slide, idx)
    if ph is None:
        return False
    sptree = slide.shapes._spTree
    sptree.remove(ph._element)
    return True


def _set_speaker_notes(slide, text: str) -> None:
    if not text:
        return
    notes = slide.notes_slide
    notes.notes_text_frame.text = text


def _add_picture(slide, image_path: Path,
                 left_in: float, top_in: float,
                 width_in: float, height_in: float):
    """Add a picture at the given inches-position. Returns the picture shape."""
    return slide.shapes.add_picture(
        str(image_path),
        Inches(left_in), Inches(top_in),
        width=Inches(width_in), height=Inches(height_in),
    )


def _add_textbox(slide, text: str,
                 left_in: float, top_in: float,
                 width_in: float, height_in: float,
                 *, font_size_pt: int = 14, bold: bool = False,
                 color_rgb: tuple[int, int, int] | None = None,
                 align_center: bool = False):
    """Add a freeform text box at the given position."""
    tb = slide.shapes.add_textbox(
        Inches(left_in), Inches(top_in),
        Inches(width_in), Inches(height_in),
    )
    tf = tb.text_frame
    tf.text = text
    p = tf.paragraphs[0]
    if align_center:
        from pptx.enum.text import PP_ALIGN
        p.alignment = PP_ALIGN.CENTER
    for run in p.runs:
        run.font.size = Pt(font_size_pt)
        run.font.bold = bold
        if color_rgb:
            run.font.color.rgb = RGBColor(*color_rgb)
    return tb


# ---------------------------------------------------------------------------
# Figure/asset position tables (per layout, when the layout has one figure
# region beyond placeholders). Inches.
# ---------------------------------------------------------------------------

# Slide is 10.0 × 5.625 inches (16:9). Logos sit at y=5.00–5.55 (bottom-
# right) so figure regions stay clear of that band. Body placeholders are
# removed via _remove_placeholder for layouts where the body region is
# occupied by a freeform figure — the placeholder's "Click to add text"
# prompt would otherwise show through.
FIGURE_REGIONS = {
    # Bullets in body placeholder (full width); figure right-side overlay.
    "claim_evidence":       (5.30, 1.30, 4.50, 3.50),
    # Title is in the accent banner (round 3); supporting graphic fills
    # the body area below banner, ABOVE the logos at y=5.00.
    "big_idea":             (1.00, 1.10, 8.00, 3.85),
    # Body placeholder removed; figure fills former body region.
    "data_figure":          (0.50, 1.40, 9.00, 3.10),
    # Body placeholder removed; image on the right of the slide.
    "concept_illustration": (5.30, 1.30, 4.50, 3.70),
}

# Caption/footer regions (overlaid on slide)
CAPTION_BAND = (0.30, 4.95, 9.40, 0.40)   # bottom 0.4-inch strip
CITATION_BAND = (0.30, 5.20, 9.40, 0.30)  # very-bottom strip
AI_DISCLOSURE_BAND = (0.30, 5.30, 9.40, 0.20)  # 8pt graphite-gray

GRAPHITE_GRAY_RGB = (157, 146, 135)  # KBase secondary palette


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_asset_path(rel_or_abs: str, draft_dir: Path,
                       warnings: list[str], where: str) -> Path | None:
    """Resolve a figure / image / logo path. Relative paths are resolved
    against draft_dir. Returns None and appends a warning if file missing."""
    candidate = Path(rel_or_abs)
    if not candidate.is_absolute():
        candidate = draft_dir / candidate
    if not candidate.is_file():
        warnings.append(
            f"{where}: asset not found at {candidate} "
            f"(slide will render with a placeholder note)"
        )
        return None
    return candidate


# ---------------------------------------------------------------------------
# Per-layout handlers
# ---------------------------------------------------------------------------
#
# Each handler signature:
#   _fill_<layout>(slide, content, draft_dir, warnings) -> None
#
# Handlers MAY add freeform shapes. They MUST not assume layouts have
# placeholders beyond what build_master.py guarantees (TITLE on every
# layout; BODY idx 1 on most; BODY idx 2 only on two_column_compare).

def _fill_title(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    parts: list[str] = []
    if content.get("subtitle"):
        parts.append(content["subtitle"])
    presenter_line = content["presenter"]
    if content.get("affiliation"):
        presenter_line = f"{presenter_line} · {content['affiliation']}"
    parts.append(presenter_line)
    if content.get("venue"):
        parts.append(content["venue"])
    parts.append(content["date"])
    _set_placeholder_text(slide, 1, "\n".join(parts))


def _fill_section_divider(slide, content, draft_dir, warnings):
    _set_title(slide, content["punchline"])
    if content.get("substory_number"):
        # Add a small footer with the substory number
        _add_textbox(slide, f"Substory {content['substory_number']}",
                     0.30, 5.10, 4.00, 0.30,
                     font_size_pt=12, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_big_idea(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    if content.get("supporting_graphic"):
        path = _resolve_asset_path(content["supporting_graphic"], draft_dir,
                                   warnings, "big_idea.supporting_graphic")
        if path:
            _add_picture(slide, path, *FIGURE_REGIONS["big_idea"])


def _fill_big_number(slide, content, draft_dir, warnings):
    """big_number's TITLE placeholder is repositioned by build_master.py
    LAYOUT_FIXES to be the huge centered area. We place the headline + a
    smaller subtitle below as a separate text box (the placeholder font is
    66pt bold, and we want subtitle smaller)."""
    _set_title(slide, content["headline"])
    # Subtitle in a separate textbox below the title region.
    # Title region per LAYOUT_FIXES: off (660902,923453) ext (7840301,3286408)
    # = (0.72, 1.01, 8.57 × 3.59 in). Subtitle goes immediately below.
    _add_textbox(slide, content["subtitle"],
                 0.72, 4.65, 8.57, 0.40,
                 font_size_pt=20, align_center=True)
    if content.get("sub_pointer"):
        _add_textbox(slide, content["sub_pointer"],
                     0.72, 5.05, 8.57, 0.30,
                     font_size_pt=12, color_rgb=GRAPHITE_GRAY_RGB,
                     align_center=True)
    if content.get("source_footer"):
        _add_textbox(slide, content["source_footer"],
                     0.30, 5.35, 9.40, 0.20,
                     font_size_pt=10, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_claim_evidence(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    bullets = content["bullets"]
    if content.get("figure"):
        # Bullets in narrower body (left half), figure on right.
        # The layout's BODY placeholder is full-width by default; we can't
        # easily resize it post-hoc. Instead, we add a freeform textbox
        # for the bullets and the figure as a separate shape — and leave
        # the BODY placeholder empty.
        # To keep the named-layout discipline, we'll fill BODY with the
        # bullets and accept that the figure may overlap the right edge
        # of the body region. Position table puts the figure at left=5.30,
        # which is past the body's typical right edge.
        _set_placeholder_bullets(slide, 1, bullets)
        path = _resolve_asset_path(content["figure"], draft_dir, warnings,
                                    "claim_evidence.figure")
        if path:
            _add_picture(slide, path, *FIGURE_REGIONS["claim_evidence"])
            # Caption band below figure (only if figure rendered)
            _add_textbox(slide, content["figure_caption"],
                         5.30, 4.85, 4.50, 0.40,
                         font_size_pt=11, color_rgb=GRAPHITE_GRAY_RGB)
    else:
        _set_placeholder_bullets(slide, 1, bullets)
    if content.get("citations"):
        # short-form citation footer at bottom
        cite_text = " · ".join(content["citations"])
        _add_textbox(slide, cite_text, *CITATION_BAND,
                     font_size_pt=10, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_two_column_compare(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    # Idx 1 = left column, Idx 2 = right column (per master inspection).
    for idx, col_key in [(1, "left_col"), (2, "right_col")]:
        col_title = content[f"{col_key}_title"]
        col_content = content[f"{col_key}_content"]
        ph = _find_placeholder(slide, idx)
        if ph is None:
            warnings.append(
                f"two_column_compare: layout missing BODY idx {idx}"
            )
            continue
        tf = ph.text_frame
        # Column-title as first paragraph (bold)
        tf.text = col_title
        if tf.paragraphs and tf.paragraphs[0].runs:
            tf.paragraphs[0].runs[0].font.bold = True
        # Then the content
        if isinstance(col_content, str):
            p = tf.add_paragraph()
            p.text = col_content
        else:
            for line in col_content:
                p = tf.add_paragraph()
                p.text = line


def _fill_data_figure(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    # Remove the body placeholder entirely — the body region is occupied
    # by the freeform figure + caption + data_source. Setting ph.text = ""
    # is insufficient: the layout-defined "Click to add text" prompt
    # still shows in PowerPoint when the placeholder is present.
    _remove_placeholder(slide, 1)
    path = _resolve_asset_path(content["figure"], draft_dir, warnings,
                                "data_figure.figure")
    if path:
        _add_picture(slide, path, *FIGURE_REGIONS["data_figure"])
    # Caption + data source go in the body region just below the figure,
    # above the bottom logos at y=5.00.
    _add_textbox(slide, content["caption"], 0.50, 4.55, 9.00, 0.30,
                 font_size_pt=12, color_rgb=GRAPHITE_GRAY_RGB)
    if content.get("data_source"):
        _add_textbox(slide, content["data_source"],
                     0.50, 4.85, 9.00, 0.13,
                     font_size_pt=10, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_workflow_diagram(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    # Diagram rendering is a STUB in v0.1.0-extractors-a. The full
    # implementation lands in v0.1.0-extractors-c via diagram_render.py.
    # For now: emit a placeholder note describing what the diagram
    # should be, so the slide structure is preserved end-to-end.
    diagram = content["diagram"]
    n_nodes = len(diagram.get("nodes", []))
    n_edges = len(diagram.get("edges", []))
    placeholder_text = (
        f"[diagram placeholder — kind={diagram.get('kind')}, "
        f"{n_nodes} nodes, {n_edges} edges; "
        f"render lands in v0.1.0-extractors-c]"
    )
    _set_placeholder_bullets(slide, 1, [placeholder_text])
    warnings.append(
        f"workflow_diagram on slide id={slide.slide_id}: diagram "
        f"rendering stubbed (v0.1.0-extractors-a). Full render in "
        f"v0.1.0-extractors-c."
    )
    # Step caption band below
    captions = content["step_caption"]
    _add_textbox(slide, "  ".join(captions), *CAPTION_BAND,
                 font_size_pt=12, color_rgb=GRAPHITE_GRAY_RGB)
    if content.get("tool_version_footer"):
        _add_textbox(slide, content["tool_version_footer"],
                     0.30, 5.30, 9.40, 0.20,
                     font_size_pt=10, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_methods_summary(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    _set_placeholder_bullets(slide, 1, content["bullets"])
    # tools_versions list and see_notes_footer: rendered as footers if present
    if content.get("see_notes_footer", True):
        _add_textbox(slide, "(see speaker notes for full detail)",
                     0.30, 5.20, 9.40, 0.30,
                     font_size_pt=10, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_concept_illustration(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    # The body placeholder on the left is narrowed (per Adam's
    # build_master fix) but v0.1 schema has no body-text field for this
    # layout — remove the placeholder so its empty prompt doesn't show
    # alongside the AI-generated image.
    _remove_placeholder(slide, 1)
    path = _resolve_asset_path(content["image_path"], draft_dir, warnings,
                                "concept_illustration.image_path")
    if path:
        _add_picture(slide, path, *FIGURE_REGIONS["concept_illustration"])
    if content.get("caption"):
        _add_textbox(slide, content["caption"],
                     5.30, 5.05, 4.50, 0.25,
                     font_size_pt=11, color_rgb=GRAPHITE_GRAY_RGB)
    if content.get("ai_disclosure_footer", True):
        _add_textbox(slide, "AI-generated illustration", *AI_DISCLOSURE_BAND,
                     font_size_pt=8, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_cross_tenant_integration(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    # Build the body content: tenant list, K-BERDL DBs, sibling projects
    lines: list[str] = []
    if content.get("no_signal_fallback"):
        lines.append("All data sourced from a single tenant.")
        lines.append("This project did not integrate across tenants.")
    else:
        if content.get("tenant_list"):
            lines.append(f"Tenants: {', '.join(content['tenant_list'])}")
        if content.get("kberdl_db_list"):
            lines.append(f"K-BERDL databases: {', '.join(content['kberdl_db_list'])}")
        if content.get("sibling_project_refs"):
            for ref in content["sibling_project_refs"]:
                lines.append(
                    f"From {ref['project_id']}: {ref['what_was_leveraged']}"
                )
    if lines:
        _set_placeholder_bullets(slide, 1, lines)
    # data_flow_diagram (optional) — same diagram-render stub story
    if content.get("data_flow_diagram"):
        warnings.append(
            f"cross_tenant_integration on slide id={slide.slide_id}: "
            f"data_flow_diagram rendering stubbed; v0.1.0-extractors-c."
        )


def _fill_implications(slide, content, draft_dir, warnings):
    _set_title(slide, content["title"])
    # bullets is list of {claim, evidence_pointer}
    lines = [
        f"{b['claim']}\n   ↪ {b['evidence_pointer']}"
        for b in content["bullets"]
    ]
    _set_placeholder_bullets(slide, 1, lines)


def _fill_acknowledgments(slide, content, draft_dir, warnings):
    # Title is hard-coded "Acknowledgments" (exempt from punchline rule per SPEC §6.1)
    _set_title(slide, "Acknowledgments")
    lines = list(content["contributors"])
    if content.get("tenant_attribution"):
        lines.append(content["tenant_attribution"])
    if content.get("code_repo_url"):
        lines.append(f"Code: {content['code_repo_url']}")
    _set_placeholder_bullets(slide, 1, lines)
    # funder_logos: render as a horizontal strip at the bottom
    if content.get("funder_logos"):
        n_logos = len(content["funder_logos"])
        slide_w_in = 10.0
        margin = 0.30
        gap = 0.20
        max_w = (slide_w_in - 2 * margin - (n_logos - 1) * gap) / max(n_logos, 1)
        max_h = 0.60
        for i, logo_path in enumerate(content["funder_logos"]):
            path = _resolve_asset_path(logo_path, draft_dir, warnings,
                                        f"acknowledgments.funder_logos[{i}]")
            if path:
                left = margin + i * (max_w + gap)
                _add_picture(slide, path, left, 4.95, max_w, max_h)


def _fill_references(slide, content, draft_dir, warnings):
    # Title is hard-coded "References" (exempt from punchline rule per SPEC §6.1)
    _set_title(slide, "References")
    _set_placeholder_bullets(slide, 1, content["refs_short"])
    # AI-disclosure footer (always emitted)
    disclosure = content.get(
        "ai_disclosure",
        "Slides drafted with beril-presentation-maker; full bibliography "
        "in speaker notes."
    )
    _add_textbox(slide, disclosure, 0.30, 5.30, 9.40, 0.30,
                 font_size_pt=8, color_rgb=GRAPHITE_GRAY_RGB)


def _fill_qa_anticipated(slide, content, draft_dir, warnings):
    _set_title(slide, content["question"])
    body_lines = [content["answer_summary"]]
    if content.get("answer_detail"):
        body_lines.append("")
        body_lines.append(content["answer_detail"])
    body_lines.append("")
    body_lines.append(f"↪ {content['evidence_pointer']}")
    _set_placeholder_bullets(slide, 1, body_lines)


# Dispatcher
LAYOUT_HANDLERS = {
    "title":                    _fill_title,
    "section_divider":          _fill_section_divider,
    "big_idea":                 _fill_big_idea,
    "big_number":               _fill_big_number,
    "claim_evidence":           _fill_claim_evidence,
    "two_column_compare":       _fill_two_column_compare,
    "data_figure":              _fill_data_figure,
    "workflow_diagram":         _fill_workflow_diagram,
    "methods_summary":          _fill_methods_summary,
    "concept_illustration":     _fill_concept_illustration,
    "cross_tenant_integration": _fill_cross_tenant_integration,
    "implications":             _fill_implications,
    "acknowledgments":          _fill_acknowledgments,
    "references":               _fill_references,
    "qa_anticipated":           _fill_qa_anticipated,
}


# ---------------------------------------------------------------------------
# Top-level assemble entry point
# ---------------------------------------------------------------------------

def assemble(slide_spec_path: str | Path,
             out_path: str | Path,
             *,
             master_path: str | Path | None = None,
             strict: bool = False) -> AssemblyResult:
    """Assemble a slide_spec.json into a .pptx file.

    Args:
      slide_spec_path: path to slide_spec.json (the contract source)
      out_path:        path to write slides.pptx
      master_path:     override the shipped master template (default:
                       references/templates/kbase-presentation-master.pptx)
      strict:          if True, raise on any warning (e.g., missing figure
                       file). Default False — warnings collected but rendered.

    Returns:
      AssemblyResult with `out_path`, `n_slides`, and `warnings`.

    Raises:
      AssemblyError on validation failure or missing master.
    """
    slide_spec_path = Path(slide_spec_path).resolve()
    out_path = Path(out_path).resolve()
    if not slide_spec_path.is_file():
        raise AssemblyError(f"slide_spec.json not found: {slide_spec_path}")

    spec = json.loads(slide_spec_path.read_text(encoding="utf-8"))

    # Pre-flight validation
    ss = _load_slide_spec_module()
    issues = ss.validate_slide_spec(spec)
    if issues:
        raise AssemblyError(
            f"slide_spec.json failed schema validation "
            f"({len(issues)} issue(s)):\n  "
            + "\n  ".join(i.format() for i in issues[:20])
            + ("\n  ..." if len(issues) > 20 else "")
        )

    # Master
    master = Path(master_path) if master_path else default_master_path()
    if not master.is_file():
        raise AssemblyError(f"master template not found: {master}")
    prs = Presentation(master)

    draft_dir = slide_spec_path.parent
    warnings: list[str] = []

    for slide_data in spec["slides"]:
        layout_name = slide_data["layout"]
        layout = _get_layout_by_name(prs, layout_name)
        slide = prs.slides.add_slide(layout)

        handler = LAYOUT_HANDLERS.get(layout_name)
        if handler is None:
            # Should be unreachable — slide_spec validator pins layout to vocab
            raise AssemblyError(
                f"no handler registered for layout {layout_name!r}"
            )
        handler(slide, slide_data["content"], draft_dir, warnings)

        if "speaker_notes" in slide_data:
            _set_speaker_notes(slide, slide_data["speaker_notes"])

    if strict and warnings:
        raise AssemblyError(
            f"--strict mode: {len(warnings)} warning(s):\n  "
            + "\n  ".join(warnings)
        )

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)

    return AssemblyResult(
        out_path=out_path,
        n_slides=len(spec["slides"]),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# PDF rendering (LibreOffice)
# ---------------------------------------------------------------------------

def render_pdf(pptx_path: Path) -> Path | None:
    """Render <pptx_path> to <pptx_path with .pdf suffix> via LibreOffice.

    Returns the .pdf path on success. Returns None if soffice is not on
    PATH (assembler emits a clear message; pptx-only output is still valid).
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    out_dir = pptx_path.parent
    cmd = [soffice, "--headless", "--convert-to", "pdf",
           "--outdir", str(out_dir), str(pptx_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"PDF render failed: {e}", file=sys.stderr)
        return None
    pdf = pptx_path.with_suffix(".pdf")
    return pdf if pdf.is_file() else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="assemble_pptx",
        description="Render slide_spec.json to slides.pptx (and optionally PDF).",
    )
    parser.add_argument("slide_spec",
                        help="Path to slide_spec.json (the contract input).")
    parser.add_argument("--out", required=True,
                        help="Output .pptx path.")
    parser.add_argument("--master",
                        help="Override master template path "
                             "(default: shipped kbase-presentation-master.pptx)")
    parser.add_argument("--format", choices=["pptx", "pdf"], default="pptx",
                        help="Output format. pdf invokes soffice; falls back "
                             "to pptx if LibreOffice not on PATH.")
    parser.add_argument("--strict", action="store_true",
                        help="Fail on any warning (e.g., missing figure file).")
    args = parser.parse_args(argv)

    try:
        result = assemble(args.slide_spec, args.out,
                          master_path=args.master, strict=args.strict)
    except AssemblyError as e:
        print(f"assemble_pptx: {e}", file=sys.stderr)
        return 2

    print(f"wrote {result.out_path} ({result.n_slides} slide(s))",
          file=sys.stderr)
    if result.warnings:
        print(f"{len(result.warnings)} warning(s):", file=sys.stderr)
        for w in result.warnings:
            print(f"  - {w}", file=sys.stderr)

    if args.format == "pdf":
        pdf = render_pdf(result.out_path)
        if pdf is None:
            print("PDF render unavailable (LibreOffice not found). "
                  "Open .pptx in PowerPoint/Keynote and export to PDF "
                  "manually.", file=sys.stderr)
        else:
            print(f"wrote {pdf}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
