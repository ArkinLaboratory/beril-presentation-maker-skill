"""Unit tests for tools/extract_deck_close.py (v0.7 Tier C.2 / D-086).

Per D-086: extract_deck_close.py reads the curator-side draft
artifacts (00_throughline.md + 02_substories.md + REPORT.md) and
emits working/deck_close_signal.json with the structured fields
the deck_close composer reads verbatim:

  - unified_point: from the throughline's punchline comment / chosen claim
  - key_takeaways: from per-substory `Conclusion for next substory:`
  - forward_call: from REPORT.md "Next directions" / "Future work" sections
  - data_source: mechanical synthesis of which artifacts were read

Test coverage:
- Happy path: all three artifacts present + well-formed → full signal.
- Per-source parsers (throughline / substories / REPORT) in isolation.
- Format-handling: v0.6+ throughline (HTML comment) vs older v0.5 fields.
- Missing-file fall-throughs (no crashes; partial signal).
- no_signal_fallback: True when substories file missing or empty.
- CLI: writes to <draft_dir>/working/deck_close_signal.json by default.
- Edge cases: REPORT.md as bulleted list; throughline as italic-meta-only;
  cap at 5 key_takeaways; final substory uses punchline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACT_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
              / "tools" / "extract_deck_close.py")


@pytest.fixture(scope="module")
def edc():
    """Load extract_deck_close as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("extract_deck_close",
                                                   EXTRACT_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_deck_close"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_draft(tmp_path: Path, project_id: str = "test_project") -> Path:
    """Create the canonical BERIL draft layout under tmp_path:
    tmp_path/projects/<id>/talks/draft_1/{narrative,working}/."""
    project_dir = tmp_path / "projects" / project_id
    draft_dir = project_dir / "talks" / "draft_1"
    (draft_dir / "narrative").mkdir(parents=True)
    (draft_dir / "working").mkdir()
    return draft_dir


def _write_throughline_v06(draft_dir: Path, punchline: str):
    """v0.6+ throughline format: HTML comment at top."""
    (draft_dir / "narrative" / "00_throughline.md").write_text(
        f"<!-- chosen: TL1 -->\n"
        f"<!-- punchline: {punchline} -->\n"
        f"\n"
        f"# Throughline (chosen: TL1)\n"
        f"\n"
        f"_Picked from `00_throughline_candidates.md` by the smoke._\n"
        f"\n"
        f"## Candidate TL1: {punchline}\n"
        f"\n"
        f"**Evidence map:** ...\n",
        encoding="utf-8",
    )


def _write_substories(draft_dir: Path,
                       substories: list[tuple[str, str, str, str]]):
    """substories = [(sid, transition_from_prior, conclusion, punchline)]
    Empty transition_from_prior → omit the field (S1 / pre-v3.2 curator).
    Empty conclusion → omit (final substory)."""
    parts = ["# Substory clusters\n\n"]
    for sid, transition, conclusion, punchline in substories:
        parts.append(f"### {sid} — {sid} cluster\n\n")
        if transition:
            parts.append(f"**Transition from prior:** {transition}\n\n")
        parts.append(f"**Question:** What does {sid} answer?\n\n")
        if conclusion:
            parts.append(f"**Conclusion for next substory:** {conclusion}\n\n")
        parts.append(f"**Punchline:** {punchline}\n\n")
        parts.append("**Critical analyses covered:**\n\n- A1: x — NB01\n\n")
    (draft_dir / "narrative" / "02_substories.md").write_text(
        "".join(parts), encoding="utf-8",
    )


def _write_report(project_dir: Path, body: str):
    """Write REPORT.md to the project dir."""
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "REPORT.md").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_emits_full_signal(edc, tmp_path):
    """All three artifacts present + well-formed → full DeckCloseReport
    with unified_point + 3 key_takeaways + forward_call + data_source."""
    draft_dir = _make_draft(tmp_path, project_id="happy_test")
    project_dir = draft_dir.parent.parent
    _write_throughline_v06(draft_dir,
        "Three lines of evidence converge on a 6-target phage cocktail.")
    _write_substories(draft_dir, [
        ("S1", "", "UC Davis stratifies into 3 ecotypes.",
         "Ecological stratification."),
        ("S2", "S1 established stratification.",
         "Pathobionts form a 2-narrative module.",
         "Two narratives unified."),
        ("S3", "S2 named the pathobionts.", "",
         "Hybrid cocktails are structural."),  # final: no conclusion
    ])
    _write_report(project_dir,
        "# REPORT\n\n## Findings\n\nstuff.\n\n## Future directions\n\n"
        "Validate Tier-1 targets in murine models. "
        "Expand to longitudinal human cohort.\n\n## Refs\n")

    report = edc.extract_deck_close(draft_dir)

    assert report.project_id == "happy_test"
    assert report.unified_point.startswith("Three lines of evidence")
    assert len(report.key_takeaways) == 3
    assert report.key_takeaways[0] == "UC Davis stratifies into 3 ecotypes."
    assert report.key_takeaways[1] == \
        "Pathobionts form a 2-narrative module."
    # Final substory has no Conclusion-for-next → uses Punchline
    assert report.key_takeaways[2] == "Hybrid cocktails are structural."
    assert "murine" in report.forward_call
    assert "S1 (C-slot)" in report.data_source
    assert "S2 (C-slot)" in report.data_source
    assert "S3 (C-slot)" in report.data_source
    assert "00_throughline.md" in report.data_source
    assert "Future directions" in report.data_source
    assert report.no_signal_fallback is False


