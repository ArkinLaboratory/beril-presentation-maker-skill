"""Tests for tools/reconcile_deck.py — the v0.4 M3 post-merge deck
reconciliation checker (V0_4_ARCHITECTURE.md §20.4).

Covers the three conflict detectors (duplicate figure, duplicate
big_number headline, AI-image count over the deck image budget), the
image-budget cap parser, the reconcile() integration, and main()'s
advisory contract (always exit 0; writes audit/deck_reconciliation.*).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)
sys.path.insert(0, str(TOOLS_DIR))

import reconcile_deck as rd  # noqa: E402


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _slide(sid: int, layout: str, **content) -> dict:
    return {"id": sid, "layout": layout, "content": dict(content)}


def _spec(slides: list[dict]) -> dict:
    return {"schema_version": "slide-spec.v1", "slides": slides}


# ----------------------------------------------------------------------
# duplicate_figure
# ----------------------------------------------------------------------

def test_duplicate_figure_flagged() -> None:
    slides = [
        _slide(1, "data_figure", figure="figures/dvh.png", caption="a"),
        _slide(2, "claim_evidence", title="t", figure="figures/dvh.png",
               figure_caption="b"),
    ]
    findings = rd.detect_duplicate_figures(slides)
    assert len(findings) == 1
    assert findings[0]["kind"] == "duplicate_figure"
    assert findings[0]["slide_ids"] == [1, 2]


def test_unique_figures_clean() -> None:
    slides = [
        _slide(1, "data_figure", figure="figures/a.png", caption="a"),
        _slide(2, "data_figure", figure="figures/b.png", caption="b"),
    ]
    assert rd.detect_duplicate_figures(slides) == []


def test_duplicate_figure_spans_figure_and_supporting_graphic() -> None:
    """A reuse across the `figure` and `supporting_graphic` keys counts."""
    slides = [
        _slide(1, "data_figure", figure="figures/x.png", caption="a"),
        _slide(2, "big_idea", title="t", supporting_graphic="figures/x.png"),
    ]
    findings = rd.detect_duplicate_figures(slides)
    assert len(findings) == 1
    assert findings[0]["slide_ids"] == [1, 2]


def test_concept_illustration_tbd_not_a_duplicate() -> None:
    """{TBD} image_path placeholders must not read as duplicate figures —
    image_path is excluded from the figure-reuse check entirely."""
    slides = [
        _slide(1, "concept_illustration", title="t", image_path="{TBD}",
               image_prompt="p"),
        _slide(2, "concept_illustration", title="t", image_path="{TBD}",
               image_prompt="p"),
    ]
    assert rd.detect_duplicate_figures(slides) == []


# ----------------------------------------------------------------------
# duplicate_headline
# ----------------------------------------------------------------------

def test_duplicate_headline_flagged() -> None:
    slides = [
        _slide(1, "big_number", headline="88.2%", subtitle="a"),
        _slide(2, "big_number", headline="88.2 %", subtitle="b"),
    ]
    findings = rd.detect_duplicate_headlines(slides)
    assert len(findings) == 1
    assert findings[0]["kind"] == "duplicate_headline"
    assert findings[0]["slide_ids"] == [1, 2]


def test_distinct_headlines_clean() -> None:
    slides = [
        _slide(1, "big_number", headline="88.2%", subtitle="a"),
        _slide(2, "big_number", headline="8,489", subtitle="b"),
    ]
    assert rd.detect_duplicate_headlines(slides) == []


def test_headline_check_ignores_non_big_number() -> None:
    """A repeated string on non-big_number slides is not a headline clash."""
    slides = [
        _slide(1, "claim_evidence", title="88.2%", bullets=["x"]),
        _slide(2, "claim_evidence", title="88.2%", bullets=["y"]),
    ]
    assert rd.detect_duplicate_headlines(slides) == []


# ----------------------------------------------------------------------
# image budget
# ----------------------------------------------------------------------

def test_extract_image_budget_cap() -> None:
    text = ("## Deck-level spec\n\n**Image budget:** ≤2 AI concept "
            "illustrations deck-wide. Data diagrams are uncapped.\n")
    assert rd._extract_image_budget_cap(text) == 2


def test_extract_image_budget_cap_absent_or_unparseable() -> None:
    assert rd._extract_image_budget_cap(None) is None
    assert rd._extract_image_budget_cap("no budget line here") is None
    assert rd._extract_image_budget_cap(
        "**Image budget:** no AI illustrations at all") is None


def test_image_budget_overflow_flagged() -> None:
    slides = [
        _slide(1, "concept_illustration", title="t", image_path="a",
               image_prompt="p"),
        _slide(2, "concept_illustration", title="t", image_path="b",
               image_prompt="p"),
        _slide(3, "concept_illustration", title="t", image_path="c",
               image_prompt="p"),
    ]
    findings = rd.detect_image_budget_overflow(
        slides, "**Image budget:** ≤2 AI concept illustrations")
    assert len(findings) == 1
    assert findings[0]["kind"] == "image_budget"
    assert findings[0]["slide_ids"] == [1, 2, 3]


def test_image_budget_within_cap_clean() -> None:
    slides = [
        _slide(1, "concept_illustration", title="t", image_path="a",
               image_prompt="p"),
        _slide(2, "concept_illustration", title="t", image_path="b",
               image_prompt="p"),
    ]
    assert rd.detect_image_budget_overflow(
        slides, "**Image budget:** ≤2 AI concept illustrations") == []


def test_image_budget_skipped_without_outline() -> None:
    """No outline (v0.3.x draft) -> the image_budget class is silent."""
    slides = [_slide(i, "concept_illustration", title="t", image_path=str(i),
                     image_prompt="p") for i in range(1, 6)]
    assert rd.detect_image_budget_overflow(slides, None) == []


# ----------------------------------------------------------------------
# reconcile() integration + clean deck
# ----------------------------------------------------------------------

def test_reconcile_clean_deck_no_findings() -> None:
    spec = _spec([
        _slide(1, "title", title="T"),
        _slide(2, "data_figure", figure="figures/a.png", caption="a"),
        _slide(3, "big_number", headline="88.2%", subtitle="s"),
    ])
    assert rd.reconcile(spec, None) == []


def test_reconcile_collects_all_three_classes() -> None:
    spec = _spec([
        _slide(1, "data_figure", figure="figures/dup.png", caption="a"),
        _slide(2, "data_figure", figure="figures/dup.png", caption="b"),
        _slide(3, "big_number", headline="61%", subtitle="s"),
        _slide(4, "big_number", headline="61%", subtitle="s"),
        _slide(5, "concept_illustration", title="t", image_path="x",
               image_prompt="p"),
        _slide(6, "concept_illustration", title="t", image_path="y",
               image_prompt="p"),
    ])
    findings = rd.reconcile(spec, "**Image budget:** ≤1 AI illustration")
    kinds = sorted(f["kind"] for f in findings)
    assert kinds == ["duplicate_figure", "duplicate_headline", "image_budget"]


# ----------------------------------------------------------------------
# main() — advisory contract
# ----------------------------------------------------------------------

def _make_draft(tmp_path: Path, spec: dict, outline: str | None) -> Path:
    draft = tmp_path / "draft_1"
    (draft / "working").mkdir(parents=True)
    (draft / "narrative").mkdir(parents=True)
    (draft / "working" / "slide_spec.json").write_text(json.dumps(spec))
    if outline is not None:
        (draft / "narrative" / "02_substories.md").write_text(outline)
    return draft


def test_main_writes_audit_files_and_exits_zero(tmp_path: Path) -> None:
    spec = _spec([
        _slide(1, "data_figure", figure="figures/dup.png", caption="a"),
        _slide(2, "data_figure", figure="figures/dup.png", caption="b"),
    ])
    draft = _make_draft(tmp_path, spec, outline=None)
    rc = rd.main([str(draft), "--quiet"])
    assert rc == 0  # advisory — always 0, even with a conflict
    payload = json.loads(
        (draft / "audit" / "deck_reconciliation.json").read_text())
    assert payload["schema_version"] == "deck-reconciliation.v1"
    assert payload["n_findings"] == 1
    assert payload["findings"][0]["kind"] == "duplicate_figure"
    assert (draft / "audit" / "deck_reconciliation.md").is_file()


def test_main_clean_deck_exits_zero(tmp_path: Path) -> None:
    spec = _spec([_slide(1, "title", title="T")])
    draft = _make_draft(tmp_path, spec, outline=None)
    rc = rd.main([str(draft), "--quiet"])
    assert rc == 0
    payload = json.loads(
        (draft / "audit" / "deck_reconciliation.json").read_text())
    assert payload["n_findings"] == 0


def test_main_missing_slide_spec_is_noop_not_error(tmp_path: Path) -> None:
    draft = tmp_path / "draft_empty"
    draft.mkdir()
    rc = rd.main([str(draft), "--quiet"])
    assert rc == 0
    payload = json.loads(
        (draft / "audit" / "deck_reconciliation.json").read_text())
    assert payload["n_findings"] == 0
    assert "note" in payload


def test_main_reads_outline_image_budget(tmp_path: Path) -> None:
    spec = _spec([
        _slide(i, "concept_illustration", title="t", image_path=str(i),
               image_prompt="p") for i in range(1, 4)
    ])
    outline = "## Deck-level spec\n\n**Image budget:** ≤1 AI illustration\n"
    draft = _make_draft(tmp_path, spec, outline=outline)
    rc = rd.main([str(draft), "--quiet"])
    assert rc == 0
    payload = json.loads(
        (draft / "audit" / "deck_reconciliation.json").read_text())
    assert payload["n_findings"] == 1
    assert payload["findings"][0]["kind"] == "image_budget"
