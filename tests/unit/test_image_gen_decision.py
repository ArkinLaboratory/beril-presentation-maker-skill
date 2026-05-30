"""Tests for v0.3.3 image_gen_decision Tier 1 decision layer.

Per V0_3_3_ARCHITECTURE.md §13 Tier 1 plan: 10 tests covering each
rule + edge cases + closed-set guarantee.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load image_gen_decision via spec_from_file_location so the test file
# doesn't need to be inside the skill package. Mirrors the pattern
# used by other unit tests in this suite.
_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import slide_spec  # noqa: E402
import image_gen_decision as igd  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub(layout: str, **content_overrides) -> dict:
    """Build a minimal slide stub with the given layout. The 'content'
    dict is layout-specific in real fragments; tests only need fields
    the decision layer reads (image_path on concept_illustration,
    bullets on claim_evidence).

    v0.7/D-088 Tier D.0: claim_evidence stubs default to 3 bullets so
    they reach the judge_fn by default (the eligibility gate per
    D-088 requires ≥3 bullets). Tests that want to exercise the
    sub-3-bullet path pass bullets=[...] explicitly.
    """
    content = {"title": "Test slide title."}
    if layout == "concept_illustration":
        # Default to slide_compose's TBD-placeholder convention.
        content.setdefault("image_path", "{TBD}")
        content.setdefault("image_prompt", "test prompt")
        content.setdefault("style", "scientific_illustration")
    elif layout == "claim_evidence":
        # Default to 3 bullets so D-088 eligibility passes by default.
        content.setdefault("bullets", [
            "First mechanism bullet.",
            "Second mechanism bullet.",
            "Third mechanism bullet.",
        ])
    content.update(content_overrides)
    return {"layout": layout, "content": content}


# ---------------------------------------------------------------------------
# Rule-by-rule tests
# ---------------------------------------------------------------------------

def test_rule_4_concept_illustration_strong_emits():
    """concept_illustration on STRONG tier with TBD placeholder → emit."""
    d = igd.decide(_stub("concept_illustration"), tier="STRONG", mode="talk-30")
    assert d.emit is True
    assert "concept_illustration" in d.reason


def test_rule_1_data_figure_skipped():
    d = igd.decide(_stub("data_figure"), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "own figure" in d.reason


def test_rule_2_data_table_skipped():
    d = igd.decide(_stub("data_table"), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "own figure" in d.reason


@pytest.mark.parametrize(
    "layout",
    [
        "title", "section_divider", "acknowledgments", "references",
        "qa_anticipated", "methods_summary", "cross_tenant_integration",
    ],
)
def test_rule_3_structural_layouts_skipped(layout: str):
    d = igd.decide(_stub(layout), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "structural" in d.reason


@pytest.mark.parametrize(
    "layout",
    [
        "claim_evidence", "workflow_diagram", "two_column_compare",
        "big_idea", "big_number", "implications",
    ],
)
def test_rule_5_deferred_layouts_skipped(layout: str):
    """v0.3.7+: when no judge_fn is provided, deferred layouts default to
    emit=false (preserving pre-v0.3.7 conservative behavior). The CLI
    wires llm_judge as the default; tests that don't pass judge_fn get
    the conservative fallback."""
    d = igd.decide(_stub(layout), tier="STRONG", mode="talk-30")
    assert d.emit is False
    assert "no judge_fn" in d.reason or "needs LLM judgment" in d.reason


def test_rule_6_exploratory_blocks_concept_illustration_by_default():
    """EXPLORATORY tier blocks concept_illustration without opt-in."""
    d = igd.decide(
        _stub("concept_illustration"), tier="EXPLORATORY", mode="talk-30"
    )
    assert d.emit is False
    assert "EXPLORATORY" in d.reason


def test_rule_6_exploratory_with_opt_in_lets_concept_illustration_through():
    """The opt-in inversion of rule 6: --image-allow-exploratory."""
    d = igd.decide(
        _stub("concept_illustration"),
        tier="EXPLORATORY", mode="talk-30",
        user_opt_in_exploratory=True,
    )
    assert d.emit is True


def test_concept_illustration_with_resolved_image_path_skips():
    """If concept_illustration somehow already has a real image path
    (resume mode? cached fragment?), don't re-generate."""
    d = igd.decide(
        _stub("concept_illustration",
              image_path="working/05_images/S2-pos4.png"),
        tier="STRONG", mode="talk-30",
    )
    assert d.emit is False
    assert "skip re-generation" in d.reason


