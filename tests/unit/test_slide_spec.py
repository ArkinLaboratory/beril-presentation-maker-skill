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
    """v0.3.2 added data_table → 16 layouts."""
    assert len(ss.LAYOUTS) == 16
    assert len(set(ss.LAYOUTS)) == 16
    assert "data_table" in ss.LAYOUTS


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


def test_concept_styles_match_decisions(ss):
    """D-028: one layout with three style variants."""
    assert set(ss.CONCEPT_STYLES) == {"metaphor", "infographic", "conceptual_diagram"}


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
])
def test_example_slide_per_layout(ss, layout):
    """Each layout's example_slide() produces a slide that, when wrapped in
    a minimal spec with only that slide, validates."""
    slide = ss.example_slide(layout, slide_id=1, substory_id=None)
    spec = {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x",
        "mode": "talk-30",
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
