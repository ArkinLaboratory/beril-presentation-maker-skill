"""v0.8.1: content_overflow → adversarial_review merger tests.

Mirrors the merge_visual_qa_into_review.py test pattern. The
content_overflow merger reads audit/content_overflow.json (emitted
by the renderer's G.10-C path), converts each finding to an
adversarial-shape entry with id="CO###" + class="content_overflow",
appends to adversarial_review.json, and recomputes the summary.

The merger runs BEFORE the 1st revise loop so content_overflow
findings ride into the 1st pass directly. This is the gap Tier H
surfaced on lanthanide draft_2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)
sys.path.insert(0, str(TOOLS_DIR))

import merge_content_overflow_into_review as mco  # noqa: E402


def _write_review(path: Path, findings: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "adversarial-review-presentation.v3",
        "tier": "STRONG",
        "findings": findings,
        "summary": {"by_severity": {}, "by_class": {}},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_content_overflow(path: Path, findings: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "content-overflow.v1",
        "pptx_path": "deliverable/draft.pptx",
        "findings": findings,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_slide_spec(path: Path, slides: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "slide-spec.v1",
        "slides": slides,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _co(slide_id: int, slot_kind: str = "title",
        chars: int = 250, base_pt: int = 28) -> dict:
    return {
        "slot_kind": slot_kind,
        "layout_name": "methods_summary",
        "slide_id": slide_id,
        "where": f"slide title (methods_summary)",
        "chars": chars,
        "base_pt": base_pt,
        "box_width_emu": 8520600,
        "box_height_emu": 572700,
        "computed_scale": 60000,
        "message": f"slide {slide_id} title: {chars} chars at floor",
    }


# ---------------------------------------------------------------------------
# Conversion: content_overflow → adversarial-shape
# ---------------------------------------------------------------------------

def test_co_to_adversarial_basic_shape() -> None:
    layouts = {16: "claim_evidence"}
    co_f = _co(16, "title", chars=224)
    result = mco._content_overflow_to_adversarial(co_f, 1, layouts)
    assert result["id"] == "CO001"
    assert result["class"] == "content_overflow"
    assert result["severity"] == "P1"
    assert result["confidence"] == "high"
    assert result["slide_id"] == 16
    assert result["slide_layout"] == "claim_evidence"
    assert "224 chars" in result["issue"]


def test_co_to_adversarial_uses_layout_from_spec_over_co_payload() -> None:
    """The adversarial finding's slide_layout should prefer the
    slide_spec layout (canonical) over the CO payload's layout_name
    (denormalized snapshot)."""
    layouts = {16: "claim_evidence"}  # canonical
    co_f = _co(16, "title", chars=224)
    co_f["layout_name"] = "stale_layout"  # CO payload — out of sync
    result = mco._content_overflow_to_adversarial(co_f, 1, layouts)
    assert result["slide_layout"] == "claim_evidence"


def test_co_to_adversarial_falls_back_to_payload_when_layout_missing() -> None:
    """If the slide_id isn't in the spec layout index, use the CO
    payload's layout_name (defensive)."""
    layouts: dict = {}
    co_f = _co(99, "title")
    result = mco._content_overflow_to_adversarial(co_f, 5, layouts)
    assert result["slide_layout"] == "methods_summary"  # from CO payload


def test_co_to_adversarial_routes_to_content_overflow_class() -> None:
    """All slot_kinds route to class='content_overflow' (NOT
    register_drift or claim_evidence — different revise discipline)."""
    layouts: dict = {}
    for slot_kind in ("title", "body", "textbox"):
        co_f = _co(1, slot_kind)
        result = mco._content_overflow_to_adversarial(co_f, 1, layouts)
        assert result["class"] == "content_overflow", (
            f"slot_kind={slot_kind} should route to content_overflow class"
        )


def test_co_to_adversarial_fix_hint_per_slot_kind() -> None:
    """The fix_hint string differs per slot_kind so the revise prompt
    knows which field to edit."""
    layouts: dict = {}
    title_hint = mco._content_overflow_to_adversarial(_co(1, "title"), 1, layouts)["fix_hint"]
    body_hint = mco._content_overflow_to_adversarial(_co(1, "body"), 1, layouts)["fix_hint"]
    # Title hint mentions content.title; body hint mentions content.bullets
    assert "title" in title_hint.lower()
    assert "bullet" in body_hint.lower() or "body" in body_hint.lower()


def test_co_to_adversarial_id_sequence_zero_padded() -> None:
    """Synthetic ids are CO001..CO999 — zero-padded for stable
    alphabetical sort with F-prefixed findings."""
    layouts: dict = {}
    f1 = mco._content_overflow_to_adversarial(_co(1), 1, layouts)
    f17 = mco._content_overflow_to_adversarial(_co(1), 17, layouts)
    assert f1["id"] == "CO001"
    assert f17["id"] == "CO017"


