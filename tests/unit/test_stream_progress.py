"""Tests for stream_progress.py — claude stream-json parser.

Coverage:
- Cost estimation per model family (sonnet, opus, haiku).
- _classify_model handles family substrings.
- parse_stream success path with Write-tool invocation.
- parse_stream returns 2 when Write was never invoked.
- parse_stream returns 3 when Write was invoked on a wrong path.
- Metadata sidecar JSON is written on success.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SP_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "stream_progress.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sp():
    return _import("stream_progress", SP_PY)


# ---------------------------------------------------------------------------
# Cost estimation + model classification
# ---------------------------------------------------------------------------

def test_classify_model_substring_match(sp):
    assert sp._classify_model("claude-sonnet-4-6") == "sonnet"
    assert sp._classify_model("claude-opus-4-7") == "opus"
    assert sp._classify_model("claude-haiku-4-5") == "haiku"
    assert sp._classify_model("CLAUDE-SONNET-4-6") == "sonnet"  # case-insensitive
    assert sp._classify_model("gpt-5") is None
    assert sp._classify_model("") is None
    assert sp._classify_model(None) is None


def test_estimate_cost_sonnet(sp):
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
    }
    cost = sp._estimate_cost(usage, "claude-sonnet-4-6")
    # 1M * $3 + 100K * $15 = $3 + $1.50 = $4.50
    assert abs(cost - 4.50) < 0.01


def test_estimate_cost_unknown_model_returns_none(sp):
    cost = sp._estimate_cost({"input_tokens": 100}, "gpt-5")
    assert cost is None


def test_estimate_cost_includes_cache_tokens(sp):
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
    }
    cost = sp._estimate_cost(usage, "claude-sonnet-4-6")
    # 1M * $0.30 + 1M * $3.75 = $0.30 + $3.75 = $4.05
    assert abs(cost - 4.05) < 0.01


# ---------------------------------------------------------------------------
# Metadata sidecar
# ---------------------------------------------------------------------------

def test_write_metadata_json(sp, tmp_path):
    out = tmp_path / "metadata.json"
    ok = sp._write_metadata_json(out, {"elapsed_seconds": 42, "input_tokens": 1000})
    assert ok
    parsed = json.loads(out.read_text())
    assert parsed["elapsed_seconds"] == 42


# ---------------------------------------------------------------------------
# parse_stream — success path with Write tool invocation
# ---------------------------------------------------------------------------

def _stream_with_write(target_path: str, model: str = "claude-sonnet-4-6") -> str:
    """Build a stream-json input that includes a Write tool_use event and a
    final result event with usage."""
    events = [
        {"type": "system", "subtype": "init", "model": model},
        {"type": "content_block_start",
         "content_block": {
             "type": "tool_use",
             "name": "Write",
             "input": {"file_path": target_path, "content": "hello"},
         }},
        {"type": "result",
         "usage": {"input_tokens": 1000, "output_tokens": 200}},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_parse_stream_returns_0_on_correct_write(sp, tmp_path, monkeypatch, capsys):
    target = str(tmp_path / "out.md")
    raw = _stream_with_write(target)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))

    rc = sp.parse_stream(
        expected_write_path=target,
        log_path=None, quiet=True,
        model="claude-sonnet-4-6",
    )
    assert rc == 0


def test_parse_stream_returns_2_when_write_missing(sp, monkeypatch):
    """Stream has NO Write event. Must return 2 (silent-failure detected)."""
    events = [
        {"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"},
        {"type": "result", "usage": {"input_tokens": 100, "output_tokens": 50}},
    ]
    raw = "\n".join(json.dumps(e) for e in events) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))

    rc = sp.parse_stream(
        expected_write_path="/some/expected/path.md",
        log_path=None, quiet=True,
    )
    assert rc == 2


def test_parse_stream_returns_3_when_write_wrong_path(sp, tmp_path, monkeypatch):
    """Write was invoked but on a different path. Must return 3."""
    expected = str(tmp_path / "expected.md")
    actual = str(tmp_path / "actual.md")
    raw = _stream_with_write(actual)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))

    rc = sp.parse_stream(
        expected_write_path=expected,
        log_path=None, quiet=True,
    )
    assert rc == 3


def test_parse_stream_no_expected_path_returns_0(sp, monkeypatch):
    """If no expected path is set, the verification step is skipped — RC 0."""
    raw = json.dumps({
        "type": "result",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    rc = sp.parse_stream(
        expected_write_path=None,
        log_path=None, quiet=True,
    )
    assert rc == 0


def test_parse_stream_writes_metadata_sidecar(sp, tmp_path, monkeypatch):
    target = str(tmp_path / "out.md")
    raw = _stream_with_write(target, model="claude-sonnet-4-6")
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))

    metadata_out = tmp_path / "meta.json"
    rc = sp.parse_stream(
        expected_write_path=target, log_path=None, quiet=True,
        model="claude-sonnet-4-6",
        metadata_out=str(metadata_out),
    )
    assert rc == 0
    assert metadata_out.is_file()
    meta = json.loads(metadata_out.read_text())
    assert meta["input_tokens"] == 1000
    assert meta["output_tokens"] == 200
    assert meta["model"] == "claude-sonnet-4-6"
    assert "estimated_cost_usd" in meta


def test_parse_stream_with_log_writes_raw(sp, tmp_path, monkeypatch):
    target = str(tmp_path / "out.md")
    raw = _stream_with_write(target)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))

    log_path = tmp_path / "stream.log"
    rc = sp.parse_stream(
        expected_write_path=target, log_path=str(log_path),
        quiet=True, model="claude-sonnet-4-6",
    )
    assert rc == 0
    assert log_path.is_file()
    # Log should contain the raw stream content
    log_text = log_path.read_text()
    assert "tool_use" in log_text


def test_parse_stream_handles_parse_errors(sp, monkeypatch, capsys):
    """Malformed lines in the stream are counted but don't abort."""
    events_raw = (
        json.dumps({"type": "system", "subtype": "init"}) + "\n"
        + "this is not json\n"
        + json.dumps({
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use", "name": "Write",
                "input": {"file_path": "/tmp/x.md"},
            },
        }) + "\n"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(events_raw))
    rc = sp.parse_stream(
        expected_write_path="/tmp/x.md",
        log_path=None, quiet=True,
    )
    # Parser tolerates malformed lines; Write was found, so RC 0.
    assert rc == 0