def test_to_slide_content_matches_d086_schema(edc, tmp_path):
    """to_slide_content() output is exactly the 4 fields validate_slide_spec
    expects on a deck_close slide."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "Unified takeaway here.")
    _write_substories(draft_dir, [
        ("S1", "", "C1.", "P1."),
        ("S2", "", "C2.", "P2."),
        ("S3", "", "", "P3."),
    ])
    _write_report(draft_dir.parent.parent,
        "# R\n\n## Next directions\n\nNext step here.\n")

    report = edc.extract_deck_close(draft_dir)
    content = report.to_slide_content()
    # Exactly the 4 fields D-086 requires
    assert set(content.keys()) == {
        "unified_point", "key_takeaways", "forward_call", "data_source",
    }
    assert isinstance(content["key_takeaways"], list)


# ---------------------------------------------------------------------------
# Throughline parser
# ---------------------------------------------------------------------------

def test_throughline_v06_html_comment_format(edc, tmp_path):
    """v0.6+ format: <!-- punchline: ... --> at top wins over other
    parsable fields."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "The chosen claim.")
    text = edc.parse_throughline(draft_dir / "narrative" / "00_throughline.md")
    assert text == "The chosen claim."


def test_throughline_candidate_heading_fallback(edc, tmp_path):
    """No <!-- punchline: --> comment → fall back to ## Candidate TL1:
    heading."""
    draft_dir = _make_draft(tmp_path)
    (draft_dir / "narrative" / "00_throughline.md").write_text(
        "# Throughline\n\n## Candidate TL1: This is the claim.\n",
        encoding="utf-8",
    )
    text = edc.parse_throughline(draft_dir / "narrative" / "00_throughline.md")
    assert text == "This is the claim."


def test_throughline_chosen_field_v05_format(edc, tmp_path):
    """v0.5 format: **Chosen throughline:** ... field."""
    draft_dir = _make_draft(tmp_path)
    (draft_dir / "narrative" / "00_throughline.md").write_text(
        "# Throughline\n\n**Chosen throughline:** The v0.5 claim style.\n",
        encoding="utf-8",
    )
    text = edc.parse_throughline(draft_dir / "narrative" / "00_throughline.md")
    assert text == "The v0.5 claim style."


def test_throughline_missing_returns_empty(edc, tmp_path):
    """Missing throughline file → empty string (no crash)."""
    draft_dir = _make_draft(tmp_path)
    text = edc.parse_throughline(draft_dir / "narrative" / "missing.md")
    assert text == ""


def test_throughline_skips_italic_meta_paragraph(edc, tmp_path):
    """The v0.7 throughline generator writes `_Picked from .../candidates.md..._`
    as an italic meta-line right after the H1. Don't grab it as the claim."""
    draft_dir = _make_draft(tmp_path)
    (draft_dir / "narrative" / "00_throughline.md").write_text(
        "# Throughline\n\n"
        "_Picked from `00_throughline_candidates.md` by the smoke orchestrator._\n"
        "\n"
        "## Candidate TL1: The actual claim.\n",
        encoding="utf-8",
    )
    text = edc.parse_throughline(draft_dir / "narrative" / "00_throughline.md")
    assert text == "The actual claim."


def test_throughline_uses_chosen_comment_to_pick_candidate(edc, tmp_path):
    """When multiple ## Candidate TLN: headings exist, the
    <!-- chosen: TLN --> comment picks which one."""
    draft_dir = _make_draft(tmp_path)
    (draft_dir / "narrative" / "00_throughline.md").write_text(
        "<!-- chosen: TL2 -->\n\n"
        "# Throughline\n\n"
        "## Candidate TL1: First candidate (NOT chosen).\n\n"
        "## Candidate TL2: Second candidate (CHOSEN).\n",
        encoding="utf-8",
    )
    text = edc.parse_throughline(draft_dir / "narrative" / "00_throughline.md")
    assert text == "Second candidate (CHOSEN)."


