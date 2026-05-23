#!/usr/bin/env python3
"""phase0_reuse.py — Phase-0 reuse-vs-originate decision helper.

Authored for beril-presentation-maker v0.4 M1 Tier C (2026-05-14) per
V0_4_ARCHITECTURE.md §4.0 (provenance table) + §4.6 (idempotency
contract), M1_PUNCH_LIST.md Tier C, and D-009 / D-040-rev1.

For each of the two NEW v0.4 Phase-0 artifacts — methods_provenance.md
and claim_inventory.tsv — this helper decides, per artifact, whether to:

  - NO-OP:     the talk-draft already has the artifact and the recorded
               input hash matches the current inputs.
  - REUSE:     copy from a sibling papers/draft_*/ (paper-writer's output).
  - ORIGINATE: invoke the vendored tool (extract_methods.py /
               extract_claims.py) to build the artifact fresh.

The three OTHER Phase-0 artifacts named in V0_4_ARCHITECTURE.md §4.6
(citation_pool.json, cross_tenant_signal.md, curated_figures.md) are
pre-existing with their own writers and their own reuse logic via
state.json.paper_writer_reuse (LAYOUT.md §6). Unifying all five under a
single helper is deferred to v0.5 (M1_PUNCH_LIST.md Tier F).

Layout
------
Artifacts land in ``<talk-draft>/working/00_phase0/`` — the
4-zone-preserving location. V0_4_ARCHITECTURE.md §4.6 originally drafted
``talks/draft_N/00_phase0/`` at draft root; that broke draft_paths.py's
exactly-four-zones rule, so the signed-off layout (Adam, 2026-05-12) is
``working/00_phase0/``. See DraftPaths.phase0_dir.

Reuse is PRESENCE-based, not hash-equality-based against paper-writer
-----------------------------------------------------------------------
Paper-writer does not stamp source-artifact hashes anywhere persistent
(verified against papers/draft_9/state.json — source_artifacts == []).
We therefore cannot cross-check a reused artifact's freshness against
paper-writer's run. We trust paper-writer's output if its draft exists;
``--force-originate`` bypasses reuse. The validator chain inside
extract_claims.py catches LLM-fabrication regardless of source, so the
worst case from a stale paper-writer artifact is surfaced downstream at
M2 review, not silently poisoned.

WITHIN-talk-draft idempotency IS hash-based
-------------------------------------------
Every decision stamps the CURRENT source-artifact input hashes into
``audit/phase0.jsonl``. A re-invocation in the same talk-draft compares
current hashes against the most-recent *successful* stamp (reuse /
originate / no-op — an ``error`` stamp is never honored, since a failed
originate can leave a non-empty partial artifact on disk); matched +
artifact present -> NO-OP. The hash is over the PROJECT-LEVEL inputs
that determine the artifact's correctness:

  - methods_provenance: notebooks/ + src/ + analysis/ + scripts/ +
    RESEARCH_PLAN.md + requirements.txt + pyproject.toml +
    environment.yml  (every input extract_methods.py reads —
    collect_package_versions() folds the three manifest files into
    methods_provenance.md, so a dependency-version bump must move the
    hash).
  - claim_inventory:   REPORT.md + methods_provenance.md  (the inputs
    extract_claims.v1.md reads).

Known limitation (out of scope for v0.4, consistent with §4.0): if
paper-writer re-runs and produces a *better* artifact from the *same*
project inputs (e.g. after their Tier I validator fix), our no-op
fast-path will keep the old copy. Delete the talk-draft artifact to
force a refresh, or re-run with changed inputs.

CLI
---
    phase0_reuse.py \\
        --project-dir <projects/<id>/> \\
        --talk-draft-dir <talks/draft_N/> \\
        --artifact {methods_provenance|claim_inventory|all} \\
        [--force-originate] \\
        [--claude-bin claude] \\
        [--model claude-sonnet-4-6] \\
        [--paper-draft-glob "papers/draft_*"]

Exit codes
----------
  0 — decision(s) executed cleanly (reuse, originate, or no-op).
  1 — user error (missing/bad --project-dir, --talk-draft-dir, or a
      required upstream artifact such as REPORT.md or methods_provenance.md
      for the claim_inventory originate path).
  2 — a vendored sub-tool invocation failed on the originate path
      (surfaces extract_methods.py / extract_claims.py's exit code).
  3 — internal consistency error (reuse predicate true but the copy
      did not produce a non-empty file). Should not happen — halt loud
      per feedback_no_benchmark_gaming.md.

cost_usd note
-------------
extract_claims.py (F5, 2026-05-21) passes ``--output-format json`` to
``claude -p`` and parses ``total_cost_usd`` from the result envelope
into its own ``tool=extract_claims`` ``phase=llm_extract`` record in the
shared ``phase0.jsonl``. The claim_inventory ORIGINATE decision record
reads that value back (``read_last_extract_claims_cost``) and reports
the real spend. It is ``null`` only when the LLM was fast-path-skipped
(output already present) or the envelope carried no parseable cost.
reuse / no-op / and the methods_provenance originate path are
deterministic -> ``0.0``.

Test coverage: tests/unit/test_phase0_reuse.py (vendored-tool
invocations mocked; no live ``claude -p``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Sibling vendored tools. The orchestrator runs this file as a script
# (sys.path[0] = the tools dir); the test suite and the `python3 -m`
# form run it as a package module. Try the package import first — that
# keeps the test / `-m` path byte-identical — and on failure (the
# orchestrator's script invocation under the pipx venv, where
# `beril_presentation_maker` is not an importable package) fall back to
# a bare sibling import with the tools dir resolved from __file__
# (mirrors merge_compose_fragments.py's sys.path idiom).
try:
    from beril_presentation_maker.skill.tools import extract_claims, extract_methods
    from beril_presentation_maker.skill.tools.draft_paths import DraftPaths
except ImportError:
    _TOOLS_DIR = Path(__file__).resolve().parent
    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))
    import extract_claims  # noqa: E402  (sibling tool)
    import extract_methods  # noqa: E402  (sibling tool)
    from draft_paths import DraftPaths  # noqa: E402  (sibling tool)

VERSION = "0.4.0-m1-tierF5"

# Default model for the claim_inventory originate path. Threaded through
# to extract_claims.py, which MUST pin the model (see extract_claims.py
# B6 note — unpinned `claude -p` caused paper-writer's draft_9
# regression). Mirrors presentation_maker.sh:79's MODEL pin and
# extract_claims._DEFAULT_MODEL — intentionally duplicated (not imported)
# so phase0_reuse stays decoupled from extract_claims' private surface;
# the value is threaded through explicitly, never relied on as a default.
_DEFAULT_MODEL = "claude-sonnet-4-6"

# Artifact name -> filename. Paper-writer writes these flat at
# papers/draft_N/<filename> (NOT in a 00_phase0/ subdir — verified
# against papers/draft_9/).
_ARTIFACT_FILENAMES = {
    "methods_provenance": "methods_provenance.md",
    "claim_inventory": "claim_inventory.tsv",
}
_ARTIFACTS = tuple(_ARTIFACT_FILENAMES)


# ---------------------------------------------------------------------------
# UTC helper
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """SHA256 of a file's bytes. Streamed; safe for large notebooks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_input_hash(
    artifact: str, project_dir: Path, talk_paths: DraftPaths
) -> str:
    """Compute the SHA256 input-hash for ``artifact``.

    The hash is over the project-level inputs that determine the
    artifact's correctness — see module docstring. Independent per
    artifact: the two artifacts have different input sets.
    """
    if artifact == "methods_provenance":
        files = list(extract_methods.find_notebooks(project_dir))
        files += list(extract_methods.find_scripts(project_dir))
        # Every other input extract_methods reads: RESEARCH_PLAN.md (design
        # intent) + the three package-manifest files that
        # collect_package_versions() folds into methods_provenance.md.
        # Omitting the manifests would let a dependency-version bump change
        # the artifact without moving the hash -> spurious no-op.
        for extra in (
            "RESEARCH_PLAN.md",
            "requirements.txt",
            "pyproject.toml",
            "environment.yml",
        ):
            p = project_dir / extra
            if p.is_file():
                files.append(p)
        # Sorted (relative-path, content-sha) tuples -> order-independent,
        # path-stable. relative_to(project_dir) is safe: find_notebooks /
        # find_scripts glob under project_dir, and the extras are direct
        # children of it (project_dir is resolved by decide_and_act).
        entries = sorted(
            (str(p.relative_to(project_dir)), _sha256_file(p)) for p in files
        )
        return _sha256_text(repr(entries))
    if artifact == "claim_inventory":
        report = project_dir / "REPORT.md"
        methods = talk_paths.methods_provenance_phase0
        report_sha = _sha256_file(report) if report.is_file() else ""
        methods_sha = _sha256_file(methods) if methods.is_file() else ""
        return _sha256_text(repr((report_sha, methods_sha)))
    raise ValueError(f"unknown artifact: {artifact!r}")


