"""Tests for revise_invariance.py — revise-verb semantic-invariance
post-check (v0.4 M5a Tier A).

Coverage targets:
- The five-invariant contract per V0_4_ARCHITECTURE §13.
- Per-invariant happy + failure paths:
  * Invariant 1 — claim_id cross-walk (DQ1 heuristic; skipped when
    claim_inventory absent).
  * Invariant 2 — citation preservation (insertion AND deletion fail).
  * Invariant 3 — numeric preservation (multiset; removal OK,
    invention fail).
  * Invariant 4 — hedge level (DQ2 per-slide aggregation; ≤1 decrease
    OK, increase fail, >1 decrease fail).
  * Invariant 5 — layout preservation.
- Report schema + verdict.
- CLI rc=0/1 (DQ3 hard-reject on any fail).
- Text-extraction walks content (incl. nested) + speaker_notes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RI_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "revise_invariance.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ri():
    return _import("revise_invariance", RI_PY)


def _slide(layout: str = "claim_evidence",
           title: str = "T",
           bullets: list[str] | None = None,
           figure_caption: str | None = None,
           speaker_notes: str | None = None,
           slide_id: int = 1) -> dict:
    """Build a minimal slide dict for invariance tests."""
    content = {"title": title}
    if bullets is not None:
        content["bullets"] = bullets
    if figure_caption is not None:
        content["figure_caption"] = figure_caption
    out = {"id": slide_id, "layout": layout, "content": content}
    if speaker_notes is not None:
        out["speaker_notes"] = speaker_notes
    return out


# ---------------------------------------------------------------------------
# Schema + report contract
# ---------------------------------------------------------------------------

def test_schema_version_pinned(ri):
    """revise-invariance.v1 is the consumer contract."""
    assert ri.SCHEMA_VERSION == "revise-invariance.v1"


def test_hedge_dictionary_matches_section_13(ri):
    """DQ2: ship §13's 5 markers as a constant. Pin so adding/removing
    breaks the test, not the contract."""
    assert ri.HEDGE_MARKERS == (
        "may", "suggests", "appears", "candidate", "preliminary",
    )


def test_report_to_dict_carries_schema_version(ri):
    """Report JSON always carries schema_version + verdict + the
    checked/skipped/violations triple."""
    pre = _slide(bullets=["foo"])
    post = _slide(bullets=["foo"])
    r = ri.check_invariance(pre, post, finding_id="F001")
    d = r.to_dict()
    assert d["schema_version"] == "revise-invariance.v1"
    assert d["finding_id"] == "F001"
    assert d["verdict"] == "pass"
    assert "checked_invariants" in d
    assert "skipped_invariants" in d
    assert "violations" in d


# ---------------------------------------------------------------------------
# Text extraction (the substrate for invariants 1-4)
# ---------------------------------------------------------------------------

def test_extract_all_text_walks_content_recursively(ri):
    """_extract_all_text walks content + speaker_notes, including
    nested lists/dicts (e.g. data_table rows / workflow_diagram steps)."""
    slide = {
        "id": 1, "layout": "data_table",
        "content": {
            "title": "Top hits",
            "rows": [["gene", "score"], ["xyzA", "0.95"]],
            "footnote": "n=50",
        },
        "speaker_notes": "see [Smith2024] for context",
    }
    text = ri._extract_all_text(slide)
    # Should contain every string in the structure
    for needle in ("Top hits", "gene", "score", "xyzA", "0.95",
                   "n=50", "Smith2024"):
        assert needle in text, f"missing {needle!r} in extracted text"


def test_extract_all_text_skips_non_string_values(ri):
    """ints/floats/bools/None aren't text — they're structural metadata
    (slide_id, position, validator_status) and must not feed into
    textual invariants."""
    slide = {"id": 42, "layout": "title",
             "content": {"slide_number": 7, "is_intro": True,
                         "title": "Real Text"}}
    text = ri._extract_all_text(slide)
    assert "Real Text" in text
    assert "42" not in text          # slide_id not in extracted text
    assert "True" not in text         # bool not in extracted text


# ---------------------------------------------------------------------------
# Invariant 1 — claim_id cross-walk (DQ1 heuristic)
# ---------------------------------------------------------------------------

def _write_claim_inventory(tmp_path: Path, ids: list[str]) -> Path:
    """Build a minimal claim_inventory.tsv with the given claim_ids."""
    path = tmp_path / "claim_inventory.tsv"
    rows = ["claim_id\tclaim_text\tsource_notebook"]
    for cid in ids:
        rows.append(f"{cid}\tsynthetic claim\tnb.ipynb")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_invariant1_skipped_when_no_claim_inventory(ri):
    """Per DQ1: if claim_inventory.tsv is missing/unreadable, the
    claim_id cross-walk is recorded as skipped (not failed). The
    revise discipline is preserved by the other 4 invariants.

    Uses digit-free claim_ids (C-alpha / C-beta) so the numeric
    invariant doesn't trip on the embedded digits of real-shape
    ids like C-001 / C-002 (those would be caught as 'invented
    numbers' by invariant 3 — unrelated to this test)."""
    pre = _slide(bullets=["see C-alpha in NB"])
    post = _slide(bullets=["see C-beta in NB"])   # different claim_id mention
    r = ri.check_invariance(pre, post)   # no claim_inventory_path
    assert "claim_id_cross_walk" in r.skipped_invariants
    assert "claim_id_cross_walk" not in r.checked_invariants
    assert r.verdict == "pass"           # other 4 didn't fail
    assert "claim_id_cross_walk skipped" in r.note


def test_invariant1_passes_when_claim_id_mentions_unchanged(ri, tmp_path):
    """Same claim_ids mentioned in pre + post → pass."""
    inv = _write_claim_inventory(tmp_path, ["C-001", "C-002"])
    pre = _slide(bullets=["evidence for C-001"])
    post = _slide(bullets=["evidence for C-001 (rephrased)"])
    r = ri.check_invariance(pre, post, claim_inventory_path=inv)
    assert "claim_id_cross_walk" in r.checked_invariants
    assert r.verdict == "pass"


def test_invariant1_fails_when_claim_id_removed(ri, tmp_path):
    """Pre mentions C-001; post does not → invariant 1 fails."""
    inv = _write_claim_inventory(tmp_path, ["C-001", "C-002"])
    pre = _slide(bullets=["evidence for C-001"])
    post = _slide(bullets=["evidence for the claim"])  # C-001 mention dropped
    r = ri.check_invariance(pre, post, claim_inventory_path=inv)
    assert r.verdict == "fail"
    assert any(v.invariant == "claim_id_cross_walk" for v in r.violations)
    v = next(v for v in r.violations if v.invariant == "claim_id_cross_walk")
    assert "C-001" in v.detail or "removed" in v.detail
    assert v.pre_value == ["C-001"]
    assert v.post_value == []


def test_invariant1_fails_when_claim_id_added(ri, tmp_path):
    """Post mentions a claim_id not in pre → invariant 1 fails."""
    inv = _write_claim_inventory(tmp_path, ["C-001", "C-002"])
    pre = _slide(bullets=["see the analysis"])
    post = _slide(bullets=["see C-002 in the analysis"])
    r = ri.check_invariance(pre, post, claim_inventory_path=inv)
    assert r.verdict == "fail"
    assert any(v.invariant == "claim_id_cross_walk" for v in r.violations)


# ---------------------------------------------------------------------------
# Invariant 2 — citation preservation
# ---------------------------------------------------------------------------

def test_invariant2_passes_when_citations_unchanged(ri):
    pre = _slide(bullets=["evidence from [Smith2024]"])
    post = _slide(bullets=["evidence (rephrased) from [Smith2024]"])
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"


def test_invariant2_fails_when_citation_deleted(ri):
    """Revise that drops a citation token → invariant 2 fails (the
    common LLM-revision footgun this invariant guards against)."""
    pre = _slide(bullets=["evidence from [Smith2024]"])
    post = _slide(bullets=["evidence from prior work"])  # citation dropped
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"
    v = next(v for v in r.violations if v.invariant == "citation_preservation")
    assert "Smith2024" in v.detail or "removed" in v.detail


def test_invariant2_fails_when_citation_added(ri):
    """Revise that adds a new citation token → invariant 2 fails (the
    LLM must not invent attributions)."""
    pre = _slide(bullets=["evidence from prior work"])
    post = _slide(bullets=["evidence from prior work [Jones2025]"])
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"


def test_invariant2_extracts_only_named_citations(ri):
    """[Smith2024] is a citation; [1] is a reference number and should
    NOT trip the citation invariant. Tests the citation regex's
    `^[A-Za-z]` anchor (numeric-only `[N]` brackets are excluded).

    Note: changes to the bracketed-number content DO trigger invariant
    3 (numeric preservation) because the digit is now in the text. To
    isolate the citation invariant here, both pre and post carry the
    same `[1]`."""
    pre = _slide(bullets=["see [1] for [Smith2024]"])
    post = _slide(bullets=["see [1] for [Smith2024] (rephrased)"])
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"
    # Confirm citation set carries Smith2024 only (not "1")
    assert "citation_preservation" in r.checked_invariants


# ---------------------------------------------------------------------------
# Invariant 3 — numeric preservation
# ---------------------------------------------------------------------------

def test_invariant3_passes_when_numerics_unchanged(ri):
    pre = _slide(bullets=["recovery is 94.7% (n=188)"])
    post = _slide(bullets=["94.7% recovery on n=188 strains"])
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"


def test_invariant3_passes_when_number_removed_for_dedup(ri):
    """Removal is allowed (composer may de-dup a redundant number)."""
    pre = _slide(bullets=["94.7% on n=188", "ALSO: 94.7%"])
    post = _slide(bullets=["94.7% on n=188"])   # removed one 94.7%
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"


def test_invariant3_fails_on_invention(ri):
    """Revise that introduces a number not in pre-edit → invariant 3 fails.
    This is the load-bearing case — protects against LLM fabrication."""
    pre = _slide(bullets=["recovery is 94.7%"])
    post = _slide(bullets=["recovery is 94.7% (improved from 89.2%)"])  # invented 89.2%
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"
    v = next(v for v in r.violations if v.invariant == "numeric_preservation")
    assert "invented" in v.detail
    assert "89.2" in v.detail or "89.2" in str(v.pre_value) + str(v.post_value)


# ---------------------------------------------------------------------------
# Invariant 4 — hedge level (DQ2 per-slide aggregation)
# ---------------------------------------------------------------------------

def test_invariant4_passes_when_hedge_count_unchanged(ri):
    pre = _slide(bullets=["this may indicate X", "suggests Y"])
    post = _slide(bullets=["may indicate X (rephrased)", "suggests Y"])
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"


def test_invariant4_passes_when_one_hedge_removed(ri):
    """≤1 decrease is allowed (rephrasing one bullet)."""
    pre = _slide(bullets=["this may indicate X", "suggests Y"])
    post = _slide(bullets=["this shows X", "suggests Y"])  # removed "may"
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"


def test_invariant4_fails_when_hedge_added(ri):
    """Adding a hedge would flip a declarative claim to hedged — fail."""
    pre = _slide(bullets=["X causes Y"])
    post = _slide(bullets=["X may cause Y"])
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"
    v = next(v for v in r.violations if v.invariant == "hedge_level")
    assert "INCREASED" in v.detail


def test_invariant4_fails_when_multiple_hedges_removed(ri):
    """Removing >1 hedge in one pass flips multiple hedged claims to
    declarative — fail. Scope-change disguised as a revise."""
    pre = _slide(bullets=["may indicate X", "suggests Y", "appears Z"])
    post = _slide(bullets=["indicates X", "shows Y", "is Z"])  # 3 hedges removed
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"
    v = next(v for v in r.violations if v.invariant == "hedge_level")
    assert "DECREASED by >1" in v.detail


def test_invariant4_is_case_insensitive(ri):
    """Hedge markers match case-insensitively (composers write 'May'
    at sentence start)."""
    pre = _slide(bullets=["May indicate X"])
    post = _slide(bullets=["X is shown"])   # hedge removed
    r = ri.check_invariance(pre, post)
    # Removing 1 hedge is allowed; should pass
    assert r.verdict == "pass"


# ---------------------------------------------------------------------------
# Invariant 5 — layout preservation
# ---------------------------------------------------------------------------

def test_invariant5_passes_when_layout_unchanged(ri):
    pre = _slide(layout="big_number")
    post = _slide(layout="big_number")
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"


def test_invariant5_fails_when_layout_changed(ri):
    """Layout change requires re-architecting; revise can't do it."""
    pre = _slide(layout="claim_evidence")
    post = _slide(layout="big_idea")
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"
    v = next(v for v in r.violations if v.invariant == "layout_preservation")
    assert "claim_evidence" in v.detail and "big_idea" in v.detail
    assert "re-architecting" in v.detail.lower() or "re-evaluate" in v.detail.lower()


# ---------------------------------------------------------------------------
# Multi-invariant + verdict
# ---------------------------------------------------------------------------

def test_multiple_invariants_can_fail_simultaneously(ri):
    """When pre + post differ in multiple ways, the report carries all
    failed invariants — operator sees the full picture."""
    pre = _slide(layout="claim_evidence",
                 bullets=["may show X from [Smith2024]"])
    post = _slide(layout="big_idea",                # invariant 5 fail
                  bullets=["shows X from [Jones2025]"])  # 2 + 4 fail
    r = ri.check_invariance(pre, post)
    assert r.verdict == "fail"
    failed_invariants = {v.invariant for v in r.violations}
    assert "layout_preservation" in failed_invariants
    assert "citation_preservation" in failed_invariants


def test_passing_revise_keeps_all_invariants_satisfied(ri):
    """A clean revise (rephrasing only) passes all 4 invariants;
    claim_id is skipped without claim_inventory."""
    pre = _slide(
        bullets=["evidence from [Smith2024] (n=42); may indicate X"],
        speaker_notes="see [Smith2024] §3.1",
    )
    post = _slide(
        bullets=["evidence from [Smith2024] (n=42); X is indicated"],  # 'may' removed (allowed)
        speaker_notes="see [Smith2024] §3.1 for context",
    )
    r = ri.check_invariance(pre, post)
    assert r.verdict == "pass"
    assert r.violations == []


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_rc0_on_pass(ri, tmp_path):
    """DQ3: rc=0 when all invariants pass."""
    pre = _slide(bullets=["recovery is 94.7%"])
    post = _slide(bullets=["recovery: 94.7%"])
    pre_path = tmp_path / "pre.json"
    post_path = tmp_path / "post.json"
    pre_path.write_text(json.dumps(pre))
    post_path.write_text(json.dumps(post))
    out_path = tmp_path / "out.json"
    rc = ri.main([str(pre_path), str(post_path), "--out", str(out_path),
                  "--quiet"])
    assert rc == 0
    report = json.loads(out_path.read_text())
    assert report["verdict"] == "pass"


def test_cli_rc1_on_fail(ri, tmp_path):
    """DQ3 hard-reject: rc=1 when any invariant fails."""
    pre = _slide(bullets=["evidence from [Smith2024]"])
    post = _slide(bullets=["evidence from prior work"])  # citation dropped
    pre_path = tmp_path / "pre.json"
    post_path = tmp_path / "post.json"
    pre_path.write_text(json.dumps(pre))
    post_path.write_text(json.dumps(post))
    out_path = tmp_path / "out.json"
    rc = ri.main([str(pre_path), str(post_path), "--out", str(out_path),
                  "--quiet"])
    assert rc == 1
    report = json.loads(out_path.read_text())
    assert report["verdict"] == "fail"


def test_cli_rc2_on_missing_pre_slide(ri, tmp_path):
    """Missing pre-edit slide path → rc=2 (operator error, not
    invariance fail)."""
    post = _slide()
    post_path = tmp_path / "post.json"
    post_path.write_text(json.dumps(post))
    rc = ri.main([str(tmp_path / "nope.json"), str(post_path), "--quiet"])
    assert rc == 2


def test_cli_threads_claim_inventory_through(ri, tmp_path):
    """The --claim-inventory flag enables invariant 1 (DQ1 heuristic)."""
    inv = _write_claim_inventory(tmp_path, ["C-001"])
    pre = _slide(bullets=["see C-001"])
    post = _slide(bullets=["see the analysis"])  # C-001 dropped
    pre_path = tmp_path / "pre.json"
    post_path = tmp_path / "post.json"
    pre_path.write_text(json.dumps(pre))
    post_path.write_text(json.dumps(post))
    out_path = tmp_path / "out.json"
    rc = ri.main([str(pre_path), str(post_path),
                  "--claim-inventory", str(inv),
                  "--out", str(out_path), "--quiet"])
    assert rc == 1
    report = json.loads(out_path.read_text())
    assert "claim_id_cross_walk" in report["checked_invariants"]
    assert any(v["invariant"] == "claim_id_cross_walk"
               for v in report["violations"])
