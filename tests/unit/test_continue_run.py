"""Tests for `beril-presentation-maker continue` (v0.3.6 --pick TLN flow).

v0.3.6 added the throughline-pick gate handoff path: bash halts cleanly
at the gate writing <draft_dir>/.handoff.json with phase=throughline_pick;
`continue --pick TLN` reads the handoff, validates the pick, runs
parse_throughline_candidates.py, and dispatches bash to resume from
substory_design. This addresses the 100% TTY-block failure for hub
participants (Claude Code auto-backgrounds bash on the hub; the previous
`read </dev/tty` fails in TTY-less contexts).

Test coverage:
- mutual exclusion of --pick and --resume-from
- helpful error when neither flag is passed and handoff is waiting
- standard error when neither flag is passed and no handoff exists
- --pick validates TLN shape, validates against handoff candidates,
  validates handoff phase
- --pick consumes the handoff (.handoff.json removed) on success
- --pick dispatches bash with --resume-from substory_design
- legacy --resume-from path still works (no regression)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "src")
)

from beril_presentation_maker.commands import continue_run  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_draft(tmp_path):
    """Build a tmp directory mirroring the BERIL_ROOT/projects/<id>/talks/draft_N
    layout that continue_run derives beril_root from (parents[3])."""
    beril_root = tmp_path / "beril-root"
    project_dir = beril_root / "projects" / "demo_project"
    talks_dir = project_dir / "talks"
    draft_dir = talks_dir / "draft_1"
    draft_dir.mkdir(parents=True)
    (draft_dir / "narrative").mkdir()
    (draft_dir / "working").mkdir()

    candidates_md = draft_dir / "working" / "00_throughline_candidates.md"
    candidates_md.write_text(
        "# Throughline candidates\n\n"
        "## Candidate TL1: First candidate label\n"
        "Body for TL1.\n\n"
        "## Candidate TL2: Second candidate label\n"
        "Body for TL2.\n\n"
        "## Candidate TL3: Third candidate label\n"
        "Body for TL3.\n",
        encoding="utf-8",
    )
    return draft_dir, candidates_md


@pytest.fixture
def fake_handoff(fake_draft):
    """Write a realistic .handoff.json into the fake draft."""
    draft_dir, candidates_md = fake_draft
    handoff = {
        "phase": "throughline_pick",
        "draft_dir": str(draft_dir),
        "candidates": [
            {"id": "TL1", "label": "First candidate label"},
            {"id": "TL2", "label": "Second candidate label"},
            {"id": "TL3", "label": "Third candidate label"},
        ],
        "candidates_md": str(candidates_md),
        "next_command": (
            f"beril-presentation-maker continue {draft_dir} --pick TLN"
        ),
    }
    (draft_dir / ".handoff.json").write_text(
        json.dumps(handoff, indent=2),
        encoding="utf-8",
    )
    return draft_dir, candidates_md, handoff


def _args_for_continue(draft_dir, **overrides):
    """Build a Namespace mirroring continue_run's argparse defaults."""
    defaults = {
        "draft_dir": str(draft_dir),
        "pick": None,
        "resume_from": None,
        "beril_root": None,
        "mode": None,
        "tier": None,
        "auto_advance": False,
        "skip_assembly": False,
        "model": None,
        "no_stream": False,
        "no_adversarial": False,
        "max_revise_cost_usd": None,
        "max_revisions": None,
        "no_images": False,
        "auto_approve_images": False,
        "image_allow_exploratory": False,
        "max_image_cost_usd": None,
        "image_style": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# _read_handoff helper
# ---------------------------------------------------------------------------


def test_read_handoff_returns_none_when_file_missing(tmp_path):
    assert continue_run._read_handoff(tmp_path) is None


def test_read_handoff_returns_none_on_corrupt_json(tmp_path):
    (tmp_path / ".handoff.json").write_text("not valid json{{{", encoding="utf-8")
    assert continue_run._read_handoff(tmp_path) is None


def test_read_handoff_returns_dict_when_valid(fake_handoff):
    draft_dir, _, _ = fake_handoff
    result = continue_run._read_handoff(draft_dir)
    assert result is not None
    assert result["phase"] == "throughline_pick"
    assert len(result["candidates"]) == 3


# ---------------------------------------------------------------------------
# _validate_pick_against_handoff helper
# ---------------------------------------------------------------------------


def test_validate_pick_invalid_shape():
    handoff = {"candidates": [{"id": "TL1", "label": "a"}]}
    ok, msg = continue_run._validate_pick_against_handoff("notTLN", handoff)
    assert not ok
    assert "TLN shape" in msg


def test_validate_pick_not_in_candidates():
    handoff = {"candidates": [
        {"id": "TL1", "label": "a"}, {"id": "TL2", "label": "b"}
    ]}
    ok, msg = continue_run._validate_pick_against_handoff("TL5", handoff)
    assert not ok
    assert "TL1" in msg and "TL2" in msg
    assert "not in" in msg.lower()


def test_validate_pick_valid_returns_label():
    handoff = {"candidates": [
        {"id": "TL1", "label": "First label"},
        {"id": "TL2", "label": "Second label"},
    ]}
    ok, msg = continue_run._validate_pick_against_handoff("TL2", handoff)
    assert ok
    assert msg == "Second label"


# ---------------------------------------------------------------------------
# run() — argument validation paths
# ---------------------------------------------------------------------------


def test_run_pick_and_resume_from_mutually_exclusive(fake_draft, capsys):
    draft_dir, _ = fake_draft
    args = _args_for_continue(draft_dir, pick="TL1", resume_from="merge")
    rc = continue_run.run(args)
    assert rc == 2
    captured = capsys.readouterr()
    assert "mutually exclusive" in captured.err


def test_run_neither_flag_without_handoff_errors_helpfully(fake_draft, capsys):
    draft_dir, _ = fake_draft
    # No .handoff.json
    args = _args_for_continue(draft_dir)
    rc = continue_run.run(args)
    assert rc == 2
    captured = capsys.readouterr()
    assert "--pick TLN" in captured.err and "--resume-from" in captured.err


def test_run_neither_flag_with_waiting_handoff_lists_candidates(
    fake_handoff, capsys
):
    """When the user runs `continue` with no flags but a handoff is waiting,
    error message should list candidates so they know what to pick."""
    draft_dir, _, _ = fake_handoff
    args = _args_for_continue(draft_dir)
    rc = continue_run.run(args)
    assert rc == 3
    captured = capsys.readouterr()
    # Lists candidates
    assert "TL1" in captured.err
    assert "TL2" in captured.err
    assert "TL3" in captured.err
    # Lists labels
    assert "First candidate label" in captured.err
    # Suggests the right command
    assert f"--pick TLN" in captured.err


# ---------------------------------------------------------------------------
# run() — --pick TLN path
# ---------------------------------------------------------------------------


def test_run_pick_without_handoff_errors(fake_draft, capsys):
    """If user passes --pick but no .handoff.json, error helpfully."""
    draft_dir, _ = fake_draft
    args = _args_for_continue(draft_dir, pick="TL1")
    rc = continue_run.run(args)
    assert rc == 3
    captured = capsys.readouterr()
    assert ".handoff.json" in captured.err
    # Suggests --resume-from for stage-replay use case
    assert "--resume-from" in captured.err


def test_run_pick_invalid_tln_shape(fake_handoff, capsys):
    draft_dir, _, _ = fake_handoff
    args = _args_for_continue(draft_dir, pick="not_a_tln")
    rc = continue_run.run(args)
    assert rc == 3
    captured = capsys.readouterr()
    assert "TLN shape" in captured.err


def test_run_pick_not_in_candidates(fake_handoff, capsys):
    draft_dir, _, _ = fake_handoff
    args = _args_for_continue(draft_dir, pick="TL99")
    rc = continue_run.run(args)
    assert rc == 3
    captured = capsys.readouterr()
    assert "TL99" in captured.err
    assert "TL1" in captured.err and "TL2" in captured.err


def test_run_pick_wrong_phase_in_handoff(fake_handoff, capsys):
    draft_dir, _, _ = fake_handoff
    # Mutate handoff to have a different phase
    handoff_path = draft_dir / ".handoff.json"
    data = json.loads(handoff_path.read_text())
    data["phase"] = "drafting"
    handoff_path.write_text(json.dumps(data), encoding="utf-8")

    args = _args_for_continue(draft_dir, pick="TL1")
    rc = continue_run.run(args)
    assert rc == 3
    captured = capsys.readouterr()
    assert "drafting" in captured.err
    assert "throughline_pick" in captured.err


def test_run_pick_valid_consumes_handoff_and_dispatches_substory_design(
    fake_handoff, capsys
):
    """The happy path: valid --pick removes .handoff.json and runs bash
    with --resume-from substory_design."""
    draft_dir, _, _ = fake_handoff

    # Mock both the parse_throughline_candidates.py invocation (called via
    # subprocess.run inside _resolve_pick_to_resume_stage) and the final
    # bash dispatch in run(). We stub both with rc=0.
    args = _args_for_continue(draft_dir, pick="TL2")

    # Mock subprocess.run to:
    #   (1) write 00_throughline.md when called with the parser script
    #   (2) return 0 for the bash dispatch
    out_path = draft_dir / "narrative" / "00_throughline.md"

    def fake_run(argv, *a, **kw):
        # First invocation: parse_throughline_candidates.py (writes the file)
        if "parse_throughline_candidates" in " ".join(str(x) for x in argv):
            out_path.write_text(
                "# Throughline TL2: Second candidate label\n", encoding="utf-8"
            )
            mock = MagicMock()
            mock.returncode = 0
            return mock
        # Second invocation: bash orchestrator dispatch — verify it received
        # --resume-from substory_design
        argv_str = " ".join(str(x) for x in argv)
        assert "--resume-from substory_design" in argv_str, argv_str
        assert str(draft_dir) in argv_str
        mock = MagicMock()
        mock.returncode = 0
        return mock

    with patch("subprocess.run", side_effect=fake_run):
        rc = continue_run.run(args)

    assert rc == 0
    # Handoff consumed
    assert not (draft_dir / ".handoff.json").exists()
    # Throughline file written (by the mocked parse step)
    assert out_path.exists()


def test_run_pick_does_not_consume_handoff_on_parse_failure(fake_handoff):
    """If parse_throughline_candidates.py fails, the handoff is NOT consumed
    so the user can retry."""
    draft_dir, _, _ = fake_handoff
    args = _args_for_continue(draft_dir, pick="TL1")

    def fake_run_fail(argv, *a, **kw):
        if "parse_throughline_candidates" in " ".join(str(x) for x in argv):
            mock = MagicMock()
            mock.returncode = 1
            return mock
        raise AssertionError(
            "bash dispatch should not be reached when parser fails"
        )

    with patch("subprocess.run", side_effect=fake_run_fail):
        rc = continue_run.run(args)

    assert rc != 0
    # Handoff still present (so user can retry)
    assert (draft_dir / ".handoff.json").exists()


# ---------------------------------------------------------------------------
# run() — legacy --resume-from path (no regression)
# ---------------------------------------------------------------------------


def test_run_resume_from_legacy_path_still_works(fake_draft):
    """v0.3.6 must not regress the v0.3.0 --resume-from <stage> mode used
    by power users for prompt iteration."""
    draft_dir, _ = fake_draft
    args = _args_for_continue(draft_dir, resume_from="merge")

    captured_argv = []

    def fake_run(argv, *a, **kw):
        captured_argv.append(argv)
        mock = MagicMock()
        mock.returncode = 0
        return mock

    with patch("subprocess.run", side_effect=fake_run):
        rc = continue_run.run(args)

    assert rc == 0
    assert len(captured_argv) == 1
    argv_str = " ".join(str(x) for x in captured_argv[0])
    assert "--resume-from merge" in argv_str
    assert str(draft_dir) in argv_str