# ---------------------------------------------------------------------------
# Paper-writer artifact locator
# ---------------------------------------------------------------------------

def find_paper_writer_artifact(
    project_dir: Path, artifact: str, glob_pattern: str = "papers/draft_*"
) -> Optional[Path]:
    """Return the most-recent paper-writer draft's copy of ``artifact``.

    Globs ``project_dir / glob_pattern`` for draft directories, parses
    the integer draft number from each name, and returns the path to the
    highest-numbered draft's artifact if it exists and is non-empty.
    Returns None when no paper-writer draft carries the artifact.
    """
    filename = _ARTIFACT_FILENAMES[artifact]
    candidates: list[tuple[int, Path]] = []
    for draft_dir in project_dir.glob(glob_pattern):
        if not draft_dir.is_dir():
            continue
        m = re.search(r"draft_(\d+)", draft_dir.name)
        if not m:
            continue
        artifact_path = draft_dir / filename
        if artifact_path.is_file() and artifact_path.stat().st_size > 0:
            candidates.append((int(m.group(1)), artifact_path))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Audit JSONL — shares <audit_dir>/phase0.jsonl with extract_claims.py
# ---------------------------------------------------------------------------

def read_last_phase0_reuse_stamp(
    audit_dir: Path, artifact: str
) -> Optional[dict]:
    """Return the most-recent ``tool == "phase0_reuse"`` record for
    ``artifact`` in ``<audit_dir>/phase0.jsonl``, or None.

    Tolerates other tools' records (extract_claims.py writes
    ``tool == "extract_claims"`` lines to the same file) and malformed
    lines — they are skipped, not fatal.
    """
    audit_path = audit_dir / "phase0.jsonl"
    if not audit_path.is_file():
        return None
    last: Optional[dict] = None
    for lineno, line in enumerate(
        audit_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # A foreign tool's unparseable record is benign; a malformed
            # phase0_reuse record means a lost stamp (we'd re-do work, not
            # wrongly skip it — the safe direction). Warn either way rather
            # than swallow silently.
            sys.stderr.write(
                f"phase0_reuse: skipping unparseable line {lineno} in "
                f"{audit_path}\n"
            )
            continue
        if rec.get("tool") == "phase0_reuse" and rec.get("artifact") == artifact:
            last = rec
    return last


def read_last_extract_claims_cost(audit_dir: Path) -> Optional[float]:
    """Return ``total_cost_usd`` from the most-recent ``extract_claims``
    ``llm_extract`` record in ``<audit_dir>/phase0.jsonl``, or None.

    extract_claims.py (F5) appends its own ``tool=extract_claims`` records
    to the shared ``phase0.jsonl``; the ``phase=llm_extract`` record
    carries ``cost_usd`` (the ``claude -p`` envelope's ``total_cost_usd``).
    phase0_reuse reads it back so the claim_inventory ORIGINATE decision
    record reflects real spend instead of a null placeholder. Returns None
    when no such record exists (e.g. the LLM was fast-path-skipped) or its
    cost field is missing / non-numeric.
    """
    audit_path = audit_dir / "phase0.jsonl"
    if not audit_path.is_file():
        return None
    cost: Optional[float] = None
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            rec.get("tool") == "extract_claims"
            and rec.get("phase") == "llm_extract"
        ):
            raw = rec.get("cost_usd")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                cost = float(raw)
            else:
                cost = None
    return cost


