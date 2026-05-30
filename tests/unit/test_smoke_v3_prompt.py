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
    on a string that's not 'v3', 'v3.1', or 'v3.2'."""
    import pytest as _pytest
    with _pytest.raises(ValueError, match="v3.*v3.1.*v3.2"):
        smoke.run_smoke(fragment_only=True, keep_tmpdir=False,
                        version="v4")


def test_cli_version_flag_documented():
    """`--help` lists the --version flag + all three choices so
    operators discover the v3.1/v3.2 paths."""
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
    # Default explicitly named so operators know what they get
    assert "default" in help_text.lower()


def test_cli_default_version_is_v3_2():
    """Per v0.7 Tier F: default --version is v3.2 (validates the
    full v0.7 stack; a v3.2 smoke implicitly covers v3 + v3.1).
    Pin so a future default change is intentional."""
    src = (smoke.SKILL_REPO_ROOT / "src" / "beril_presentation_maker"
           / "skill" / "tools" / "smoke_v3_prompt.py").read_text(
               encoding="utf-8")
    # The default v3.2 must appear in the --version flag definition.
    assert ('choices=["v3", "v3.1", "v3.2"], default="v3.2"' in src), (
        "expected `choices=[\"v3\", \"v3.1\", \"v3.2\"], "
        "default=\"v3.2\"` in smoke source; if this changed "
        "intentionally, update the test + V0_7 docs.")



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
