"""Tests for m6_score.py — M6 A/B cut-over scoring script (Tier A).

Coverage:
- Metric extraction (per-source-file)
- Comparison logic (lower-is-better; tie band; n/a)
- Decision rule (≥4/6 on target + wall-clock ≥40%)
- Report rendering (Markdown shape pin)
- CLI argument validation + end-to-end with synthetic audit dirs
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
M6_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "m6_score.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def m6():
    return _import("m6_score", M6_PY)


def _make_audit_dir(tmp_path: Path,
                     *,
                     runs: list[dict] | None = None,
                     adversarial: dict | None = None,
                     cascade: dict | None = None,
                     validation: dict | None = None,
                     image_provenance: dict | None = None) -> Path:
    """Build a synthetic audit dir with the requested source files."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)

    if runs:
        runs_dir = audit / "runs"
        runs_dir.mkdir()
        for i, summary in enumerate(runs, 1):
            run_dir = runs_dir / f"run-{i}"
            run_dir.mkdir()
            (run_dir / "summary.json").write_text(
                json.dumps(summary), encoding="utf-8")

    if adversarial is not None:
        (audit / "adversarial_review.json").write_text(
            json.dumps(adversarial), encoding="utf-8")
    if cascade is not None:
        (audit / "review_cascade.json").write_text(
            json.dumps(cascade), encoding="utf-8")
    if validation is not None:
        (audit / "presentation_validation.json").write_text(
            json.dumps(validation), encoding="utf-8")
    if image_provenance is not None:
        (audit / "image_provenance.json").write_text(
            json.dumps(image_provenance), encoding="utf-8")
    return audit


# ---------------------------------------------------------------------------
# aggregate_runs
# ---------------------------------------------------------------------------

def test_aggregate_runs_sums_cost_and_elapsed(m6, tmp_path):
    audit = _make_audit_dir(tmp_path, runs=[
        {"total_cost_usd": 1.25, "total_elapsed_seconds": 300,
         "started_at": "2026-05-24T10:00:00Z",
         "finished_at": "2026-05-24T10:05:00Z", "exit_code": 0},
        {"total_cost_usd": 2.50, "total_elapsed_seconds": 600,
         "started_at": "2026-05-24T11:00:00Z",
         "finished_at": "2026-05-24T11:10:00Z", "exit_code": 0},
    ])
    out = m6.aggregate_runs(audit)
    assert out.n_runs == 2
    assert out.total_cost_usd == 3.75
    assert out.total_elapsed_seconds == 900
    assert out.earliest_started == "2026-05-24T10:00:00Z"
    assert out.latest_finished == "2026-05-24T11:10:00Z"
    assert out.exit_codes == [0, 0]


