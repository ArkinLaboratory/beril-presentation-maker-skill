"""Unit tests for the CRAFT Cycle-4 (DP6) decision.v1 emission at the
throughline-pick halt.

`emit_throughline_handoff` (in presentation_maker.sh) now EXTENDS the
throughline `.handoff.json` with the decision.v1 presentation fields:
retaining the keys the continue CLI reads (phase / draft_dir / candidates
/ candidates_md / next_command) and ADDING schema_version / skill / gate /
prompt / kind / options[{id,summary,detail}] / default / confirm /
continue{cmd}. These tests:

  1. extract the REAL emitter heredoc from the shell (so the test can't
     drift from the shipped code), run it against a realistic candidates
     fixture, and
  2. validate the emitted payload with the platform validator
     `craft.decision.validate_decision` (the same one Family-G uses).

`craft.decision` is importable because craft-platform is installed in the
conformance/test venv (it's the run-record + decision validator home).
The test skips gracefully if craft isn't importable, mirroring the
Family-E/G discipline.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ORCH_SH = _REPO / "src" / "beril_presentation_maker" / "skill" / "tools" / "presentation_maker.sh"
_FIXTURE = _REPO / "tests" / "fixtures" / "throughline" / "00_throughline_candidates.md"

try:
    from craft.decision import validate_decision  # type: ignore
    _HAVE_CRAFT = True
except ImportError:
    _HAVE_CRAFT = False


def _extract_emitter_body() -> str:
    """Pull the python heredoc body of emit_throughline_handoff from the
    shell source (between `<<'PYEOF'` and `PYEOF`). Fails loudly if the
    marker moves, so the test always runs the shipped code."""
    text = _ORCH_SH.read_text(encoding="utf-8")
    anchor = "emit_throughline_handoff()"
    a = text.find(anchor)
    assert a >= 0, "could not locate emit_throughline_handoff in the shell"
    start = text.find("<<'PYEOF'\n", a)
    assert start >= 0, "could not locate the PYEOF heredoc opener"
    start += len("<<'PYEOF'\n")
    end = text.find("\nPYEOF", start)
    assert end >= 0, "could not locate the PYEOF heredoc terminator"
    return text[start:end]


def _emit(tmp_path: Path) -> dict:
    """Run the real emitter heredoc against the fixture; return the parsed
    .handoff.json payload."""
    body = _extract_emitter_body()
    handoff = tmp_path / ".handoff.json"
    draft_dir = "/projects/ibd_phage_targeting/talks/draft_7"
    r = subprocess.run(
        [sys.executable, "-c", body, str(_FIXTURE), str(handoff), draft_dir],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"emitter failed: {r.stderr}"
    return json.loads(handoff.read_text(encoding="utf-8"))


def test_fixture_present():
    assert _FIXTURE.is_file(), f"candidates fixture missing at {_FIXTURE}"


def test_emitter_retains_handoff_keys(tmp_path):
    """decision.v1 EXTENDS the handoff — the keys the continue CLI reads
    must survive."""
    p = _emit(tmp_path)
    for k in ("phase", "draft_dir", "candidates", "candidates_md",
              "next_command"):
        assert k in p, f"emitter dropped handoff key {k!r}"
    assert p["phase"] == "throughline_pick"
    assert isinstance(p["candidates"], list) and p["candidates"]
    # each legacy candidate keeps {id, label}
    for c in p["candidates"]:
        assert set(c) >= {"id", "label"}


def test_emitter_adds_decision_v1_fields(tmp_path):
    p = _emit(tmp_path)
    assert p["schema_version"] == "decision.v1"
    assert p["skill"] == "presentation-maker"
    assert p["gate"] == p["phase"] == "throughline_pick"   # gate == phase
    assert p["kind"] == "single_select"
    assert p["confirm"] is True                            # consequential gate
    assert p["default"] == p["options"][0]["id"]           # first candidate
    assert "{id}" in p["continue"]["cmd"]                  # placeholder present
    # options carry full detail (not just the truncated label)
    ids = [o["id"] for o in p["options"]]
    assert ids == ["TL1", "TL2", "TL3"]
    for o in p["options"]:
        assert set(o) >= {"id", "summary", "detail"}
        assert o["detail"].strip(), "option detail must be non-empty"
    # the full section body (more than the one-line summary) is the detail
    tl1 = next(o for o in p["options"] if o["id"] == "TL1")
    assert len(tl1["detail"]) > len(tl1["summary"])
    assert "Evidence chain" in tl1["detail"]               # full section text


def test_emitter_continue_cmd_has_no_literal_pick(tmp_path):
    """continue.cmd carries the {id} placeholder, not a hardcoded pick."""
    p = _emit(tmp_path)
    cmd = p["continue"]["cmd"]
    assert "--pick {id}" in cmd
    assert "--pick TL1" not in cmd  # not a baked-in choice


@pytest.mark.skipif(not _HAVE_CRAFT,
                    reason="craft not importable (install craft-platform)")
def test_emitted_payload_validates_against_platform_validator(tmp_path):
    """The REAL emitted handoff passes craft.decision.validate_decision —
    the same validator Family-G runs on shipped goldens."""
    p = _emit(tmp_path)
    errors = validate_decision(p)
    assert errors == [], f"emitted decision.v1 failed validation: {errors}"
