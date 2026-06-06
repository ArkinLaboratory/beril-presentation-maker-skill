"""Tests for review_tier2.py — Tier 2 narrative-light Haiku review
(v0.4 M4b Tier C).

Coverage:
- Toolchain probe (probe_toolchain — just claude CLI).
- Stub-report writers (write_stub_reports).
- claude -p invocation (invoke_tier2_review) — argv shape, model pin
  (Haiku 4.5), allowedTools=Read,Write, --output-format json envelope,
  cost parsing.
- Top-level run_tier2 happy path (everything mocked).
- Failure paths: missing claude, missing spec, claude -p failure —
  each writes a stub report, returns 0 (advisory).
- CLI smoke.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RT2_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
          / "tools" / "review_tier2.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rt2():
    return _import("review_tier2", RT2_PY)


# ---------------------------------------------------------------------------
# Toolchain probe
# ---------------------------------------------------------------------------

def test_toolchain_status_ok_with_claude_present(rt2):
    s = rt2.ToolchainStatus(claude="/u/claude")
    assert s.ok is True
    assert s.missing() == []


def test_toolchain_status_missing_claude(rt2):
    s = rt2.ToolchainStatus(claude=None)
    assert s.ok is False
    assert any("claude" in m for m in s.missing())


def test_probe_toolchain_uses_shutil_which(rt2, monkeypatch):
    """probe_toolchain delegates to shutil.which."""
    monkeypatch.setattr(rt2.shutil, "which",
                        lambda name: "/u/c" if name == "my-claude" else None)
    status = rt2.probe_toolchain(claude_bin="my-claude")
    assert status.claude == "/u/c"


# ---------------------------------------------------------------------------
# Stub-report writers
# ---------------------------------------------------------------------------

def test_write_stub_reports_emits_schema(rt2, tmp_path):
    """The stub report carries schema_version + draft_dir + note +
    empty findings (mirrors visual_qa.py)."""
    j = tmp_path / "audit" / "review_tier2.json"
    m = tmp_path / "audit" / "review_tier2.md"
    rt2.write_stub_reports(j, m, tmp_path, note="missing dep: claude")
    payload = json.loads(j.read_text())
    assert payload["schema_version"] == rt2.SCHEMA_VERSION
    assert payload["n_slides_reviewed"] == 0
    assert payload["findings"] == []
    assert "claude" in payload["note"]
    md = m.read_text()
    assert "Tier 2 review report" in md
    assert "claude" in md


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------

def test_invoke_tier2_review_builds_argv(rt2, tmp_path):
    """argv carries -p, --model haiku-4-5, --system-prompt,
    --allowedTools Read,Write (NOT Bash — Tier 2 is structured
    review), --output-format json, --dangerously-skip-permissions, +
    the user prompt naming all five inputs."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"slides": []}))
    out_json = tmp_path / "audit" / "review_tier2.json"
    out_md = tmp_path / "audit" / "review_tier2.md"
    throughline = tmp_path / "00_throughline.md"
    substories = tmp_path / "02_substories.md"
    quant = tmp_path / "quant.json"

    envelope = json.dumps({"type": "result", "total_cost_usd": 0.0512})
    fake_proc = MagicMock(returncode=0, stdout=envelope, stderr="")

    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        # Simulate the model writing the JSON output
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({"findings": []}))
        return fake_proc

    with patch.object(rt2.subprocess, "run", side_effect=fake_run):
        diag = rt2.invoke_tier2_review(
            draft_dir=tmp_path,
            slide_spec_path=spec_path,
            throughline_path=throughline,
            substories_path=substories,
            quant_grounding_path=quant,
            out_json_path=out_json,
            out_md_path=out_md,
            claude_bin="claude",
        )

    assert captured[0] == "claude"
    assert "-p" in captured
    assert "--system-prompt" in captured
    assert "--allowedTools" in captured
    # Tier 2 uses Read+Write only (NOT Bash) — structured review.
    assert "Read,Write" in captured
    assert "--dangerously-skip-permissions" in captured
    assert "--model" in captured
    # CRAFT §3.4 / brief §5a: Tier 2 review is fast pattern detection
    # → fast tier (haiku). The on-disk literal is now the alias `haiku`;
    # Claude Code resolves it via ANTHROPIC_DEFAULT_HAIKU_MODEL in
    # settings.json at runtime (DQ3 cost discipline preserved by the
    # configure-step discovery + pin).
    assert captured[captured.index("--model") + 1] == rt2.DEFAULT_MODEL
    assert rt2.DEFAULT_MODEL == "haiku", (
        f"DEFAULT_MODEL must be the haiku tier alias; got {rt2.DEFAULT_MODEL}"
    )
    assert "--output-format" in captured
    assert captured[captured.index("--output-format") + 1] == "json"

    # Diagnostic shape mirrors visual_qa.py + extract_claims.py
    assert diag["tool"] == "review_tier2"
    assert diag["phase"] == "narrative_review"
    assert diag["exit_status"] == 0
    assert diag["output_present"] is True
    assert diag["cost_usd"] == 0.0512
    assert "stdout_tail" in diag
    assert "stderr_tail" in diag
    assert diag["model"] == rt2.DEFAULT_MODEL


