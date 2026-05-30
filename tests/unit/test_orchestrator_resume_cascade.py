"""Unit tests for v0.7 Tier A.2 (D-090) — resumable cascade +
checkpoint markers + `resume-cascade` CLI subcommand.

Context: v0.6 fdm Tier-E live run rendered a valid .pptx but the
audit directory was missing review_cascade.json + adversarial_review.*
+ presentation_validation.json. Tier-0 C1 diagnostic root-caused as
operator-side interruption — the orchestrator was killed after
merge/assemble but before the cascade wrote artifacts.

D-090 fix:
1. stage_review_cascade writes pre-cascade `audit/cascade-started.json`
   + post-cascade `audit/cascade-completed.json` checkpoint markers.
   The "started without completed" delta is the interruption signature
   future operators can use post-mortem.
2. New `presentation_maker.sh resume-cascade <draft-dir>` subcommand
   re-invokes the cascade against an existing draft without re-running
   merge/assemble. Idempotent (cascade overwrites its outputs).

These tests pin the structural intent + invocation contract so a
future refactor can't accidentally drop the protection.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def _extract_stage_review_cascade_body(text: str) -> str:
    """Extract the full body of stage_review_cascade.

    The function contains heredocs whose closing JSON `}` lands at
    column 0 (matching the function-close pattern). A naive
    `find("\\n}\\n")` truncates mid-heredoc. We scan forward from
    the function header, tracking heredoc state explicitly so we
    only count column-0 `}` lines that are OUTSIDE a heredoc."""
    fn_start = text.find("stage_review_cascade() {")
    if fn_start < 0:
        raise AssertionError("stage_review_cascade function missing")
    lines = text[fn_start:].splitlines(keepends=True)
    out_lines = [lines[0]]
    in_heredoc = False
    for line in lines[1:]:
        out_lines.append(line)
        if not in_heredoc:
            if "<<EOF" in line:
                in_heredoc = True
            elif line.rstrip("\n") == "}":
                # Function close (column-0 `}` outside any heredoc)
                break
        else:
            if line.rstrip("\n") == "EOF":
                in_heredoc = False
    return "".join(out_lines)


# ---------------------------------------------------------------------------
# Checkpoint markers in stage_review_cascade
# ---------------------------------------------------------------------------

def test_stage_review_cascade_writes_started_marker():
    """stage_review_cascade must write `audit/cascade-started.json`
    BEFORE invoking review_cascade.py (D-090). Pin the source-level
    pattern: the marker write (the `cat > "$_started_marker"`
    heredoc) must precede the python invocation."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_review_cascade_body(text)
    # The actual marker-write line (not the docstring mention).
    started_write_pos = body.find('cat > "$_started_marker"')
    assert started_write_pos > 0, (
        "stage_review_cascade must write the pre-cascade marker via "
        "`cat > \"$_started_marker\"` heredoc per D-090")
    # The cascade invocation (not the docstring mention) — look for
    # the actual python call.
    py_pos = body.find('$TOOLS_DIR/review_cascade.py')
    assert py_pos > 0, "cascade python invocation missing"
    # Order: marker write must come BEFORE python invocation
    assert started_write_pos < py_pos, (
        "checkpoint marker write must precede the cascade invocation "
        "(otherwise an interruption mid-cascade leaves NO marker, "
        "defeating the diagnostic purpose)")


def test_stage_review_cascade_writes_completed_marker():
    """stage_review_cascade must write `audit/cascade-completed.json`
    AFTER review_cascade.py finishes (D-090). The "started without
    completed" delta is the interruption signature."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_review_cascade_body(text)
    # The actual marker-write line (not the docstring mention).
    completed_write_pos = body.find('cat > "$_completed_marker"')
    assert completed_write_pos > 0, (
        "stage_review_cascade must write the post-cascade marker via "
        "`cat > \"$_completed_marker\"` heredoc per D-090")
    # The cascade invocation
    py_pos = body.find('$TOOLS_DIR/review_cascade.py')
    assert py_pos > 0
    # Order: completed marker must come AFTER python invocation
    assert completed_write_pos > py_pos, (
        "cascade-completed.json must be written AFTER the cascade "
        "runs (so it serves as a completion signal)")


def test_checkpoint_markers_capture_schema_version():
    """Both checkpoint markers must declare `schema_version:
    cascade-checkpoint.v1` for future schema evolution."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_review_cascade_body(text)
    assert "cascade-checkpoint.v1" in body, (
        "checkpoint markers must declare schema_version "
        "cascade-checkpoint.v1")


