#!/usr/bin/env python3
"""finalize_run.py — v0.3.4.2 audit hygiene closer + Cycle-3/DP1
run-record.v1 emitter.

At the end of every orchestrator invocation (success or failure),
walks the draft's per-stage `.metadata.json` sidecars (written by
stream_progress.py at each `claude -p` call) and produces three
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

3. **audit/run_record.json + audit/runs/run-N/run_record.json**
   (Cycle 3 / DP1, 2026-06-07) — the cross-skill `run-record.v1`
   contract (validator in craft-platform `craft.run_record`). The
   canonical path is the LATEST run's record (`craft status` polls
   it); the archive is a per-run history copy. Re-runs allocate
   the next `run-N` (mirror `_next_run_n`), write the archive,
   then atomically replace the canonical via tempfile +
   `os.replace` in the same directory.

   Three CLI write points support the incremental contract:
     record-start    : initial write (status=running, empty stages)
     record-stage    : append/patch one stage entry, refresh totals
     record-finalize : terminal write (status=completed|failed) —
                       MUST NOT overwrite an existing status=halted
                       (the halt-gate writer owns that transition).

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

    python3 finalize_run.py record-start \\
        --draft-dir <draft> --started-at <ISO> \\
        [--mode <m>] [--skill-version <v>]

    python3 finalize_run.py record-stage \\
        --draft-dir <draft> --stage <id> --status <s> \\
        [--model <m>] [--started-at <ISO>] [--finished-at <ISO>]

    python3 finalize_run.py record-finalize \\
        --draft-dir <draft> --exit-code <N> --started-at <ISO> \\
        [--skill-version <v>]

    python3 finalize_run.py record-halt \\
        --draft-dir <draft> --gate <id> --started-at <ISO> \\
        [--skill-version <v>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from beril_presentation_maker import __version__ as _skill_version

# Public alias used throughout this module — keeps the call sites
# readable while satisfying ruff N812 (don't import a lowercase
# dunder as an ALL_CAPS name).
_SKILL_VERSION = _skill_version

# Import draft_paths sibling for canonical path resolution
_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))
import draft_paths as dp  # noqa: E402


class CompletenessError(Exception):
    """Raised at finalize when the C1-A2 completeness guard finds the
    canonical would drop a stage a prior run completed. Carries the list
    of human-readable error strings. Caught at the CLI boundary → loud
    non-zero exit; never silently swallowed."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__("; ".join(errors))


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
    # The cross_tenant LLM writes the slide fragment to
    # 03_slides/cross_tenant.json; its sidecar must map to the same
    # `cross_tenant` id the orchestrator records, so finalize-time
    # reconciliation doesn't false-warn on an id mismatch.
    "cross_tenant.json": "cross_tenant",
    # Same for deck_close (writes 03_slides/deck_close.json).
    "deck_close.json": "deck_close",
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


# v1.3.1 / Cycle-3 follow-up P0-1: aggregate_run_totals +
# write_stage_metadata + write_run_summary (the legacy run-summary.v1 /
# stage-metadata.v1 archive) are RETIRED. run-record.v1 is a strict
# superset (stages[] + totals + status), and that archive ran its own
# uncoordinated _next_run_n against the shared audit/runs/ namespace —
# the second-allocator bug this fix removes. collect_stage_metadata +
# _stage_label below are KEPT: record-finalize still reads the per-stage
# .metadata.json sidecars for its loud reconciliation.


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


# ---------------------------------------------------------------------------
# C1-A2 — cross-record completeness guard (VENDORED from craft.run_record)
# ---------------------------------------------------------------------------
#
# The canonical implementation lives in craft-platform
# `craft.run_record.check_no_dropped_stages`. This skill ships STANDALONE
# on the hub (`pipx install …beril-presentation-maker-skill.git`, no
# craft-platform on PYTHONPATH), so — like the run-record validator and the
# llm_config/chrome vendoring — the function is COPIED here, not imported.
# A craft-platform conformance check pins this copy byte-equal to the
# canonical (don't edit one without the other). Keep the two in sync.
#
# Why it's needed: a resume must NEVER lose a stage a prior run completed.
# The per-record reconciliation only checks totals==sum(stages present), so
# an incomplete record reconciles perfectly. The C1-A drop (a resume after
# failure that opened a fresh empty run, losing the already-completed
# substory_design/curate_figures, ~$5 on the $40 run) is exactly this
# class. Called at finalize, BEFORE writing status=completed; a non-empty
# return is a hard, loud failure.


def _completed_stage_ids(record: object) -> set[str]:
    """The set of stage ids a record marks `completed`. Tolerant of a
    malformed record. (Vendored from craft.run_record.)"""
    out: set[str] = set()
    if not isinstance(record, dict):
        return out
    stages = record.get("stages")
    if not isinstance(stages, list):
        return out
    for s in stages:
        if (isinstance(s, dict) and s.get("status") == "completed"
                and isinstance(s.get("id"), str) and s["id"]):
            out.add(s["id"])
    return out


def check_no_dropped_stages(
    canonical: dict, archived_runs: list,
) -> list:
    """Cross-record completeness guard (C1-A2). The canonical's set of
    `completed` stage ids MUST be a SUPERSET of every archived run's
    `completed` set; returns error strings naming any dropped stage.
    Manifest-free. VENDORED byte-equal from craft.run_record — keep in
    sync (conformance-pinned)."""
    errors: list = []
    canon_completed = _completed_stage_ids(canonical)
    canon_run_id = (canonical.get("run_id")
                    if isinstance(canonical, dict) else None)
    for archived in archived_runs:
        arch_run_id = (archived.get("run_id")
                       if isinstance(archived, dict) else None)
        if arch_run_id is not None and arch_run_id == canon_run_id:
            continue
        arch_completed = _completed_stage_ids(archived)
        dropped = arch_completed - canon_completed
        if dropped:
            errors.append(
                f"completeness: canonical (run_id={canon_run_id!r}) is "
                f"missing {len(dropped)} stage(s) that archived run "
                f"{arch_run_id!r} completed: {sorted(dropped)} — a resume "
                f"must never drop a completed stage (C1-A). Refusing to "
                f"finalize as completed."
            )
    return errors


