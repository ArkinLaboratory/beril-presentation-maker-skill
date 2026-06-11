"""C1-B tests: the stage-output completion guard (rc==0 != completion).

stream_progress.py verifies a Write tool-USE event fired — NOT that the
artifact landed on disk. The draft_4 qa_prep failure emitted a Write
event (rc=0) yet the `{"status":"in_progress"}` sentinel survived, so the
deck shipped a missing stage. `_verify_stage_output` (called from
invoke_claude_with_retry after a claimed-success invoke) closes that gap:
a surviving sentinel or a stale mtime is a HARD FAIL with retry, not a
pass.

Harness: extract claim_file + _mtime_epoch + _verify_stage_output +
invoke_claude_with_retry from presentation_maker.sh, run them in a fresh
bash subshell with a STUBBED invoke_claude that simulates each failure
mode. (Same extract-and-exec pattern as the other orchestrator tests.)
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def _extract_func(text: str, name: str) -> str:
    """Pull a bash `name() { ... }` body out of the orchestrator source.
    Function bodies end at a `^}` at column 0."""
    start = text.find(f"{name}() {{")
    assert start >= 0, f"could not locate {name} in {ORCH_SH}"
    end = text.find("\n}\n", start) + 2
    return text[start:end]


def _harness(stub_invoke_claude: str) -> str:
    """Build a runnable snippet: the real guard functions + retry wrapper,
    a stubbed invoke_claude, MAX=2 for speed."""
    text = ORCH_SH.read_text(encoding="utf-8")
    claim = _extract_func(text, "claim_file")
    mtime = _extract_func(text, "_mtime_epoch")
    verify = _extract_func(text, "_verify_stage_output")
    retry = _extract_func(text, "invoke_claude_with_retry")
    # MAX=3 → 2 to keep the test fast (still exercises the retry loop).
    retry = retry.replace("local MAX=3", "local MAX=2")
    return textwrap.dedent("""\
        set -uo pipefail
        {claim}
        {mtime}
        {verify}
        {stub}
        {retry}
        """).format(claim=claim, mtime=mtime, verify=verify,
                    stub=stub_invoke_claude, retry=retry)


def _run(snippet: str, expected_path: str):
    wrapper = snippet + (
        f'\ninvoke_claude_with_retry "sys" "user" "{expected_path}" "qa_prep"\n'
        'echo "WRAPPER_RC=$?"\n'
    )
    return subprocess.run(["bash", "-c", wrapper],
                          capture_output=True, text=True, timeout=30)


def _rc(out: str) -> int:
    for line in out.splitlines():
        if line.startswith("WRAPPER_RC="):
            return int(line.split("=", 1)[1])
    raise AssertionError(f"no WRAPPER_RC in output: {out!r}")


# ---------------------------------------------------------------------------
# Silent-Write: invoke_claude returns 0 but leaves the sentinel → hard fail
# ---------------------------------------------------------------------------

def test_silent_write_sentinel_survives_hard_fails_with_retry(tmp_path):
    out = tmp_path / "qa_prep.json"
    # Stub: returns 0 WITHOUT writing real content (claim_file already put
    # the in_progress sentinel there; this simulates a Write EVENT that
    # didn't land).
    stub = "invoke_claude() { return 0; }"
    r = _run(_harness(stub), str(out))
    assert _rc(r.stdout) == 1, (
        f"a surviving sentinel must hard-fail the wrapper.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}")
    # the guard surfaced the sentinel diagnosis (loud), and it RETRIED
    assert "sentinel survived" in r.stderr
    assert "output verification failed" in r.stderr  # retry message


def test_real_write_passes(tmp_path):
    out = tmp_path / "qa_prep.json"
    # Stub: writes real (non-sentinel) content + returns 0.
    stub = (
        'invoke_claude() { '
        'echo \'{"qa": ["real content"]}\' > "$3"; return 0; }'
    )
    r = _run(_harness(stub), str(out))
    assert _rc(r.stdout) == 0, (
        f"a real write must pass.\nstdout={r.stdout}\nstderr={r.stderr}")
    assert out.read_text().strip().startswith('{"qa"')


def test_write_then_recovers_on_retry(tmp_path):
    out = tmp_path / "qa_prep.json"
    marker = tmp_path / "attempted"
    # Stub: first attempt leaves the sentinel (no write); second attempt
    # writes real content. Proves the guard RETRIES rather than failing
    # outright, and recovers when the artifact finally lands.
    stub = (
        'invoke_claude() { '
        f'if [ -f "{marker}" ]; then echo \'{{"qa":["ok"]}}\' > "$3"; '
        f'else touch "{marker}"; fi; return 0; }}'
    )
    r = _run(_harness(stub), str(out))
    assert _rc(r.stdout) == 0, (
        f"guard must recover when the retry lands the artifact.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}")
    assert out.read_text().strip().startswith('{"qa"')


# ---------------------------------------------------------------------------
# Source-level pins (the guard is wired into the shared chokepoint)
# ---------------------------------------------------------------------------

def test_guard_is_wired_into_retry_wrapper():
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "_verify_stage_output" in text, (
        "C1-B: _verify_stage_output helper must exist")
    # called from the retry wrapper on the rc==0 branch
    retry = _extract_func(text, "invoke_claude_with_retry")
    assert "_verify_stage_output" in retry, (
        "C1-B: invoke_claude_with_retry must call _verify_stage_output on "
        "the rc==0 branch (every artifact-writing stage uses this wrapper, "
        "so the guard generalizes)")