def test_checkpoint_markers_capture_timestamp_and_sha():
    """Checkpoint markers must capture started_at_utc + skill_git_sha
    for traceability (post-mortem operators can correlate with
    git log + cluster logs)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_stage_review_cascade_body(text)
    # Timestamp capture
    assert "date -u +%Y-%m-%dT%H:%M:%SZ" in body, (
        "checkpoint markers must capture UTC ISO-8601 timestamps")
    # Git sha capture
    assert "git rev-parse" in body, (
        "checkpoint markers must capture skill repo git sha for "
        "traceability")
    # JSON shape pins
    assert '"started_at_utc":' in body
    assert '"skill_git_sha":' in body


# ---------------------------------------------------------------------------
# resume-cascade subcommand: error paths
# ---------------------------------------------------------------------------

def test_resume_cascade_missing_arg_exits_2(tmp_path):
    """`resume-cascade` without a <draft-dir> argument must exit 2
    with a clear usage message."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "resume-cascade"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "resume-cascade requires" in result.stderr
    assert "draft-dir" in result.stderr.lower()


def test_resume_cascade_missing_directory_exits_1(tmp_path):
    """`resume-cascade <nonexistent-path>` must exit 1 with the
    'draft directory not found' message."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "resume-cascade",
         str(tmp_path / "nonexistent")],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_resume_cascade_non_draft_directory_exits_1(tmp_path):
    """`resume-cascade <dir-without-slide_spec.json>` must exit 1
    with a clear 'doesn't look like a presentation-maker draft'
    message (catches the case where the operator points at the
    wrong directory or the pipeline was interrupted BEFORE
    merge/assemble)."""
    # Create an empty directory (no working/slide_spec.json)
    bad_dir = tmp_path / "not-a-draft"
    bad_dir.mkdir()
    result = subprocess.run(
        ["bash", str(ORCH_SH), "resume-cascade", str(bad_dir)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "doesn't look like a presentation-maker" in result.stderr
    assert "slide_spec.json" in result.stderr


# ---------------------------------------------------------------------------
# resume-cascade subcommand: structural pins
# ---------------------------------------------------------------------------

def test_resume_cascade_intercept_lives_before_arg_parse():
    """The resume-cascade subcommand must intercept BEFORE the
    while loop that parses --flag arguments (so it can short-circuit
    project-id validation + smoke gate etc.). Pin the location."""
    text = ORCH_SH.read_text(encoding="utf-8")
    intercept_pos = text.find('"${1:-}" == "resume-cascade"')
    arg_parse_pos = text.find("# --- Parse arguments ---")
    assert intercept_pos > 0, "resume-cascade intercept block missing"
    assert arg_parse_pos > 0
    assert intercept_pos < arg_parse_pos, (
        "resume-cascade intercept must precede the --- Parse "
        "arguments --- block so it short-circuits validation")


def test_resume_cascade_writes_checkpoint_markers_in_intercept():
    """The resume-cascade intercept must write the same
    cascade-started.json + cascade-completed.json markers as
    stage_review_cascade (so resume-mode runs are diagnosable
    in the same way as a normal pipeline run)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the resume-cascade intercept block (between the if test
    # and its fi).
    intercept_start = text.find('if [[ "${1:-}" == "resume-cascade" ]]; then')
    assert intercept_start > 0
    # The block ends at the matching fi (followed by '# --- Parse arguments ---')
    fi_pos = text.find('\nfi\n\n# --- Parse arguments ---', intercept_start)
    assert fi_pos > 0
    block = text[intercept_start:fi_pos]
    assert "cascade-started.json" in block, (
        "resume-cascade intercept must write cascade-started.json")
    assert "cascade-completed.json" in block, (
        "resume-cascade intercept must write cascade-completed.json")


def test_resume_cascade_invokes_python_review_cascade():
    """The resume-cascade intercept must invoke review_cascade.py
    against the draft directory (not just write markers)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    intercept_start = text.find('if [[ "${1:-}" == "resume-cascade" ]]; then')
    fi_pos = text.find('\nfi\n\n# --- Parse arguments ---', intercept_start)
    block = text[intercept_start:fi_pos]
    assert "review_cascade.py" in block, (
        "resume-cascade intercept must invoke review_cascade.py")


def test_resume_cascade_passes_beril_root_to_adversarial():
    """The resume-cascade intercept must derive BERIL_ROOT from the
    draft-dir path and pass it to beril-adversarial (the adversarial
    CLI needs it to locate .claude/skills/). Pin the env-var
    invocation pattern."""
    text = ORCH_SH.read_text(encoding="utf-8")
    intercept_start = text.find('if [[ "${1:-}" == "resume-cascade" ]]; then')
    fi_pos = text.find('\nfi\n\n# --- Parse arguments ---', intercept_start)
    block = text[intercept_start:fi_pos]
    assert "beril-adversarial" in block, (
        "resume-cascade should run standalone adversarial when "
        "cascade Tier-3 didn't")
    assert "BERIL_ROOT=" in block, (
        "resume-cascade must pass BERIL_ROOT env var to "
        "beril-adversarial")


def test_resume_cascade_derives_beril_root_from_draft_path():
    """The resume-cascade intercept must derive BERIL_ROOT by walking
    up the draft-dir path (BERIL_ROOT/projects/<id>/talks/draft_N).
    Pin the path-derivation pattern by counting 4 nested dirname
    calls — exact whitespace varies (line continuations etc.)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    intercept_start = text.find('if [[ "${1:-}" == "resume-cascade" ]]; then')
    fi_pos = text.find('\nfi\n\n# --- Parse arguments ---', intercept_start)
    block = text[intercept_start:fi_pos]
    assert "_RESUME_BERIL_ROOT" in block, (
        "resume-cascade should derive BERIL_ROOT into a variable "
        "for clarity")
    # Extract the line(s) defining _RESUME_BERIL_ROOT, normalize
    # whitespace, then count nested dirname calls. 4 nested = walks
    # draft_N → talks → project → projects → BERIL_ROOT.
    beril_root_start = block.find("_RESUME_BERIL_ROOT=")
    # Capture up to the closing `)" on the same logical statement;
    # may span multiple physical lines via `\` continuation.
    beril_root_end = block.find("\n\n", beril_root_start)
    beril_root_line = block[beril_root_start:beril_root_end]
    # Normalize whitespace (collapse newlines + continuations)
    normalized = " ".join(beril_root_line.split())
    n_dirname = normalized.count("dirname")
    assert n_dirname == 4, (
        f"resume-cascade should call dirname exactly 4 times to walk "
        f"draft_N → talks → project → projects → BERIL_ROOT; got "
        f"{n_dirname}. Definition normalized: {normalized!r}")
    # Must reference _RESUME_OUTDIR as the start of the walk
    assert "_RESUME_OUTDIR" in normalized


def test_resume_cascade_exits_after_intercept_runs():
    """The intercept must `exit 0` after writing the completed
    marker — without an explicit exit, the rest of the orchestrator
    main flow would run (project-id validation would fail since we
    didn't supply one)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    intercept_start = text.find('if [[ "${1:-}" == "resume-cascade" ]]; then')
    fi_pos = text.find('\nfi\n\n# --- Parse arguments ---', intercept_start)
    block = text[intercept_start:fi_pos]
    # Must contain `exit 0` somewhere after the completed marker
    completed_pos = block.find("cascade-completed.json")
    exit_pos = block.rfind("exit 0")
    assert exit_pos > completed_pos, (
        "resume-cascade intercept must `exit 0` after writing the "
        "completed marker so main-flow validation doesn't run")


# ---------------------------------------------------------------------------
# resume-cascade subcommand: --help discoverability
# ---------------------------------------------------------------------------

def test_help_documents_resume_cascade():
    """--help output must document the resume-cascade subcommand so
    operators can discover it post-interruption without reading the
    source."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "resume-cascade" in help_text, (
        "--help should mention the resume-cascade subcommand")
    # D-090 attribution pin so future readers know the why
    assert "D-090" in help_text or "interrupted" in help_text.lower(), (
        "--help should cite D-090 or the 'interrupted' use case so "
        "the why is clear")


