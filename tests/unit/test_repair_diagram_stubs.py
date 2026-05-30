"""Tests for tools/repair_diagram_stubs.py.

The repair script coerces malformed workflow_diagram and
cross_tenant_integration data_flow_diagram content into schema-conformant
stubs. Tests cover:

  - Shape coercion (invented vocab → 7-shape vocabulary)
  - Edge-kind coercion (missing/invented → 3-kind vocabulary)
  - Missing diagram.kind → boxes_and_arrows
  - Missing geometry → linear horizontal flow
  - Idempotency (already-valid spec is unchanged)
  - End-to-end: repaired spec passes slide_spec validation
  - Coercion report content
  - Live-failure regression (the actual failing payload from
    2026-04-26 functional_dark_matter smoke run)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)
sys.path.insert(0, str(TOOLS_DIR))

import repair_diagram_stubs as rds  # noqa: E402
import slide_spec  # noqa: E402


# ---------------------------------------------------------------------------
# Unit tests on the coerce_* helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("rectangle", "rectangle"),       # already valid — no change
    ("rounded", "rounded"),
    ("ellipse", "ellipse"),
    ("data_input", "parallelogram"),  # generic flowchart vocab → schema
    ("output", "parallelogram"),
    ("process", "rectangle"),
    ("decision", "ellipse"),
    ("database", "cylinder"),
    ("annotation", "callout"),
    ("nonsense", "rectangle"),         # unknown → default rectangle
    (None, "rectangle"),                # None → default
    ("", "rectangle"),                  # empty → default
    ("Process", "rectangle"),           # case-insensitive
    ("DATA_INPUT", "parallelogram"),
])
def test_coerce_shape(raw, expected):
    coerced, _orig = rds.coerce_shape(raw)
    assert coerced == expected


def test_coerce_shape_returns_original_on_change():
    coerced, orig = rds.coerce_shape("data_input")
    assert coerced == "parallelogram"
    assert orig == "data_input"


def test_coerce_shape_returns_none_when_unchanged():
    coerced, orig = rds.coerce_shape("rectangle")
    assert coerced == "rectangle"
    assert orig is None


@pytest.mark.parametrize("raw,expected", [
    ("straight", "straight"),
    ("elbow", "elbow"),
    ("curved", "curved"),
    ("line", "straight"),
    ("arrow", "straight"),
    ("right_angle", "elbow"),
    ("bezier", "curved"),
    (None, "straight"),
    ("", "straight"),
    ("nonsense", "straight"),
])
def test_coerce_edge_kind(raw, expected):
    coerced, _orig = rds.coerce_edge_kind(raw)
    assert coerced == expected


def test_compute_linear_geometry_4_nodes():
    # CONTENT_LEFT=0.5, CONTENT_WIDTH=9.0, gap=0.4
    # node_w = (9.0 - 5*0.4) / 4 = 7.0 / 4 = 1.75
    # node_0 x = 0.5 + 1*0.4 + 0*1.75 = 0.9
    # node_1 x = 0.5 + 2*0.4 + 1*1.75 = 1.3 + 1.75 = wait, let me recompute
    # Actually: x = CONTENT_LEFT + (i+1)*gap + i*node_w
    # i=0: 0.5 + 0.4 + 0 = 0.9
    # i=1: 0.5 + 0.8 + 1.75 = 3.05
    # i=2: 0.5 + 1.2 + 3.5 = 5.2
    # i=3: 0.5 + 1.6 + 5.25 = 7.35
    geoms = [rds.compute_linear_geometry(4, i) for i in range(4)]
    xs = [g["x"] for g in geoms]
    assert xs == [0.9, 3.05, 5.2, 7.35]
    # All same width / height
    assert {g["w"] for g in geoms} == {1.75}
    assert {g["h"] for g in geoms} == {0.9}
    # All nodes inside content region (0.5..9.5 horizontal)
    for g in geoms:
        assert 0.5 <= g["x"]
        assert g["x"] + g["w"] <= 9.5


def test_compute_linear_geometry_floors_node_width():
    # 20 nodes would normally produce node_w < 0.6 — should floor to 0.6
    g = rds.compute_linear_geometry(20, 0)
    assert g["w"] >= 0.6


# ---------------------------------------------------------------------------
# Diagram-level repair tests
# ---------------------------------------------------------------------------

def test_repair_diagram_idempotent_on_valid():
    """Already-valid diagram should pass through unchanged (no coercions)."""
    valid = {
        "kind": "boxes_and_arrows",
        "nodes": [
            {"id": "a", "label": "A", "shape": "rectangle",
             "x": 1.0, "y": 1.0, "w": 1.5, "h": 0.9},
            {"id": "b", "label": "B", "shape": "rectangle",
             "x": 3.5, "y": 1.0, "w": 1.5, "h": 0.9},
        ],
        "edges": [{"from": "a", "to": "b", "kind": "straight"}],
    }
    coercions = []
    out = rds.repair_diagram(valid, "$.test", coercions)
    assert coercions == [], f"unexpected coercions: {coercions}"
    assert out["kind"] == "boxes_and_arrows"
    assert len(out["nodes"]) == 2
    assert len(out["edges"]) == 1


def test_repair_diagram_coerces_shapes_and_geometry():
    """Real failure shape from 2026-04-26 smoke."""
    invalid = {
        # Missing kind
        "nodes": [
            {"id": "n1", "label": "Top 500", "shape": "data_input"},
            {"id": "n2", "label": "Greedy", "shape": "process"},
            {"id": "n3", "label": "Roadmap", "shape": "output"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "candidates"},  # missing kind
            {"from": "n2", "to": "n3", "label": "optimized"},   # missing kind
        ],
    }
    coercions = []
    out = rds.repair_diagram(invalid, "$.test", coercions)
    # kind added
    assert out["kind"] == "boxes_and_arrows"
    # Shapes coerced
    shapes = [n["shape"] for n in out["nodes"]]
    assert shapes == ["parallelogram", "rectangle", "parallelogram"]
    # Geometry computed
    for n in out["nodes"]:
        assert isinstance(n["x"], (int, float))
        assert isinstance(n["y"], (int, float))
        assert isinstance(n["w"], (int, float))
        assert isinstance(n["h"], (int, float))
    # Edge kinds coerced to straight
    for e in out["edges"]:
        assert e["kind"] == "straight"
    # Coercions logged
    assert len(coercions) >= 6  # 1 kind + 3 shapes + 3 geometry + 2 edges


def test_repair_diagram_drops_non_object_nodes():
    invalid = {
        "kind": "boxes_and_arrows",
        "nodes": [
            "not-an-object",  # invalid
            {"id": "ok", "label": "OK", "shape": "rectangle",
             "x": 1, "y": 1, "w": 1, "h": 1},
        ],
        "edges": [],
    }
    coercions = []
    out = rds.repair_diagram(invalid, "$.test", coercions)
    assert len(out["nodes"]) == 1
    assert out["nodes"][0]["id"] == "ok"
    assert any("not an object" in c for c in coercions)


# ---------------------------------------------------------------------------
# Top-level repair_spec tests
# ---------------------------------------------------------------------------

def _make_minimal_spec(workflow_diagram_content: dict) -> dict:
    """Build a minimal valid slide_spec with one workflow_diagram slide.

    Uses mode=lightning-5 to avoid the v0.7/D-086 deck_close-presence
    soft-warning (talk-30 STRONG would require a deck_close slide;
    repair-diagram tests are orthogonal to that contract)."""
    return {
        "schema_version": slide_spec.SCHEMA_VERSION,
        "project_id": "test",
        "mode": "lightning-5",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {
            "id": "TL1", "punchline": "Test punchline",
            "tier_evidence": "STRONG",
        },
        "substories": [{"id": "S1", "punchline": "S1 punchline",
                        "slide_ids": [1]}],
        "slides": [{
            "id": 1,
            "layout": "workflow_diagram",
            "substory_id": "S1",
            "content": {
                "title": "Test workflow",
                "diagram": workflow_diagram_content,
                "step_caption": ["one", "two", "three"],
            },
        }],
    }


def test_repair_spec_makes_invalid_diagram_validate():
    """The actual smoke-failure regression: post-repair spec validates."""
    bad_diagram = {
        "nodes": [
            {"id": "a", "label": "A", "shape": "data_input"},
            {"id": "b", "label": "B", "shape": "process"},
            {"id": "c", "label": "C", "shape": "output"},
        ],
        "edges": [
            {"from": "a", "to": "b", "label": "x"},
            {"from": "b", "to": "c", "label": "y"},
        ],
    }
    spec = _make_minimal_spec(bad_diagram)

    # Pre-repair: validation fails
    pre_issues = slide_spec.validate_slide_spec(spec)
    assert pre_issues, "pre-repair spec should fail validation"

    # Repair
    new_spec, coercions = rds.repair_spec(spec)
    assert len(coercions) > 0

    # Post-repair: validation passes
    post_issues = slide_spec.validate_slide_spec(new_spec)
    assert post_issues == [], (
        "post-repair spec must validate; remaining issues:\n  "
        + "\n  ".join(i.format() for i in post_issues)
    )


def test_repair_spec_idempotent_on_valid():
    valid_diagram = {
        "kind": "boxes_and_arrows",
        "nodes": [
            {"id": "a", "label": "A", "shape": "rectangle",
             "x": 1.0, "y": 1.0, "w": 1.5, "h": 0.9},
            {"id": "b", "label": "B", "shape": "rectangle",
             "x": 3.5, "y": 1.0, "w": 1.5, "h": 0.9},
        ],
        "edges": [{"from": "a", "to": "b", "kind": "straight"}],
    }
    spec = _make_minimal_spec(valid_diagram)
    new_spec, coercions = rds.repair_spec(spec)
    assert coercions == []
    # Spec content unchanged
    assert new_spec["slides"][0]["content"]["diagram"] == valid_diagram


def test_repair_spec_handles_no_diagram_slides():
    """A spec with no workflow_diagram slides should pass through cleanly."""
    spec = {
        "schema_version": slide_spec.SCHEMA_VERSION,
        "project_id": "test",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [{"id": "S1", "punchline": "x",
                        "slide_ids": [1]}],
        "slides": [{
            "id": 1, "layout": "claim_evidence", "substory_id": "S1",
            "content": {"title": "T", "bullets": ["b1"]},
        }],
    }
    new_spec, coercions = rds.repair_spec(spec)
    assert coercions == []
    assert new_spec == spec


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_writes_repaired_spec_and_report(tmp_path: Path):
    bad_diagram = {
        "nodes": [
            {"id": "a", "label": "A", "shape": "data_input"},
            {"id": "b", "label": "B", "shape": "output"},
        ],
        "edges": [{"from": "a", "to": "b", "label": "x"}],
    }
    spec = _make_minimal_spec(bad_diagram)
    in_path = tmp_path / "spec.json"
    in_path.write_text(json.dumps(spec))
    out_path = tmp_path / "spec.repaired.json"
    report_path = tmp_path / "report.md"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "repair_diagram_stubs.py"),
         "--in", str(in_path),
         "--out", str(out_path),
         "--report", str(report_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    # Output file is valid JSON
    repaired = json.loads(out_path.read_text())
    issues = slide_spec.validate_slide_spec(repaired)
    assert issues == []

    # Report names the coercions
    report = report_path.read_text()
    assert "coercion(s) applied" in report
    assert "'data_input'" in report and "parallelogram" in report
    assert "'output'" in report


def test_cli_idempotent_writes_empty_report(tmp_path: Path):
    valid_diagram = {
        "kind": "boxes_and_arrows",
        "nodes": [
            {"id": "a", "label": "A", "shape": "rectangle",
             "x": 1.0, "y": 1.0, "w": 1.5, "h": 0.9},
        ],
        "edges": [],
    }
    spec = _make_minimal_spec(valid_diagram)
    in_path = tmp_path / "spec.json"
    in_path.write_text(json.dumps(spec))
    out_path = tmp_path / "spec.repaired.json"
    report_path = tmp_path / "report.md"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "repair_diagram_stubs.py"),
         "--in", str(in_path),
         "--out", str(out_path),
         "--report", str(report_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0
    report = report_path.read_text()
    assert "No coercions applied" in report


# ----------------------------------------------------------------------
# Bullet-count repair tests (added 2026-04-26 from intro smoke failures)
# ----------------------------------------------------------------------

def test_repair_bullets_truncates_overlong_claim_evidence():
    coercions = []
    content = {
        "title": "Goal: ...",
        "bullets": [
            "Bullet one",
            "Bullet two",
            "Bullet three",
            "Bullet four (over cap)",
        ],
    }
    out = rds.repair_bullets("claim_evidence", content, "$.test", coercions)
    assert len(out["bullets"]) == 3
    assert out["bullets"] == ["Bullet one", "Bullet two", "Bullet three"]
    assert any("truncated 4" in c for c in coercions)


def test_repair_bullets_truncates_overlong_implications():
    coercions = []
    content = {
        "title": "Implications",
        "bullets": [
            {"claim": "C1", "evidence_pointer": "P1"},
            {"claim": "C2", "evidence_pointer": "P2"},
            {"claim": "C3", "evidence_pointer": "P3"},
            {"claim": "C4", "evidence_pointer": "P4"},
        ],
    }
    out = rds.repair_bullets("implications", content, "$.test", coercions)
    assert len(out["bullets"]) == 3
    assert any("truncated 4" in c for c in coercions)


def test_repair_bullets_truncates_overlong_references():
    coercions = []
    content = {
        "refs_short": [f"ref{i}" for i in range(10)],  # 10 entries, cap is 8
    }
    out = rds.repair_bullets("references", content, "$.test", coercions)
    assert len(out["refs_short"]) == 8
    assert any("truncated 10" in c for c in coercions)


def test_repair_bullets_logs_methods_summary_underflow():
    """Methods_summary needs ≥5 bullets; coercion can't fabricate content."""
    coercions = []
    content = {
        "title": "Methods",
        "bullets": ["m1", "m2", "m3", "m4"],  # 4 < 5 floor
    }
    out = rds.repair_bullets("methods_summary", content, "$.test", coercions)
    # Bullets unchanged (can't pad with fake content)
    assert out["bullets"] == ["m1", "m2", "m3", "m4"]
    # But coercion logged so user knows
    assert any("4 entries below methods_summary floor" in c
               for c in coercions)