def test_unknown_layout_raises():
    """Layout not in slide_spec.LAYOUTS must raise UnknownLayoutError."""
    with pytest.raises(igd.UnknownLayoutError):
        igd.decide({"layout": "future_layout_v0_4"},
                   tier="STRONG", mode="talk-30")


def test_missing_layout_raises_keyerror():
    with pytest.raises(KeyError):
        igd.decide({"content": {}}, tier="STRONG", mode="talk-30")


# ---------------------------------------------------------------------------
# Closed-set guarantee
# ---------------------------------------------------------------------------

def test_all_layouts_have_a_verdict():
    """Every layout in slide_spec.LAYOUTS must produce a Decision.

    This is the closed-set assertion: drift between slide_spec and
    the decision-layer categorization surfaces immediately on any
    layout addition that doesn't update image_gen_decision.py."""
    for layout in slide_spec.LAYOUTS:
        d = igd.decide(_stub(layout), tier="STRONG", mode="talk-30")
        assert isinstance(d.emit, bool)
        assert d.layout == layout
        # concept_illustration is the only YES; everything else is NO.
        if layout == "concept_illustration":
            assert d.emit is True, (
                f"{layout}: STRONG tier with TBD placeholder should emit"
            )
        else:
            assert d.emit is False, (
                f"{layout}: should not emit in v0.3.3 (got {d.reason!r})"
            )


# ---------------------------------------------------------------------------
# Fragment-level tests
# ---------------------------------------------------------------------------

def test_decide_fragment_walks_all_slides():
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S2",
        "slides": [
            _stub("section_divider"),
            _stub("claim_evidence"),
            _stub("concept_illustration"),
            _stub("data_figure"),
        ],
    }
    decisions = igd.decide_fragment(
        fragment, tier="STRONG", mode="talk-30"
    )
    assert len(decisions) == 4
    assert [d.layout for d in decisions] == [
        "section_divider", "claim_evidence",
        "concept_illustration", "data_figure",
    ]
    assert [d.emit for d in decisions] == [False, False, True, False]
    # Slide_id format: substory_id-pos{N}, 0-indexed.
    assert [d.slide_id for d in decisions] == [
        "S2-pos0", "S2-pos1", "S2-pos2", "S2-pos3",
    ]
    assert all(d.substory_id == "S2" for d in decisions)


def test_decide_fragment_handles_intro_kind():
    """Intro fragments don't carry substory_id; the layer should label
    them 'intro' so slide_ids don't collide with 'pos0' from another
    substory-less fragment."""
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "intro",
        "slides": [
            _stub("section_divider"),
            _stub("claim_evidence"),
        ],
    }
    decisions = igd.decide_fragment(
        fragment, tier="STRONG", mode="talk-30"
    )
    assert len(decisions) == 2
    assert all(d.substory_id == "intro" for d in decisions)
    assert decisions[0].slide_id == "intro-pos0"


# ---------------------------------------------------------------------------
# Envelope + CLI tests
# ---------------------------------------------------------------------------

def test_emit_decisions_writes_envelope(tmp_path: Path):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    s1_fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [
            _stub("section_divider"),
            _stub("concept_illustration"),
        ],
    }
    s2_fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S2",
        "slides": [
            _stub("claim_evidence"),
            _stub("concept_illustration"),
        ],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(s1_fragment))
    (slides_dir / "S2_slides.json").write_text(json.dumps(s2_fragment))

    envelope = igd.emit_decisions(
        slides_dir, tier="STRONG", mode="talk-30"
    )
    assert envelope["schema_version"] == "image-decisions.v1"
    assert envelope["tier"] == "STRONG"
    assert envelope["user_opt_in_exploratory"] is False
    decisions = envelope["decisions"]
    # 4 slides total (2 per fragment), 2 concept_illustration → 2 emit.
    assert len(decisions) == 4
    assert sum(1 for d in decisions if d["emit"]) == 2
    yes = igd.yes_decisions(envelope)
    assert len(yes) == 2
    assert {d["slide_id"] for d in yes} == {"S1-pos1", "S2-pos1"}