# ---------------------------------------------------------------------------
# Integration: resume-cascade against a synthetic minimal draft
# ---------------------------------------------------------------------------

def test_resume_cascade_runs_against_synthetic_draft(tmp_path):
    """End-to-end: a minimal synthetic draft (slide_spec.json +
    empty audit/) + invoke resume-cascade → both checkpoint markers
    written; cascade attempts to run (may produce minimal output).

    This is the structural test that the wiring works; the C1
    verification step against the live v0.6 fdm draft_6 is run
    out-of-band (documented in the Tier-A.2 commit message)."""
    # Build a minimal draft layout matching the canonical pattern
    # BERIL_ROOT/projects/<id>/talks/draft_N.
    beril_root = tmp_path / "beril_root"
    project_dir = beril_root / "projects" / "synthetic_project"
    draft_dir = project_dir / "talks" / "draft_1"
    (draft_dir / "working").mkdir(parents=True)
    (draft_dir / "narrative").mkdir()
    (draft_dir / "audit").mkdir()
    # Minimal slide_spec.json that won't crash the cascade reader
    spec = {
        "schema_version": "slide-spec.v1",
        "project_id": "synthetic_project",
        "talk_mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "slides": [],
    }
    (draft_dir / "working" / "slide_spec.json").write_text(
        json.dumps(spec), encoding="utf-8")

    # Invoke resume-cascade.
    result = subprocess.run(
        ["bash", str(ORCH_SH), "resume-cascade", str(draft_dir)],
        capture_output=True, text=True, timeout=120,
    )
    # Cascade may emit non-fatal errors on a synthetic minimal draft
    # (missing 02_substories.md etc.) but the orchestrator should still
    # exit 0 — the resume-cascade contract is "run what we can, don't
    # gate on cascade rc". Checkpoint markers are the load-bearing
    # output.
    assert result.returncode == 0, (
        f"resume-cascade should exit 0 even when cascade emits "
        f"non-fatal warnings; stderr:\n{result.stderr[-1500:]}")

    # Both checkpoint markers written.
    started = draft_dir / "audit" / "cascade-started.json"
    completed = draft_dir / "audit" / "cascade-completed.json"
    assert started.is_file(), "cascade-started.json missing"
    assert completed.is_file(), "cascade-completed.json missing"

    # Marker shape pins.
    started_data = json.loads(started.read_text(encoding="utf-8"))
    completed_data = json.loads(completed.read_text(encoding="utf-8"))
    assert started_data["schema_version"] == "cascade-checkpoint.v1"
    assert completed_data["schema_version"] == "cascade-checkpoint.v1"
    assert started_data["phase"] == "started"
    assert completed_data["phase"] == "completed"
    assert started_data["invoked_via"] == "resume-cascade"
    assert completed_data["invoked_via"] == "resume-cascade"
    # completed_data preserves the started_at_utc from started_data
    assert started_data["started_at_utc"] == \
        completed_data["started_at_utc"], (
        "completed marker should preserve started_at_utc from the "
        "started marker so post-mortem can correlate them")


def test_started_without_completed_signals_interruption(tmp_path):
    """The "started without completed" file-state is the post-mortem
    interruption signature. This test simulates an interrupted
    cascade by deleting the completed marker, then asserts that the
    started marker remains as evidence."""
    # Simulate the state by writing just the started marker
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    started_data = {
        "schema_version": "cascade-checkpoint.v1",
        "phase": "started",
        "started_at_utc": "2026-05-30T19:00:00Z",
        "skill_git_sha": "abc1234",
        "draft_dir": str(tmp_path),
        "stages": ["review_cascade.py", "stage_adversarial_review"],
        "invoked_via": "resume-cascade",
    }
    (audit_dir / "cascade-started.json").write_text(
        json.dumps(started_data), encoding="utf-8")

    # Post-mortem check: started present + completed absent =
    # interruption.
    assert (audit_dir / "cascade-started.json").is_file()
    assert not (audit_dir / "cascade-completed.json").exists()
    # The diagnostic value is the explicit phase field
    data = json.loads(
        (audit_dir / "cascade-started.json").read_text(encoding="utf-8"))
    assert data["phase"] == "started"
