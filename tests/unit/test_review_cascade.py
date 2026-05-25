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
# Tier-A scaffolding — per-tier dispatchers
# (Tier B replaced run_tier1 with the real aggregation; Tier 2/3 still stubs)
# ---------------------------------------------------------------------------

def test_tier1_missing_spec_returns_pass_with_empty_findings(rc, tmp_path):
    """When working/slide_spec.json is absent, Tier 1 has nothing to
    aggregate — validate_presentation skips, the four audit readers
    return [], and Tier 1 lands as 'pass' (no findings, no P0). This
    is also the cascade's no-op-on-missing-spec posture (paired with
    main()'s stub-report when slide_spec.json is missing)."""
    result = rc.run_tier1(tmp_path)
    assert result.name == "tier1"
    assert result.status == "pass"
    assert result.has_p0 is False
    assert result.findings == []


def test_tier2_dispatcher_lifts_skipped_from_stub_audit(rc, tmp_path, monkeypatch):
    """Tier C: cascade's run_tier2 invokes review_tier2.run_tier2 (which
    handles its own toolchain probe + stub-report fallback). If
    review_tier2 writes a stub (claude missing, spec missing — empty
    findings + a note), the cascade lifts it as 'skipped' so the
    cascade report reflects the degraded path without claiming a
    clean pass."""
    # Stub the cascade's review_tier2 invoker so we control what
    # audit/review_tier2.json contains.
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "review_tier2.json").write_text(json.dumps({
        "schema_version": "review-tier2.v1",
        "n_slides_reviewed": 0,
        "findings": [],
        "note": "Tier 2 toolchain incomplete (missing: claude)",
    }))
    monkeypatch.setattr(rc, "_invoke_review_tier2",
                        lambda d, claude_bin="claude": 0)
    result = rc.run_tier2(tmp_path)
    assert result.name == "tier2"
    assert result.status == "skipped"
    assert "toolchain incomplete" in result.note


def test_tier2_dispatcher_lifts_findings_from_audit_json(rc, tmp_path, monkeypatch):
    """Happy-path: review_tier2 writes a real findings list; cascade
    lifts each into a CascadeFinding with tier='tier2'."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "review_tier2.json").write_text(json.dumps({
        "schema_version": "review-tier2.v1",
        "n_slides_reviewed": 5,
        "findings": [
            {"slide_id": 7, "kind": "register_drift",
             "severity": "P1", "confidence": "high",
             "detail": "passive voice on STRONG",
             "evidence_locator": "content.subtitle"},
            {"slide_id": 12, "kind": "qa_softball",
             "severity": "P2", "confidence": "medium",
             "detail": "low-novelty question",
             "evidence_locator": "content.question"},
        ],
    }))
    monkeypatch.setattr(rc, "_invoke_review_tier2",
                        lambda d, claude_bin="claude": 0)
    result = rc.run_tier2(tmp_path)
    assert result.status == "advisory"
    assert len(result.findings) == 2
    assert {f.kind for f in result.findings} == {"register_drift", "qa_softball"}
    assert all(f.tier == "tier2" for f in result.findings)
    # DQ4: NO P0 from Tier 2
    assert not any(f.severity == "P0" for f in result.findings)
    assert result.has_p0 is False


def test_tier2_dispatcher_demotes_rogue_p0_to_p1(rc, tmp_path, monkeypatch):
    """DQ4 invariant pin: if the Tier-2 model emits a P0 (against the
    prompt's contract), the cascade dispatcher demotes it to P1. The
    cascade's short-circuit reads TierResult.has_p0; an unintended
    Tier-2 P0 must NOT trigger short-circuit."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "review_tier2.json").write_text(json.dumps({
        "schema_version": "review-tier2.v1",
        "n_slides_reviewed": 1,
        "findings": [
            {"slide_id": 1, "kind": "register_drift",
             "severity": "P0",         # ← rogue Tier-2 P0
             "confidence": "high",
             "detail": "model emitted P0 against prompt contract",
             "evidence_locator": "content.subtitle"},
        ],
    }))
    monkeypatch.setattr(rc, "_invoke_review_tier2",
                        lambda d, claude_bin="claude": 0)
    result = rc.run_tier2(tmp_path)
    assert result.findings[0].severity == "P1"   # demoted from P0
    assert result.has_p0 is False                 # short-circuit NOT triggered


