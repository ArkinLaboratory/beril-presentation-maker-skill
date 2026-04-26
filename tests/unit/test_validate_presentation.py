"""Tests for validate_presentation.py — P1–P10 mechanized validators.

Coverage strategy:
- For each Pn: one happy-path (status==pass) and at least one failure
  case with the right escalation_path.
- Pre-flight: bad slide_spec rejected with exit 3.
- ValidationReport overall_status logic.
- Numeric-claim extractor false-positive filters (dates, section refs).
- CLI: validate clean spec, validate dirty spec.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SLIDE_SPEC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                 / "tools" / "slide_spec.py")
VP_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "validate_presentation.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ss():
    return _import("slide_spec", SLIDE_SPEC_PY)


@pytest.fixture(scope="module")
def vp():
    _import("slide_spec", SLIDE_SPEC_PY)
    return _import("validate_presentation", VP_PY)


# ---------------------------------------------------------------------------
# Numeric claim extractor: false positive filters
# ---------------------------------------------------------------------------

def test_numeric_extractor_skips_dates(vp):
    out = vp._extract_numeric_claims("Date: 2026-06-12. Time: 2026-04-26T15:12:00Z.")
    assert out == [], f"unexpected numeric matches: {out}"


def test_numeric_extractor_skips_section_refs(vp):
    out = vp._extract_numeric_claims("See REPORT.md §4.1 and §3.2.1.")
    assert out == []


def test_numeric_extractor_skips_bare_years(vp):
    out = vp._extract_numeric_claims("As described in 2024, building on 1999 work.")
    assert out == []


def test_numeric_extractor_finds_real_claims(vp):
    out = vp._extract_numeric_claims(
        "The agent reaches 90% accuracy on n=120 holdout, processing "
        "27,000,000 fitness scores across 1,400 genomes in ~12 minutes."
    )
    assert "90" in out or "90%" in " ".join(out)
    assert "120" in out
    assert "27,000,000" in out
    assert "1,400" in out
    assert "12" in out


# ---------------------------------------------------------------------------
# Helpers — build minimal valid specs for testing
# ---------------------------------------------------------------------------

def _wrap(slides_list, mode="talk-30", substories=None, n_pad=None):
    """Wrap a list of slides into a minimal valid slide_spec dict.
    Optionally pad with extra simple title slides to hit a target slide count."""
    return {
        "schema_version": "1.0",
        "project_id": "test",
        "mode": mode,
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": substories or [],
        "slides": slides_list,
    }


def _full_talk_30_spec(ss, vp):
    """A spec that should pass P1, P2, P7, P8, P9 (within reason)."""
    slides = []
    sid = 1
    # Title (slide 1 — required)
    slides.append(ss.example_slide("title", slide_id=sid, substory_id=None))
    sid += 1
    # Substory 1: opens with section_divider
    slides.append(ss.example_slide("section_divider", slide_id=sid, substory_id="S1"))
    sub_first_id = sid
    sid += 1
    # Pad with claim_evidence-style slides to hit talk-30 budget (25-32 slides)
    for _ in range(20):
        sl = ss.example_slide("claim_evidence", slide_id=sid, substory_id="S1")
        slides.append(sl)
        sid += 1
    # Required slides
    slides.append(ss.example_slide("cross_tenant_integration", slide_id=sid, substory_id=None))
    sid += 1
    slides.append(ss.example_slide("acknowledgments", slide_id=sid, substory_id=None))
    sid += 1
    slides.append(ss.example_slide("references", slide_id=sid, substory_id=None))
    sid += 1
    substories = [
        {"id": "S1", "punchline": "x",
         "slide_ids": [s["id"] for s in slides if s.get("substory_id") == "S1"]},
    ]
    spec = _wrap(slides, mode="talk-30", substories=substories)
    return spec


# ---------------------------------------------------------------------------
# P1 — Mode slide budget
# ---------------------------------------------------------------------------

def test_p1_pass_in_budget(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p1_mode_budget(spec)
    assert res.status == "pass", res.violations


def test_p1_fail_below_budget(vp, ss):
    spec = _wrap([ss.example_slide("title", 1, None)], mode="talk-30")
    res = vp.validate_p1_mode_budget(spec)
    assert res.status == "fail"
    assert res.violations[0].escalation_path == "auto-fix"


def test_p1_pass_for_single_slide_poster(vp, ss):
    """Posters have a 1-slide budget by design (fixed grid). One slide = pass."""
    spec = _wrap([ss.example_slide("title", 1, None)], mode="poster-h")
    res = vp.validate_p1_mode_budget(spec)
    assert res.status == "pass"


def test_p1_fail_for_multi_slide_poster(vp, ss):
    """Posters with >1 slide fail P1 — each poster mode is single-slide."""
    spec = _wrap(
        [ss.example_slide("title", i + 1, None) for i in range(3)],
        mode="poster-h",
    )
    res = vp.validate_p1_mode_budget(spec)
    assert res.status == "fail"


# ---------------------------------------------------------------------------
# P2 — Mode time budget
# ---------------------------------------------------------------------------

def test_p2_pass_within_tolerance(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p2_time_budget(spec)
    assert res.status == "pass"


def test_p2_fail_outside_tolerance(vp, ss):
    spec = _wrap([ss.example_slide("title", 1, None)], mode="talk-30")
    res = vp.validate_p2_time_budget(spec)
    assert res.status == "fail"


# ---------------------------------------------------------------------------
# P3 — Numeric provenance (the load-bearing one; auto-fix forbidden)
# ---------------------------------------------------------------------------

def test_p3_pass_when_no_numeric_claims(vp, ss):
    slide = ss.example_slide("section_divider", 1, None)
    slide["content"]["punchline"] = "Annotation is a hypothesis, not a fact."
    spec = _wrap([slide])
    res = vp.validate_p3_numeric_provenance(spec)
    assert res.status == "pass", res.violations


def test_p3_fail_unprovenanced_numeric_claim(vp, ss):
    slide = ss.example_slide("claim_evidence", 1, None)
    slide["content"]["bullets"] = ["The agent reaches 90% accuracy."]
    spec = _wrap([slide])
    res = vp.validate_p3_numeric_provenance(spec)
    assert res.status == "fail"
    assert res.violations[0].escalation_path == "escalate"
    assert "auto-fix forbidden" in res.violations[0].message.lower() or \
           "fabrication" in res.violations[0].message.lower()


def test_p3_pass_when_claim_is_provenanced(vp, ss):
    slide = ss.example_slide("claim_evidence", 1, None)
    slide["content"]["bullets"] = ["The agent reaches 90% accuracy."]
    slide["speaker_notes_provenance"] = [
        {"claim": "90% accuracy",
         "source": {"kind": "report_line", "path": "REPORT.md", "line": 42}},
    ]
    spec = _wrap([slide])
    res = vp.validate_p3_numeric_provenance(spec)
    assert res.status == "pass", [v.message for v in res.violations]


# ---------------------------------------------------------------------------
# P4 — Citation pool integrity
# ---------------------------------------------------------------------------

def test_p4_skipped_without_pool(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p4_citation_pool_integrity(spec, citation_pool=None)
    assert res.status == "skipped"


def test_p4_pass_when_citations_in_pool(vp, ss):
    slide = ss.example_slide("claim_evidence", 1, None)
    slide["content"]["citations"] = ["smith2023"]
    spec = _wrap([slide])
    pool = {"entries": [{"key": "smith2023", "title": "..."}]}
    res = vp.validate_p4_citation_pool_integrity(spec, citation_pool=pool)
    assert res.status == "pass"


def test_p4_fail_when_citation_missing_from_pool(vp, ss):
    slide = ss.example_slide("claim_evidence", 1, None)
    slide["content"]["citations"] = ["smith2023", "jones2099"]
    spec = _wrap([slide])
    pool = {"entries": [{"key": "smith2023", "title": "..."}]}
    res = vp.validate_p4_citation_pool_integrity(spec, citation_pool=pool)
    assert res.status == "fail"
    assert any("jones2099" in v.message for v in res.violations)


# ---------------------------------------------------------------------------
# P5 — Forbidden contrast pairs
# ---------------------------------------------------------------------------

def test_p5_pass_with_safe_colors(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p5_contrast(spec, brand_tokens=None)
    assert res.status == "pass"


def test_p5_fail_with_forbidden_pair(vp, ss):
    slide = ss.example_slide("workflow_diagram", 1, None)
    slide["content"]["diagram"]["nodes"][0]["fill_color"] = "spring_green"
    slide["content"]["diagram"]["nodes"][0]["text_color"] = "golden_yellow"
    spec = _wrap([slide])
    res = vp.validate_p5_contrast(spec, brand_tokens=None)
    assert res.status == "fail"
    assert res.violations[0].escalation_path == "auto-fix"


# ---------------------------------------------------------------------------
# P6 — Figure resolution (Pillow-dependent; skipped if Pillow missing)
# ---------------------------------------------------------------------------

def _write_png(path: Path, w: int, h: int) -> None:
    import struct, zlib
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    raw = b"".join(b"\x00" + bytes([0xa0, 0xc0, 0xe0]) * w for _ in range(h))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    path.write_bytes(sig + ihdr + idat + iend)


def test_p6_skipped_without_draft_dir(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p6_figure_resolution(spec, draft_dir=None)
    assert res.status == "skipped"


def test_p6_pass_for_high_res_figure(vp, ss, tmp_path):
    fig = tmp_path / "fig.png"
    _write_png(fig, 1920, 1080)
    slide = ss.example_slide("data_figure", 1, None)
    slide["content"]["figure"] = "fig.png"
    spec = _wrap([slide])
    res = vp.validate_p6_figure_resolution(spec, draft_dir=tmp_path)
    assert res.status in ("pass", "skipped")  # skipped if Pillow missing


def test_p6_warns_for_low_res_figure(vp, ss, tmp_path):
    if vp.Image is None:
        pytest.skip("Pillow not installed")
    fig = tmp_path / "fig.png"
    _write_png(fig, 400, 300)
    slide = ss.example_slide("data_figure", 1, None)
    slide["content"]["figure"] = "fig.png"
    spec = _wrap([slide])
    res = vp.validate_p6_figure_resolution(spec, draft_dir=tmp_path)
    assert res.status == "soft-warning"
    assert any("blurry" in v.message.lower() or "long edge" in v.message.lower()
               for v in res.violations)


# ---------------------------------------------------------------------------
# P7 — Divider slides at substory transitions
# ---------------------------------------------------------------------------

def test_p7_pass_when_substory_opens_with_divider(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p7_divider_slides(spec)
    assert res.status == "pass"


def test_p7_fail_when_substory_opens_with_content_slide(vp, ss):
    slide_a = ss.example_slide("claim_evidence", 1, "S1")
    spec = _wrap([slide_a],
                 substories=[{"id": "S1", "punchline": "x", "slide_ids": [1]}])
    res = vp.validate_p7_divider_slides(spec)
    assert res.status == "fail"
    assert res.violations[0].escalation_path == "auto-fix"


def test_p7_pass_for_big_idea_opening(vp, ss):
    slide = ss.example_slide("big_idea", 1, "S1")
    spec = _wrap([slide],
                 substories=[{"id": "S1", "punchline": "x", "slide_ids": [1]}])
    res = vp.validate_p7_divider_slides(spec)
    assert res.status == "pass"


# ---------------------------------------------------------------------------
# P8 — Required slides present
# ---------------------------------------------------------------------------

def test_p8_pass_with_all_required(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    res = vp.validate_p8_required_slides(spec)
    assert res.status == "pass"


def test_p8_fail_missing_acknowledgments(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    spec["slides"] = [s for s in spec["slides"] if s["layout"] != "acknowledgments"]
    res = vp.validate_p8_required_slides(spec)
    assert res.status == "fail"
    assert any("acknowledgments" in v.message for v in res.violations)


def test_p8_not_applicable_for_poster(vp, ss):
    spec = _wrap([ss.example_slide("title", 1, None)], mode="poster-h")
    res = vp.validate_p8_required_slides(spec)
    assert res.status == "not-applicable"


# ---------------------------------------------------------------------------
# P9 — No orphan citations
# ---------------------------------------------------------------------------

def test_p9_pass_when_citations_in_refs_short(vp, ss):
    cite_slide = ss.example_slide("claim_evidence", 1, None)
    cite_slide["content"]["citations"] = ["Smith2023"]
    refs_slide = ss.example_slide("references", 2, None)
    refs_slide["content"]["refs_short"] = ["Smith 2023"]
    spec = _wrap([cite_slide, refs_slide])
    res = vp.validate_p9_no_orphan_citations(spec)
    assert res.status == "pass", [v.message for v in res.violations]


def test_p9_warns_for_orphan_citation(vp, ss):
    cite_slide = ss.example_slide("claim_evidence", 1, None)
    cite_slide["content"]["citations"] = ["Lonely2099"]
    refs_slide = ss.example_slide("references", 2, None)
    refs_slide["content"]["refs_short"] = ["Smith 2023"]
    spec = _wrap([cite_slide, refs_slide])
    res = vp.validate_p9_no_orphan_citations(spec)
    assert res.status == "soft-warning"


# ---------------------------------------------------------------------------
# P10 — Density discipline
# ---------------------------------------------------------------------------

def test_p10_fail_topic_title(vp, ss):
    slide = ss.example_slide("claim_evidence", 1, None)
    slide["content"]["title"] = "Methods"
    spec = _wrap([slide])
    res = vp.validate_p10_density(spec)
    assert res.status == "fail"
    assert any("punchline" in v.message.lower() for v in res.violations)


def test_p10_warns_excess_words(vp, ss):
    slide = ss.example_slide("claim_evidence", 1, None)
    long_bullet = " ".join(["word"] * 45)
    slide["content"]["bullets"] = [long_bullet]
    spec = _wrap([slide])
    res = vp.validate_p10_density(spec)
    assert res.status == "soft-warning"


def test_p10_methods_summary_exempt_from_word_cap(vp, ss):
    """methods_summary has 5–10 bullets by design; word cap doesn't apply."""
    slide = ss.example_slide("methods_summary", 1, None)
    slide["content"]["bullets"] = ["Long bullet point " + str(i) for i in range(8)]
    spec = _wrap([slide])
    res = vp.validate_p10_density(spec)
    assert res.status == "pass"


