"""Tests for slide_spec.py — schema, types, validator.

Coverage targets:
- All 15 layouts produce a valid example.
- Top-level required fields enforced.
- Per-layout required/optional fields enforced.
- Discriminated content (wrong content for layout → reported).
- Diagram sub-schema enforced (node ids unique, shapes/edges in vocab).
- Substory cross-reference (slide.substory_id → declared substory).
- JSON Schema doc round-trips (parse, has expected $defs).
- CLI: validate, schema-json, example.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SLIDE_SPEC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                 / "tools" / "slide_spec.py")
SCHEMA_JSON = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "references" / "slide_spec.schema.json")


def _import_slide_spec():
    spec = importlib.util.spec_from_file_location("slide_spec", SLIDE_SPEC_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load slide_spec from {SLIDE_SPEC_PY}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve forward type refs.
    sys.modules["slide_spec"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ss():
    return _import_slide_spec()


# ---------------------------------------------------------------------------
# Constants and vocabulary
# ---------------------------------------------------------------------------

def test_layouts_in_vocabulary(ss):
    """v0.3.2 added data_table → 16 layouts;
    v0.7/D-086 added deck_close → 17 layouts."""
    assert len(ss.LAYOUTS) == 17
    assert len(set(ss.LAYOUTS)) == 17
    assert "data_table" in ss.LAYOUTS
    assert "deck_close" in ss.LAYOUTS


# ---------------------------------------------------------------------------
# v0.3.2: data_table validator
# ---------------------------------------------------------------------------


def _dt_content(**overrides):
    """Build a minimally valid data_table content dict."""
    base = {
        "title": "Top candidates",
        "columns": ["Gene", "Organism", "Score"],
        "rows": [
            ["G1", "Org A", "0.95"],
            ["G2", "Org B", "0.87"],
        ],
    }
    base.update(overrides)
    return base


def test_data_table_minimal_valid(ss):
    """Minimal data_table (title + columns + rows) validates clean."""
    issues = ss.LAYOUT_CHECKERS["data_table"](_dt_content(), "$.slides[0].content")
    assert issues == []


def test_data_table_with_optional_fields(ss):
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(
            caption="Top 2 candidates from full ranking.",
            footnote="Full ranking in REPORT.md §4.2.",
            data_source="REPORT.md §4.2",
            highlight_rows=[0],
        ),
        "$.slides[0].content",
    )
    assert issues == []


def test_data_table_missing_title_rejects(ss):
    content = _dt_content()
    del content["title"]
    issues = ss.LAYOUT_CHECKERS["data_table"](content, "$.slides[0].content")
    assert any("title" in i.message or "title" in i.path for i in issues)


def test_data_table_too_few_columns_rejects(ss):
    """Singleton-column tables aren't tables — use a bullet list instead."""
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(columns=["Gene"], rows=[["G1"], ["G2"]]),
        "$.slides[0].content",
    )
    assert any("columns" in i.path for i in issues)


def test_data_table_empty_corner_cell_allowed(ss):
    """v0.3.2.2: matrix-table convention — first column header may be
    empty (corner cell where row labels meet column labels). The
    selection-signature-matrix pattern from slide_compose.v1.md's
    worked example uses this. Live failure: core_gene_tradeoffs draft_2
    slide 14 was rejected before the relaxation."""
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(
            columns=["", "Conserved (core)", "Variable (accessory)"],
            rows=[
                ["Costly in lab",  "28,017", "5,526"],
                ["Neutral in lab", "86,761", "21,886"],
            ],
        ),
        "$.slides[0].content",
    )
    assert issues == [], (
        "matrix corner-cell empty header should be allowed; got: "
        + "; ".join(i.message for i in issues)
    )


def test_data_table_non_string_header_rejects(ss):
    """Type-correctness check: headers must be strings (empty-OK), not
    integers or other types."""
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(columns=[1, "B", "C"], rows=[["a", "b", "c"]]),
        "$.slides[0].content",
    )
    assert any("must be a string" in i.message for i in issues)


def test_data_table_too_many_columns_rejects(ss):
    """Cap at DATA_TABLE_MAX_COLS (6). Wide tables exceed presentation
    floor readability and should be summarized or split."""
    cols = [f"col_{i}" for i in range(ss.DATA_TABLE_MAX_COLS + 1)]
    rows = [[f"r0c{j}" for j in range(len(cols))]]
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(columns=cols, rows=rows),
        "$.slides[0].content",
    )
    assert any("too many columns" in i.message for i in issues)


def test_data_table_too_many_rows_rejects(ss):
    """Cap at DATA_TABLE_MAX_ROWS (12). Above this, link to REPORT.md."""
    rows = [[f"r{i}c0", f"r{i}c1", f"r{i}c2"]
            for i in range(ss.DATA_TABLE_MAX_ROWS + 1)]
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(rows=rows),
        "$.slides[0].content",
    )
    assert any("too many rows" in i.message for i in issues)


def test_data_table_zero_rows_rejects(ss):
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(rows=[]),
        "$.slides[0].content",
    )
    assert any("at least 1 row" in i.message for i in issues)


def test_data_table_row_length_mismatch_rejects(ss):
    """Each row must have exactly len(columns) cells."""
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(
            columns=["A", "B", "C"],
            rows=[["a", "b"]],  # 2 cells, 3 cols
        ),
        "$.slides[0].content",
    )
    assert any("3 headers" in i.message for i in issues)


