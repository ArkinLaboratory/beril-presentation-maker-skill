"""Unit tests for tools/smoke_v3_prompt.py (v0.5.1 Tier B / D-076).

Pure-function tests for:
  - validate_fragment(): the schema validator that catches the
    morning-abort bug classes (top-level shape + per-layout fields).
  - compute_prompt_sha(): the sha used by the gate-check.
  - write_record() / check_recent_pass(): the sidecar I/O + gating.

The LIVE smoke (run_smoke + invoke_claude) is intentionally NOT
tested here — that's gated behind BERIL_PRESENTATION_MAKER_RUN_LIVE
via tests/integration/. These unit tests mock-free verify the
mechanism around the live call.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from beril_presentation_maker.skill.tools import smoke_v3_prompt as smoke


# ---------------------------------------------------------------------------
# validate_fragment — happy path + bug-class coverage
# ---------------------------------------------------------------------------

def _good_fragment(layout: str = "section_divider",
                   content: dict | None = None) -> dict:
    """Minimal valid compose-fragment.v3 with one slide."""
    if content is None:
        content = {"punchline": "Test punchline", "substory_number": 1}
    return {
        "schema_version": "compose-fragment.v3",
        "substory_id": "S1",
        "slides": [
            {"layout": layout, "content": content},
        ],
    }


def test_validate_fragment_happy_path():
    """A well-formed fragment with one section_divider slide
    validates with zero issues."""
    assert smoke.validate_fragment(_good_fragment()) == []


def test_validate_fragment_accepts_v2_schema_version():
    """compose-fragment.v2 is also valid (backwards-compat for any
    v2-composed fragments inspected through the smoke validator)."""
    frag = _good_fragment()
    frag["schema_version"] = "compose-fragment.v2"
    assert smoke.validate_fragment(frag) == []


def test_validate_fragment_rejects_unknown_schema_version():
    frag = _good_fragment()
    frag["schema_version"] = "compose-fragment.v99"
    issues = smoke.validate_fragment(frag)
    assert any("schema_version" in i.field and "unexpected" in i.message
               for i in issues if i.field)


# Class 1 bugs: top-level shape (the morning-abort first bug)

def test_validate_fragment_class1_missing_slides_array():
    """The morning-abort Bug 1: v3 emitted {section_divider,
    content_slides} instead of {slides[]}. Validator must flag."""
    bad = {
        "schema_version": "compose-fragment.v3",
        "substory_id": "S1",
        "section_divider": {"layout": "section_divider", "content": {}},
        "content_slides": [],
    }
    issues = smoke.validate_fragment(bad)
    assert any(i.field == "slides" for i in issues)
    assert any("morning-abort" in i.message or "top-level" in i.message
               for i in issues)


def test_validate_fragment_class1_slides_not_a_list():
    bad = _good_fragment()
    bad["slides"] = {"not": "a list"}
    issues = smoke.validate_fragment(bad)
    assert any("must be a list" in i.message for i in issues)


def test_validate_fragment_class1_empty_slides():
    bad = _good_fragment()
    bad["slides"] = []
    issues = smoke.validate_fragment(bad)
    assert any("empty" in i.message for i in issues)


def test_validate_fragment_missing_substory_id():
    frag = _good_fragment()
    del frag["substory_id"]
    issues = smoke.validate_fragment(frag)
    assert any(i.field == "substory_id" for i in issues)


# Class 2 bugs: per-layout field-name drift (the morning-abort second
# bug). These are the specific 21-error pattern we saw on ibd + fdm.

def test_validate_fragment_class2_section_divider_missing_punchline():
    """The morning-abort Bug 2: section_divider emitted with
    {title, subtitle, transition_note} instead of {punchline,
    substory_number}. Validator must flag both required fields."""
    bad = _good_fragment(layout="section_divider", content={
        "title": "wrong field name",
        "subtitle": "wrong",
        "transition_note": "wrong",
    })
    issues = smoke.validate_fragment(bad)
    field_messages = {(i.field, i.message) for i in issues if i.field}
    assert ("punchline", "required field missing on section_divider") \
        in field_messages
    assert ("substory_number", "required field missing on section_divider") \
        in field_messages


def test_validate_fragment_class2_big_number_missing_headline():
    bad = _good_fragment(layout="big_number", content={
        "punchline": "wrong field",
        "metric_value": "97.2%",
    })
    issues = smoke.validate_fragment(bad)
    fields = {i.field for i in issues if i.field}
    assert "headline" in fields
    assert "subtitle" in fields


def test_validate_fragment_class2_claim_evidence_uses_title_not_punchline():
    """D-077 ground truth: claim_evidence requires `title` (not
    `punchline`). A fragment that emits `punchline` instead of
    `title` for claim_evidence should fail."""
    bad = _good_fragment(layout="claim_evidence", content={
        "punchline": "the C-slide-without-conclusion bug",
        "bullets": ["evidence"],
    })
    issues = smoke.validate_fragment(bad)
    fields = {i.field for i in issues if i.field}
    assert "title" in fields, (
        "validator must flag claim_evidence missing `title` even when "
        "`punchline` is present — D-077 ground truth")


def test_validate_fragment_class2_data_figure_missing_figure_field():
    bad = _good_fragment(layout="data_figure", content={
        "title": "ok",
        "caption": "ok",
        # missing: figure
    })
    issues = smoke.validate_fragment(bad)
    fields = {i.field for i in issues if i.field}
    assert "figure" in fields


def test_validate_fragment_unknown_layout():
    bad = _good_fragment(layout="bogus_layout", content={"title": "x"})
    issues = smoke.validate_fragment(bad)
    assert any("unknown layout" in i.message for i in issues)


def test_validate_fragment_slide_missing_content():
    bad = _good_fragment()
    del bad["slides"][0]["content"]
    issues = smoke.validate_fragment(bad)
    assert any(i.field == "content" for i in issues)


def test_validate_fragment_slide_missing_layout():
    bad = _good_fragment()
    del bad["slides"][0]["layout"]
    issues = smoke.validate_fragment(bad)
    assert any(i.field == "layout" for i in issues)


def test_layout_required_map_covers_all_16_v2_layouts():
    """v2's per-layout vocabulary is 16 layouts (15 core +
    data_table added in v0.3.2). The validator's required-fields
    map should cover them. Allow some omissions (e.g., the rare
    `acknowledgments` / `title_slide` layouts may be boilerplate-
    only with no Required: line); pin a minimum set explicitly."""
    expected = {
        "section_divider", "big_idea", "big_number", "claim_evidence",
        "two_column_compare", "data_figure", "data_table",
        "workflow_diagram", "methods_summary", "concept_illustration",
        "implications", "qa_anticipated",
    }
    actual = set(smoke.LAYOUT_REQUIRED_FIELDS.keys())
    missing = expected - actual
    assert not missing, (
        f"LAYOUT_REQUIRED_FIELDS missing v2 layouts: {missing}")


# ---------------------------------------------------------------------------
# compute_prompt_sha — determinism + sensitivity
# ---------------------------------------------------------------------------

def test_compute_prompt_sha_returns_hex_digest():
    """The sha is a stable 64-char hex string when all source files
    exist."""
    sha = smoke.compute_prompt_sha()
    assert isinstance(sha, str)
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_compute_prompt_sha_is_deterministic():
    """Two consecutive calls return the same sha (sanity)."""
    assert smoke.compute_prompt_sha() == smoke.compute_prompt_sha()


# ---------------------------------------------------------------------------
# write_record / check_recent_pass — gate-check semantics
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_record(tmp_path, monkeypatch):
    """Redirect PASS_RECORD + FAIL_RECORD into tmp_path so tests
    don't write to the real audit/ dir."""
    fake_audit = tmp_path / "audit"
    fake_audit.mkdir()
    fake_pass = fake_audit / "v3_smoke_pass.json"
    fake_fail = fake_audit / "v3_smoke_fail.json"
    monkeypatch.setattr(smoke, "SMOKE_DIR", fake_audit)
    monkeypatch.setattr(smoke, "PASS_RECORD", fake_pass)
    monkeypatch.setattr(smoke, "FAIL_RECORD", fake_fail)
    return fake_pass, fake_fail