def append_audit_record(audit_dir: Path, record: dict) -> None:
    """Append one decision record to ``<audit_dir>/phase0.jsonl``.

    Append-only, one JSON object per line. Coexists with
    extract_claims.py's records in the same file.
    """
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "phase0.jsonl"
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Per-artifact decision
# ---------------------------------------------------------------------------

def _dest_path(artifact: str, talk_paths: DraftPaths) -> Path:
    if artifact == "methods_provenance":
        return talk_paths.methods_provenance_phase0
    if artifact == "claim_inventory":
        return talk_paths.claim_inventory_phase0
    raise ValueError(f"unknown artifact: {artifact!r}")


def decide_and_act(
    artifact: str,
    project_dir: Path,
    talk_draft_dir: Path,
    *,
    force_originate: bool = False,
    claude_bin: str = "claude",
    model: str = _DEFAULT_MODEL,
    paper_draft_glob: str = "papers/draft_*",
) -> tuple[dict, int]:
    """Decide and execute reuse / originate / no-op for one artifact.

    Returns ``(audit_record, exit_code)``. The record is ALWAYS returned
    (including on error — fail loud with maximal diagnostics) and the
    caller is responsible for appending it to the audit JSONL.
    """
    t0 = datetime.now(timezone.utc)
    start_iso = _utc_now_iso()

    # decide_and_act is public — tests and the M2 orchestrator call it
    # directly, not only via main() (which resolves). Resolve here so
    # compute_input_hash's relative_to() and the glob paths are stable.
    project_dir = project_dir.resolve()

    talk_paths = DraftPaths.from_draft_dir(talk_draft_dir)
    talk_paths.init_layout()  # idempotent; guarantees working/00_phase0 + audit/
    audit_dir = talk_paths.audit
    dest = _dest_path(artifact, talk_paths)

    def _record(
        decision: str,
        *,
        source_path: Optional[Path] = None,
        inputs_hashed: Optional[str] = None,
        cost_usd: Optional[float] = 0.0,
        rationale: str = "",
        error_detail: Optional[str] = None,
    ) -> dict:
        rec = {
            "timestamp": start_iso,
            "tool": "phase0_reuse",
            "version": VERSION,
            "artifact": artifact,
            "decision": decision,
            "source_path": str(source_path) if source_path else None,
            "destination_path": str(dest),
            "inputs_hashed": inputs_hashed,
            "cost_usd": cost_usd,
            "duration_sec": (datetime.now(timezone.utc) - t0).total_seconds(),
            "rationale": rationale,
        }
        if error_detail is not None:
            rec["error_detail"] = error_detail
        return rec

    # --- precondition checks for claim_inventory ---
    if artifact == "claim_inventory":
        report = project_dir / "REPORT.md"
        if not report.is_file():
            return _record(
                "error",
                rationale="missing_report_md",
                error_detail=f"REPORT.md not found at {report}",
            ), 1
        methods = talk_paths.methods_provenance_phase0
        if not methods.is_file():
            return _record(
                "error",
                rationale="missing_methods_provenance",
                error_detail=(
                    f"methods_provenance.md not found at {methods}; run "
                    f"--artifact methods_provenance (or --artifact all) first."
                ),
            ), 1

    # --- compute current input hash ---
    inputs_hashed = compute_input_hash(artifact, project_dir, talk_paths)

    # --- fast-path: NO-OP if dest present + hash matches the last
    #     *successful* stamp. The decision-whitelist guard is load-bearing:
    #     an `error` stamp also carries inputs_hashed, and a failed originate
    #     can leave a non-empty partial artifact on disk — honoring that
    #     stamp would spuriously no-op a bad artifact (a silent failure,
    #     forbidden by feedback_no_benchmark_gaming.md). ---
    if dest.is_file() and dest.stat().st_size > 0:
        prior = read_last_phase0_reuse_stamp(audit_dir, artifact)
        if (
            prior is not None
            and prior.get("decision") in ("reuse", "originate", "no-op")
            and prior.get("inputs_hashed") == inputs_hashed
        ):
            return _record(
                "no-op", inputs_hashed=inputs_hashed, rationale="hashes_match"
            ), 0

    # --- stale dest: clear it so the vendored tool's own idempotent
    #     fast-path (extract_claims.py skips the LLM when output exists)
    #     does not skip regeneration after an input change ---
    if dest.is_file():
        dest.unlink()

    # --- reuse path ---
    if not force_originate:
        src = find_paper_writer_artifact(project_dir, artifact, paper_draft_glob)
        if src is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if not (dest.is_file() and dest.stat().st_size > 0):
                return _record(
                    "error",
                    source_path=src,
                    inputs_hashed=inputs_hashed,
                    rationale="reuse_copy_failed",
                    error_detail=(
                        f"copy from {src} to {dest} did not produce a "
                        f"non-empty file"
                    ),
                ), 3
            return _record(
                "reuse",
                source_path=src,
                inputs_hashed=inputs_hashed,
                rationale="paper_artifact_present",
            ), 0

    # --- originate path ---
    rationale = "force_originate" if force_originate else "paper_artifact_absent"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if artifact == "methods_provenance":
        rc = extract_methods.main(
            [str(project_dir), "--output-dir", str(talk_paths.phase0_dir)]
        )
        if rc != 0 or not (dest.is_file() and dest.stat().st_size > 0):
            output_present = dest.is_file()
            # Don't leave a known-bad artifact at the canonical path.
            dest.unlink(missing_ok=True)
            return _record(
                "error",
                inputs_hashed=inputs_hashed,
                rationale=rationale,
                error_detail=(
                    f"extract_methods.main returned {rc}; "
                    f"output_present={output_present} (removed)"
                ),
            ), 2
        return _record(
            "originate", inputs_hashed=inputs_hashed, cost_usd=0.0,
            rationale=rationale,
        ), 0

    # claim_inventory originate
    rc = extract_claims.main(
        [
            "--report", str(project_dir / "REPORT.md"),
            "--methods-provenance", str(talk_paths.methods_provenance_phase0),
            "--project-root", str(project_dir),
            "--output", str(dest),
            "--audit-dir", str(audit_dir),
            "--claude-bin", claude_bin,
            "--model", model,
        ]
    )
    if rc != 0 or not (dest.is_file() and dest.stat().st_size > 0):
        output_present = dest.is_file()
        # extract_claims may have left a validator-rejected TSV at dest;
        # don't leave a known-bad artifact at the canonical path.
        dest.unlink(missing_ok=True)
        return _record(
            "error",
            inputs_hashed=inputs_hashed,
            rationale=rationale,
            error_detail=(
                f"extract_claims.main returned {rc}; "
                f"output_present={output_present} (removed)"
            ),
        ), 2
    # F5: extract_claims.py parses the claude -p envelope's total_cost_usd
    # into its own tool=extract_claims llm_extract record in the shared
    # phase0.jsonl. Read it back so this decision record reflects real
    # spend. None if the LLM was fast-path-skipped or the envelope lacked
    # a parseable cost.
    cost = read_last_extract_claims_cost(audit_dir)
    return _record(
        "originate", inputs_hashed=inputs_hashed, cost_usd=cost,
        rationale=rationale,
    ), 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="phase0_reuse.py",
        description=(
            "Decide, per Phase-0 artifact (methods_provenance, "
            "claim_inventory), whether to reuse a sibling paper-writer "
            "draft's output, originate via the vendored tool, or no-op on "
            "an unchanged-input re-run. v0.4 M1 Tier C."
        ),
    )
    p.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Project root (projects/<id>/) — contains REPORT.md, "
        "notebooks/, and optionally papers/draft_*/ for the reuse path.",
    )
    p.add_argument(
        "--talk-draft-dir",
        type=Path,
        required=True,
        help="Talk draft directory (talks/draft_N/). Artifacts land in "
        "its working/00_phase0/; the decision is stamped to its "
        "audit/phase0.jsonl.",
    )
    p.add_argument(
        "--artifact",
        choices=(*_ARTIFACTS, "all"),
        required=True,
        help="Which artifact to decide on. 'all' runs methods_provenance "
        "then claim_inventory (claim_inventory depends on methods_provenance).",
    )
    p.add_argument(
        "--force-originate",
        action="store_true",
        help="Skip the paper-writer reuse path; always originate via the "
        "vendored tool. Does NOT bypass the unchanged-input no-op fast-path.",
    )
    p.add_argument(
        "--claude-bin",
        default="claude",
        help="Path to the claude CLI binary (passed to extract_claims.py "
        "on the claim_inventory originate path). Default: 'claude' on PATH.",
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Model for the claim_inventory originate `claude -p` call "
        f"(default: {_DEFAULT_MODEL}). Threaded to extract_claims.py, which "
        f"MUST pin the model — see its B6 note.",
    )
    p.add_argument(
        "--paper-draft-glob",
        default="papers/draft_*",
        help="Glob (relative to --project-dir) for paper-writer draft "
        "directories. Default: 'papers/draft_*'.",
    )
    args = p.parse_args(argv)

    project_dir: Path = args.project_dir.resolve()
    if not project_dir.is_dir():
        sys.stderr.write(
            f"error: --project-dir not a directory: {project_dir}\n"
        )
        return 1

    talk_draft_dir: Path = args.talk_draft_dir.resolve()
    if not talk_draft_dir.parent.is_dir():
        sys.stderr.write(
            f"error: --talk-draft-dir parent does not exist: "
            f"{talk_draft_dir.parent}\n"
        )
        return 1

    if args.artifact == "all":
        # ORDER MATTERS: claim_inventory's input hash AND its originate path
        # both consume methods_provenance.md, so methods_provenance must be
        # materialized first. Explicit list, not _ARTIFACTS iteration order
        # (which is dict-insertion order — too implicit to depend on).
        artifacts = ["methods_provenance", "claim_inventory"]
    else:
        artifacts = [args.artifact]

    audit_dir = DraftPaths.from_draft_dir(talk_draft_dir).audit

    for artifact in artifacts:
        record, rc = decide_and_act(
            artifact,
            project_dir,
            talk_draft_dir,
            force_originate=args.force_originate,
            claude_bin=args.claude_bin,
            model=args.model,
            paper_draft_glob=args.paper_draft_glob,
        )
        append_audit_record(audit_dir, record)
        sys.stderr.write(
            f"phase0_reuse: {artifact} -> decision={record['decision']} "
            f"rationale={record['rationale']}"
            + (
                f" source={record['source_path']}"
                if record.get("source_path")
                else ""
            )
            + "\n"
        )
        if rc != 0:
            sys.stderr.write(
                f"phase0_reuse: halting on {artifact} (exit {rc})"
                + (
                    f": {record['error_detail']}"
                    if record.get("error_detail")
                    else ""
                )
                + "\n"
            )
            return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
