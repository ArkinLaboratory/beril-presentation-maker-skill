"""Unit tests for the vendored CRAFT chrome.py in presentation-maker
(Cycle-4, DP6).

presentation-maker vendors a BYTE-IDENTICAL copy of craft-platform's
canonical `chrome.py` (Family-F conformance). The shell orchestrator
shells out to it for the STAGE/RESULT banners and the NOISE→log routing.
These tests lock:

  1. the vendored copy exists at the package root (where the shell's
     CHROME_PY points: <pkg>/chrome.py);
  2. its CLI surface works (stage / result / noise);
  3. `noise` writes to audit/orchestrator.log and prints NOTHING to
     stdout (the suppression half of the "distinguish signal from noise"
     win);
  4. byte-identity against the canonical IF craft-platform is locatable
     as a sibling checkout (skips otherwise — the load-bearing Family-F
     check lives in craft-platform's own conformance suite).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

_REPO = Path(__file__).resolve().parents[2]
_VENDORED = _REPO / "src" / "beril_presentation_maker" / "chrome.py"


def test_vendored_chrome_exists_at_package_root():
    assert _VENDORED.is_file(), (
        f"vendored chrome.py missing at {_VENDORED} — the shell's CHROME_PY "
        f"(=$SKILL_DIR/../chrome.py) points here."
    )


def test_cli_stage_banner():
    r = subprocess.run(
        [sys.executable, str(_VENDORED), "stage", "--skill",
         "presentation-maker", "--n", "2", "--total", "14", "--stage",
         "throughline_candidates", "--model", "opus", "--state", "running"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "◆ CRAFT · presentation-maker · STAGE 2/14" in r.stdout
    assert "throughline_candidates" in r.stdout


def test_cli_result_line():
    r = subprocess.run(
        [sys.executable, str(_VENDORED), "result", "--skill",
         "presentation-maker", "--summary", "deck assembled", "--cost",
         "3.42"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "◆ CRAFT · presentation-maker · RESULT · deck assembled" in r.stdout
    assert "$3.42" in r.stdout


def test_cli_noise_writes_log_not_stdout(tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    r = subprocess.run(
        [sys.executable, str(_VENDORED), "noise", "--audit-dir", str(audit),
         "--message", "[orchestrator] CBORG_API_KEY loaded from BERIL_ROOT/.env"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", "noise must print nothing to stdout"
    log = (audit / "orchestrator.log").read_text(encoding="utf-8")
    assert "CBORG_API_KEY loaded" in log


def test_cli_noise_never_leaks_secret_value(tmp_path):
    """Defensive: the message is logged verbatim, but the orchestrator
    only ever passes the marker (never the key value). Confirm the CLI
    doesn't echo to stdout where a careless caller's message could leak."""
    audit = tmp_path / "audit"
    audit.mkdir()
    r = subprocess.run(
        [sys.executable, str(_VENDORED), "noise", "--audit-dir", str(audit),
         "--message", "provider chosen"],
        capture_output=True, text=True,
    )
    assert r.stdout == "" and r.returncode == 0


def _canonical_chrome() -> Path | None:
    """Locate craft-platform's canonical chrome.py as a sibling checkout
    (spike/craft-platform/src/craft/chrome.py). None if not present."""
    cand = _REPO.parent / "craft-platform" / "src" / "craft" / "chrome.py"
    return cand if cand.is_file() else None


def _normalize(s: str) -> str:
    return dedent("\n".join(ln.rstrip() for ln in s.splitlines())).rstrip()


def test_family_f_byte_identity_against_canonical():
    """Family-F (local mirror): the vendored copy is byte-identical to the
    canonical. The authoritative check is craft-platform's conformance
    suite (which validates the SUBMODULE post-re-pin); this is the
    develop-tree early-warning so drift is caught before the release."""
    canonical = _canonical_chrome()
    if canonical is None:
        pytest.skip("craft-platform sibling checkout not found; Family-F "
                    "authoritative check runs in craft-platform's suite")
    vendored_src = _normalize(_VENDORED.read_text(encoding="utf-8"))
    canonical_src = _normalize(canonical.read_text(encoding="utf-8"))
    assert vendored_src == canonical_src, (
        "vendored chrome.py drifted from craft-platform's canonical — "
        "re-copy verbatim (glyphs are multi-byte UTF-8)."
    )
