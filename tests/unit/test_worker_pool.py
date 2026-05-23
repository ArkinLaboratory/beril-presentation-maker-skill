"""Tests for tools/worker_pool.sh — the v0.4 M3 bounded-concurrency
batch runner that drives parallel per-substory slide composition.

worker_pool.sh is a sourceable bash library (functions only, no
side effects). These tests source it inside a throwaway bash harness
and exercise `wp_run_pool` with stub runner functions, asserting:

  - concurrency: jobs within a batch overlap (wall-clock ~= 1x, not Nx);
  - the MAX cap is enforced (batching — N>MAX takes multiple batches);
  - exit-code collection: a failing job makes the pool return non-zero;
  - per-job log capture: failed jobs' logs are preserved + non-empty,
    passing jobs' logs are removed;
  - usage errors (bad MAX, undefined runner, too few args) return rc 2.

The pool is the wall-clock win of the v0.4 pivot (V0_4_0_PUNCH_LIST C1);
its correctness under `set -euo pipefail` is the load-bearing risk
(M3_PUNCH_LIST.md DQ2), so it is tested in isolation.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import pytest

WORKER_POOL_SH = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools/worker_pool.sh"
)


def _run_harness(
    tmp_path: Path,
    *,
    runner_body: str,
    runner_name: str,
    max_workers: int,
    ids: list[str],
    label: str = "job",
    logdir: Path | None = None,
) -> tuple[int, float, str, str, Path]:
    """Source worker_pool.sh in a bash harness, define a stub runner,
    call wp_run_pool, and return (pool_rc, elapsed_s, stdout, stderr,
    logdir). pool_rc is parsed from a ``POOL_RC=<n>`` marker so the
    harness can exit 0 even when the pool reports failure.
    """
    if logdir is None:
        logdir = tmp_path / "logs"
    harness = tmp_path / "harness.sh"
    id_args = " ".join(ids)
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'source "{WORKER_POOL_SH}"\n'
        f"{runner_body}\n"
        f'if wp_run_pool {max_workers} "{logdir}" "{label}" '
        f"{runner_name} {id_args}; then\n"
        '  echo "POOL_RC=0"\n'
        "else\n"
        '  echo "POOL_RC=$?"\n'
        "fi\n"
    )
    start = time.monotonic()
    proc = subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - start
    m = re.search(r"POOL_RC=(\d+)", proc.stdout)
    # No marker → the harness aborted before the pool returned (e.g. a
    # usage error under set -e); fall back to the process exit code.
    pool_rc = int(m.group(1)) if m else proc.returncode
    return pool_rc, elapsed, proc.stdout, proc.stderr, logdir


# A runner that sleeps 1s then succeeds — the timing probe.
_SLEEP_OK = 'sleeper() { sleep 1; echo "ran $1"; }'

# A runner that sleeps briefly, fails for id "BAD", else succeeds.
_SLEEP_MAYBE_FAIL = (
    'maybe() { sleep 0.3; '
    'if [[ "$1" == BAD ]]; then echo "boom $1" >&2; return 7; fi; '
    'echo "ok $1"; }'
)


def test_concurrency_jobs_overlap(tmp_path: Path) -> None:
    """4 one-second jobs with max=5 finish in ~1s, not ~4s."""
    rc, elapsed, _out, _err, _logs = _run_harness(
        tmp_path,
        runner_body=_SLEEP_OK,
        runner_name="sleeper",
        max_workers=5,
        ids=["S1", "S2", "S3", "S4"],
    )
    assert rc == 0
    # Sequential would be ~4s; parallel is ~1s + spawn overhead.
    assert elapsed < 2.5, f"jobs did not overlap (elapsed {elapsed:.2f}s)"


def test_batching_respects_max(tmp_path: Path) -> None:
    """4 one-second jobs with max=2 run as two batches: ~2s, not ~1s."""
    rc, elapsed, _out, _err, _logs = _run_harness(
        tmp_path,
        runner_body=_SLEEP_OK,
        runner_name="sleeper",
        max_workers=2,
        ids=["S1", "S2", "S3", "S4"],
    )
    assert rc == 0
    # Two batches of 2 → >~2s. If the cap were ignored, all 4 would run
    # at once (~1s); if fully sequential, ~4s.
    assert 1.7 < elapsed < 3.8, f"batching not enforced (elapsed {elapsed:.2f}s)"


def test_all_jobs_pass(tmp_path: Path) -> None:
    rc, _elapsed, _out, _err, logdir = _run_harness(
        tmp_path,
        runner_body=_SLEEP_MAYBE_FAIL,
        runner_name="maybe",
        max_workers=5,
        ids=["S1", "S2", "S3"],
    )
    assert rc == 0
    # Every job passed → every log removed.
    assert list(logdir.glob("*.log")) == []


def test_one_failure_fails_the_pool(tmp_path: Path) -> None:
    """A single failing job makes wp_run_pool return non-zero."""
    rc, _elapsed, _out, _err, _logs = _run_harness(
        tmp_path,
        runner_body=_SLEEP_MAYBE_FAIL,
        runner_name="maybe",
        max_workers=5,
        ids=["S1", "BAD", "S3"],
    )
    assert rc == 1, "pool must return non-zero when any job fails"


def test_failed_log_preserved_passing_removed(tmp_path: Path) -> None:
    """Failed jobs keep their log; passing jobs have theirs cleaned up."""
    _rc, _elapsed, _out, _err, logdir = _run_harness(
        tmp_path,
        runner_body=_SLEEP_MAYBE_FAIL,
        runner_name="maybe",
        max_workers=5,
        ids=["S1", "BAD", "S3"],
        label="slide_compose",
    )
    logs = {p.name for p in logdir.glob("*.log")}
    assert logs == {"slide_compose-BAD.log"}, f"unexpected logs: {logs}"
    # The preserved log captured the failing runner's stderr.
    bad_log = (logdir / "slide_compose-BAD.log").read_text()
    assert "boom BAD" in bad_log


def test_failed_job_output_echoed_to_stderr(tmp_path: Path) -> None:
    """A failed job's captured output is surfaced (indented) on stderr."""
    _rc, _elapsed, _out, err, _logs = _run_harness(
        tmp_path,
        runner_body=_SLEEP_MAYBE_FAIL,
        runner_name="maybe",
        max_workers=5,
        ids=["BAD"],
    )
    assert "boom BAD" in err
    assert "FAILED (exit 7)" in err


def test_empty_id_list_is_a_noop(tmp_path: Path) -> None:
    rc, _elapsed, _out, _err, _logs = _run_harness(
        tmp_path,
        runner_body=_SLEEP_OK,
        runner_name="sleeper",
        max_workers=5,
        ids=[],
    )
    assert rc == 0


def test_bad_max_is_usage_error(tmp_path: Path) -> None:
    rc, _elapsed, _out, _err, _logs = _run_harness(
        tmp_path,
        runner_body=_SLEEP_OK,
        runner_name="sleeper",
        max_workers="notanumber",  # type: ignore[arg-type]
        ids=["S1"],
    )
    assert rc == 2


def test_undefined_runner_is_usage_error(tmp_path: Path) -> None:
    rc, _elapsed, _out, _err, _logs = _run_harness(
        tmp_path,
        runner_body="# no runner defined",
        runner_name="does_not_exist",
        max_workers=5,
        ids=["S1"],
    )
    assert rc == 2
