"""Tests for check_substory_shape.py — v0.5 Tier B / D-071 + D-073.

Coverage:
- Field extraction from 02_substories.md (v1/v2-shape, v3-shape with
  Question + Conclusion fields)
- Slide inventory per substory (substory_id → [(slide_id, layout)])
- Per-substory shape check (Q/A/R/C presence; word-count caps)
- Last-substory exemption (no Conclusion field required)
- Empty-substory handling
- Defensive: missing 02_substories.md / missing slide_spec.json
- Full check_substory_shape orchestration
- Text report rendering
- CLI happy + sad paths
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
          / "tools" / "check_substory_shape.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def css():
    return _import("check_substory_shape", CSS_PY)


# Substory markdown fixtures
SUBSTORIES_V1_SHAPE = """\
# Substory clusters — `test_project` / talk mode `talk-30`

**Throughline:** the throughline claim.

## Substory clusters

### S1 — First cluster

**Punchline:** S1's punchline goes here.

**Critical analyses covered:**

- A1: foo

### S2 — Second cluster

**Punchline:** S2's punchline.

### S3 — Third (last) cluster

**Punchline:** S3's punchline.
"""

SUBSTORIES_V3_SHAPE = """\
# Substory clusters — `test_project` / talk mode `talk-30`

**Throughline:** the throughline claim.

## Substory clusters

### S1 — First cluster

**Question:** What is the first question?

**Conclusion for next substory:** This answers part of the puzzle and motivates S2.

**Punchline:** S1's punchline.

### S2 — Second cluster

**Question:** What is the second question?

**Conclusion for next substory:** This builds toward the final conclusion in S3.

**Punchline:** S2's punchline.

### S3 — Third (last) cluster

**Question:** What does it all mean together?

**Punchline:** S3's punchline.
"""


def _spec_with_slides(slides: list[dict]) -> dict:
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


def _slide(sid, layout, substory_id=None):
    """Build a minimal slide dict for shape-checking."""
    content = {"title": f"Slide {sid}"}
    if layout == "data_figure":
        content.update({"figure": "fig.png", "caption": "c"})
    return {"id": sid, "substory_id": substory_id, "layout": layout,
            "content": content}


# ---------------------------------------------------------------------------
# extract_substory_fields
# ---------------------------------------------------------------------------

def test_extract_fields_v1_shape_returns_punchline_only(css):
    """v1/v2-shape input has Punchline but NO Question or Conclusion."""
    metas = css.extract_substory_fields(SUBSTORIES_V1_SHAPE)
    assert len(metas) == 3
    for m in metas:
        assert m["question"] is None
        assert m["conclusion_for_next"] is None
        assert m["punchline"] is not None


def test_extract_fields_v3_shape_returns_question_and_conclusion(css):
    """v3-shape (per D-071) input has Question + Conclusion fields."""
    metas = css.extract_substory_fields(SUBSTORIES_V3_SHAPE)
    assert len(metas) == 3
    s1 = metas[0]
    assert s1["question"] == "What is the first question?"
    assert s1["conclusion_for_next"] == (
        "This answers part of the puzzle and motivates S2.")
    assert s1["punchline"] == "S1's punchline."
    # Last substory has Question but NO conclusion (per D-071 — last
    # substory's conclusion is implicit in the throughline)
    s3 = metas[2]
    assert s3["question"] == "What does it all mean together?"
    assert s3["conclusion_for_next"] is None


def test_extract_fields_handles_alternative_field_names(css):
    """Accept Hands off to / Next substory / Scientific question variants."""
    text = """\
### S1 — A cluster

**Scientific question:** Variant 1 of question.

**Hands off to:** Variant 1 of conclusion.