def test_invoke_tier2_review_user_prompt_names_all_inputs(rt2, tmp_path):
    """The user prompt must explicitly name each of the 5 inputs +
    both outputs so the model can Read them. Pin so a future refactor
    doesn't silently drop one (which would make the model improvise)."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{}")
    throughline = tmp_path / "00_throughline.md"
    substories = tmp_path / "02_substories.md"
    quant = tmp_path / "quant.json"
    out_json = tmp_path / "audit" / "review_tier2.json"
    out_md = tmp_path / "audit" / "review_tier2.md"

    fake_proc = MagicMock(returncode=0, stdout="{}", stderr="")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text("{}")
        return fake_proc

    with patch.object(rt2.subprocess, "run", side_effect=fake_run):
        rt2.invoke_tier2_review(
            draft_dir=tmp_path,
            slide_spec_path=spec_path,
            throughline_path=throughline,
            substories_path=substories,
            quant_grounding_path=quant,
            out_json_path=out_json,
            out_md_path=out_md,
            claude_bin="claude",
        )

    # The user prompt is the LAST argv element (positional after --
    # dangerously-skip-permissions in our build_cmd order)
    user_prompt = captured[-1]
    for label in ("DRAFT_DIR:", "SLIDE_SPEC_PATH:", "THROUGHLINE_PATH:",
                  "SUBSTORIES_PATH:", "QUANT_GROUNDING_PATH:",
                  "OUT_PATH:", "OUT_PATH_MD:"):
        assert label in user_prompt, f"user prompt must name {label}"


def test_invoke_tier2_review_model_override(rt2, tmp_path):
    """A non-default --model is threaded into argv + diagnostic."""
    out_json = tmp_path / "audit" / "review_tier2.json"
    out_md = tmp_path / "audit" / "review_tier2.md"
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{}")
    for p in (tmp_path / "00_throughline.md", tmp_path / "02_substories.md",
              tmp_path / "quant.json"):
        p.write_text("{}")

    fake_proc = MagicMock(returncode=0, stdout="{}", stderr="")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text("{}")
        return fake_proc

    with patch.object(rt2.subprocess, "run", side_effect=fake_run):
        diag = rt2.invoke_tier2_review(
            draft_dir=tmp_path,
            slide_spec_path=spec_path,
            throughline_path=tmp_path / "00_throughline.md",
            substories_path=tmp_path / "02_substories.md",
            quant_grounding_path=tmp_path / "quant.json",
            out_json_path=out_json,
            out_md_path=out_md,
            claude_bin="claude",
            model="claude-sonnet-4-6",
        )

    assert captured[captured.index("--model") + 1] == "claude-sonnet-4-6"
    assert diag["model"] == "claude-sonnet-4-6"


def test_invoke_tier2_review_missing_prompt_raises(rt2, tmp_path):
    """A missing system prompt file is operator error → FileNotFoundError."""
    bogus = tmp_path / "no-such-prompt.md"
    with pytest.raises(FileNotFoundError):
        rt2.invoke_tier2_review(
            draft_dir=tmp_path,
            slide_spec_path=tmp_path / "spec.json",
            throughline_path=tmp_path / "throughline.md",
            substories_path=tmp_path / "substories.md",
            quant_grounding_path=tmp_path / "quant.json",
            out_json_path=tmp_path / "out.json",
            out_md_path=tmp_path / "out.md",
            prompt_path=bogus,
            claude_bin="claude",
        )


def test_parse_cost_from_envelope_happy(rt2):
    envelope = json.dumps({"type": "result", "total_cost_usd": 0.0512})
    cost, note = rt2._parse_cost_from_envelope(envelope)
    assert cost == 0.0512
    assert note == ""


def test_parse_cost_from_envelope_missing_field(rt2):
    cost, note = rt2._parse_cost_from_envelope(json.dumps({"type": "result"}))
    assert cost == 0.0
    assert "missing" in note


def test_parse_cost_from_envelope_unparseable(rt2):
    cost, note = rt2._parse_cost_from_envelope("not json")
    assert cost == 0.0
    assert "not parseable" in note


# ---------------------------------------------------------------------------
# run_tier2 — failure paths
# ---------------------------------------------------------------------------

def test_run_tier2_returns_0_when_claude_missing(rt2, tmp_path, monkeypatch):
    """Missing claude CLI → stub report + rc=0 (cascade-advisory)."""
    monkeypatch.setattr(rt2, "probe_toolchain",
                        lambda *a, **kw: rt2.ToolchainStatus(claude=None))
    rc = rt2.run_tier2(tmp_path, quiet=True)
    assert rc == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_tier2.json").read_text())
    assert payload["findings"] == []
    assert "claude" in payload["note"].lower()


def test_run_tier2_returns_0_when_spec_missing(rt2, tmp_path, monkeypatch):
    """No working/slide_spec.json → stub report + rc=0."""
    monkeypatch.setattr(rt2, "probe_toolchain",
                        lambda *a, **kw: rt2.ToolchainStatus(claude="/u/c"))
    rc = rt2.run_tier2(tmp_path, quiet=True)
    assert rc == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_tier2.json").read_text())
    assert "not found" in payload["note"]


def test_run_tier2_returns_0_when_llm_call_fails(rt2, tmp_path, monkeypatch):
    """claude -p non-zero exit → stub report + rc=0."""
    monkeypatch.setattr(rt2, "probe_toolchain",
                        lambda *a, **kw: rt2.ToolchainStatus(claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({"slides": []}))

    monkeypatch.setattr(rt2, "invoke_tier2_review",
                        lambda **kw: {
                            "tool": "review_tier2", "exit_status": 2,
                            "output_present": False, "cost_usd": 0.0,
                            "cost_note": "", "stdout_tail": "",
                            "stderr_tail": "model rate-limited",
                            "model": rt2.DEFAULT_MODEL, "duration_sec": 1,
                            "version": rt2.VERSION,
                            "phase": "narrative_review",
                            "timestamp": "x", "claude_bin": "/u/c",
                        })
    rc = rt2.run_tier2(tmp_path, quiet=True)
    assert rc == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_tier2.json").read_text())
    assert "rate-limited" in payload["note"]


# ---------------------------------------------------------------------------
# run_tier2 — happy path (everything mocked)
# ---------------------------------------------------------------------------

def test_run_tier2_happy_path(rt2, tmp_path, monkeypatch):
    """End-to-end stub: claude probes OK, spec present, LLM 'returns'
    a valid JSON; cascade gets a real audit/review_tier2.json."""
    monkeypatch.setattr(rt2, "probe_toolchain",
                        lambda *a, **kw: rt2.ToolchainStatus(claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({
        "schema_version": "v1",
        "slides": [{"id": 1, "layout": "title"}],
    }))

    def _fake_review(*, out_json_path, out_md_path, **kw):
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        out_json_path.write_text(json.dumps({
            "schema_version": rt2.SCHEMA_VERSION,
            "draft_dir": str(kw["draft_dir"]),
            "n_slides_reviewed": 1,
            "findings": [{
                "slide_id": 1, "kind": "register_drift",
                "severity": "P1", "confidence": "high",
                "detail": "synthetic finding for test",
                "evidence_locator": "content.title",
            }],
        }))
        out_md_path.write_text("# Tier 2 review report\n")
        return {
            "tool": "review_tier2", "exit_status": 0,
            "output_present": True, "cost_usd": 0.0512,
            "cost_note": "", "stdout_tail": "",
            "stderr_tail": "", "model": rt2.DEFAULT_MODEL,
            "duration_sec": 3, "version": rt2.VERSION,
            "phase": "narrative_review", "timestamp": "x",
            "claude_bin": "/u/c",
        }

    monkeypatch.setattr(rt2, "invoke_tier2_review", _fake_review)

    rc = rt2.run_tier2(tmp_path, quiet=True)
    assert rc == 0
    payload = json.loads(
        (tmp_path / "audit" / "review_tier2.json").read_text())
    assert payload["n_slides_reviewed"] == 1
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["severity"] == "P1"
    # DQ4: severity is P1 or P2, NEVER P0 (Tier 2 doesn't gate)
    assert payload["findings"][0]["severity"] in ("P1", "P2")


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_main_returns_0_on_missing_draft(rt2, tmp_path):
    """CLI on an empty directory → missing-deps OR missing-spec stub;
    either way rc=0."""
    rc = rt2.main([str(tmp_path), "--quiet"])
    assert rc == 0
