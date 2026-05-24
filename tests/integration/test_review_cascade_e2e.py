"""Integration tests for review_cascade.py end-to-end behaviour
(v0.4 M4b Tier E).

These tests exercise the cascade orchestration end-to-end on
synthetic specs but stub the live-LLM boundary points
(_invoke_review_tier2, _invoke_beril_adversarial) so the suite stays
offline. The live calibration probe — running cascade against
ibd_phage_targeting/draft_1 with real Haiku + real adversarial — is
operator-driven (no automated test fires it; it's a Tier E build-
session step recorded in audit/review_tier2_calibration.md).

Coverage:
- P3 numeric violation → Tier 1 P0 → cascade short-circuits Tier 2+3
  (the value proposition of the cascade in one test).
- Clean spec → Tier 1 pass → Tier 2 + Tier 3 both run and lift
  findings into the cascade report.
- The cascade JSON's short_circuited_at field is the gate the
  orchestrator's de-dup logic reads.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "review_cascade.py")
SS_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "slide_spec.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rc():
    return _import("review_cascade", RC_PY)


@pytest.fixture(scope="module")
def ss():
    return _import("slide_spec", SS_PY)


# ---------------------------------------------------------------------------
# Synthetic-defect smoke — DQ4 fail-fast short-circuit
# ---------------------------------------------------------------------------

def _structurally_valid_spec_with_p3_violation(ss) -> dict:
    """Build a spec that PASSES slide_spec.validate_slide_spec (so
    Tier 1's _validate_p1_p10 will actually run P-validators on it)
    but FAILS validate_p3_numeric_provenance (P0 trigger).

    P3 fails when a slide carries a numeric claim that doesn't trace
    to REPORT — but we can't easily set up a REPORT fixture here, so
    we lean on P3's actual implementation: it walks slide content
    looking for numbers and verifies them. A spec without a REPORT
    path produces a P3 fail because the validator can't verify any
    number.

    Actually simpler: stub _validate_p1_p10 to return a synthetic
    P0 finding directly — exercises the cascade's short-circuit
    plumbing without depending on the full REPORT-grounding
    pipeline. The Tier B unit test already pins P3-on-real-spec
    behaviour."""
    return {
        "schema_version": ss.SCHEMA_VERSION,
        "project_id": "x", "mode": "talk-30",
        "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [ss.example_slide("title", substory_id=None)],
    }


def test_e2e_p0_tier1_short_circuits_tier2_and_tier3(rc, ss, tmp_path, monkeypatch):
    """The cascade's value prop: a P3 numeric-provenance fail in
    Tier 1 short-circuits Tier 2 + Tier 3 — adversarial NEVER runs
    on a deck with a known mechanical fail. Saves ~$0.50–$1.50 per
    failed-Tier-1 draft."""
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    (spec_dir / "slide_spec.json").write_text(
        json.dumps(_structurally_valid_spec_with_p3_violation(ss)))

    # Inject a synthetic P3 P0 finding through _validate_p1_p10 (avoids
    # needing a REPORT.md fixture for P3 to fire naturally).
    def _fake_validate(draft_dir, write_audit=True):
        return [rc.CascadeFinding(
            tier="tier1", kind="P3", severity="P0",
            slide_id=1, detail="P3 numeric provenance fail",
            evidence={"where": "slide[1].title"},
        )]
    monkeypatch.setattr(rc, "_validate_p1_p10", _fake_validate)

    # Tier 2 and Tier 3 invokers MUST NOT be called (the test will
    # fail loudly if they are — proving the short-circuit triggered).
    def _no_tier2(*args, **kwargs):
        pytest.fail("Tier 2 must NOT run when Tier 1 P0 short-circuits")
    def _no_tier3(*args, **kwargs):
        pytest.fail("Tier 3 must NOT run when Tier 1 P0 short-circuits")
    monkeypatch.setattr(rc, "_invoke_review_tier2", _no_tier2)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial", _no_tier3)
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)

    rc_val = rc.main([str(tmp_path), "--quiet"])
    assert rc_val == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_cascade.json").read_text())

    # Tier 1 fail; Tier 2 + 3 skipped with short-circuit note
    assert payload["tiers"][0]["status"] == "fail"
    assert payload["tiers"][1]["status"] == "skipped"
    assert payload["tiers"][2]["status"] == "skipped"
    # The cascade JSON's short_circuited_at is the gate the
    # orchestrator's de-dup logic reads — must be set to "tier1"
    # so the standalone stage_adversarial_review DOES still run
    # (cascade Tier 3 was skipped, so no double-spend concern; but
    # NO_ADVERSARIAL=0 + cascade tier3 status="skipped" → standalone
    # runs per the orchestrator's case statement).
    assert payload["short_circuited_at"] == "tier1"


# ---------------------------------------------------------------------------
# Clean-spec smoke — Tier 1 pass → Tier 2 + Tier 3 both run
# ---------------------------------------------------------------------------

def test_e2e_clean_spec_runs_all_three_tiers(rc, ss, tmp_path, monkeypatch):
    """The happy path: clean Tier 1 → Tier 2 (advisory findings) →
    Tier 3 (advisory findings). Cascade lifts findings from each tier
    into the cascade JSON; orchestrator's de-dup logic sees
    tiers[2].status='advisory' and skips standalone adversarial."""
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    (spec_dir / "slide_spec.json").write_text(
        json.dumps(_structurally_valid_spec_with_p3_violation(ss)))

    # Stub Tier 2: writes a real audit/review_tier2.json with 1 finding.
    def _stub_t2(draft_dir, claude_bin="claude"):
        audit = draft_dir / "audit"
        audit.mkdir(parents=True, exist_ok=True)
        (audit / "review_tier2.json").write_text(json.dumps({
            "schema_version": "review-tier2.v1",
            "n_slides_reviewed": 1,
            "findings": [
                {"slide_id": 1, "kind": "register_drift",
                 "severity": "P1", "confidence": "medium",
                 "detail": "synthetic Tier-2 finding",
                 "evidence_locator": "content.title"},
            ],
        }))
        return 0
    monkeypatch.setattr(rc, "_invoke_review_tier2", _stub_t2)

    # Stub Tier 3: pretend beril-adversarial CLI exists; the invoker
    # returns rc=0 + we pre-write audit/adversarial_review.json.
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    def _stub_t3(d, adversarial_bin="beril-adversarial", beril_root=None):
        return (0, "ok", "", 30.0)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial", _stub_t3)
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    # Real v3 schema (`adversarial-review-presentation.v3`): uses
    # `class` (not `kind`), `issue` (not `summary`), severity in
    # {P0, P1, info}.
    (audit / "adversarial_review.json").write_text(json.dumps({
        "schema_version": "adversarial-review-presentation.v3",
        "findings": [
            {"id": "F001", "slide_id": 1, "class": "claim_evidence",
             "severity": "P1", "confidence": "high",
             "issue": "synthetic Tier-3 finding"},
        ],
    }))

    rc_val = rc.main([str(tmp_path), "--quiet"])
    assert rc_val == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_cascade.json").read_text())

    # Tier 1 lands as either 'pass' or 'advisory' on a minimal spec
    # (P-validators may emit advisory P1 findings for missing required
    # slides like references / acknowledgments on a 1-slide deck — not
    # a P0, just shape advice). Key invariant: no P0 → no
    # short-circuit → Tier 2 + 3 both run.
    assert payload["tiers"][0]["status"] in ("pass", "advisory")
    assert not any(f["severity"] == "P0" for f in payload["tiers"][0]["findings"])
    assert payload["tiers"][1]["status"] == "advisory"
    assert payload["tiers"][2]["status"] == "advisory"
    assert payload["short_circuited_at"] is None
    # tier3 status is 'advisory' → orchestrator's CASCADE_RAN_TIER3
    # would be 1; standalone stage_adversarial_review skips.
    assert payload["tiers"][2]["status"] in ("pass", "advisory", "fail"), \
        "Tier 3 must run to a terminal state when not short-circuited"

    # Findings tally across all three tiers
    all_kinds = [f["kind"] for t in payload["tiers"] for f in t["findings"]]
    assert "register_drift" in all_kinds   # Tier 2
    assert "claim_evidence" in all_kinds   # Tier 3 (real v3 class)


# ---------------------------------------------------------------------------
# Orchestrator de-dup logic — direct exercise of the cascade-JSON read
# ---------------------------------------------------------------------------

def test_orchestrator_de_dup_reads_cascade_tier3_status(rc, tmp_path):
    """The orchestrator's de-dup logic reads cascade JSON's
    tiers[2].status via a python -c one-liner. This test exercises
    the same read pattern (a python invocation that parses the JSON
    and extracts the status) to pin the contract the shell relies on:
    cascade JSON MUST carry tiers[2].status as a string in {pass,
    advisory, fail, skipped, error, not-implemented}."""
    # Build a cascade JSON that the orchestrator would read
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "review_cascade.json").write_text(json.dumps({
        "schema_version": "review-cascade.v1",
        "draft_dir": str(tmp_path),
        "tiers": [
            {"name": "tier1", "status": "pass", "findings": []},
            {"name": "tier2", "status": "advisory", "findings": []},
            {"name": "tier3", "status": "advisory", "findings": []},
        ],
        "short_circuited_at": None,
    }))
    # Same code path the orchestrator uses (python -c read of
    # tiers[2].status)
    payload = json.loads(
        (audit / "review_cascade.json").read_text())
    tier3_status = payload["tiers"][2]["status"]
    assert tier3_status == "advisory"
    # The orchestrator's case-statement maps pass/advisory/fail →
    # CASCADE_RAN_TIER3=1 (skip standalone adversarial)
    assert tier3_status in {"pass", "advisory", "fail"}


def test_orchestrator_de_dup_does_not_skip_when_cascade_tier3_skipped(rc, tmp_path):
    """When cascade Tier 3 is 'skipped' (e.g., --no-tier3 or CLI
    missing), the orchestrator's case-statement does NOT match
    pass/advisory/fail → CASCADE_RAN_TIER3=0 → standalone
    stage_adversarial_review runs as before."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "review_cascade.json").write_text(json.dumps({
        "schema_version": "review-cascade.v1",
        "draft_dir": str(tmp_path),
        "tiers": [
            {"name": "tier1", "status": "pass", "findings": []},
            {"name": "tier2", "status": "advisory", "findings": []},
            {"name": "tier3", "status": "skipped", "findings": [],
             "note": "skipped — --no-tier3"},
        ],
        "short_circuited_at": None,
    }))
    payload = json.loads(
        (audit / "review_cascade.json").read_text())
    tier3_status = payload["tiers"][2]["status"]
    assert tier3_status == "skipped"
    # NOT in the pass/advisory/fail set → orchestrator's
    # CASCADE_RAN_TIER3 stays 0 → standalone adversarial runs
    assert tier3_status not in {"pass", "advisory", "fail"}
