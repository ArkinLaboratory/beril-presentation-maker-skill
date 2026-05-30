"""Unit tests for tools/check_cross_tenant_grounding.py (v0.7
Tier E.2 / D-089).

Per D-089: the cross_tenant_integration slide's title +
speaker_notes must be grounded in the structured signal from
extract_cross_tenant.py. This validator emits soft-warnings on:

- database_omission: signal entry not named in slide text
- database_hallucination: slide names a known DB not in signal
- cohort_omission: signal cohort not named in slide text
- cohort_hallucination: slide names a known cohort not in signal
- notebook_count_mismatch: slide claims N notebooks; signal has M

Test coverage:
- Happy path: slide enumerates all signal entries → no findings
- Per-finding-kind: each kind fires when its precondition is met
- Match precision: ambiguous short names (ec/go) require
  discriminator keywords to count as a slide-side mention
- Defensive: missing slide_spec / signal / slide → graceful
- CLI: default output paths + custom paths
- Cascade integration: review_cascade._read_cross_tenant_grounding
  lifts findings with cross_tenant_grounding:<kind> at P1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                / "tools" / "check_cross_tenant_grounding.py")


@pytest.fixture(scope="module")
def ctg():
    """Load check_cross_tenant_grounding as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_cross_tenant_grounding", VALIDATOR_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_cross_tenant_grounding"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_slide_spec(tmp_path: Path, *, slide_id: int = 1,
                      title: str = "All data sourced from K-BERDL.",
                      speaker_notes: str = "",
                      kberdl_db_list: list[str] | None = None) -> Path:
    """Write a minimal slide_spec.json with one cross_tenant_integration
    slide. Returns the spec path."""
    content = {"title": title}
    if kberdl_db_list:
        content["kberdl_db_list"] = kberdl_db_list
    slide = {
        "id": slide_id,
        "layout": "cross_tenant_integration",
        "content": content,
    }
    if speaker_notes:
        slide["speaker_notes"] = speaker_notes
    spec = {
        "schema_version": "slide-spec.v1",
        "project_id": "test",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [slide],
    }
    out = tmp_path / "slide_spec.json"
    out.write_text(json.dumps(spec), encoding="utf-8")
    return out