def test_co_to_adversarial_preserves_origin_metadata() -> None:
    """The _content_overflow_origin sub-dict preserves the source
    finding's geometry data (slot_kind, chars, base_pt, box dims,
    computed_scale) so downstream consumers can reconstruct what
    the renderer saw."""
    layouts: dict = {}
    co_f = _co(16, "title", chars=224, base_pt=28)
    result = mco._content_overflow_to_adversarial(co_f, 1, layouts)
    origin = result["_content_overflow_origin"]
    assert origin["slot_kind"] == "title"
    assert origin["chars"] == 224
    assert origin["base_pt"] == 28
    assert origin["computed_scale"] == 60000


# ---------------------------------------------------------------------------
# merge() — integration with adversarial_review.json
# ---------------------------------------------------------------------------

def test_merge_no_content_overflow_file_is_noop(tmp_path: Path) -> None:
    """When audit/content_overflow.json is absent, merge is a no-op
    (happy path — renderer wrote nothing because nothing clamped)."""
    audit = tmp_path / "audit"
    working = tmp_path / "working"
    review = audit / "adversarial_review.json"
    spec = working / "slide_spec.json"
    _write_review(review, [{"id": "F001", "class": "claim_evidence",
                            "severity": "P1", "slide_id": 5,
                            "issue": "x", "fix_hint": "x"}])
    _write_slide_spec(spec, [{"id": 5, "layout": "claim_evidence"}])

    n_added, n_dup = mco.merge(audit / "content_overflow.json", review, spec)
    assert n_added == 0
    assert n_dup == 0

    # Review file unchanged
    payload = json.loads(review.read_text(encoding="utf-8"))
    assert len(payload["findings"]) == 1


def test_merge_appends_co_findings(tmp_path: Path) -> None:
    """Each content_overflow finding appends as a CO###-prefixed
    adversarial-shape entry."""
    audit = tmp_path / "audit"
    working = tmp_path / "working"
    review = audit / "adversarial_review.json"
    co_path = audit / "content_overflow.json"
    spec = working / "slide_spec.json"

    _write_review(review, [{"id": "F001", "class": "claim_evidence",
                            "severity": "P1", "slide_id": 5,
                            "issue": "real issue", "fix_hint": "real hint"}])
    _write_content_overflow(co_path, [
        _co(16, "title", chars=224),
        _co(27, "title", chars=174),
    ])
    _write_slide_spec(spec, [
        {"id": 5, "layout": "claim_evidence"},
        {"id": 16, "layout": "claim_evidence"},
        {"id": 27, "layout": "claim_evidence"},
    ])

    n_added, n_dup = mco.merge(co_path, review, spec)
    assert n_added == 2
    assert n_dup == 0

    payload = json.loads(review.read_text(encoding="utf-8"))
    findings = payload["findings"]
    assert len(findings) == 3  # 1 original + 2 CO
    co_ids = sorted(f["id"] for f in findings if f["id"].startswith("CO"))
    assert co_ids == ["CO001", "CO002"]