def test_aggregate_runs_returns_empty_on_missing_dir(m6, tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    out = m6.aggregate_runs(audit)
    assert out.n_runs == 0
    assert out.total_cost_usd == 0.0


def test_aggregate_runs_wall_clock_uses_timestamp_delta(m6, tmp_path):
    """M6 Tier A.1: metric 1's wall_clock_seconds is (latest_finished -
    earliest_started), NOT sum(per-stage elapsed). This is the
    user-perceived clock. For a single-run draft, the two should
    match when stages run sequentially; for parallel-compose
    architectures (v0.4), wall-clock < sum(elapsed)."""
    audit = _make_audit_dir(tmp_path, runs=[
        # Single run: 10 min wall-clock end-to-end
        {"total_cost_usd": 5.0,
         "total_elapsed_seconds": 600,  # sequential equivalent
         "started_at": "2026-05-25T10:00:00Z",
         "finished_at": "2026-05-25T10:10:00Z", "exit_code": 0}])
    out = m6.aggregate_runs(audit)
    # timestamp delta = 10 min = 600s
    assert out.wall_clock_seconds == 600.0
    assert out.total_elapsed_seconds == 600.0  # both agree here


def test_aggregate_runs_wall_clock_correctly_attributes_parallelism(m6, tmp_path):
    """The architectural promise of v0.4 parallel-compose: 4 substories
    composing in parallel for 10 min each take 10 min of wall-clock
    but sum to 40 min of stage-elapsed. wall_clock_seconds must
    measure the wall-clock; total_elapsed_seconds keeps the (larger)
    summed view. M6 metric 1 uses wall_clock_seconds."""
    audit = _make_audit_dir(tmp_path, runs=[
        # Simulated v0.4 parallel-compose: 4 stages × 10min each ran
        # concurrently. finalize_run.py sums to 40 min; wrapper
        # observes 10 min.
        {"total_cost_usd": 5.0,
         "total_elapsed_seconds": 2400,  # 4 × 600s (double-counted)
         "started_at": "2026-05-25T10:00:00Z",
         "finished_at": "2026-05-25T10:10:00Z", "exit_code": 0}])
    out = m6.aggregate_runs(audit)
    assert out.wall_clock_seconds == 600.0       # 10 min wrapper
    assert out.total_elapsed_seconds == 2400.0   # 40 min sum (kept for ref)


def test_aggregate_runs_wall_clock_spans_multiple_runs(m6, tmp_path):
    """For a draft with multiple runs (initial + resume), wall_clock
    spans from the earliest started to the latest finished — captures
    real wall-clock attributable to the draft. Doesn't double-count
    pauses between runs (operator-time isn't pipeline-time, but the
    delta-based measure captures all of it as a single span — the
    sum-based measure would skip the gap)."""
    audit = _make_audit_dir(tmp_path, runs=[
        {"total_cost_usd": 2.0, "total_elapsed_seconds": 300,
         "started_at": "2026-05-25T10:00:00Z",
         "finished_at": "2026-05-25T10:05:00Z", "exit_code": 0},
        # 2 hour gap (operator iteration)
        {"total_cost_usd": 3.0, "total_elapsed_seconds": 600,
         "started_at": "2026-05-25T12:00:00Z",
         "finished_at": "2026-05-25T12:10:00Z", "exit_code": 0},
    ])
    out = m6.aggregate_runs(audit)
    # earliest_started → latest_finished = 2h 10min = 7800s
    assert out.wall_clock_seconds == 7800.0
    # sum of per-stage elapsed: 900s (does NOT include the 2h gap)
    assert out.total_elapsed_seconds == 900.0


def test_aggregate_runs_wall_clock_falls_back_when_timestamps_missing(m6, tmp_path):
    """If summary.json doesn't have started_at/finished_at (legacy or
    malformed), wall_clock_seconds falls back to total_elapsed_seconds
    rather than 0 (which would falsely show v0.4 as infinitely fast)."""
    audit = _make_audit_dir(tmp_path, runs=[
        {"total_cost_usd": 1.0, "total_elapsed_seconds": 500,
         "exit_code": 0}])  # no started_at / finished_at
    out = m6.aggregate_runs(audit)
    assert out.wall_clock_seconds == 500.0  # fell back
    assert out.earliest_started is None
    assert out.latest_finished is None


def test_aggregate_runs_ignores_malformed_json(m6, tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    runs_dir = audit / "runs"
    runs_dir.mkdir()
    (runs_dir / "run-1").mkdir()
    (runs_dir / "run-1" / "summary.json").write_text("{not json")
    (runs_dir / "run-2").mkdir()
    (runs_dir / "run-2" / "summary.json").write_text(json.dumps(
        {"total_cost_usd": 5.00, "total_elapsed_seconds": 100,
         "started_at": "2026-05-24T10:00:00Z",
         "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}))
    out = m6.aggregate_runs(audit)
    assert out.n_runs == 1  # only the good one
    assert out.total_cost_usd == 5.00


# ---------------------------------------------------------------------------
# count_adversarial_findings
# ---------------------------------------------------------------------------

def test_adversarial_findings_from_adversarial_review(m6, tmp_path):
    audit = _make_audit_dir(tmp_path, adversarial={
        "summary": {"total_findings": 7}})
    assert m6.count_adversarial_findings(audit) == 7


def test_adversarial_findings_falls_back_to_cascade_tier3(m6, tmp_path):
    """If adversarial_review.json is absent but review_cascade.json has
    tier 3 (the adversarial wrapper), use its findings count."""
    audit = _make_audit_dir(tmp_path, cascade={
        "schema_version": "review-cascade.v1",
        "tiers": [
            {"name": "tier1", "findings": []},
            {"name": "tier2", "findings": []},
            {"name": "tier3", "findings": [{"x": 1}, {"x": 2}, {"x": 3}]},
        ],
    })
    assert m6.count_adversarial_findings(audit) == 3


def test_adversarial_findings_returns_none_when_absent(m6, tmp_path):
    audit = _make_audit_dir(tmp_path)
    assert m6.count_adversarial_findings(audit) is None


def test_adversarial_findings_adversarial_review_wins_over_cascade(m6, tmp_path):
    """When both files exist, adversarial_review.json is canonical."""
    audit = _make_audit_dir(tmp_path,
        adversarial={"summary": {"total_findings": 14}},
        cascade={"tiers": [{}, {}, {"findings": [{"x": 1}]}]},
    )
    assert m6.count_adversarial_findings(audit) == 14


# ---------------------------------------------------------------------------
# count_validator_failures
# ---------------------------------------------------------------------------

def test_validator_failures_counts_only_fail_status(m6, tmp_path):
    audit = _make_audit_dir(tmp_path, validation={
        "validators": [
            {"id": "P1", "status": "pass"},
            {"id": "P2", "status": "pass"},
            {"id": "P3", "status": "fail"},
            {"id": "P4", "status": "fail"},
            {"id": "P5", "status": "skipped"},  # not a failure
        ],
    })
    assert m6.count_validator_failures(audit) == 2


def test_validator_failures_returns_none_when_absent(m6, tmp_path):
    audit = _make_audit_dir(tmp_path)
    assert m6.count_validator_failures(audit) is None


# ---------------------------------------------------------------------------
# aggregate_image_budget
# ---------------------------------------------------------------------------

def test_image_budget_sums_entries(m6, tmp_path):
    audit = _make_audit_dir(tmp_path, image_provenance={
        "entries": [
            {"cost_usd": 0.045, "model": "x"},
            {"cost_usd": 0.046, "model": "x"},
            {"cost_usd": 0.044, "model": "x"},
        ],
    })
    out = m6.aggregate_image_budget(audit)
    assert out.n_images == 3
    assert abs(out.total_cost_usd - 0.135) < 1e-9


def test_image_budget_zero_when_no_provenance_file(m6, tmp_path):
    audit = _make_audit_dir(tmp_path)
    out = m6.aggregate_image_budget(audit)
    assert out.n_images == 0
    assert out.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# compare_lower_is_better
# ---------------------------------------------------------------------------

def test_compare_v0_4_wins_when_lower(m6):
    winner, delta = m6.compare_lower_is_better(100.0, 60.0)
    assert winner == "v0_4"
    assert abs(delta - (-40.0)) < 0.01


def test_compare_v0_3_wins_when_lower(m6):
    winner, delta = m6.compare_lower_is_better(60.0, 100.0)
    assert winner == "v0_3"
    assert abs(delta - 66.67) < 0.1  # 100 is 66.67% higher than 60


def test_compare_tie_when_within_band(m6):
    """Default tie band is ±5%. 100 vs 103 is a tie."""
    winner, delta = m6.compare_lower_is_better(100.0, 103.0)
    assert winner == "tie"


def test_compare_just_outside_tie_band(m6):
    """100 vs 95 is -5.0%, exactly at band — by `<=` semantics, tie."""
    winner_at_band, _ = m6.compare_lower_is_better(100.0, 95.0)
    assert winner_at_band == "tie"
    # 100 vs 94 is -6.0%, outside band — v0_4 wins
    winner_outside, _ = m6.compare_lower_is_better(100.0, 94.0)
    assert winner_outside == "v0_4"


def test_compare_n_a_when_missing(m6):
    assert m6.compare_lower_is_better(None, 50.0) == ("n/a", None)
    assert m6.compare_lower_is_better(50.0, None) == ("n/a", None)
    assert m6.compare_lower_is_better(None, None) == ("n/a", None)


def test_compare_handles_zero_baseline(m6):
    """v0_3 = 0 (baseline cost-free) means any v0_4 cost is a loss."""
    assert m6.compare_lower_is_better(0.0, 0.0) == ("tie", 0.0)
    winner, _ = m6.compare_lower_is_better(0.0, 5.0)
    assert winner == "v0_3"


def test_compare_subjective_higher_is_better(m6):
    """Metric 5 inverts: higher Likert is better."""
    assert m6.compare_subjective_higher_is_better(3, 4) == ("v0_4", 1.0)
    assert m6.compare_subjective_higher_is_better(4, 3) == ("v0_3", -1.0)
    assert m6.compare_subjective_higher_is_better(3, 3) == ("tie", 0.0)


# ---------------------------------------------------------------------------
# score_project
# ---------------------------------------------------------------------------

def test_score_project_v0_4_dominant_run(m6, tmp_path):
    """v0.4 faster + cheaper + fewer findings + fewer validator failures."""
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 20}},
        validation={"validators": [
            {"id": "P1", "status": "fail"},
            {"id": "P2", "status": "fail"},
            {"id": "P3", "status": "pass"},
        ]},
    )
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 7.0, "total_elapsed_seconds": 800,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:13:20Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 12}},
        validation={"validators": [
            {"id": "P1", "status": "pass"},
            {"id": "P2", "status": "pass"},
            {"id": "P3", "status": "pass"},
        ]},
    )
    score = m6.score_project("test", v3_audit, v4_audit)
    # 1: wall-clock — v0.4 800/1800 = -55.6%, v0.4 wins
    # 2: cost — v0.4 7/10 = -30%, v0.4 wins
    # 3: adversarial — v0.4 12/20 = -40%, v0.4 wins
    # 4: validator failures — v0.4 0/2 = -100%, v0.4 wins
    # 5: arc coherence — n/a (no subjective scores)
    # 6: image budget — tie (both 0)
    assert score.v0_4_wins == 4
    assert score.v0_3_wins == 0
    assert score.ties == 1  # image budget
    assert score.n_a == 1   # arc coherence


