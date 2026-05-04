"""Tests for tools/revise_loop.py — review-rewrite loop driver.

Coverage:
  - Finding classification (revisable / addable / surface-only)
  - Spec helpers: find_slide / replace_slide / insert_slide
  - LoopState dict serialization
  - next_actions.md rendering
  - Top-level run_revise_loop with --dry-run (no claude calls)
  - Severity floor filtering
  - Max-revisions cap
  - Validator gate + rollback
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
    / "revise_loop.py"
)


@pytest.fixture(scope="module")
def rl():
    spec = importlib.util.spec_from_file_location("revise_loop", _TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["revise_loop"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Finding classification
# ---------------------------------------------------------------------------


def test_finding_register_drift_is_revisable(rl):
    f = rl.Finding(raw={"id": "F001", "class": "register_drift",
                        "severity": "P0", "slide_id": 8})
    assert f.is_revisable
    assert not f.is_addable
    assert not f.is_surface_only


def test_finding_claim_evidence_is_revisable(rl):
    f = rl.Finding(raw={"id": "F002", "class": "claim_evidence",
                        "severity": "P1", "slide_id": 4})
    assert f.is_revisable


def test_finding_qa_softball_is_revisable(rl):
    f = rl.Finding(raw={"id": "F003", "class": "qa_softball",
                        "severity": "P1", "slide_id": 22})
    assert f.is_revisable


def test_finding_substory_arc_is_revisable(rl):
    f = rl.Finding(raw={"id": "F004", "class": "substory_arc",
                        "severity": "P1", "slide_id": 19})
    assert f.is_revisable


def test_finding_missing_slide_is_addable(rl):
    f = rl.Finding(raw={"id": "F005", "class": "missing_slide",
                        "severity": "P0"})
    assert f.is_addable
    assert not f.is_revisable


def test_finding_throughline_is_surface_only(rl):
    f = rl.Finding(raw={"id": "F006", "class": "throughline",
                        "severity": "P1"})
    assert f.is_surface_only


def test_finding_narrative_weakness_is_surface_only(rl):
    """v2 backwards-compat: narrative_weakness still surfaces as info."""
    f = rl.Finding(raw={"id": "F007", "class": "narrative_weakness",
                        "severity": "info"})
    assert f.is_surface_only


def test_finding_central_objection_is_surface_only(rl):
    """v3: central_objection (renamed from narrative_weakness) surfaces
    as info — same role, different name. Both must route to surface-only
    so the dispatch table works against v2 and v3 audit files alike."""
    f = rl.Finding(raw={"id": "F007", "class": "central_objection",
                        "severity": "info"})
    assert f.is_surface_only


def test_finding_citation_reality_is_surface_only(rl):
    """v3 new class: citation_reality fires on questionable citations.
    Per adversarial team guidance: surface for human verification rather
    than auto-revise. citation_id is required by the producer's validator
    (D2); we don't enforce here, just route to surface-only."""
    f = rl.Finding(raw={"id": "F010", "class": "citation_reality",
                        "severity": "P1",
                        "citation_id": "scott2010ribosome",
                        "slide_id": 14})
    assert f.is_surface_only


def test_finding_unknown_class_is_surface_only(rl):
    f = rl.Finding(raw={"id": "F008", "class": "alien_class",
                        "severity": "P1"})
    assert f.is_surface_only


def test_finding_revisable_without_slide_id_is_not_revisable(rl):
    """A register_drift finding without a slide_id can't be revised."""
    f = rl.Finding(raw={"id": "F009", "class": "register_drift",
                        "severity": "P0"})
    assert not f.is_revisable


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_spec():
    return {
        "schema_version": "1.0",
        "project_id": "test",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [
            {"id": 1, "position": 0, "substory_id": "S1", "layout": "title",
             "content": {"title": "X", "presenter": "Y", "date": "2026-04-29"}},
            {"id": 2, "position": 1, "substory_id": "S1", "layout": "claim_evidence",
             "content": {"title": "Original title", "bullets": ["a", "b", "c"]}},
            {"id": 3, "position": 2, "substory_id": "S2", "layout": "data_figure",
             "content": {"title": "X", "figure": "figures/x.png", "caption": "y"}},
        ],
    }


def test_find_slide_in_spec_hit(rl, sample_spec):
    s = rl._find_slide_in_spec(sample_spec, 2)
    assert s is not None
    assert s["content"]["title"] == "Original title"