def test_data_table_non_string_cell_rejects(ss):
    """Caller must stringify numbers with desired precision; the layout
    cannot reason about precision."""
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(rows=[["G1", "Org A", 0.95]]),  # float, not str
        "$.slides[0].content",
    )
    assert any("must be a string" in i.message for i in issues)


def test_data_table_highlight_row_out_of_range_rejects(ss):
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(highlight_rows=[5]),  # only 2 rows in fixture
        "$.slides[0].content",
    )
    assert any("out of range" in i.message for i in issues)


def test_data_table_highlight_row_non_int_rejects(ss):
    issues = ss.LAYOUT_CHECKERS["data_table"](
        _dt_content(highlight_rows=["0"]),  # string, not int
        "$.slides[0].content",
    )
    assert any("must be an int" in i.message for i in issues)


def test_data_table_in_example_slides(ss):
    """example_slide('data_table') returns a valid slide."""
    slide = ss.example_slide("data_table", 1, "S1")
    assert slide["layout"] == "data_table"
    issues = ss.LAYOUT_CHECKERS["data_table"](
        slide["content"], "$.slides[0].content")
    assert issues == []


def test_layout_checkers_cover_full_vocabulary(ss):
    assert set(ss.LAYOUT_CHECKERS.keys()) == set(ss.LAYOUTS)


def test_modes_match_spec(ss):
    assert set(ss.MODES) == {"talk-30", "talk-15", "talk-45",
                             "lightning-5", "poster-h", "poster-v"}


def test_diagram_node_shapes_include_swimlane(ss):
    """Adam confirmed swimlane in v0.1; tree deferred to v0.2."""
    assert "swimlane" in ss.DIAGRAM_NODE_SHAPES
    assert "tree" not in ss.DIAGRAM_NODE_SHAPES
    assert len(ss.DIAGRAM_NODE_SHAPES) == 7


def test_concept_styles_match_ai_image_prompt(ss):
    """v0.3.3: CONCEPT_STYLES must match the styles enumerated in
    ai_image_prompt.v1.md (the source of truth for image-request styles).

    Drift between these two surfaces produces silent contract-drift
    bugs: a concept_illustration slide with a calibration-ratified
    style passes the request schema but fails the spec validator.
    Caught in v0.3.3 smoke 2026-05-03 — validator hard-rejected
    'scientific_illustration' (the T2-winning default per calibration)
    because this tuple still listed only the original 3.

    If ai_image_prompt.v1.md adds or removes a style, this tuple MUST
    be updated in the same commit.
    """
    expected = {
        # Original 3 (pre-v0.3.0).
        "metaphor", "infographic", "conceptual_diagram",
        # v0.3.0 calibration additions.
        "scientific_illustration", "watercolor", "minimalist", "abstract",
    }
    assert set(ss.CONCEPT_STYLES) == expected, (
        f"CONCEPT_STYLES drifted from ai_image_prompt.v1.md: "
        f"{set(ss.CONCEPT_STYLES)} != {expected}"
    )


def test_concept_illustration_accepts_scientific_illustration(ss):
    """The T2-winning calibration default must validate cleanly."""
    spec = ss.example_slide_spec()
    # Find the concept_illustration slide in the example
    for slide in spec["slides"]:
        if slide.get("layout") == "concept_illustration":
            slide["content"]["style"] = "scientific_illustration"
            break
    issues = ss.validate_slide_spec(spec)
    assert issues == [], (
        "scientific_illustration must validate (calibration default): "
        + "; ".join(i.format() for i in issues)
    )


def test_concept_channels_match_two_channel_design(ss):
    """D-005-rev1: Channel A (LLM-proposed) and Channel B (user-requested)."""
    assert set(ss.CONCEPT_CHANNELS) == {"A", "B"}


# ---------------------------------------------------------------------------
# example_slide_spec round-trip
# ---------------------------------------------------------------------------

def test_example_slide_spec_validates(ss):
    spec = ss.example_slide_spec()
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "example_slide_spec must validate cleanly: " + \
        "; ".join(i.format() for i in issues)


def test_example_slide_spec_covers_all_layouts(ss):
    spec = ss.example_slide_spec()
    layouts_used = {s["layout"] for s in spec["slides"]}
    assert layouts_used == set(ss.LAYOUTS)


@pytest.mark.parametrize("layout", [
    "title", "section_divider", "big_idea", "big_number",
    "claim_evidence", "two_column_compare", "data_figure",
    "workflow_diagram", "methods_summary", "concept_illustration",
    "cross_tenant_integration", "implications", "acknowledgments",
    "references", "qa_anticipated",
    "deck_close",  # v0.7/D-086
])
def test_example_slide_per_layout(ss, layout):
    """Each layout's example_slide() produces a slide that, when wrapped in
    a minimal spec with only that slide, validates.

    Uses mode=lightning-5 to avoid the v0.7/D-086 deck_close-presence
    soft-warning that fires on talk-30 STRONG specs missing deck_close
    (orthogonal to per-layout schema check; that check has its own
    coverage)."""
    slide = ss.example_slide(layout, slide_id=1, substory_id=None)
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "lightning-5",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {
            "id": "TL1", "punchline": "x", "tier_evidence": "STRONG",
        },
        "substories": [],
        "slides": [slide],
    }
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "; ".join(i.format() for i in issues)


# ---------------------------------------------------------------------------
# Top-level field enforcement
# ---------------------------------------------------------------------------

def test_missing_schema_version_rejected(ss):
    spec = ss.example_slide_spec()
    spec["schema_version"] = "0.0"
    issues = ss.validate_slide_spec(spec)
    assert any("schema_version" in i.path for i in issues)


