"""Unit tests for tools/merge_visual_qa_into_review.py (v0.8 Tier G.7).

Verifies visual-QA findings are correctly converted to adversarial-
shape entries with the right class + severity mapping, summary is
recomputed, dedup behavior is correct on re-runs, and the writer
preserves the original adversarial_review.json structure.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "merge_visual_qa_into_review.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def merger():
    return _import("merge_visual_qa_into_review", TOOL_PY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def _minimal_review(findings=()):
    return {
        "schema_version": "adversarial-review.v3",
        "tier": "STRONG",
        "verdict": "PASS",
        "findings": list(findings),
        "summary": {
            "by_severity": {},
            "by_class": {},
        },
    }


def _minimal_visual_qa(findings):
    return {
        "schema_version": "visual-qa.v1",
        "n_slides_reviewed": 30,
        "findings": list(findings),
    }


def _minimal_spec(slide_layouts):
    return {
        "schema_version": "1.0",
        "slides": [
            {"id": sid, "layout": layout, "content": {}}
            for sid, layout in slide_layouts.items()
        ],
    }


# ---------------------------------------------------------------------------
# Class + severity mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vq_kind,expected_class", [
    ("illegible_scale", "register_drift"),
    ("container_breach", "register_drift"),
    ("element_overlap", "register_drift"),
    ("footer_or_title_collision", "register_drift"),
    ("headline_body_mismatch", "claim_evidence"),
])
def test_vq_kind_class_mapping(merger, tmp_path, vq_kind, expected_class):
    """Each visual-QA kind maps to the documented adversarial class."""
    vq = _minimal_visual_qa([{
        "slide_id": 5,
        "kind": vq_kind,
        "severity": "warning",
        "confidence": "high",
        "detail": "example detail",
        "evidence_locator": "x",
    }])
    review = _minimal_review()
    spec = _minimal_spec({5: "claim_evidence"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    assert len(updated["findings"]) == 1
    f = updated["findings"][0]
    assert f["class"] == expected_class
    assert f["_visual_qa_origin"]["kind"] == vq_kind


@pytest.mark.parametrize("confidence,expected_severity", [
    ("high", "P1"),
    ("medium", "P2"),
    ("low", "P2"),
])
def test_confidence_severity_mapping(merger, tmp_path,
                                      confidence, expected_severity):
    """confidence=high → P1; medium|low → P2 (per spec)."""
    vq = _minimal_visual_qa([{
        "slide_id": 5,
        "kind": "illegible_scale",
        "severity": "warning",
        "confidence": confidence,
        "detail": "example",
        "evidence_locator": "x",
    }])
    review = _minimal_review()
    spec = _minimal_spec({5: "data_figure"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    assert updated["findings"][0]["severity"] == expected_severity


# ---------------------------------------------------------------------------
# Synthetic-id generation
# ---------------------------------------------------------------------------

def test_vq_ids_start_at_vq001_when_no_existing(merger, tmp_path):
    """When the review has no existing VQ-id findings, new ones
    start at VQ001."""
    vq = _minimal_visual_qa([
        {"slide_id": 1, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d1", "evidence_locator": ""},
        {"slide_id": 2, "kind": "container_breach", "severity": "warning",
         "confidence": "medium", "detail": "d2", "evidence_locator": ""},
    ])
    review = _minimal_review()
    spec = _minimal_spec({1: "data_figure", 2: "claim_evidence"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    ids = [f["id"] for f in updated["findings"]]
    assert ids == ["VQ001", "VQ002"]


def test_vq_ids_continue_after_existing(merger, tmp_path):
    """When the review already has VQ005, a new finding gets VQ006."""
    review = _minimal_review([
        {"id": "VQ005", "class": "register_drift", "severity": "P1",
         "confidence": "high", "slide_id": 99, "issue": "old",
         "_visual_qa_origin": {"kind": "illegible_scale", "evidence_locator": ""}},
    ])
    vq = _minimal_visual_qa([
        {"slide_id": 7, "kind": "container_breach", "severity": "warning",
         "confidence": "high", "detail": "new finding", "evidence_locator": ""},
    ])
    spec = _minimal_spec({7: "data_figure"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    new_finding = next(f for f in updated["findings"]
                       if f["slide_id"] == 7)
    assert new_finding["id"] == "VQ006"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_on_re_run(merger, tmp_path):
    """Running the merger twice with the same visual-QA input should
    NOT duplicate findings."""
    vq = _minimal_visual_qa([
        {"slide_id": 5, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high",
         "detail": "the same finding text", "evidence_locator": ""},
    ])
    review = _minimal_review()
    spec = _minimal_spec({5: "data_figure"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    n1, _ = merger.merge(vq_path, rev_path, spec_path)
    n2, dup = merger.merge(vq_path, rev_path, spec_path)
    assert n1 == 1
    assert n2 == 0
    assert dup == 1
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    # Still only one finding total
    assert len(updated["findings"]) == 1


# ---------------------------------------------------------------------------
# Summary recomputation
# ---------------------------------------------------------------------------

def test_summary_recomputed_after_merge(merger, tmp_path):
    """summary.by_severity + by_class get accurate counts after
    merger appends new findings."""
    review = _minimal_review([
        {"id": "F001", "class": "throughline", "severity": "P0",
         "slide_id": 1, "issue": "x"},
    ])
    vq = _minimal_visual_qa([
        {"slide_id": 2, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d1", "evidence_locator": ""},
        {"slide_id": 3, "kind": "illegible_scale", "severity": "warning",
         "confidence": "medium", "detail": "d2", "evidence_locator": ""},
        {"slide_id": 4, "kind": "headline_body_mismatch", "severity": "warning",
         "confidence": "high", "detail": "d3", "evidence_locator": ""},
    ])
    spec = _minimal_spec({1: "title", 2: "data_figure", 3: "data_figure",
                          4: "claim_evidence"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    summary = updated["summary"]
    # 1 P0 (F001) + 2 P1 (illegible_scale high + headline_body high)
    # + 1 P2 (illegible_scale medium)
    assert summary["by_severity"] == {"P0": 1, "P1": 2, "P2": 1}
    # F001=throughline; 2× register_drift (illegibles);
    # 1× claim_evidence (headline_body_mismatch)
    assert summary["by_class"] == {
        "throughline": 1,
        "register_drift": 2,
        "claim_evidence": 1,
    }


# ---------------------------------------------------------------------------
# Slide layout enrichment
# ---------------------------------------------------------------------------

def test_slide_layout_populated_from_spec(merger, tmp_path):
    """The synthetic finding's slide_layout field should reflect the
    actual slide_spec.json layout, so revise_slide.v1 knows what
    layout it's editing."""
    vq = _minimal_visual_qa([
        {"slide_id": 12, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d", "evidence_locator": ""},
    ])
    review = _minimal_review()
    spec = _minimal_spec({12: "qa_anticipated"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    assert updated["findings"][0]["slide_layout"] == "qa_anticipated"


def test_unknown_slide_layout_when_spec_lacks_slide(merger, tmp_path):
    """If the visual-QA finding's slide_id isn't in slide_spec.json,
    slide_layout falls back to 'unknown' (defensive)."""
    vq = _minimal_visual_qa([
        {"slide_id": 999, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d", "evidence_locator": ""},
    ])
    review = _minimal_review()
    spec = _minimal_spec({1: "title"})  # no slide 999
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    merger.merge(vq_path, rev_path, spec_path)
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    assert updated["findings"][0]["slide_layout"] == "unknown"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_visual_qa_findings_no_op(merger, tmp_path):
    """No visual-QA findings → merger is a no-op; review unchanged."""
    vq = _minimal_visual_qa([])
    original_review = _minimal_review([
        {"id": "F001", "class": "throughline", "severity": "P0",
         "slide_id": 1, "issue": "x"},
    ])
    spec = _minimal_spec({1: "title"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", original_review)
    spec_path = _write(tmp_path, "spec.json", spec)
    n_added, n_dup = merger.merge(vq_path, rev_path, spec_path)
    assert n_added == 0
    assert n_dup == 0
    updated = json.loads(rev_path.read_text(encoding="utf-8"))
    # Original finding preserved
    assert len(updated["findings"]) == 1
    assert updated["findings"][0]["id"] == "F001"


def test_missing_review_file_raises(merger, tmp_path):
    vq = _minimal_visual_qa([])
    vq_path = _write(tmp_path, "vq.json", vq)
    with pytest.raises(FileNotFoundError):
        merger.merge(vq_path, tmp_path / "no_review.json",
                     tmp_path / "no_spec.json")


def test_missing_visual_qa_file_raises(merger, tmp_path):
    review = _minimal_review()
    rev_path = _write(tmp_path, "rev.json", review)
    with pytest.raises(FileNotFoundError):
        merger.merge(tmp_path / "no_vq.json", rev_path,
                     tmp_path / "no_spec.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_missing_visual_qa_returns_0(merger, tmp_path):
    """Per spec: when visual_qa_final.json is missing, the CLI
    returns 0 (not an error) — caller may invoke speculatively."""
    draft = tmp_path / "draft_X"
    (draft / "audit").mkdir(parents=True)
    (draft / "working").mkdir()
    # Write a stub adversarial_review.json so we get past the
    # review-file-required check
    _write(draft / "audit", "adversarial_review.json", _minimal_review())
    rc = merger.main(["--draft-dir", str(draft)])
    assert rc == 0


def test_cli_writes_findings_to_review(merger, tmp_path):
    """End-to-end CLI: --draft-dir resolves all paths + merger writes
    the augmented adversarial_review.json."""
    draft = tmp_path / "draft_X"
    (draft / "audit").mkdir(parents=True)
    (draft / "working").mkdir()
    _write(draft / "audit", "visual_qa_final.json",
           _minimal_visual_qa([
               {"slide_id": 1, "kind": "illegible_scale",
                "severity": "warning", "confidence": "high",
                "detail": "d", "evidence_locator": ""},
           ]))
    _write(draft / "audit", "adversarial_review.json", _minimal_review())
    _write(draft / "working", "slide_spec.json",
           _minimal_spec({1: "data_figure"}))
    rc = merger.main(["--draft-dir", str(draft)])
    assert rc == 0
    augmented = json.loads(
        (draft / "audit" / "adversarial_review.json").read_text(
            encoding="utf-8"))
    assert len(augmented["findings"]) == 1
    assert augmented["findings"][0]["id"] == "VQ001"
