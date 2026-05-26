"""Tests for check_register_discipline.py — v0.5 Tier A.1 / D-072.

Coverage:
- Pattern matching (7 patterns from D-072 audit)
- Field-class classifier (operator / audience / other)
- Per-pattern field-class severity rules
- Per-project allowlist mechanism
- Allowlist substring matching
- Full scan_slide / check_register_discipline orchestration
- Text report rendering pin (operator-readable shape)
- CLI: file-not-found, malformed JSON, end-to-end on synthetic spec
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CRD_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
          / "tools" / "check_register_discipline.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def crd():
    return _import("check_register_discipline", CRD_PY)


def _spec_with_slides(slides: list[dict]) -> dict:
    """Build a minimal spec with the given slides."""
    return {
        "schema_version": "1.0",
        "project_id": "test",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x",
                        "tier_evidence": "STRONG"},
        "substories": [],
        "slides": slides,
    }


# ---------------------------------------------------------------------------
# Field-class classifier
# ---------------------------------------------------------------------------

def test_classify_data_source_as_operator(crd):
    """`data_source` is the canonical operator-provenance field."""
    assert crd.classify_field("data_source") == "operator"


def test_classify_notes_as_operator(crd):
    """`notes` / `speaker_notes` are operator-facing (audit fields)."""
    assert crd.classify_field("notes") == "operator"
    assert crd.classify_field("speaker_notes") == "operator"


def test_classify_audience_fields(crd):
    """Per D-072: title, bullets, caption, etc. are audience-facing."""
    for field in ("title", "headline", "subtitle", "punchline", "caption",
                   "bullets", "answer_summary", "step_caption", "context",
                   "implication", "concession", "left_col_content",
                   "right_col_content", "metric_value"):
        assert crd.classify_field(field) == "audience", (
            f"{field} should be classified audience")


def test_classify_unknown_field_as_other(crd):
    """Unknown leaf fields (e.g., diagram node labels) default to 'other'.
    `other` is treated as audience-facing by default per D-072 ("structural
    fields treated as audience-facing")."""
    assert crd.classify_field("label") == "other"
    assert crd.classify_field("method_text") == "other"
    assert crd.classify_field("randomkey") == "other"


def test_classify_v0_5_q_arc_fields_as_audience(crd):
    """v0.5 / D-071 Q-arc fields (`question`, `conclusion_for_next_substory`)
    are audience-facing — they appear on the Q-slide + the C-slide
    handoff, both visible to the audience."""
    assert crd.classify_field("question") == "audience"
    assert crd.classify_field("conclusion_for_next_substory") == "audience"


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

def _patterns_by_name(crd):
    return {p.name: p for p in crd.PATTERNS}


def test_pattern_notebook_id_matches_NB_refs(crd):
    pat = _patterns_by_name(crd)["notebook_id"]
    assert pat.regex.findall("see NB10 for details") == ["NB10"]
    assert pat.regex.findall("NB04b retracted; NB04c is current") == [
        "NB04b", "NB04c"]
    # With section marker
    assert pat.regex.findall("per NB10 §3") == ["NB10 §3"]


def test_pattern_notebook_id_does_not_match_NBA_or_NB(crd):
    """Avoid false-positives on words containing `NB`."""
    pat = _patterns_by_name(crd)["notebook_id"]
    # "NBA" is a word; "NB" alone (no digits) shouldn't match
    assert pat.regex.findall("NBA franchise") == []
    assert pat.regex.findall("NB without digits") == []


def test_pattern_notebook_filename(crd):
    pat = _patterns_by_name(crd)["notebook_filename"]
    assert pat.regex.findall(
        "see 01_demo.ipynb and 12_bakta_enrichment.ipynb") == [
        "01_demo.ipynb", "12_bakta_enrichment.ipynb"]


def test_pattern_section_marker(crd):
    pat = _patterns_by_name(crd)["section_marker"]
    assert pat.regex.findall("REPORT.md §Finding 7 and §Step 13") == [
        "§Finding 7", "§Step 13"]
    assert pat.regex.findall("§Interpretation 4 + §Hypothesis 1") == [
        "§Interpretation 4", "§Hypothesis 1"]


def test_pattern_notebook_cell(crd):
    pat = _patterns_by_name(crd)["notebook_cell"]
    assert pat.regex.findall("see cell 21 and Cell 5") == ["cell 21", "Cell 5"]


def test_pattern_figure_filename(crd):
    pat = _patterns_by_name(crd)["figure_filename"]
    assert pat.regex.findall(
        "see F03_recovery_by_method.png and fig28_domain.svg") == [
        "F03_recovery_by_method.png", "fig28_domain.svg"]


def test_pattern_schema_version_matches_internal_artifact_versions(crd):
    pat = _patterns_by_name(crd)["schema_version"]
    # `slide_spec.v1`, `review_cascade.v1` should match
    assert "slide_spec.v1" in str(
        pat.regex.findall("emit slide_spec.v1 format"))


def test_pattern_tool_version_matches_Bakta(crd):
    pat = _patterns_by_name(crd)["tool_version"]
    assert pat.regex.findall("Bakta v1.12.0 reannotation") == ["Bakta v1.12.0"]


def test_tool_version_audience_severity_is_allowed_by_default(crd):
    """Per D-072: tool versions audience-relevant by default; per-project
    allowlist can demote specific tool names to soft-warning."""
    pat = _patterns_by_name(crd)["tool_version"]
    assert pat.audience_severity == "allowed"


def test_all_other_patterns_default_to_soft_warning(crd):
    """Per D-072: 6 of 7 patterns are soft-warning in audience fields;
    only tool_version is allowed-by-default."""
    soft = [p for p in crd.PATTERNS if p.audience_severity == "soft-warning"]
    allowed = [p for p in crd.PATTERNS if p.audience_severity == "allowed"]
    assert len(soft) == 6
    assert len(allowed) == 1
    assert allowed[0].name == "tool_version"


# ---------------------------------------------------------------------------
# Per-field-class severity (the core D-072 contract)
# ---------------------------------------------------------------------------

def test_nb_ref_in_data_source_is_allowed(crd):
    """Per D-072: operator-facing fields like `data_source` legitimately
    contain notebook IDs / §section markers / etc. — these are NOT
    violations."""
    slide = {
        "id": 1,
        "content": {
            "title": "Clean title",
            "data_source": "REPORT.md §Finding 13; 09_final_synthesis.ipynb",
        },
    }
    violations = crd.scan_slide(slide)
    # Both §Finding 13 and 09_final_synthesis.ipynb are in data_source
    # (operator field) — must not be reported.
    assert violations == [], (
        f"expected no violations on operator field, got {violations}")


def test_nb_ref_in_bullets_is_soft_warning(crd):
    """Per D-072: audience-facing fields like `bullets` get
    soft-warning on notebook IDs."""
    slide = {
        "id": 5,
        "content": {
            "title": "Clean title",
            "bullets": [
                "NB04 retracted; NB04b is current",
                "Per §Finding 7, the analysis ..."
            ],
        },
    }
    violations = crd.scan_slide(slide)
    # Expect 2 NB-id matches + 1 §section-marker match
    assert len(violations) >= 3
    # All soft-warning, all in audience field
    for v in violations:
        assert v.severity == "soft-warning"
        assert v.field_class == "audience"


def test_nb_ref_in_caption_is_soft_warning(crd):
    """Captions are audience-facing too — NB-refs land as soft-warning."""
    slide = {
        "id": 8,
        "content": {
            "title": "t",
            "figure": "fig.png",
            "caption": "Bakta v1.12.0 reannotation; see NB12 §3",
        },
    }
    violations = crd.scan_slide(slide)
    # Bakta v1.12.0 = tool_version (allowed-default; not reported);
    # NB12 §3 = notebook_id (soft-warning)
    nb_viols = [v for v in violations if v.pattern_name == "notebook_id"]
    assert len(nb_viols) == 1
    assert nb_viols[0].severity == "soft-warning"


def test_tool_version_in_audience_field_is_allowed_default(crd):
    """Per D-072: tool versions don't trigger by default; per-project
    allowlist would DEMOTE them to soft-warning if a project wanted
    to discourage specific names."""
    slide = {
        "id": 1,
        "content": {
            "title": "Clean title",
            "bullets": ["Bakta v1.12.0 reannotation"],
        },
    }
    violations = crd.scan_slide(slide)
    # No violations — Bakta v1.12.0 is allowed by default
    assert violations == []


def test_clean_slide_emits_no_violations(crd):
    """A slide with no specialist references emits zero violations."""
    slide = {
        "id": 1,
        "content": {
            "title": "Recovery rate by annotation method",
            "subtitle": "Morgan Price 2022 gold standard, n=142 loci",
            "caption": "Annotation pipelines produce diverging recovery rates.",
            "bullets": [
                "Recovery 87/95 on E. coli K-12",
                "Consistent across replicates",
            ],
        },
    }
    violations = crd.scan_slide(slide)
    assert violations == []


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

def test_load_allowlist_returns_empty_when_no_project_dir(crd):
    assert crd.load_allowlist(None) == frozenset()


def test_load_allowlist_returns_empty_when_file_absent(crd, tmp_path):
    (tmp_path / "references").mkdir()
    assert crd.load_allowlist(tmp_path) == frozenset()


def test_load_allowlist_reads_terms(crd, tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "register_allowlist.md").write_text(
        "# Project allowlist\n"
        "NB10\n"
        "GapMind v2.4\n"
        "\n"
        "# This comment is ignored\n"
        "Bakta v1.12.0\n",
        encoding="utf-8")
    allowlist = crd.load_allowlist(tmp_path)
    assert allowlist == frozenset({"NB10", "GapMind v2.4", "Bakta v1.12.0"})


def test_allowlist_substring_match_demotes_violation_to_allowed(crd):
    """When a violation match is a substring of an allowlisted term
    (or vice versa), the violation severity becomes 'allowed' +
    `allowlisted=True` for audit visibility."""
    slide = {
        "id": 1,
        "content": {
            "title": "Tool comparison",
            "bullets": ["NB10 baseline + NB05 ablation"],
        },
    }
    # Allowlist NB10 specifically
    violations = crd.scan_slide(slide, allowlist=frozenset({"NB10"}))
    # NB10 should appear with severity=allowed, allowlisted=True
    # NB05 should appear with severity=soft-warning, allowlisted=False
    nb10 = [v for v in violations if v.matched_text == "NB10"]
    nb05 = [v for v in violations if v.matched_text == "NB05"]
    assert len(nb10) == 1
    assert nb10[0].severity == "allowed"
    assert nb10[0].allowlisted is True
    assert len(nb05) == 1
    assert nb05[0].severity == "soft-warning"
    assert nb05[0].allowlisted is False


# ---------------------------------------------------------------------------
# check_register_discipline orchestration
# ---------------------------------------------------------------------------

def test_check_aggregates_across_slides(crd):
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T1", "bullets": ["NB01 see this"]}},
        {"id": 2, "content": {"title": "T2", "caption": "§Finding 3 details"}},
        {"id": 3, "content": {"title": "T3 — clean"}},
    ])
    report = crd.check_register_discipline(spec)
    # Two violations total: NB01 in slide 1, §Finding 3 in slide 2
    assert len(report.violations) == 2
    assert report.n_violations_by_severity == {"soft-warning": 2}
    assert report.n_violations_by_pattern == {
        "notebook_id": 1, "section_marker": 1}