def _load_archived_runs(paths: dp.DraftPaths) -> list:
    """Load every archived runs/run-N/run_record.json as a parsed dict.
    Skips unreadable/non-JSON archives (forensic snapshots may be partial)
    — the completeness guard tolerates a malformed entry. Loud-warns on a
    parse failure so a corrupt archive is visible, but never raises."""
    out: list = []
    runs_dir = paths.runs_dir
    if not runs_dir.is_dir():
        return out
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        rr = run_dir / "run_record.json"
        if not rr.is_file():
            continue
        try:
            out.append(json.loads(rr.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"finalize_run: WARNING — could not read archived run "
                f"record {rr} for the completeness guard ({exc}); "
                f"skipping that archive.",
                file=sys.stderr,
            )
    return out


# ---------------------------------------------------------------------------
# Cycle 3 / DP1 — run-record.v1 emitter
# ---------------------------------------------------------------------------
#
# Cross-skill contract: validator + schema docstring in craft-platform
# `craft.run_record`. Three write points (record-start / record-stage /
# record-finalize) + one halt-gate (record-halt) cover the incremental
# protocol. All writes are atomic (tempfile in the SAME directory +
# os.replace) so `craft status` polling mid-run never observes a
# half-written file.
#
# Two-path strategy (the no-clobber rule from the brief):
#   canonical:  audit/run_record.json                  (latest run; pollable)
#   archive:    audit/runs/run-N/run_record.json       (per-run history)
# record-start allocates the next run-N (mirror _next_run_n), writes
# both copies, and pins the run_n in the canonical record so the
# subsequent record-stage / record-finalize calls can locate the
# matching archive without reallocating.

_RUN_RECORD_SCHEMA_VERSION = "run-record.v1"
_PRESMAKER_SKILL = "presentation-maker"

# record-finalize reconciliation: a recorded stage cost is allowed to
# fall this far below its sidecar cost before we flag it (rounding
# noise from the round(…, 6) on each side). Recorded cost ABOVE the
# sidecar is expected (image_gen folds generation cost) and never
# warns.
_COST_RECONCILE_TOLERANCE = 1e-4


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_minus_seconds(iso_ts: str, seconds: float) -> str:
    """Return `iso_ts` shifted back by `seconds`, in the same
    `YYYY-MM-DDTHH:MM:SSZ` shape. Used to back-date a stage's
    started_at from its finished_at + sidecar elapsed when the shell
    didn't capture a T0. On a parse failure, returns iso_ts unchanged
    (better a zero-duration stage than a crash in the trap path)."""
    try:
        from datetime import timedelta
        dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc,
        )
        shifted = dt - timedelta(seconds=float(seconds))
        return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return iso_ts


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Atomically write a JSON payload to `path`.

    Tempfile in the SAME directory (so `os.replace` is a single rename
    on the same filesystem; cross-fs replace is non-atomic on some
    posix variants) + delete=False (Python opens the tempfile; we
    close it before replace), encoding utf-8.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    import contextlib
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the tempfile if anything failed
        # between mkstemp and os.replace.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _load_existing_record(path: Path) -> dict | None:
    """Read the canonical run_record.json if present. None on absent
    or malformed (a downstream re-init will overwrite cleanly)."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _project_stages_from_metadata(
    stage_metadata: dict[str, dict],
) -> list[dict]:
    """Project the legacy stage-metadata.v1 dict into the ordered
    stages[] array required by run-record.v1.

    Each metadata entry knows: started_at, finished_at,
    elapsed_seconds, input_tokens, output_tokens, cache_*_tokens,
    estimated_cost_usd (→ cost_usd), model. We map each to a
    completed stage entry. Stages currently mid-flight aren't in
    the metadata sidecars (the sidecar is written on call return),
    so the trap-EXIT finalize sees only completed work.

    Sorted by started_at for determinism (the metadata dict
    insertion order is non-deterministic across runs).
    """
    out: list[dict] = []
    items = list(stage_metadata.items())
    # Sort by started_at when available, else label.
    items.sort(key=lambda kv: kv[1].get("started_at") or kv[0])
    for label, meta in items:
        started_at = meta.get("started_at") or _utc_iso_now()
        finished_at = meta.get("finished_at") or started_at
        out.append({
            "id": label,
            "status": "completed",
            "model": meta.get("model"),
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": float(meta.get("elapsed_seconds", 0)),
            "input_tokens": int(meta.get("input_tokens", 0)),
            "output_tokens": int(meta.get("output_tokens", 0)),
            "cache_read_tokens": int(meta.get("cache_read_tokens", 0)),
            "cache_creation_tokens": int(
                meta.get("cache_creation_tokens", 0)
            ),
            "cost_usd": round(
                float(meta.get("estimated_cost_usd", 0.0)), 6,
            ),
            "subrecord": None,
        })
    return out


def _read_sidecar_metadata(sidecar_path: Path) -> dict:
    """Read a per-stage `.metadata.json` sidecar (written by
    stream_progress.py at each `claude -p` call) into a normalized
    dict the shell-wired record-stage can fold into a stage entry.

    The sidecar carries: elapsed_seconds, input_tokens, output_tokens,
    cache_read_tokens, cache_creation_tokens (both omitted when zero),
    estimated_cost_usd, model. Returns {} on a missing/malformed
    sidecar — the caller treats absence as "no LLM cost" (a non-LLM
    stage has no sidecar) rather than an error.
    """
    if not sidecar_path.is_file():
        return {}
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "model": data.get("model"),
        "elapsed_seconds": float(data.get("elapsed_seconds", 0) or 0),
        "input_tokens": int(data.get("input_tokens", 0) or 0),
        "output_tokens": int(data.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(data.get("cache_read_tokens", 0) or 0),
        "cache_creation_tokens": int(
            data.get("cache_creation_tokens", 0) or 0
        ),
        "cost_usd": round(
            float(data.get("estimated_cost_usd", 0.0) or 0.0), 6,
        ),
    }


def _read_revise_metadata(meta_path: Path) -> dict:
    """Read audit/revise_loop_metadata.json (revise_loop.py's own
    provenance format — distinct from the stream_progress sidecars).
    Returns {cost_usd, started_at, finished_at}. The format carries
    `cost_usd_cumulative` + ISO timestamps but NO token counts and NO
    model (revise_loop drives nested claude calls and only tracks the
    rolled-up cost), so those stay 0/None. Empty on missing/malformed.
    """
    out = {"cost_usd": 0.0, "started_at": None, "finished_at": None}
    if not meta_path.is_file():
        return out
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(data, dict):
        return out
    out["cost_usd"] = round(float(data.get("cost_usd_cumulative", 0.0) or 0.0), 6)
    sa = data.get("started_at")
    fa = data.get("finished_at")
    out["started_at"] = sa if isinstance(sa, str) and sa else None
    out["finished_at"] = fa if isinstance(fa, str) and fa else None
    return out


def _sum_phase0_jsonl(jsonl_path: Path) -> dict:
    """Sum the `cost_usd` across all records in audit/phase0.jsonl
    (phase0_reuse.py's append-only decision log; the ORIGINATE path's
    extract_claims LLM call records `cost_usd` from the claude -p
    envelope; reuse / no-op records carry 0). Returns {cost_usd}.
    Empty on missing/malformed (reuse-only or no-paper run → $0).

    Like the revise-metadata format, phase0.jsonl carries no token
    counts and no model on its cost-bearing record, so only cost folds.
    """
    out = {"cost_usd": 0.0}
    if not jsonl_path.is_file():
        return out
    total = 0.0
    try:
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                c = rec.get("cost_usd")
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    total += float(c)
    except OSError:
        return out
    out["cost_usd"] = round(total, 6)
    return out


def _sidecar_parent_stage(label: str) -> str | None:
    """Map a per-call sidecar label to a recorded stage id that
    ALREADY ACCOUNTS FOR it, or None if the label is its own stage.
    Used by finalize reconciliation to skip a sidecar whose cost is
    already in a recorded entry (so it isn't double-counted /
    false-warned). Two cases:

    * Sub-unit fold: every `ai_image_prompt-*` prompt sidecar folds
      into the single `image_gen` stage (one prompt per generated
      image; the orchestrator sums them via --sidecar-glob and adds
      the per-image generation cost via --image-provenance).
    * Alias: the v0.4 `deck_outline` stage and the v0.3 `substory_design`
      stage BOTH write `02_substories.md`, whose sidecar maps to
      `substory_design`. On a v0.4 run the orchestrator records
      `deck_outline` from that same sidecar — so a `substory_design`
      sidecar is absorbed by a recorded `deck_outline` (only one of
      the two runs per pipeline).
    """
    if label.startswith("ai_image_prompt-"):
        return "image_gen"
    if label == "substory_design":
        return "deck_outline"
    return None


def _sum_image_provenance(provenance_path: Path) -> dict:
    """Aggregate the GENERATION cost of all approved images from
    audit/image_provenance.json (the append-only log image_client.py
    writes per image). This is the fix for the image_gen totals
    undercount: the prompt-composition LLM cost lives in the
    `ai_image_prompt-*` sidecars, but the actual image-GENERATION cost
    (the provider's per-image charge) only lives here. The image_gen
    stage entry must carry BOTH.

    Schema: {version, entries: [{cost_usd, elapsed_seconds, model,
    ...}]}. Returns {cost_usd, elapsed_seconds, models, n_entries}.
    Empty/malformed → zeros (no images generated this run).
    """
    out = {
        "cost_usd": 0.0,
        "elapsed_seconds": 0.0,
        "models": [],
        "n_entries": 0,
    }
    if not provenance_path.is_file():
        return out
    try:
        data = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return out
    models: set[str] = set()
    cost = 0.0
    elapsed = 0.0
    n = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        n += 1
        cost += float(e.get("cost_usd", 0.0) or 0.0)
        elapsed += float(e.get("elapsed_seconds", 0.0) or 0.0)
        m = e.get("model")
        if isinstance(m, str) and m:
            models.add(m)
    out["cost_usd"] = round(cost, 6)
    out["elapsed_seconds"] = elapsed
    out["models"] = sorted(models)
    out["n_entries"] = n
    return out


def _refresh_totals(stages: list[dict]) -> dict:
    """Sum stages[].* into the totals dict. The validator's
    reconciliation check (craft.run_record._check_totals_reconciliation)
    expects this exact relationship — any drift here is a real bug."""
    totals = {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "elapsed_seconds": 0.0,
    }
    for s in stages:
        totals["cost_usd"] += float(s.get("cost_usd", 0.0))
        totals["input_tokens"] += int(s.get("input_tokens", 0))
        totals["output_tokens"] += int(s.get("output_tokens", 0))
        totals["cache_read_tokens"] += int(s.get("cache_read_tokens", 0))
        totals["cache_creation_tokens"] += int(
            s.get("cache_creation_tokens", 0)
        )
        totals["elapsed_seconds"] += float(s.get("elapsed_seconds", 0.0))
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return totals


def _models_used(stages: list[dict]) -> list[str]:
    seen: set[str] = set()
    for s in stages:
        m = s.get("model")
        if isinstance(m, str) and m:
            seen.add(m)
    return sorted(seen)


def _project_artifacts(paths: dp.DraftPaths) -> dict:
    """Resolve the three artifact pointers paper-writer / presmaker
    share. Each is a string (relative path under draft_dir) when the
    artifact exists on disk; null otherwise. Pointers, not contents
    — telemetry / chrome read these to deep-dive."""
    def _rel(p: Path) -> str | None:
        return str(p.relative_to(paths.draft_dir)) if p.is_file() else None

    user_intent = _rel(paths.audit / "user_intent.json")
    deliverable_validation = _rel(
        paths.audit / "deliverable_validation.json"
    )
    # presmaker's deliverable is the assembled .pptx in deliverable/.
    deliverable = None
    pptx = paths.deliverable / "draft.pptx"
    if pptx.is_file():
        deliverable = _rel(pptx)
    return {
        "user_intent": user_intent,
        "deliverable_validation": deliverable_validation,
        "deliverable": deliverable,
    }


def _resolve_mode(paths: dp.DraftPaths) -> str | None:
    """Project mode from user_intent.json when present (DP9b link).
    Returns None when user_intent is missing or the field is absent
    — the validator's `mode: str | None` accepts both."""
    ui_path = paths.audit / "user_intent.json"
    if not ui_path.is_file():
        return None
    try:
        ui = json.loads(ui_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(ui, dict):
        return None
    mode = ui.get("mode")
    return mode if isinstance(mode, str) else None


def _build_record(
    paths: dp.DraftPaths,
    *,
    run_n: int,
    status: str,
    started_at: str,
    finished_at: str | None,
    exit_code: int | None,
    current_stage: str | None,
    stages: list[dict],
    skill_version: str,
) -> dict:
    """Assemble a run-record.v1 dict ready for validation + atomic
    write. The validator (craft.run_record.validate_run_record) is
    the single source of truth for the field set; if a key is
    missing here, the validator complains."""
    return {
        "schema_version": _RUN_RECORD_SCHEMA_VERSION,
        "skill": _PRESMAKER_SKILL,
        "skill_version": skill_version,
        "run_id": f"run-{run_n}",
        "draft_dir": str(paths.draft_dir),
        "mode": _resolve_mode(paths),
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "current_stage": current_stage,
        "stages": stages,
        "totals": _refresh_totals(stages),
        "models_used": _models_used(stages),
        "artifacts": _project_artifacts(paths),
    }


def write_run_record_canonical_and_archive(
    paths: dp.DraftPaths, record: dict, run_n: int,
) -> tuple[Path, Path]:
    """Write the record to BOTH the canonical path
    (audit/run_record.json) AND the per-run archive
    (audit/runs/run-N/run_record.json). Archive first, canonical
    second (an interrupted write leaves the archive intact and the
    canonical at the prior version)."""
    paths.audit.mkdir(parents=True, exist_ok=True)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = paths.run_archive_dir(run_n)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "run_record.json"
    _atomic_write_json(archive_path, record)
    canonical_path = paths.run_record
    _atomic_write_json(canonical_path, record)
    return canonical_path, archive_path


def record_start(
    paths: dp.DraftPaths,
    *,
    started_at: str,
    skill_version: str,
) -> tuple[Path, int]:
    """Initial write point. Allocates the next run-N (no-clobber on
    re-run — the prior canonical record's contents already moved to
    its own archive on its own record-finalize), writes a fresh
    status=running record with empty stages. Returns
    (canonical_path, run_n) so the caller can pin run_n into
    subsequent record-stage / record-finalize invocations."""
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    run_n = _next_run_n(paths.runs_dir)
    record = _build_record(
        paths,
        run_n=run_n,
        status="running",
        started_at=started_at,
        finished_at=None,
        exit_code=None,
        current_stage=None,
        stages=[],
        skill_version=skill_version,
    )
    canonical, _archive = write_run_record_canonical_and_archive(
        paths, record, run_n,
    )
    return canonical, run_n


def record_resume_or_start(
    paths: dp.DraftPaths,
    *,
    started_at: str,
    skill_version: str,
) -> tuple[Path, int, str]:
    """Resume-aware entry point (v1.3.1 / Cycle-3 follow-up P0-2).

    The shell calls THIS (not record_start) at the --resume-from entry,
    so a halt+resume stays ONE run record instead of fragmenting across
    run-N (halted) + run-N+1 (resumed) and resetting craft status to $0
    mid-build. Decision is by the existing canonical record's STATUS,
    not guesswork:

      status ∈ {halted, running, failed}  → RE-OPEN it. Flip
        status→running; KEEP run_id + started_at + cumulative totals +
        existing stages[]. The interrupted run continues; subsequent
        record-stage calls append, and a stage that previously failed
        upserts failed→completed in place on retry via the
        find-or-append-by-id in record-stage. (running covers a
        crash/re-invoke with no clean halt; halted covers the
        throughline-pick gate; FAILED covers a mid-pipeline stage
        failure — a `--resume-from` after a failure is a CONTINUATION
        of the same build, not a redo, so the stages the failed run
        completed before the failure point MUST be carried, not dropped.
        Bucketing `failed` with `completed` here was the C1-A defect:
        it opened a fresh empty run that lost the already-completed
        substory_design/curate_figures cost, ~$5 on the $40 run.)
      status == completed, or NO record → ALLOCATE a fresh run-N (a
        genuine redo / fresh start — e.g. --resume-from targeting an
        already-finished deck). Per Adam (C1, 2026-06-11): the fix is
        `failed` ONLY; `completed → fresh` stays.

    Returns (canonical_path, run_n, action) where action ∈
    {"reopened", "allocated"} for the caller's logging.
    """
    existing = _load_existing_record(paths.run_record)
    status = existing.get("status") if isinstance(existing, dict) else None

    if status in ("halted", "running", "failed"):
        # Re-open the interrupted record: only the status (and the
        # archive copy) changes; identity + accumulated state persist.
        # `failed` is a CONTINUATION (C1-A), not a redo — carry the
        # stages the failed run already completed.
        run_n = _find_canonical_run_n(existing)
        if run_n is None:
            # Corrupted run_id on an otherwise-resumable record — fall
            # through to a fresh allocation rather than mutate a record
            # we can't address.
            canonical, run_n = record_start(
                paths, started_at=started_at, skill_version=skill_version)
            return canonical, run_n, "allocated"
        reopened = dict(existing)
        reopened["status"] = "running"
        reopened["finished_at"] = None
        reopened["exit_code"] = None
        # started_at, run_id, stages[], totals, models_used, artifacts
        # all carry over from the existing record unchanged.
        canonical, _archive = write_run_record_canonical_and_archive(
            paths, reopened, run_n,
        )
        return canonical, run_n, "reopened"

    # completed / no-record → genuine fresh run. (`failed` is handled
    # above as a continuation — C1-A.)
    canonical, run_n = record_start(
        paths, started_at=started_at, skill_version=skill_version)
    return canonical, run_n, "allocated"


def _find_canonical_run_n(record: dict | None) -> int | None:
    """Extract the integer run-N from a loaded record's `run_id`.
    None on a missing record or non-conformant run_id."""
    if record is None:
        return None
    rid = record.get("run_id")
    if not isinstance(rid, str):
        return None
    m = re.match(r"^run-(\d+)$", rid)
    return int(m.group(1)) if m else None


def record_stage(
    paths: dp.DraftPaths,
    *,
    stage_id: str,
    status: str,
    model: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    elapsed_seconds: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
    cost_usd: float | None = None,
    from_sidecar: Path | None = None,
    sidecar_glob: str | None = None,
    image_provenance: Path | None = None,
    from_revise_metadata: Path | None = None,
    from_phase0_jsonl: Path | None = None,
) -> Path:
    """Append-or-update a stage entry. Reads the canonical record,
    finds-or-creates the entry by stage_id, updates its fields,
    refreshes totals, bumps current_stage to this id (we treat the
    most-recent record-stage as the "current" one for `craft
    status`'s sake; the record-finalize call clears it), atomic-
    writes the canonical + archive.

    The orchestrator is the single source of truth for the stage
    ENUM + ordering (it passes `stage_id`); the per-stage VALUES come
    from the artifacts the stage actually wrote:

      from_sidecar       — a `.metadata.json` the stage's `claude -p`
                           call wrote (tokens / cost / model / elapsed).
                           Used for every LLM stage. None for a non-LLM
                           stage (curate_figures, citation_pool reuse,
                           assemble, merge) — those record a zero-cost
                           entry naming the stage.
      image_provenance   — audit/image_provenance.json; for the
                           image_gen stage ONLY. Its per-image
                           GENERATION cost is summed and ADDED to
                           whatever the prompt-composition sidecar(s)
                           reported, fixing the documented image_gen
                           undercount (prompt cost was counted; the
                           provider's per-image charge was not).

    Explicit keyword args (input_tokens=…, cost_usd=…) OVERRIDE the
    artifact-derived values when provided (None = "take from artifact
    or default to 0"). Tests pass explicit values; the shell passes
    `from_sidecar` / `image_provenance`.

    If no canonical record exists yet (record-start wasn't called
    — e.g. the shell hit a stage before its trap setup), this
    bootstraps one. The bootstrap path is for robustness; the
    well-behaved orchestrator always record-starts first."""
    existing = _load_existing_record(paths.run_record)

    if existing is None:
        # Bootstrap: synthesize a record-start equivalent.
        _canon, run_n = record_start(
            paths,
            started_at=started_at,
            skill_version=_SKILL_VERSION,
        )
        existing = _load_existing_record(paths.run_record)
        assert existing is not None
    else:
        run_n = _find_canonical_run_n(existing)
        if run_n is None:
            # Corrupted run_id — re-allocate. Loud-warn via stderr.
            print(
                "finalize_run: warning — canonical record had no "
                "parseable run_id; re-allocating",
                file=sys.stderr,
            )
            run_n = _next_run_n(paths.runs_dir)

    # If the existing record is terminal or halted, refuse to mutate
    # stages — that's a contract violation (the run is over or
    # paused; the caller should have started a new run first).
    existing_status = existing.get("status")
    if existing_status in ("completed", "failed", "halted"):
        print(
            f"finalize_run: warning — record-stage called on a "
            f"{existing_status!r} record; ignoring (run is "
            f"terminal/halted; start a new run to add stages)",
            file=sys.stderr,
        )
        return paths.run_record

    # Resolve per-stage values: artifact-derived (sidecar +
    # image-provenance) form the base; explicit kwargs override.
    base = {
        "model": None,
        "elapsed_seconds": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cost_usd": 0.0,
    }
    if from_sidecar is not None:
        sc = _read_sidecar_metadata(Path(from_sidecar))
        for k, v in sc.items():
            if v is not None:
                base[k] = v
    if sidecar_glob is not None:
        # Sum MANY sidecars into the base — used for the image_gen
        # stage, whose prompt-composition cost is spread across one
        # `ai_image_prompt-*_request.json.metadata.json` per image.
        # Token counts + cost + elapsed accumulate; model adopts the
        # first non-empty one. Combine with `from_sidecar` is allowed
        # (the single-sidecar base is summed into first).
        import glob as _glob
        for sc_path in sorted(_glob.glob(sidecar_glob)):
            sc = _read_sidecar_metadata(Path(sc_path))
            if not sc:
                continue
            base["input_tokens"] += int(sc.get("input_tokens", 0) or 0)
            base["output_tokens"] += int(sc.get("output_tokens", 0) or 0)
            base["cache_read_tokens"] += int(
                sc.get("cache_read_tokens", 0) or 0
            )
            base["cache_creation_tokens"] += int(
                sc.get("cache_creation_tokens", 0) or 0
            )
            base["cost_usd"] = round(
                float(base["cost_usd"]) + float(sc.get("cost_usd", 0.0) or 0.0),
                6,
            )
            base["elapsed_seconds"] += float(sc.get("elapsed_seconds", 0) or 0)
            if not base["model"] and sc.get("model"):
                base["model"] = sc["model"]
    if image_provenance is not None:
        # Image-generation cost ADDS to the prompt-composition cost
        # already in the sidecar — this is the undercount fix. Same
        # for elapsed (generation wall-clock is real time spent).
        prov = _sum_image_provenance(Path(image_provenance))
        base["cost_usd"] = round(
            float(base["cost_usd"]) + float(prov["cost_usd"]), 6,
        )
        base["elapsed_seconds"] = (
            float(base["elapsed_seconds"]) + float(prov["elapsed_seconds"])
        )
        # If the sidecar had no model (or there was no sidecar), adopt
        # the image-generation model so models_used reflects the
        # provider. When both exist, keep the LLM prompt model as the
        # stage's primary (the generation model is a sub-detail; the
        # provenance file is the authoritative per-image record).
        if not base["model"] and prov["models"]:
            base["model"] = prov["models"][0]
    if from_revise_metadata is not None:
        # revise_loop.py provenance (revise_slides + visual_qa_final's
        # 2nd pass): cost_usd_cumulative ADDS to the base; the format
        # carries no tokens/model so only cost (+ timestamps) fold.
        rev = _read_revise_metadata(Path(from_revise_metadata))
        base["cost_usd"] = round(
            float(base["cost_usd"]) + float(rev["cost_usd"]), 6,
        )
        # Adopt the revise window's timestamps when the caller didn't
        # supply its own (the loop tracks real wall-clock for the pass).
        if started_at is None and rev["started_at"] is not None:
            started_at = rev["started_at"]
        if finished_at is None and rev["finished_at"] is not None:
            finished_at = rev["finished_at"]
    if from_phase0_jsonl is not None:
        # phase0_tooling ORIGINATE-path LLM cost (extract_claims) lives
        # in audit/phase0.jsonl. Sum it in; the format has no
        # tokens/model so only cost folds. $0 on a reuse-only run.
        ph0 = _sum_phase0_jsonl(Path(from_phase0_jsonl))
        base["cost_usd"] = round(
            float(base["cost_usd"]) + float(ph0["cost_usd"]), 6,
        )

    # Explicit kwargs win over artifact-derived values (tests + any
    # caller that already knows the numbers).
    def _pick(explicit, key):
        return base[key] if explicit is None else explicit

    resolved_model = model if model is not None else base["model"]
    resolved_elapsed = float(_pick(elapsed_seconds, "elapsed_seconds"))

    # Timestamp derivation — lets the shell call record-stage with just
    # `--stage` + `--from-sidecar` (no T0 threaded through 19 stages).
    #   finished_at: explicit, else now (a completed/skipped/failed
    #                stage finished when we record it; running → null).
    #   started_at:  explicit, else finished_at − elapsed (the sidecar
    #                carries elapsed; back-date so wall-clock is right).
    if finished_at is None and status != "running":
        finished_at = _utc_iso_now()
    if started_at is None:
        if finished_at is not None and resolved_elapsed > 0:
            started_at = _iso_minus_seconds(finished_at, resolved_elapsed)
        else:
            started_at = finished_at or _utc_iso_now()

    stages = list(existing.get("stages", []))
    new_entry = {
        "id": stage_id,
        "status": status,
        "model": resolved_model,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": resolved_elapsed,
        "input_tokens": int(_pick(input_tokens, "input_tokens")),
        "output_tokens": int(_pick(output_tokens, "output_tokens")),
        "cache_read_tokens": int(
            _pick(cache_read_tokens, "cache_read_tokens")
        ),
        "cache_creation_tokens": int(
            _pick(cache_creation_tokens, "cache_creation_tokens")
        ),
        "cost_usd": round(float(_pick(cost_usd, "cost_usd")), 6),
        "subrecord": None,
    }

    # Find-or-append by id (idempotent on retry; the stream_progress
    # path may double-emit on retry).
    replaced = False
    for i, s in enumerate(stages):
        if s.get("id") == stage_id:
            stages[i] = new_entry
            replaced = True
            break
    if not replaced:
        stages.append(new_entry)

    record = _build_record(
        paths,
        run_n=run_n,
        status="running",
        started_at=existing.get("started_at") or started_at,
        finished_at=None,
        exit_code=None,
        current_stage=stage_id,
        stages=stages,
        skill_version=existing.get("skill_version", _SKILL_VERSION),
    )
    canonical, _archive = write_run_record_canonical_and_archive(
        paths, record, run_n,
    )
    return canonical


def record_halt(
    paths: dp.DraftPaths,
    *,
    gate_id: str,
    started_at: str,
    skill_version: str,
) -> Path:
    """Halt-gate writer. Adds a `status: running` stage entry for the
    gate (so the referential check `current_stage ∈ {stages[].id}`
    passes) and flips the record's top-level status to `halted`.

    This MUST run BEFORE the process exits at a halt-gate (e.g.
    presmaker's throughline-pick gate writes .handoff.json then
    exits 0). The matching record-finalize on trap-EXIT will see
    status=halted and refuse to overwrite (the finalize guard) —
    the run stays halted until a resume flips it back to running.

    Bootstraps a record-start if no canonical record exists yet
    (the shell wiring should record-start before reaching any gate,
    but defensive)."""
    existing = _load_existing_record(paths.run_record)
    if existing is None:
        _canon, run_n = record_start(
            paths,
            started_at=started_at,
            skill_version=skill_version,
        )
        existing = _load_existing_record(paths.run_record)
        assert existing is not None
    else:
        run_n = _find_canonical_run_n(existing) or _next_run_n(
            paths.runs_dir,
        )

    # Add the gate as a stage entry (running) so it's referentially
    # resolvable from current_stage.
    stages = list(existing.get("stages", []))
    gate_entry = {
        "id": gate_id,
        "status": "running",
        "model": None,
        "started_at": started_at,
        "finished_at": None,
        "elapsed_seconds": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cost_usd": 0.0,
        "subrecord": None,
    }
    # Idempotent: if the gate is already in stages[], leave its
    # entry alone (a re-entry into the same halt-gate is the
    # operator inspecting and re-halting — no semantic change).
    if not any(s.get("id") == gate_id for s in stages):
        stages.append(gate_entry)

    record = _build_record(
        paths,
        run_n=run_n,
        status="halted",
        started_at=existing.get("started_at") or started_at,
        finished_at=None,
        exit_code=None,
        current_stage=gate_id,
        stages=stages,
        skill_version=existing.get("skill_version", skill_version),
    )
    canonical, _archive = write_run_record_canonical_and_archive(
        paths, record, run_n,
    )
    return canonical


def record_finalize(
    paths: dp.DraftPaths,
    *,
    exit_code: int,
    started_at: str | None,
    skill_version: str,
) -> Path:
    """Terminal write point. Sets status to `completed` (exit_code==0)
    or `failed` (exit_code!=0), populates finished_at, clears
    current_stage.

    THE ORCHESTRATOR IS AUTHORITATIVE for stages[] (Adam,
    2026-06-07): the shell calls record-stage at every boundary, so
    the in-record stages[] is the truth. The metadata-sidecar walk is
    NO LONGER a silent overwrite source — it's a LOUD RECONCILIATION:

      * a sidecar exists for a stage MISSING from the orchestrator's
        stages[]  → WARN (the shell missed a boundary wiring), and
        ADD a projected entry so the data isn't lost.
      * a sidecar's cost MATERIALLY DISAGREES with the recorded
        stage's cost (beyond float tolerance) → WARN; KEEP the
        orchestrator's recorded value (it already folded the sidecar
        — for image_gen it also folded the generation cost the
        sidecar can't see, so the recorded value is the RICHER one;
        overwriting from the bare sidecar would REINTRODUCE the
        undercount).

    Net: never silently overwrite an orchestrator-authored entry.

    THE FINALIZE GUARD (correctness lynchpin per the Cycle-3 brief):
    if the existing canonical record has status==`halted`, DO NOT
    overwrite — the halt-gate already wrote the right state, and
    the trap-EXIT finalize would otherwise demote it to
    completed/failed. The halt is preserved across the trap; only
    a resume's record-start clears it.
    """
    existing = _load_existing_record(paths.run_record)

    if existing is not None and existing.get("status") == "halted":
        print(
            "finalize_run: record-finalize — existing record is "
            "halted; preserving halt state (guard active; "
            "the halt-gate already wrote the right state, and "
            "demoting it to completed/failed would lose the gate).",
            file=sys.stderr,
        )
        return paths.run_record

    finished_at = _utc_iso_now()
    status = "completed" if exit_code == 0 else "failed"

    # The orchestrator-authored stages[] is authoritative.
    existing_stages = list(
        existing.get("stages", []) if existing else []
    )
    recorded_ids = {
        s.get("id") for s in existing_stages if isinstance(s, dict)
    }

    # Reconcile against the metadata sidecars — LOUDLY, not silently.
    sidecar_metadata = collect_stage_metadata(paths.working)
    sidecar_stages = _project_stages_from_metadata(sidecar_metadata)
    sidecar_by_id = {s["id"]: s for s in sidecar_stages}

    by_id = {
        s["id"]: s for s in existing_stages if isinstance(s, dict)
    }
    for sid, scs in sidecar_by_id.items():
        # Fold/alias skip: some sidecars are already accounted for by a
        # recorded stage — sub-units (ai_image_prompt-* → image_gen via
        # --sidecar-glob) or aliases (substory_design sidecar absorbed
        # by a recorded deck_outline on the v0.4 path). When that
        # absorbing stage is recorded, skip the sidecar (re-adding would
        # double-count + false-warn).
        absorbed_by = _sidecar_parent_stage(sid)
        if absorbed_by is not None and absorbed_by in recorded_ids:
            continue
        if sid not in recorded_ids:
            # The shell never recorded this stage — wiring gap. Don't
            # drop the data, but make the gap LOUD so it gets fixed.
            print(
                f"finalize_run: RECONCILE WARNING — sidecar for stage "
                f"{sid!r} has no orchestrator-recorded entry; the shell "
                f"missed a record-stage boundary. Adding a projected "
                f"entry from the sidecar so its cost isn't lost — but "
                f"the orchestrator wiring should record it.",
                file=sys.stderr,
            )
            by_id[sid] = scs
            continue
        # Present in both: orchestrator wins. Warn on material cost
        # disagreement (the orchestrator value may legitimately be
        # LARGER — image_gen folds generation cost the sidecar can't
        # see; that's expected, not a bug — but a SMALLER recorded
        # value than the bare sidecar means a wiring bug worth a flag).
        rec_cost = float(by_id[sid].get("cost_usd", 0.0) or 0.0)
        sc_cost = float(scs.get("cost_usd", 0.0) or 0.0)
        if rec_cost + _COST_RECONCILE_TOLERANCE < sc_cost:
            print(
                f"finalize_run: RECONCILE WARNING — stage {sid!r} "
                f"recorded cost ${rec_cost:.6f} is LESS than its "
                f"sidecar cost ${sc_cost:.6f}; the orchestrator "
                f"record-stage may have under-reported. Keeping the "
                f"recorded value (orchestrator is authoritative); "
                f"inspect the wiring if this recurs.",
                file=sys.stderr,
            )
        # Keep the orchestrator entry (by_id[sid] unchanged).

    merged_stages = sorted(
        by_id.values(),
        key=lambda s: s.get("started_at") or "",
    )

    run_n = (
        _find_canonical_run_n(existing)
        if existing is not None
        else _next_run_n(paths.runs_dir)
    )
    if run_n is None:
        run_n = _next_run_n(paths.runs_dir)

    if started_at is None:
        if existing is not None:
            started_at = existing.get("started_at") or finished_at
        else:
            started_at = finished_at

    record = _build_record(
        paths,
        run_n=run_n,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=int(exit_code),
        current_stage=None,
        stages=merged_stages,
        skill_version=(
            existing.get("skill_version", skill_version)
            if existing is not None
            else skill_version
        ),
    )

    # C1-A2 completeness guard: before declaring the run COMPLETED, the
    # canonical's completed-stage set MUST be a superset of every archived
    # run's completed set. A resume that dropped a completed stage (the
    # C1-A failure mode) reconciles totals perfectly yet under-reports —
    # this is the only check that catches it. Fail LOUD: do NOT finalize as
    # completed; raise so the CLI exits non-zero with the diagnostic. (We
    # only guard the completed path — a `failed` finalize is already
    # signalling a problem and may legitimately lack stages.)
    if status == "completed":
        archived = _load_archived_runs(paths)
        drop_errors = check_no_dropped_stages(record, archived)
        if drop_errors:
            for e in drop_errors:
                print(f"finalize_run: COMPLETENESS FAILURE — {e}",
                      file=sys.stderr)
            raise CompletenessError(drop_errors)

    canonical, _archive = write_run_record_canonical_and_archive(
        paths, record, run_n,
    )
    return canonical


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# v1.3.1 / Cycle-3 follow-up P0-1: _cmd_write (the legacy `write`
# subcommand) is RETIRED along with write_run_summary /
# write_stage_metadata / aggregate_run_totals — see the comment at the
# top of the run-record emitter section.


def _cmd_record_start(args) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    if not paths.is_initialized():
        print(
            f"finalize_run: draft_dir not initialized: {paths.draft_dir}",
            file=sys.stderr,
        )
        return 1
    if getattr(args, "resume", False):
        # v1.3.1 P0-2: resume-aware — re-open a halted/running record
        # (one run per deck across the halt) instead of allocating a
        # fresh run-N.
        canonical, run_n, action = record_resume_or_start(
            paths,
            started_at=args.started_at,
            skill_version=args.skill_version or _SKILL_VERSION,
        )
        print(
            f"finalize_run: record-start --resume {action} run-{run_n} "
            f"→ {canonical}",
            file=sys.stderr,
        )
        return 0
    canonical, run_n = record_start(
        paths,
        started_at=args.started_at,
        skill_version=args.skill_version or _SKILL_VERSION,
    )
    print(
        f"finalize_run: record-start run-{run_n} → {canonical}",
        file=sys.stderr,
    )
    return 0


def _cmd_record_stage(args) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    if not paths.is_initialized():
        print(
            f"finalize_run: draft_dir not initialized: {paths.draft_dir}",
            file=sys.stderr,
        )
        return 1
    canonical = record_stage(
        paths,
        stage_id=args.stage,
        status=args.status,
        model=args.model,
        started_at=args.started_at,
        finished_at=args.finished_at,
        elapsed_seconds=args.elapsed_seconds,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        cache_read_tokens=args.cache_read_tokens,
        cache_creation_tokens=args.cache_creation_tokens,
        cost_usd=args.cost_usd,
        from_sidecar=(
            Path(args.from_sidecar) if args.from_sidecar else None
        ),
        sidecar_glob=args.sidecar_glob or None,
        image_provenance=(
            Path(args.image_provenance) if args.image_provenance else None
        ),
        from_revise_metadata=(
            Path(args.from_revise_metadata)
            if args.from_revise_metadata else None
        ),
        from_phase0_jsonl=(
            Path(args.from_phase0_jsonl) if args.from_phase0_jsonl else None
        ),
    )
    print(
        f"finalize_run: record-stage {args.stage}={args.status} → "
        f"{canonical}",
        file=sys.stderr,
    )
    return 0


def _cmd_record_halt(args) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    if not paths.is_initialized():
        print(
            f"finalize_run: draft_dir not initialized: {paths.draft_dir}",
            file=sys.stderr,
        )
        return 1
    canonical = record_halt(
        paths,
        gate_id=args.gate,
        started_at=args.started_at,
        skill_version=args.skill_version or _SKILL_VERSION,
    )
    print(
        f"finalize_run: record-halt gate={args.gate} → {canonical}",
        file=sys.stderr,
    )
    return 0


def _cmd_record_finalize(args) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    if not paths.is_initialized():
        print(
            f"finalize_run: draft_dir not initialized: {paths.draft_dir}",
            file=sys.stderr,
        )
        return 1
    try:
        canonical = record_finalize(
            paths,
            exit_code=args.exit_code,
            started_at=args.started_at,
            skill_version=args.skill_version or _SKILL_VERSION,
        )
    except CompletenessError as exc:
        # C1-A2: the run would have been finalized as completed while
        # dropping a stage a prior run completed. The canonical was NOT
        # written as completed (it keeps its prior running/reopened
        # status). Fail loud + non-zero so the wrapping orchestrator and
        # any CI surface the regression.
        print(
            f"finalize_run: record-finalize ABORTED — completeness guard "
            f"failed ({len(exc.errors)} dropped-stage error(s)); the run "
            f"was NOT finalized as completed. Fix the resume disposition "
            f"or the dropped stage(s) and re-finalize.",
            file=sys.stderr,
        )
        return 3
    print(
        f"finalize_run: record-finalize exit_code={args.exit_code} → "
        f"{canonical}",
        file=sys.stderr,
    )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="finalize_run",
        description=(
            "Cycle-3 DP1 run-record.v1 emitter: record-start / "
            "record-stage / record-halt / record-finalize maintain "
            "audit/run_record.json + the audit/runs/run-N/ archive. "
            "(The legacy `write` subcommand — run-summary.v1 / "
            "stage-metadata.v1 — was retired in v1.3.1, P0-1.)"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # Cycle 3 / DP1 run-record.v1 incremental write CLI. See module
    # docstring for the protocol.

    p_start = sub.add_parser(
        "record-start",
        help="Cycle-3 DP1: write the initial run_record.json "
             "(status=running, allocates next run-N).",
    )
    p_start.add_argument("--draft-dir", required=True)
    p_start.add_argument(
        "--started-at", required=True,
        help="Orchestrator start time, ISO-8601 UTC.",
    )
    p_start.add_argument(
        "--skill-version", default=None,
        help="Override skill version (default: __version__).",
    )
    p_start.add_argument(
        "--resume", action="store_true",
        help="v1.3.1 P0-2: resume-aware. RE-OPEN an existing "
             "halted/running record (one run per deck across a halt) "
             "instead of allocating a fresh run-N. completed/failed or "
             "no record → fresh run-N. The shell passes this on the "
             "--resume-from entry.",
    )
    p_start.set_defaults(func=_cmd_record_start)

    p_stage = sub.add_parser(
        "record-stage",
        help="Cycle-3 DP1: append/patch a stage entry in run_record.json.",
    )
    p_stage.add_argument("--draft-dir", required=True)
    p_stage.add_argument("--stage", required=True,
                         help="Stage id (the orchestrator's canonical "
                              "name; the brief's `--stage` plumb-through).")
    p_stage.add_argument(
        "--status", required=True,
        choices=("completed", "running", "failed", "skipped"),
        help="Stage status (matches craft.run_record.STAGE_STATUSES).",
    )
    p_stage.add_argument("--model", default=None)
    p_stage.add_argument(
        "--started-at", default=None,
        help="Stage start time, ISO-8601 UTC. Optional: when omitted "
             "the emitter back-dates it from finished_at − sidecar "
             "elapsed (so the shell can wire stages without threading "
             "a per-stage T0).",
    )
    p_stage.add_argument(
        "--finished-at", default=None,
        help="Stage finish time, ISO-8601 UTC. Optional: defaults to "
             "now for terminal stage statuses; null when "
             "status=running.",
    )
    # Per-stage VALUES. Default None = "take from --from-sidecar /
    # --image-provenance, else 0". An explicit value OVERRIDES the
    # artifact-derived one (tests + callers that already know).
    p_stage.add_argument("--elapsed-seconds", type=float, default=None)
    p_stage.add_argument("--input-tokens", type=int, default=None)
    p_stage.add_argument("--output-tokens", type=int, default=None)
    p_stage.add_argument("--cache-read-tokens", type=int, default=None)
    p_stage.add_argument("--cache-creation-tokens", type=int, default=None)
    p_stage.add_argument("--cost-usd", type=float, default=None)
    p_stage.add_argument(
        "--from-sidecar", default=None,
        help="Path to the stage's .metadata.json sidecar (written by "
             "stream_progress.py). Supplies tokens / cost / model / "
             "elapsed for LLM stages. Omit for non-LLM stages.",
    )
    p_stage.add_argument(
        "--sidecar-glob", default=None,
        help="Glob matching MANY .metadata.json sidecars to SUM into "
             "one stage entry (image_gen: one prompt sidecar per "
             "image). Token counts / cost / elapsed accumulate.",
    )
    p_stage.add_argument(
        "--image-provenance", default=None,
        help="Path to audit/image_provenance.json (image_gen stage "
             "ONLY). Sums per-image GENERATION cost and ADDS it to the "
             "prompt-composition sidecar cost — the image_gen "
             "undercount fix.",
    )
    p_stage.add_argument(
        "--from-revise-metadata", default=None,
        help="Path to audit/revise_loop_metadata.json (revise_slides + "
             "visual_qa_final 2nd pass). Folds cost_usd_cumulative (+ "
             "the pass's ISO timestamps). No tokens/model in that "
             "format, so only cost folds.",
    )
    p_stage.add_argument(
        "--from-phase0-jsonl", default=None,
        help="Path to audit/phase0.jsonl (phase0_tooling). Sums "
             "cost_usd across records — the ORIGINATE path's "
             "extract_claims LLM cost. $0 on a reuse-only run. No "
             "tokens/model in that format, so only cost folds.",
    )
    p_stage.set_defaults(func=_cmd_record_stage)

    p_halt = sub.add_parser(
        "record-halt",
        help="Cycle-3 DP1: flip run_record.json to status=halted at a "
             "halt-gate. Names the gate as a running stage so the "
             "referential check passes. record-finalize on trap-EXIT "
             "preserves this state (the finalize guard).",
    )
    p_halt.add_argument("--draft-dir", required=True)
    p_halt.add_argument(
        "--gate", required=True,
        help="Halt-gate id (e.g. throughline_pick); will be the "
             "current_stage value in the halted record.",
    )
    p_halt.add_argument(
        "--started-at", required=True,
        help="Run start time, ISO-8601 UTC (preserved across halt).",
    )
    p_halt.add_argument(
        "--skill-version", default=None,
        help="Override skill version (default: __version__).",
    )
    p_halt.set_defaults(func=_cmd_record_halt)

    p_fin = sub.add_parser(
        "record-finalize",
        help="Cycle-3 DP1: terminal write. status=completed (exit=0) "
             "or failed (exit!=0). The finalize guard refuses to "
             "overwrite a status=halted record.",
    )
    p_fin.add_argument("--draft-dir", required=True)
    p_fin.add_argument("--exit-code", type=int, required=True)
    p_fin.add_argument(
        "--started-at", default=None,
        help="Orchestrator start time, ISO-8601 UTC. If omitted, "
             "preserved from the existing record.",
    )
    p_fin.add_argument(
        "--skill-version", default=None,
        help="Override skill version (default: __version__).",
    )
    p_fin.set_defaults(func=_cmd_record_finalize)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