def test_score_project_with_subjective_scores(m6, tmp_path):
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}])
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 5.0, "total_elapsed_seconds": 900,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:15:00Z", "exit_code": 0}])
    score = m6.score_project(
        "test", v3_audit, v4_audit,
        subjective={"v0_3": 3, "v0_4": 4, "comment": "tighter"})
    # Metric 5 should now be a v0.4 win
    arc = next(m for m in score.metrics if m.name.startswith("5."))
    assert arc.winner == "v0_4"
    assert arc.v0_3 == 3
    assert arc.v0_4 == 4
    assert arc.note == "tighter"


# ---------------------------------------------------------------------------
# evaluate_decision (D-065 + D-066)
# ---------------------------------------------------------------------------

def test_decision_passes_when_4_of_6_on_target_and_wall_clock_40pct(m6, tmp_path):
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 20}},
        validation={"validators": [{"id": "P1", "status": "fail"}]},
    )
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 7.0, "total_elapsed_seconds": 700,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:11:40Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 12}},
        validation={"validators": [{"id": "P1", "status": "pass"}]},
    )
    target = m6.score_project("t", v3_audit, v4_audit,
        subjective={"v0_3": 3, "v0_4": 4})
    # Expected: 5 wins for v0.4 (1+2+3+4+5), 1 tie (image budget)
    assert target.v0_4_wins == 5
    decision = m6.evaluate_decision(target)
    assert decision.rule_passes is True
    assert decision.wall_clock_40pct_met is True
    assert "PASS" in decision.decision_text