def test_check_recent_pass_no_record(isolated_record):
    pass_path, _ = isolated_record
    ok, reason = smoke.check_recent_pass(record_path=pass_path)
    assert not ok
    assert "no v3 smoke-pass record" in reason


def test_check_recent_pass_stale(isolated_record):
    """A record older than SMOKE_FRESHNESS_DAYS days is stale."""
    pass_path, _ = isolated_record
    current_sha = "a" * 64
    stale_ts = datetime.now(timezone.utc) - timedelta(days=10)
    pass_path.write_text(json.dumps({
        "schema_version": "v3_smoke.v1",
        "passed": True,
        "timestamp": stale_ts.isoformat(),
        "prompts_sha": current_sha,
    }) + "\n", encoding="utf-8")
    ok, reason = smoke.check_recent_pass(
        record_path=pass_path, current_sha=current_sha)
    assert not ok
    assert "10 days old" in reason or "days old" in reason


def test_check_recent_pass_sha_mismatch(isolated_record):
    """A fresh record but with sha != current prompts means the
    prompts have changed since the smoke; gate fails."""
    pass_path, _ = isolated_record
    pass_path.write_text(json.dumps({
        "schema_version": "v3_smoke.v1",
        "passed": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts_sha": "old" * 22,  # 66 chars; sha-shape but different
    }) + "\n", encoding="utf-8")
    ok, reason = smoke.check_recent_pass(
        record_path=pass_path, current_sha="new" * 22)
    assert not ok
    assert "sha mismatch" in reason