def test_unknown_mode_rejected(ss):
    spec = ss.example_slide_spec()
    spec["mode"] = "talk-90"
    issues = ss.validate_slide_spec(spec)
    assert any("mode" in i.path for i in issues)


def test_unknown_audience_rejected(ss):
    spec = ss.example_slide_spec()
    spec["audience"] = "lay"   # v1.x scope, not v1
    issues = ss.validate_slide_spec(spec)
    assert any("audience" in i.path for i in issues)


def test_unknown_tier_rejected(ss):
    spec = ss.example_slide_spec()
    spec["tier"] = "MEDIUM"   # not in vocabulary
    issues = ss.validate_slide_spec(spec)
    assert any("tier" in i.path for i in issues)


def test_throughline_missing_punchline_rejected(ss):
    spec = ss.example_slide_spec()
    del spec["throughline"]["punchline"]
    issues = ss.validate_slide_spec(spec)
    assert any("throughline.punchline" in i.path for i in issues)


def test_substory_id_duplicates_rejected(ss):
    spec = ss.example_slide_spec()
    spec["substories"] = [
        {"id": "S1", "punchline": "a", "slide_ids": [1]},
        {"id": "S1", "punchline": "b", "slide_ids": [2]},
    ]
    issues = ss.validate_slide_spec(spec)
    assert any("duplicate substory id" in i.message for i in issues)


def test_slide_id_duplicates_rejected(ss):
    spec = ss.example_slide_spec()
    spec["slides"][1]["id"] = spec["slides"][0]["id"]
    issues = ss.validate_slide_spec(spec)
    assert any("duplicate slide id" in i.message for i in issues)