def test_decision_fails_when_wall_clock_not_40pct(m6, tmp_path):
    """v0.4 wins 5/6 but wall-clock only 20% reduction → FAIL."""
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 20}},
        validation={"validators": [{"id": "P1", "status": "fail"}]},
    )
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 7.0, "total_elapsed_seconds": 1440,  # only -20%
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:24:00Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 12}},
        validation={"validators": [{"id": "P1", "status": "pass"}]},
    )
    target = m6.score_project("t", v3_audit, v4_audit,
        subjective={"v0_3": 3, "v0_4": 4})
    decision = m6.evaluate_decision(target)
    assert decision.rule_passes is False
    assert decision.wall_clock_40pct_met is False
    assert "FAIL" in decision.decision_text
    assert "wall-clock" in decision.decision_text


def test_decision_fails_when_under_4_wins_on_target(m6, tmp_path):
    """v0.4 wins only 3 of 6 → FAIL even with great wall-clock."""
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 10}},  # v0.4 worse
        validation={"validators": [{"id": "P1", "status": "pass"}]},
    )
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 5.0, "total_elapsed_seconds": 500,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:08:20Z", "exit_code": 0}],
        adversarial={"summary": {"total_findings": 30}},  # got WORSE
        validation={"validators": [{"id": "P1", "status": "fail"},
                                    {"id": "P2", "status": "fail"}]},
    )
    target = m6.score_project("t", v3_audit, v4_audit,
        subjective={"v0_3": 4, "v0_4": 3})  # v0.4 worse on Likert too
    decision = m6.evaluate_decision(target)
    # v0.4 wins: 1 (wall-clock), 2 (cost) — that's 2
    # v0.3 wins: 3 (adversarial), 4 (validator failures), 5 (subjective)
    # ties: 6 (image)
    assert target.v0_4_wins == 2
    assert decision.rule_passes is False


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def test_render_report_contains_all_metrics(m6, tmp_path):
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}])
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 5.0, "total_elapsed_seconds": 900,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:15:00Z", "exit_code": 0}])
    target = m6.score_project("ibd_phage_targeting", v3_audit, v4_audit)
    decision = m6.evaluate_decision(target)
    report = m6.render_report(target, None, decision)

    # Schema pin (so a future bump is explicit)
    assert "m6-score.v1" in report
    # Decision-rule pin: D-065 + D-066 named
    assert "D-065" in report
    assert "D-066" in report
    # All 6 metrics show up
    assert "1. wall-clock" in report
    assert "2. token cost" in report
    assert "3. adversarial findings" in report
    assert "4. validator failures" in report
    assert "5. arc coherence" in report
    assert "6. image budget" in report
    # Metric 7 is NOT in the report (dropped per D-065)
    assert "7." not in report
    assert "paper-review" not in report.lower()
    # Adam-veto section present
    assert "Adam-veto" in report
    assert "Ship v0.4 as default" in report


