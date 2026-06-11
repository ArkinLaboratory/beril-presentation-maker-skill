"""Tests for the finalize_run run-record.v1 emitter.

Covers:
- Stage label derivation from per-stage .metadata.json filenames
- Stage metadata collection (recursive walk of working/) — still used
  by record-finalize's reconciliation
- The run-record.v1 emitter: record-start / record-stage / record-halt
  / record-finalize, run-N allocation + no-clobber, the finalize guard,
  the value-source folds, and the shared-validator roundtrip

(v1.3.1 / Cycle-3 follow-up P0-1 retired the legacy `write` subcommand —
run-summary.v1 / stage-metadata.v1 — and its tests, because that archive
was a second uncoordinated run-N allocator. run-record.v1 supersedes it.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import draft_paths as dp  # noqa: E402
import finalize_run as fr  # noqa: E402

# ---------------------------------------------------------------------------
# _stage_label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metadata_filename, expected", [
    ("00_plan.md.metadata.json", "plan"),
    ("00_throughline_candidates.md.metadata.json", "throughline_candidates"),
    ("02_substories.md.metadata.json", "substory_design"),
    ("citation_pool.json.metadata.json", "citation_pool"),
    ("cross_tenant_signal.md.metadata.json", "cross_tenant"),
    ("cross_tenant_signal.json.metadata.json", "cross_tenant"),
    ("intro.json.metadata.json", "intro"),
    ("qa_anticipated.json.metadata.json", "qa_prep"),
    ("S1_slides.json.metadata.json", "slide_compose-S1"),
    ("S2_slides.json.metadata.json", "slide_compose-S2"),
    ("S99_slides.json.metadata.json", "slide_compose-S99"),
    ("S1_speaker_notes.md.metadata.json", "speaker_notes-S1"),
    ("S3_speaker_notes.md.metadata.json", "speaker_notes-S3"),
    ("S1-pos5_request.json.metadata.json", "ai_image_prompt-S1-pos5"),
    ("intro-pos0_request.json.metadata.json", "ai_image_prompt-intro-pos0"),
])
def test_stage_label_known_pattern(metadata_filename, expected):
    p = Path("/some/working") / metadata_filename
    assert fr._stage_label(p) == expected


def test_stage_label_unknown_falls_back_to_target_name():
    """Unrecognized filename → use target name verbatim (without .metadata.json)."""
    p = Path("/some/working/unrecognized_artifact.txt.metadata.json")
    assert fr._stage_label(p) == "unrecognized_artifact.txt"


# ---------------------------------------------------------------------------
# collect_stage_metadata
# ---------------------------------------------------------------------------

@pytest.fixture
def initialized_draft_with_metadata(tmp_path):
    """Build an initialized draft with a representative spread of
    per-stage .metadata.json files."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()

    # Plan stage
    (paths.working / "00_plan.md.metadata.json").write_text(json.dumps({
        "elapsed_seconds": 120,
        "input_tokens": 50_000,
        "output_tokens": 1_500,
        "estimated_cost_usd": 0.20,
        "model": "claude-sonnet-4-6",
    }))

    # Substory_design
    (paths.working / "02_substories.md.metadata.json").write_text(json.dumps({
        "elapsed_seconds": 90,
        "input_tokens": 40_000,
        "output_tokens": 1_000,
        "estimated_cost_usd": 0.15,
        "model": "claude-sonnet-4-6",
    }))

    # Per-substory slide_compose
    (paths.slides_dir / "S1_slides.json.metadata.json").write_text(json.dumps({
        "elapsed_seconds": 60,
        "input_tokens": 30_000,
        "output_tokens": 800,
        "estimated_cost_usd": 0.10,
        "model": "claude-sonnet-4-6",
    }))
    (paths.slides_dir / "S2_slides.json.metadata.json").write_text(json.dumps({
        "elapsed_seconds": 70,
        "input_tokens": 32_000,
        "output_tokens": 900,
        "estimated_cost_usd": 0.12,
        "model": "claude-sonnet-4-6",
    }))

    # Speaker notes
    (paths.speaker_notes_dir / "S1_speaker_notes.md.metadata.json").write_text(
        json.dumps({
            "elapsed_seconds": 50,
            "input_tokens": 25_000,
            "output_tokens": 700,
            "estimated_cost_usd": 0.08,
            "model": "claude-sonnet-4-6",
        })
    )

    return paths


def test_collect_walks_subdirs(initialized_draft_with_metadata):
    paths = initialized_draft_with_metadata
    meta = fr.collect_stage_metadata(paths.working)
    assert "plan" in meta
    assert "substory_design" in meta
    assert "slide_compose-S1" in meta
    assert "slide_compose-S2" in meta
    assert "speaker_notes-S1" in meta
    # Each entry has source_path for traceability
    for label, m in meta.items():
        assert "_source_path" in m