# ---------------------------------------------------------------------------
# Substory parser
# ---------------------------------------------------------------------------

def test_substory_parser_pulls_conclusion_per_record(edc, tmp_path):
    draft_dir = _make_draft(tmp_path)
    _write_substories(draft_dir, [
        ("S1", "", "S1 conclusion.", "S1 punchline."),
        ("S2", "", "S2 conclusion.", "S2 punchline."),
    ])
    records = edc.parse_substory_records(
        draft_dir / "narrative" / "02_substories.md")
    assert len(records) == 2
    assert records[0].substory_id == "S1"
    assert records[0].conclusion_for_next == "S1 conclusion."
    assert records[0].punchline == "S1 punchline."
    assert records[0].transition_from_prior == ""
    assert records[1].conclusion_for_next == "S2 conclusion."


def test_substory_parser_pulls_v3_2_transition_when_present(edc, tmp_path):
    """When the substory_design v3.2 overlay (D-087) is in play, the
    Transition from prior: field is parsed (used as evidence flag in
    raw_evidence; not load-bearing for the takeaways)."""
    draft_dir = _make_draft(tmp_path)
    _write_substories(draft_dir, [
        ("S1", "", "C1.", "P1."),
        ("S2", "S1 established X. S2 asks Y.", "C2.", "P2."),
    ])
    records = edc.parse_substory_records(
        draft_dir / "narrative" / "02_substories.md")
    assert records[0].transition_from_prior == ""
    assert records[1].transition_from_prior.startswith("S1 established")


def test_substory_parser_missing_file_returns_empty(edc, tmp_path):
    records = edc.parse_substory_records(tmp_path / "missing.md")
    assert records == []


def test_final_substory_uses_punchline_when_no_conclusion(edc, tmp_path):
    """Final substory has no Conclusion-for-next-substory (because there
    is no next); takeaway comes from its Punchline instead."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    _write_substories(draft_dir, [
        ("S1", "", "C1.", "P1."),
        ("S2", "", "", "P2 final punchline."),  # final: no conclusion
    ])
    _write_report(draft_dir.parent.parent, "# R\n")
    report = edc.extract_deck_close(draft_dir)
    assert report.key_takeaways == ["C1.", "P2 final punchline."]


# ---------------------------------------------------------------------------
# REPORT forward_call parser
# ---------------------------------------------------------------------------

def test_report_forward_call_prose_section(edc, tmp_path):
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    _write_report(project_dir,
        "# REPORT\n\n## Next directions\n\n"
        "Validate the predicted Tier-1 targets in murine models. "
        "Then expand to a longitudinal human cohort.\n")
    text, sections = edc.parse_report_forward_call(project_dir / "REPORT.md")
    assert "murine" in text
    assert "Next directions" in sections


def test_report_forward_call_bulleted_section(edc, tmp_path):
    """When the section is a bulleted list (common in REPORT.md),
    pull the first 1-2 bullets as a concatenated string."""
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    _write_report(project_dir,
        "# REPORT\n\n## Next directions\n\n"
        "- Validate Tier-1 targets in murine colitis models.\n"
        "- Expand to longitudinal human cohort.\n"
        "- Some later thing not in the first 2 bullets.\n")
    text, sections = edc.parse_report_forward_call(project_dir / "REPORT.md")
    assert "Tier-1" in text or "murine" in text
    assert "longitudinal" in text
    assert "Some later thing" not in text
    assert "Next directions" in sections


def test_report_forward_call_ranks_next_directions_above_synthesis(edc, tmp_path):
    """When both 'Next directions' AND 'Synthesis' exist, prefer
    'Next directions' (more operationally actionable)."""
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    _write_report(project_dir,
        "# REPORT\n\n"
        "## Synthesis\n\nThe synthesis paragraph.\n\n"
        "## Next directions\n\nThe forward direction.\n")
    text, sections = edc.parse_report_forward_call(project_dir / "REPORT.md")
    # Next directions should win
    assert "forward direction" in text
    assert "synthesis paragraph" not in text
    assert sections[0] == "Next directions"


def test_report_forward_call_missing_file_returns_empty(edc, tmp_path):
    text, sections = edc.parse_report_forward_call(tmp_path / "missing.md")
    assert text == ""
    assert sections == []


def test_report_forward_call_no_matching_section_returns_empty(edc, tmp_path):
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    _write_report(project_dir,
        "# REPORT\n\n## Methods\n\nMethods here.\n\n## Results\n\nResults here.\n")
    text, sections = edc.parse_report_forward_call(project_dir / "REPORT.md")
    assert text == ""
    # No matched sections (no sections from _REPORT_FORWARD_SECTIONS list)
    assert sections == []


# ---------------------------------------------------------------------------
# Fallback / edge cases
# ---------------------------------------------------------------------------

def test_no_signal_fallback_when_substories_missing(edc, tmp_path):
    """Missing 02_substories.md → no_signal_fallback=True; orchestrator
    should NOT emit a deck_close slide."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    _write_report(draft_dir.parent.parent, "# R\n\n## Next directions\n\nGo.\n")
    # No substories file written.
    report = edc.extract_deck_close(draft_dir)
    assert report.no_signal_fallback is True
    assert report.key_takeaways == []