def test_render_report_handles_missing_sanity(m6, tmp_path):
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}])
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 5.0, "total_elapsed_seconds": 900,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:15:00Z", "exit_code": 0}])
    target = m6.score_project("ibd", v3_audit, v4_audit)
    decision = m6.evaluate_decision(target, sanity=None)
    report = m6.render_report(target, None, decision)
    # Only Target section, no Sanity section
    assert "## Target:" in report
    assert "## Sanity-check:" not in report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_missing_audit_dir_returns_1(m6, tmp_path):
    rc = m6.main([
        "--v0_3-target", str(tmp_path / "does-not-exist"),
        "--v0_4-target", str(tmp_path / "also-not-exist"),
    ])
    assert rc == 1


def test_cli_sanity_arg_pairing_required(m6, tmp_path):
    """--v0_3-sanity and --v0_4-sanity must come together."""
    v3 = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    v4 = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    extra = _make_audit_dir(tmp_path / "extra",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    rc = m6.main([
        "--v0_3-target", str(v3),
        "--v0_4-target", str(v4),
        "--v0_3-sanity", str(extra),
        # missing --v0_4-sanity
    ])
    assert rc == 1


def test_cli_end_to_end_writes_report(m6, tmp_path):
    v3_audit = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 10.0, "total_elapsed_seconds": 1800,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:30:00Z", "exit_code": 0}])
    v4_audit = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 5.0, "total_elapsed_seconds": 900,
               "started_at": "2026-05-24T11:00:00Z",
               "finished_at": "2026-05-24T11:15:00Z", "exit_code": 0}])
    out = tmp_path / "report.md"
    rc = m6.main([
        "--v0_3-target", str(v3_audit),
        "--v0_4-target", str(v4_audit),
        "--out", str(out),
    ])
    assert rc == 0
    assert out.is_file()
    body = out.read_text()
    assert "M6 A/B comparison report" in body
    assert "1. wall-clock" in body


def test_cli_subjective_scores_consumed(m6, tmp_path):
    """--subjective-scores JSON gets read + metric 5 reflects it."""
    v3 = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    v4 = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    subj_path = tmp_path / "subj.json"
    subj_path.write_text(json.dumps({
        "target": {"v0_3": 2, "v0_4": 5, "comment": "much tighter"}}))
    out = tmp_path / "report.md"
    rc = m6.main([
        "--v0_3-target", str(v3),
        "--v0_4-target", str(v4),
        "--subjective-scores", str(subj_path),
        "--out", str(out),
    ])
    assert rc == 0
    body = out.read_text()
    # The Likert score-line shows up
    assert "5. arc coherence" in body
    assert "2/5" in body  # v0_3 value
    assert "5/5" in body  # v0_4 value
    assert "much tighter" in body


def test_cli_subjective_scores_malformed_returns_2(m6, tmp_path):
    v3 = _make_audit_dir(tmp_path / "v3",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    v4 = _make_audit_dir(tmp_path / "v4",
        runs=[{"total_cost_usd": 1.0, "total_elapsed_seconds": 100,
               "started_at": "2026-05-24T10:00:00Z",
               "finished_at": "2026-05-24T10:01:40Z", "exit_code": 0}])
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    rc = m6.main([
        "--v0_3-target", str(v3),
        "--v0_4-target", str(v4),
        "--subjective-scores", str(bad),
    ])
    assert rc == 2
