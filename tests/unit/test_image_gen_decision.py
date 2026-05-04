"""Tests for v0.3.3 image_gen_decision Tier 1 decision layer.

Per V0_3_3_ARCHITECTURE.md §13 Tier 1 plan: 10 tests covering each
rule + edge cases + closed-set guarantee.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load image_gen_decision via spec_from_file_location so the test file
# doesn't need to be inside the skill package. Mirrors the pattern
# used by other unit tests in this suite.
_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import slide_spec  # noqa: E402
import image_gen_decision as igd  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub(layout: str, **content_overrides) -> dict:
    """Build a minimal slide stub with the given layout. The 'content'
    dict is layout-specific in real fragments; tests only need fields
    the decision layer reads (image_path on concept_illustration)."""
    content = {"title": "Test slide title."}
    if layout == "concept_illustration":
        # Default to slide_compose's TBD-placeholder convention.
        content.setdefault("image_path", "{TBD}")
        content.setdefault("image_prompt", "test prompt")
        content.setdefault("style", "scientific_illustration")
    content.update(content_overrides)
    return {"layout": layout, "content": content}


# ---------------------------------------------------------------------------
# Rule-by-rule tests
# ---------------------------------------------------------------------------

def test_rule_4_concept_illustration_strong_emits():
    """concept_illustration on STRONG tier with TBD placeholder → emit."""
    d = igd.decide(_stub("concept_illustration"), tier="STRONG", mode="talk-30")
    assert d.emit is True
    assert "concept_illustration" in d.reason


def test_rule_1_data_figure_skipped():
    d = igd.decide(_stub("data_figure"), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "own figure" in d.reason


def test_rule_2_data_table_skipped():
    d = igd.decide(_stub("data_table"), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "own figure" in d.reason


@pytest.mark.parametrize(
    "layout",
    [
        "title", "section_divider", "acknowledgments", "references",
        "qa_anticipated", "methods_summary", "cross_tenant_integration",
    ],
)
def test_rule_3_structural_layouts_skipped(layout: str):
    d = igd.decide(_stub(layout), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "structural" in d.reason


@pytest.mark.parametrize(
    "layout",
    [
        "claim_evidence", "workflow_diagram", "two_column_compare",
        "big_idea", "big_number", "implications",
    ],
)
def test_rule_5_deferred_layouts_skipped(layout: str):
    d = igd.decide(_stub(layout), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "v0.3.4" in d.reason


def test_rule_6_exploratory_blocks_concept_illustration_by_default():
    """EXPLORATORY tier blocks concept_illustration without opt-in."""
    d = igd.decide(
        _stub("concept_illustration"), tier="EXPLORATORY", mode="talk-30"
    )
    assert d.emit is False
    assert "EXPLORATORY" in d.reason


def test_rule_6_exploratory_with_opt_in_lets_concept_illustration_through():
    """The opt-in inversion of rule 6: --image-allow-exploratory."""
    d = igd.decide(
        _stub("concept_illustration"),
        tier="EXPLORATORY", mode="talk-30",
        user_opt_in_exploratory=True,
    )
    assert d.emit is True


def test_concept_illustration_with_resolved_image_path_skips():
    """If concept_illustration somehow already has a real image path
    (resume mode? cached fragment?), don't re-generate."""
    d = igd.decide(
        _stub("concept_illustration",
              image_path="working/05_images/S2-pos4.png"),
        tier="STRONG", mode="talk-30",
    )
    assert d.emit is False
    assert "skip re-generation" in d.reason


def test_unknown_layout_raises():
    """Layout not in slide_spec.LAYOUTS must raise UnknownLayoutError."""
    with pytest.raises(igd.UnknownLayoutError):
        igd.decide({"layout": "future_layout_v0_4"},
                   tier="STRONG", mode="talk-30")


def test_missing_layout_raises_keyerror():
    with pytest.raises(KeyError):
        igd.decide({"content": {}}, tier="STRONG", mode="talk-30")


# ---------------------------------------------------------------------------
# Closed-set guarantee
# ---------------------------------------------------------------------------

def test_all_layouts_have_a_verdict():
    """Every layout in slide_spec.LAYOUTS must produce a Decision.

    This is the closed-set assertion: drift between slide_spec and
    the decision-layer categorization surfaces immediately on any
    layout addition that doesn't update image_gen_decision.py."""
    for layout in slide_spec.LAYOUTS:
        d = igd.decide(_stub(layout), tier="STRONG", mode="talk-30")
        assert isinstance(d.emit, bool)
        assert d.layout == layout
        # concept_illustration is the only YES; everything else is NO.
        if layout == "concept_illustration":
            assert d.emit is True, (
                f"{layout}: STRONG tier with TBD placeholder should emit"
            )
        else:
            assert d.emit is False, (
                f"{layout}: should not emit in v0.3.3 (got {d.reason!r})"
            )