def test_no_signal_fallback_when_no_conclusions_parsable(edc, tmp_path):
    """02_substories.md exists but no Conclusion fields → fallback."""
    draft_dir = _make_draft(tmp_path)
    (draft_dir / "narrative" / "02_substories.md").write_text(
        "# Substories\n\n### S1 — first\n\nNo conclusion field here.\n",
        encoding="utf-8")
    _write_throughline_v06(draft_dir, "TL.")
    report = edc.extract_deck_close(draft_dir)
    assert report.no_signal_fallback is True


def test_partial_signal_when_only_throughline_missing(edc, tmp_path):
    """Missing throughline → unified_point empty but signal still OK
    (composer can fill / Adam catches at Tier-F)."""
    draft_dir = _make_draft(tmp_path)
    _write_substories(draft_dir, [("S1", "", "C1.", "P1."),
                                    ("S2", "", "", "P2.")])
    _write_report(draft_dir.parent.parent,
        "# R\n\n## Future work\n\nFuture stuff.\n")
    report = edc.extract_deck_close(draft_dir)
    assert report.unified_point == ""
    assert report.no_signal_fallback is False  # takeaways still extracted
    assert len(report.key_takeaways) == 2


def test_partial_signal_when_only_report_missing(edc, tmp_path):
    """Missing REPORT → forward_call empty but takeaways extracted."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    _write_substories(draft_dir, [("S1", "", "C1.", "P1."),
                                    ("S2", "", "", "P2.")])
    # No REPORT.md written
    report = edc.extract_deck_close(draft_dir)
    assert report.forward_call == ""
    assert report.no_signal_fallback is False
    assert len(report.key_takeaways) == 2


def test_key_takeaways_capped_at_5(edc, tmp_path):
    """7 substories → only first 5 takeaways (D-086 schema cap)."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    substories = [(f"S{i}", "", f"C{i}.", f"P{i}.") for i in range(1, 8)]
    _write_substories(draft_dir, substories)
    report = edc.extract_deck_close(draft_dir)
    assert len(report.key_takeaways) == 5
    assert report.raw_evidence["n_takeaways_capped"] is True
    assert report.raw_evidence["n_takeaways_total_before_cap"] == 7


def test_raw_evidence_records_what_was_read(edc, tmp_path):
    """raw_evidence is the audit trail: which files were read +
    which substory IDs + which REPORT sections matched."""
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    _write_substories(draft_dir, [("S1", "S0→S1", "C1.", "P1."),
                                    ("S2", "S1→S2", "", "P2.")])
    _write_report(draft_dir.parent.parent,
        "# R\n\n## Next directions\n\nDo X.\n")
    report = edc.extract_deck_close(draft_dir)
    ev = report.raw_evidence
    assert ev["throughline_path"] == "narrative/00_throughline.md"
    assert ev["substories_path"] == "narrative/02_substories.md"
    assert ev["report_path"] == "REPORT.md"
    assert ev["substory_ids_seen"] == ["S1", "S2"]
    assert ev["n_substories"] == 2
    assert "Next directions" in ev["report_sections_matched"]
    assert ev["v3_2_transition_field_present"] is True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_writes_to_default_path(edc, tmp_path):
    """`extract_deck_close <draft_dir>` writes
    <draft_dir>/working/deck_close_signal.json by default."""
    draft_dir = _make_draft(tmp_path, project_id="cli_test")
    _write_throughline_v06(draft_dir, "TL.")
    _write_substories(draft_dir, [("S1", "", "C1.", "P1."),
                                    ("S2", "", "", "P2.")])
    _write_report(draft_dir.parent.parent,
        "# R\n\n## Next directions\n\nGo.\n")
    rc = edc.main([str(draft_dir), "--quiet"])
    assert rc == 0
    out_path = draft_dir / "working" / "deck_close_signal.json"
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == edc.SCHEMA_VERSION
    assert payload["project_id"] == "cli_test"
    assert payload["unified_point"] == "TL."
    assert payload["key_takeaways"] == ["C1.", "P2."]