def test_emit_decisions_skips_unparseable_fragment(tmp_path: Path, capsys):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    # Valid one
    valid = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [_stub("concept_illustration")],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(valid))
    # Malformed
    (slides_dir / "broken.json").write_text("{not valid json")

    envelope = igd.emit_decisions(
        slides_dir, tier="STRONG", mode="talk-30"
    )
    captured = capsys.readouterr()
    assert "broken.json" in captured.err
    assert "could not parse" in captured.err
    # Valid fragment still processed.
    assert len(envelope["decisions"]) == 1
    assert envelope["decisions"][0]["emit"] is True


def test_cli_emit_decisions_writes_file(tmp_path: Path):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [_stub("concept_illustration")],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(fragment))
    out_path = tmp_path / "decisions.json"

    rc = igd.main([
        "emit-decisions",
        "--slides-dir", str(slides_dir),
        "--tier", "STRONG",
        "--mode", "talk-30",
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.is_file()
    envelope = json.loads(out_path.read_text())
    assert envelope["schema_version"] == "image-decisions.v1"
    assert len(envelope["decisions"]) == 1


def test_cli_emit_decisions_with_allow_exploratory(tmp_path: Path):
    slides_dir = tmp_path / "03_slides"
    slides_dir.mkdir()
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [_stub("concept_illustration")],
    }
    (slides_dir / "S1_slides.json").write_text(json.dumps(fragment))
    out_path = tmp_path / "decisions.json"

    rc = igd.main([
        "emit-decisions",
        "--slides-dir", str(slides_dir),
        "--tier", "EXPLORATORY",
        "--mode", "talk-30",
        "--allow-exploratory",
        "--out", str(out_path),
    ])
    assert rc == 0
    envelope = json.loads(out_path.read_text())
    assert envelope["user_opt_in_exploratory"] is True
    assert envelope["decisions"][0]["emit"] is True


def test_cli_emit_decisions_missing_slides_dir(tmp_path: Path, capsys):
    out_path = tmp_path / "decisions.json"
    rc = igd.main([
        "emit-decisions",
        "--slides-dir", str(tmp_path / "nonexistent"),
        "--tier", "STRONG",
        "--mode", "talk-30",
        "--out", str(out_path),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err


# ---------------------------------------------------------------------------
# v0.3.7+ LLM-judgment layer
# ---------------------------------------------------------------------------

class TestJudgeFnIntegration:
    """Tests for the v0.3.7 judge_fn callback integration into decide()."""

    def test_judge_fn_yes_flips_deferred_to_emit_true(self):
        """A judge_fn returning (True, reason) should make a deferred-layout
        slide emit=true with the LLM-judged reason."""
        def stub_yes(slide_stub, tier, mode):
            return (True, "concept slide benefits from cartoon")

        d = igd.decide(
            _stub("claim_evidence"),
            tier="STRONG", mode="talk-30",
            judge_fn=stub_yes,
        )
        assert d.emit is True
        assert "LLM-judged" in d.reason
        assert "concept slide benefits from cartoon" in d.reason

    def test_judge_fn_no_keeps_deferred_at_emit_false(self):
        def stub_no(slide_stub, tier, mode):
            return (False, "data-heavy; illustration would compete")

        d = igd.decide(
            _stub("claim_evidence"),
            tier="STRONG", mode="talk-30",
            judge_fn=stub_no,
        )
        assert d.emit is False
        assert "LLM-judged" in d.reason
        assert "data-heavy" in d.reason

    def test_judge_fn_exception_defaults_to_no_with_error_reason(self):
        def stub_explode(slide_stub, tier, mode):
            raise RuntimeError("simulated LLM failure")

        d = igd.decide(
            _stub("big_idea"),
            tier="STRONG", mode="talk-30",
            judge_fn=stub_explode,
        )
        assert d.emit is False
        assert "LLM judgment failed" in d.reason
        assert "RuntimeError" in d.reason

    def test_judge_fn_not_called_for_non_deferred_layouts(self):
        """judge_fn should NOT be invoked for layouts outside _DEFERRED_LLM_DECISION
        (data_figure carries its own figure; structural layouts are pure;
        concept_illustration is deterministic-yes when conditions are right)."""
        called = []
        def stub_track(slide_stub, tier, mode):
            called.append(slide_stub.get("layout"))
            return (True, "should not be called")

        # data_figure → has-own-figure path; judge_fn must not be called
        d_fig = igd.decide(
            _stub("data_figure"), tier="STRONG", mode="talk-30",
            judge_fn=stub_track,
        )
        assert d_fig.emit is False
        assert d_fig.reason.startswith("data_figure carries its own figure")

        # title → structural; judge_fn must not be called
        d_title = igd.decide(
            _stub("title"), tier="STRONG", mode="talk-30",
            judge_fn=stub_track,
        )
        assert d_title.emit is False
        assert "structural" in d_title.reason

        # concept_illustration → AI-image-vehicle; judge_fn must not be called
        d_ci = igd.decide(
            _stub("concept_illustration", image_path="{TBD}"),
            tier="STRONG", mode="talk-30",
            judge_fn=stub_track,
        )
        assert d_ci.emit is True

        assert called == [], (
            f"judge_fn should not have been invoked for non-deferred layouts; "
            f"called for: {called}"
        )

    def test_judge_fn_called_for_all_six_deferred_layouts(self):
        """All six layouts in _DEFERRED_LLM_DECISION should reach the
        judge_fn callback when one is provided."""
        called_layouts = []
        def stub_track(slide_stub, tier, mode):
            called_layouts.append(slide_stub.get("layout"))
            return (True, "ok")

        for layout in [
            "claim_evidence", "workflow_diagram", "two_column_compare",
            "big_idea", "big_number", "implications",
        ]:
            igd.decide(
                _stub(layout), tier="STRONG", mode="talk-30",
                judge_fn=stub_track,
            )
        assert sorted(called_layouts) == sorted([
            "claim_evidence", "workflow_diagram", "two_column_compare",
            "big_idea", "big_number", "implications",
        ])


class TestLLMJudgeHelper:
    """Tests for llm_judge() — the default judge_fn that wraps claude -p."""

    def test_llm_judge_returns_no_when_claude_not_on_path(self, monkeypatch):
        """If claude CLI isn't available, llm_judge returns the conservative
        default (emit=false) without raising."""
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        emit, reason = igd.llm_judge(_stub("claim_evidence"), "STRONG", "talk-30")
        assert emit is False
        assert "claude CLI not on PATH" in reason

    def test_llm_judge_parses_yes_response(self, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "YES this slide presents a mechanism that benefits from a cartoon\n"
        mock_run.return_value.stderr = ""
        monkeypatch.setattr("subprocess.run", mock_run)

        emit, reason = igd.llm_judge(_stub("claim_evidence"), "STRONG", "talk-30")
        assert emit is True
        assert "mechanism that benefits" in reason

    def test_llm_judge_parses_no_response(self, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "NO data-heavy slide; illustration would compete\n"
        mock_run.return_value.stderr = ""
        monkeypatch.setattr("subprocess.run", mock_run)

        emit, reason = igd.llm_judge(_stub("claim_evidence"), "STRONG", "talk-30")
        assert emit is False
        assert "data-heavy" in reason

    def test_llm_judge_unparseable_response_defaults_to_no(self, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "I think maybe sure why not\n"
        mock_run.return_value.stderr = ""
        monkeypatch.setattr("subprocess.run", mock_run)

        emit, reason = igd.llm_judge(_stub("claim_evidence"), "STRONG", "talk-30")
        assert emit is False
        assert "unparseable" in reason

    def test_llm_judge_subprocess_timeout_defaults_to_no(self, monkeypatch):
        import subprocess as sp
        from unittest.mock import MagicMock
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
        mock_run = MagicMock(side_effect=sp.TimeoutExpired(cmd="claude", timeout=60))
        monkeypatch.setattr("subprocess.run", mock_run)

        emit, reason = igd.llm_judge(_stub("claim_evidence"), "STRONG", "talk-30")
        assert emit is False
        assert "timed out" in reason

    def test_llm_judge_nonzero_exit_defaults_to_no(self, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
        mock_run = MagicMock()
        mock_run.return_value.returncode = 2
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "rate limit exceeded"
        monkeypatch.setattr("subprocess.run", mock_run)

        emit, reason = igd.llm_judge(_stub("claim_evidence"), "STRONG", "talk-30")
        assert emit is False
        assert "rc=2" in reason


class TestParseJudgeResponse:
    """Tests for _parse_judge_response — pure parser, no I/O."""

    def test_yes_with_reason(self):
        emit, reason = igd._parse_judge_response("YES this is a concept slide")
        assert emit is True
        assert reason == "this is a concept slide"

    def test_no_with_reason(self):
        emit, reason = igd._parse_judge_response("NO data heavy")
        assert emit is False
        assert reason == "data heavy"

    def test_yes_with_dash_separator(self):
        emit, reason = igd._parse_judge_response("YES — concept slide")
        assert emit is True
        assert reason == "concept slide"

    def test_yes_with_colon_separator(self):
        emit, reason = igd._parse_judge_response("YES: concept slide")
        assert emit is True
        assert reason == "concept slide"

    def test_yes_no_reason_provided(self):
        emit, reason = igd._parse_judge_response("YES")
        assert emit is True
        assert "no reason given" in reason

    def test_no_no_reason_provided(self):
        emit, reason = igd._parse_judge_response("NO")
        assert emit is False
        assert "no reason given" in reason

    def test_empty_response(self):
        emit, reason = igd._parse_judge_response("")
        assert emit is False
        assert "empty LLM response" in reason

    def test_unparseable_response(self):
        emit, reason = igd._parse_judge_response("Maybe? I think it would help")
        assert emit is False
        assert "unparseable" in reason
        assert "Maybe?" in reason  # Surfaces head of response

    def test_uses_first_line_only(self):
        """If the LLM emits multiple lines, only the first is parsed."""
        emit, reason = igd._parse_judge_response(
            "YES concept slide\nFurther reasoning that should be ignored"
        )
        assert emit is True
        assert reason == "concept slide"

    def test_case_insensitive_yes_no(self):
        emit, reason = igd._parse_judge_response("yes lowercase concept")
        assert emit is True
        emit, reason = igd._parse_judge_response("no lowercase data")
        assert emit is False


class TestEmitDecisionsLLMJudgmentFlag:
    """Tests for emit_decisions() llm_judgment_used envelope flag."""

    def test_envelope_flag_false_when_no_judge_fn(self, tmp_path: Path):
        slides_dir = tmp_path / "03_slides"
        slides_dir.mkdir()
        (slides_dir / "S1.json").write_text(json.dumps({
            "schema_version": "slide-fragment.v1",
            "kind": "substory",
            "substory_id": "S1",
            "slides": [_stub("claim_evidence")],
        }))
        envelope = igd.emit_decisions(
            slides_dir, tier="STRONG", mode="talk-30",
        )
        assert envelope["llm_judgment_used"] is False

    def test_envelope_flag_true_when_judge_fn_passed(self, tmp_path: Path):
        slides_dir = tmp_path / "03_slides"
        slides_dir.mkdir()
        (slides_dir / "S1.json").write_text(json.dumps({
            "schema_version": "slide-fragment.v1",
            "kind": "substory",
            "substory_id": "S1",
            "slides": [_stub("claim_evidence")],
        }))
        envelope = igd.emit_decisions(
            slides_dir, tier="STRONG", mode="talk-30",
            judge_fn=lambda s, t, m: (True, "stub yes"),
        )
        assert envelope["llm_judgment_used"] is True
        # And the deferred slide was actually flipped to yes.
        flipped = [d for d in envelope["decisions"] if d["emit"]]
        assert len(flipped) == 1
        assert "LLM-judged" in flipped[0]["reason"]


class TestCLIWithLLMJudgeFlags:
    """Tests for --no-llm-judge and --judge-model CLI flags."""

    def test_cli_no_llm_judge_disables_judgment(self, tmp_path: Path, capsys):
        slides_dir = tmp_path / "03_slides"
        slides_dir.mkdir()
        (slides_dir / "S1.json").write_text(json.dumps({
            "schema_version": "slide-fragment.v1",
            "kind": "substory",
            "substory_id": "S1",
            "slides": [_stub("claim_evidence")],
        }))
        out_path = tmp_path / "decisions.json"
        rc = igd.main([
            "emit-decisions",
            "--slides-dir", str(slides_dir),
            "--tier", "STRONG",
            "--mode", "talk-30",
            "--no-llm-judge",
            "--out", str(out_path),
        ])
        assert rc == 0
        envelope = json.loads(out_path.read_text())
        assert envelope["llm_judgment_used"] is False
        captured = capsys.readouterr()
        assert "--no-llm-judge set" in captured.err

    def test_cli_falls_back_when_claude_not_on_path(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        slides_dir = tmp_path / "03_slides"
        slides_dir.mkdir()
        (slides_dir / "S1.json").write_text(json.dumps({
            "schema_version": "slide-fragment.v1",
            "kind": "substory",
            "substory_id": "S1",
            "slides": [_stub("claim_evidence")],
        }))
        out_path = tmp_path / "decisions.json"
        rc = igd.main([
            "emit-decisions",
            "--slides-dir", str(slides_dir),
            "--tier", "STRONG",
            "--mode", "talk-30",
            "--out", str(out_path),
        ])
        assert rc == 0
        envelope = json.loads(out_path.read_text())
        assert envelope["llm_judgment_used"] is False
        captured = capsys.readouterr()
        assert "claude CLI not on PATH" in captured.err


# ===========================================================================
# v0.7 Tier D.0 — claim_evidence eligibility gate + judge technical-specificity (D-088)
# ===========================================================================

class TestClaimEvidenceBulletGate:
    """v0.7/D-088: claim_evidence is image-eligible ONLY when it has >=3
    bullets. Slides below the floor short-circuit to emit=False BEFORE
    the judge call (saves judge cost + prevents the judge from
    approving generic art for short claims)."""

    def test_claim_evidence_with_zero_bullets_rejected_before_judge(self):
        """No bullets -> ineligible, judge not consulted."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "should not be reached")
        slide = _stub("claim_evidence", bullets=[])
        d = igd.decide(slide, tier="STRONG", mode="talk-30",
                       judge_fn=stub_judge)
        assert d.emit is False
        assert called["n"] == 0, "judge must not be consulted for <3-bullet claim_evidence"
        assert "0 bullet" in d.reason
        assert "D-088" in d.reason

    def test_claim_evidence_with_two_bullets_rejected_before_judge(self):
        """2 bullets -> ineligible (below the 3-bullet floor)."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "should not be reached")
        slide = _stub("claim_evidence",
                      bullets=["first claim.", "second claim."])
        d = igd.decide(slide, tier="STRONG", mode="talk-30",
                       judge_fn=stub_judge)
        assert d.emit is False
        assert called["n"] == 0
        assert "2 bullet" in d.reason

    def test_claim_evidence_with_three_bullets_reaches_judge(self):
        """3 bullets -> eligibility gate passes, judge consulted."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "three mechanisms map to a 3-panel diagram")
        slide = _stub("claim_evidence",
                      bullets=["mech A.", "mech B.", "mech C."])
        d = igd.decide(slide, tier="STRONG", mode="talk-30",
                       judge_fn=stub_judge)
        assert called["n"] == 1, "judge MUST be consulted for >=3-bullet claim_evidence"
        assert d.emit is True
        assert "LLM-judged" in d.reason

    def test_claim_evidence_with_four_bullets_reaches_judge(self):
        """4 bullets -> also passes the floor."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "four phases")
        slide = _stub("claim_evidence",
                      bullets=["a.", "b.", "c.", "d."])
        d = igd.decide(slide, tier="STRONG", mode="talk-30",
                       judge_fn=stub_judge)
        assert called["n"] == 1
        assert d.emit is True

    def test_claim_evidence_dict_bullets_counted_correctly(self):
        """claim_evidence supports both str and dict bullet shapes;
        the count helper handles both."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "ok")
        slide = _stub("claim_evidence", bullets=[
            {"claim": "first.", "evidence_pointer": "ref"},
            {"claim": "second.", "evidence_pointer": "ref"},
            {"claim": "third.", "evidence_pointer": "ref"},
        ])
        d = igd.decide(slide, tier="STRONG", mode="talk-30",
                       judge_fn=stub_judge)
        assert called["n"] == 1
        assert d.emit is True

    def test_claim_evidence_empty_string_bullets_dont_count(self):
        """Empty-string bullets don't count (3 entries but all empty
        -> 0 distinct bullets -> below floor)."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "ok")
        slide = _stub("claim_evidence", bullets=["", "  ", ""])
        d = igd.decide(slide, tier="STRONG", mode="talk-30",
                       judge_fn=stub_judge)
        assert d.emit is False
        assert called["n"] == 0
        assert "0 bullet" in d.reason

    def test_count_distinct_bullets_handles_missing_content(self):
        """Defensive: missing content key -> 0 bullets, no crash."""
        assert igd._count_distinct_bullets({"layout": "claim_evidence"}) == 0

    def test_count_distinct_bullets_handles_non_dict_content(self):
        """Defensive: content as string (malformed) -> 0 bullets, no crash."""
        assert igd._count_distinct_bullets(
            {"layout": "claim_evidence", "content": "broken"}) == 0

    def test_count_distinct_bullets_handles_non_list_bullets(self):
        """Defensive: bullets as string (malformed) -> 0 bullets."""
        assert igd._count_distinct_bullets(
            {"layout": "claim_evidence",
             "content": {"bullets": "single string"}}) == 0

    def test_floor_constant_pins_value(self):
        """Pin the constant so a future change is intentional."""
        assert igd._MIN_CLAIM_EVIDENCE_BULLETS_FOR_IMAGE == 3

    def test_other_deferred_layouts_unaffected_by_claim_evidence_gate(self):
        """The bullet-count gate fires ONLY on claim_evidence. Other
        deferred layouts (workflow_diagram, two_column_compare,
        big_idea, big_number, implications) still go straight to the
        judge regardless of bullet count."""
        called = {"n": 0}
        def stub_judge(s, t, m):
            called["n"] += 1
            return (True, "judged")
        d = igd.decide(
            {"layout": "workflow_diagram", "content": {"title": "x"}},
            tier="STRONG", mode="talk-30", judge_fn=stub_judge,
        )
        assert called["n"] == 1, (
            "workflow_diagram must still reach the judge regardless "
            "of bullets (the claim_evidence gate is layout-specific)"
        )
        assert d.emit is True


class TestJudgeTechnicalSpecificityCriterion:
    """v0.7/D-088: the judge prompt includes a technical-specificity
    criterion (gatekeeps the v0.6 Tier-F D-084 finding 4 "generic /
    too conceptual" failure mode)."""

    def test_judge_prompt_includes_technical_specificity_section(self):
        """The judge prompt MUST contain explicit technical-specificity
        language so the LLM knows to apply the v0.7 criterion."""
        prompt = igd._build_judge_prompt(
            _stub("claim_evidence"), tier="STRONG", mode="talk-30",
        )
        assert "TECHNICAL-SPECIFICITY CRITERION" in prompt
        assert "D-088" in prompt
        assert "generic" in prompt.lower()
        assert "abstract" in prompt.lower() or "metaphor" in prompt.lower()

    def test_judge_prompt_names_v06_tier_f_motivation(self):
        """The criterion cites the D-084 finding it addresses so the
        load-bearing reason is explicit in the prompt itself."""
        prompt = igd._build_judge_prompt(
            _stub("big_idea"), tier="STRONG", mode="talk-30",
        )
        assert "D-084" in prompt or "Tier-F" in prompt or "v0.6" in prompt

    def test_judge_prompt_directs_per_panel_naming_for_claim_evidence(self):
        """For multi-bullet claim_evidence, the prompt explicitly asks
        the judge to name what each panel would contain (the "three
        mechanisms / four phases" pattern from D-088)."""
        prompt = igd._build_judge_prompt(
            _stub("claim_evidence",
                  bullets=["mech A", "mech B", "mech C"]),
            tier="STRONG", mode="talk-30",
        )
        assert ("three mechanisms" in prompt.lower()
                or "four phases" in prompt.lower()
                or "n categories" in prompt.lower())

    def test_judge_prompt_response_format_unchanged(self):
        """The YES/NO one-line response contract is preserved
        (parser depends on this; D-088 only EXTENDS criteria, not
        the response format)."""
        prompt = igd._build_judge_prompt(
            _stub("big_idea"), tier="STRONG", mode="talk-30",
        )
        assert "YES" in prompt and "NO" in prompt
        assert "first word" in prompt.lower()
        assert "uppercase" in prompt.lower()
