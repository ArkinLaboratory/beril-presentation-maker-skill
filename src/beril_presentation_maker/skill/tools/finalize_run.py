#!/usr/bin/env python3
"""finalize_run.py — v0.3.4.2 audit hygiene closer.

At the end of every orchestrator invocation (success or failure),
walks the draft's per-stage `.metadata.json` sidecars (written by
stream_progress.py at each `claude -p` call) and produces two
consolidated outputs:

1. **audit/stage-metadata.json** — single document keyed by stage
   name, containing per-stage tokens / cost / elapsed / model.
   Replaces the chaos of 13+ scattered `*.metadata.json` files
   that pre-v0.3.4.2 audits had to grep-collate by hand.

2. **audit/runs/run-<N>/summary.json** — per-orchestrator-invocation
   summary: started_at, finished_at, exit_code, stages_run,
   total_cost_usd, total_input_tokens, total_output_tokens, model.
   The audit/runs/ directory was declared in v0.3.1's draft_paths.py
   but no code populated it until v0.3.4.2.

Both writes are idempotent in the sense that repeated invocations
overwrite stage-metadata.json (always reflects current state) and
allocate the next sequential run-N directory (each invocation is
its own run).

The bash orchestrator hooks via `trap EXIT` in
presentation_maker.sh — runs even on partial pipelines or
Ctrl-C. Reads the actual on-disk .metadata.json files, so it
captures whatever stages completed.

CLI:
    python3 finalize_run.py write \\
        --draft-dir <draft> \\
        --exit-code <N> \\
        [--orchestrator-pid <PID>] \\
        [--started-at <ISO-8601>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Import draft_paths sibling for canonical path resolution
_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))
import draft_paths as dp  # noqa: E402


# Stage name extraction. Per-stage metadata files land at paths like:
#   working/00_plan.md.metadata.json          → "plan"
#   working/00_throughline_candidates.md.metadata.json → "throughline_candidates"
#   working/02_substories.md.metadata.json    → "substory_design" (renamed)
#   working/citation_pool.json.metadata.json  → "citation_pool"
#   working/cross_tenant_signal.{md,json}.metadata.json → "cross_tenant"
#   working/03_slides/intro.json.metadata.json → "intro"
#   working/03_slides/S1_slides.json.metadata.json → "slide_compose-S1"
#   working/03_slides/qa_anticipated.json.metadata.json → "qa_prep"
#   working/04_speaker_notes/S1_speaker_notes.md.metadata.json → "speaker_notes-S1"
#   working/05_image_requests/S1-pos5_request.json.metadata.json → "ai_image_prompt-S1-pos5"
#
# The pattern is: walk all *.metadata.json files under working/, derive a
# stage label from the parent filename. Some require special-casing.

_STAGE_LABEL_RE_BY_NAME = {
    "00_plan.md": "plan",
    "00_throughline_candidates.md": "throughline_candidates",
    "02_substories.md": "substory_design",
    "citation_pool.json": "citation_pool",
    "cross_tenant_signal.md": "cross_tenant",
    "cross_tenant_signal.json": "cross_tenant",
    "intro.json": "intro",
    "qa_anticipated.json": "qa_prep",
}

_STAGE_LABEL_PATTERNS = [
    # working/03_slides/<sid>_slides.json
    (re.compile(r"^(S\d+)_slides\.json$"), lambda m: f"slide_compose-{m.group(1)}"),
    # working/04_speaker_notes/<sid>_speaker_notes.md
    (re.compile(r"^(S\d+)_speaker_notes\.md$"), lambda m: f"speaker_notes-{m.group(1)}"),
    # working/05_image_requests/<slide_id>_request.json
    (re.compile(r"^(.+)_request\.json$"), lambda m: f"ai_image_prompt-{m.group(1)}"),
]


def _stage_label(metadata_file: Path) -> str:
    """Derive a stage label from a *.metadata.json filename. The
    metadata file is named <target>.metadata.json so we look at
    target (i.e., strip the .metadata.json suffix)."""
    target_name = metadata_file.name[: -len(".metadata.json")]
    if target_name in _STAGE_LABEL_RE_BY_NAME:
        return _STAGE_LABEL_RE_BY_NAME[target_name]
    for regex, formatter in _STAGE_LABEL_PATTERNS:
        m = regex.match(target_name)
        if m:
            return formatter(m)
    # Fallback: use the target filename verbatim (without suffix)
    return target_name


def collect_stage_metadata(working_dir: Path) -> dict[str, dict]:
    """Walk working/ recursively for *.metadata.json files; return a
    dict keyed by stage label, value is the metadata dict.

    Order is non-deterministic per-call; the caller can sort if it
    matters for the final write.
    """
    out: dict[str, dict] = {}
    if not working_dir.is_dir():
        return out
    for f in working_dir.rglob("*.metadata.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        label = _stage_label(f)
        # If two files map to the same label (e.g., a stage retry left
        # both versions on disk), keep the LATEST by mtime.
        if label in out:
            existing_mtime = out[label].get("_mtime", 0)
            this_mtime = f.stat().st_mtime
            if this_mtime <= existing_mtime:
                continue
        data["_mtime"] = f.stat().st_mtime
        data["_source_path"] = str(f.relative_to(working_dir))
        out[label] = data
    # Strip _mtime (internal); keep _source_path for audit traceability
    for label, meta in out.items():
        meta.pop("_mtime", None)
    return out


def aggregate_run_totals(stage_metadata: dict[str, dict]) -> dict:
    """Sum per-stage costs / tokens / elapsed for the run summary.

    Returns a dict with: total_cost_usd, total_input_tokens,
    total_output_tokens, total_cache_read_tokens,
    total_cache_creation_tokens, total_elapsed_seconds, models_used.
    """
    totals = {
        "total_cost_usd": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_creation_tokens": 0,
        "total_elapsed_seconds": 0,
    }
    models_used: set[str] = set()
    for label, meta in stage_metadata.items():
        totals["total_cost_usd"] += float(meta.get("estimated_cost_usd", 0.0))
        totals["total_input_tokens"] += int(meta.get("input_tokens", 0))
        totals["total_output_tokens"] += int(meta.get("output_tokens", 0))
        totals["total_cache_read_tokens"] += int(meta.get("cache_read_tokens", 0))
        totals["total_cache_creation_tokens"] += int(
            meta.get("cache_creation_tokens", 0))
        totals["total_elapsed_seconds"] += int(meta.get("elapsed_seconds", 0))
        m = meta.get("model")
        if m:
            models_used.add(m)
    totals["models_used"] = sorted(models_used)
    totals["total_cost_usd"] = round(totals["total_cost_usd"], 4)
    return totals


def write_stage_metadata(paths: dp.DraftPaths,
                         stage_metadata: dict[str, dict]) -> Path:
    """Write the consolidated audit/stage-metadata.json. Returns the
    path written. Idempotent — overwrites prior content."""
    paths.audit.mkdir(parents=True, exist_ok=True)
    target = paths.stage_metadata
    envelope = {
        "schema_version": "stage-metadata.v1",
        "draft_dir": str(paths.draft_dir),
        "stages": dict(sorted(stage_metadata.items())),
    }
    target.write_text(
        json.dumps(envelope, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _next_run_n(runs_dir: Path) -> int:
    """Allocate the next run-<N> directory by scanning existing ones."""
    if not runs_dir.is_dir():
        return 1
    n = 1
    while (runs_dir / f"run-{n}").is_dir():
        n += 1
        if n > 9999:
            raise RuntimeError(
                f"cannot allocate run directory under {runs_dir}; "
                f"too many existing runs"
            )
    return n


def write_run_summary(paths: dp.DraftPaths,
                      *,
                      exit_code: int,
                      started_at: Optional[str] = None,
                      stage_metadata: Optional[dict[str, dict]] = None) -> Path:
    """Write audit/runs/run-<N>/summary.json. Allocates the next
    available run-N. Returns the summary path written."""
    if stage_metadata is None:
        stage_metadata = collect_stage_metadata(paths.working)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    n = _next_run_n(paths.runs_dir)
    run_dir = paths.run_archive_dir(n)
    run_dir.mkdir(parents=True, exist_ok=True)

    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if started_at is None:
        started_at = finished_at  # fallback if caller didn't provide

    totals = aggregate_run_totals(stage_metadata)
    summary = {
        "schema_version": "run-summary.v1",
        "run_n": n,
        "draft_dir": str(paths.draft_dir),
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": int(exit_code),
        "stages_run": sorted(stage_metadata.keys()),
        **totals,
    }
    target = run_dir / "summary.json"
    target.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_write(args) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    if not paths.is_initialized():
        print(f"finalize_run: draft_dir not initialized: {paths.draft_dir}",
              file=sys.stderr)
        return 1
    stage_meta = collect_stage_metadata(paths.working)
    stage_meta_path = write_stage_metadata(paths, stage_meta)
    summary_path = write_run_summary(
        paths,
        exit_code=args.exit_code,
        started_at=args.started_at,
        stage_metadata=stage_meta,
    )
    n_stages = len(stage_meta)
    totals = aggregate_run_totals(stage_meta)
    print(
        f"finalize_run: consolidated {n_stages} stages "
        f"(${totals['total_cost_usd']:.4f}, "
        f"{totals['total_input_tokens']:,} in / "
        f"{totals['total_output_tokens']:,} out tokens, "
        f"{totals['total_elapsed_seconds']}s)",
        file=sys.stderr,
    )
    print(f"  stage-metadata: {stage_meta_path}", file=sys.stderr)
    print(f"  run summary: {summary_path}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="finalize_run",
        description=(
            "v0.3.4.2: consolidate per-stage .metadata.json sidecars "
            "into audit/stage-metadata.json + write per-orchestrator "
            "audit/runs/run-N/summary.json."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser(
        "write",
        help="Walk working/ for .metadata.json files; write consolidations.",
    )
    p_write.add_argument("--draft-dir", required=True)
    p_write.add_argument("--exit-code", type=int, default=0,
                         help="Exit code from the orchestrator (default: 0).")
    p_write.add_argument("--started-at", default=None,
                         help="Orchestrator start time, ISO-8601 UTC. "
                              "If omitted, run summary uses finish time.")
    p_write.set_defaults(func=_cmd_write)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
