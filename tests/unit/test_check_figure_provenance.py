"""Unit tests for tools/check_figure_provenance.py (v0.6 Tier A.1 /
D-080 + D-081).

Test surfaces:
- Happy path: substory cites a curated figure + uses it in a
  data_figure slide → no findings.
- missing_data_figure_for_curated_analysis: substory cites a curated
  figure but has 0 data_figure slides using it.
- data_figure_path_not_in_curated_inventory: a data_figure slide's
  figure: field points at a non-curated path.
- Per-substory utilization rate calculation.
- Curated-figure inventory parsing (the markdown shape from the
  curator).
- NB-id matching: NB04b_* and NB04h_* both group under NB04.
- Defensive: missing files return empty / fail-soft.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from beril_presentation_maker.skill.tools import check_figure_provenance as fp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_curated(tmp_path: Path, paths: list[str]) -> Path:
    """Write a synthetic curated_figures.md listing the given paths."""
    lines = ["# Figures Curated for `talk-30`", ""]
    for i, p in enumerate(paths, 1):
        lines.append(f"### {i}. `{p}` _(source-strength: REPORT-referenced)_")
        lines.append("")
        lines.append("_PNG, 100 KB_")
        lines.append("")
    out = tmp_path / "curated_figures.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _write_substories(tmp_path: Path,
                      substories: list[tuple[str, list[str]]]) -> Path:
    """Write a synthetic 02_substories.md with given substory_id +
    notebook-filename pairs."""
    lines = ["# Substory clusters", ""]
    for sid, notebooks in substories:
        lines.append(f"### {sid} — {sid} cluster")
        lines.append("")
        lines.append("**Critical analyses covered:**")
        lines.append("")
        for nb in notebooks:
            lines.append(f"- A1: analysis — REPORT.md / {nb}")
        lines.append("")
    out = tmp_path / "02_substories.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _slide(layout: str, substory_id: str | None = None,
           figure: str | None = None, **extra) -> dict:
    content = dict(extra)
    if figure is not None:
        content["figure"] = figure
    return {"layout": layout, "substory_id": substory_id,
            "content": content}


def _write_spec(tmp_path: Path, slides: list[dict]) -> Path:
    spec = {"schema_version": "slide-spec.v1", "slides": slides}
    out = tmp_path / "slide_spec.json"
    out.write_text(json.dumps(spec), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_no_findings(tmp_path):
    """Substory cites NB13 + has a data_figure slide using
    figures/NB13_*.png. No findings."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    spec = _write_spec(tmp_path, [
        _slide("data_figure", substory_id="S1",
               figure="figures/NB13_phage.png", title="x", caption="x"),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    assert report.findings == []
    assert report.utilization_rate == 1.0
    assert report.n_data_figure_using_curated == 1


# ---------------------------------------------------------------------------
# missing_data_figure_for_curated_analysis (the load-bearing finding)
# ---------------------------------------------------------------------------