def test_check_includes_schema_version(crd):
    """Schema version pinned for cross-skill consumer contracts."""
    spec = _spec_with_slides([])
    report = crd.check_register_discipline(spec)
    assert report.schema_version == "register-discipline.v1"


def test_check_uses_allowlist_from_project_dir(crd, tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "register_allowlist.md").write_text(
        "NB01\n", encoding="utf-8")
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T", "bullets": ["NB01 retracted"]}},
    ])
    report = crd.check_register_discipline(spec, project_dir=tmp_path)
    assert "NB01" in report.allowlist_terms
    # The NB01 violation is emitted but severity=allowed + allowlisted=True
    assert len(report.violations) == 1
    assert report.violations[0].allowlisted is True
    assert report.violations[0].severity == "allowed"


# ---------------------------------------------------------------------------
# Field-walker handles nested structures
# ---------------------------------------------------------------------------

def test_iter_prose_walks_diagram_nodes(crd):
    """workflow_diagram has nested nodes[].label structures. The walker
    should yield each node's label with field_name='label' (the
    immediate parent key — D-072 field-class taxonomy is by leaf
    field name)."""
    content = {
        "title": "Workflow",
        "diagram": {
            "nodes": [
                {"id": "n1", "label": "see NB10"},
                {"id": "n2", "label": "clean"},
            ],
        },
    }
    yielded = list(crd._iter_prose_strings(content))
    # Each leaf string gets its immediate-parent key as field_name
    pairs = [(field, text) for field, text in yielded]
    assert ("label", "see NB10") in pairs
    assert ("label", "clean") in pairs


