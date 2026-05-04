"""Tests for v0.3.3 image_gen_approval Tier 5 approval gate.

Per V0_3_3_ARCHITECTURE.md §13 Tier 5 plan: extract a testable
helper that returns a Verdict given a deterministic input_fn.
Adam green-lit (2026-05-03) omitting the [e]dit choice from v0.3.3
in favor of the --resume-from image_gen power-user route.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import image_gen_approval as iga  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _request_dict(**overrides) -> dict:
    base = {
        "schema_version": "image-request.v1",
        "slide_id_target": "S2-pos4",
        "channel": "A",
        "originator": "slide_compose flagged concept_illustration",
        "style": "scientific_illustration",
        "image_prompt": "A scientific illustration of inner-loop annotation.",
        "negative_prompt": "no quantitative content, no axes, no specific numbers",
        "placement": {"region": "body", "aspect_ratio": "16:9",
                      "max_width_in": 8.5, "max_height_in": 4.0},
        "model_preference": "gemini-3-pro-image",
        "worst_case_cost_usd": 0.04,
        "user_supplied_prompt": None,
        "approval_required": True,
    }
    base.update(overrides)
    return base


class _CannedInput:
    """Stub for input(). Returns inputs in order; raises EOFError after."""

    def __init__(self, *responses: str):
        self._responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            raise EOFError
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# Verdict semantics
# ---------------------------------------------------------------------------

def test_verdict_is_approve_methods():
    assert iga.Verdict.APPROVE.is_approve
    assert iga.Verdict.APPROVE_ALL.is_approve
    assert not iga.Verdict.REJECT.is_approve
    assert not iga.Verdict.QUIT.is_approve


def test_verdict_is_reject_methods():
    assert iga.Verdict.REJECT.is_reject
    assert iga.Verdict.REJECT_ALL.is_reject
    assert not iga.Verdict.APPROVE.is_reject


def test_verdict_is_bulk_methods():
    assert iga.Verdict.APPROVE_ALL.is_bulk
    assert iga.Verdict.REJECT_ALL.is_bulk
    assert not iga.Verdict.APPROVE.is_bulk


# ---------------------------------------------------------------------------
# Bulk-mode short-circuit
# ---------------------------------------------------------------------------

def test_bulk_approve_all_short_circuits():
    canned = _CannedInput()  # would raise if called
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=canned,
        bulk_mode=iga.BulkMode.APPROVE_ALL,
    )
    assert out is iga.Verdict.APPROVE_ALL
    assert canned.calls == []  # input never read


def test_bulk_reject_all_short_circuits():
    canned = _CannedInput()
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=canned,
        bulk_mode=iga.BulkMode.REJECT_ALL,
    )
    assert out is iga.Verdict.REJECT_ALL
    assert canned.calls == []


# ---------------------------------------------------------------------------
# Single-keystroke verdicts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("char,expected", [
    ("a", iga.Verdict.APPROVE),
    ("r", iga.Verdict.REJECT),
    ("A", iga.Verdict.APPROVE_ALL),
    ("R", iga.Verdict.REJECT_ALL),
    ("q", iga.Verdict.QUIT),
])
def test_each_choice_returns_correct_verdict(char, expected):
    canned = _CannedInput(char)
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=canned,
        output_stream=io.StringIO(),
    )
    assert out is expected
    assert len(canned.calls) == 1


def test_eof_returns_quit():
    """No interactive input → quit (don't crash on non-interactive runs)."""
    canned = _CannedInput()  # empty → EOFError on first call
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=canned,
        output_stream=io.StringIO(),
    )
    assert out is iga.Verdict.QUIT


def test_keyboard_interrupt_returns_quit():
    def _raises_kbd(prompt):
        raise KeyboardInterrupt
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=_raises_kbd,
        output_stream=io.StringIO(),
    )
    assert out is iga.Verdict.QUIT


def test_view_full_prompt_then_approve():
    """[v] shows the full prompt then re-prompts; [a] then approves."""
    canned = _CannedInput("v", "a")
    output = io.StringIO()
    out = iga.prompt_approval(
        _request_dict(image_prompt="A" * 1000),
        budget_remaining_usd=0.5,
        input_fn=canned,
        output_stream=output,
    )
    assert out is iga.Verdict.APPROVE
    assert len(canned.calls) == 2
    body = output.getvalue()
    assert "full image_prompt" in body
    assert "negative_prompt" in body


def test_unknown_choice_reprompts_until_valid():
    canned = _CannedInput("x", "yes please", "", "a")
    output = io.StringIO()
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=canned,
        output_stream=output,
    )
    assert out is iga.Verdict.APPROVE
    assert len(canned.calls) == 4
    body = output.getvalue()
    assert "unrecognized choice" in body