**Punchline:** P.
"""
    metas = css.extract_substory_fields(text)
    assert metas[0]["question"] == "Variant 1 of question."
    assert metas[0]["conclusion_for_next"] == "Variant 1 of conclusion."


# ---------------------------------------------------------------------------
# inventory_slides_per_substory
# ---------------------------------------------------------------------------

def test_inventory_groups_slides_by_substory_id(css):
    spec = _spec_with_slides([
        _slide(1, "title", None),  # no substory_id; excluded
        _slide(2, "section_divider", "S1"),
        _slide(3, "claim_evidence", "S1"),
        _slide(4, "section_divider", "S2"),
        _slide(5, "data_figure", "S2"),
        _slide(6, "references", None),  # excluded
    ])
    out = css.inventory_slides_per_substory(spec, ["S1", "S2"])
    assert out["S1"] == [(2, "section_divider"), (3, "claim_evidence")]
    assert out["S2"] == [(4, "section_divider"), (5, "data_figure")]


def test_inventory_returns_empty_list_for_substory_with_no_slides(css):
    spec = _spec_with_slides([_slide(1, "title", None)])
    out = css.inventory_slides_per_substory(spec, ["S1"])
    assert out["S1"] == []


# ---------------------------------------------------------------------------
# Per-substory checker
# ---------------------------------------------------------------------------

def test_check_v3_clean_substory_emits_zero_findings(css):
    """A substory with Q + Conclusion + Q-slide + R-slide + C-slide → 0 findings."""
    meta = {
        "substory_id": "S1",
        "title": "Clean substory",
        "question": "What is the question?",
        "conclusion_for_next": "Hand off to S2.",
        "punchline": "P",
    }
    slides = [
        (1, "section_divider"),  # Q-slide
        (2, "data_figure"),      # R-slide
        (3, "claim_evidence"),   # C-slide
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    assert findings == []
    assert record.has_q_slide is True
    assert record.has_r_slide is True
    assert record.has_c_slide is True


def test_check_v1_substory_emits_missing_question_and_conclusion(css):
    """A v1-shape substory (no Question/Conclusion fields) emits
    missing_question + missing_conclusion."""
    meta = {
        "substory_id": "S1",
        "title": "v1-shape substory",
        "question": None,
        "conclusion_for_next": None,
        "punchline": "P",
    }
    slides = [
        (1, "section_divider"),
        (2, "data_figure"),
        (3, "claim_evidence"),
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    kinds = [f.kind for f in findings]
    assert "missing_question" in kinds
    assert "missing_conclusion" in kinds
    # All P1 per D-073
    assert all(f.severity == "P1" for f in findings)


def test_check_last_substory_is_exempt_from_conclusion_requirement(css):
    """Last substory (is_last=True) doesn't need conclusion_for_next."""
    meta = {
        "substory_id": "S3",
        "title": "Last substory",
        "question": "What does it all mean?",
        "conclusion_for_next": None,  # no handoff — last substory
        "punchline": "P",
    }
    slides = [
        (1, "section_divider"),
        (2, "data_figure"),
        (3, "claim_evidence"),
    ]
    record, findings = css.check_substory(meta, slides, is_last=True)
    # missing_conclusion must NOT appear for last substory
    kinds = [f.kind for f in findings]
    assert "missing_conclusion" not in kinds