def test_tier2_dispatcher_error_status_when_audit_missing(rc, tmp_path, monkeypatch):
    """If review_tier2 ran but failed to produce the audit file
    (subprocess crash, etc.), cascade lifts as 'error' — distinct from
    'skipped' (which means review_tier2 wrote a clean stub)."""
    monkeypatch.setattr(rc, "_invoke_review_tier2",
                        lambda d, claude_bin="claude": 0)
    # No audit file pre-written → cascade reads None
    result = rc.run_tier2(tmp_path)
    assert result.status == "error"
    assert "did not produce" in result.note


def test_derive_beril_root_walks_four_parents_up(rc, tmp_path):
    """_derive_beril_root: draft sits at <BERIL_ROOT>/projects/<id>/
    talks/draft_N/; walk 4 parents up + verify .claude/skills/ marker."""
    root = tmp_path / "beril_root"
    (root / "projects" / "x" / "talks" / "draft_1").mkdir(parents=True)
    (root / ".claude" / "skills").mkdir(parents=True)
    draft = root / "projects" / "x" / "talks" / "draft_1"
    assert rc._derive_beril_root(draft) == root


def test_derive_beril_root_returns_none_when_marker_absent(rc, tmp_path):
    """If .claude/skills/ is missing 4 parents up, return None — the
    cascade falls back to the env var (or beril-adversarial does its
    own thing without --beril-root)."""
    # Structure 4-parents-up is just tmp_path; no .claude/skills/ marker
    (tmp_path / "projects" / "x" / "talks" / "draft_1").mkdir(parents=True)
    draft = tmp_path / "projects" / "x" / "talks" / "draft_1"
    assert rc._derive_beril_root(draft) is None


