"""Tests for review_cascade.py — tiered review cascade orchestrator
(v0.4 M4b Tier A scaffolding).

Coverage:
- Cascade contract (CascadeReport, TierResult, CascadeFinding shape +
  JSON schema).
- Tier-A scaffolding: per-tier dispatchers return 'not-implemented'.
- Orchestrator semantics (DQ4 operator-gated short-circuit):
  - Tier 1 P0 → Tier 2 + Tier 3 SKIPPED.
  - Tier 1 clear + Tier 2 findings (advisory) → Tier 3 RUNS.
  - --no-tier2 / --no-tier3 skip the respective tier.
- Stub-report when slide_spec.json missing (mirrors visual_qa.py +
  reconcile_deck.py degradation posture).
- CLI smoke (rc=0 always).
- MD rendering carries the per-tier status + short-circuit note.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "review_cascade.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rc():
    return _import("review_cascade", RC_PY)


# ---------------------------------------------------------------------------
# Cascade contract (schema)
# ---------------------------------------------------------------------------

def test_schema_version_pinned(rc):
    """The cascade JSON consumer contract is review-cascade.v1."""
    assert rc.SCHEMA_VERSION == "review-cascade.v1"


def test_tier_statuses_complete(rc):
    """The status vocabulary covers every state Tiers B/C/D will need."""
    expected = {"pass", "advisory", "fail", "skipped",
                "not-implemented", "error"}
    assert set(rc.TIER_STATUSES) == expected


def test_cascade_finding_to_dict_shape(rc):
    """CascadeFinding.to_dict() carries the cascade JSON consumer's
    expected per-finding shape."""
    f = rc.CascadeFinding(
        tier="tier1", kind="P3", severity="P0", slide_id=5,
        detail="numeric provenance fail",
        evidence={"violations": ["97.2%"]},
    )
    d = f.to_dict()
    assert d == {
        "tier": "tier1", "kind": "P3", "severity": "P0", "slide_id": 5,
        "detail": "numeric provenance fail",
        "evidence": {"violations": ["97.2%"]},
    }


def test_tier_result_has_p0_detects_severity(rc):
    """TierResult.has_p0 is the short-circuit trigger."""
    no_p0 = rc.TierResult(name="tier1", status="advisory", findings=[
        rc.CascadeFinding(tier="tier1", kind="P10", severity="P1",
                          slide_id=2, detail="density warn"),
    ])
    with_p0 = rc.TierResult(name="tier1", status="fail", findings=[
        rc.CascadeFinding(tier="tier1", kind="P3", severity="P0",
                          slide_id=5, detail="numeric"),
    ])
    assert no_p0.has_p0 is False
    assert with_p0.has_p0 is True


def test_cascade_report_to_dict_carries_schema_version(rc):
    """CascadeReport JSON always carries schema_version + tiers +
    short_circuited_at + totals."""
    report = rc.CascadeReport(
        draft_dir="/tmp/d",
        tiers=[
            rc.TierResult(name="tier1", status="pass", cost_usd=0.0,
                          duration_sec=0.1),
            rc.TierResult(name="tier2", status="advisory",
                          cost_usd=0.05, duration_sec=2.1),
            rc.TierResult(name="tier3", status="pass",
                          cost_usd=0.85, duration_sec=12.3),
        ],
    )
    d = report.to_dict()
    assert d["schema_version"] == "review-cascade.v1"
    assert d["draft_dir"] == "/tmp/d"
    assert len(d["tiers"]) == 3
    assert d["short_circuited_at"] is None
    assert d["total_cost_usd"] == pytest.approx(0.90)
    assert d["total_duration_sec"] == pytest.approx(14.5)


def test_cascade_report_short_circuit_field(rc):
    """short_circuited_at is set when a tier has a P0 finding (cascade
    orchestration writes it; the field itself is just on the report)."""
    report = rc.CascadeReport(
        draft_dir="/tmp/d",
        tiers=[rc.TierResult(name="tier1", status="fail")],
        short_circuited_at="tier1",
    )
    assert report.to_dict()["short_circuited_at"] == "tier1"


# ---------------------------------------------------------------------------
# Tier-A scaffolding — per-tier dispatchers return 'not-implemented'
# ---------------------------------------------------------------------------

def test_tier1_scaffolding_not_implemented(rc, tmp_path):
    """Tier A ships the cascade contract; Tier B fills run_tier1."""
    result = rc.run_tier1(tmp_path)
    assert result.name == "tier1"
    assert result.status == "not-implemented"
    assert result.has_p0 is False


def test_tier2_scaffolding_not_implemented(rc, tmp_path):
    """Tier C will build review_tier2.py + prompts/review_tier2.v1.md."""
    result = rc.run_tier2(tmp_path)
    assert result.name == "tier2"
    assert result.status == "not-implemented"


def test_tier3_scaffolding_not_implemented(rc, tmp_path):
    """Tier D will wrap stage_adversarial_review under the cascade
    contract."""
    result = rc.run_tier3(tmp_path)
    assert result.name == "tier3"
    assert result.status == "not-implemented"


# ---------------------------------------------------------------------------
# Cascade orchestration semantics (DQ4 — operator-gated short-circuit)
# ---------------------------------------------------------------------------

def test_run_cascade_clear_runs_all_tiers(rc, tmp_path, monkeypatch):
    """Tier 1 emits no P0 → Tier 2 + Tier 3 RUN."""
    # Make tier1 return advisory (no P0)
    monkeypatch.setattr(rc, "run_tier1", lambda d: rc.TierResult(
        name="tier1", status="advisory",
        findings=[rc.CascadeFinding(
            tier="tier1", kind="P10", severity="P1",
            slide_id=2, detail="density warn",
        )],
    ))
    monkeypatch.setattr(rc, "run_tier2", lambda d: rc.TierResult(
        name="tier2", status="advisory", cost_usd=0.05,
    ))
    monkeypatch.setattr(rc, "run_tier3", lambda d: rc.TierResult(
        name="tier3", status="pass", cost_usd=0.85,
    ))
    report = rc.run_cascade(tmp_path)
    assert report.short_circuited_at is None
    assert [t.status for t in report.tiers] == ["advisory", "advisory", "pass"]
    assert report.total_cost_usd == pytest.approx(0.90)


def test_run_cascade_tier1_p0_short_circuits_2_and_3(rc, tmp_path, monkeypatch):
    """DQ4 operator-gated: Tier 1 P0 SHORT-CIRCUITS Tier 2 + Tier 3."""
    monkeypatch.setattr(rc, "run_tier1", lambda d: rc.TierResult(
        name="tier1", status="fail",
        findings=[rc.CascadeFinding(
            tier="tier1", kind="P3", severity="P0",
            slide_id=5, detail="numeric provenance fail",
        )],
    ))
    # Sentinels — these should NEVER be called
    monkeypatch.setattr(rc, "run_tier2", lambda d: pytest.fail(
        "Tier 2 must NOT run when Tier 1 short-circuits"))
    monkeypatch.setattr(rc, "run_tier3", lambda d: pytest.fail(
        "Tier 3 must NOT run when Tier 1 short-circuits"))

    report = rc.run_cascade(tmp_path)
    assert report.short_circuited_at == "tier1"
    assert [t.status for t in report.tiers] == ["fail", "skipped", "skipped"]
    # Total cost = Tier 1 only ($0 in this fixture — the real Tier 1 from
    # Tier B may carry small validate_presentation overhead)
    assert report.total_cost_usd == 0.0


def test_run_cascade_tier2_findings_never_gate_tier3(rc, tmp_path, monkeypatch):
    """DQ4 operator-gated: Tier 2 ALWAYS advisory — even if it emits
    findings, Tier 3 runs. The cascade has no Tier-2-→-short-circuit
    path (would defeat Tier 3's authority before calibration data is in)."""
    monkeypatch.setattr(rc, "run_tier1", lambda d: rc.TierResult(
        name="tier1", status="pass",
    ))
    monkeypatch.setattr(rc, "run_tier2", lambda d: rc.TierResult(
        name="tier2", status="advisory",
        findings=[rc.CascadeFinding(
            tier="tier2", kind="register_drift", severity="P1",
            slide_id=7, detail="passive voice on a STRONG-tier claim",
        )],
        cost_usd=0.05,
    ))
    tier3_called = {"yes": False}

    def _t3(d):
        tier3_called["yes"] = True
        return rc.TierResult(name="tier3", status="pass", cost_usd=0.85)

    monkeypatch.setattr(rc, "run_tier3", _t3)

    report = rc.run_cascade(tmp_path)
    assert tier3_called["yes"], "Tier 3 must run even when Tier 2 emits findings"
    assert report.short_circuited_at is None
    assert report.tiers[1].findings, "Tier 2 findings preserved"


def test_run_cascade_no_tier2_flag_skips_tier2(rc, tmp_path, monkeypatch):
    """--no-tier2 skips Tier 2; Tier 3 still runs (no short-circuit)."""
    monkeypatch.setattr(rc, "run_tier1", lambda d: rc.TierResult(
        name="tier1", status="pass"))
    monkeypatch.setattr(rc, "run_tier2", lambda d: pytest.fail(
        "Tier 2 must NOT run when --no-tier2 is set"))
    monkeypatch.setattr(rc, "run_tier3", lambda d: rc.TierResult(
        name="tier3", status="pass", cost_usd=0.85,
    ))
    report = rc.run_cascade(tmp_path, run_tier2_enabled=False)
    assert report.tiers[1].status == "skipped"
    assert "--no-tier2" in report.tiers[1].note
    assert report.tiers[2].status == "pass"   # Tier 3 still ran


def test_run_cascade_no_tier3_flag_skips_tier3(rc, tmp_path, monkeypatch):
    """--no-tier3 skips Tier 3; Tier 2 still runs."""
    monkeypatch.setattr(rc, "run_tier1", lambda d: rc.TierResult(
        name="tier1", status="pass"))
    monkeypatch.setattr(rc, "run_tier2", lambda d: rc.TierResult(
        name="tier2", status="advisory", cost_usd=0.05,
    ))
    monkeypatch.setattr(rc, "run_tier3", lambda d: pytest.fail(
        "Tier 3 must NOT run when --no-tier3 is set"))
    report = rc.run_cascade(tmp_path, run_tier3_enabled=False)
    assert report.tiers[1].status == "advisory"
    assert report.tiers[2].status == "skipped"
    assert "--no-tier3" in report.tiers[2].note


def test_run_cascade_scaffolding_end_to_end_not_implemented(rc, tmp_path):
    """Tier A scaffolding end-to-end: all three tiers emit
    'not-implemented' (no monkeypatch); cascade still completes."""
    report = rc.run_cascade(tmp_path)
    assert [t.status for t in report.tiers] == [
        "not-implemented", "not-implemented", "not-implemented",
    ]
    assert report.short_circuited_at is None
    assert report.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# Stub-report when slide_spec.json missing
# ---------------------------------------------------------------------------

def test_main_missing_spec_writes_stub_rc0(rc, tmp_path, capsys):
    """No working/slide_spec.json → cascade writes a stub report with
    all three tiers 'skipped' + a note; rc=0 (mirrors visual_qa.py +
    reconcile_deck.py)."""
    rc_val = rc.main([str(tmp_path), "--quiet"])
    assert rc_val == 0
    j = tmp_path / "audit" / "review_cascade.json"
    assert j.is_file()
    payload = json.loads(j.read_text())
    assert payload["schema_version"] == "review-cascade.v1"
    assert [t["status"] for t in payload["tiers"]] == [
        "skipped", "skipped", "skipped",
    ]
    assert "slide_spec.json missing" in payload["note"]


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_render_md_carries_per_tier_status(rc):
    """The MD report includes a per-tier section + the short-circuit
    note when applicable."""
    report = rc.CascadeReport(
        draft_dir="/tmp/d",
        tiers=[
            rc.TierResult(name="tier1", status="fail",
                          findings=[rc.CascadeFinding(
                              tier="tier1", kind="P3", severity="P0",
                              slide_id=5,
                              detail="numeric provenance fail")]),
            rc.TierResult(name="tier2", status="skipped",
                          note="skipped — short-circuited at tier1"),
            rc.TierResult(name="tier3", status="skipped",
                          note="skipped — short-circuited at tier1"),
        ],
        short_circuited_at="tier1",
    )
    md = rc.render_md(report)
    assert "# Review cascade report" in md
    assert "## tier1 — fail" in md
    assert "## tier2 — skipped" in md
    assert "## tier3 — skipped" in md
    assert "Short-circuited at tier1" in md
    assert "**P0** P3" in md and "slide 5" in md


def test_write_reports_creates_both_files(rc, tmp_path):
    """write_reports emits both audit/review_cascade.json and .md."""
    report = rc.CascadeReport(
        draft_dir=str(tmp_path),
        tiers=[rc.TierResult(name="tier1", status="pass"),
               rc.TierResult(name="tier2", status="advisory"),
               rc.TierResult(name="tier3", status="pass")],
    )
    audit_dir = tmp_path / "audit"
    j, m = rc.write_reports(report, audit_dir)
    assert j.is_file() and m.is_file()
    payload = json.loads(j.read_text())
    assert payload["schema_version"] == "review-cascade.v1"


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_returns_0_on_clean_scaffolding(rc, tmp_path):
    """CLI on a draft with slide_spec.json present → all three tiers
    not-implemented (Tier A scaffolding); rc=0."""
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    (spec_dir / "slide_spec.json").write_text(json.dumps({"slides": []}))
    rc_val = rc.main([str(tmp_path), "--quiet"])
    assert rc_val == 0
    j = tmp_path / "audit" / "review_cascade.json"
    payload = json.loads(j.read_text())
    assert [t["status"] for t in payload["tiers"]] == [
        "not-implemented", "not-implemented", "not-implemented",
    ]
    assert payload["short_circuited_at"] is None


def test_cli_no_tier2_no_tier3_propagate(rc, tmp_path):
    """--no-tier2 + --no-tier3 → Tier 1 runs (scaffolding stub), 2+3 skipped."""
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    (spec_dir / "slide_spec.json").write_text(json.dumps({"slides": []}))
    rc_val = rc.main([str(tmp_path), "--no-tier2", "--no-tier3", "--quiet"])
    assert rc_val == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_cascade.json").read_text())
    assert payload["tiers"][1]["status"] == "skipped"
    assert payload["tiers"][2]["status"] == "skipped"
    assert "--no-tier2" in payload["tiers"][1]["note"]
    assert "--no-tier3" in payload["tiers"][2]["note"]
