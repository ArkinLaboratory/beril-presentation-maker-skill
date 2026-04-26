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

def test_15_layouts_in_vocabulary(ss):
    assert len(ss.LAYOUTS) == 15
    assert len(set(ss.LAYOUTS)) == 15


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
    assert len(schema["$defs"]) >= 16   # 15 layouts + diagram


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
