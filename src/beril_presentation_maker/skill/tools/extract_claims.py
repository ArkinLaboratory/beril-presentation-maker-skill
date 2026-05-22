#!/usr/bin/env python3
"""extract_claims.py — Standalone adapter for LLM claim-inventory extraction.

Authored for beril-presentation-maker v0.4 M1 (2026-05-12) per
V0_4_ARCHITECTURE.md §4.4 + D-040-rev1. Wraps the same `claude -p`
invocation paper-writer's orchestrator.py performs at `phase_triage`
(orchestrator.py lines 309-375), exposing it as a standalone CLI tool
that the presentation-maker orchestrator (M2 deliverable) will call.

Active path per paper-writer STAGED_IMPROVEMENT_PLAN.md Stage 1
(closed 2026-05-11): "agent-built Python orchestrator + holistic-draft
prompt + LLM-only Phase-0 extraction is the right shape." This adapter
implements that pattern for presentation-maker without re-introducing
the deferred M1 §B1 regex+demarcation machinery from
paper-writer's `claim_inventory.py` (see feedback memory
`feedback_vendor_port_verify_active_path.md`).

Two-step pipeline:
  1. Invoke `claude -p` with prompts/extract_claims.v1.md as system
     prompt. The LLM reads REPORT.md + methods_provenance.md and emits
     `claim_inventory.tsv` via the Write tool.
  2. Chain `validate_claim_inventory.py` against the emitted TSV.
     Validator clears LLM-fabricated source_notebook paths (~10%
     fabrication rate observed on paper-writer's draft_3).

The validator step is NOT optional. The LLM's source_notebook
fabrication rate makes raw extraction output unreliable for
downstream consumers (M2's architect consumes claim_inventory.tsv as
a constraint table; fabricated rows would poison the architecture).

Usage:
    extract_claims.py \\
        --report <REPORT.md> \\
        --methods-provenance <methods_provenance.md> \\
        --project-root <projects/<id>/> \\
        --output <claim_inventory.tsv> \\
        [--audit-dir <audit_dir>] \\
        [--claude-bin claude] \\
        [--model claude-sonnet-4-6] \\
        [--skip-validator]

Exit codes:
  0 — extraction + validation succeeded (TSV written, validator ran).
  1 — user error (missing required input file, bad CLI args).
  2 — LLM call failed (claude -p returned non-zero or no TSV produced).
  3 — validator failed (validate_claim_inventory.py returned non-zero).

Test coverage: tests/unit/test_extract_claims.py (mocked subprocess).
Smoke coverage: tier-D smoke against ibd_phage_targeting (M1 plan).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


VERSION = "0.4.0-m1-tierB.1"  # B6: pinned model in the `claude -p` invocation

# Path resolution: prompt + sibling validator both live relative to this
# module. Mirrors paper-writer's pattern at orchestrator.py:310 / :349.
_MODULE_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _MODULE_DIR.parent
_PROMPT_PATH = _SKILL_DIR / "prompts" / "extract_claims.v1.md"
_VALIDATOR_PATH = _MODULE_DIR / "validate_claim_inventory.py"

# Allowed tools for the `claude -p` subprocess. Matches paper-writer's
# invocation at orchestrator.py:329. The LLM needs Read+Write (read
# inputs, write TSV), plus Grep/Glob/Bash for notebook-cell scanning,
# plus Edit (rarely used but present for symmetry with upstream).
_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Grep,Glob"

# Default model for the `claude -p` extraction call. MUST be pinned:
# an unpinned `claude -p` resolves a different default model by
# execution context (plain shell vs. nested Claude Code), and a
# context-resolved model produced the draft_9 source_notebook
# regression in paper-writer (their Tier G post-mortem, 2026-05-14).
# claude-sonnet-4-6 matches presentation_maker.sh:79's MODEL pin so
# the originate path is consistent with the rest of the orchestrator.
# The M2 orchestrator wiring should pass --model "$MODEL" through;
# this default is the floor, not a substitute for explicit pinning.
_DEFAULT_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# UTC helper
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Subprocess wrapper for `claude -p`
# ---------------------------------------------------------------------------

def invoke_claude_extract(
    *,
    report_path: Path,
    methods_provenance_path: Path,
    output_tsv_path: Path,
    prompt_path: Path = _PROMPT_PATH,
    claude_bin: str = "claude",
    model: str = _DEFAULT_MODEL,
    env: Optional[dict] = None,
) -> dict:
    """Invoke `claude -p` to extract claims into a TSV.

    ``model`` is passed through as an explicit ``--model`` flag. It is
    pinned by default (see ``_DEFAULT_MODEL``) because an unpinned
    ``claude -p`` resolves a context-dependent default model — the
    root cause of paper-writer's draft_9 regression.

    Returns a diagnostic dict: ``{"exit_status", "stdout", "stderr",
    "output_present", "duration_sec", "model"}``. Does NOT raise on
    subprocess failure; the caller decides escalation based on the
    diagnostic.
    """
    if not prompt_path.is_file():
        raise FileNotFoundError(
            f"extract_claims prompt not found at {prompt_path}; "
            f"check that the skill package is installed correctly."
        )
    system_prompt = prompt_path.read_text(encoding="utf-8")

    user_prompt = (
        "Please execute the extract claims task.\n"
        f"- REPORT_PATH: {report_path}\n"
        f"- METHODS_PATH: {methods_provenance_path}\n"
        f"- OUTPUT_PATH: {output_tsv_path}\n"
        "\n"
        "Write the resulting TSV strictly to OUTPUT_PATH using the Write tool."
    )

    cmd = [
        claude_bin, "-p",
        "--model", model,
        "--system-prompt", system_prompt,
        "--allowedTools", _ALLOWED_TOOLS,
        "--dangerously-skip-permissions",
        user_prompt,
    ]

    output_tsv_path.parent.mkdir(parents=True, exist_ok=True)

    start = _utc_now_iso()
    t0 = datetime.now(timezone.utc)
    proc = subprocess.run(
        cmd,
        env=env if env is not None else os.environ.copy(),
        capture_output=True,
        text=True,
    )
    duration = (datetime.now(timezone.utc) - t0).total_seconds()

    diag = {
        "tool": "extract_claims",
        "version": VERSION,
        "phase": "llm_extract",
        "timestamp": start,
        "duration_sec": duration,
        "exit_status": proc.returncode,
        "output_present": output_tsv_path.is_file(),
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
        "claude_bin": claude_bin,
        "model": model,
    }
    return diag


# ---------------------------------------------------------------------------
# Validator chain
# ---------------------------------------------------------------------------

def invoke_validator(
    *,
    tsv_path: Path,
    project_root: Path,
    audit_json_path: Optional[Path] = None,
    validator_path: Path = _VALIDATOR_PATH,
    python_bin: str = sys.executable,
) -> dict:
    """Chain validate_claim_inventory.py against the emitted TSV.

    Returns a diagnostic dict mirroring ``invoke_claude_extract``'s shape.
    Validator non-zero exit is surfaced via ``exit_status``; the caller
    decides whether it's a halt or advisory.
    """
    if not validator_path.is_file():
        raise FileNotFoundError(
            f"validate_claim_inventory.py not found at {validator_path}"
        )
    cmd = [
        python_bin, str(validator_path),
        "--tsv", str(tsv_path),
        "--project-root", str(project_root),
    ]
    if audit_json_path is not None:
        cmd.extend(["--audit", str(audit_json_path)])

    start = _utc_now_iso()
    t0 = datetime.now(timezone.utc)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    duration = (datetime.now(timezone.utc) - t0).total_seconds()

    return {
        "tool": "extract_claims",
        "version": VERSION,
        "phase": "validator",
        "timestamp": start,
        "duration_sec": duration,
        "exit_status": proc.returncode,
        "audit_json_path": str(audit_json_path) if audit_json_path else None,
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
    }


# ---------------------------------------------------------------------------
# Audit JSONL emission
# ---------------------------------------------------------------------------

def append_audit(audit_dir: Path, diag: dict) -> None:
    """Append one diagnostic record to ``<audit_dir>/phase0.jsonl``.

    Matches paper-writer's audit JSONL pattern (per their tools'
    audit conventions; one line per tool invocation).
    """
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "phase0.jsonl"
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(diag, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="extract_claims.py",
        description=(
            "Standalone adapter: invoke `claude -p` with extract_claims.v1.md "
            "to extract claim_inventory.tsv from REPORT.md + methods_provenance.md, "
            "then chain validate_claim_inventory.py. Active-path Phase-0 tool "
            "per paper-writer Stage 1 Tier E (2026-05-11) and "
            "V0_4_ARCHITECTURE.md §4.4."
        ),
    )
    p.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to REPORT.md (canonical findings).",
    )
    p.add_argument(
        "--methods-provenance",
        type=Path,
        required=True,
        help=(
            "Path to methods_provenance.md (produced by extract_methods.py). "
            "The LLM uses this to link each numeric claim to a notebook."
        ),
    )
    p.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help=(
            "Project root containing notebooks/ subdirectory. The validator "
            "checks <project-root>/notebooks/<source_notebook> for every row."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write claim_inventory.tsv.",
    )
    p.add_argument(
        "--audit-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory for audit JSONL + validator JSON. "
            "Recommended: <talks/draft_N/audit/>."
        ),
    )
    p.add_argument(
        "--claude-bin",
        default="claude",
        help="Path to claude CLI binary (default: 'claude' on PATH).",
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=(
            f"Model for the `claude -p` extraction call (default: "
            f"{_DEFAULT_MODEL}). MUST stay pinned — an unpinned call "
            f"resolves a context-dependent model and caused paper-writer's "
            f"draft_9 source_notebook regression. The M2 orchestrator "
            f"should pass its own --model through for consistency."
        ),
    )
    p.add_argument(
        "--skip-validator",
        action="store_true",
        help=(
            "Debug flag: skip the validator chain. Production use should "
            "NOT pass this — the validator catches LLM source_notebook "
            "fabrications (~10% rate observed on paper-writer's draft_3)."
        ),
    )
    args = p.parse_args(argv)

    # Input sanity
    for label, path in [
        ("--report", args.report),
        ("--methods-provenance", args.methods_provenance),
    ]:
        if not path.is_file():
            sys.stderr.write(f"error: {label} not a file: {path}\n")
            return 1
    if not args.project_root.is_dir():
        sys.stderr.write(f"error: --project-root not a directory: {args.project_root}\n")
        return 1

    # Idempotent fast-path: if output exists and is non-empty, skip the
    # LLM. Mirrors paper-writer orchestrator.py:315 ("not claims_out.exists()").
    if args.output.is_file() and args.output.stat().st_size > 0:
        sys.stderr.write(
            f"extract_claims: output already exists, skipping LLM: {args.output}\n"
        )
    else:
        # Verify claude CLI is available before paying the setup cost.
        if shutil.which(args.claude_bin) is None and not Path(args.claude_bin).is_file():
            sys.stderr.write(
                f"error: claude CLI not found at '{args.claude_bin}'. "
                f"Set --claude-bin or add 'claude' to PATH.\n"
            )
            return 2

        extract_diag = invoke_claude_extract(
            report_path=args.report.resolve(),
            methods_provenance_path=args.methods_provenance.resolve(),
            output_tsv_path=args.output.resolve(),
            claude_bin=args.claude_bin,
            model=args.model,
        )
        if args.audit_dir is not None:
            append_audit(args.audit_dir.resolve(), extract_diag)

        if extract_diag["exit_status"] != 0 or not extract_diag["output_present"]:
            sys.stderr.write(
                f"extract_claims: LLM extraction failed "
                f"(exit={extract_diag['exit_status']}, "
                f"output_present={extract_diag['output_present']}); "
                f"stderr tail: {extract_diag['stderr_tail'][-300:]}\n"
            )
            return 2

    # Validator chain
    if args.skip_validator:
        sys.stderr.write(
            "extract_claims: --skip-validator set; raw LLM output not validated. "
            "DO NOT use in production.\n"
        )
        return 0

    audit_json_path = None
    if args.audit_dir is not None:
        audit_json_path = args.audit_dir / "claim_inventory_validation.json"

    validator_diag = invoke_validator(
        tsv_path=args.output.resolve(),
        project_root=args.project_root.resolve(),
        audit_json_path=audit_json_path.resolve() if audit_json_path else None,
    )
    if args.audit_dir is not None:
        append_audit(args.audit_dir.resolve(), validator_diag)

    if validator_diag["exit_status"] != 0:
        sys.stderr.write(
            f"extract_claims: validator failed "
            f"(exit={validator_diag['exit_status']}); "
            f"stderr tail: {validator_diag['stderr_tail'][-300:]}\n"
        )
        return 3

    # Surface validator's summary line (it writes to stderr).
    if validator_diag.get("stderr_tail"):
        sys.stderr.write(validator_diag["stderr_tail"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