def test_missing_data_figure_for_curated_analysis(tmp_path):
    """Substory cites an analysis whose NB-id matches a curated
    figure, but the substory has 0 data_figure slides. D-080
    violation."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    spec = _write_spec(tmp_path, [
        # claim_evidence instead of data_figure — the v0.5.1 pattern
        _slide("claim_evidence", substory_id="S1",
               title="claim", bullets=["evidence"]),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.kind == "missing_data_figure_for_curated_analysis"
    assert f.severity == "soft-warning"
    assert f.substory_id == "S1"
    assert "NB13_phage.png" in f.message
    # Utilization rate is 0/1 substories covered
    assert report.utilization_rate == 0.0


def test_nb_id_grouping_strips_trailing_letter(tmp_path):
    """NB04b_* and NB04h_* both match NB04_*.png per D-080
    notebook-id matching rule (sub-analyses share the same figure)."""
    curated = _write_curated(tmp_path, ["figures/NB04_ecotype.png"])
    substories = _write_substories(
        tmp_path,
        [("S1", ["NB04b_ecotype_refit.ipynb", "NB04h_hmp2.ipynb"])])
    # Use the curated figure on a data_figure slide → no finding.
    spec = _write_spec(tmp_path, [
        _slide("data_figure", substory_id="S1",
               figure="figures/NB04_ecotype.png", title="x", caption="x"),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    assert report.findings == []


def test_substory_with_no_curated_match_skipped(tmp_path):
    """Substory whose analyses don't match any curated figure
    DOES NOT trigger the rule (D-080: rule fires only when curated
    figure exists for the analysis)."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB99_unrelated.ipynb"])])
    spec = _write_spec(tmp_path, [
        _slide("claim_evidence", substory_id="S1",
               title="claim", bullets=["evidence"]),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    assert report.findings == []
    # No substories with curated figures → utilization 1.0 (vacuous)
    assert report.utilization_rate == 1.0


# ---------------------------------------------------------------------------
# data_figure_path_not_in_curated_inventory
# ---------------------------------------------------------------------------

def test_data_figure_path_not_in_curated_inventory(tmp_path):
    """A data_figure slide whose figure: path isn't in the curated
    inventory triggers the curated-figure-substitution finding."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    spec = _write_spec(tmp_path, [
        # Wrong figure path — not in curated inventory.
        _slide("data_figure", substory_id="S1",
               figure="figures/NB99_random.png", title="x", caption="x"),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    # Two findings: (1) missing for NB13 (the non-curated figure
    # doesn't count); (2) data_figure points at non-curated path.
    kinds = sorted(f.kind for f in report.findings)
    assert "data_figure_path_not_in_curated_inventory" in kinds
    # The non-curated-path finding has slide_id
    nc = [f for f in report.findings
          if f.kind == "data_figure_path_not_in_curated_inventory"][0]
    assert nc.slide_id == 0
    assert "NB99_random.png" in nc.message


# ---------------------------------------------------------------------------
# Curated-figure inventory parsing
# ---------------------------------------------------------------------------

def test_parse_curated_figures_extracts_paths(tmp_path):
    curated = _write_curated(tmp_path, [
        "figures/NB13_phage.png",
        "figures/NB04_ecotype.png",
        "figures/F03_recovery.svg",
    ])
    paths = fp.parse_curated_figures(curated)
    assert paths == {
        "figures/NB13_phage.png",
        "figures/NB04_ecotype.png",
        "figures/F03_recovery.svg",
    }


def test_parse_curated_figures_missing_file_returns_empty(tmp_path):
    """Defensive: missing curated_figures.md → empty set, no error."""
    paths = fp.parse_curated_figures(tmp_path / "nonexistent.md")
    assert paths == set()


def test_parse_substory_analyses_extracts_notebooks(tmp_path):
    substories = _write_substories(tmp_path, [
        ("S1", ["NB13_phagefoundry.ipynb", "NB14_endogenous_phageome.ipynb"]),
        ("S2", ["NB04b_ecotype_refit.ipynb"]),
    ])
    out = fp.parse_substory_analyses(substories)
    assert set(out.keys()) == {"S1", "S2"}
    # Notebook filenames preserved verbatim
    assert "NB13_phagefoundry.ipynb" in out["S1"]
    assert "NB14_endogenous_phageome.ipynb" in out["S1"]
    assert "NB04b_ecotype_refit.ipynb" in out["S2"]


# ---------------------------------------------------------------------------
# Utilization rate
# ---------------------------------------------------------------------------

def test_utilization_rate_partial_coverage(tmp_path):
    """3 substories with curated figures; 2 use them → 2/3 rate."""
    curated = _write_curated(tmp_path, [
        "figures/NB13_phage.png",
        "figures/NB14_phageome.png",
        "figures/NB15_cocktail.png",
    ])
    substories = _write_substories(tmp_path, [
        ("S1", ["NB13_phagefoundry.ipynb"]),
        ("S2", ["NB14_endogenous.ipynb"]),
        ("S3", ["NB15_patient_cocktail.ipynb"]),
    ])
    # S1 + S2 use curated; S3 doesn't.
    spec = _write_spec(tmp_path, [
        _slide("data_figure", substory_id="S1",
               figure="figures/NB13_phage.png", title="x", caption="x"),
        _slide("data_figure", substory_id="S2",
               figure="figures/NB14_phageome.png", title="x", caption="x"),
        _slide("claim_evidence", substory_id="S3",
               title="x", bullets=["x"]),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    # rate = 2 (covered) / 3 (with curated available)
    assert report.utilization_rate == pytest.approx(2 / 3)
    assert len(report.findings) == 1
    assert report.findings[0].substory_id == "S3"


# ---------------------------------------------------------------------------
# Report shape + serialization
# ---------------------------------------------------------------------------

def test_report_to_dict_serializable(tmp_path):
    """Report.to_dict() must be JSON-serializable end-to-end (the
    cascade reader json.loads the audit output)."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    spec = _write_spec(tmp_path, [
        _slide("claim_evidence", substory_id="S1",
               title="claim", bullets=["evidence"]),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    text = json.dumps(report.to_dict())
    parsed = json.loads(text)
    assert parsed["schema_version"] == fp.SCHEMA_VERSION
    assert isinstance(parsed["findings"], list)
    assert parsed["findings"][0]["kind"] == \
        "missing_data_figure_for_curated_analysis"


def test_format_text_report_includes_findings(tmp_path):
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    spec = _write_spec(tmp_path, [
        _slide("claim_evidence", substory_id="S1",
               title="claim", bullets=["evidence"]),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    text = fp.format_text_report(report)
    assert "figure-provenance.v1" in text
    assert "missing_data_figure_for_curated_analysis" in text
    assert "S1" in text


def test_format_text_report_clean_pass(tmp_path):
    """When all rules are satisfied, the report says so explicitly."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    spec = _write_spec(tmp_path, [
        _slide("data_figure", substory_id="S1",
               figure="figures/NB13_phage.png", title="x", caption="x"),
    ])
    report = fp.check_figure_provenance(spec, substories, curated)
    text = fp.format_text_report(report)
    assert "No findings" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_writes_json_to_audit_dir_by_default(tmp_path):
    """`--report-format json` without --out writes to
    <draft-dir>/audit/figure_provenance.json."""
    draft_dir = tmp_path / "draft"
    (draft_dir / "narrative").mkdir(parents=True)
    (draft_dir / "working").mkdir()
    curated = _write_curated(draft_dir / "working", ["figures/NB13_phage.png"])
    substories = _write_substories(
        draft_dir / "narrative",
        [("S1", ["NB13_phagefoundry.ipynb"])])
    # Rename via move since fixtures wrote to tmp_path root.
    (draft_dir / "narrative" / "02_substories.md").write_text(
        substories.read_text(encoding="utf-8"), encoding="utf-8")
    (draft_dir / "working" / "curated_figures.md").write_text(
        curated.read_text(encoding="utf-8"), encoding="utf-8")
    spec = _write_spec(draft_dir / "working", [
        _slide("claim_evidence", substory_id="S1",
               title="claim", bullets=["evidence"]),
    ])
    (draft_dir / "working" / "slide_spec.json").write_text(
        spec.read_text(encoding="utf-8"), encoding="utf-8")

    rc = fp.main(["--draft-dir", str(draft_dir),
                  "--report-format", "json"])
    assert rc == 0
    out_path = draft_dir / "audit" / "figure_provenance.json"
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == fp.SCHEMA_VERSION
    assert len(payload["findings"]) == 1


def test_cli_text_format_to_stdout(tmp_path, capsys):
    draft_dir = tmp_path / "draft"
    (draft_dir / "narrative").mkdir(parents=True)
    (draft_dir / "working").mkdir()
    _write_curated(draft_dir / "working", ["figures/NB13_phage.png"])
    (draft_dir / "working" / "curated_figures.md").write_text(
        (draft_dir / "working" / "curated_figures.md").read_text(
            encoding="utf-8"), encoding="utf-8")
    _write_substories(draft_dir / "narrative",
                      [("S1", ["NB13_phagefoundry.ipynb"])])
    (draft_dir / "narrative" / "02_substories.md").write_text(
        (draft_dir / "narrative" / "02_substories.md").read_text(
            encoding="utf-8"), encoding="utf-8")
    _write_spec(draft_dir / "working", [
        _slide("claim_evidence", substory_id="S1",
               title="claim", bullets=["evidence"]),
    ])
    (draft_dir / "working" / "slide_spec.json").write_text(
        (draft_dir / "working" / "slide_spec.json").read_text(
            encoding="utf-8"), encoding="utf-8")

    rc = fp.main(["--draft-dir", str(draft_dir),
                  "--report-format", "text"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "figure-provenance.v1" in captured.out
    assert "missing_data_figure_for_curated_analysis" in captured.out


# ---------------------------------------------------------------------------
# Defensive — missing files
# ---------------------------------------------------------------------------

def test_missing_slide_spec_returns_empty_findings(tmp_path):
    """Defensive: missing slide_spec → empty slides → no findings.
    Should not crash."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    substories = _write_substories(
        tmp_path, [("S1", ["NB13_phagefoundry.ipynb"])])
    report = fp.check_figure_provenance(
        tmp_path / "nonexistent.json", substories, curated)
    # No slides means no data_figure violations + no analyses-cited-but-
    # not-rendered violations either (no slides to check against).
    # Strictly: substory cites NB13 + curated has NB13, but there are
    # no slides at all → the missing-data_figure finding STILL fires
    # because the substory should have one.
    assert any(f.kind == "missing_data_figure_for_curated_analysis"
               for f in report.findings)


def test_missing_substories_returns_empty(tmp_path):
    """No substories → no substory-level findings."""
    curated = _write_curated(tmp_path, ["figures/NB13_phage.png"])
    spec = _write_spec(tmp_path, [
        _slide("data_figure", substory_id="S1",
               figure="figures/NB13_phage.png", title="x", caption="x"),
    ])
    report = fp.check_figure_provenance(
        spec, tmp_path / "nonexistent.md", curated)
    # No substories → no missing_data_figure findings. The
    # data_figure slide cites a curated path → no
    # not-in-inventory finding either.
    assert report.findings == []


# ---------------------------------------------------------------------------
# Cascade integration pin (review_cascade reads audit/figure_provenance.json)
# ---------------------------------------------------------------------------

def test_review_cascade_reads_figure_provenance(tmp_path):
    """review_cascade._read_figure_provenance must lift our findings
    into cascade Tier-1 with kind=figure_provenance:<sub-kind> at P1
    (soft-warning maps to P1)."""
    from beril_presentation_maker.skill.tools import review_cascade as rc

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    payload = {
        "schema_version": fp.SCHEMA_VERSION,
        "findings": [
            {
                "kind": "missing_data_figure_for_curated_analysis",
                "severity": "soft-warning",
                "substory_id": "S3",
                "slide_id": None,
                "message": "substory S3 missing data_figure",
                "evidence": {"relevant_curated_figures":
                             ["figures/NB11.png"]},
            },
        ],
    }
    (audit_dir / "figure_provenance.json").write_text(
        json.dumps(payload), encoding="utf-8")

    findings = rc._read_figure_provenance(tmp_path)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "figure_provenance:missing_data_figure_for_curated_analysis"
    assert f.severity == "P1"
    assert f.tier == "tier1"
    assert "S3" in f.detail


def test_review_cascade_figure_provenance_absent_returns_empty(tmp_path):
    """Read-if-present: missing audit/figure_provenance.json → no
    cascade contribution."""
    from beril_presentation_maker.skill.tools import review_cascade as rc
    findings = rc._read_figure_provenance(tmp_path)
    assert findings == []