def _make_signal(tmp_path: Path, *,
                  kberdl_db_list: list[str] | None = None,
                  reference_databases: list[str] | None = None,
                  external_cohorts: list[str] | None = None,
                  notebook_count: int = 0) -> Path:
    """Write a cross_tenant_signal.json with the given fields."""
    signal = {
        "project_id": "test",
        "tenant_list": [],
        "kberdl_db_list": kberdl_db_list or [],
        "sibling_project_refs": [],
        "kbase_urls": [],
        "no_signal_fallback": False,
        "reference_databases": reference_databases or [],
        "external_cohorts": external_cohorts or [],
        "notebook_count": notebook_count,
    }
    out = tmp_path / "cross_tenant_signal.json"
    out.write_text(json.dumps(signal), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_slide_enumerates_all_signal_entries(ctg, tmp_path):
    """Slide title + speaker_notes name every K-BERDL DB + reference
    DB + cohort in the signal, and the notebook count matches.
    Result: no findings.

    Note: we avoid using `metabolomics` in the speaker_notes prose
    because it's a canonical K-BERDL DB name and would flag as
    hallucination if not also in the signal. Realistic decks DO
    use "metabolomics" both as a DB name + as a data-type word;
    that ambiguity is the v0.8+ disambiguation surface."""
    spec_path = _make_slide_spec(
        tmp_path,
        title=("This work integrates fitnessbrowser + paperblast "
               "across 32 notebooks."),
        speaker_notes=(
            "Primary K-BERDL DBs: fitnessbrowser, paperblast. "
            "External reference DBs: MIBiG for BGC catalog, MetaCyc "
            "for pathway ontology. External cohort: HMP2 sample set."
        ),
    )
    signal_path = _make_signal(
        tmp_path,
        kberdl_db_list=["fitnessbrowser", "paperblast"],
        reference_databases=["MIBiG", "MetaCyc"],
        external_cohorts=["HMP2"],
        notebook_count=32,
    )
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    assert report.findings == [], (
        "happy path expects no findings; got: "
        + "; ".join(f.kind for f in report.findings))
    assert report.cross_tenant_slide_present is True


# ---------------------------------------------------------------------------
# Database omission
# ---------------------------------------------------------------------------

def test_database_omission_kberdl_db_not_named(ctg, tmp_path):
    """Signal has K-BERDL DB 'fitnessbrowser' but slide doesn't name
    it → database_omission finding."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="All data from K-BERDL.",
        speaker_notes="We pulled from various sources.",
    )
    signal_path = _make_signal(
        tmp_path, kberdl_db_list=["fitnessbrowser"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "database_omission"]
    assert len(omissions) == 1
    assert "fitnessbrowser" in omissions[0].message
    assert omissions[0].severity == "soft-warning"


def test_database_omission_reference_db_not_named(ctg, tmp_path):
    """Signal has reference DB 'MIBiG' but slide doesn't name it
    → database_omission finding (separate path from kberdl)."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Data sources.",
        speaker_notes="Our annotations leverage several catalogs.",
    )
    signal_path = _make_signal(
        tmp_path, reference_databases=["MIBiG"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "database_omission"
                 and f.evidence.get("kind") == "reference_db"]
    assert len(omissions) == 1
    assert "MIBiG" in omissions[0].message


def test_database_omission_silent_when_named(ctg, tmp_path):
    """When the DB IS named in slide notes, no omission finding."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes="Primary DB: fitnessbrowser via berdl_query.",
    )
    signal_path = _make_signal(
        tmp_path, kberdl_db_list=["fitnessbrowser"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "database_omission"]
    assert omissions == []


# ---------------------------------------------------------------------------
# Cohort omission
# ---------------------------------------------------------------------------

def test_cohort_omission_when_signal_cohort_not_named(ctg, tmp_path):
    """Adam's load-bearing v0.6 failure mode: signal has HMP2 but
    slide doesn't name it."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Data sources.",
        speaker_notes="All data is from K-BERDL.",
    )
    signal_path = _make_signal(
        tmp_path, external_cohorts=["HMP2"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "cohort_omission"]
    assert len(omissions) == 1
    assert "HMP2" in omissions[0].message


def test_cohort_omission_silent_when_named(ctg, tmp_path):
    spec_path = _make_slide_spec(
        tmp_path,
        title="Data sources.",
        speaker_notes="External validation against HMP2 metabolomics.",
    )
    signal_path = _make_signal(
        tmp_path, external_cohorts=["HMP2"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "cohort_omission"]
    assert omissions == []


# ---------------------------------------------------------------------------
# Database hallucination
# ---------------------------------------------------------------------------

def test_database_hallucination_kberdl_named_but_not_in_signal(ctg, tmp_path):
    """Slide names 'fitnessbrowser' but signal doesn't list it →
    database_hallucination."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes="Primary DB: fitnessbrowser.",
    )
    signal_path = _make_signal(
        tmp_path, kberdl_db_list=["paperblast"])  # different DB
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    halls = [f for f in report.findings
             if f.kind == "database_hallucination"]
    # Should flag fitnessbrowser as hallucinated
    assert any("fitnessbrowser" in f.message for f in halls)


def test_database_hallucination_reference_named_but_not_in_signal(ctg, tmp_path):
    """Slide names 'MIBiG' but signal doesn't list it."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes="Annotations via MIBiG catalog.",
    )
    signal_path = _make_signal(
        tmp_path, reference_databases=["MetaCyc"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    halls = [f for f in report.findings
             if f.kind == "database_hallucination"
             and "MIBiG" in f.message]
    assert len(halls) == 1


def test_database_hallucination_silent_for_unknown_words(ctg, tmp_path):
    """Random words in slide text DON'T hallucinate — the validator
    only flags canonical-list-known names not in signal."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Random text.",
        speaker_notes="We ate sandwiches and looked at things.",
    )
    signal_path = _make_signal(tmp_path)
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    halls = [f for f in report.findings
             if "hallucination" in f.kind]
    assert halls == [], (
        "non-canonical words should never flag as hallucination")


# ---------------------------------------------------------------------------
# Cohort hallucination
# ---------------------------------------------------------------------------

def test_cohort_hallucination(ctg, tmp_path):
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes="Validated against HMP2 and FRANZOSA_2019.",
    )
    signal_path = _make_signal(
        tmp_path, external_cohorts=["HMP2"])  # FRANZOSA_2019 not in signal
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    halls = [f for f in report.findings
             if f.kind == "cohort_hallucination"]
    assert any("FRANZOSA_2019" in f.message for f in halls)


# ---------------------------------------------------------------------------
# Ambiguous-short-name handling (ec / go)
# ---------------------------------------------------------------------------

def test_ec_go_require_discriminator_to_count_as_mention(ctg, tmp_path):
    """The K-BERDL DBs `ec` and `go` are 2-letter abbreviations that
    false-match English words. The validator requires them to appear
    with a discriminator (EC numbers, GO annotations) to count as
    a slide-side mention. A casual 'we go forward' should NOT
    suppress the omission finding."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes="We go forward with this approach.",
    )
    signal_path = _make_signal(
        tmp_path, kberdl_db_list=["go"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "database_omission"]
    # 'go forward' shouldn't count → omission still fires
    assert len(omissions) == 1
    assert "'go'" in omissions[0].message


def test_ec_with_discriminator_counts_as_mention(ctg, tmp_path):
    """'EC numbers' / 'EC database' / 'EC annotations' counts."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="EC numbers used for pathway scoring.",
    )
    signal_path = _make_signal(
        tmp_path, kberdl_db_list=["ec"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    omissions = [f for f in report.findings
                 if f.kind == "database_omission"
                 and f.evidence.get("db") == "ec"]
    assert omissions == [], (
        "'EC numbers' should count as a slide-side mention of the "
        "ec K-BERDL DB")


# ---------------------------------------------------------------------------
# Notebook-count mismatch
# ---------------------------------------------------------------------------

def test_notebook_count_mismatch_off_by_one(ctg, tmp_path):
    """The v0.6 slide-27 failure mode: slide claims 31 notebooks,
    signal counts 32."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes=(
            "This project drew from 8 K-BERDL DBs across 31 notebooks."
        ),
    )
    signal_path = _make_signal(tmp_path, notebook_count=32)
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    mismatches = [f for f in report.findings
                  if f.kind == "notebook_count_mismatch"]
    assert len(mismatches) == 1
    assert "31" in mismatches[0].message
    assert "32" in mismatches[0].message


def test_notebook_count_match_silent(ctg, tmp_path):
    spec_path = _make_slide_spec(
        tmp_path,
        title="Test.",
        speaker_notes="32 notebooks of analysis.",
    )
    signal_path = _make_signal(tmp_path, notebook_count=32)
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    mismatches = [f for f in report.findings
                  if f.kind == "notebook_count_mismatch"]
    assert mismatches == []


def test_notebook_count_only_fires_when_slide_makes_a_claim(ctg, tmp_path):
    """If the slide doesn't mention notebooks at all, no mismatch
    (we can't mismatch an unstated claim)."""
    spec_path = _make_slide_spec(
        tmp_path,
        title="Data sources.",
        speaker_notes="We worked with K-BERDL platform.",
    )
    signal_path = _make_signal(tmp_path, notebook_count=32)
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    mismatches = [f for f in report.findings
                  if f.kind == "notebook_count_mismatch"]
    assert mismatches == []


# ---------------------------------------------------------------------------
# Defensive cases
# ---------------------------------------------------------------------------

def test_missing_slide_spec_returns_empty(ctg, tmp_path):
    """Missing slide_spec → no slides → empty findings, slide
    presence False."""
    signal_path = _make_signal(tmp_path)
    report = ctg.check_cross_tenant_grounding(
        tmp_path / "nonexistent.json", signal_path)
    assert report.cross_tenant_slide_present is False
    assert report.findings == []


def test_missing_signal_returns_empty_findings(ctg, tmp_path):
    """Missing signal → signal dict is empty → no omissions
    fire (no signal-listed entries to check); but the slide is
    still present."""
    spec_path = _make_slide_spec(tmp_path)
    report = ctg.check_cross_tenant_grounding(
        spec_path, tmp_path / "nonexistent.json")
    assert report.cross_tenant_slide_present is True
    # No signal → no omissions (nothing to omit). Hallucinations
    # may still fire if slide names canonical DBs not in (empty)
    # signal — but our minimal slide says "All data sourced from
    # K-BERDL." which doesn't name any canonical DB.
    omissions = [f for f in report.findings
                 if "omission" in f.kind]
    assert omissions == []


def test_no_cross_tenant_slide_in_spec(ctg, tmp_path):
    """spec has slides but no cross_tenant_integration slide."""
    spec = {
        "schema_version": "slide-spec.v1",
        "project_id": "test",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [{"id": 1, "layout": "title",
                     "content": {"title": "T", "presenter": "X",
                                  "date": "2026"}}],
    }
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    signal_path = _make_signal(tmp_path, kberdl_db_list=["fitnessbrowser"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    assert report.cross_tenant_slide_present is False
    assert report.findings == []


# ---------------------------------------------------------------------------
# Report serialization + text format
# ---------------------------------------------------------------------------

def test_report_to_dict_serializable(ctg, tmp_path):
    spec_path = _make_slide_spec(tmp_path)
    signal_path = _make_signal(tmp_path, kberdl_db_list=["fitnessbrowser"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    text = json.dumps(report.to_dict())
    parsed = json.loads(text)
    assert parsed["schema_version"] == ctg.SCHEMA_VERSION


def test_format_text_report_clean_pass(ctg, tmp_path):
    spec_path = _make_slide_spec(
        tmp_path,
        title="fitnessbrowser is the primary DB.",
    )
    signal_path = _make_signal(tmp_path, kberdl_db_list=["fitnessbrowser"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    text = ctg.format_text_report(report)
    assert "No findings" in text


def test_format_text_report_with_findings(ctg, tmp_path):
    spec_path = _make_slide_spec(tmp_path)
    signal_path = _make_signal(tmp_path,
                                kberdl_db_list=["fitnessbrowser"])
    report = ctg.check_cross_tenant_grounding(spec_path, signal_path)
    text = ctg.format_text_report(report)
    assert "database_omission" in text
    assert "fitnessbrowser" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_writes_json_to_audit_dir_by_default(ctg, tmp_path):
    draft_dir = tmp_path / "draft"
    (draft_dir / "working").mkdir(parents=True)
    spec_path = _make_slide_spec(draft_dir / "working")
    signal_path = _make_signal(
        draft_dir / "working", kberdl_db_list=["fitnessbrowser"])
    rc = ctg.main(["--draft-dir", str(draft_dir),
                    "--report-format", "json"])
    assert rc == 0
    out_path = draft_dir / "audit" / "cross_tenant_grounding.json"
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == ctg.SCHEMA_VERSION
    assert len(payload["findings"]) == 1  # fitnessbrowser omission


def test_cli_text_to_stdout(ctg, tmp_path, capsys):
    draft_dir = tmp_path / "draft"
    (draft_dir / "working").mkdir(parents=True)
    _make_slide_spec(draft_dir / "working")
    _make_signal(draft_dir / "working")
    rc = ctg.main(["--draft-dir", str(draft_dir),
                    "--report-format", "text"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "grounding check" in out


# ---------------------------------------------------------------------------
# Cascade integration
# ---------------------------------------------------------------------------

def test_review_cascade_reads_cross_tenant_grounding(ctg, tmp_path):
    """review_cascade._read_cross_tenant_grounding lifts our findings
    into cascade Tier-1 with kind=cross_tenant_grounding:<sub-kind>
    at P1."""
    from beril_presentation_maker.skill.tools import review_cascade as rc

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    payload = {
        "schema_version": ctg.SCHEMA_VERSION,
        "findings": [
            {
                "kind": "database_omission",
                "severity": "soft-warning",
                "slide_id": 22,
                "message": "signal lists 'fitnessbrowser' but not in slide",
                "evidence": {"db": "fitnessbrowser",
                             "kind": "kberdl_db"},
            },
            {
                "kind": "cohort_hallucination",
                "severity": "soft-warning",
                "slide_id": 22,
                "message": "slide names HMP2 not in signal",
                "evidence": {"cohort": "HMP2"},
            },
        ],
    }
    (audit_dir / "cross_tenant_grounding.json").write_text(
        json.dumps(payload), encoding="utf-8")

    findings = rc._read_cross_tenant_grounding(tmp_path)
    assert len(findings) == 2
    kinds = sorted(f.kind for f in findings)
    assert kinds == [
        "cross_tenant_grounding:cohort_hallucination",
        "cross_tenant_grounding:database_omission",
    ]
    for f in findings:
        assert f.severity == "P1"
        assert f.tier == "tier1"


def test_review_cascade_grounding_absent_returns_empty(ctg, tmp_path):
    """Read-if-present: missing audit/cross_tenant_grounding.json →
    no cascade contribution."""
    from beril_presentation_maker.skill.tools import review_cascade as rc
    findings = rc._read_cross_tenant_grounding(tmp_path)
    assert findings == []