def test_iter_prose_walks_bullets_lists(crd):
    """bullets is a list of strings; each element yields with
    field_name='bullets'."""
    content = {
        "title": "T",
        "bullets": ["one NB01", "two §Finding 4", "three clean"],
    }
    yielded = list(crd._iter_prose_strings(content))
    bullet_strings = [text for field, text in yielded if field == "bullets"]
    assert len(bullet_strings) == 3


# ---------------------------------------------------------------------------
# Text report rendering
# ---------------------------------------------------------------------------

def test_text_report_clean_deck_says_clean(crd):
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T1"}},
    ])
    report = crd.check_register_discipline(spec)
    text = crd.format_text_report(report)
    assert "Clean" in text or "no register-discipline violations" in text


def test_text_report_groups_by_slide(crd):
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T1", "bullets": ["NB01"]}},
        {"id": 2, "content": {"title": "T2", "bullets": ["NB02"]}},
    ])
    report = crd.check_register_discipline(spec)
    text = crd.format_text_report(report)
    assert "Slide 1" in text
    assert "Slide 2" in text
    assert "NB01" in text
    assert "NB02" in text


def test_text_report_includes_schema_version(crd):
    spec = _spec_with_slides([])
    report = crd.check_register_discipline(spec)
    text = crd.format_text_report(report)
    assert "register-discipline.v1" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_missing_slide_spec_returns_2(crd, tmp_path):
    rc = crd.main([str(tmp_path / "does-not-exist.json")])
    assert rc == 2