def test_cli_writes_to_explicit_out_path(edc, tmp_path):
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    _write_substories(draft_dir, [("S1", "", "", "P1.")])
    out_path = tmp_path / "custom" / "signal.json"
    rc = edc.main([str(draft_dir), "--out", str(out_path), "--quiet"])
    assert rc == 0
    assert out_path.is_file()


def test_cli_missing_draft_dir_returns_2(edc, tmp_path):
    rc = edc.main([str(tmp_path / "nonexistent"), "--quiet"])
    assert rc == 2


def test_cli_stdout_when_out_dash(edc, tmp_path, capsys):
    draft_dir = _make_draft(tmp_path)
    _write_throughline_v06(draft_dir, "TL.")
    _write_substories(draft_dir, [("S1", "", "", "P1.")])
    rc = edc.main([str(draft_dir), "--out", "-", "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["schema_version"] == edc.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_strip_md_removes_inline_markdown(edc):
    assert edc._strip_md("**bold**") == "bold"
    assert edc._strip_md("*italic*") == "italic"
    assert edc._strip_md("`code`") == "code"
    assert edc._strip_md("a `b` and **c**") == "a b and c"


def test_first_n_sentences_handles_simple_prose(edc):
    text = ("First sentence. Second sentence. Third sentence. "
            "Fourth sentence.")
    assert edc._first_n_sentences(text, n=2) == \
        "First sentence. Second sentence."


def test_first_bullets_strips_markers(edc):
    body = "- First bullet\n- Second bullet\n- Third\n"
    bullets = edc._first_bullets(body, n=2)
    assert bullets == ["First bullet.", "Second bullet."]


def test_first_bullets_handles_numbered_list(edc):
    body = "1. Item one\n2. Item two\n3. Item three\n"
    bullets = edc._first_bullets(body, n=2)
    assert bullets == ["Item one.", "Item two."]


# ---------------------------------------------------------------------------
# Integration against live v0.6 drafts (skips if unavailable)
# ---------------------------------------------------------------------------

LIVE_BERIL_ROOT = Path("/Users/aparkin/Documents/Claude/Projects/"
                       "research-coscientist-dev/spike/beril-extended")


@pytest.mark.skipif(not (LIVE_BERIL_ROOT / "projects").is_dir(),
                    reason="live beril-extended fixture not available")
def test_live_fdm_draft_extracts_clean_signal(edc):
    """Smoke test against the v0.6 fdm draft_6 on disk. Pins the
    extractor against the actual artifact shapes it'll see in
    production (catches regressions from format drift)."""
    fdm_draft = (LIVE_BERIL_ROOT / "projects" / "functional_dark_matter"
                 / "talks" / "draft_6")
    if not fdm_draft.is_dir():
        pytest.skip("fdm draft_6 not on disk")
    report = edc.extract_deck_close(fdm_draft)
    assert report.project_id == "functional_dark_matter"
    assert report.no_signal_fallback is False
    assert report.unified_point  # non-empty
    assert len(report.key_takeaways) == 3  # 3 substories on fdm
    assert "17,344" in report.unified_point or \
           "17,344" in report.key_takeaways[0]


@pytest.mark.skipif(not (LIVE_BERIL_ROOT / "projects").is_dir(),
                    reason="live beril-extended fixture not available")
def test_live_ibd_draft_extracts_clean_signal(edc):
    """Smoke test against the v0.6 ibd draft_6."""
    ibd_draft = (LIVE_BERIL_ROOT / "projects" / "ibd_phage_targeting"
                 / "talks" / "draft_6")
    if not ibd_draft.is_dir():
        pytest.skip("ibd draft_6 not on disk")
    report = edc.extract_deck_close(ibd_draft)
    assert report.project_id == "ibd_phage_targeting"
    assert report.no_signal_fallback is False
    # ibd v0.6 has 4 substories
    assert len(report.key_takeaways) == 4
    # The throughline + first takeaway should mention some ibd-specific
    # vocabulary
    full = report.unified_point + " " + " ".join(report.key_takeaways)
    assert "ecotype" in full.lower() or "pathobiont" in full.lower()