def test_check_recent_pass_ok(isolated_record):
    """Fresh record + matching sha + passed=true → gate ok."""
    pass_path, _ = isolated_record
    current_sha = "deadbeef" * 8  # 64 chars
    pass_path.write_text(json.dumps({
        "schema_version": "v3_smoke.v1",
        "passed": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts_sha": current_sha,
    }) + "\n", encoding="utf-8")
    ok, reason = smoke.check_recent_pass(
        record_path=pass_path, current_sha=current_sha)
    assert ok
    assert "ok" in reason.lower()


def test_check_recent_pass_passed_false(isolated_record):
    """A record with passed=false counts as no-pass."""
    pass_path, _ = isolated_record
    current_sha = "deadbeef" * 8
    pass_path.write_text(json.dumps({
        "schema_version": "v3_smoke.v1",
        "passed": False,  # the bug
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts_sha": current_sha,
    }) + "\n", encoding="utf-8")
    ok, reason = smoke.check_recent_pass(
        record_path=pass_path, current_sha=current_sha)
    assert not ok
    assert "passed=false" in reason


def test_write_record_roundtrip(isolated_record):
    """write_record + check_recent_pass round-trip on the same
    sha → gate passes."""
    pass_path, _ = isolated_record
    current_sha = smoke.compute_prompt_sha()
    smoke.write_record(
        pass_path, True, [],
        evidence={"prompts_sha": current_sha, "fragment_only": False})
    ok, _ = smoke.check_recent_pass(
        record_path=pass_path, current_sha=current_sha)
    assert ok


# ---------------------------------------------------------------------------
# CLI smoke (no LLM invocation)
# ---------------------------------------------------------------------------

def test_cli_check_recent_returns_rc1_when_no_record(isolated_record):
    """--check-recent with no pass record returns rc=1 (the gate
    will reject `--prompts-version v3`)."""
    rc = smoke.main(["--check-recent"])
    assert rc == 1


def test_cli_check_recent_returns_rc0_when_fresh(isolated_record):
    """--check-recent with a fresh matching pass record returns rc=0."""
    pass_path, _ = isolated_record
    current_sha = smoke.compute_prompt_sha()
    smoke.write_record(
        pass_path, True, [],
        evidence={"prompts_sha": current_sha, "fragment_only": False})
    rc = smoke.main(["--check-recent"])
    assert rc == 0


def test_fixture_dir_exists():
    """The fixture dir must exist on disk so a smoke run doesn't
    immediately fail with ENOENT."""
    assert smoke.FIXTURE_DIR.is_dir(), (
        f"smoke fixture missing at {smoke.FIXTURE_DIR}")
    # Spot-check the required fixture files.
    assert (smoke.FIXTURE_DIR / "REPORT.md").is_file()
    assert (smoke.FIXTURE_DIR / "narrative" / "02_substories.md").is_file()
    assert (smoke.FIXTURE_DIR / "working" / "00_plan.md").is_file()


