"""Tests for tools/check_quantitative_grounding.py — number extraction
and REPORT.md cross-check.

Coverage:
  - Number extraction: integers, decimals, percents, ratios, n=, scientific
  - Normalization: commas, percent ↔ decimal, rounding tolerance
  - Year filter: 4-digit publication years skipped
  - Layout exclusions: references / acknowledgments skipped
  - Grounded vs ungrounded classification
  - Severity grading
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# Load check_quantitative_grounding.py as a module (it lives in skill/tools/,
# not in the importable package path directly).
_TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
    / "check_quantitative_grounding.py"
)


@pytest.fixture(scope="module")
def cqg():
    spec = importlib.util.spec_from_file_location(
        "check_quantitative_grounding", _TOOL_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_quantitative_grounding"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------


def test_extract_simple_integer(cqg):
    nums = cqg.extract_numbers("We found 142 dark genes.")
    assert len(nums) == 1
    assert nums[0].canonical == "142"
    assert nums[0].kind == "integer"


def test_extract_comma_integer(cqg):
    nums = cqg.extract_numbers("57,011 of 228,709 genes are dark.")
    canonicals = [n.canonical for n in nums]
    assert "57011" in canonicals
    assert "228709" in canonicals
    assert all(n.kind == "integer" for n in nums)


def test_extract_decimal_and_percent(cqg):
    nums = cqg.extract_numbers("24.9% of bacterial genes (0.249 ratio) are dark.")
    canonicals = [n.canonical for n in nums]
    assert "24.9" in canonicals
    assert "0.249" in canonicals
    # Find which one is the percent
    percents = [n for n in nums if n.kind == "percent"]
    assert len(percents) >= 1
    assert percents[0].canonical == "24.9"


def test_extract_ratio(cqg):
    nums = cqg.extract_numbers("Lab-field concordance: 4/4 pre-registered tests pass.")
    ratios = [n for n in nums if n.kind == "ratio"]
    assert len(ratios) == 1
    assert ratios[0].canonical == "4/4"


def test_extract_n_eq(cqg):
    nums = cqg.extract_numbers("Cross-validated against the gold standard (n=142).")
    n_eq_finds = [n for n in nums if n.kind == "n_eq"]
    assert len(n_eq_finds) == 1
    assert n_eq_finds[0].canonical == "142"


def test_extract_scientific(cqg):
    nums = cqg.extract_numbers("Significance: FDR=2.3e-4 across all tests.")
    sci = [n for n in nums if n.kind == "scientific"]
    assert len(sci) == 1
    assert "2.3e-4" in sci[0].canonical.lower()


def test_year_detection(cqg):
    """Years in the publication-year range should be flagged via is_year()."""
    nums = cqg.extract_numbers("As shown by Smith 2023 and Jones 1995, …")
    years = [n for n in nums if n.is_year()]
    canonicals = [n.canonical for n in years]
    assert "2023" in canonicals
    assert "1995" in canonicals


def test_no_double_extraction_n_eq_then_integer(cqg):
    """n=142 should produce ONE finding (kind=n_eq), not also a separate
    'integer 142'."""
    nums = cqg.extract_numbers("n=142 measurements were taken.")
    # 142 should appear once, with kind=n_eq
    matching = [n for n in nums if n.canonical == "142"]
    assert len(matching) == 1
    assert matching[0].kind == "n_eq"


# ---------------------------------------------------------------------------
# REPORT.md matching
# ---------------------------------------------------------------------------


def _make_report_index(cqg, text: str):
    """Helper: build a ReportIndex from raw text without needing a file."""
    idx = cqg.ReportIndex(
        raw_text=text,
        normalized_text=text.replace(",", "").lower(),
        text_no_approx=text.replace(",", "").lower(),
        numeric_set=cqg.build_numeric_set(text),
    )
    return idx


def test_match_verbatim_integer(cqg):
    idx = _make_report_index(cqg, "We identified 142 candidate genes in NB04.")
    nums = cqg.extract_numbers("title says 142 candidates")
    match = cqg._find_in_report(nums[0], idx)
    assert match is not None
    assert match["match_form"] == "verbatim"


def test_match_comma_normalized(cqg):
    idx = _make_report_index(cqg, "Total: 57,011 dark genes across 48 organisms.")
    # Slide says "57011" without comma
    nums = cqg.extract_numbers("57011 dark genes")
    match = cqg._find_in_report(nums[0], idx)
    assert match is not None
    # Could match verbatim (if normalized text strips commas) or comma_normalized
    assert match["match_form"] in ("verbatim", "comma_normalized")


def test_match_percent_to_decimal(cqg):
    """Slide says '24.9%', REPORT mentions '0.249' — should match via cross-form."""
    idx = _make_report_index(cqg, "The dark fraction is 0.249 of all genes.")
    nums = cqg.extract_numbers("24.9% of genes")
    pct = [n for n in nums if n.kind == "percent"][0]
    match = cqg._find_in_report(pct, idx)
    assert match is not None
    assert match["match_form"] == "percent_to_decimal"


def test_match_ratio_variant(cqg):
    """Slide says '4/4', REPORT says '4 of 4'."""
    idx = _make_report_index(cqg, "4 of 4 pre-registered tests passed.")
    nums = cqg.extract_numbers("4/4 pass rate")
    match = cqg._find_in_report(nums[0], idx)
    assert match is not None
    assert match["match_form"] == "ratio_variant"


def test_no_match_when_absent(cqg):
    """Slide says '17,344' but REPORT only has '17,200' — should not match."""
    idx = _make_report_index(cqg, "Approximately 17,200 genes were scored.")
    nums = cqg.extract_numbers("17,344 dark genes")
    match = cqg._find_in_report(nums[0], idx)
    # 17,344 is close to 17,200 but exact match should fail
    assert match is None or match["match_form"] != "verbatim"


# ---------------------------------------------------------------------------
# End-to-end check_grounding
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_dirs(tmp_path):
    """Create a synthetic v0.3.1+ talks/draft_N/ + REPORT.md fixture."""
    project_dir = tmp_path / "synthetic"
    talks_dir = project_dir / "talks" / "draft_1"
    # v0.3.1 4-zone layout
    for sub in ("deliverable", "narrative", "working", "audit"):
        (talks_dir / sub).mkdir(parents=True)
    return project_dir, talks_dir


def _write_spec(talks_dir, slides):
    spec = {
        "schema_version": "1.0",
        "project_id": "synthetic",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": slides,
    }
    # v0.3.1: spec lives under working/
    (talks_dir / "working" / "slide_spec.json").write_text(
        json.dumps(spec), encoding="utf-8")


def _write_report(project_dir, body):
    (project_dir / "REPORT.md").write_text(body, encoding="utf-8")


def test_e2e_all_grounded(cqg, fixture_dirs):
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "We identified 142 dark genes across 48 organisms.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "We found 142 candidates",
                        "bullets": ["across 48 organisms"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    assert report.total_grounded == 2
    assert report.total_ungrounded == 0
    assert len(report.findings) == 0


def test_e2e_ungrounded_finding(cqg, fixture_dirs):
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "We identified 142 dark genes.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "We found 9999 candidates",
                        "bullets": ["unverified"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    assert report.total_ungrounded >= 1
    nines = [f for f in report.findings if f.number.canonical == "9999"]
    assert len(nines) == 1
    assert nines[0].severity == "high"  # > 1000


def test_e2e_references_layout_skipped(cqg, fixture_dirs):
    """Numbers in references/acknowledgments slides should NOT be checked
    — they're typically external citation issue numbers."""
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "Some content with no journal numbers.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "references",
            "content": {"refs_short": ["Smith 2023 Nature 557(7706):503"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    # 7706 (journal issue) should not be flagged
    sevens = [f for f in report.findings if "7706" in f.number.canonical]
    assert len(sevens) == 0


def test_e2e_year_skipped(cqg, fixture_dirs):
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "Smith published in 2023.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "Citing Smith 1999",
                        "bullets": ["Jones 2024 also relevant"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    # 1999 and 2024 are years; should be skipped (not grounded, not findings)
    assert report.total_skipped_years >= 2
    year_findings = [f for f in report.findings
                     if f.number.canonical in ("1999", "2024")]
    assert len(year_findings) == 0


def test_e2e_severity_grading(cqg, fixture_dirs):
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "Empty report.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "Big number 12345 vs small 5",
                        "bullets": ["54.3% rate"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    sevs = {f.number.canonical: f.severity for f in report.findings}
    # 12345 > 1000 → high
    assert sevs.get("12345") == "high"
    # 5 ≤ 100 → low
    assert sevs.get("5") == "low"
    # 54.3 (percent) → medium
    assert sevs.get("54.3") == "medium"


# ---------------------------------------------------------------------------
# D-052 — numeric-grounding false-positive fixes
# ---------------------------------------------------------------------------
# Ported 2026-05-21 from paper-writer's check_numeric_grounding.py
# 0.2.0-d052. Four surface-form canonicalization classes that produce
# false "ungrounded" findings when the slide and REPORT.md write the
# same value differently:
#   1. superscript scientific notation  (1.1 x 10^-130  vs  1.1e-130)
#   2. K/M/G/T SI-suffix expansion, source-side  (83K  vs  83,000)
#   3. trailing-zero canonicalization  (82.0  vs  82)
#   4. comma support in the n= extractor  (n=22,751  not truncated to n=22)


def test_d052_extract_superscript_scientific(cqg):
    """`1.1 x 10^-130` extracts as ONE scientific number, not three
    (mantissa / 10 / exponent) bare numbers."""
    nums = cqg.extract_numbers("p-value 1.1 x 10^-130 observed")
    sci = [n for n in nums if n.kind == "scientific"]
    assert len(sci) == 1
    assert sci[0].canonical == "1.1e-130"
    # No stray bare numbers from the mantissa / "10" / exponent.
    assert not any(n.canonical in ("10", "130", "1.1") for n in nums)


def test_d052_extract_n_eq_with_comma(cqg):
    """`n=22,751` extracts as ONE n_eq number (canonical 22751), not a
    truncated n_eq 22 plus a stray integer 751."""
    nums = cqg.extract_numbers("cohort n=22,751 patients enrolled")
    n_eq = [n for n in nums if n.kind == "n_eq"]
    assert len(n_eq) == 1
    assert n_eq[0].canonical == "22751"
    assert not any(n.canonical == "751" for n in nums)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("82.0", "82"),                     # trailing-zero collapse
        ("82", "82"),
        ("0.30", "0.3"),
        ("0.3", "0.3"),
        ("1.77e-06", "1.77e-6"),            # exponent leading-zero strip
        ("1.5e-43", "1.5e-43"),
        ("not-a-number", "not-a-number"),   # passthrough on parse failure
    ],
)
def test_d052_canonical_form(cqg, raw, expected):
    assert cqg._canonical_form(raw) == expected


@pytest.mark.parametrize(
    "text,expected_substr",
    [
        ("83K reads", "83000"),
        ("1.5M cells", "1500000"),
        ("2G base pairs", "2000000000"),
    ],
)
def test_d052_expand_si_suffixes(cqg, text, expected_substr):
    """K/M/G/T SI suffixes expand to integer form."""
    assert expected_substr in cqg._expand_si_suffixes(text)


def test_d052_expand_si_suffixes_guards_word_collisions(cqg):
    """`1.5MHz` must NOT expand — the M is mid-word (lookahead guard)."""
    assert cqg._expand_si_suffixes("1.5MHz signal") == "1.5MHz signal"


def test_d052_build_numeric_set_collapses_variants(cqg):
    """build_numeric_set collapses scientific / SI / trailing-zero forms
    to a common canonical key."""
    s = cqg.build_numeric_set("values: 82.0, 1.1 x 10^-130, 83K, n=22,751")
    assert "82" in s
    assert "1.1e-130" in s
    assert "83000" in s
    assert "22751" in s


def test_d052_e2e_superscript_grounds(cqg, fixture_dirs):
    """Slide `1.1 x 10^-130`, REPORT `1.1e-130` — grounded, no false
    positive. Pre-D-052 the slide value tokenized into 1.1 / 10 / 130
    and the bare `10` was flagged ungrounded."""
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "The enrichment p-value was 1.1e-130 overall.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "Significance 1.1 x 10^-130",
                        "bullets": ["highly enriched"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    assert report.total_ungrounded == 0


def test_d052_e2e_si_suffix_source_side_grounds(cqg, fixture_dirs):
    """Slide `83,000`, REPORT `83K` — SI expansion is source-side, so the
    REPORT's `83K` grounds the slide's `83,000`."""
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "We generated 83K sequencing reads.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "83,000 reads generated",
                        "bullets": ["deep coverage"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    assert report.total_ungrounded == 0


def test_d052_e2e_trailing_zero_grounds(cqg, fixture_dirs):
    """Slide `82.0`, REPORT `82` — trailing-zero canonicalization grounds
    it. Form 6 (rounding tolerance) misses this case: REPORT has no
    decimal point, so its float scan finds nothing to round."""
    project_dir, talks_dir = fixture_dirs
    _write_report(project_dir, "We profiled 82 organisms in total.")
    _write_spec(talks_dir, [
        {
            "id": 1, "position": 0, "layout": "claim_evidence",
            "content": {"title": "Across 82.0 organisms",
                        "bullets": ["broad sampling"]},
        },
    ])
    report = cqg.check_grounding(talks_dir)
    assert report.total_ungrounded == 0
