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
        # v0.8.0 forwarded flags
        "prompts_version": None,
        "force_v3_smoke_stale": False,
        "architecture_pipeline": None,
        "resume_from": None,
        "draft_dir": None,
        "revise_severity_floor": None,
        "visual_qa": False,
        "no_visual_qa": False,
        "image_provider": None,
        "max_image_approvals": None,
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


# ---------------------------------------------------------------------------
# v0.8.0: forwarded flags (--prompts-version + the rest of the v0.5/v0.6/
# v0.7/v0.8 surface previously dropped by the Python wrapper)
# ---------------------------------------------------------------------------

def _capture_argv(fake_beril_root, monkeypatch, **arg_overrides):
    """Helper: run draft.run() with patched subprocess.run; return
    the argv list passed to bash."""
    monkeypatch.delenv("BERIL_ROOT", raising=False)
    monkeypatch.chdir(fake_beril_root)
    captured = []

    def fake_run(argv, **kwargs):
        captured.extend(argv)

        class _Result:
            returncode = 0
        return _Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = draft.run(_args(**arg_overrides))
    assert rc == 0
    return captured


def test_forwards_prompts_version(fake_beril_root, monkeypatch):
    """v0.8.0 release-blocker: --prompts-version must reach the
    shell orchestrator. Pre-v0.8.0, the wrapper silently dropped
    this flag, causing a silent v2 downgrade on the documented
    invocation path."""
    argv = _capture_argv(
        fake_beril_root, monkeypatch, prompts_version="v3.3"
    )
    assert "--prompts-version" in argv
    idx = argv.index("--prompts-version")
    assert argv[idx + 1] == "v3.3"


def test_omits_prompts_version_when_unset(fake_beril_root, monkeypatch):
    """When --prompts-version is unset the wrapper must not pass
    it to the shell (preserving the shell's own default; don't
    force v2 from the Python side)."""
    argv = _capture_argv(fake_beril_root, monkeypatch)
    assert "--prompts-version" not in argv


def test_forwards_force_v3_smoke_stale(fake_beril_root, monkeypatch):
    """The D-076 smoke-gate bypass must be forwardable through the
    wrapper (otherwise the wrapper can't be used when the operator
    has freshly edited prompts)."""
    argv = _capture_argv(
        fake_beril_root, monkeypatch, force_v3_smoke_stale=True
    )
    assert "--force-v3-smoke-stale" in argv


def test_forwards_resume_from_and_draft_dir(
    fake_beril_root, monkeypatch, tmp_path
):
    """Resume mechanism must be forwardable. Both --resume-from
    and --draft-dir reach the shell."""
    draft_dir = tmp_path / "talks" / "draft_1"
    argv = _capture_argv(
        fake_beril_root, monkeypatch,
        resume_from="slide_compose",
        draft_dir=str(draft_dir),
    )
    assert "--resume-from" in argv
    assert argv[argv.index("--resume-from") + 1] == "slide_compose"
    assert "--draft-dir" in argv
    assert argv[argv.index("--draft-dir") + 1] == str(draft_dir)


def test_forwards_architecture_pipeline(fake_beril_root, monkeypatch):
    argv = _capture_argv(
        fake_beril_root, monkeypatch, architecture_pipeline="v0_4"
    )
    assert "--architecture-pipeline" in argv
    idx = argv.index("--architecture-pipeline")
    assert argv[idx + 1] == "v0_4"


def test_forwards_revise_severity_floor(fake_beril_root, monkeypatch):
    """v0.8 G.6: --revise-severity-floor must be forwardable so
    operators can override the v0.8 default of P1."""
    argv = _capture_argv(
        fake_beril_root, monkeypatch, revise_severity_floor="P0"
    )
    assert "--revise-severity-floor" in argv
    idx = argv.index("--revise-severity-floor")
    assert argv[idx + 1] == "P0"


def test_forwards_visual_qa_flags(fake_beril_root, monkeypatch):
    """D-096: both --visual-qa and --no-visual-qa must be
    forwardable (the shell's mode-aware default-on can be
    overridden in either direction)."""
    argv_on = _capture_argv(
        fake_beril_root, monkeypatch, visual_qa=True
    )
    assert "--visual-qa" in argv_on
    argv_off = _capture_argv(
        fake_beril_root, monkeypatch, no_visual_qa=True
    )
    assert "--no-visual-qa" in argv_off


def test_forwards_image_provider_and_max_approvals(
    fake_beril_root, monkeypatch
):
    """M5b D-062 image-provider override + D-088 max-approvals cap
    must be forwardable."""
    argv = _capture_argv(
        fake_beril_root, monkeypatch,
        image_provider="google-ai-studio",
        max_image_approvals=8,
    )
    assert "--image-provider" in argv
    assert argv[argv.index("--image-provider") + 1] == "google-ai-studio"
    assert "--max-image-approvals" in argv
    assert argv[argv.index("--max-image-approvals") + 1] == "8"


def test_all_forwarded_flags_omitted_when_unset(
    fake_beril_root, monkeypatch
):
    """Sanity: with default _args() the wrapper passes none of the
    new v0.8.0 flags to bash. This pin prevents accidental defaults
    leaking through the wrapper (which would override shell-side
    defaults like the v0.8 P1 severity floor)."""
    argv = _capture_argv(fake_beril_root, monkeypatch)
    for flag in (
        "--prompts-version",
        "--force-v3-smoke-stale",
        "--architecture-pipeline",
        "--resume-from",
        "--draft-dir",
        "--revise-severity-floor",
        "--visual-qa",
        "--no-visual-qa",
        "--image-provider",
        "--max-image-approvals",
    ):
        assert flag not in argv, (
            f"{flag} must not appear when its arg is unset; would "
            f"force a non-default value through the wrapper"
        )