def test_invoke_beril_adversarial_passes_beril_root_explicitly(rc, tmp_path, monkeypatch):
    """M4b Tier E hotpatch: subprocess invocation must include
    --beril-root so beril-adversarial doesn't walk from its own pipx
    venv location (which has no .claude/skills/)."""
    import subprocess

    root = tmp_path / "beril_root"
    (root / "projects" / "x" / "talks" / "draft_1").mkdir(parents=True)
    (root / ".claude" / "skills").mkdir(parents=True)
    draft = root / "projects" / "x" / "talks" / "draft_1"

    captured = []

    def _fake_run(cmd, **kwargs):
        captured.extend(cmd)
        from unittest.mock import MagicMock
        return MagicMock(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    # Make sure env BERIL_ROOT doesn't preempt the derivation
    monkeypatch.delenv("BERIL_ROOT", raising=False)
    rc._invoke_beril_adversarial(draft)

    assert "--beril-root" in captured, \
        "M4b Tier E hotpatch: must pass --beril-root explicitly"
    idx = captured.index("--beril-root")
    assert captured[idx + 1] == str(root)


def test_invoke_beril_adversarial_prefers_explicit_beril_root_arg(rc, tmp_path, monkeypatch):
    """When the caller passes beril_root explicitly, use that even if
    env or derivation would resolve a different path."""
    import subprocess
    explicit = tmp_path / "explicit_root"
    explicit.mkdir()
    draft = tmp_path / "projects" / "x" / "talks" / "draft_1"
    draft.mkdir(parents=True)
    captured = []
    def _fake_run(cmd, **kwargs):
        captured.extend(cmd)
        from unittest.mock import MagicMock
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    rc._invoke_beril_adversarial(draft, beril_root=explicit)
    idx = captured.index("--beril-root")
    assert captured[idx + 1] == str(explicit)


def test_invoke_beril_adversarial_uses_env_var_when_no_explicit_arg(rc, tmp_path, monkeypatch):
    """$BERIL_ROOT env var is the second-priority resolution
    (matches the orchestrator's pattern)."""
    import subprocess
    env_root = tmp_path / "env_root"
    env_root.mkdir()
    draft = tmp_path / "projects" / "x" / "talks" / "draft_1"
    draft.mkdir(parents=True)
    captured = []
    def _fake_run(cmd, **kwargs):
        captured.extend(cmd)
        from unittest.mock import MagicMock
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setenv("BERIL_ROOT", str(env_root))
    rc._invoke_beril_adversarial(draft)
    idx = captured.index("--beril-root")
    assert captured[idx + 1] == str(env_root)


def test_tier3_returns_skipped_when_adversarial_cli_missing(rc, tmp_path, monkeypatch):
    """Tier D: cascade's run_tier3 probes for beril-adversarial on
    PATH. If absent → status='skipped' + install-hint note. Never
    raises (advisory)."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": False)
    result = rc.run_tier3(tmp_path)
    assert result.name == "tier3"
    assert result.status == "skipped"
    assert "PATH" in result.note or "install" in result.note.lower()


def test_tier3_returns_error_when_adversarial_subprocess_fails(rc, tmp_path, monkeypatch):
    """beril-adversarial generic non-zero (non-contract) → status='error'.
    M6 Tier B.3 contract: rc=0/2 are consumer-safe; rc=3 (config),
    rc=4 (NOT consumer-safe; quarantine), and other rc values all
    map to error status. This test pins the "other" / rc=1 path."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (1, "", "model rate-limited", 1.0))
    result = rc.run_tier3(tmp_path)
    assert result.status == "error"
    assert "rate-limited" in result.note


def test_tier3_rc4_quarantines_json_and_returns_error(rc, tmp_path, monkeypatch):
    """M6 Tier B.3 (per adversarial v0.7.0.8 contract): rc=4 means the
    .json is NOT consumer-safe (schema-invalid or unparseable after
    failed auto-repair). Cascade must quarantine the file so any
    downstream file-existence consumer doesn't load broken findings.
    Parallel-fix to stage_adversarial_review's rc=4 quarantine in
    presentation_maker.sh."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    # Simulate beril-adversarial v0.7.0.8 returning rc=4 + having
    # written a (broken) JSON file to disk first.
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    bad_json_path = audit_dir / "adversarial_review.json"
    bad_json_path.write_text('{"schema_version":"v3","findings":[]}',
                              encoding="utf-8")  # parses but schema-invalid
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (4, "", "schema validation failed", 1.0))
    result = rc.run_tier3(tmp_path)
    assert result.status == "error"
    # JSON quarantined (renamed) — original path absent, .quarantined-rc4 present
    assert not bad_json_path.is_file(), (
        f"rc=4 must quarantine the .json (rename); original path "
        f"still exists: {bad_json_path}")
    quarantine = bad_json_path.with_suffix(".json.quarantined-rc4")
    assert quarantine.is_file(), (
        f"rc=4 quarantine target missing: {quarantine}")
    # Note names rc=4 + quarantine + .md-intact-by-implication
    assert "rc=4" in result.note
    assert "quarantined" in result.note.lower()
    assert "schema-invalid" in result.note.lower() or "consumer-safe" in result.note.lower()


def test_tier3_rc4_handles_missing_json_gracefully(rc, tmp_path, monkeypatch):
    """rc=4 path doesn't crash if the .json was never written
    (e.g., adversarial failed before its Write step). Still returns
    error status with a note explaining there was nothing to quarantine."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (4, "", "unparseable after auto-repair", 1.0))
    # No audit/ dir; no JSON to quarantine
    result = rc.run_tier3(tmp_path)
    assert result.status == "error"
    assert "rc=4" in result.note
    assert "no .json to quarantine" in result.note or "quarantine" in result.note.lower()


def test_tier3_rc2_treats_as_consumer_safe(rc, tmp_path, monkeypatch):
    """M6 Tier B.3: rc=2 (auto-repaired but still consumer-safe per
    v0.7.0.7 contract) flows through the success path. The TierResult
    note records the auto-repair audit signal so downstream consumers
    can distinguish rc=0 (clean first try) from rc=2 (recovered)."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (2, "", "auto-repaired", 1.0))
    # Create a valid v3-shape JSON so the success path completes
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    valid_json_path = audit_dir / "adversarial_review.json"
    valid_json_path.write_text(
        '{"schema_version":"adversarial-review-presentation.v3",'
        '"summary":{"total_findings":2},'
        '"findings":[{"id":"F001","class":"throughline","severity":"P1",'
        '"issue":"x"},{"id":"F002","class":"claim_evidence",'
        '"severity":"P0","issue":"y"}]}',
        encoding="utf-8",
    )
    result = rc.run_tier3(tmp_path)
    # Success path, not error
    assert result.status in ("advisory", "pass"), (
        f"rc=2 should be consumer-safe; got status={result.status} "
        f"note={result.note}")
    assert len(result.findings) == 2
    # Audit signal preserved
    assert "auto-repaired" in result.note.lower() or "rc=2" in result.note


def test_tier3_returns_error_when_no_audit_json_post_invoke(rc, tmp_path, monkeypatch):
    """beril-adversarial rc=0 but no audit/adversarial_review.json
    written → status='error' (contract violation; the adversarial CLI
    must always produce the JSON on rc=0)."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (0, "ok", "", 2.0))
    # No audit/adversarial_review.json pre-written
    result = rc.run_tier3(tmp_path)
    assert result.status == "error"
    assert "did not produce" in result.note


def test_tier3_lifts_v3_findings_into_cascade_findings(rc, tmp_path, monkeypatch):
    """Happy path: adversarial v3 JSON present → cascade lifts each
    finding as CascadeFinding(tier='tier3').

    M4b Tier E live-data fix (2026-05-24): the real v3 schema
    (`adversarial-review-presentation.v3`) uses `class` (not `kind`),
    `issue` (not `summary`), and central_objection is a regular
    finding with `class="central_objection"` (NOT a top-level
    field). Severity is preserved from the v3 finding (P0/P1/info
    → cascade P0/P1/P2)."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (0, "ok", "", 25.0))

    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "adversarial_review.json").write_text(json.dumps({
        "schema_version": "adversarial-review-presentation.v3",
        "project_id": "x", "draft_number": 1,
        "reviewer_model": "claude-sonnet-4-6",
        "prompt_version": "adversarial_presentation.v3",
        "tier": "STRONG",
        "summary": "test",
        "findings": [
            {"id": "F001", "class": "throughline",
             "severity": "P0", "confidence": "high",
             "slide_id": 1, "title_quote": "...",
             "issue": "throughline contradicts REPORT",
             "recommendation": "fix throughline"},
            {"id": "F002", "class": "register_drift",
             "severity": "P1", "confidence": "medium",
             "slide_id": 13,
             "issue": "passive voice on STRONG claim",
             "recommendation": "rewrite active"},
            {"id": "F003", "class": "central_objection",
             "severity": "info", "confidence": "high",
             "slide_id": None,
             "issue": "deck weakness: gap between ecotype claim and clinical action",
             "recommendation": "add slide on AIEC strain-resolution gap"},
        ],
    }))
    result = rc.run_tier3(tmp_path)
    assert result.status == "advisory"
    assert len(result.findings) == 3
    assert all(f.tier == "tier3" for f in result.findings)
    # Severities preserved: P0 → P0, P1 → P1, info → P2
    sevs = {f.kind: f.severity for f in result.findings}
    assert sevs["throughline"] == "P0"
    assert sevs["register_drift"] == "P1"
    assert sevs["central_objection"] == "P2"   # info → P2
    # cascade severity P0 on Tier 3 does NOT trigger short-circuit
    # (Tier 3 is the bottom tier; nothing to short-circuit). The
    # cascade orchestrator reads has_p0 ONLY on Tier 1.
    assert result.has_p0 is True
    # Details lifted from v3's `issue` field (not `summary`)
    details = {f.kind: f.detail for f in result.findings}
    assert "throughline contradicts" in details["throughline"]
    assert "passive voice" in details["register_drift"]
    # central_objection has its own class; evidence captures the
    # v3 input severity so consumers can distinguish from a v3 P0
    # that happened to be tagged differently.
    co = next(f for f in result.findings if f.kind == "central_objection")
    assert co.evidence["v3_severity"] == "info"


def test_tier3_skipped_finding_status_pass_when_no_findings(rc, tmp_path, monkeypatch):
    """v3 JSON with empty findings → status='pass' (the deck cleared
    Tier 3; no advisory findings to surface)."""
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": True)
    monkeypatch.setattr(rc, "_invoke_beril_adversarial",
                        lambda d, adversarial_bin="beril-adversarial",
                               beril_root=None:
                            (0, "ok", "", 25.0))
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "adversarial_review.json").write_text(json.dumps({
        "schema_version": "presentation-adversarial.v3",
        "findings": [],
    }))
    result = rc.run_tier3(tmp_path)
    assert result.status == "pass"
    assert result.findings == []


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


def test_run_cascade_end_to_end_all_tiers_wired(rc, tmp_path, monkeypatch):
    """Cascade end-to-end on an empty draft (no slide_spec.json):
    Tier 1 runs real aggregation (lands 'pass'); Tier 2 invokes
    review_tier2 (stubbed in tests); Tier 3 invokes beril-adversarial
    (stubbed-absent in tests).

    All three tiers are wired (no scaffolding stubs remain).
    short_circuited_at stays null because Tier 1 doesn't emit P0
    on an empty draft."""
    # Defensively stub Tier 2 (claude may be on PATH) — tests must
    # never hit live LLM.
    def _stub_invoke_t2(draft_dir, claude_bin="claude"):
        audit = draft_dir / "audit"
        audit.mkdir(parents=True, exist_ok=True)
        (audit / "review_tier2.json").write_text(json.dumps({
            "schema_version": "review-tier2.v1",
            "n_slides_reviewed": 0, "findings": [],
            "note": "stubbed by test",
        }))
        return 0
    monkeypatch.setattr(rc, "_invoke_review_tier2", _stub_invoke_t2)
    # Defensively stub Tier 3 (beril-adversarial may be on PATH).
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": False)

    report = rc.run_cascade(tmp_path)
    assert report.tiers[0].status == "pass"
    assert report.tiers[1].status != "not-implemented", \
        "Tier C wired run_tier2"
    assert report.tiers[2].status != "not-implemented", \
        "Tier D wired run_tier3"
    assert report.short_circuited_at is None


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

def test_cli_returns_0_on_empty_spec(rc, tmp_path, monkeypatch):
    """CLI on a draft with a minimal (empty-slides) slide_spec.json →
    Tier 1 runs real aggregation but finds nothing (validators skipped
    structurally-invalid spec); Tier 2 lifts a 'skipped' stub (mocked
    via _invoke_review_tier2 — tests must NEVER hit live LLM); Tier 3
    lifts 'skipped' (mocked adversarial-CLI-missing — tests must NEVER
    hit live LLM). rc=0 always."""
    def _stub_invoke_t2(draft_dir, claude_bin="claude"):
        audit = draft_dir / "audit"
        audit.mkdir(parents=True, exist_ok=True)
        (audit / "review_tier2.json").write_text(json.dumps({
            "schema_version": "review-tier2.v1",
            "n_slides_reviewed": 0, "findings": [],
            "note": "stubbed by test_cli_returns_0_on_empty_spec",
        }))
        return 0
    monkeypatch.setattr(rc, "_invoke_review_tier2", _stub_invoke_t2)
    monkeypatch.setattr(rc, "_adversarial_cli_available",
                        lambda bin="beril-adversarial": False)

    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    (spec_dir / "slide_spec.json").write_text(json.dumps({"slides": []}))
    rc_val = rc.main([str(tmp_path), "--quiet"])
    assert rc_val == 0
    j = tmp_path / "audit" / "review_cascade.json"
    payload = json.loads(j.read_text())
    assert payload["tiers"][0]["status"] == "pass"
    assert payload["tiers"][1]["status"] == "skipped"   # T2 stubbed
    assert payload["tiers"][2]["status"] == "skipped"   # T3 stubbed
    assert payload["short_circuited_at"] is None


def test_cli_no_tier2_no_tier3_propagate(rc, tmp_path):
    """--no-tier2 + --no-tier3 → Tier 1 runs (real aggregation), 2+3 skipped."""
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


# ---------------------------------------------------------------------------
# M4b Tier B — Tier 1 aggregation specifics
# ---------------------------------------------------------------------------

def _write_audit_json(draft_dir: Path, filename: str, payload: dict) -> None:
    """Helper: drop a JSON file into <draft_dir>/audit/."""
    audit = draft_dir / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / filename).write_text(json.dumps(payload))


def test_tier1_p0_validators_pinned_to_p3_p4_p5(rc):
    """DQ4 + D-059: P3, P4, P5 short-circuit on the v0.4 cascade.

    History (per D-058 + D-059):
    - M4b Tier B initially set `{P3, P4, P5}` (v0.3-era pin).
    - M4b Tier E live probe found v0.3-shaped P3 broke the cascade
      on every v0.4 deck (282 false-positives from
      `speaker_notes_provenance` missing); D-058 demoted to `{P4, P5}`.
    - M5a Tier C rewrote `validate_p3_numeric_provenance` as a
      wrapper around `check_quantitative_grounding`. P3 is now
      v0.4-native; re-added to `_P0_VALIDATORS` (D-058 obsolete;
      D-059 retirement closes M5a scope).

    Pin the set so a future refactor (or accidental P3 demote) breaks
    the test, not the cascade contract."""
    assert rc._P0_VALIDATORS == frozenset({"P3", "P4", "P5"})


def test_tier1_reads_quantitative_grounding_artifact(rc, tmp_path):
    """audit/quantitative_grounding.json findings flow into Tier 1
    findings; high severity → P1, others → P2; all advisory (no P0)."""
    _write_audit_json(tmp_path, "quantitative_grounding.json", {
        "schema_version": "quantitative-grounding.v1",
        "findings": [
            {"slide_id": 7, "slide_position": 6, "slide_layout": "big_number",
             "severity": "high", "note": "94.7% not in REPORT",
             "number": {"text": "94.7%", "raw": "94.7%"}},
            {"slide_id": 13, "slide_position": 12, "slide_layout": "claim_evidence",
             "severity": "low", "note": "0.31 partial match",
             "number": {"text": "0.31", "raw": "0.31"}},
        ],
    })
    findings = rc._read_quantitative_grounding(tmp_path)
    assert len(findings) == 2
    high = next(f for f in findings if f.slide_id == 7)
    low = next(f for f in findings if f.slide_id == 13)
    assert high.severity == "P1"
    assert low.severity == "P2"
    assert all(f.tier == "tier1" for f in findings)
    assert all(f.kind == "quantitative_grounding" for f in findings)
    # No P0 from this checker
    assert not any(f.severity == "P0" for f in findings)


def test_tier1_reads_no_artifact_refs_artifact(rc, tmp_path):
    """audit/no_artifact_refs.json hits flow into Tier 1 as P2 (all
    advisory; process-detail-bleed is a hint, not a contract violation)."""
    _write_audit_json(tmp_path, "no_artifact_refs.json", {
        "schema_version": "no-artifact-refs.v1",
        "hits": [
            {"slide_id": 9, "slide_position": 8, "slide_layout": "claim_evidence",
             "location": "bullets[0]", "pattern": "notebook_ref",
             "matched_text": "NB04c §13",
             "explanation": "notebook section ref leaked to slide face",
             "suggestion": "move to speaker notes", "context": "..."},
        ],
    })
    findings = rc._read_no_artifact_refs(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "P2"
    assert findings[0].kind == "no_artifact_refs"
    assert findings[0].slide_id == 9


def test_tier1_reads_deck_reconciliation_artifact(rc, tmp_path):
    """audit/deck_reconciliation.json findings flow in as P1 (cross-
    section conflicts are real but not load-bearing-P0). slide_ids list
    preserved in evidence."""
    _write_audit_json(tmp_path, "deck_reconciliation.json", {
        "schema_version": "deck-reconciliation.v1",
        "findings": [
            {"kind": "duplicate_headline", "severity": "warning",
             "slide_ids": [8, 12],
             "detail": "OR=8.11 appears on two big_number slides"},
        ],
    })
    findings = rc._read_deck_reconciliation(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "P1"
    assert findings[0].kind == "duplicate_headline"
    assert findings[0].slide_id == 8        # first slide_id in the list
    assert findings[0].evidence["slide_ids"] == [8, 12]


def test_tier1_reads_visual_qa_artifact_per_dq2(rc, tmp_path):
    """DQ2 (Adam 2026-05-24 — ship as (b)): cascade reads
    audit/visual_qa.json if present, NEVER invokes visual_qa.py.
    confidence='high' → P1; 'medium'/'low' → P2; no P0 from visual-QA."""
    _write_audit_json(tmp_path, "visual_qa.json", {
        "schema_version": "visual-qa.v1",
        "n_slides_reviewed": 3,
        "findings": [
            {"slide_id": 6, "kind": "container_breach",
             "severity": "warning", "confidence": "high",
             "detail": "diagram label overflows", "evidence_locator": "x"},
            {"slide_id": 10, "kind": "illegible_scale",
             "severity": "warning", "confidence": "medium",
             "detail": "step caption small", "evidence_locator": "y"},
        ],
    })
    findings = rc._read_visual_qa(tmp_path)
    assert len(findings) == 2
    high_finding = next(f for f in findings if f.slide_id == 6)
    med_finding = next(f for f in findings if f.slide_id == 10)
    assert high_finding.severity == "P1"
    assert med_finding.severity == "P2"
    assert all(f.kind.startswith("visual_qa:") for f in findings)
    assert not any(f.severity == "P0" for f in findings)


def test_tier1_visual_qa_stub_report_ignored_per_dq2(rc, tmp_path):
    """The M4a stub-report posture writes visual_qa.json with empty
    findings + a note (toolchain missing, spec missing, etc.). Tier 1
    must ignore the stub and emit zero findings — not treat the note
    as a finding."""
    _write_audit_json(tmp_path, "visual_qa.json", {
        "schema_version": "visual-qa.v1",
        "n_slides_reviewed": 0,
        "findings": [],
        "note": "visual-QA toolchain incomplete (missing: soffice)",
    })
    assert rc._read_visual_qa(tmp_path) == []


def test_tier1_missing_audit_artifacts_returns_empty(rc, tmp_path):
    """Each reader is no-op-safe when its audit JSON is absent —
    the cascade should not require operator to have run the optional
    checks (visual-QA in particular, per DQ2)."""
    assert rc._read_quantitative_grounding(tmp_path) == []
    assert rc._read_no_artifact_refs(tmp_path) == []
    assert rc._read_deck_reconciliation(tmp_path) == []
    assert rc._read_visual_qa(tmp_path) == []


def test_tier1_p0_validator_fail_triggers_status_fail(rc, tmp_path, monkeypatch):
    """The first time the cascade sees a P3/P4/P5 fail, Tier 1's
    status becomes 'fail' and has_p0 is True. This is the
    short-circuit trigger run_cascade reads."""
    # Mock _validate_p1_p10 directly to inject a P3 finding (avoids
    # building a full slide_spec that triggers P3 validate_p3_numeric).
    def _fake_validate(draft_dir, write_audit=True):
        return [rc.CascadeFinding(
            tier="tier1", kind="P3", severity="P0",
            slide_id=5, detail="numeric provenance fail",
            evidence={"where": "slide[5].bullets[0]"},
        )]
    monkeypatch.setattr(rc, "_validate_p1_p10", _fake_validate)

    result = rc.run_tier1(tmp_path)
    assert result.status == "fail"
    assert result.has_p0 is True
    assert len(result.findings) == 1
    assert result.findings[0].kind == "P3"


def test_tier1_only_p1_p2_findings_yields_status_advisory(rc, tmp_path, monkeypatch):
    """Tier 1 with findings but no P0 → status 'advisory' (cascade
    continues to Tier 2 + 3)."""
    monkeypatch.setattr(rc, "_validate_p1_p10",
                        lambda d, write_audit=True: [rc.CascadeFinding(
                            tier="tier1", kind="P10", severity="P1",
                            slide_id=3, detail="density warn",
                        )])
    result = rc.run_tier1(tmp_path)
    assert result.status == "advisory"
    assert result.has_p0 is False


def _structurally_valid_minimal_spec() -> dict:
    """Build a structurally-valid (per slide_spec.validate_slide_spec)
    minimal spec for Tier 1 tests that need validate_presentation to
    actually run. Uses one title slide with substory_id=None so the
    substory-cross-reference check doesn't fire."""
    import importlib.util as _u
    import sys
    REPO_ROOT = Path(__file__).resolve().parents[2]
    ss_path = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "tools" / "slide_spec.py")
    spec = _u.spec_from_file_location("_ss_for_test", ss_path)
    mod = _u.module_from_spec(spec)
    sys.modules["_ss_for_test"] = mod
    spec.loader.exec_module(mod)
    return {
        "schema_version": mod.SCHEMA_VERSION,
        "project_id": "x", "mode": "talk-30",
        "audience": "peer", "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [mod.example_slide("title", substory_id=None)],
    }