def test_repair_bullets_idempotent_on_valid():
    """Already-valid bullet count: no coercion logged."""
    coercions = []
    content = {"title": "T", "bullets": ["a", "b", "c"]}
    out = rds.repair_bullets("claim_evidence", content, "$.test", coercions)
    assert out["bullets"] == ["a", "b", "c"]
    assert coercions == []


def test_repair_bullets_unaffected_layouts():
    """Layouts without bullet caps in our table pass through."""
    coercions = []
    content = {"title": "Title", "presenter": "X", "date": "2026-04-26"}
    out = rds.repair_bullets("title", content, "$.test", coercions)
    assert out == content
    assert coercions == []


def test_repair_spec_runs_bullet_repair_alongside_diagram_repair():
    """End-to-end: spec with both diagram AND bullet violations
    gets both repaired in one pass.

    Uses mode=lightning-5 to avoid the v0.7/D-086 deck_close-presence
    warning that's orthogonal to the diagram + bullet repair tested
    here."""
    spec = {
        "schema_version": slide_spec.SCHEMA_VERSION,
        "project_id": "test",
        "mode": "lightning-5",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [{"id": "S1", "punchline": "x",
                        "slide_ids": [1]}],
        "slides": [{
            "id": 1,
            "layout": "claim_evidence",
            "substory_id": "S1",
            "content": {
                "title": "Goal",
                "bullets": ["a", "b", "c", "d", "e"],  # 5 bullets, cap 3
            },
        }],
    }
    new_spec, coercions = rds.repair_spec(spec)
    assert len(new_spec["slides"][0]["content"]["bullets"]) == 3
    assert any("truncated 5" in c for c in coercions)
    issues = slide_spec.validate_slide_spec(new_spec)
    assert issues == []