# ---------------------------------------------------------------------------
# v0.6 Tier C — --version v3.1 stacked concat (D-080)
# ---------------------------------------------------------------------------
#
# v3.1 stacks the figure-utilization overlay on the v3 chain. The
# smoke must compose against the right stack so the live LLM gets
# the v3.1 instructions; a v3-only smoke wouldn't validate v3.1.

def test_build_concat_variadic_two_sources(tmp_path):
    """build_concat with 2 sources = v3 chain. Bytes appended in
    order."""
    a = tmp_path / "a.md"
    a.write_text("==A==\n", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("==B==\n", encoding="utf-8")
    out = tmp_path / "out.md"
    smoke.build_concat(a, b, out=out)
    body = out.read_text(encoding="utf-8")
    a_pos = body.find("==A==")
    b_pos = body.find("==B==")
    assert a_pos >= 0 and b_pos >= 0
    assert a_pos < b_pos


def test_build_concat_variadic_three_sources(tmp_path):
    """build_concat with 3 sources = v3.1 chain. Bytes in order."""
    a = tmp_path / "a.md"
    a.write_text("==A==\n", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("==B==\n", encoding="utf-8")
    c = tmp_path / "c.md"
    c.write_text("==C==\n", encoding="utf-8")
    out = tmp_path / "out.md"
    smoke.build_concat(a, b, c, out=out)
    body = out.read_text(encoding="utf-8")
    a_pos = body.find("==A==")
    b_pos = body.find("==B==")
    c_pos = body.find("==C==")
    assert a_pos >= 0 and b_pos >= 0 and c_pos >= 0
    assert a_pos < b_pos < c_pos


def test_run_smoke_rejects_invalid_version(tmp_path):
    """run_smoke must validate the version arg and raise ValueError
    on a string that's not 'v3', 'v3.1', 'v3.2', or 'v3.3'."""
    import pytest as _pytest
    with _pytest.raises(ValueError, match="v3.*v3.1.*v3.2.*v3.3"):
        smoke.run_smoke(fragment_only=True, keep_tmpdir=False,
                        version="v4")


def test_cli_version_flag_documented():
    """`--help` lists the --version flag + all four choices so
    operators discover the v3.1/v3.2/v3.3 paths."""
    import subprocess as _sp
    result = _sp.run(
        [sys.executable, str(smoke.SKILL_REPO_ROOT / "src"
                              / "beril_presentation_maker" / "skill"
                              / "tools" / "smoke_v3_prompt.py"),
         "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--version" in help_text
    assert "v3.1" in help_text
    assert "v3.2" in help_text
    assert "v3.3" in help_text
    # Default explicitly named so operators know what they get
    assert "default" in help_text.lower()


def test_cli_default_version_is_v3_3():
    """Per v0.8 Tier F (D-095): default --version is v3.3 (the
    v0.8 default; runs the clean-overlay substory_design that
    fixes the v3.2 recency-bias field-drop bug). Pin so a future
    default change is intentional."""
    src = (smoke.SKILL_REPO_ROOT / "src" / "beril_presentation_maker"
           / "skill" / "tools" / "smoke_v3_prompt.py").read_text(
               encoding="utf-8")
    # The default v3.3 must appear in the --version flag definition.
    # Use a regex tolerant of formatting (single-line vs broken
    # across two physical lines).
    import re as _re
    pat = _re.compile(
        r'choices=\["v3",\s*"v3\.1",\s*"v3\.2",\s*"v3\.3"\]\s*,\s*'
        r'default="v3\.3"',
        _re.DOTALL,
    )
    assert pat.search(src), (
        "expected `choices=[\"v3\", \"v3.1\", \"v3.2\", \"v3.3\"], "
        "default=\"v3.3\"` in smoke source; if this changed "
        "intentionally, update the test + V0_8 docs.")



# ===========================================================================
# v0.7 Tier F — --version v3.2 stacked concat (D-085 / D-086 / D-087)
# ===========================================================================
#
# v3.2 stacks the figure-relevance + deck_close + arc-transition
# overlays on the v3.1 chain (for slide_compose) and adds the
# transition_from_prior overlay on the v3 chain (for substory_design).
# A v3.2 smoke implicitly validates the v3 + v3.1 chains too.


def test_v3_2_overlay_files_exist_on_disk():
    """v3.2 overlays for BOTH slide_compose and substory_design
    must ship with the skill (per Tier A + Tier B)."""
    assert smoke.SLIDE_OVERLAY_V3_2.is_file(), (
        f"slide_compose v3.2 overlay missing at "
        f"{smoke.SLIDE_OVERLAY_V3_2}")
    assert smoke.SUBSTORY_OVERLAY_V3_2.is_file(), (
        f"substory_design v3.2 overlay missing at "
        f"{smoke.SUBSTORY_OVERLAY_V3_2}")


def test_compute_prompt_sha_includes_v3_2_overlays(tmp_path, monkeypatch):
    """compute_prompt_sha must include both v3.2 overlay files in
    the sha computation — so a v3-only or v3.1-only pass record
    can't satisfy a v3.2 gate (the sha would differ)."""
    # Read the actual sha; should be deterministic.
    sha = smoke.compute_prompt_sha()
    assert len(sha) == 64  # SHA-256 hex
    # Now mutate the v3.2 slide overlay and re-compute; sha must
    # change. Use a monkeypatch that points the constant at a
    # different file.
    fake_overlay = tmp_path / "fake_slide_v3_2_overlay.md"
    fake_overlay.write_text("UNIQUE_TEST_MARKER_v3_2_slide\n",
                             encoding="utf-8")
    monkeypatch.setattr(smoke, "SLIDE_OVERLAY_V3_2", fake_overlay)
    new_sha = smoke.compute_prompt_sha()
    assert new_sha != sha, (
        "compute_prompt_sha must change when v3.2 slide overlay "
        "content changes; a v3.1 pass record would otherwise "
        "satisfy a v3.2 gate")


def test_compute_prompt_sha_includes_v3_2_substory_overlay(
        tmp_path, monkeypatch):
    """Same as above for the v3.2 substory_design overlay."""
    sha = smoke.compute_prompt_sha()
    fake_overlay = tmp_path / "fake_substory_v3_2_overlay.md"
    fake_overlay.write_text("UNIQUE_TEST_MARKER_v3_2_substory\n",
                             encoding="utf-8")
    monkeypatch.setattr(smoke, "SUBSTORY_OVERLAY_V3_2", fake_overlay)
    new_sha = smoke.compute_prompt_sha()
    assert new_sha != sha, (
        "compute_prompt_sha must change when v3.2 substory overlay "
        "content changes")


def test_run_smoke_v3_2_validation_passes(tmp_path, monkeypatch):
    """run_smoke must accept version='v3.2' (the v0.7 default)
    without raising ValueError on the validation step.

    We don't actually invoke the LLM here. Strategy: monkeypatch
    FIXTURE_DIR to a non-existent path so the fixture-check raises
    FileNotFoundError BEFORE the smoke would invoke claude. If
    version validation rejected 'v3.2', ValueError would raise
    FIRST (before the fixture check) and the FileNotFoundError
    would never fire — that's what this test pins."""
    import pytest as _pytest
    monkeypatch.setattr(smoke, "FIXTURE_DIR", tmp_path / "no_such_fixture")
    with _pytest.raises(FileNotFoundError, match="fixture missing"):
        smoke.run_smoke(fragment_only=True, keep_tmpdir=False,
                        version="v3.2")


def test_build_concat_variadic_four_sources(tmp_path):
    """build_concat with 4 sources = v3.2 slide_compose chain.
    Bytes in concat order: v2, v3-overlay, v3.1-overlay, v3.2-overlay."""
    a = tmp_path / "a.md"
    a.write_text("==A==\n", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("==B==\n", encoding="utf-8")
    c = tmp_path / "c.md"
    c.write_text("==C==\n", encoding="utf-8")
    d = tmp_path / "d.md"
    d.write_text("==D==\n", encoding="utf-8")
    out = tmp_path / "out.md"
    smoke.build_concat(a, b, c, d, out=out)
    body = out.read_text(encoding="utf-8")
    a_pos = body.find("==A==")
    b_pos = body.find("==B==")
    c_pos = body.find("==C==")
    d_pos = body.find("==D==")
    assert a_pos >= 0 and b_pos >= 0 and c_pos >= 0 and d_pos >= 0
    assert a_pos < b_pos < c_pos < d_pos, (
        f"4-source build_concat order wrong: a={a_pos}, b={b_pos}, "
        f"c={c_pos}, d={d_pos}; expected strictly ascending")


# ===========================================================================
# v0.8 Tier F — --version v3.3 + validate_substory_design_fields (D-095)
# ===========================================================================
#
# v3.3 substory_design is a CLEAN overlay on v1 (NOT stacked on v3
# or v3.2). It consolidates v3 Q/A/R/C + v3.2 transition_from_prior
# into one unified template with explicit supersede-clauses, to fix
# the v3.2 recency-bias displacement bug live-discovered in v0.7
# Tier G where LLMs treated v3.2's example as authoritative and
# dropped v3-required fields (Conclusion-for-next, Transition-from-
# prior).
#
# slide_compose stack is UNCHANGED from v3.2 (D-095 scope decision).
#
# The load-bearing piece is validate_substory_design_fields(), a
# smoke-time backstop that parses the produced 02_substories.md
# and asserts the v3.3 fields appear per-substory. The unit suite
# can't catch this — it's emergent LLM behavior — but this smoke
# validator can.


def test_v3_3_overlay_file_exists_on_disk():
    """v3.3 substory_design overlay must ship with the skill
    (per Tier C, commit c83db0f). slide_compose has no v3.3
    overlay (D-095 scopes v3.3 to substory_design only)."""
    assert smoke.SUBSTORY_OVERLAY_V3_3.is_file(), (
        f"substory_design v3.3 overlay missing at "
        f"{smoke.SUBSTORY_OVERLAY_V3_3}")


def test_compute_prompt_sha_includes_v3_3_substory_overlay(
        tmp_path, monkeypatch):
    """compute_prompt_sha must include the v3.3 substory_design
    overlay in the sha computation — so a v3.2 pass record can't
    satisfy a v3.3 gate (the sha would differ). This forces a
    re-smoke when operators switch from v3.2 to v3.3."""
    sha = smoke.compute_prompt_sha()
    assert len(sha) == 64
    fake_overlay = tmp_path / "fake_substory_v3_3_overlay.md"
    fake_overlay.write_text("UNIQUE_TEST_MARKER_v3_3_substory\n",
                             encoding="utf-8")
    monkeypatch.setattr(smoke, "SUBSTORY_OVERLAY_V3_3", fake_overlay)
    new_sha = smoke.compute_prompt_sha()
    assert new_sha != sha, (
        "compute_prompt_sha must change when v3.3 substory overlay "
        "content changes; a v3.2 pass record would otherwise "
        "satisfy a v3.3 gate")


def test_run_smoke_v3_3_validation_passes(tmp_path, monkeypatch):
    """run_smoke must accept version='v3.3' (the v0.8 default)
    without raising ValueError on the validation step.

    Same monkeypatch-the-fixture-away strategy as the v3.2 test:
    if version validation rejected 'v3.3', ValueError would raise
    FIRST and the FileNotFoundError would never fire."""
    import pytest as _pytest
    monkeypatch.setattr(smoke, "FIXTURE_DIR", tmp_path / "no_such_fixture")
    with _pytest.raises(FileNotFoundError, match="fixture missing"):
        smoke.run_smoke(fragment_only=True, keep_tmpdir=False,
                        version="v3.3")


# --- validate_substory_design_fields() tests --------------------------------


def _v3_3_valid_single_substory_md() -> str:
    """Smoke-fixture-shaped output (1 substory): Question present;
    Conclusion-for-next + Transition-from-prior BOTH omitted (only
    substory is also the final + first, so neither field applies)."""
    return (
        "# Substories — smoke_v3_fixture\n"
        "\n"
        "### S1 — Which cluster carries the enrichment?\n"
        "\n"
        "**Question:** Which of the three clusters carries the "
        "biomarker-X enrichment?\n"
        "\n"
        "**Punchline:** Cluster B (n=42) is significantly enriched.\n"
        "\n"
        "**Analyses cited:** A001, A002\n"
        "\n"
        "**Cluster rationale:** single cluster fixture.\n"
        "\n"
        "**Slide budget:** 4\n"
    )


def _v3_3_valid_multi_substory_md() -> str:
    """3-substory output: S1 has Question + Conclusion; S2 has
    Question + Transition + Conclusion; S3 has Question + Transition
    (final, no Conclusion). All v3.3 contracts satisfied."""
    return (
        "# Substories — multi\n"
        "\n"
        "### S1 — First arc\n"
        "**Question:** Q1?\n"
        "**Punchline:** P1.\n"
        "**Conclusion for next substory:** This sets up S2's frame.\n"
        "\n"
        "### S2 — Middle arc\n"
        "**Transition from prior:** S1 established X; now we ask Y.\n"
        "**Question:** Q2?\n"
        "**Punchline:** P2.\n"
        "**Conclusion for next substory:** This sets up S3's frame.\n"
        "\n"
        "### S3 — Final arc\n"
        "**Transition from prior:** S2 showed Y; now we close.\n"
        "**Question:** Q3?\n"
        "**Punchline:** P3.\n"
    )


def test_validate_substory_design_fields_passes_on_single_substory():
    """Smoke-fixture-shaped single substory: Question only;
    Conclusion + Transition both correctly omitted. No issues."""
    issues = smoke.validate_substory_design_fields(
        _v3_3_valid_single_substory_md())
    assert issues == [], (
        f"single-substory v3.3-valid output should produce no "
        f"issues; got: {[i.message for i in issues]}")


def test_validate_substory_design_fields_passes_on_multi_substory():
    """3-substory output with all fields correctly placed: S1 has
    Conclusion (not Transition); S3 has Transition (not Conclusion);
    S2 has both. All v3.3 contracts satisfied; no issues."""
    issues = smoke.validate_substory_design_fields(
        _v3_3_valid_multi_substory_md())
    assert issues == [], (
        f"multi-substory v3.3-valid output should produce no "
        f"issues; got: {[i.message for i in issues]}")


def test_validate_substory_design_fields_catches_missing_question():
    """If a substory drops the **Question:** field, the validator
    flags it. Question is required on every substory."""
    bad = (
        "### S1 — first\n"
        "**Punchline:** missing Question field above.\n"
    )
    issues = smoke.validate_substory_design_fields(bad)
    assert any("Question" in i.field and "S1" in i.message
               for i in issues), (
        f"expected Question-missing issue on S1; got: "
        f"{[(i.field, i.message) for i in issues]}")


def test_validate_substory_design_fields_catches_dropped_conclusion():
    """THE BUG v3.3 WAS DESIGNED TO PREVENT: non-final substory
    drops **Conclusion for next substory:**. v3.2 produced output
    that dropped this field on every substory. v3.3 + this
    validator catches the regression."""
    bad = (
        "### S1 — first of three\n"
        "**Question:** Q1?\n"
        "**Punchline:** P1.\n"
        "\n"  # Missing Conclusion for next substory — THE BUG
        "### S2 — middle\n"
        "**Transition from prior:** ok\n"
        "**Question:** Q2?\n"
        "**Conclusion for next substory:** ok\n"
        "\n"
        "### S3 — final\n"
        "**Transition from prior:** ok\n"
        "**Question:** Q3?\n"
    )
    issues = smoke.validate_substory_design_fields(bad)
    assert any("Conclusion for next substory" in i.field
               and "S1" in i.message
               for i in issues), (
        f"expected Conclusion-missing issue on S1 (non-final "
        f"substory); got: {[(i.field, i.message) for i in issues]}")


def test_validate_substory_design_fields_catches_dropped_transition():
    """v3.3 also requires **Transition from prior:** on every
    non-first substory. v3.2 dropped this too — same recency-bias
    bug class."""
    bad = (
        "### S1 — first\n"
        "**Question:** Q1?\n"
        "**Conclusion for next substory:** ok\n"
        "\n"
        "### S2 — middle\n"
        "**Question:** Q2?\n"  # Missing Transition from prior — BUG
        "**Conclusion for next substory:** ok\n"
        "\n"
        "### S3 — final\n"
        "**Transition from prior:** ok\n"
        "**Question:** Q3?\n"
    )
    issues = smoke.validate_substory_design_fields(bad)
    assert any("Transition from prior" in i.field
               and "S2" in i.message
               for i in issues), (
        f"expected Transition-missing issue on S2 (non-first "
        f"substory); got: {[(i.field, i.message) for i in issues]}")


def test_validate_substory_design_fields_advises_misplaced_conclusion_on_final(
        capsys):
    """**Conclusion for next substory:** on the FINAL substory is
    over-zealous (no next substory to hand off to). Per v0.8 Tier-G
    live discovery, the LLM tends to emit it anyway when the
    template makes it look required — the rule was DEMOTED from
    hard fail to advisory. Validator still surfaces the issue via
    stderr, but does NOT add it to the issues list (smoke passes).
    """
    bad = (
        "### S1 — first\n"
        "**Question:** Q1?\n"
        "**Conclusion for next substory:** ok\n"
        "\n"
        "### S2 — final\n"
        "**Transition from prior:** ok\n"
        "**Question:** Q2?\n"
        "**Conclusion for next substory:** WRONG — nothing follows\n"
    )
    issues = smoke.validate_substory_design_fields(bad)
    # NO hard fail — issues list must be empty for this misplaced-
    # on-edge case (it's a wart, not a content bug).
    assert issues == [], (
        f"misplaced Conclusion-on-final should be ADVISORY, not a "
        f"hard fail; got: {[(i.field, i.message) for i in issues]}")
    # But the advisory MUST print to stderr so the operator sees it.
    captured = capsys.readouterr()
    assert "[smoke advisory]" in captured.err
    assert "Conclusion for next substory" in captured.err
    assert "S2" in captured.err
    assert "FINAL" in captured.err


def test_validate_substory_design_fields_advises_misplaced_transition_on_first(
        capsys):
    """**Transition from prior:** on S1 is over-zealous (no prior).
    Same v0.8 Tier-G demotion rationale as Conclusion-on-final:
    advisory, not hard fail."""
    bad = (
        "### S1 — first\n"
        "**Transition from prior:** WRONG — nothing precedes\n"
        "**Question:** Q1?\n"
        "**Conclusion for next substory:** ok\n"
        "\n"
        "### S2 — final\n"
        "**Transition from prior:** ok\n"
        "**Question:** Q2?\n"
    )
    issues = smoke.validate_substory_design_fields(bad)
    assert issues == [], (
        f"misplaced Transition-on-first should be ADVISORY, not a "
        f"hard fail; got: {[(i.field, i.message) for i in issues]}")
    captured = capsys.readouterr()
    assert "[smoke advisory]" in captured.err
    assert "Transition from prior" in captured.err
    assert "S1" in captured.err
    assert "FIRST" in captured.err


def test_validate_substory_design_fields_handles_empty_input():
    """Empty input is a smoke failure: substory_design stage
    produced no output. Validator must flag rather than silently
    pass (which would let a broken pipeline through)."""
    issues = smoke.validate_substory_design_fields("")
    assert any("empty" in i.message.lower()
               for i in issues), (
        f"expected empty-output issue; got: "
        f"{[(i.field, i.message) for i in issues]}")


def test_validate_substory_design_fields_handles_missing_headers():
    """If the output has no ### S{N} headers, the markdown is
    malformed — flag rather than silently pass."""
    bad = (
        "# Substories\n"
        "\n"
        "Lorem ipsum but no substory headers.\n"
        "**Question:** Q?\n"
    )
    issues = smoke.validate_substory_design_fields(bad)
    assert any("substory_headers" in i.field
               or "no ### S" in i.message
               for i in issues), (
        f"expected malformed-markdown issue; got: "
        f"{[(i.field, i.message) for i in issues]}")
