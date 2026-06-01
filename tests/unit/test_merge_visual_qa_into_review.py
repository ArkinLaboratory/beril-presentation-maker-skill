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


# ===========================================================================
# v0.8 Tier G.8 — standalone VQ-only review for 2nd revise pass
# ===========================================================================
#
# Live finding on draft_12: 2nd revise pass re-iterated the original
# F-prefixed adversarial findings + hit max_revisions=6 cap before
# reaching any VQ-prefixed visual-QA finding. The visual-QA fixes
# were architecturally plumbed but never actually applied to slides.
#
# G.8 fix: merge() now also writes a STANDALONE adversarial-review-
# shaped JSON containing ONLY the synthetic VQ findings (via the
# new vq_only_review_path arg / --vq-only-review CLI flag). The
# orchestrator's 2nd revise pass reads that file via --review-path
# so it has its own max_revisions budget and ONLY iterates VQ
# findings.


def test_g8_writes_standalone_vq_only_review(merger, tmp_path):
    """When vq_only_review_path is supplied, merge writes a
    standalone adversarial-review-shaped JSON with ONLY VQ findings."""
    vq = _minimal_visual_qa([
        {"slide_id": 5, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d1", "evidence_locator": ""},
        {"slide_id": 7, "kind": "headline_body_mismatch", "severity": "warning",
         "confidence": "medium", "detail": "d2", "evidence_locator": ""},
    ])
    # Pre-existing review has F-prefixed findings that should NOT
    # appear in the VQ-only standalone output
    review = _minimal_review([
        {"id": "F001", "class": "throughline", "severity": "P0",
         "slide_id": 1, "issue": "original"},
        {"id": "F002", "class": "register_drift", "severity": "P1",
         "slide_id": 2, "issue": "another original"},
    ])
    spec = _minimal_spec({5: "data_figure", 7: "claim_evidence"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    vq_only_path = tmp_path / "vq_only.json"

    n_added, _ = merger.merge(
        vq_path, rev_path, spec_path,
        vq_only_review_path=vq_only_path)
    assert n_added == 2

    # Standalone file exists + contains ONLY the VQ findings
    assert vq_only_path.is_file()
    vq_only = json.loads(vq_only_path.read_text(encoding="utf-8"))
    assert len(vq_only["findings"]) == 2, (
        f"VQ-only file must contain ONLY the synthetic VQ findings; "
        f"got: {[f['id'] for f in vq_only['findings']]}")
    assert all(f["id"].startswith("VQ") for f in vq_only["findings"]), (
        f"all findings in VQ-only file must be VQ-prefixed; got: "
        f"{[f['id'] for f in vq_only['findings']]}")

    # Original review STILL has both F-findings AND new VQ findings
    # (G.8 doesn't break the cascade-reader path)
    merged = json.loads(rev_path.read_text(encoding="utf-8"))
    assert len(merged["findings"]) == 4  # 2 F + 2 VQ
    f_ids = {f["id"] for f in merged["findings"]}
    assert {"F001", "F002", "VQ001", "VQ002"}.issubset(f_ids)


def test_g8_vq_only_review_has_adversarial_review_envelope(merger, tmp_path):
    """The standalone VQ-only file must have the adversarial-review
    schema fields (tier, verdict, summary, findings) so revise_loop.py
    can read it without crashing on missing fields."""
    vq = _minimal_visual_qa([
        {"slide_id": 5, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d", "evidence_locator": ""},
    ])
    review = _minimal_review()
    review["tier"] = "STRONG"
    spec = _minimal_spec({5: "data_figure"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    vq_only_path = tmp_path / "vq_only.json"

    merger.merge(vq_path, rev_path, spec_path,
                 vq_only_review_path=vq_only_path)

    vq_only = json.loads(vq_only_path.read_text(encoding="utf-8"))
    # Required envelope fields
    assert "schema_version" in vq_only
    assert "tier" in vq_only and vq_only["tier"] == "STRONG"
    assert "verdict" in vq_only
    assert "findings" in vq_only
    assert "summary" in vq_only
    # Summary is recomputed from the VQ-only findings (NOT from the
    # full merged review)
    summary = vq_only["summary"]
    assert "by_severity" in summary
    assert "by_class" in summary
    # One P1 register_drift (illegible_scale high → P1 register_drift)
    assert summary["by_severity"] == {"P1": 1}
    assert summary["by_class"] == {"register_drift": 1}


def test_g8_vq_only_review_origin_marker(merger, tmp_path):
    """The standalone file must carry an _origin field naming Tier G.8
    so downstream consumers / forensic readers know which file produced
    them (vs the main adversarial_review.json)."""
    vq = _minimal_visual_qa([
        {"slide_id": 1, "kind": "illegible_scale", "severity": "warning",
         "confidence": "high", "detail": "d", "evidence_locator": ""},
    ])
    review = _minimal_review()
    spec = _minimal_spec({1: "data_figure"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    vq_only_path = tmp_path / "vq_only.json"

    merger.merge(vq_path, rev_path, spec_path,
                 vq_only_review_path=vq_only_path)

    vq_only = json.loads(vq_only_path.read_text(encoding="utf-8"))
    assert "_origin" in vq_only
    assert "G.8" in vq_only["_origin"] or "Tier G.8" in vq_only["_origin"]


def test_g8_empty_visual_qa_still_writes_empty_standalone(merger, tmp_path):
    """Defensive: when visual-QA had zero findings, the merger still
    writes an empty VQ-only file (with findings=[]) so the orchestrator's
    2nd-revise-pass invocation has a stable artifact to read. Without
    this, revise_loop.py crashes on missing --review-path."""
    vq = _minimal_visual_qa([])  # zero findings
    review = _minimal_review([
        {"id": "F001", "class": "throughline", "severity": "P0",
         "slide_id": 1, "issue": "x"},
    ])
    spec = _minimal_spec({1: "title"})
    vq_path = _write(tmp_path, "vq.json", vq)
    rev_path = _write(tmp_path, "rev.json", review)
    spec_path = _write(tmp_path, "spec.json", spec)
    vq_only_path = tmp_path / "vq_only.json"

    n_added, n_dup = merger.merge(
        vq_path, rev_path, spec_path,
        vq_only_review_path=vq_only_path)
    assert n_added == 0
    # Standalone file still exists with empty findings
    assert vq_only_path.is_file(), (
        "VQ-only file must be written even when no findings (so "
        "revise_loop.py's --review-path read doesn't crash on missing file)")
    vq_only = json.loads(vq_only_path.read_text(encoding="utf-8"))
    assert vq_only["findings"] == []


def test_g8_cli_writes_vq_only_at_default_path(merger, tmp_path):
    """End-to-end CLI: --draft-dir resolves the VQ-only path to
    DRAFT/audit/adversarial_review_vq_only.json by default."""
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
    vq_only_default = draft / "audit" / "adversarial_review_vq_only.json"
    assert vq_only_default.is_file(), (
        "CLI must write VQ-only to default path "
        "DRAFT/audit/adversarial_review_vq_only.json")
    payload = json.loads(vq_only_default.read_text(encoding="utf-8"))
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["id"] == "VQ001"


def test_g8_cli_writes_vq_only_at_override_path(merger, tmp_path):
    """--vq-only-review CLI flag overrides the default output path."""
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
    custom_path = tmp_path / "custom_vq.json"
    rc = merger.main([
        "--draft-dir", str(draft),
        "--vq-only-review", str(custom_path),
    ])
    assert rc == 0
    assert custom_path.is_file()
    # Default path NOT used
    default_path = draft / "audit" / "adversarial_review_vq_only.json"
    assert not default_path.is_file(), (
        "when --vq-only-review override is supplied, the default "
        "path must NOT be written")