def test_find_slide_in_spec_miss(rl, sample_spec):
    s = rl._find_slide_in_spec(sample_spec, 99)
    assert s is None


def test_replace_slide_in_spec(rl, sample_spec):
    new_slide = {
        "layout": "claim_evidence",
        "content": {"title": "Revised title", "bullets": ["d", "e"]},
    }
    ok = rl._replace_slide_in_spec(sample_spec, 2, new_slide)
    assert ok
    s = rl._find_slide_in_spec(sample_spec, 2)
    assert s["content"]["title"] == "Revised title"
    # id / position / substory_id preserved
    assert s["id"] == 2
    assert s["position"] == 1
    assert s["substory_id"] == "S1"


def test_replace_slide_miss_returns_false(rl, sample_spec):
    ok = rl._replace_slide_in_spec(sample_spec, 99, {"layout": "x", "content": {}})
    assert not ok


def test_insert_slide_into_spec(rl, sample_spec):
    new_slide = {
        "position": 2,
        "substory_id": "S1",
        "layout": "claim_evidence",
        "content": {"title": "New", "bullets": ["x"]},
    }
    new_id = rl._insert_slide_into_spec(sample_spec, new_slide, position=2)
    assert new_id == 4  # max existing was 3
    # Verify positions shifted
    pos_to_id = {s["position"]: s["id"] for s in sample_spec["slides"]}
    assert pos_to_id[0] == 1
    assert pos_to_id[1] == 2
    assert pos_to_id[2] == 4  # new slide
    assert pos_to_id[3] == 3  # was at position 2, now at 3


# ---------------------------------------------------------------------------
# v0.3.1 wrinkle A1: position fallback when siblings lack `position`
# ---------------------------------------------------------------------------


def test_insert_slide_substory_anchor_when_positions_missing(rl):
    """When existing slides have no `position` field but the new slide
    has a substory_id matching some existing slides, insert immediately
    after the LAST existing slide of that substory (not at end-of-deck).
    """
    spec = {
        "slides": [
            {"id": 1, "substory_id": "S1", "layout": "title",
             "content": {"title": "a"}},
            {"id": 2, "substory_id": "S1", "layout": "claim_evidence",
             "content": {"title": "b", "bullets": ["x"]}},
            {"id": 3, "substory_id": "S2", "layout": "claim_evidence",
             "content": {"title": "c", "bullets": ["y"]}},
            {"id": 4, "substory_id": "S2", "layout": "claim_evidence",
             "content": {"title": "d", "bullets": ["z"]}},
        ]
    }
    new_slide = {
        "substory_id": "S1",
        "layout": "claim_evidence",
        "content": {"title": "new in S1", "bullets": ["q"]},
    }
    new_id = rl._insert_slide_into_spec(spec, new_slide, position=9)
    # New slide should land immediately AFTER the last S1 slide (id=2),
    # i.e. at array index 2. NOT at end-of-deck (which would be idx 4).
    assert new_id == 5
    assert spec["slides"][2]["id"] == 5  # new slide at idx 2
    assert spec["slides"][2]["substory_id"] == "S1"
    assert spec["slides"][3]["id"] == 3  # S2 slides shifted right
    assert spec["slides"][4]["id"] == 4


def test_insert_slide_position_as_array_index_fallback(rl):
    """When positions missing AND no substory_id match, fall back to
    interpreting `position` as a 1-based array index."""
    spec = {
        "slides": [
            {"id": 1, "layout": "title", "content": {"title": "a"}},
            {"id": 2, "layout": "claim_evidence",
             "content": {"title": "b", "bullets": ["x"]}},
            {"id": 3, "layout": "claim_evidence",
             "content": {"title": "c", "bullets": ["y"]}},
        ]
    }
    new_slide = {
        # No substory_id → can't anchor by substory
        "layout": "claim_evidence",
        "content": {"title": "new", "bullets": ["q"]},
    }
    # position=2 should land at array idx 1 (between slides 1 and 2)
    new_id = rl._insert_slide_into_spec(spec, new_slide, position=2)
    assert new_id == 4
    assert spec["slides"][1]["id"] == 4
    assert spec["slides"][2]["id"] == 2
    assert spec["slides"][3]["id"] == 3