# ---------------------------------------------------------------------------
# Fragment-level tests
# ---------------------------------------------------------------------------

def test_decide_fragment_walks_all_slides():
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S2",
        "slides": [
            _stub("section_divider"),
            _stub("claim_evidence"),
            _stub("concept_illustration"),
            _stub("data_figure"),
        ],
    }
    decisions = igd.decide_fragment(
        fragment, tier="STRONG", mode="talk-30"
    )
    assert len(decisions) == 4
    assert [d.layout for d in decisions] == [
        "section_divider", "claim_evidence",
        "concept_illustration", "data_figure",
    ]
    assert [d.emit for d in decisions] == [False, False, True, False]
    # Slide_id format: substory_id-pos{N}, 0-indexed.
    assert [d.slide_id for d in decisions] == [
        "S2-pos0", "S2-pos1", "S2-pos2", "S2-pos3",
    ]
    assert all(d.substory_id == "S2" for d in decisions)


def test_decide_fragment_handles_intro_kind():
    """Intro fragments don't carry substory_id; the layer should label
    them 'intro' so slide_ids don't collide with 'pos0' from another
    substory-less fragment."""
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "intro",
        "slides": [
            _stub("section_divider"),
            _stub("claim_evidence"),
        ],
    }
    decisions = igd.decide_fragment(
        fragment, tier="STRONG", mode="talk-30"
    )
    assert len(decisions) == 2
    assert all(d.substory_id == "intro" for d in decisions)
    assert decisions[0].slide_id == "intro-pos0"


# ---------------------------------------------------------------------------
# Envelope + CLI tests
# ---------------------------------------------------------------------------

def test_emit_decisions_writes_envelope(tmp_path: Path):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    s1_fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [
            _stub("section_divider"),
            _stub("concept_illustration"),
        ],
    }
    s2_fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S2",
        "slides": [
            _stub("claim_evidence"),
            _stub("concept_illustration"),
        ],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(s1_fragment))
    (slides_dir / "S2_slides.json").write_text(json.dumps(s2_fragment))

    envelope = igd.emit_decisions(
        slides_dir, tier="STRONG", mode="talk-30"
    )
    assert envelope["schema_version"] == "image-decisions.v1"
    assert envelope["tier"] == "STRONG"
    assert envelope["user_opt_in_exploratory"] is False
    decisions = envelope["decisions"]
    # 4 slides total (2 per fragment), 2 concept_illustration → 2 emit.
    assert len(decisions) == 4
    assert sum(1 for d in decisions if d["emit"]) == 2
    yes = igd.yes_decisions(envelope)
    assert len(yes) == 2
    assert {d["slide_id"] for d in yes} == {"S1-pos1", "S2-pos1"}


def test_emit_decisions_skips_unparseable_fragment(tmp_path: Path, capsys):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    # Valid one
    valid = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [_stub("concept_illustration")],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(valid))
    # Malformed
    (slides_dir / "broken.json").write_text("{not valid json")

    envelope = igd.emit_decisions(
        slides_dir, tier="STRONG", mode="talk-30"
    )
    captured = capsys.readouterr()
    assert "broken.json" in captured.err
    assert "could not parse" in captured.err
    # Valid fragment still processed.
    assert len(envelope["decisions"]) == 1
    assert envelope["decisions"][0]["emit"] is True


def test_cli_emit_decisions_writes_file(tmp_path: Path):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [_stub("concept_illustration")],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(fragment))
    out_path = tmp_path / "decisions.json"

    rc = igd.main([
        "emit-decisions",
        "--slides-dir", str(slides_dir),
        "--tier", "STRONG",
        "--mode", "talk-30",
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.is_file()
    envelope = json.loads(out_path.read_text())
    assert envelope["schema_version"] == "image-decisions.v1"
    assert len(envelope["decisions"]) == 1


def test_cli_emit_decisions_with_allow_exploratory(tmp_path: Path):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [_stub("concept_illustration")],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(fragment))
    out_path = tmp_path / "decisions.json"

    rc = igd.main([
        "emit-decisions",
        "--slides-dir", str(slides_dir),
        "--tier", "EXPLORATORY",
        "--mode", "talk-30",
        "--allow-exploratory",
        "--out", str(out_path),
    ])
    assert rc == 0
    envelope = json.loads(out_path.read_text())
    assert envelope["user_opt_in_exploratory"] is True
    assert envelope["decisions"][0]["emit"] is True


def test_cli_emit_decisions_missing_slides_dir(tmp_path: Path, capsys):
    out_path = tmp_path / "decisions.json"
    rc = igd.main([
        "emit-decisions",
        "--slides-dir", str(tmp_path / "nonexistent"),
        "--tier", "STRONG",
        "--mode", "talk-30",
        "--out", str(out_path),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err