def test_e_choice_is_not_supported_v0_3_3():
    """Adam 2026-05-03: omit [e]dit; document --resume-from image_gen
    power-user route. The character should be treated as unknown
    (re-prompt) rather than dispatch into an editor."""
    canned = _CannedInput("e", "a")
    output = io.StringIO()
    out = iga.prompt_approval(
        _request_dict(),
        budget_remaining_usd=0.5,
        input_fn=canned,
        output_stream=output,
    )
    assert out is iga.Verdict.APPROVE
    body = output.getvalue()
    assert "unrecognized choice" in body
    assert "'e'" in body


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------

def test_summary_includes_slide_id_and_cost():
    s = iga.format_request_summary(
        _request_dict(),
        budget_remaining_usd=0.5,
    )
    assert "S2-pos4" in s
    assert "$0.040" in s
    assert "$0.500" in s
    assert "scientific_illustration" in s


def test_summary_truncates_long_prompts():
    long_prompt = "X" * 1000
    s = iga.format_request_summary(
        _request_dict(image_prompt=long_prompt),
        budget_remaining_usd=0.5,
    )
    # The preview cap is documented in the module.
    assert len(s) < 1500
    assert "..." in s


def test_summary_does_not_truncate_short_prompts():
    short_prompt = "A short illustration prompt."
    s = iga.format_request_summary(
        _request_dict(image_prompt=short_prompt),
        budget_remaining_usd=0.5,
    )
    assert short_prompt in s
    # No truncation marker for short prompts.
    assert "..." not in s


# ---------------------------------------------------------------------------
# Slide-id verification (Adam-greenlit trust-but-verify)
# ---------------------------------------------------------------------------

def test_verify_request_slide_id_ok(tmp_path):
    target = tmp_path / "S2-pos4_request.json"
    target.write_text(json.dumps(_request_dict(slide_id_target="S2-pos4")))
    errors = iga.verify_request_slide_id(target, "S2-pos4")
    assert errors == []


def test_verify_request_slide_id_mismatch(tmp_path):
    target = tmp_path / "req.json"
    target.write_text(json.dumps(_request_dict(slide_id_target="S2-pos4")))
    errors = iga.verify_request_slide_id(target, "S3-pos1")
    assert len(errors) == 1
    assert "slide_id_target mismatch" in errors[0]
    assert "S3-pos1" in errors[0]
    assert "S2-pos4" in errors[0]


def test_verify_request_slide_id_missing_field(tmp_path):
    target = tmp_path / "req.json"
    payload = _request_dict()
    del payload["slide_id_target"]
    target.write_text(json.dumps(payload))
    errors = iga.verify_request_slide_id(target, "S2-pos4")
    assert any("slide_id_target" in e for e in errors)


def test_verify_request_slide_id_missing_file(tmp_path):
    errors = iga.verify_request_slide_id(tmp_path / "no.json", "S2-pos4")
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_verify_request_slide_id_malformed_json(tmp_path):
    target = tmp_path / "req.json"
    target.write_text("{not json")
    errors = iga.verify_request_slide_id(target, "S2-pos4")
    assert any("not valid JSON" in e for e in errors)


def test_verify_request_catches_wrong_schema_version(tmp_path):
    target = tmp_path / "req.json"
    target.write_text(json.dumps(_request_dict(schema_version="image-request.v0")))
    errors = iga.verify_request_slide_id(target, "S2-pos4")
    assert any("schema_version" in e for e in errors)


def test_verify_request_catches_approval_required_false(tmp_path):
    """D-029: approval_required must be True in v0.3.3.
    LLM dropping it to False is a contract violation."""
    target = tmp_path / "req.json"
    target.write_text(json.dumps(_request_dict(approval_required=False)))
    errors = iga.verify_request_slide_id(target, "S2-pos4")
    assert any("approval_required" in e and "D-029" in e for e in errors)


def test_verify_request_catches_invalid_channel(tmp_path):
    target = tmp_path / "req.json"
    target.write_text(json.dumps(_request_dict(channel="C")))
    errors = iga.verify_request_slide_id(target, "S2-pos4")
    assert any("channel" in e for e in errors)


# ---------------------------------------------------------------------------
# CLI exit-code mapping
# ---------------------------------------------------------------------------

def test_verdict_to_exit_code_complete():
    """Every Verdict has an exit code; mapping is documented."""
    expected = {
        iga.Verdict.APPROVE: 0,
        iga.Verdict.REJECT: 1,
        iga.Verdict.APPROVE_ALL: 10,
        iga.Verdict.REJECT_ALL: 11,
        iga.Verdict.QUIT: 20,
    }
    for verdict, code in expected.items():
        assert iga._verdict_to_exit_code(verdict) == code


def test_cli_verify_ok(tmp_path, capsys):
    target = tmp_path / "req.json"
    target.write_text(json.dumps(_request_dict()))
    rc = iga.main(["verify", str(target), "S2-pos4"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.err


def test_cli_verify_mismatch(tmp_path, capsys):
    target = tmp_path / "req.json"
    target.write_text(json.dumps(_request_dict(slide_id_target="S2-pos4")))
    rc = iga.main(["verify", str(target), "S99-pos99"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "error" in captured.err
    assert "mismatch" in captured.err