def test_tier1_writes_presentation_validation_audit_artifact(rc, tmp_path):
    """When validate_presentation runs, Tier 1 persists the report at
    audit/presentation_validation.json (forensic trail; lets a future
    --no-review-cascade run still have the artifact)."""
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    spec = _structurally_valid_minimal_spec()
    (spec_dir / "slide_spec.json").write_text(json.dumps(spec))
    rc.run_tier1(tmp_path)
    audit = tmp_path / "audit" / "presentation_validation.json"
    assert audit.is_file(), \
        "Tier 1 must write audit/presentation_validation.json as side-effect"
    payload = json.loads(audit.read_text())
    # Sanity: validate_presentation report schema (has 'validators' list)
    assert "validators" in payload


def test_tier1_skips_validate_on_structurally_invalid_spec(rc, tmp_path):
    """A structurally-invalid spec (e.g., missing required fields) would
    crash validate_presentation. Tier 1's pre-flight via
    slide_spec.validate_slide_spec catches that; the cascade emits zero
    P1-P10 findings (the assembler is the authoritative gate for
    structural validity) and the audit artifact is NOT written.
    """
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    # Empty-slides spec is structurally invalid (missing schema_version,
    # mode, etc.)
    (spec_dir / "slide_spec.json").write_text(json.dumps({"slides": []}))
    result = rc.run_tier1(tmp_path)
    # No crash; no P1-P10 findings from the validator (other audit
    # readers are independent — they emit only if their JSONs exist)
    assert result.status == "pass"
    # Audit artifact NOT written because validate didn't run
    assert not (tmp_path / "audit" / "presentation_validation.json").is_file()