def test_insert_slide_append_at_end_when_all_fallbacks_fail(rl):
    """When positions missing, no substory_id match, and position is out
    of array range → append at end (with stderr warning, but no crash)."""
    spec = {
        "slides": [
            {"id": 1, "layout": "title", "content": {"title": "a"}},
            {"id": 2, "layout": "claim_evidence",
             "content": {"title": "b", "bullets": ["x"]}},
        ]
    }
    new_slide = {
        # No substory_id, position=99 way out of range
        "layout": "claim_evidence",
        "content": {"title": "new", "bullets": ["q"]},
    }
    new_id = rl._insert_slide_into_spec(spec, new_slide, position=99)
    assert new_id == 3
    assert spec["slides"][-1]["id"] == 3


# ---------------------------------------------------------------------------
# LoopState
# ---------------------------------------------------------------------------


def test_loop_state_dict_round_trip(rl):
    state = rl.LoopState(
        findings_revised=["F001"],
        findings_added=["F003"],
        findings_skipped=["F002"],
        findings_failed=[],
        retries_per_slide={8: 1, 9: 2},
        cost_usd_cumulative=2.345,
        started_at="2026-04-29T13:00:00Z",
        finished_at="2026-04-29T13:05:00Z",
    )
    d = state.to_dict()
    assert d["findings_revised"] == ["F001"]
    assert d["findings_added"] == ["F003"]
    assert d["retries_per_slide"] == {"8": 1, "9": 2}  # keys str-ified for JSON
    assert d["cost_usd_cumulative"] == 2.345


# ---------------------------------------------------------------------------
# End-to-end with --dry-run (no claude calls)
# ---------------------------------------------------------------------------


@pytest.fixture
def dry_run_fixture(tmp_path, sample_spec):
    """Build a synthetic v0.3.1+ draft_dir with the 4-zone layout."""
    project_dir = tmp_path / "project"
    talks_dir = project_dir / "talks" / "draft_1"
    # v0.3.1 4-zone layout
    working_dir = talks_dir / "working"
    narrative_dir = talks_dir / "narrative"
    audit_dir = talks_dir / "audit"
    snapshots_dir = audit_dir / "snapshots"
    for d in (working_dir, narrative_dir, audit_dir, snapshots_dir,
              talks_dir / "deliverable"):
        d.mkdir(parents=True)

    (working_dir / "slide_spec.json").write_text(
        json.dumps(sample_spec), encoding="utf-8")
    (project_dir / "REPORT.md").write_text("# Report\n\nNothing.\n",
                                           encoding="utf-8")
    (narrative_dir / "00_throughline.md").write_text("# TL\n", encoding="utf-8")
    (narrative_dir / "02_substories.md").write_text("# substories\n", encoding="utf-8")
    (working_dir / "citation_pool.json").write_text("{}", encoding="utf-8")
    (working_dir / "curated_figures.md").write_text("# figures\n", encoding="utf-8")

    review = {
        "schema_version": "adversarial-review-presentation.v2",
        "draft_dir": str(talks_dir),
        "tier": "STRONG",
        "summary": {"total_findings": 4, "by_severity": {"P0": 2, "P1": 1, "P2": 0, "info": 1}},
        "findings": [
            {"id": "F001", "class": "register_drift", "severity": "P0",
             "slide_id": 2, "issue": "overclaims", "fix_target": "slide_compose.v1.md"},
            {"id": "F002", "class": "missing_slide", "severity": "P0",
             "slide_id": None, "issue": "no top-N slide", "fix_hint": "insert at position 2"},
            {"id": "F003", "class": "qa_softball", "severity": "P1",
             "slide_id": 3, "issue": "doesn't land"},
            {"id": "F004", "class": "narrative_weakness", "severity": "info",
             "issue": "the deck's biggest weakness"},
        ],
    }
    (audit_dir / "adversarial_review.json").write_text(
        json.dumps(review), encoding="utf-8")
    return talks_dir, project_dir


def test_dry_run_processes_p0_findings(rl, dry_run_fixture):
    talks_dir, _ = dry_run_fixture
    meta = rl.run_revise_loop(talks_dir, severity_floor="P0", dry_run=True)
    # P0 findings: F001 (revise) + F002 (add). F003 P1 + F004 info → skipped.
    assert "F001" in meta["findings_revised"]
    assert "F002" in meta["findings_added"]
    assert "F003" in meta["findings_skipped"]
    assert "F004" in meta["findings_skipped"]
    assert meta["cost_usd_cumulative"] == 0.0  # dry-run = no LLM calls


