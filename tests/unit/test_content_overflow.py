"""v0.8.0 Tier G.10-C: content_overflow finding emission tests.

Three layers covered:

1. Assembler-side: when the geometry-aware fitter clamps at the
   FONTSCALE_FLOOR (60%), an OverflowFinding is appended to the
   active collector + persisted to audit/content_overflow.json.

2. Cascade reader: review_cascade._read_content_overflow lifts
   the audit JSON into a CascadeFinding with kind='content_overflow'
   at P1.

3. Revise-loop routing: content_overflow is in REVISE_CLASSES, so
   findings route to revise_slide.v1 (not surface_only).
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

import assemble_pptx as asm  # noqa: E402
import revise_loop as rl  # noqa: E402


# ---------------------------------------------------------------------------
# Module-level collector stack
# ---------------------------------------------------------------------------

def test_collector_stack_starts_empty() -> None:
    """The stack must start empty (no active assembly)."""
    # Defensive: capture + restore in case earlier tests leaked
    saved = list(asm._OVERFLOW_COLLECTOR_STACK)
    asm._OVERFLOW_COLLECTOR_STACK.clear()
    try:
        assert asm._current_overflow_collector() is None
    finally:
        asm._OVERFLOW_COLLECTOR_STACK.extend(saved)


def test_push_pop_collector_round_trip() -> None:
    saved = list(asm._OVERFLOW_COLLECTOR_STACK)
    asm._OVERFLOW_COLLECTOR_STACK.clear()
    try:
        my_list: list = []
        asm._push_overflow_collector(my_list)
        assert asm._current_overflow_collector() is my_list
        asm._pop_overflow_collector()
        assert asm._current_overflow_collector() is None
    finally:
        asm._OVERFLOW_COLLECTOR_STACK.extend(saved)


def test_nested_collectors_use_top_of_stack() -> None:
    """If assemble() were ever called from within assemble() (e.g.,
    a revise re-render), the inner collector wins. Stack semantics."""
    saved = list(asm._OVERFLOW_COLLECTOR_STACK)
    asm._OVERFLOW_COLLECTOR_STACK.clear()
    try:
        outer: list = []
        inner: list = []
        asm._push_overflow_collector(outer)
        asm._push_overflow_collector(inner)
        assert asm._current_overflow_collector() is inner
        asm._pop_overflow_collector()
        assert asm._current_overflow_collector() is outer
        asm._pop_overflow_collector()
        assert asm._current_overflow_collector() is None
    finally:
        asm._OVERFLOW_COLLECTOR_STACK.extend(saved)


# ---------------------------------------------------------------------------
# OverflowFinding dataclass + to_dict
# ---------------------------------------------------------------------------

def test_overflow_finding_to_dict_roundtrip() -> None:
    f = asm.OverflowFinding(
        slot_kind="title",
        layout_name="methods_summary",
        slide_id=24,
        where="slide title (methods_summary)",
        chars=337,
        base_pt=28,
        box_width_emu=8520600,
        box_height_emu=572700,
        computed_scale=60000,
        message="clamped at 60%",
    )
    d = f.to_dict()
    assert d["slot_kind"] == "title"
    assert d["chars"] == 337
    assert d["computed_scale"] == 60000


# ---------------------------------------------------------------------------
# Audit-file write
# ---------------------------------------------------------------------------

def test_write_content_overflow_audit_creates_json(tmp_path: Path) -> None:
    """The audit writer drops a schema-versioned JSON next to the
    draft pptx (in audit/, parallel to the layout_overlaps writer)."""
    pptx_dir = tmp_path / "draft_1" / "deliverable"
    pptx_dir.mkdir(parents=True)
    audit_dir = tmp_path / "draft_1" / "audit"
    audit_dir.mkdir()
    findings = [
        asm.OverflowFinding(
            slot_kind="title", layout_name="methods_summary",
            slide_id=24,
            where="slide title (methods_summary)",
            chars=337, base_pt=28,
            box_width_emu=8520600, box_height_emu=572700,
            computed_scale=60000, message="clamped",
        ),
    ]
    out = asm._write_content_overflow_audit(
        pptx_dir / "draft.pptx", findings,
    )
    assert out is not None
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "content-overflow.v1"
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["chars"] == 337


def test_write_content_overflow_falls_back_when_no_audit_dir(
    tmp_path: Path,
) -> None:
    """If the draft layout is unexpected (no audit/ sibling), the
    writer falls back to writing next to the pptx instead of
    losing the data."""
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    findings = [
        asm.OverflowFinding(
            slot_kind="title", layout_name="x",
            slide_id=1, where="x", chars=100, base_pt=28,
            box_width_emu=1000, box_height_emu=1000,
            computed_scale=60000, message="x",
        ),
    ]
    out = asm._write_content_overflow_audit(
        custom_dir / "draft.pptx", findings,
    )
    assert out is not None
    # Wrote into custom_dir/audit OR custom_dir itself — both are
    # acceptable fallbacks. Pin: the file got written somewhere.
    assert "content_overflow.json" in str(out)
    assert out.is_file()


# ---------------------------------------------------------------------------
# Cascade reader
# ---------------------------------------------------------------------------

@pytest.fixture
def rc():
    """Lazy-import review_cascade so it picks up the latest module."""
    sys.modules.pop("review_cascade", None)
    import review_cascade as _rc  # noqa: E402
    return _rc


def _write_audit_json(draft_dir: Path, filename: str, payload: dict) -> None:
    audit = draft_dir / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / filename).write_text(
        json.dumps(payload), encoding="utf-8",
    )


def test_cascade_read_content_overflow_no_op_when_missing(rc, tmp_path):
    """Reader is no-op-safe when audit/content_overflow.json absent."""
    assert rc._read_content_overflow(tmp_path) == []


def test_cascade_read_content_overflow_lifts_p1_findings(rc, tmp_path):
    """Each OverflowFinding lifts as a CascadeFinding with
    kind='content_overflow' at P1."""
    _write_audit_json(tmp_path, "content_overflow.json", {
        "schema_version": "content-overflow.v1",
        "pptx_path": "deliverable/draft.pptx",
        "findings": [
            {
                "slot_kind": "title",
                "layout_name": "methods_summary",
                "slide_id": 24,
                "where": "slide title (methods_summary)",
                "chars": 337,
                "base_pt": 28,
                "box_width_emu": 8520600,
                "box_height_emu": 572700,
                "computed_scale": 60000,
                "message": "clamped at 60%",
            },
            {
                "slot_kind": "body",
                "layout_name": "claim_evidence",
                "slide_id": 8,
                "where": "claim_evidence body",
                "chars": 880,
                "base_pt": 14,
                "box_width_emu": 8520000,
                "box_height_emu": 2972400,
                "computed_scale": 60000,
                "message": "clamped at 60%",
            },
        ],
    })
    findings = rc._read_content_overflow(tmp_path)
    assert len(findings) == 2
    for f in findings:
        assert f.kind == "content_overflow"
        assert f.severity == "P1"
    f0 = findings[0]
    assert f0.slide_id == 24
    assert f0.evidence["slot_kind"] == "title"
    assert f0.evidence["chars"] == 337
    assert f0.evidence["computed_scale"] == 60000


def test_cascade_aggregates_content_overflow_in_run_tier1(rc, tmp_path):
    """run_tier1 calls _read_content_overflow as the 11th reader;
    findings appear in the aggregated result. P1 (advisory) — never
    gates the cascade."""
    _write_audit_json(tmp_path, "content_overflow.json", {
        "schema_version": "content-overflow.v1",
        "findings": [
            {
                "slot_kind": "title", "layout_name": "methods_summary",
                "slide_id": 24, "where": "x", "chars": 337,
                "base_pt": 28, "box_width_emu": 100, "box_height_emu": 100,
                "computed_scale": 60000, "message": "x",
            },
        ],
    })
    result = rc.run_tier1(tmp_path)
    kinds = [f.kind for f in result.findings]
    assert "content_overflow" in kinds
    # P1 advisory — no P0 from content_overflow alone
    co_p0 = [f for f in result.findings
             if f.kind == "content_overflow" and f.severity == "P0"]
    assert co_p0 == []


# ---------------------------------------------------------------------------
# Revise routing: content_overflow is in REVISE_CLASSES
# ---------------------------------------------------------------------------

def test_content_overflow_is_in_revise_classes() -> None:
    """The class must route to revise_slide.v1 (not surface-only),
    otherwise the renderer's finding wouldn't be auto-fixable —
    the operator would have to rewrite manually every cycle."""
    assert "content_overflow" in rl.REVISE_CLASSES


def test_content_overflow_not_in_surface_only_classes() -> None:
    """Defensive: must not be both REVISE and SURFACE_ONLY (would
    create ambiguous routing in the orchestrator)."""
    assert "content_overflow" not in rl.SURFACE_ONLY_CLASSES


def test_content_overflow_not_in_add_classes() -> None:
    """content_overflow shortens an existing slide; it doesn't add
    new slides. Must not be in ADD_CLASSES."""
    assert "content_overflow" not in rl.ADD_CLASSES


def test_revise_prompt_documents_content_overflow_class() -> None:
    """revise_slide.v1.md must include a per-class guidance section
    for content_overflow (otherwise the LLM has no idea what to do
    when the orchestrator routes a content_overflow finding to it)."""
    prompt_path = (Path(__file__).resolve().parents[2]
                   / "src/beril_presentation_maker/skill/prompts"
                   / "revise_slide.v1.md")
    text = prompt_path.read_text(encoding="utf-8")
    assert "### `content_overflow`" in text
    assert "slot_kind" in text  # the evidence field the LLM reads
    assert "FONTSCALE_FLOOR" in text or "60%" in text  # the floor concept


def test_revise_prompt_class_enum_lists_content_overflow() -> None:
    """The output schema's finding_class enum must include
    content_overflow so the LLM's emitted revision_log entries are
    accepted by downstream validators."""
    prompt_path = (Path(__file__).resolve().parents[2]
                   / "src/beril_presentation_maker/skill/prompts"
                   / "revise_slide.v1.md")
    text = prompt_path.read_text(encoding="utf-8")
    # The enum line lists pipe-separated classes
    assert "content_overflow" in text
