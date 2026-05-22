"""Unit tests for tools/extract_claims.py.

Authored for presentation-maker v0.4 M1 (2026-05-12). The adapter
is presentation-maker-specific (paper-writer inlined this logic
in orchestrator.py at phase_triage; we extract as a standalone
tool per V0_4_ARCHITECTURE.md §4.4).

Coverage:
  - invoke_claude_extract: builds the expected subprocess argv, with the
    model pinned (B6 — Tier G heads-up fix).
  - invoke_claude_extract: a --model override is threaded into argv + diag.
  - invoke_claude_extract: returns diagnostic with exit_status, duration,
    stdout_tail, stderr_tail, model.
  - invoke_claude_extract: raises FileNotFoundError when prompt absent.
  - invoke_validator: builds the expected validator argv.
  - invoke_validator: raises FileNotFoundError when validator absent.
  - append_audit: creates phase0.jsonl, one record per call.
  - main CLI: missing --report file → exit 1.
  - main CLI: missing --project-root dir → exit 1.
  - main CLI: claude binary not on PATH → exit 2.
  - main CLI: --skip-validator path (no validator call).
  - main CLI: existing output is skipped (idempotent fast-path).
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from beril_presentation_maker.skill.tools import extract_claims as ec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TSV_HEADER = [
    "claim_id", "claim_text", "source_notebook", "source_cell",
    "figure_or_table", "effect_size_present", "ci_present",
    "pvalue_present", "notes",
]


def _make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "synthetic_project"
    (proj / "notebooks").mkdir(parents=True, exist_ok=True)
    (proj / "REPORT.md").write_text("# Synthetic Report\n\nx = 88.2%.\n",
                                     encoding="utf-8")
    (proj / "methods_provenance.md").write_text(
        "# Methods Provenance\n\n## NB01.ipynb\n- cell 14: scipy.stats.ttest_ind\n",
        encoding="utf-8",
    )
    (proj / "notebooks" / "NB01.ipynb").write_text("{}", encoding="utf-8")
    return proj


def _write_synthetic_tsv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=TSV_HEADER, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerow({
            "claim_id": "C001", "claim_text": "x is 88.2%",
            "source_notebook": "notebooks/NB01.ipynb",
            "source_cell": "14", "figure_or_table": "",
            "effect_size_present": "no", "ci_present": "no",
            "pvalue_present": "no", "notes": "",
        })


# ---------------------------------------------------------------------------
# invoke_claude_extract
# ---------------------------------------------------------------------------

def test_invoke_claude_extract_builds_argv(tmp_path):
    proj = _make_project(tmp_path)
    out = tmp_path / "talks" / "draft_1" / "00_phase0" / "claim_inventory.tsv"

    # F5: --output-format json makes stdout a result envelope with cost.
    envelope = json.dumps(
        {"type": "result", "result": "ok", "total_cost_usd": 0.1234}
    )
    fake_proc = MagicMock(returncode=0, stdout=envelope, stderr="")

    captured_argv = []
    def _fake_run(cmd, **kwargs):
        captured_argv.extend(cmd)
        # Simulate the LLM writing the TSV (presence is the success signal)
        _write_synthetic_tsv(out)
        return fake_proc

    with patch.object(subprocess, "run", side_effect=_fake_run):
        diag = ec.invoke_claude_extract(
            report_path=proj / "REPORT.md",
            methods_provenance_path=proj / "methods_provenance.md",
            output_tsv_path=out,
            claude_bin="claude",
        )

    # Expected argv shape mirrors paper-writer orchestrator.py:325-332
    assert captured_argv[0] == "claude"
    assert "-p" in captured_argv
    assert "--system-prompt" in captured_argv
    assert "--allowedTools" in captured_argv
    assert "Read,Write,Edit,Bash,Grep,Glob" in captured_argv
    assert "--dangerously-skip-permissions" in captured_argv
    # B6: the model MUST be pinned (unpinned `claude -p` resolves a
    # context-dependent model — paper-writer's draft_9 regression).
    assert "--model" in captured_argv
    assert captured_argv[captured_argv.index("--model") + 1] == "claude-sonnet-4-6"
    # F5: --output-format json so the result envelope carries total_cost_usd.
    assert "--output-format" in captured_argv
    assert captured_argv[captured_argv.index("--output-format") + 1] == "json"

    # Diagnostic shape
    assert diag["tool"] == "extract_claims"
    assert diag["phase"] == "llm_extract"
    assert diag["exit_status"] == 0
    assert diag["output_present"] is True
    assert "duration_sec" in diag
    assert "stdout_tail" in diag
    assert "stderr_tail" in diag
    assert diag["model"] == "claude-sonnet-4-6"
    # F5: cost parsed from the envelope.
    assert diag["cost_usd"] == 0.1234
    assert diag["cost_note"] is None


def test_invoke_claude_extract_model_override(tmp_path):
    """A non-default --model value is threaded into the argv + diagnostic."""
    proj = _make_project(tmp_path)
    out = tmp_path / "talks" / "draft_1" / "00_phase0" / "claim_inventory.tsv"

    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    captured_argv = []
    def _fake_run(cmd, **kwargs):
        captured_argv.extend(cmd)
        _write_synthetic_tsv(out)
        return fake_proc

    with patch.object(subprocess, "run", side_effect=_fake_run):
        diag = ec.invoke_claude_extract(
            report_path=proj / "REPORT.md",
            methods_provenance_path=proj / "methods_provenance.md",
            output_tsv_path=out,
            claude_bin="claude",
            model="claude-opus-4-6",
        )

    assert captured_argv[captured_argv.index("--model") + 1] == "claude-opus-4-6"
    assert diag["model"] == "claude-opus-4-6"


def test_invoke_claude_extract_records_failure(tmp_path):
    proj = _make_project(tmp_path)
    out = tmp_path / "talks" / "draft_1" / "00_phase0" / "claim_inventory.tsv"

    fake_proc = MagicMock(returncode=42, stdout="", stderr="boom")
    with patch.object(subprocess, "run", return_value=fake_proc):
        diag = ec.invoke_claude_extract(
            report_path=proj / "REPORT.md",
            methods_provenance_path=proj / "methods_provenance.md",
            output_tsv_path=out,
            claude_bin="claude",
        )
    assert diag["exit_status"] == 42
    assert diag["output_present"] is False  # TSV not written
    assert "boom" in diag["stderr_tail"]
    # F5: empty stdout (no envelope) → cost 0.0, never raises.
    assert diag["cost_usd"] == 0.0


def test_invoke_claude_extract_missing_prompt_raises(tmp_path):
    proj = _make_project(tmp_path)
    out = tmp_path / "claim_inventory.tsv"
    with pytest.raises(FileNotFoundError, match="prompt not found"):
        ec.invoke_claude_extract(
            report_path=proj / "REPORT.md",
            methods_provenance_path=proj / "methods_provenance.md",
            output_tsv_path=out,
            prompt_path=tmp_path / "does_not_exist.md",
        )


# ---------------------------------------------------------------------------
# _parse_cost_from_envelope (F5)
# ---------------------------------------------------------------------------

def test_parse_cost_from_envelope_happy():
    """A well-formed --output-format json envelope yields the cost, no note."""
    envelope = json.dumps(
        {"type": "result", "result": "done", "total_cost_usd": 0.0734}
    )
    cost, note = ec._parse_cost_from_envelope(envelope)
    assert cost == 0.0734
    assert note is None


def test_parse_cost_from_envelope_empty():
    """Empty stdout → 0.0 + an explanatory note (never raises)."""
    cost, note = ec._parse_cost_from_envelope("")
    assert cost == 0.0
    assert note and "empty" in note


def test_parse_cost_from_envelope_unparseable():
    """Non-JSON stdout → 0.0 + a note; a telemetry miss never fails."""
    cost, note = ec._parse_cost_from_envelope("not json at all")
    assert cost == 0.0
    assert note and "not parseable" in note


def test_parse_cost_from_envelope_missing_field():
    """A valid envelope with no total_cost_usd → 0.0 + a note."""
    cost, note = ec._parse_cost_from_envelope(json.dumps({"result": "ok"}))
    assert cost == 0.0
    assert note and "total_cost_usd" in note


# ---------------------------------------------------------------------------
# invoke_validator
# ---------------------------------------------------------------------------

def test_invoke_validator_builds_argv(tmp_path):
    proj = _make_project(tmp_path)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_synthetic_tsv(tsv)

    fake_proc = MagicMock(returncode=0, stdout="", stderr="validate_claim_inventory: total=1")
    captured_argv = []
    def _fake_run(cmd, **kwargs):
        captured_argv.extend(cmd)
        return fake_proc

    with patch.object(subprocess, "run", side_effect=_fake_run):
        diag = ec.invoke_validator(
            tsv_path=tsv, project_root=proj,
            audit_json_path=tmp_path / "audit" / "validation.json",
        )

    assert any(arg.endswith("validate_claim_inventory.py") for arg in captured_argv)
    assert "--tsv" in captured_argv
    assert "--project-root" in captured_argv
    assert "--audit" in captured_argv
    assert diag["exit_status"] == 0
    assert diag["phase"] == "validator"


def test_invoke_validator_missing_validator_raises(tmp_path):
    proj = _make_project(tmp_path)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_synthetic_tsv(tsv)
    with pytest.raises(FileNotFoundError, match="validate_claim_inventory.py not found"):
        ec.invoke_validator(
            tsv_path=tsv, project_root=proj,
            validator_path=tmp_path / "does_not_exist.py",
        )


# ---------------------------------------------------------------------------
# append_audit
# ---------------------------------------------------------------------------

def test_append_audit_creates_jsonl_one_record_per_call(tmp_path):
    audit_dir = tmp_path / "audit"
    diag1 = {"tool": "extract_claims", "phase": "llm_extract", "exit_status": 0}
    diag2 = {"tool": "extract_claims", "phase": "validator", "exit_status": 0}
    ec.append_audit(audit_dir, diag1)
    ec.append_audit(audit_dir, diag2)
    audit_path = audit_dir / "phase0.jsonl"
    assert audit_path.is_file()
    lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["phase"] == "llm_extract"
    assert parsed[1]["phase"] == "validator"


# ---------------------------------------------------------------------------
# main CLI
# ---------------------------------------------------------------------------

def test_main_missing_report_exits_1(tmp_path):
    proj = _make_project(tmp_path)
    out = tmp_path / "claim_inventory.tsv"
    rc = ec.main([
        "--report", str(tmp_path / "nope.md"),
        "--methods-provenance", str(proj / "methods_provenance.md"),
        "--project-root", str(proj),
        "--output", str(out),
    ])
    assert rc == 1


def test_main_missing_project_root_exits_1(tmp_path):
    proj = _make_project(tmp_path)
    out = tmp_path / "claim_inventory.tsv"
    rc = ec.main([
        "--report", str(proj / "REPORT.md"),
        "--methods-provenance", str(proj / "methods_provenance.md"),
        "--project-root", str(tmp_path / "not_a_dir"),
        "--output", str(out),
    ])
    assert rc == 1


def test_main_no_claude_binary_exits_2(tmp_path, monkeypatch):
    proj = _make_project(tmp_path)
    out = tmp_path / "claim_inventory.tsv"
    # Ensure no `claude` on PATH for this test:
    monkeypatch.setenv("PATH", "/nonexistent_dir_for_test")
    rc = ec.main([
        "--report", str(proj / "REPORT.md"),
        "--methods-provenance", str(proj / "methods_provenance.md"),
        "--project-root", str(proj),
        "--output", str(out),
        "--claude-bin", "claude-does-not-exist-anywhere",
    ])
    assert rc == 2


def test_main_skip_validator_short_circuits(tmp_path):
    proj = _make_project(tmp_path)
    out = tmp_path / "claim_inventory.tsv"
    # Pre-create the output so the LLM path is fast-skipped.
    _write_synthetic_tsv(out)

    # No subprocess.run should be invoked at all in --skip-validator path
    with patch.object(subprocess, "run") as mock_run:
        rc = ec.main([
            "--report", str(proj / "REPORT.md"),
            "--methods-provenance", str(proj / "methods_provenance.md"),
            "--project-root", str(proj),
            "--output", str(out),
            "--skip-validator",
        ])
    assert rc == 0
    assert mock_run.call_count == 0  # neither LLM nor validator called


def test_main_idempotent_output_skips_llm(tmp_path):
    """If --output exists and is non-empty, skip the `claude -p` call."""
    proj = _make_project(tmp_path)
    out = tmp_path / "claim_inventory.tsv"
    _write_synthetic_tsv(out)  # pre-existing output

    # Mock validator subprocess.run; we want to verify ONLY the validator
    # path runs, not the LLM path.
    fake_validator = MagicMock(returncode=0, stdout="", stderr="validate_claim_inventory: total=1")
    with patch.object(subprocess, "run", return_value=fake_validator) as mock_run:
        rc = ec.main([
            "--report", str(proj / "REPORT.md"),
            "--methods-provenance", str(proj / "methods_provenance.md"),
            "--project-root", str(proj),
            "--output", str(out),
        ])
    assert rc == 0
    # Exactly one subprocess.run call (the validator); the LLM path was skipped.
    assert mock_run.call_count == 1
    # And it was the validator, not claude:
    argv = mock_run.call_args[0][0]
    assert any(a.endswith("validate_claim_inventory.py") for a in argv)