def test_check_emits_question_too_long_when_over_word_cap(css):
    """≤25 words per D-071; over → question_too_long."""
    long_q = " ".join([f"word{i}" for i in range(30)])
    meta = {
        "substory_id": "S1",
        "title": "Long-q substory",
        "question": long_q,
        "conclusion_for_next": "Short.",
        "punchline": "P",
    }
    slides = [
        (1, "section_divider"),
        (2, "data_figure"),
        (3, "claim_evidence"),
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    kinds = [f.kind for f in findings]
    assert "question_too_long" in kinds


def test_check_emits_conclusion_too_long_when_over_word_cap(css):
    long_c = " ".join([f"word{i}" for i in range(30)])
    meta = {
        "substory_id": "S1",
        "title": "Long-c substory",
        "question": "Short?",
        "conclusion_for_next": long_c,
        "punchline": "P",
    }
    slides = [
        (1, "section_divider"),
        (2, "data_figure"),
        (3, "claim_evidence"),
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    kinds = [f.kind for f in findings]
    assert "conclusion_too_long" in kinds


def test_check_emits_missing_q_slide(css):
    """Substory without a section_divider/big_idea → missing_q_slide."""
    meta = {"substory_id": "S1", "title": "T", "question": "Q?",
            "conclusion_for_next": "C.", "punchline": "P"}
    slides = [
        (1, "data_figure"),    # no Q-slide
        (2, "claim_evidence"),
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    kinds = [f.kind for f in findings]
    assert "missing_q_slide" in kinds
    assert record.has_q_slide is False


def test_check_emits_missing_r_slide(css):
    """Substory without data_figure/data_table/big_number/etc. →
    missing_r_slide."""
    meta = {"substory_id": "S1", "title": "T", "question": "Q?",
            "conclusion_for_next": "C.", "punchline": "P"}
    slides = [
        (1, "section_divider"),  # Q
        (2, "claim_evidence"),   # C; no R-slide
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    kinds = [f.kind for f in findings]
    assert "missing_r_slide" in kinds


def test_check_emits_missing_c_slide(css):
    """Substory without claim_evidence/big_idea closing → missing_c_slide."""
    meta = {"substory_id": "S1", "title": "T", "question": "Q?",
            "conclusion_for_next": "C.", "punchline": "P"}
    slides = [
        (1, "section_divider"),
        (2, "data_figure"),
        (3, "data_table"),  # all R; no C-slide
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    kinds = [f.kind for f in findings]
    assert "missing_c_slide" in kinds


def test_check_empty_substory_emits_substory_has_no_slides(css):
    """A substory declared in 02_substories.md but with no slides
    assigned in slide_spec.json → substory_has_no_slides; skip
    further checks."""
    meta = {"substory_id": "S1", "title": "Orphan", "question": "Q?",
            "conclusion_for_next": "C.", "punchline": "P"}
    record, findings = css.check_substory(meta, [], is_last=False)
    kinds = [f.kind for f in findings]
    assert "substory_has_no_slides" in kinds
    # No other shape findings (skipped — nothing to validate)
    assert "missing_q_slide" not in kinds
    assert "missing_r_slide" not in kinds


def test_big_idea_can_serve_as_both_q_and_c(css):
    """big_idea is in both Q_SLIDE_LAYOUTS and C_SLIDE_LAYOUTS — a
    substory that opens AND closes on big_idea satisfies both."""
    meta = {"substory_id": "S1", "title": "T", "question": "Q?",
            "conclusion_for_next": "C.", "punchline": "P"}
    slides = [
        (1, "big_idea"),
        (2, "data_figure"),
        (3, "big_idea"),  # also acceptable as closing
    ]
    record, findings = css.check_substory(meta, slides, is_last=False)
    # No shape findings — Q✓ R✓ C✓ all satisfied
    shape_kinds = [f.kind for f in findings if f.kind.startswith("missing_")]
    assert shape_kinds == []


# ---------------------------------------------------------------------------
# check_substory_shape orchestration
# ---------------------------------------------------------------------------

def test_orchestration_loads_inputs_and_returns_report(css, tmp_path):
    """End-to-end: build a draft_dir layout + run check_substory_shape."""
    # Build draft directory structure
    draft = tmp_path / "draft_1"
    (draft / "narrative").mkdir(parents=True)
    (draft / "working").mkdir(parents=True)
    (draft / "narrative" / "02_substories.md").write_text(
        SUBSTORIES_V3_SHAPE, encoding="utf-8")
    spec = _spec_with_slides([
        _slide(1, "title", None),
        _slide(2, "section_divider", "S1"),
        _slide(3, "data_figure", "S1"),
        _slide(4, "claim_evidence", "S1"),
        _slide(5, "section_divider", "S2"),
        _slide(6, "data_figure", "S2"),
        _slide(7, "claim_evidence", "S2"),
        _slide(8, "section_divider", "S3"),
        _slide(9, "data_figure", "S3"),
        _slide(10, "claim_evidence", "S3"),
    ])
    (draft / "working" / "slide_spec.json").write_text(
        json.dumps(spec), encoding="utf-8")
    report = css.check_substory_shape(draft)
    assert report.schema_version == "substory-shape.v1"
    assert report.n_substories == 3
    # All 3 substories well-shaped (v3 + Q/A/R/C present) → 0 findings
    assert report.findings == []


def test_orchestration_missing_substories_file_emits_global_finding(
        css, tmp_path):
    draft = tmp_path / "draft_1"
    draft.mkdir()
    report = css.check_substory_shape(draft)
    assert report.n_substories == 0
    assert len(report.findings) == 1
    assert report.findings[0].kind == "missing_input"
    assert report.findings[0].substory_id == "(global)"


def test_orchestration_missing_slide_spec_emits_global_finding(
        css, tmp_path):
    draft = tmp_path / "draft_1"
    (draft / "narrative").mkdir(parents=True)
    (draft / "narrative" / "02_substories.md").write_text(
        SUBSTORIES_V3_SHAPE, encoding="utf-8")
    # No working/slide_spec.json
    report = css.check_substory_shape(draft)
    assert report.n_substories == 0
    assert any(f.kind == "missing_input" for f in report.findings)


def test_orchestration_v1_shape_substories_emits_missing_fields(
        css, tmp_path):
    """Running against a v1-shape substory list (today's M6 drafts)
    emits missing_question + missing_conclusion for each substory."""
    draft = tmp_path / "draft_1"
    (draft / "narrative").mkdir(parents=True)
    (draft / "working").mkdir(parents=True)
    (draft / "narrative" / "02_substories.md").write_text(
        SUBSTORIES_V1_SHAPE, encoding="utf-8")
    spec = _spec_with_slides([
        _slide(1, "section_divider", "S1"),
        _slide(2, "data_figure", "S1"),
        _slide(3, "claim_evidence", "S1"),
        _slide(4, "section_divider", "S2"),
        _slide(5, "data_figure", "S2"),
        _slide(6, "claim_evidence", "S2"),
        _slide(7, "section_divider", "S3"),
        _slide(8, "data_figure", "S3"),
        _slide(9, "claim_evidence", "S3"),
    ])
    (draft / "working" / "slide_spec.json").write_text(
        json.dumps(spec), encoding="utf-8")
    report = css.check_substory_shape(draft)
    # 3 substories × missing_question + 2 (non-last) × missing_conclusion = 5
    by_kind: dict[str, int] = {}
    for f in report.findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    assert by_kind.get("missing_question") == 3
    assert by_kind.get("missing_conclusion") == 2  # S1 + S2 only


# ---------------------------------------------------------------------------
# Text report rendering
# ---------------------------------------------------------------------------

def test_text_report_clean_says_clean(css, tmp_path):
    draft = tmp_path / "draft_1"
    (draft / "narrative").mkdir(parents=True)
    (draft / "working").mkdir(parents=True)
    (draft / "narrative" / "02_substories.md").write_text(
        SUBSTORIES_V3_SHAPE, encoding="utf-8")
    spec = _spec_with_slides([
        _slide(1, "section_divider", "S1"),
        _slide(2, "data_figure", "S1"),
        _slide(3, "claim_evidence", "S1"),
        _slide(4, "section_divider", "S2"),
        _slide(5, "data_figure", "S2"),
        _slide(6, "claim_evidence", "S2"),
        _slide(7, "section_divider", "S3"),
        _slide(8, "data_figure", "S3"),
        _slide(9, "claim_evidence", "S3"),
    ])
    (draft / "working" / "slide_spec.json").write_text(
        json.dumps(spec), encoding="utf-8")
    report = css.check_substory_shape(draft)
    text = css.format_text_report(report)
    assert "Clean" in text


def test_text_report_includes_schema_version(css, tmp_path):
    draft = tmp_path / "draft_1"
    draft.mkdir()
    report = css.check_substory_shape(draft)  # missing inputs
    text = css.format_text_report(report)
    assert "substory-shape.v1" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_missing_draft_dir_returns_2(css, tmp_path):
    rc = css.main(["--draft-dir", str(tmp_path / "does-not-exist")])
    assert rc == 2


def test_cli_writes_json_to_default_audit_path(css, tmp_path):
    draft = tmp_path / "draft_1"
    (draft / "narrative").mkdir(parents=True)
    (draft / "working").mkdir(parents=True)
    (draft / "narrative" / "02_substories.md").write_text(
        SUBSTORIES_V3_SHAPE, encoding="utf-8")
    spec = _spec_with_slides([
        _slide(1, "section_divider", "S1"),
        _slide(2, "data_figure", "S1"),
        _slide(3, "claim_evidence", "S1"),
    ])
    (draft / "working" / "slide_spec.json").write_text(
        json.dumps(spec), encoding="utf-8")
    rc = css.main(["--draft-dir", str(draft), "--report-format", "json"])
    assert rc == 0
    out = draft / "audit" / "substory_shape.json"
    assert out.is_file()
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == "substory-shape.v1"


def test_cli_text_to_stdout(css, tmp_path, capsys):
    draft = tmp_path / "draft_1"
    draft.mkdir()
    # Will emit missing-input finding; just confirm text format renders
    rc = css.main(["--draft-dir", str(draft), "--report-format", "text"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "substory-shape.v1" in out


def test_cli_text_to_file(css, tmp_path):
    draft = tmp_path / "draft_1"
    draft.mkdir()
    out = tmp_path / "report.md"
    rc = css.main(["--draft-dir", str(draft), "--out", str(out)])
    assert rc == 0
    assert "substory-shape.v1" in out.read_text()