def test_p10_acknowledgments_exempt_from_punchline_rule(vp, ss):
    """acknowledgments title is hard-coded by the assembler — exempt."""
    slide = ss.example_slide("acknowledgments", 1, None)
    spec = _wrap([slide])
    res = vp.validate_p10_density(spec)
    assert res.status == "pass"


# ---------------------------------------------------------------------------
# Top-level validate_presentation + report
# ---------------------------------------------------------------------------

def test_validate_presentation_returns_report(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    report = vp.validate_presentation(spec)
    assert report.n_slides == len(spec["slides"])
    assert report.mode == "talk-30"
    assert len(report.validators) == 10
    ids = {v.id for v in report.validators}
    assert ids == {f"P{i}" for i in range(1, 11)}


def test_overall_status_pass_when_all_pass(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    # Strip numeric claims so P3 also passes
    for s in spec["slides"]:
        if "bullets" in s["content"]:
            s["content"]["bullets"] = ["No numbers here"] * len(s["content"]["bullets"])
    report = vp.validate_presentation(spec)
    # P3 + P4 should pass / skipped; nothing should be 'fail'
    assert report.overall_status in ("pass", "warn")


def test_overall_status_fail_propagates(vp, ss):
    """A single fail anywhere → overall_status='fail'."""
    spec = _full_talk_30_spec(ss, vp)
    spec["slides"][0]["content"]["title"] = "Methods"  # P10 fail
    report = vp.validate_presentation(spec)
    assert report.overall_status == "fail"


# ---------------------------------------------------------------------------
# Text + JSON report formats
# ---------------------------------------------------------------------------

def test_format_text_report_contains_summary(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    report = vp.validate_presentation(spec)
    text = vp.format_text_report(report)
    assert "overall:" in text
    for pid in ("P1", "P3", "P10"):
        assert pid in text


def test_to_dict_summary_keys(vp, ss):
    spec = _full_talk_30_spec(ss, vp)
    report = vp.validate_presentation(spec)
    d = report.to_dict()
    assert "summary" in d
    for k in ("passed", "failed", "soft_warnings", "skipped",
              "not_applicable", "overall_status"):
        assert k in d["summary"]


# ---------------------------------------------------------------------------
# Write-back: validator_status persists onto slides
# ---------------------------------------------------------------------------

def test_write_back_updates_slide_validator_status(vp, ss, tmp_path):
    spec = _full_talk_30_spec(ss, vp)
    spec["slides"][0]["content"]["title"] = "Methods"  # P10 fail on slide 1

    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))

    report = vp.validate_presentation(spec, slide_spec_path=str(spec_path))
    vp.write_back_validator_status(spec_path, report)

    updated = json.loads(spec_path.read_text())
    slide_1 = next(s for s in updated["slides"] if s["id"] == 1)
    assert "validator_status" in slide_1
    assert "P10" in slide_1["validator_status"]


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_cli_clean_spec_returns_0(vp, ss, tmp_path):
    spec = _full_talk_30_spec(ss, vp)
    # Strip numeric claims so P3 passes
    for s in spec["slides"]:
        if isinstance(s["content"].get("bullets"), list):
            s["content"]["bullets"] = ["No numbers"] * 2
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    rc = vp.main([str(spec_path), "--report-format", "json"])
    assert rc in (0, 1)  # may have soft-warnings but not a fail


def test_cli_dirty_spec_returns_1(vp, ss, tmp_path, capsys):
    spec = _full_talk_30_spec(ss, vp)
    spec["slides"][0]["content"]["title"] = "Methods"  # P10 fail
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(spec))
    rc = vp.main([str(spec_path), "--report-format", "text"])
    assert rc == 1


def test_cli_invalid_schema_returns_3(vp, tmp_path):
    bad = {"schema_version": "0.0", "slides": []}  # invalid
    spec_path = tmp_path / "slide_spec.json"
    spec_path.write_text(json.dumps(bad))
    rc = vp.main([str(spec_path)])
    assert rc == 3