def test_slide_substory_id_must_reference_declared(ss):
    spec = ss.example_slide_spec()
    spec["slides"][0]["substory_id"] = "S99"   # not declared
    issues = ss.validate_slide_spec(spec)
    assert any("undeclared substory" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Per-layout content enforcement
# ---------------------------------------------------------------------------

def test_unknown_layout_rejected(ss):
    spec = ss.example_slide_spec()
    spec["slides"][0]["layout"] = "frobozzicate"
    issues = ss.validate_slide_spec(spec)
    assert any(i.path.endswith(".layout") for i in issues)


def test_claim_evidence_bullets_max_3(ss):
    slide = ss.example_slide("claim_evidence")
    slide["content"]["bullets"] = ["a", "b", "c", "d"]   # 4
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("bullets" in i.path for i in issues)


def test_claim_evidence_figure_without_caption_rejected(ss):
    slide = ss.example_slide("claim_evidence")
    slide["content"]["figure"] = "figures/x.png"
    # caption deliberately absent
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("figure and figure_caption" in i.message for i in issues)


def test_data_figure_curated_path_rejected(ss):
    """Regression: the deprecated figures/curated/ convention silently
    dropped four data-slide pictures in draft_8 (2026-04-27). The
    validator must hard-fail rather than letting the assembler warn-
    and-drop. See slide_compose.v1.md changelog 2026-04-27."""
    slide = ss.example_slide("data_figure")
    slide["content"]["figure"] = "figures/curated/fig34_classification_heatmap.png"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("deprecated 'curated/' segment" in i.message for i in issues), \
        f"expected /curated/ rejection; got: {[i.format() for i in issues]}"


def test_claim_evidence_curated_path_rejected(ss):
    """Same regression on claim_evidence.figure."""
    slide = ss.example_slide("claim_evidence")
    slide["content"]["figure"] = "figures/curated/F03.png"
    slide["content"]["figure_caption"] = "x"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("deprecated 'curated/' segment" in i.message for i in issues)


def test_concept_illustration_curated_path_rejected_but_tbd_ok(ss):
    """concept_illustration.image_path: {TBD} placeholder is legitimate
    (filled by ai_image_prompt.v1), but figures/curated/ is not."""
    # 1. {TBD} must pass the path-shape check
    slide = ss.example_slide("concept_illustration")
    slide["content"]["image_path"] = "{TBD}"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert not any("deprecated 'curated/' segment" in i.message for i in issues), \
        "{TBD} placeholder should pass path-shape check"

    # 2. figures/curated/ must fail
    slide["content"]["image_path"] = "figures/curated/img01.png"
    issues = ss.validate_slide_spec(spec)
    assert any("deprecated 'curated/' segment" in i.message for i in issues)


def test_big_idea_supporting_graphic_curated_path_rejected(ss):
    """big_idea.supporting_graphic — same path-shape rule applies."""
    slide = ss.example_slide("big_idea")
    slide["content"]["supporting_graphic"] = "figures/curated/icon.png"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("deprecated 'curated/' segment" in i.message for i in issues)


def test_relative_figure_path_accepted(ss):
    """Sanity: the recommended path shape (figures/<name>.png) passes."""
    slide = ss.example_slide("data_figure")
    slide["content"]["figure"] = "figures/fig34_classification_heatmap.png"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert not any("curated/" in i.message for i in issues)


def test_data_figure_caption_at_cap_passes(ss):
    """v0.3.5: caption length cap pinned at DATA_FIGURE_CAPTION_MAX_CHARS.
    A caption exactly at the cap should pass. Also pins the constant
    name so prompt-vs-tool drift produces a test-suite failure if the
    cap is renamed without updating slide_compose.v1.md / revise_slide.v1.md."""
    cap = ss.DATA_FIGURE_CAPTION_MAX_CHARS
    assert cap == 280, "cap is the contract; bumping changes prompt + tests together"
    slide = ss.example_slide("data_figure")
    slide["content"]["caption"] = "x" * cap
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert not any("data_figure caption is" in i.message for i in issues), \
        f"caption at cap should pass; got: {[i.format() for i in issues]}"


def test_data_figure_caption_over_cap_rejected(ss):
    """v0.3.5: regression on the live failure mode — revise-loop produced
    a 410-char caption on gene_function_ecological_agora draft_1 slides
    21+23 → text spilled into the y=5.00 brand strip. The validator must
    hard-fail (assemble.py rejects → revise loop must re-emit shorter)."""
    cap = ss.DATA_FIGURE_CAPTION_MAX_CHARS
    slide = ss.example_slide("data_figure")
    slide["content"]["caption"] = "x" * (cap + 1)
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    matches = [i for i in issues if "data_figure caption is" in i.message]
    assert matches, f"expected caption-cap rejection; got: {[i.format() for i in issues]}"
    msg = matches[0].message
    assert str(cap + 1) in msg and str(cap) in msg, \
        f"error message should report actual length and cap: {msg!r}"
    assert "y=5.00" in msg or "brand strip" in msg, \
        f"error should hint at the failure mode for the LLM revise loop: {msg!r}"


def test_data_figure_caption_410_char_live_failure_rejected(ss):
    """v0.3.5: pin the exact magnitude of the live failure (~410 chars)
    so a future cap loosening / removal trips this test instead of
    silently re-shipping the brand-strip overflow."""
    slide = ss.example_slide("data_figure")
    # Approximate the gene_function_ecological_agora draft_1 slide-21
    # caption: long-form sentence with citation + interpretation hedge.
    slide["content"]["caption"] = (
        "Top-N comparison shows that the high-confidence cluster (n=12) "
        "achieves higher discrimination than the broader candidate pool "
        "(n=347) under the same evidence-tier threshold, with a clear "
        "separation at score >= 0.85 (REPORT.md §4.2; Smith et al. 2024 "
        "for the underlying ranking method); pattern holds across both "
        "STRONG and THIN evidence tiers but weakens for EXPLORATORY."
    )
    assert len(slide["content"]["caption"]) > 280, \
        "fixture should reproduce a >280 char caption"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("data_figure caption is" in i.message for i in issues), \
        f"410-char regression caption must hard-fail; got: {[i.format() for i in issues]}"


def test_methods_summary_bullets_min_5(ss):
    slide = ss.example_slide("methods_summary")
    slide["content"]["bullets"] = ["a", "b"]   # too few
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("bullets" in i.path for i in issues)


def test_methods_summary_tools_versions_option_a(ss):
    """Option A: list of {tool, version} objects, not strings."""
    slide = ss.example_slide("methods_summary")
    slide["content"]["tools_versions"] = ["gene-annotate 2.3.1"]   # Option B style
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("tools_versions" in i.path for i in issues)


def test_concept_illustration_requires_provenance(ss):
    slide = ss.example_slide("concept_illustration")
    del slide["content"]["provenance"]
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("provenance" in i.path for i in issues)


def test_concept_illustration_unknown_style_rejected(ss):
    slide = ss.example_slide("concept_illustration")
    slide["content"]["style"] = "rococo"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any(i.path.endswith(".style") for i in issues)


def test_implications_bullets_must_be_objects(ss):
    slide = ss.example_slide("implications")
    slide["content"]["bullets"] = ["plain string"]   # not {claim, evidence_pointer}
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("bullets" in i.path for i in issues)


def test_qa_anticipated_requires_evidence_pointer(ss):
    slide = ss.example_slide("qa_anticipated")
    del slide["content"]["evidence_pointer"]
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any(i.path.endswith(".evidence_pointer") for i in issues)


def test_references_max_8_short_refs(ss):
    slide = ss.example_slide("references")
    slide["content"]["refs_short"] = [f"Ref {i}" for i in range(10)]
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("refs_short" in i.path for i in issues)


# ---------------------------------------------------------------------------
# Diagram sub-schema enforcement
# ---------------------------------------------------------------------------

def test_diagram_unknown_node_shape_rejected(ss):
    slide = ss.example_slide("workflow_diagram")
    slide["content"]["diagram"]["nodes"][0]["shape"] = "hexagon"   # not in vocab
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("shape" in i.path for i in issues)


def test_diagram_swimlane_accepted(ss):
    """swimlane is a v0.1 first-class node shape."""
    slide = ss.example_slide("workflow_diagram")
    slide["content"]["diagram"]["nodes"].append({
        "id": "lane1", "label": "Phase 1", "shape": "swimlane",
        "x": 0, "y": 0, "w": 5, "h": 3,
    })
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "; ".join(i.format() for i in issues)


def test_diagram_duplicate_node_id_rejected(ss):
    slide = ss.example_slide("workflow_diagram")
    slide["content"]["diagram"]["nodes"][1]["id"] = \
        slide["content"]["diagram"]["nodes"][0]["id"]
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("duplicate node id" in i.message for i in issues)


def test_diagram_unknown_edge_kind_rejected(ss):
    slide = ss.example_slide("workflow_diagram")
    slide["content"]["diagram"]["edges"][0]["kind"] = "magic"
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("kind" in i.path for i in issues)


def test_workflow_step_caption_must_be_3(ss):
    slide = ss.example_slide("workflow_diagram")
    slide["content"]["step_caption"] = ["only one"]
    spec = ss.example_slide_spec()
    spec["slides"][0] = slide
    spec["substories"] = [{"id": "S1", "punchline": "x",
                            "slide_ids": [s["id"] for s in spec["slides"]
                                          if s["substory_id"] == "S1"]}]
    issues = ss.validate_slide_spec(spec)
    assert any("step_caption" in i.path for i in issues)


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------

def test_dump_json_schema_round_trip(ss):
    schema = ss.dump_json_schema()
    # Must be JSON-serializable + non-trivial
    text = json.dumps(schema)
    parsed = json.loads(text)
    assert parsed == schema
    assert "$defs" in schema
    assert len(schema["$defs"]) >= 17   # v0.3.2: 16 layouts + diagram


def test_schema_json_on_disk_matches_dump(ss):
    """The checked-in JSON Schema doc must equal the live dump_json_schema()
    output. Catches schema drift between code and committed reference."""
    on_disk = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    fresh = ss.dump_json_schema()
    assert on_disk == fresh, (
        "slide_spec.schema.json is out of date with slide_spec.py — run "
        "`python3 src/.../skill/tools/slide_spec.py schema-json --out src/.../skill/references/slide_spec.schema.json`"
    )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_cli_validate_clean_spec(ss, tmp_path):
    spec = ss.example_slide_spec()
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    rc = ss.main(["validate", str(p)])
    assert rc == 0


def test_cli_validate_dirty_spec(ss, tmp_path, capsys):
    spec = ss.example_slide_spec()
    spec["mode"] = "talk-90"   # invalid
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    rc = ss.main(["validate", str(p)])
    assert rc == 1


def test_cli_schema_to_file(ss, tmp_path):
    out = tmp_path / "out.schema.json"
    rc = ss.main(["schema-json", "--out", str(out)])
    assert rc == 0
    parsed = json.loads(out.read_text())
    assert "$defs" in parsed


def test_cli_example_known_layout(ss, capsys):
    rc = ss.main(["example", "claim_evidence"])
    assert rc == 0


def test_cli_example_unknown_layout_errors(ss, capsys):
    rc = ss.main(["example", "frobozz"])
    assert rc == 2


# ---------------------------------------------------------------------------
# M4a Tier B — advisory content-length caps (DQ4 soft-warning)
# ---------------------------------------------------------------------------

def _spec_with_one_slide(ss, slide):
    # mode=lightning-5 to avoid the v0.7/D-086 deck_close-presence
    # soft-warning that fires on talk-30 STRONG specs missing deck_close
    # (orthogonal to the per-layout advisory-cap checks below).
    return {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "lightning-5", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [slide],
    }


def test_validator_issue_severity_defaults_to_error(ss):
    """Existing call sites omit `severity`; default must be hard-error
    so v0.3.x semantics are preserved."""
    iss = ss.ValidatorIssue("$.foo", "bad")
    assert iss.severity == "error"


def test_big_number_subtitle_advisory_cap_emits_soft_warning(ss):
    """80-char advisory cap on big_number subtitle (Tier-A safety net
    absorbs it; the cap is advisory so prompt drift surfaces)."""
    long_subtitle = "x" * (ss.BIG_NUMBER_SUBTITLE_MAX_CHARS + 20)
    slide = {"id": 1, "substory_id": None, "layout": "big_number",
             "content": {"headline": "42", "subtitle": long_subtitle}}
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    soft = [i for i in issues if i.severity == "soft-warning"]
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], f"expected no errors, got {errors}"
    assert any("subtitle" in i.path and "advisory cap" in i.message
               for i in soft), soft