def test_cli_malformed_json_returns_2(crd, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    rc = crd.main([str(p)])
    assert rc == 2


def test_cli_clean_spec_returns_0_with_text_report(crd, tmp_path, capsys):
    p = tmp_path / "spec.json"
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "Clean title"}},
    ])
    p.write_text(json.dumps(spec), encoding="utf-8")
    rc = crd.main([str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "register-discipline.v1" in out


def test_cli_writes_out_file(crd, tmp_path):
    p = tmp_path / "spec.json"
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T", "bullets": ["see NB42"]}},
    ])
    p.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "report.md"
    rc = crd.main([str(p), "--out", str(out)])
    assert rc == 0
    body = out.read_text()
    assert "NB42" in body


def test_cli_json_format(crd, tmp_path, capsys):
    p = tmp_path / "spec.json"
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T", "bullets": ["NB42"]}},
    ])
    p.write_text(json.dumps(spec), encoding="utf-8")
    rc = crd.main([str(p), "--report-format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema_version"] == "register-discipline.v1"
    assert len(data["violations"]) == 1


def test_cli_loads_allowlist_when_project_dir_provided(crd, tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "register_allowlist.md").write_text(
        "NB42\n", encoding="utf-8")
    p = tmp_path / "spec.json"
    spec = _spec_with_slides([
        {"id": 1, "content": {"title": "T", "bullets": ["NB42 baseline"]}},
    ])
    p.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "report.json"
    rc = crd.main([str(p), "--project-dir", str(tmp_path),
                    "--out", str(out), "--report-format", "json"])
    assert rc == 0
    data = json.loads(out.read_text())
    assert "NB42" in data["allowlist_terms"]
    # Violation is emitted but marked allowlisted
    assert data["violations"][0]["allowlisted"] is True
    assert data["violations"][0]["severity"] == "allowed"
