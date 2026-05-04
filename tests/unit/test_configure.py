"""Tests for `beril-presentation-maker configure` (v0.3.4.5 fixes).

Covers two fixes from the 2026-05-04 hub-install dry-run:

1. **Adversarial CLI name fix.** Pre-v0.3.4.5 checked
   `shutil.which("beril-adversarial-cli")` — that binary never
   existed. Real binary is `beril-adversarial`. Tests pin the
   correct lookup.

2. **CBORG_API_KEY resolution.** Pre-v0.3.4.5, configure didn't
   check CBORG_API_KEY despite HUB_INSTALL.md claiming it did.
   Tests pin the env-var precedence + BERIL_ROOT/.env fallback +
   never-echoes-value invariant.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "src")
)

from beril_presentation_maker.commands import configure  # noqa: E402


# ---------------------------------------------------------------------------
# CBORG_API_KEY resolver
# ---------------------------------------------------------------------------

def test_cborg_resolver_uses_shell_env(monkeypatch, tmp_path):
    """Shell $CBORG_API_KEY wins. Even when BERIL_ROOT/.env has a
    different value, the env var takes precedence."""
    monkeypatch.setenv("CBORG_API_KEY", "shell-value")
    (tmp_path / ".env").write_text("CBORG_API_KEY=env-file-value\n")
    status = configure._resolve_cborg_api_key_status(tmp_path)
    assert status["found"] is True
    assert "shell env" in status["source"]


def test_cborg_resolver_falls_back_to_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    (tmp_path / ".env").write_text("CBORG_API_KEY=env-file-value\n")
    status = configure._resolve_cborg_api_key_status(tmp_path)
    assert status["found"] is True
    assert ".env" in status["source"]


def test_cborg_resolver_handles_quoted_values(monkeypatch, tmp_path):
    """`.env` files may quote values. Both " and ' should work."""
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    (tmp_path / ".env").write_text('CBORG_API_KEY="quoted-value"\n')
    status = configure._resolve_cborg_api_key_status(tmp_path)
    assert status["found"] is True

    (tmp_path / ".env").write_text("CBORG_API_KEY='single-quoted'\n")
    status2 = configure._resolve_cborg_api_key_status(tmp_path)
    assert status2["found"] is True


def test_cborg_resolver_ignores_comments_and_blanks(monkeypatch, tmp_path):
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "# CBORG_API_KEY=commented-out\n"
        "\n"
        "  \n"
        "OTHER_VAR=foo\n"
        "CBORG_API_KEY=actual\n"
    )
    status = configure._resolve_cborg_api_key_status(tmp_path)
    assert status["found"] is True


def test_cborg_resolver_treats_empty_value_as_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    (tmp_path / ".env").write_text("CBORG_API_KEY=\n")
    status = configure._resolve_cborg_api_key_status(tmp_path)
    assert status["found"] is False


def test_cborg_resolver_no_env_no_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    # tmp_path has no .env file
    status = configure._resolve_cborg_api_key_status(tmp_path)
    assert status["found"] is False
    assert status["source"] == ""


def test_cborg_resolver_no_beril_root(monkeypatch):
    """beril_root=None should still check shell env, then return
    not-found without crashing on the missing path."""
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    status = configure._resolve_cborg_api_key_status(None)
    assert status["found"] is False


def test_cborg_resolver_with_only_shell_no_beril_root(monkeypatch):
    monkeypatch.setenv("CBORG_API_KEY", "shell-value")
    status = configure._resolve_cborg_api_key_status(None)
    assert status["found"] is True
    assert "shell env" in status["source"]


def test_cborg_resolver_never_echoes_value(monkeypatch, tmp_path):
    """Critical: the resolver must never include the actual key
    value in its return dict. Per feedback_secret_file_handling.md,
    secret values must never be in any output the configure command
    prints. The dict's "source" field describes WHERE it was found,
    not WHAT was found."""
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    secret = "supersecret-key-12345"
    (tmp_path / ".env").write_text(f"CBORG_API_KEY={secret}\n")
    status = configure._resolve_cborg_api_key_status(tmp_path)
    # The secret value must not appear anywhere in the returned status
    for v in status.values():
        if isinstance(v, str):
            assert secret not in v, f"secret leaked into status: {v!r}"
        elif isinstance(v, bool):
            pass
        else:
            # No other field types should exist
            assert False, f"unexpected status field type: {type(v)}"


def test_cborg_resolver_handles_unreadable_env_file(monkeypatch, tmp_path):
    """Permission-denied / IO-error on .env should not crash configure."""
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("CBORG_API_KEY=value\n")
    env_file.chmod(0)  # remove all permissions
    try:
        status = configure._resolve_cborg_api_key_status(tmp_path)
        # On the rare filesystems that grant root effective perms or where
        # chmod 0 doesn't actually deny access, found may still be True.
        # The critical invariant: no crash.
        assert isinstance(status, dict)
        assert "found" in status
    finally:
        env_file.chmod(0o644)  # restore for cleanup


# ---------------------------------------------------------------------------
# Adversarial CLI lookup name
# ---------------------------------------------------------------------------

def test_adversarial_cli_uses_correct_binary_name():
    """The configure module looks for `beril-adversarial`, not the
    pre-v0.3.4.5 incorrect `beril-adversarial-cli`."""
    src = (
        Path(__file__).resolve().parents[2]
        / "src" / "beril_presentation_maker" / "commands" / "configure.py"
    )
    text = src.read_text(encoding="utf-8")
    # Confirm we look for the right binary
    assert 'shutil.which("beril-adversarial")' in text, (
        "configure.py should look up `beril-adversarial`, not `beril-adversarial-cli`"
    )
    # Confirm we DO NOT look for the wrong binary (in active code; the
    # comment may mention it as a historical reference but `shutil.which`
    # of the wrong name is the bug we're fixing).
    assert 'shutil.which("beril-adversarial-cli")' not in text, (
        "configure.py should not check for `beril-adversarial-cli` "
        "(that binary never existed; v0.3.4.5 fix)"
    )


# ---------------------------------------------------------------------------
# End-to-end: run() produces non-empty output
# ---------------------------------------------------------------------------

def test_run_completes_with_no_args_namespace(monkeypatch, capsys, tmp_path):
    """A bare invocation of run() with a synthesized argparse.Namespace
    completes without crashing and emits the expected section
    headers."""
    import argparse
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    args = argparse.Namespace(beril_root=str(tmp_path), quiet=False)
    rc = configure.run(args)
    # Hard requirements may fail in sandbox (no claude CLI), but the
    # output should always include the section headers.
    captured = capsys.readouterr()
    assert "=== Hard requirements ===" in captured.out
    assert "=== Soft requirements ===" in captured.out
    assert "CBORG_API_KEY" in captured.out
    # rc is 0 (all hard met) or 3 (something missing in sandbox)
    assert rc in (0, 3)