def test_big_number_subtitle_at_cap_no_warning(ss):
    """A subtitle at exactly the cap is fine — no warning."""
    slide = {"id": 1, "substory_id": None, "layout": "big_number",
             "content": {"headline": "42",
                         "subtitle": "x" * ss.BIG_NUMBER_SUBTITLE_MAX_CHARS}}
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    assert all(i.severity == "error" for i in issues) or issues == []


def test_workflow_step_caption_advisory_cap_emits_soft_warning(ss):
    """70-char advisory cap per step_caption (3-column band; renderer
    shrink-to-fit absorbs)."""
    long_cap = "x" * (ss.WORKFLOW_STEP_CAPTION_MAX_CHARS + 20)
    slide = {
        "id": 1, "substory_id": None, "layout": "workflow_diagram",
        "content": {
            "title": "t",
            "diagram": {
                "kind": "boxes_and_arrows",
                "nodes": [
                    {"id": "n1", "label": "a", "shape": "rounded",
                     "x": 0.5, "y": 1.4, "w": 1.5, "h": 0.8},
                    {"id": "n2", "label": "b", "shape": "rounded",
                     "x": 7.0, "y": 1.4, "w": 1.5, "h": 0.8},
                ],
                "edges": [{"from": "n1", "to": "n2", "kind": "straight"}],
            },
            "step_caption": [long_cap, "ok", "also ok"],
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    soft = [i for i in issues if i.severity == "soft-warning"]
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], f"expected no errors, got {errors}"
    assert any("step_caption[0]" in i.path and "advisory cap" in i.message
               for i in soft), soft


def test_qa_answer_summary_advisory_cap_emits_soft_warning(ss):
    """600-char advisory cap on qa_anticipated.answer_summary (depth
    belongs in answer_detail, routed to notes pane per M3 E-5).

    Below the v0.8 Tier-G.2 HARD cap (1100 chars) but above the
    advisory cap (600 chars): emits soft-warning ONLY, no error.
    Renderer's shrink-to-fit absorbs cleanly in the 600-1100 range.
    """
    long_ans = "x" * (ss.QA_ANSWER_SUMMARY_MAX_CHARS + 50)
    # Sanity: this length must be in the soft-only band
    assert len(long_ans) < ss.QA_ANSWER_SUMMARY_HARD_MAX_CHARS
    slide = {
        "id": 1, "substory_id": None, "layout": "qa_anticipated",
        "content": {
            "question": "q?",
            "answer_summary": long_ans,
            "evidence_pointer": "Substory 1",
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    soft = [i for i in issues if i.severity == "soft-warning"]
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], f"expected no errors, got {errors}"
    assert any("answer_summary" in i.path and "advisory cap" in i.message
               for i in soft), soft


def test_qa_answer_summary_hard_cap_emits_error(ss):
    """v0.8 Tier G.2 HARD cap: above 1100 chars the renderer's
    shrink-to-fit drops below 80% scale → projection-illegible.
    Composer must comply; validator fails the spec.

    Live evidence: draft_8 ibd_phage_targeting slides 25/26/27
    produced answer_summary at 1013/1141/1325 chars; visual-QA
    flagged all three illegible_scale. The advisory was being
    ignored cycle after cycle because nothing failed. Hard cap
    forces compliance."""
    over_hard = "y" * (ss.QA_ANSWER_SUMMARY_HARD_MAX_CHARS + 50)
    slide = {
        "id": 1, "substory_id": None, "layout": "qa_anticipated",
        "content": {
            "question": "q?",
            "answer_summary": over_hard,
            "evidence_pointer": "Substory 1",
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    errors = [i for i in issues if i.severity == "error"]
    assert any(
        "answer_summary" in i.path
        and "projection-legibility cliff" in i.message
        for i in errors), (
        f"expected hard-cap error citing the projection-legibility "
        f"cliff; got errors: {[(i.path, i.message[:80]) for i in errors]}")


def test_qa_answer_summary_at_hard_cap_boundary_passes(ss):
    """Exactly at the 1100-char hard cap → no error (cap is
    inclusive: > triggers, == passes). Pin the boundary so a
    future change to `> hard_max` vs `>= hard_max` breaks a test."""
    at_boundary = "z" * ss.QA_ANSWER_SUMMARY_HARD_MAX_CHARS
    slide = {
        "id": 1, "substory_id": None, "layout": "qa_anticipated",
        "content": {
            "question": "q?",
            "answer_summary": at_boundary,
            "evidence_pointer": "Substory 1",
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    errors = [i for i in issues if i.severity == "error"]
    cliff_errors = [e for e in errors
                    if "projection-legibility cliff" in e.message]
    assert cliff_errors == [], (
        f"length exactly == hard cap must NOT trigger the cliff "
        f"error; got: {[(e.path, e.message[:80]) for e in cliff_errors]}")


def test_qa_answer_summary_well_under_caps_clean(ss):
    """Realistic-length answer_summary (~400 chars) emits no
    soft-warning AND no error. Pin so the validator only fires when
    something's actually wrong."""
    realistic = "x" * 400
    slide = {
        "id": 1, "substory_id": None, "layout": "qa_anticipated",
        "content": {
            "question": "q?",
            "answer_summary": realistic,
            "evidence_pointer": "Substory 1",
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    qa_issues = [i for i in issues if "answer_summary" in i.path]
    assert qa_issues == [], (
        f"realistic-length answer_summary should produce no issues; "
        f"got: {qa_issues}")


def test_diagram_node_label_advisory_cap_emits_soft_warning(ss):
    """40-char advisory cap on diagram node label (a phrase, not a
    sentence)."""
    long_label = "x" * (ss.DIAGRAM_NODE_LABEL_MAX_CHARS + 10)
    slide = {
        "id": 1, "substory_id": None, "layout": "workflow_diagram",
        "content": {
            "title": "t",
            "diagram": {
                "kind": "boxes_and_arrows",
                "nodes": [
                    {"id": "n1", "label": long_label, "shape": "rounded",
                     "x": 0.5, "y": 1.4, "w": 1.5, "h": 0.8},
                    {"id": "n2", "label": "b", "shape": "rounded",
                     "x": 7.0, "y": 1.4, "w": 1.5, "h": 0.8},
                ],
                "edges": [{"from": "n1", "to": "n2", "kind": "straight"}],
            },
            "step_caption": ["a", "b", "c"],
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    soft = [i for i in issues if i.severity == "soft-warning"]
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], f"expected no errors, got {errors}"
    assert any("nodes[0].label" in i.path and "advisory cap" in i.message
               for i in soft), soft


def test_data_figure_caption_demoted_to_soft_warning(ss):
    """M6 Tier C.1 (D-068): DATA_FIGURE_CAPTION_MAX_CHARS=280 demoted
    from hard error → soft-warning. The original v0.3.5 hard-reject
    motivation (no shrink-to-fit fallback at the time) is obsolete:
    `assemble_pptx._fill_data_figure` now sets
    MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE on the caption textbox, absorbing
    long captions. Matches the M4a Tier B / DQ4 posture for the other
    4 length caps (BIG_NUMBER_SUBTITLE, WORKFLOW_STEP_CAPTION,
    QA_ANSWER_SUMMARY, DIAGRAM_NODE_LABEL).

    Live trigger: 2026-05-25 fdm v0.4 draft_3 slide 13, caption was
    290 chars (10 over the cap); pipeline hard-failed for a render
    artifact that shrink-to-fit absorbs. v0.3 on the same project
    produced 273 chars (within band but close) — both pipelines can
    land in the 280-300 range stochastically.
    """
    long_cap = "x" * (ss.DATA_FIGURE_CAPTION_MAX_CHARS + 50)
    slide = {
        "id": 1, "substory_id": None, "layout": "data_figure",
        "content": {
            "title": "t",
            "figure": "figures/x.png",
            "caption": long_cap,
        },
    }
    issues = ss.validate_slide_spec(_spec_with_one_slide(ss, slide))
    # No hard error on caption length.
    errors = [i for i in issues if i.severity == "error"
              and "caption" in i.path]
    assert errors == [], (
        f"data_figure caption should be soft-warning per D-068, got "
        f"hard errors: {errors}")
    # Soft-warning IS emitted (operator sees it in the assembler's
    # warnings channel, M4a Tier B pattern).
    soft = [i for i in issues if i.severity == "soft-warning"
            and "caption" in i.path]
    assert soft, (
        f"expected soft-warning on long data_figure caption per D-068, "
        f"got {issues}")
    # Advisory diagnostic still names the 280 threshold + shrink-to-fit
    # fallback (so an operator reading the warning understands why
    # it's not a hard fail anymore).
    msg = soft[0].message
    assert "280" in msg or "advisory cap" in msg
    assert "shrink-to-fit" in msg.lower() or "absorbs" in msg.lower()


def test_validator_issue_format_marks_soft_warnings(ss):
    """ValidatorIssue.format() prefixes soft-warnings so they're visible
    in the assembler's error/warning channels."""
    err = ss.ValidatorIssue("$.foo", "bad")
    soft = ss.ValidatorIssue("$.bar", "advisory", severity="soft-warning")
    assert not err.format().startswith("[soft-warning]")
    assert soft.format().startswith("[soft-warning]")


def test_cli_validate_rc0_on_soft_warnings_only(ss, tmp_path, capsys):
    """M4a Tier B/E: the CLI must NOT fail validation on soft-warnings
    alone (advisory; renderer absorbs). Live-failure pin: pre-fix logic
    counted all issues regardless of severity, halting the orchestrator
    when 19 soft-warnings + 0 errors fired on the Tier E recompose."""
    # Build a spec with a single soft-warning trigger (big_number subtitle
    # past 80 chars) and zero hard errors.
    long_subtitle = "x" * (ss.BIG_NUMBER_SUBTITLE_MAX_CHARS + 50)
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{"id": 1, "substory_id": None, "layout": "big_number",
                    "content": {"headline": "42", "subtitle": long_subtitle}}],
    }
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    rc = ss.main(["validate", str(p)])
    assert rc == 0, "CLI must rc=0 on a spec with only soft-warnings"
    out = capsys.readouterr()
    # Soft-warning printed to stdout (operator sees it)
    assert "soft-warning" in out.out or "soft-warning" in out.err


def test_cli_validate_rc1_on_hard_errors(ss, tmp_path, capsys):
    """The CLI must still rc=1 on hard errors. After D-068 demoted the
    data_figure caption cap to soft-warning, this test uses a
    missing-required-field hard error (data_figure with no `figure`
    path) — the layout's required-field check is unaffected by D-068
    and still load-bearing."""
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        # Missing required `figure` field → hard error from layout checker
        "slides": [{"id": 1, "substory_id": None, "layout": "data_figure",
                    "content": {"title": "t",
                                "caption": "short caption ok"}}],
    }
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    rc = ss.main(["validate", str(p)])
    assert rc == 1


def test_cli_validate_rc1_when_errors_and_soft_warnings_mixed(ss, tmp_path):
    """If both severities fire, rc=1 (the errors are still load-bearing).
    After D-068, the hard-error fixture uses missing-required-field
    rather than caption overflow."""
    long_subtitle = "x" * (ss.BIG_NUMBER_SUBTITLE_MAX_CHARS + 50)   # soft
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [
            # Hard error: missing required `figure` field
            {"id": 1, "substory_id": None, "layout": "data_figure",
             "content": {"title": "t",
                         "caption": "short caption ok"}},
            # Soft warning: big_number subtitle overflow
            {"id": 2, "substory_id": None, "layout": "big_number",
             "content": {"headline": "42", "subtitle": long_subtitle}},
        ],
    }
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    rc = ss.main(["validate", str(p)])
    assert rc == 1

# ---------------------------------------------------------------------------
# v0.7 Tier C.0 — deck_close validator + mode-gated presence check (D-086)
# ---------------------------------------------------------------------------

def _deck_close_content_valid():
    """Canonical valid deck_close content per D-086."""
    return {
        "unified_point": "The deck unified takeaway in one or two sentences.",
        "key_takeaways": [
            "First arc takeaway.",
            "Second arc takeaway.",
            "Third arc takeaway.",
        ],
        "forward_call": "Next experiment / open question / validation gap.",
        "data_source": "S1 C-slot + S2 C-slot + REPORT.md sect 3.",
    }


def _spec_with_deck_close(ss, mode="talk-30", deck_close_content=None):
    """Build a minimal spec at the given mode with a single deck_close
    slide (using deck_close_content if provided, else canonical)."""
    content = deck_close_content or _deck_close_content_valid()
    return {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": mode, "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{"id": 1, "substory_id": None,
                    "layout": "deck_close", "content": content}],
    }


def test_deck_close_in_LAYOUTS(ss):
    """deck_close is in the LAYOUTS tuple per D-086."""
    assert "deck_close" in ss.LAYOUTS


def test_deck_close_in_layout_checkers(ss):
    """deck_close has a dispatched validator (assert in module covers
    this too; pin explicitly)."""
    assert "deck_close" in ss.LAYOUT_CHECKERS


def test_deck_close_required_modes_only_talk_30(ss):
    """Per Adam Tier-0 DQ2: only mode=talk-30 (STRONG) gates deck_close
    presence. Below STRONG (lightning-5, talk-15 BRIEF) it stays
    optional and absence is silent."""
    assert ss.DECK_CLOSE_REQUIRED_MODES == frozenset({"talk-30"})


def test_deck_close_valid_content_passes(ss):
    """A canonical deck_close slide validates with no issues."""
    spec = _spec_with_deck_close(ss, mode="talk-30")
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "; ".join(i.format() for i in issues)


def test_deck_close_missing_unified_point_errors(ss):
    """unified_point is required (hard error if missing)."""
    content = _deck_close_content_valid()
    del content["unified_point"]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    err_paths = [i.path for i in issues if i.severity == "error"]
    assert any("unified_point" in p for p in err_paths)


def test_deck_close_missing_forward_call_errors(ss):
    content = _deck_close_content_valid()
    del content["forward_call"]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    err_paths = [i.path for i in issues if i.severity == "error"]
    assert any("forward_call" in p for p in err_paths)


def test_deck_close_missing_data_source_errors(ss):
    content = _deck_close_content_valid()
    del content["data_source"]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    err_paths = [i.path for i in issues if i.severity == "error"]
    assert any("data_source" in p for p in err_paths)


def test_deck_close_key_takeaways_too_few_errors(ss):
    """key_takeaways requires 3-5 items; 2 should error (and the rest
    of the spec still validates)."""
    content = _deck_close_content_valid()
    content["key_takeaways"] = ["only one", "and another"]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    err_paths = [i.path for i in issues if i.severity == "error"]
    assert any("key_takeaways" in p for p in err_paths)


def test_deck_close_key_takeaways_too_many_errors(ss):
    """key_takeaways requires 3-5 items; 6 should error."""
    content = _deck_close_content_valid()
    content["key_takeaways"] = [f"item {i}" for i in range(6)]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    err_paths = [i.path for i in issues if i.severity == "error"]
    assert any("key_takeaways" in p for p in err_paths)


def test_deck_close_key_takeaways_exactly_3_passes(ss):
    """3 key_takeaways (the lower bound) passes."""
    content = _deck_close_content_valid()
    content["key_takeaways"] = ["a", "b", "c"]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "; ".join(i.format() for i in issues)


def test_deck_close_key_takeaways_exactly_5_passes(ss):
    """5 key_takeaways (the upper bound) passes."""
    content = _deck_close_content_valid()
    content["key_takeaways"] = ["a", "b", "c", "d", "e"]
    spec = _spec_with_deck_close(ss, mode="talk-30",
                                 deck_close_content=content)
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "; ".join(i.format() for i in issues)


def test_deck_close_presence_required_on_talk_30(ss):
    """A talk-30 spec WITHOUT a deck_close slide emits the soft-warning
    presence finding per D-086."""
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{"id": 1, "substory_id": None, "layout": "big_idea",
                    "content": {"title": "headline"}}],
    }
    issues = ss.validate_slide_spec(spec)
    deck_close_warnings = [
        i for i in issues
        if "deck_close" in i.message and i.severity == "soft-warning"
    ]
    assert len(deck_close_warnings) == 1, (
        "exactly one deck_close presence soft-warning expected on "
        "talk-30 without deck_close; got: "
        + "; ".join(i.format() for i in issues)
    )
    # Cite D-086 in the message so operators can find the rationale
    assert "D-086" in deck_close_warnings[0].message


def test_deck_close_presence_silent_on_lightning_5(ss):
    """A lightning-5 spec WITHOUT a deck_close slide does NOT warn
    (mode-gated check fires only on talk-30 per Adam DQ2)."""
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "lightning-5", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{"id": 1, "substory_id": None, "layout": "big_idea",
                    "content": {"title": "headline"}}],
    }
    issues = ss.validate_slide_spec(spec)
    deck_close_warnings = [i for i in issues if "deck_close" in i.message]
    assert deck_close_warnings == []


def test_deck_close_presence_silent_on_talk_15(ss):
    """Same: talk-15 BRIEF is below STRONG; no deck_close gate."""
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-15", "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{"id": 1, "substory_id": None, "layout": "big_idea",
                    "content": {"title": "headline"}}],
    }
    issues = ss.validate_slide_spec(spec)
    deck_close_warnings = [i for i in issues if "deck_close" in i.message]
    assert deck_close_warnings == []


def test_deck_close_presence_silent_when_present_on_talk_30(ss):
    """A talk-30 spec WITH a deck_close slide does NOT trigger the
    presence soft-warning (the rule fires only on absence)."""
    spec = _spec_with_deck_close(ss, mode="talk-30")
    issues = ss.validate_slide_spec(spec)
    deck_close_warnings = [
        i for i in issues
        if "missing deck_close" in i.message
    ]
    assert deck_close_warnings == []


def test_example_slide_deck_close_is_valid(ss):
    """The canonical example_slide("deck_close") output validates."""
    slide = ss.example_slide("deck_close", slide_id=1, substory_id=None)
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "lightning-5",  # avoid the presence-gated warning
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [slide],
    }
    issues = ss.validate_slide_spec(spec)
    assert issues == [], "; ".join(i.format() for i in issues)
