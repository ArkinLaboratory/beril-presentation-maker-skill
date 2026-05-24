"""Tests for the M5b orchestrator image-provider wiring.

Covers the auth-discovery + provider-precedence block in
presentation_maker.sh (M5b Tier B / D-062). Tests use synthetic .env
files in tmp_path and exercise the relevant shell snippet via
`bash -c`, so we don't need to run the whole orchestrator.

The snippet under test:
  1. Resolves CBORG_API_KEY + GOOGLE_AI_STUDIO_API_KEY from a single
     pass of BERIL_ROOT/.env (env-var precedence preserved).
  2. Computes IMAGE_PROVIDER per D-062 precedence:
     --image-provider arg > GOOGLE_AI_STUDIO_API_KEY > CBORG_API_KEY > "".
  3. Validates an explicit --image-provider value with a warning when
     the corresponding env var is missing.

Defensive: never echoes key values — only the loaded marker line.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def _extract_auth_block() -> str:
    """Extract the auth-discovery + provider-precedence block from
    presentation_maker.sh.

    Spans from `# --- v0.3.3 + M5b image-gen: resolve provider API keys ---`
    through the `export IMAGE_PROVIDER` line. Re-extracting from source
    keeps the test honest — if the shell snippet moves or renames, the
    extractor fails loudly rather than silently testing a stale copy.
    """
    text = ORCH_SH.read_text(encoding="utf-8")
    start_marker = "# --- v0.3.3 + M5b image-gen: resolve provider API keys ---"
    end_marker = "export IMAGE_PROVIDER"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise AssertionError(
            f"could not locate auth-discovery block in {ORCH_SH} — "
            f"start_marker={start} end_marker={end}; the M5b Tier B "
            f"comments may have been renamed."
        )
    # Include the export line
    end_of_line = text.find("\n", end)
    return text[start:end_of_line + 1]


def _run_snippet(env: dict[str, str],
                 beril_root: Path,
                 image_provider_initial: str = "") -> tuple[int, str, str]:
    """Run the extracted auth block in a fresh bash subshell with the
    given env. Returns (returncode, stdout, stderr).

    The wrapper sets BERIL_ROOT + PYTHON_BIN + IMAGE_PROVIDER, then
    `echo`s a summary line that the test parses to assert the
    resolved IMAGE_PROVIDER + which keys were loaded.
    """
    block = _extract_auth_block()
    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        BERIL_ROOT={beril_root!s}
        PYTHON_BIN={sys.executable!s}
        IMAGE_PROVIDER={image_provider_initial!r}
        {block}
        # Summary line for test assertions
        echo "RESOLVED_PROVIDER=$IMAGE_PROVIDER"
        echo "CBORG_KEY_SET=${{CBORG_API_KEY:+yes}}"
        echo "AI_STUDIO_KEY_SET=${{GOOGLE_AI_STUDIO_API_KEY:+yes}}"
        """)
    # Strip caller env entirely (we want to control CBORG_API_KEY +
    # GOOGLE_AI_STUDIO_API_KEY exactly).
    clean_env = {"PATH": os.environ.get("PATH", "")}
    clean_env.update(env)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        env=clean_env, capture_output=True, text=True, timeout=20,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_summary(stdout: str) -> dict[str, str]:
    out = {}
    for line in stdout.splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


# ---------------------------------------------------------------------------
# Provider precedence (D-062)
# ---------------------------------------------------------------------------

def test_ai_studio_takes_precedence_when_both_keys_set(tmp_path):
    """D-062: GOOGLE_AI_STUDIO_API_KEY present → IMAGE_PROVIDER=google_ai_studio
    even if CBORG_API_KEY is also set. (Matches Adam's stated intent
    in §14.1: 'use the user's Gemini Studio license if available'.)"""
    rc, stdout, stderr = _run_snippet(
        env={"CBORG_API_KEY": "cborg-test", "GOOGLE_AI_STUDIO_API_KEY": "ai-test"},
        beril_root=tmp_path,
    )
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "google_ai_studio"
    assert summary["CBORG_KEY_SET"] == "yes"
    assert summary["AI_STUDIO_KEY_SET"] == "yes"


def test_cborg_fallback_when_only_cborg_set(tmp_path):
    rc, stdout, stderr = _run_snippet(
        env={"CBORG_API_KEY": "cborg-test"},
        beril_root=tmp_path,
    )
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "cborg"


def test_no_provider_when_neither_key_set(tmp_path):
    """D-062: both keys absent → IMAGE_PROVIDER stays empty (downstream
    image-gen stage handles the no-provider case)."""
    rc, stdout, stderr = _run_snippet(
        env={},
        beril_root=tmp_path,
    )
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == ""
    assert summary["CBORG_KEY_SET"] == ""
    assert summary["AI_STUDIO_KEY_SET"] == ""


def test_explicit_provider_arg_overrides_precedence(tmp_path):
    """Explicit --image-provider cborg wins even when AI Studio key is set."""
    rc, stdout, stderr = _run_snippet(
        env={"CBORG_API_KEY": "c", "GOOGLE_AI_STUDIO_API_KEY": "a"},
        beril_root=tmp_path,
        image_provider_initial="cborg",
    )
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "cborg"