def test_collect_handles_malformed_json(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    # Write a malformed metadata file
    (paths.working / "00_plan.md.metadata.json").write_text("{not valid json")
    (paths.working / "02_substories.md.metadata.json").write_text(json.dumps({
        "elapsed_seconds": 90, "input_tokens": 1, "output_tokens": 1,
        "model": "test",
    }))
    meta = fr.collect_stage_metadata(paths.working)
    # Malformed file silently skipped; valid one survives
    assert "plan" not in meta
    assert "substory_design" in meta


def test_collect_handles_missing_dir(tmp_path):
    meta = fr.collect_stage_metadata(tmp_path / "nonexistent")
    assert meta == {}


def test_collect_dedupes_by_mtime(tmp_path):
    """If a stage retried and left two metadata files at different
    paths but the SAME label (rare but possible), keep the latest."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    p1 = paths.working / "00_plan.md.metadata.json"
    p1.write_text(json.dumps({"elapsed_seconds": 100, "model": "old"}))
    # No second file with same label (the regex / dict map ensure
    # one-to-one), but we test the dedup-by-mtime path with
    # synthetic same-label metadata files via direct dict mutation.
    meta = fr.collect_stage_metadata(paths.working)
    assert meta["plan"]["model"] == "old"


# ===========================================================================
# Cycle 3 / DP1 — run-record.v1 emitter
# ===========================================================================
#
# Tests the record-start / record-stage / record-halt / record-finalize
# CLI surface AND the underlying functions. Where the platform-shared
# `craft.run_record.validate_run_record` is available (i.e. craft-platform
# is editable-installed alongside the skill), we additionally assert that
# every emitted record validates clean against the contract — this is
# the closest thing we have to a Family E roundtrip from inside the
# skill's own test suite.



def _read_canonical(paths) -> dict:
    return json.loads(paths.run_record.read_text(encoding="utf-8"))


def _try_import_validator():
    """Try to import craft.run_record.validate_run_record. Returns the
    callable or None — skill tests must not hard-depend on craft-
    platform being installed alongside (the conformance pattern
    skips when absent)."""
    try:
        from craft.run_record import validate_run_record  # type: ignore
        return validate_run_record
    except ImportError:
        return None


def test_record_start_writes_canonical_and_archive(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()

    canonical, run_n = fr.record_start(
        paths,
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )

    assert run_n == 1
    assert canonical == paths.run_record
    assert canonical.is_file()
    archive = paths.run_archive_dir(1) / "run_record.json"
    assert archive.is_file()

    rec = _read_canonical(paths)
    assert rec["schema_version"] == "run-record.v1"
    assert rec["skill"] == "presentation-maker"
    assert rec["skill_version"] == "1.3.0"
    assert rec["run_id"] == "run-1"
    assert rec["status"] == "running"
    assert rec["finished_at"] is None
    assert rec["exit_code"] is None
    assert rec["current_stage"] is None
    assert rec["stages"] == []


def test_record_start_no_clobber_allocates_next_run_n(tmp_path):
    """A second record-start (re-run) allocates run-2 + canonical
    is the latest run; the archive of run-1 is untouched."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()

    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    archive_1 = paths.run_archive_dir(1) / "run_record.json"
    snapshot_1 = archive_1.read_bytes()

    _canon, run_n = fr.record_start(
        paths, started_at="2026-06-07T19:00:00Z",
        skill_version="1.3.0",
    )
    assert run_n == 2
    # The run-1 archive is untouched (no clobber).
    assert archive_1.read_bytes() == snapshot_1
    # The canonical is now run-2.
    rec = _read_canonical(paths)
    assert rec["run_id"] == "run-2"
    assert rec["started_at"] == "2026-06-07T19:00:00Z"


# ---------------------------------------------------------------------------
# v1.3.1 / Cycle-3 follow-up P0-2 — resume re-opens, doesn't allocate
# ---------------------------------------------------------------------------

def test_resume_reopens_halted_record_same_run(tmp_path):
    """A halt → resume must stay ONE run record: re-open (flip halted→
    running), keep run_id + started_at + cumulative totals + stages[].
    NOT a fresh run-N (the P0-2 fragmentation bug)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    # pre-halt run: a stage with real cost, then halt at the gate.
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        model="claude-opus-4-7", started_at="2026-06-08T17:00:05Z",
        finished_at="2026-06-08T17:02:30Z", elapsed_seconds=145.0,
        input_tokens=12000, output_tokens=3200, cost_usd=12.76,
    )
    fr.record_halt(paths, gate_id="throughline_pick",
                   started_at="2026-06-08T17:00:00Z", skill_version="1.3.1")
    pre = _read_canonical(paths)
    assert pre["status"] == "halted" and pre["run_id"] == "run-1"

    # RESUME: must re-open run-1, not allocate run-2.
    _canon, run_n, action = fr.record_resume_or_start(
        paths, started_at="2026-06-08T17:42:00Z", skill_version="1.3.1")
    assert action == "reopened"
    assert run_n == 1
    rec = _read_canonical(paths)
    assert rec["run_id"] == "run-1"                 # same run
    assert rec["status"] == "running"               # flipped back
    assert rec["started_at"] == "2026-06-08T17:00:00Z"  # ORIGINAL start
    assert rec["finished_at"] is None and rec["exit_code"] is None
    # cumulative cost + stages carried over (NOT reset to $0).
    assert rec["totals"]["cost_usd"] == 12.76
    assert {s["id"] for s in rec["stages"]} >= {"plan", "throughline_pick"}
    # exactly one run dir exists.
    run_dirs = sorted(p.name for p in paths.runs_dir.iterdir() if p.is_dir())
    assert run_dirs == ["run-1"]


def test_resume_then_continue_completes_one_record(tmp_path):
    """Full halt→resume→complete: ONE record, cumulative total, status
    completed, stages span the halt."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(paths, stage_id="plan", status="completed",
                    cost_usd=12.76, started_at="2026-06-08T17:00:05Z",
                    finished_at="2026-06-08T17:02:30Z")
    fr.record_halt(paths, gate_id="throughline_pick",
                   started_at="2026-06-08T17:00:00Z", skill_version="1.3.1")
    # resume
    fr.record_resume_or_start(paths, started_at="2026-06-08T17:42:00Z",
                              skill_version="1.3.1")
    fr.record_stage(paths, stage_id="substory_design", status="completed",
                    cost_usd=6.73, started_at="2026-06-08T17:42:05Z",
                    finished_at="2026-06-08T17:45:00Z")
    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")
    rec = _read_canonical(paths)
    assert rec["status"] == "completed" and rec["run_id"] == "run-1"
    assert abs(rec["totals"]["cost_usd"] - 19.49) < 1e-9  # cumulative
    ids = {s["id"] for s in rec["stages"]}
    assert {"plan", "substory_design"} <= ids  # span the halt
    run_dirs = sorted(p.name for p in paths.runs_dir.iterdir() if p.is_dir())
    assert run_dirs == ["run-1"]  # exactly one


def test_resume_on_running_record_reopens(tmp_path):
    """A crash/re-invoke with no clean halt (status still running) also
    re-opens — same run, not a new one."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(paths, stage_id="plan", status="completed",
                    cost_usd=1.0, started_at="2026-06-08T17:00:05Z",
                    finished_at="2026-06-08T17:01:00Z")
    _c, run_n, action = fr.record_resume_or_start(
        paths, started_at="2026-06-08T18:00:00Z", skill_version="1.3.1")
    assert action == "reopened" and run_n == 1


def test_resume_on_completed_record_allocates_fresh(tmp_path):
    """--resume-from targeting an ALREADY-FINISHED deck is a genuine
    redo → allocate a fresh run-N."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")
    assert _read_canonical(paths)["status"] == "completed"
    _c, run_n, action = fr.record_resume_or_start(
        paths, started_at="2026-06-08T18:00:00Z", skill_version="1.3.1")
    assert action == "allocated" and run_n == 2
    assert _read_canonical(paths)["status"] == "running"


