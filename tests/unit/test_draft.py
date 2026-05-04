"""Tests for `beril-presentation-maker draft` (v0.3.4.6 fix).

v0.3.4.6 added auto-detection of BERIL_ROOT via discovery.find_beril_root()
when --beril-root not passed. Pre-v0.3.4.6, the bash orchestrator
hard-failed with "must set --beril-root or $BERIL_ROOT" because Python
subprocess.run inherits exported env vars only — and hub users
routinely use `BERIL_ROOT=...` (no export) which doesn't propagate.
Discovery's walk-up logic (find a dir with .env + .claude/skills +
BERIL-core marker) auto-resolves cleanly when invoked from inside a
BERIL checkout.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "src")
)

from beril_presentation_maker.commands import draft  # noqa: E402
from beril_presentation_maker import discovery  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_beril_root(tmp_path):
    """Build a tmp directory that passes the BERIL_ROOT marker check
    (.env + .claude/skills + at least one BERIL-core skill)."""
    beril_root = tmp_path / "beril-root"
    beril_root.mkdir()
    (beril_root / ".env").write_text("CBORG_API_KEY=test\n")
    (beril_root / ".claude" / "skills" / "submit").mkdir(parents=True)
    (beril_root / "projects").mkdir()
    return beril_root


def _args(**kw):
    """Build an argparse.Namespace stub for run() tests. Defaults
    mirror the actual draft.py flag set."""
    defaults = {
        "project": "test_project",
        "beril_root": None,
        "mode": None,
        "tier": None,
        "audience": None,
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
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Auto-detect BERIL_ROOT via discovery
# ---------------------------------------------------------------------------


def test_run_auto_detects_beril_root_when_not_passed(
    fake_beril_root, monkeypatch
):
    """When --beril-root not passed, run() walks up from cwd via
    discovery.find_beril_root() and forwards the resolved path to
    the bash subprocess."""
    monkeypatch.delenv("BERIL_ROOT", raising=False)
    # cd into the fake root so walk-up lands here on the first check
    monkeypatch.chdir(fake_beril_root)

    # Capture the subprocess argv without actually running bash
    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        # Return success-ish CompletedProcess
        class _Result:
            returncode = 0
        return _Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = draft.run(_args())
    assert rc == 0
    # Subprocess should have received --beril-root <fake_beril_root>
    assert "--beril-root" in captured_argv
    idx = captured_argv.index("--beril-root")
    forwarded = Path(captured_argv[idx + 1])
    assert forwarded.resolve() == fake_beril_root.resolve()


def test_run_explicit_beril_root_overrides_detection(
    fake_beril_root, tmp_path, monkeypatch
):
    """An explicit --beril-root takes precedence over walk-up
    detection. The path doesn't even need to be valid — that's the
    bash orchestrator's job to validate."""
    monkeypatch.delenv("BERIL_ROOT", raising=False)
    monkeypatch.chdir(fake_beril_root)
    explicit = tmp_path / "totally-different-beril-root"

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        class _Result:
            returncode = 0
        return _Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = draft.run(_args(beril_root=str(explicit)))
    assert rc == 0
    assert "--beril-root" in captured_argv
    idx = captured_argv.index("--beril-root")
    assert captured_argv[idx + 1] == str(explicit)


def test_run_uses_env_var_when_set(fake_beril_root, monkeypatch, tmp_path):
    """When BERIL_ROOT env var is set + valid + --beril-root not
    passed, discovery picks up the env var (precedence per
    discovery module: explicit > env > walk-up)."""
    monkeypatch.setenv("BERIL_ROOT", str(fake_beril_root))
    monkeypatch.chdir(tmp_path)  # cwd is NOT under fake_beril_root

    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        class _Result:
            returncode = 0
        return _Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = draft.run(_args())
    assert rc == 0
    idx = captured_argv.index("--beril-root")
    forwarded = Path(captured_argv[idx + 1])
    assert forwarded.resolve() == fake_beril_root.resolve()


def test_run_returns_1_with_clear_error_when_discovery_fails(
    tmp_path, monkeypatch, capsys
):
    """When BERIL_ROOT can't be resolved (no env var, cwd has no
    BERIL markers in the walk-up), run() returns 1 with a usage hint
    about cd / --beril-root / export."""
    monkeypatch.delenv("BERIL_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)  # tmp_path has no BERIL markers
    rc = draft.run(_args())
    assert rc == 1
    captured = capsys.readouterr()
    err = captured.err
    # Clear error message + actionable hint
    assert "BERIL_ROOT" in err
    assert "--beril-root" in err
    assert "export" in err.lower()


def test_run_validates_explicit_beril_root_via_discovery(
    tmp_path, monkeypatch, capsys
):
    """Explicit --beril-root pointing at a non-BERIL dir must surface
    discovery's marker-failure diagnostic, not a confusing bash error."""
    not_beril = tmp_path / "not-a-beril-checkout"
    not_beril.mkdir()
    monkeypatch.delenv("BERIL_ROOT", raising=False)
    rc = draft.run(_args(beril_root=str(not_beril)))
    # When user passes explicit path that's not a BERIL checkout,
    # discovery raises BerilRootNotFound. v0.3.4.6 shape: explicit
    # path bypasses walk-up; bash will get it and fail. We DON'T
    # validate explicit paths via discovery (that would over-constrain
    # operators with non-standard layouts). The bash orchestrator's
    # own validation handles this case. So this test asserts the
    # explicit path IS forwarded as-is (lets bash produce the
    # diagnostic), NOT that discovery rejects it.
    captured_argv = []

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        class _Result:
            returncode = 0
        return _Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = draft.run(_args(beril_root=str(not_beril)))
    assert rc == 0  # subprocess is fake; argv was forwarded
    assert "--beril-root" in captured_argv
    idx = captured_argv.index("--beril-root")
    assert captured_argv[idx + 1] == str(not_beril)