def test_merge_recomputes_summary(tmp_path: Path) -> None:
    """summary.by_severity + summary.by_class get recomputed to
    include the new CO findings."""
    audit = tmp_path / "audit"
    working = tmp_path / "working"
    review = audit / "adversarial_review.json"
    co_path = audit / "content_overflow.json"
    spec = working / "slide_spec.json"

    _write_review(review, [{"id": "F001", "class": "claim_evidence",
                            "severity": "P0", "slide_id": 5,
                            "issue": "x", "fix_hint": "x"}])
    _write_content_overflow(co_path, [_co(16), _co(27)])
    _write_slide_spec(spec, [
        {"id": 5, "layout": "claim_evidence"},
        {"id": 16, "layout": "claim_evidence"},
        {"id": 27, "layout": "claim_evidence"},
    ])

    mco.merge(co_path, review, spec)

    payload = json.loads(review.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["by_severity"]["P0"] == 1
    assert summary["by_severity"]["P1"] == 2  # two new CO findings
    assert summary["by_class"]["content_overflow"] == 2
    assert summary["by_class"]["claim_evidence"] == 1


def test_merge_is_idempotent_via_dedupe(tmp_path: Path) -> None:
    """Running the merge twice on the same content_overflow.json
    doesn't multiply CO entries — fingerprint matches existing
    entries + skips them as dupes."""
    audit = tmp_path / "audit"
    working = tmp_path / "working"
    review = audit / "adversarial_review.json"
    co_path = audit / "content_overflow.json"
    spec = working / "slide_spec.json"

    _write_review(review, [])
    _write_content_overflow(co_path, [_co(16, "title", chars=224)])
    _write_slide_spec(spec, [{"id": 16, "layout": "claim_evidence"}])

    n1, _ = mco.merge(co_path, review, spec)
    n2, dup2 = mco.merge(co_path, review, spec)
    assert n1 == 1
    assert n2 == 0
    assert dup2 == 1

    payload = json.loads(review.read_text(encoding="utf-8"))
    co_entries = [f for f in payload["findings"] if f["id"].startswith("CO")]
    assert len(co_entries) == 1


def test_merge_co_ids_continue_from_max_existing(tmp_path: Path) -> None:
    """If review already has CO entries (e.g., from a prior merge
    that the user manually inspected + edited), new CO ids continue
    from max(existing)+1."""
    audit = tmp_path / "audit"
    working = tmp_path / "working"
    review = audit / "adversarial_review.json"
    co_path = audit / "content_overflow.json"
    spec = working / "slide_spec.json"

    _write_review(review, [
        {"id": "CO005", "class": "content_overflow", "severity": "P1",
         "slide_id": 99, "issue": "x", "fix_hint": "x",
         "_content_overflow_origin": {"slot_kind": "title", "chars": 999}},
    ])
    _write_content_overflow(co_path, [_co(16, "title", chars=224)])
    _write_slide_spec(spec, [
        {"id": 16, "layout": "claim_evidence"},
        {"id": 99, "layout": "qa_anticipated"},
    ])

    mco.merge(co_path, review, spec)
    payload = json.loads(review.read_text(encoding="utf-8"))
    new_co_ids = sorted(
        f["id"] for f in payload["findings"]
        if f["id"].startswith("CO") and f["slide_id"] == 16
    )
    assert new_co_ids == ["CO006"]  # continued from 5+1


def test_merge_raises_when_review_missing(tmp_path: Path) -> None:
    """If adversarial_review.json doesn't exist, raise — caller
    should have run adversarial review first."""
    co_path = tmp_path / "audit" / "content_overflow.json"
    _write_content_overflow(co_path, [_co(16)])
    spec = tmp_path / "working" / "slide_spec.json"
    _write_slide_spec(spec, [{"id": 16, "layout": "x"}])

    with pytest.raises(FileNotFoundError):
        mco.merge(co_path, tmp_path / "no_review.json", spec)


def test_merge_handles_empty_findings(tmp_path: Path) -> None:
    """A content_overflow.json with findings=[] is a no-op (the
    renderer wrote the file with zero findings — clean run)."""
    audit = tmp_path / "audit"
    working = tmp_path / "working"
    review = audit / "adversarial_review.json"
    co_path = audit / "content_overflow.json"
    spec = working / "slide_spec.json"

    _write_review(review, [])
    _write_content_overflow(co_path, [])
    _write_slide_spec(spec, [])

    n_added, _ = mco.merge(co_path, review, spec)
    assert n_added == 0


# ---------------------------------------------------------------------------
# Integration with revise_loop's REVISE_CLASSES
# ---------------------------------------------------------------------------

def test_co_class_is_in_revise_classes() -> None:
    """Pin: 'content_overflow' is in REVISE_CLASSES (G.10-C landed
    this). Without this, the merged findings would be classified
    as surface-only by revise_loop and skipped."""
    sys.path.insert(0, str(TOOLS_DIR))
    import revise_loop as rl
    assert "content_overflow" in rl.REVISE_CLASSES


def test_orchestrator_invokes_merger_before_revise_loop() -> None:
    """Source-level pin: presentation_maker.sh's stage_revise_slides
    must invoke merge_content_overflow_into_review.py BEFORE
    revise_loop.py. Without this ordering, the 1st revise pass
    still misses content_overflow findings."""
    sh_path = TOOLS_DIR / "presentation_maker.sh"
    text = sh_path.read_text(encoding="utf-8")
    # Find stage_revise_slides function body
    stage_start = text.find("stage_revise_slides() {")
    assert stage_start > 0
    # Find the next function definition to bound the body
    next_fn = text.find("\n}\n", stage_start)
    body = text[stage_start:next_fn]
    merge_pos = body.find("merge_content_overflow_into_review.py")
    revise_pos = body.find("revise_loop.py")
    assert merge_pos > 0, (
        "stage_revise_slides must invoke merge_content_overflow_into_review.py"
    )
    assert revise_pos > merge_pos, (
        "merge_content_overflow_into_review.py must run BEFORE revise_loop.py"
    )