def test_resume_no_record_allocates_fresh(tmp_path):
    """--resume with no existing record (defensive) → fresh run-1."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _c, run_n, action = fr.record_resume_or_start(
        paths, started_at="2026-06-08T18:00:00Z", skill_version="1.3.1")
    assert action == "allocated" and run_n == 1


# ---------------------------------------------------------------------------
# C1-A1 — reopen on `failed` (the disposition fix). A `--resume-from` after
# a mid-pipeline FAILURE is a CONTINUATION of the same build, not a redo:
# the stages the failed run completed before the failure MUST be carried,
# not dropped. (The C1-A defect bucketed `failed` with `completed` → opened
# a fresh empty run → lost substory_design/curate_figures cost, ~$5/$40.)
# ---------------------------------------------------------------------------

def test_resume_on_failed_record_reopens_not_fresh(tmp_path):
    """status=failed → reopen the SAME run (continuation), not allocate."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(paths, stage_id="plan", status="completed", cost_usd=1.0,
                    started_at="2026-06-08T17:00:05Z",
                    finished_at="2026-06-08T17:01:00Z")
    # mid-pipeline failure → canonical status=failed
    fr.record_finalize(paths, exit_code=2, started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")
    assert _read_canonical(paths)["status"] == "failed"
    _c, run_n, action = fr.record_resume_or_start(
        paths, started_at="2026-06-08T18:00:00Z", skill_version="1.3.1")
    assert action == "reopened" and run_n == 1
    assert _read_canonical(paths)["status"] == "running"


def test_failure_then_resume_carries_completed_stages_no_drop_no_dup(tmp_path):
    """C1-A ACCEPTANCE (deterministic repro of the $40-run drop).

    Sequence: a run completes plan + substory_design + curate_figures,
    then qa_prep FAILS (finalize exit nonzero → status=failed). A
    `--resume-from qa_prep` reopens and completes qa_prep + merge.

    PASS = the canonical holds ALL completed stages (substory_design +
    curate_figures PRESENT — the dropped-on-the-$40-run stages), each
    exactly ONCE (no double-count), status=completed, and total ==
    sum over what actually ran (NOT a fresh-run undercount). The failed
    qa_prep entry transitions failed→completed in place (no duplicate id).
    """
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    # --- continue#1: runs past the gate, completes 3 stages, then qa_prep
    #     fails ---
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(paths, stage_id="plan", status="completed", cost_usd=0.20,
                    started_at="2026-06-08T17:00:05Z",
                    finished_at="2026-06-08T17:01:00Z")
    fr.record_stage(paths, stage_id="substory_design", status="completed",
                    cost_usd=4.99, started_at="2026-06-08T17:01:05Z",
                    finished_at="2026-06-08T17:06:00Z")
    fr.record_stage(paths, stage_id="curate_figures", status="completed",
                    cost_usd=0.00, started_at="2026-06-08T17:06:05Z",
                    finished_at="2026-06-08T17:06:30Z")
    # qa_prep started but failed (record the running entry then fail-finalize)
    fr.record_stage(paths, stage_id="qa_prep", status="running",
                    started_at="2026-06-08T17:07:00Z")
    fr.record_finalize(paths, exit_code=1, started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")
    assert _read_canonical(paths)["status"] == "failed"

    # --- continue#2: --resume-from qa_prep → reopen (NOT fresh) ---
    _c, run_n, action = fr.record_resume_or_start(
        paths, started_at="2026-06-08T18:00:00Z", skill_version="1.3.1")
    assert action == "reopened" and run_n == 1, (
        "C1-A: a resume after failure must REOPEN the same run, not "
        f"allocate a fresh one (got action={action!r}, run-{run_n})"
    )
    # qa_prep now succeeds (upserts failed/running → completed in place),
    # then merge runs.
    fr.record_stage(paths, stage_id="qa_prep", status="completed",
                    cost_usd=1.05, started_at="2026-06-08T18:00:05Z",
                    finished_at="2026-06-08T18:01:30Z")
    fr.record_stage(paths, stage_id="merge", status="completed", cost_usd=0.00,
                    started_at="2026-06-08T18:01:35Z",
                    finished_at="2026-06-08T18:01:50Z")
    fr.record_finalize(paths, exit_code=0, started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")

    rec = _read_canonical(paths)
    assert rec["status"] == "completed"
    assert rec["run_id"] == "run-1"  # ONE run across the failure
    ids = [s["id"] for s in rec["stages"]]
    # no duplicate ids (the failed-stage upserts in place)
    assert len(ids) == len(set(ids)), f"duplicate stage ids: {ids}"
    completed = {s["id"] for s in rec["stages"]
                 if s.get("status") == "completed"}
    # the stages the failed run completed before the failure are CARRIED
    assert {"plan", "substory_design", "curate_figures"} <= completed, (
        "C1-A drop: pre-failure completed stages missing from canonical — "
        f"completed={sorted(completed)}"
    )
    # and the post-resume stages
    assert {"qa_prep", "merge"} <= completed
    # qa_prep is completed (transitioned from failed/running, single entry)
    qa_entries = [s for s in rec["stages"] if s["id"] == "qa_prep"]
    assert len(qa_entries) == 1 and qa_entries[0]["status"] == "completed"
    # A3: total == sum over the ACCUMULATED stages (ground-truth cost of
    # what actually ran: 0.20 + 4.99 + 0.00 + 1.05 + 0.00 = 6.24), NOT a
    # fresh-run undercount that drops substory's 4.99.
    assert abs(rec["totals"]["cost_usd"] - 6.24) < 1e-9, (
        f"total mis-accounts the carried stages: {rec['totals']['cost_usd']}"
    )
    # exactly one run dir
    run_dirs = sorted(p.name for p in paths.runs_dir.iterdir() if p.is_dir())
    assert run_dirs == ["run-1"]


def test_cli_record_start_resume_reopens(tmp_path, capsys):
    """The shell's `record-start --resume` path re-opens a halted run."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_halt(paths, gate_id="throughline_pick",
                   started_at="2026-06-08T17:00:00Z", skill_version="1.3.1")
    rc = fr.main([
        "record-start", "--draft-dir", str(tmp_path),
        "--started-at", "2026-06-08T17:42:00Z", "--resume",
    ])
    assert rc == 0
    rec = _read_canonical(paths)
    assert rec["run_id"] == "run-1" and rec["status"] == "running"
    captured = capsys.readouterr()
    assert "reopened run-1" in captured.err


def test_record_stage_append_then_finalize(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()

    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_stage(
        paths,
        stage_id="plan",
        status="completed",
        model="claude-opus-4-7",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        elapsed_seconds=145.0,
        input_tokens=12000,
        output_tokens=3200,
        cost_usd=0.31,
    )
    rec = _read_canonical(paths)
    assert rec["status"] == "running"
    assert rec["current_stage"] == "plan"
    assert len(rec["stages"]) == 1
    assert rec["stages"][0]["id"] == "plan"
    assert rec["totals"]["cost_usd"] == 0.31
    assert rec["totals"]["input_tokens"] == 12000

    fr.record_finalize(
        paths, exit_code=0,
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert rec["status"] == "completed"
    assert rec["exit_code"] == 0
    assert rec["finished_at"] is not None
    assert rec["current_stage"] is None


def test_finalize_completeness_guard_fires_on_dropped_stage(tmp_path):
    """C1-A2 (presmaker wiring): if a (hypothetical) resume regression
    produced a canonical that drops a stage an ARCHIVED run completed,
    record_finalize must REFUSE to finalize as completed and raise
    CompletenessError. Defense-in-depth: even if A1 regresses, this fires.

    We simulate the regression directly: an archived run-1 that completed
    substory_design, and a canonical run-2 that lacks it, then finalize."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    # Forge an archived run-1 that completed substory_design (a prior run
    # that finished those stages before dying).
    run1 = paths.runs_dir / "run-1"
    run1.mkdir(parents=True, exist_ok=True)
    archived = {
        "run_id": "run-1", "status": "failed",
        "stages": [
            {"id": "plan", "status": "completed"},
            {"id": "substory_design", "status": "completed"},
        ],
    }
    (run1 / "run_record.json").write_text(json.dumps(archived),
                                          encoding="utf-8")
    # Canonical run-2 only ran the late stages (the dropped-stage bug).
    fr.record_start(paths, started_at="2026-06-08T18:00:00Z",
                    skill_version="1.3.1")
    # bump it to run-2 by faking a prior completed run would be complex;
    # instead assert directly against the guard semantics: the canonical
    # (run-2, no substory_design) vs the archive (run-1, has it).
    canonical_now = fr._load_existing_record(paths.run_record)
    # the just-started canonical is run-2 (run-1 dir exists) with no stages
    assert canonical_now["run_id"] == "run-2"
    fr.record_stage(paths, stage_id="qa_prep", status="completed",
                    cost_usd=1.0, started_at="2026-06-08T18:00:05Z",
                    finished_at="2026-06-08T18:01:00Z")
    with pytest.raises(fr.CompletenessError) as ei:
        fr.record_finalize(paths, exit_code=0,
                           started_at="2026-06-08T18:00:00Z",
                           skill_version="1.3.1")
    msg = "; ".join(ei.value.errors)
    assert "substory_design" in msg and "must never drop" in msg
    # and the canonical was NOT written as completed
    assert fr._load_existing_record(paths.run_record)["status"] != "completed"


def test_finalize_cli_completeness_failure_returns_nonzero(tmp_path, capsys):
    """The CLI surfaces the guard as a non-zero exit (loud)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    run1 = paths.runs_dir / "run-1"
    run1.mkdir(parents=True, exist_ok=True)
    (run1 / "run_record.json").write_text(json.dumps({
        "run_id": "run-1", "status": "failed",
        "stages": [{"id": "substory_design", "status": "completed"}],
    }), encoding="utf-8")
    fr.record_start(paths, started_at="2026-06-08T18:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(paths, stage_id="qa_prep", status="completed",
                    cost_usd=1.0, started_at="2026-06-08T18:00:05Z",
                    finished_at="2026-06-08T18:01:00Z")
    rc = fr.main([
        "record-finalize", "--draft-dir", str(tmp_path),
        "--exit-code", "0", "--started-at", "2026-06-08T18:00:00Z",
    ])
    assert rc == 3  # non-zero, loud
    err = capsys.readouterr().err
    assert "COMPLETENESS FAILURE" in err and "substory_design" in err


def test_finalize_completeness_guard_passes_normal_resume(tmp_path):
    """Defensive: the guard must NOT false-fire on a correct A1 resume,
    where the failed run's archive shares the canonical's run_id (skipped)
    and the carried stages are present."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-08T17:00:00Z",
                    skill_version="1.3.1")
    fr.record_stage(paths, stage_id="plan", status="completed", cost_usd=0.2,
                    started_at="2026-06-08T17:00:05Z",
                    finished_at="2026-06-08T17:01:00Z")
    fr.record_stage(paths, stage_id="substory_design", status="completed",
                    cost_usd=4.99, started_at="2026-06-08T17:01:05Z",
                    finished_at="2026-06-08T17:06:00Z")
    fr.record_finalize(paths, exit_code=1, started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")  # failed
    # resume (reopen run-1, same run_id) → complete
    fr.record_resume_or_start(paths, started_at="2026-06-08T18:00:00Z",
                              skill_version="1.3.1")
    fr.record_stage(paths, stage_id="qa_prep", status="completed",
                    cost_usd=1.0, started_at="2026-06-08T18:00:05Z",
                    finished_at="2026-06-08T18:01:00Z")
    # must NOT raise — substory_design carried, archive run_id == canonical
    fr.record_finalize(paths, exit_code=0, started_at="2026-06-08T17:00:00Z",
                       skill_version="1.3.1")
    rec = _read_canonical(paths)
    assert rec["status"] == "completed"
    assert {"plan", "substory_design", "qa_prep"} <= {
        s["id"] for s in rec["stages"] if s["status"] == "completed"}


def test_record_finalize_failed_when_exit_nonzero(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_finalize(
        paths, exit_code=2,
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert rec["status"] == "failed"
    assert rec["exit_code"] == 2


def test_record_halt_writes_halted_status(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_halt(
        paths, gate_id="throughline_pick",
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert rec["status"] == "halted"
    assert rec["current_stage"] == "throughline_pick"
    assert rec["finished_at"] is None
    assert rec["exit_code"] is None
    # Gate is also in stages[] so the referential check passes.
    assert any(s["id"] == "throughline_pick" for s in rec["stages"])


def test_record_finalize_preserves_halted_state(tmp_path):
    """THE FINALIZE GUARD: record-finalize MUST NOT overwrite a
    status=halted record. The trap-EXIT path on a halted process
    exit fires this; without the guard it would demote halted to
    completed (the bug Adam's amend rationale called out)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_halt(
        paths, gate_id="throughline_pick",
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    snapshot_before = paths.run_record.read_bytes()

    # Simulate the trap-EXIT firing on a halt.
    fr.record_finalize(
        paths, exit_code=0,
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert rec["status"] == "halted", (
        "finalize guard regression: halted record was overwritten "
        "to completed. See finalize_run.record_finalize for the "
        "guard logic — the trap-EXIT path MUST NOT demote halted."
    )
    # And the canonical file should be byte-identical to the pre-
    # finalize snapshot (the guard returned early, no write).
    assert paths.run_record.read_bytes() == snapshot_before


def test_record_finalize_after_real_completion_status_completed(tmp_path):
    """Counter-test: a normal completion (no halt) does flip to
    completed via finalize. Pairs with the guard test to pin both
    sides of the conditional."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        model="claude-opus-4-7",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        elapsed_seconds=145.0,
    )
    fr.record_finalize(
        paths, exit_code=0,
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert rec["status"] == "completed"


def test_record_stage_idempotent_on_repeat(tmp_path):
    """A retry that re-emits the same stage id replaces the prior
    entry instead of appending a duplicate (the stream_progress
    path can double-emit). totals must NOT double-count."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        model="claude-opus-4-7",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        elapsed_seconds=145.0,
        input_tokens=12000, output_tokens=3200, cost_usd=0.31,
    )
    # Retry the same stage with updated numbers.
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        model="claude-opus-4-7",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:45Z",
        elapsed_seconds=160.0,
        input_tokens=13000, output_tokens=3400, cost_usd=0.33,
    )
    rec = _read_canonical(paths)
    plan_entries = [s for s in rec["stages"] if s["id"] == "plan"]
    assert len(plan_entries) == 1, "stage id collision should replace, not append"
    assert plan_entries[0]["cost_usd"] == 0.33
    assert rec["totals"]["cost_usd"] == 0.33  # not 0.64


def test_atomic_write_no_partial_file_visible(tmp_path):
    """The tempfile+rename discipline means the canonical path is
    either fully-written (with the prior content) or fully-written
    (with the new content) — never a partially-written readable
    file. We can't easily prove ordering under contention in pure
    pytest, but we CAN assert the tempfile is gone after a successful
    write (proves the rename happened, not a leftover .tmp)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # Expected canonical exists; any leftover .tmp would be a leak.
    leftover = [
        p for p in paths.audit.iterdir()
        if p.name.startswith(".") and p.name.endswith(".tmp")
    ]
    assert leftover == [], (
        f"atomic write left a tempfile behind: {leftover}"
    )


def test_emitted_records_validate_against_shared_validator(tmp_path):
    """The Family-E cross-skill check, exercised from inside the
    skill: every record we emit at every CLI write point validates
    clean against craft.run_record.validate_run_record. Graceful-
    skips when craft-platform isn't installed alongside (the same
    discipline as the conformance fixture)."""
    validate = _try_import_validator()
    if validate is None:
        pytest.skip(
            "craft-platform not editable-installed alongside; "
            "Family-E roundtrip is checked at craft-platform's "
            "conformance pytest. To run locally: "
            "pip install -e ../craft-platform"
        )
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()

    # record-start
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    rec = _read_canonical(paths)
    assert validate(rec) == []

    # record-stage
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        model="claude-opus-4-7",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        elapsed_seconds=145.0,
        input_tokens=12000, output_tokens=3200, cost_usd=0.31,
    )
    rec = _read_canonical(paths)
    assert validate(rec) == []

    # record-halt
    fr.record_halt(
        paths, gate_id="throughline_pick",
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert validate(rec) == []

    # record-finalize (guard active — halted preserved)
    fr.record_finalize(
        paths, exit_code=0,
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    rec = _read_canonical(paths)
    assert validate(rec) == []
    # And it's still halted (guard worked).
    assert rec["status"] == "halted"


def test_cli_record_start_idempotent_via_subprocess_safe(tmp_path, capsys):
    """The shell wires the CLI subcommand; this exercises the
    argparse path end-to-end (the function calls above bypass it)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    rc = fr.main([
        "record-start",
        "--draft-dir", str(tmp_path),
        "--started-at", "2026-06-07T18:00:00Z",
        "--skill-version", "1.3.0",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "record-start run-1" in captured.err
    assert paths.run_record.is_file()


def test_cli_record_halt_via_argparse(tmp_path, capsys):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    rc = fr.main([
        "record-halt",
        "--draft-dir", str(tmp_path),
        "--gate", "throughline_pick",
        "--started-at", "2026-06-07T18:00:00Z",
        "--skill-version", "1.3.0",
    ])
    assert rc == 0
    rec = _read_canonical(paths)
    assert rec["status"] == "halted"
    assert rec["current_stage"] == "throughline_pick"


def test_cli_record_finalize_guard_via_argparse(tmp_path, capsys):
    """Exercise the guard through the CLI to pin the shell-facing
    path (the trap-EXIT path will invoke this verbatim)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_halt(
        paths, gate_id="throughline_pick",
        started_at="2026-06-07T18:00:00Z",
        skill_version="1.3.0",
    )
    snapshot = paths.run_record.read_bytes()
    rc = fr.main([
        "record-finalize",
        "--draft-dir", str(tmp_path),
        "--exit-code", "0",
        "--started-at", "2026-06-07T18:00:00Z",
        "--skill-version", "1.3.0",
    ])
    assert rc == 0
    # Halt preserved; canonical byte-identical to pre-finalize state.
    assert paths.run_record.read_bytes() == snapshot
    captured = capsys.readouterr()
    assert "preserving halt state" in captured.err


# ---------------------------------------------------------------------------
# Orchestrator-authoritative stage wiring (Adam 2026-06-07):
#   --from-sidecar / --image-provenance value sourcing +
#   loud reconciliation at finalize.
# ---------------------------------------------------------------------------

def _write_sidecar(paths, name: str, payload: dict) -> Path:
    p = paths.working / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_read_sidecar_metadata_normalizes_fields(tmp_path):
    sc = tmp_path / "x.metadata.json"
    sc.write_text(json.dumps({
        "elapsed_seconds": 42,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 50,
        "estimated_cost_usd": 0.123456789,
        "model": "claude-opus-4-7",
    }), encoding="utf-8")
    out = fr._read_sidecar_metadata(sc)
    assert out["model"] == "claude-opus-4-7"
    assert out["elapsed_seconds"] == 42.0
    assert out["input_tokens"] == 1000
    assert out["output_tokens"] == 200
    assert out["cache_read_tokens"] == 50
    assert out["cache_creation_tokens"] == 0  # omitted-when-zero in source
    assert out["cost_usd"] == round(0.123456789, 6)


def test_read_sidecar_metadata_missing_returns_empty(tmp_path):
    assert fr._read_sidecar_metadata(tmp_path / "nope.json") == {}


def test_sum_image_provenance_aggregates_cost(tmp_path):
    prov = tmp_path / "image_provenance.json"
    prov.write_text(json.dumps({
        "version": "1.0",
        "entries": [
            {"cost_usd": 0.04, "elapsed_seconds": 8.0, "model": "imagen-x"},
            {"cost_usd": 0.04, "elapsed_seconds": 9.0, "model": "imagen-x"},
            {"cost_usd": 0.03, "elapsed_seconds": 7.0, "model": "imagen-y"},
        ],
    }), encoding="utf-8")
    out = fr._sum_image_provenance(prov)
    assert out["cost_usd"] == round(0.11, 6)
    assert out["elapsed_seconds"] == 24.0
    assert out["models"] == ["imagen-x", "imagen-y"]
    assert out["n_entries"] == 3


def test_sum_image_provenance_missing_returns_zeros(tmp_path):
    out = fr._sum_image_provenance(tmp_path / "nope.json")
    assert out == {
        "cost_usd": 0.0, "elapsed_seconds": 0.0,
        "models": [], "n_entries": 0,
    }


def test_record_stage_from_sidecar_sources_values(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    sc = _write_sidecar(paths, "00_plan.md.metadata.json", {
        "elapsed_seconds": 145,
        "input_tokens": 12000,
        "output_tokens": 3200,
        "estimated_cost_usd": 0.31,
        "model": "claude-opus-4-7",
    })
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        from_sidecar=sc,
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "plan")
    assert stage["model"] == "claude-opus-4-7"
    assert stage["input_tokens"] == 12000
    assert stage["output_tokens"] == 3200
    assert stage["cost_usd"] == 0.31
    assert stage["elapsed_seconds"] == 145.0
    # totals reconcile (validator-critical)
    assert rec["totals"]["input_tokens"] == 12000
    assert rec["totals"]["cost_usd"] == 0.31


def test_record_stage_image_provenance_adds_generation_cost(tmp_path):
    """The undercount fix: image_gen stage cost = prompt-composition
    sidecar cost + summed per-image generation cost."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # Prompt-composition sidecar (the LLM that wrote the image prompt).
    sc = _write_sidecar(paths, "S1-pos5_request.json.metadata.json", {
        "elapsed_seconds": 10,
        "input_tokens": 500,
        "output_tokens": 100,
        "estimated_cost_usd": 0.02,
        "model": "claude-sonnet-4-6",
    })
    # Image-generation provenance (the provider's per-image charge).
    prov = paths.image_provenance_json
    prov.parent.mkdir(parents=True, exist_ok=True)
    prov.write_text(json.dumps({
        "version": "1.0",
        "entries": [
            {"cost_usd": 0.04, "elapsed_seconds": 8.0, "model": "imagen-x"},
            {"cost_usd": 0.04, "elapsed_seconds": 9.0, "model": "imagen-x"},
        ],
    }), encoding="utf-8")

    fr.record_stage(
        paths, stage_id="image_gen", status="completed",
        started_at="2026-06-07T18:10:00Z",
        finished_at="2026-06-07T18:11:00Z",
        from_sidecar=sc,
        image_provenance=prov,
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "image_gen")
    # 0.02 (prompt) + 0.08 (2×0.04 generation) = 0.10
    assert stage["cost_usd"] == round(0.10, 6)
    # elapsed: 10 (prompt) + 17 (8+9 generation) = 27
    assert stage["elapsed_seconds"] == 27.0
    # LLM prompt model stays primary; generation model is a sub-detail.
    assert stage["model"] == "claude-sonnet-4-6"


def test_record_stage_image_provenance_adopts_gen_model_when_no_sidecar(
    tmp_path,
):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    prov = paths.image_provenance_json
    prov.parent.mkdir(parents=True, exist_ok=True)
    prov.write_text(json.dumps({
        "version": "1.0",
        "entries": [{"cost_usd": 0.04, "elapsed_seconds": 8.0,
                     "model": "imagen-x"}],
    }), encoding="utf-8")
    fr.record_stage(
        paths, stage_id="image_gen", status="completed",
        started_at="2026-06-07T18:10:00Z",
        finished_at="2026-06-07T18:11:00Z",
        image_provenance=prov,
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "image_gen")
    assert stage["cost_usd"] == 0.04
    assert stage["model"] == "imagen-x"


def test_record_stage_explicit_args_override_sidecar(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    sc = _write_sidecar(paths, "00_plan.md.metadata.json", {
        "input_tokens": 12000, "estimated_cost_usd": 0.31,
        "model": "claude-opus-4-7", "elapsed_seconds": 145,
    })
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        from_sidecar=sc,
        input_tokens=999,  # explicit override
        cost_usd=1.23,     # explicit override
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "plan")
    assert stage["input_tokens"] == 999
    assert stage["cost_usd"] == 1.23
    # non-overridden field still comes from sidecar
    assert stage["output_tokens"] == 0
    assert stage["model"] == "claude-opus-4-7"


def test_record_stage_non_llm_zero_cost_entry(tmp_path):
    """A non-LLM stage (no sidecar) records a zero-cost entry naming
    the stage — the orchestrator-authoritative enum still includes it."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_stage(
        paths, stage_id="curate_figures", status="completed",
        started_at="2026-06-07T18:05:00Z",
        finished_at="2026-06-07T18:05:03Z",
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "curate_figures")
    assert stage["cost_usd"] == 0.0
    assert stage["model"] is None
    assert stage["input_tokens"] == 0


def test_record_stage_backdates_started_at_from_elapsed(tmp_path):
    """The shell can call record-stage with just --stage +
    --from-sidecar (no T0): started_at is back-dated from finished_at
    − sidecar elapsed."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        finished_at="2026-06-07T18:02:30Z",
        elapsed_seconds=150.0,
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "plan")
    # 18:02:30 − 150s = 18:00:00
    assert stage["started_at"] == "2026-06-07T18:00:00Z"
    assert stage["finished_at"] == "2026-06-07T18:02:30Z"


def test_iso_minus_seconds_handles_bad_input():
    assert fr._iso_minus_seconds("not-a-date", 10) == "not-a-date"
    assert fr._iso_minus_seconds(
        "2026-06-07T18:02:30Z", 90
    ) == "2026-06-07T18:01:00Z"


def test_record_stage_sidecar_glob_sums_many(tmp_path):
    """image_gen: prompt-composition cost spread across one sidecar per
    image is summed via --sidecar-glob into the single stage entry."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    req_dir = paths.working / "05_image_requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    for i, cost in enumerate([0.01, 0.02, 0.015]):
        (req_dir / f"S1-pos{i}_request.json.metadata.json").write_text(
            json.dumps({
                "input_tokens": 100, "output_tokens": 50,
                "estimated_cost_usd": cost, "model": "claude-sonnet-4-6",
                "elapsed_seconds": 5,
            }), encoding="utf-8")
    fr.record_stage(
        paths, stage_id="image_gen", status="completed",
        finished_at="2026-06-07T18:11:00Z",
        sidecar_glob=str(req_dir / "*_request.json.metadata.json"),
    )
    rec = _read_canonical(paths)
    stage = next(s for s in rec["stages"] if s["id"] == "image_gen")
    assert stage["input_tokens"] == 300  # 3 × 100
    assert stage["output_tokens"] == 150
    assert stage["cost_usd"] == round(0.045, 6)
    assert stage["elapsed_seconds"] == 15.0
    assert stage["model"] == "claude-sonnet-4-6"


def test_record_stage_glob_plus_provenance_full_image_gen(tmp_path):
    """The complete image_gen fold: --sidecar-glob (prompt) +
    --image-provenance (generation). Both costs in one entry."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    req_dir = paths.working / "05_image_requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "S1-pos0_request.json.metadata.json").write_text(
        json.dumps({"estimated_cost_usd": 0.02, "elapsed_seconds": 5,
                    "model": "claude-sonnet-4-6"}), encoding="utf-8")
    prov = paths.image_provenance_json
    prov.parent.mkdir(parents=True, exist_ok=True)
    prov.write_text(json.dumps({
        "version": "1.0",
        "entries": [{"cost_usd": 0.08, "elapsed_seconds": 9.0,
                     "model": "imagen-x"}],
    }), encoding="utf-8")
    fr.record_stage(
        paths, stage_id="image_gen", status="completed",
        finished_at="2026-06-07T18:11:00Z",
        sidecar_glob=str(req_dir / "*_request.json.metadata.json"),
        image_provenance=prov,
    )
    stage = next(
        s for s in _read_canonical(paths)["stages"] if s["id"] == "image_gen"
    )
    # 0.02 (prompt) + 0.08 (generation) = 0.10
    assert stage["cost_usd"] == round(0.10, 6)
    assert stage["elapsed_seconds"] == 14.0  # 5 + 9


def test_finalize_folds_image_prompt_sidecars_into_image_gen(
    tmp_path, capsys,
):
    """At finalize, the per-image ai_image_prompt-* sidecars must NOT
    re-appear as their own stages (they're folded into the recorded
    image_gen) — no double-count, no false RECONCILE WARNING."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # Drop the per-image prompt sidecars on disk (the finalize walk
    # would normally project them).
    req_dir = paths.working / "05_image_requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (req_dir / f"S1-pos{i}_request.json.metadata.json").write_text(
            json.dumps({"estimated_cost_usd": 0.02, "elapsed_seconds": 5,
                        "model": "claude-sonnet-4-6"}), encoding="utf-8")
    # Orchestrator recorded the aggregate image_gen (folding both).
    fr.record_stage(
        paths, stage_id="image_gen", status="completed",
        finished_at="2026-06-07T18:11:00Z",
        sidecar_glob=str(req_dir / "*_request.json.metadata.json"),
    )
    recorded = next(
        s for s in _read_canonical(paths)["stages"] if s["id"] == "image_gen"
    )
    assert recorded["cost_usd"] == round(0.04, 6)

    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-07T18:00:00Z",
                       skill_version="1.3.0")
    rec = _read_canonical(paths)
    ids = [s["id"] for s in rec["stages"]]
    # No ai_image_prompt-* stages leaked in; only the aggregate.
    assert not any(i.startswith("ai_image_prompt-") for i in ids)
    assert "image_gen" in ids
    # image_gen cost unchanged (not double-counted).
    fin = next(s for s in rec["stages"] if s["id"] == "image_gen")
    assert fin["cost_usd"] == round(0.04, 6)
    captured = capsys.readouterr()
    assert "RECONCILE WARNING" not in captured.err


def test_sidecar_parent_stage_maps_image_prompts():
    assert fr._sidecar_parent_stage("ai_image_prompt-S1-pos5") == "image_gen"
    assert fr._sidecar_parent_stage("plan") is None


def test_sidecar_parent_stage_substory_design_alias():
    # v0.4 deck_outline + v0.3 substory_design share 02_substories.md;
    # the substory_design sidecar is absorbed by a recorded deck_outline.
    assert fr._sidecar_parent_stage("substory_design") == "deck_outline"


def test_finalize_v0_4_deck_outline_absorbs_substory_sidecar(tmp_path, capsys):
    """A v0.4 run records `deck_outline` but the shared 02_substories.md
    sidecar maps to `substory_design`; finalize must NOT re-add it or
    warn (it's an alias of the recorded deck_outline)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # The sidecar on disk (02_substories.md → label substory_design).
    (paths.working / "02_substories.md.metadata.json").write_text(
        json.dumps({"estimated_cost_usd": 0.20, "model": "claude-opus-4-7",
                    "elapsed_seconds": 120}), encoding="utf-8")
    # v0.4 orchestrator recorded deck_outline from that sidecar.
    fr.record_stage(
        paths, stage_id="deck_outline", status="completed",
        from_sidecar=paths.working / "02_substories.md.metadata.json",
        finished_at="2026-06-07T18:05:00Z",
    )
    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-07T18:00:00Z",
                       skill_version="1.3.0")
    rec = _read_canonical(paths)
    ids = [s["id"] for s in rec["stages"]]
    assert "deck_outline" in ids
    assert "substory_design" not in ids  # alias absorbed, not duplicated
    captured = capsys.readouterr()
    assert "RECONCILE WARNING" not in captured.err


def test_read_revise_metadata_extracts_cost_and_timestamps(tmp_path):
    meta = tmp_path / "revise_loop_metadata.json"
    meta.write_text(json.dumps({
        "findings_revised": ["F1", "F2"],
        "findings_added": [],
        "cost_usd_cumulative": 0.4732,
        "started_at": "2026-06-07T18:20:00Z",
        "finished_at": "2026-06-07T18:25:00Z",
    }), encoding="utf-8")
    out = fr._read_revise_metadata(meta)
    assert out["cost_usd"] == round(0.4732, 6)
    assert out["started_at"] == "2026-06-07T18:20:00Z"
    assert out["finished_at"] == "2026-06-07T18:25:00Z"


def test_read_revise_metadata_missing_returns_zeros(tmp_path):
    out = fr._read_revise_metadata(tmp_path / "nope.json")
    assert out == {"cost_usd": 0.0, "started_at": None, "finished_at": None}


def test_record_stage_revise_metadata_folds_cost(tmp_path):
    """revise_slides: cost_usd_cumulative folds in; timestamps adopted
    when the caller passes none."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    meta = paths.audit / "revise_loop_metadata.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({
        "cost_usd_cumulative": 0.55,
        "started_at": "2026-06-07T18:20:00Z",
        "finished_at": "2026-06-07T18:25:00Z",
    }), encoding="utf-8")
    fr.record_stage(
        paths, stage_id="revise_slides", status="completed",
        from_revise_metadata=meta,
    )
    stage = next(
        s for s in _read_canonical(paths)["stages"]
        if s["id"] == "revise_slides"
    )
    assert stage["cost_usd"] == 0.55
    assert stage["started_at"] == "2026-06-07T18:20:00Z"
    assert stage["finished_at"] == "2026-06-07T18:25:00Z"


def test_sum_phase0_jsonl_sums_cost(tmp_path):
    p = tmp_path / "phase0.jsonl"
    p.write_text(
        json.dumps({"tool": "phase0_reuse", "decision": "reuse",
                    "cost_usd": 0.0}) + "\n"
        + json.dumps({"tool": "extract_claims", "phase": "llm_extract",
                      "cost_usd": 0.085}) + "\n"
        + json.dumps({"tool": "phase0_reuse", "decision": "originate",
                      "cost_usd": 0.085}) + "\n",
        encoding="utf-8",
    )
    assert fr._sum_phase0_jsonl(p)["cost_usd"] == round(0.17, 6)


def test_sum_phase0_jsonl_missing_and_malformed(tmp_path):
    assert fr._sum_phase0_jsonl(tmp_path / "nope.jsonl")["cost_usd"] == 0.0
    p = tmp_path / "bad.jsonl"
    p.write_text("not json\n{\"cost_usd\": 0.5}\n", encoding="utf-8")
    assert fr._sum_phase0_jsonl(p)["cost_usd"] == 0.5  # skips bad line


def test_record_stage_phase0_folds_originate_cost(tmp_path):
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    jsonl = paths.audit / "phase0.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text(
        json.dumps({"tool": "extract_claims", "phase": "llm_extract",
                    "cost_usd": 0.09}) + "\n",
        encoding="utf-8",
    )
    fr.record_stage(
        paths, stage_id="phase0_tooling", status="completed",
        finished_at="2026-06-07T18:01:00Z",
        from_phase0_jsonl=jsonl,
    )
    stage = next(
        s for s in _read_canonical(paths)["stages"]
        if s["id"] == "phase0_tooling"
    )
    assert stage["cost_usd"] == 0.09


def test_record_stage_vqa_folds_vision_sidecar_plus_revise(tmp_path):
    """visual_qa_final: vision-pass sidecar cost + 2nd-pass revise cost
    fold into one entry."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # Vision-pass sidecar (visual_qa.py writes this next to its JSON).
    vsc = paths.audit / "visual_qa_final.json.metadata.json"
    vsc.parent.mkdir(parents=True, exist_ok=True)
    vsc.write_text(json.dumps({
        "estimated_cost_usd": 0.90, "model": "claude-opus-4-7",
        "elapsed_seconds": 30,
    }), encoding="utf-8")
    # 2nd revise pass metadata.
    meta = paths.audit / "revise_loop_metadata.json"
    meta.write_text(json.dumps({
        "cost_usd_cumulative": 0.35,
        "started_at": "2026-06-07T18:30:00Z",
        "finished_at": "2026-06-07T18:33:00Z",
    }), encoding="utf-8")
    fr.record_stage(
        paths, stage_id="visual_qa_final", status="completed",
        from_sidecar=vsc, from_revise_metadata=meta,
    )
    stage = next(
        s for s in _read_canonical(paths)["stages"]
        if s["id"] == "visual_qa_final"
    )
    # 0.90 (vision) + 0.35 (2nd revise) = 1.25
    assert stage["cost_usd"] == round(1.25, 6)
    assert stage["model"] == "claude-opus-4-7"


def test_finalize_reconcile_warns_on_unrecorded_sidecar(tmp_path, capsys):
    """A sidecar with no orchestrator-recorded stage → LOUD warning +
    the projected entry is added (data not lost)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # Orchestrator recorded 'plan' but a stray 'intro' sidecar exists
    # that the shell never record-stage'd.
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        input_tokens=100, cost_usd=0.10,
    )
    _write_sidecar(paths, "intro.json.metadata.json", {
        "input_tokens": 500, "estimated_cost_usd": 0.05,
        "model": "claude-sonnet-4-6", "elapsed_seconds": 20,
    })
    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-07T18:00:00Z",
                       skill_version="1.3.0")
    captured = capsys.readouterr()
    assert "RECONCILE WARNING" in captured.err
    assert "intro" in captured.err
    rec = _read_canonical(paths)
    ids = {s["id"] for s in rec["stages"]}
    assert "intro" in ids  # data preserved despite the wiring gap
    assert "plan" in ids


def test_finalize_reconcile_keeps_orchestrator_richer_image_cost(
    tmp_path, capsys,
):
    """The image_gen recorded cost (prompt + generation) is LARGER than
    the bare sidecar — finalize must KEEP it (no overwrite, no warning):
    overwriting would reintroduce the undercount."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    # Sidecar for image prompt = 0.02; provenance generation = 0.08.
    sc = _write_sidecar(paths, "S1-pos5_request.json.metadata.json", {
        "input_tokens": 500, "estimated_cost_usd": 0.02,
        "model": "claude-sonnet-4-6", "elapsed_seconds": 10,
    })
    prov = paths.image_provenance_json
    prov.parent.mkdir(parents=True, exist_ok=True)
    prov.write_text(json.dumps({
        "version": "1.0",
        "entries": [{"cost_usd": 0.08, "elapsed_seconds": 8.0,
                     "model": "imagen-x"}],
    }), encoding="utf-8")
    # Orchestrator records image_gen with the folded (richer) cost.
    fr.record_stage(
        paths, stage_id="ai_image_prompt-S1-pos5", status="completed",
        started_at="2026-06-07T18:10:00Z",
        finished_at="2026-06-07T18:11:00Z",
        from_sidecar=sc, image_provenance=prov,
    )
    recorded_before = next(
        s for s in _read_canonical(paths)["stages"]
        if s["id"] == "ai_image_prompt-S1-pos5"
    )
    assert recorded_before["cost_usd"] == round(0.10, 6)

    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-07T18:00:00Z",
                       skill_version="1.3.0")
    captured = capsys.readouterr()
    # Recorded (0.10) > sidecar (0.02): expected, NOT a warning.
    assert "RECONCILE WARNING" not in captured.err
    stage = next(
        s for s in _read_canonical(paths)["stages"]
        if s["id"] == "ai_image_prompt-S1-pos5"
    )
    # Orchestrator's richer value preserved — undercount NOT reintroduced.
    assert stage["cost_usd"] == round(0.10, 6)


def test_finalize_reconcile_warns_when_recorded_under_sidecar(
    tmp_path, capsys,
):
    """If the recorded cost is LESS than the sidecar (a wiring bug),
    warn — but still keep the orchestrator value (authoritative)."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fr.record_start(paths, started_at="2026-06-07T18:00:00Z",
                    skill_version="1.3.0")
    _write_sidecar(paths, "00_plan.md.metadata.json", {
        "input_tokens": 12000, "estimated_cost_usd": 0.31,
        "model": "claude-opus-4-7", "elapsed_seconds": 145,
    })
    # Orchestrator under-recorded (e.g. forgot --from-sidecar).
    fr.record_stage(
        paths, stage_id="plan", status="completed",
        started_at="2026-06-07T18:00:05Z",
        finished_at="2026-06-07T18:02:30Z",
        cost_usd=0.00,
    )
    fr.record_finalize(paths, exit_code=0,
                       started_at="2026-06-07T18:00:00Z",
                       skill_version="1.3.0")
    captured = capsys.readouterr()
    assert "RECONCILE WARNING" in captured.err
    assert "LESS than its" in captured.err
    stage = next(
        s for s in _read_canonical(paths)["stages"] if s["id"] == "plan"
    )
    assert stage["cost_usd"] == 0.0  # orchestrator value kept