def test_dry_run_severity_floor_p1_processes_more(rl, dry_run_fixture):
    talks_dir, _ = dry_run_fixture
    meta = rl.run_revise_loop(talks_dir, severity_floor="P1", dry_run=True)
    # P0 + P1 processed; F003 (P1 qa_softball) is now revisable
    assert "F001" in meta["findings_revised"]
    assert "F002" in meta["findings_added"]
    assert "F003" in meta["findings_revised"]
    # F004 info still skipped
    assert "F004" in meta["findings_skipped"]


def test_dry_run_writes_metadata_and_next_actions(rl, dry_run_fixture):
    talks_dir, _ = dry_run_fixture
    rl.run_revise_loop(talks_dir, severity_floor="P0", dry_run=True)
    assert (talks_dir / "audit" / "revise_loop_metadata.json").is_file()
    # v0.3.1: next_actions.md lives under working/
    assert (talks_dir / "working" / "next_actions.md").is_file()
    # Pre-revise spec backup is now a snapshot under audit/snapshots/
    assert (talks_dir / "audit" / "snapshots" / "slide_spec.pre_revise.json").is_file()


def test_dry_run_max_revisions_cap(rl, dry_run_fixture):
    talks_dir, _ = dry_run_fixture
    # Cap at 1 — only F001 should process; F002 (the 2nd) is skipped
    meta = rl.run_revise_loop(talks_dir, severity_floor="P0",
                              max_revisions=1, dry_run=True)
    n_processed = (len(meta["findings_revised"]) + len(meta["findings_added"]))
    assert n_processed == 1


def test_next_actions_renders_failed_findings(rl, dry_run_fixture):
    talks_dir, _ = dry_run_fixture
    rl.run_revise_loop(talks_dir, severity_floor="P0", dry_run=True)
    # v0.3.1: next_actions.md lives under working/
    md = (talks_dir / "working" / "next_actions.md").read_text(encoding="utf-8")
    # Surface-only findings (F003, F004) appear in the markdown
    assert "F003" in md
    assert "F004" in md
    # v0.3.3.1: header text reflects v3 framing (central objection),
    # but a v2 fixture's narrative_weakness finding still routes here.
    # Backwards-compat: both class names match DECK_WIDE_OBJECTION_CLASSES.
    assert "central objection" in md.lower()


# ---------------------------------------------------------------------------
# v0.3.3.1 — adversarial v0.7.0.1 schema migration
# ---------------------------------------------------------------------------


@pytest.fixture
def dry_run_fixture_v3(tmp_path, sample_spec):
    """v0.3.3.1: parallel fixture using adversarial v3 schema. Mirrors
    dry_run_fixture but uses central_objection (v3 rename) instead of
    narrative_weakness (v2), and adds a citation_reality finding."""
    project_dir = tmp_path / "project"
    talks_dir = project_dir / "talks" / "draft_1"
    working_dir = talks_dir / "working"
    narrative_dir = talks_dir / "narrative"
    audit_dir = talks_dir / "audit"
    snapshots_dir = audit_dir / "snapshots"
    for d in (working_dir, narrative_dir, audit_dir, snapshots_dir,
              talks_dir / "deliverable"):
        d.mkdir(parents=True)

    (working_dir / "slide_spec.json").write_text(
        json.dumps(sample_spec), encoding="utf-8")
    (project_dir / "REPORT.md").write_text("# Report\n\nNothing.\n",
                                           encoding="utf-8")
    (narrative_dir / "00_throughline.md").write_text("# TL\n", encoding="utf-8")
    (narrative_dir / "02_substories.md").write_text("# substories\n", encoding="utf-8")
    (working_dir / "citation_pool.json").write_text("{}", encoding="utf-8")
    (working_dir / "curated_figures.md").write_text("# figures\n", encoding="utf-8")

    review = {
        "schema_version": "adversarial-review-presentation.v3",
        "draft_dir": str(talks_dir),
        "tier": "STRONG",
        "summary": {"total_findings": 4,
                    "by_severity": {"P0": 1, "P1": 2, "P2": 0, "info": 1}},
        "findings": [
            {"id": "F001", "class": "register_drift", "severity": "P0",
             "slide_id": 2, "issue": "overclaims",
             "fix_target": "slide_compose.v1.md"},
            # v3 NEW class: surface for human verification
            {"id": "F002", "class": "citation_reality", "severity": "P1",
             "slide_id": 4, "issue": "Scott et al. 2010 not in citation_pool",
             "citation_id": "scott2010ribosome"},
            {"id": "F003", "class": "qa_softball", "severity": "P1",
             "slide_id": 3, "issue": "doesn't land"},
            # v3 RENAMED class (was narrative_weakness in v2)
            {"id": "F004", "class": "central_objection", "severity": "info",
             "issue": "the deck conflates correlation with causation"},
        ],
    }
    (audit_dir / "adversarial_review.json").write_text(
        json.dumps(review), encoding="utf-8")
    return talks_dir, project_dir