def test_repair_spec_real_world_intro_failure(tmp_path: Path):
    """Regression for the 2026-04-26 draft_4 failure: intro produced
    methods_summary with 4 bullets (< 5 floor). Repair logs the issue
    but can't fix it; validator will still fail with a clear pointer."""
    spec = {
        "schema_version": slide_spec.SCHEMA_VERSION,
        "project_id": "functional_dark_matter",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [{"id": "S1", "punchline": "x",
                        "slide_ids": [2]}],
        "slides": [
            {"id": 1, "layout": "title",
             "content": {"title": "T", "presenter": "X",
                         "date": "2026-04-26"}},
            {"id": 2, "layout": "section_divider",
             "substory_id": "S1",
             "content": {"punchline": "p", "substory_number": 1}},
            {"id": 3, "layout": "methods_summary",  # 4-bullet violation
             "content": {
                 "title": "Approach",
                 "bullets": ["m1", "m2", "m3", "m4"],  # < 5
             }},
        ],
    }
    new_spec, coercions = rds.repair_spec(spec)
    assert any("methods_summary floor" in c for c in coercions)
    # Validator still fails for this case (can't pad), per design
    issues = slide_spec.validate_slide_spec(new_spec)
    assert any("must be a list of 5" in i.message for i in issues), (
        "validator should still flag underflow methods_summary; "
        "repair cannot pad without fabricating content"
    )


def test_cli_fails_on_missing_input(tmp_path: Path):
    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "repair_diagram_stubs.py"),
         "--in", str(tmp_path / "does-not-exist.json"),
         "--out", str(tmp_path / "out.json")],
        capture_output=True, text=True,
    )
    assert rc.returncode == 1