def test_explicit_provider_arg_warns_when_env_missing(tmp_path):
    """--image-provider google_ai_studio without GOOGLE_AI_STUDIO_API_KEY
    → warning on stderr but doesn't fail (downstream catches)."""
    rc, stdout, stderr = _run_snippet(
        env={},
        beril_root=tmp_path,
        image_provider_initial="google_ai_studio",
    )
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "google_ai_studio"
    assert "GOOGLE_AI_STUDIO_API_KEY not set" in stderr


def test_explicit_unknown_provider_fails(tmp_path):
    """--image-provider openai is rejected at orchestrator level
    (the snippet exits 2 with an error rather than passing through)."""
    rc, _stdout, stderr = _run_snippet(
        env={"CBORG_API_KEY": "x"},
        beril_root=tmp_path,
        image_provider_initial="openai",
    )
    assert rc == 2
    assert "must be 'cborg' or 'google_ai_studio'" in stderr


# ---------------------------------------------------------------------------
# .env file resolution
# ---------------------------------------------------------------------------

def test_loads_cborg_from_dotenv_when_env_unset(tmp_path):
    """No shell env, but BERIL_ROOT/.env has CBORG_API_KEY → loaded."""
    env_file = tmp_path / ".env"
    env_file.write_text("CBORG_API_KEY=from-dotenv\n", encoding="utf-8")
    rc, stdout, stderr = _run_snippet(env={}, beril_root=tmp_path)
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "cborg"
    assert summary["CBORG_KEY_SET"] == "yes"
    # The loaded-marker line goes to stderr
    assert "CBORG_API_KEY loaded from BERIL_ROOT/.env" in stderr
    # Defensive: the actual key value must NEVER appear in stderr/stdout
    assert "from-dotenv" not in stderr
    assert "from-dotenv" not in stdout


def test_loads_ai_studio_from_dotenv_when_env_unset(tmp_path):
    """No shell env, but BERIL_ROOT/.env has GOOGLE_AI_STUDIO_API_KEY →
    loaded; takes precedence over CBORG_API_KEY (D-062)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CBORG_API_KEY=cborg-from-dotenv\n"
        "GOOGLE_AI_STUDIO_API_KEY=ai-from-dotenv\n",
        encoding="utf-8",
    )
    rc, stdout, stderr = _run_snippet(env={}, beril_root=tmp_path)
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "google_ai_studio"
    assert "GOOGLE_AI_STUDIO_API_KEY loaded from BERIL_ROOT/.env" in stderr
    # Defensive
    assert "ai-from-dotenv" not in stderr
    assert "cborg-from-dotenv" not in stderr


def test_shell_env_wins_over_dotenv(tmp_path):
    """Shell env CBORG_API_KEY takes precedence over the same key in
    BERIL_ROOT/.env (the snippet uses the in-place check, doesn't
    overwrite)."""
    env_file = tmp_path / ".env"
    env_file.write_text("CBORG_API_KEY=from-dotenv\n", encoding="utf-8")
    rc, stdout, stderr = _run_snippet(
        env={"CBORG_API_KEY": "from-shell-env"},
        beril_root=tmp_path,
    )
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == "cborg"
    # No "loaded from BERIL_ROOT/.env" marker because the env-set value
    # was already present
    assert "CBORG_API_KEY loaded" not in stderr


def test_handles_quoted_values_in_dotenv(tmp_path):
    """The .env parser strips matching surrounding quotes
    (preserves the v0.3.3 CBORG behaviour for the new AI Studio key)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GOOGLE_AI_STUDIO_API_KEY="ai-quoted-value"\n',
        encoding="utf-8",
    )
    rc, stdout, stderr = _run_snippet(env={}, beril_root=tmp_path)
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["AI_STUDIO_KEY_SET"] == "yes"
    assert summary["RESOLVED_PROVIDER"] == "google_ai_studio"
    # Quoted value should not leak
    assert "ai-quoted-value" not in stderr
    assert "ai-quoted-value" not in stdout


def test_handles_missing_dotenv_file_gracefully(tmp_path):
    """No .env file → snippet still completes (just no key loading)."""
    # tmp_path with no .env
    rc, stdout, stderr = _run_snippet(env={}, beril_root=tmp_path)
    assert rc == 0, stderr
    summary = _parse_summary(stdout)
    assert summary["RESOLVED_PROVIDER"] == ""


# ---------------------------------------------------------------------------
# Help text + CLI flag presence
# ---------------------------------------------------------------------------

def test_image_provider_flag_appears_in_help():
    """--image-provider flag must be documented in the orchestrator's
    usage block — discoverability for end users."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    # --help exits 0 (usage function)
    help_text = result.stdout + result.stderr
    assert "--image-provider" in help_text
    assert "google_ai_studio" in help_text


def test_image_provider_flag_parses():
    """--image-provider value is parsed without arg-parse error."""
    # Run with --help triggered AFTER --image-provider — confirms the
    # parser accepts the flag and value before exiting on --help.
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--image-provider", "google_ai_studio", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    # Should not fail with "unknown option"
    assert "unknown option" not in result.stderr.lower()
    assert "--image-provider" not in result.stderr or result.returncode == 0