def test_v3_schema_central_objection_routes_surface_only(rl, dry_run_fixture_v3):
    """v3 central_objection (renamed from narrative_weakness) still
    surfaces — same role, different class name."""
    talks_dir, _ = dry_run_fixture_v3
    meta = rl.run_revise_loop(talks_dir, severity_floor="P0", dry_run=True)
    assert "F004" in meta["findings_skipped"]
    md = (talks_dir / "working" / "next_actions.md").read_text(encoding="utf-8")
    assert "central objection" in md.lower()
    assert "correlation with causation" in md


def test_v3_schema_citation_reality_routes_surface_only(rl, dry_run_fixture_v3):
    """v3 NEW class citation_reality surfaces in next_actions with its
    own dedicated section + citation_id annotation. Per adversarial
    team: don't auto-revise."""
    talks_dir, _ = dry_run_fixture_v3
    meta = rl.run_revise_loop(talks_dir, severity_floor="P1", dry_run=True)
    # F002 is citation_reality at P1 → surface-only even at floor=P1
    assert "F002" in meta["findings_skipped"]
    md = (talks_dir / "working" / "next_actions.md").read_text(encoding="utf-8")
    assert "Citation verification needed" in md
    assert "scott2010ribosome" in md
    # Other surface-only findings still appear
    assert "central objection" in md.lower()


def test_v3_schema_dispatch_unchanged_for_existing_classes(rl, dry_run_fixture_v3):
    """register_drift + qa_softball + missing_slide dispatches don't
    change between v2 and v3 schemas — only narrative_weakness rename
    and citation_reality addition affect surface-only routing."""
    talks_dir, _ = dry_run_fixture_v3
    meta = rl.run_revise_loop(talks_dir, severity_floor="P1", dry_run=True)
    assert "F001" in meta["findings_revised"]   # register_drift P0
    assert "F003" in meta["findings_revised"]   # qa_softball P1


def test_v2_audit_files_still_readable_post_migration(rl, dry_run_fixture):
    """Adversarial v2 acceptance is still on per the producer; consumer-
    side dispatch must accept v2 audit files for forensic compat. The
    existing dry_run_fixture uses v2 schema with narrative_weakness;
    test_dry_run_processes_p0_findings et al cover this implicitly,
    but pin it explicitly here so the migration's 'transition release'
    semantics don't get accidentally tightened."""
    talks_dir, _ = dry_run_fixture
    meta = rl.run_revise_loop(talks_dir, severity_floor="P0", dry_run=True)
    # F004 (narrative_weakness, v2 schema) routes to surface-only
    assert "F004" in meta["findings_skipped"]
    md = (talks_dir / "working" / "next_actions.md").read_text(encoding="utf-8")
    # v3-framed header still applies because both class names map to the
    # same DECK_WIDE_OBJECTION_CLASSES tuple.
    assert "central objection" in md.lower()


# ---------------------------------------------------------------------------
# next_actions rendering — direct
# ---------------------------------------------------------------------------


def test_render_next_actions_minimal(rl):
    review = {
        "reviewer_model": "test-model",
        "reviewed_at": "2026-04-29T13:00:00Z",
        "findings": [
            {"id": "F001", "class": "register_drift", "severity": "P0",
             "slide_id": 8, "issue": "x"},
        ],
    }
    state = rl.LoopState(
        findings_revised=["F001"],
        findings_added=[],
        findings_skipped=[],
        findings_failed=[],
        cost_usd_cumulative=0.5,
        started_at="2026-04-29T13:00:00Z",
        finished_at="2026-04-29T13:05:00Z",
    )
    paths = {"draft_dir": Path("/tmp/draft")}
    md = rl._render_next_actions(review, state, paths)
    assert "**Revised:** 1 (F001)" in md
    assert "Cost:** ~$0.50" in md
    assert "Fixed by the loop" in md