def test_tier1_aggregates_all_five_sources_in_one_pass(rc, tmp_path):
    """End-to-end Tier 1: spec + all four audit artifacts present.
    Findings list aggregates across all sources (validator + 4 audits).
    No P0 since none of the artifacts inject one."""
    spec_dir = tmp_path / "working"
    spec_dir.mkdir()
    (spec_dir / "slide_spec.json").write_text(json.dumps({"slides": []}))
    _write_audit_json(tmp_path, "quantitative_grounding.json", {
        "findings": [{"slide_id": 1, "severity": "high",
                      "note": "n", "number": {"text": "X"}}],
    })
    _write_audit_json(tmp_path, "no_artifact_refs.json", {
        "hits": [{"slide_id": 2, "pattern": "p",
                  "matched_text": "M", "explanation": "e"}],
    })
    _write_audit_json(tmp_path, "deck_reconciliation.json", {
        "findings": [{"kind": "duplicate_figure", "severity": "warning",
                      "slide_ids": [3, 4], "detail": "d"}],
    })
    _write_audit_json(tmp_path, "visual_qa.json", {
        "n_slides_reviewed": 5,
        "findings": [{"slide_id": 5, "kind": "container_breach",
                      "severity": "warning", "confidence": "high",
                      "detail": "d", "evidence_locator": "x"}],
    })
    result = rc.run_tier1(tmp_path)
    # 1 quant-grounding + 1 artifact-ref + 1 reconciliation + 1 visual-qa
    # = 4 findings (validate_presentation on empty slides emits none)
    kinds = [f.kind for f in result.findings]
    assert "quantitative_grounding" in kinds
    assert "no_artifact_refs" in kinds
    assert "duplicate_figure" in kinds
    assert any(k.startswith("visual_qa:") for k in kinds)
    # All P1/P2; no P0 → status advisory, cascade continues
    assert result.status == "advisory"
    assert result.has_p0 is False
