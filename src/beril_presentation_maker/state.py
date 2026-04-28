"""state.json — read/write helpers (orchestrator is canonical).

In v0.2.0, presentation_maker.sh is the canonical owner of per-draft
state. Unlike beril-paper-writer (which has a Python state machine
with explicit phase transitions and revision counters), presentation-
maker's orchestrator runs the 11-stage pipeline in one shot with
`--resume-from` for re-runs. There is no Python-level state machine
to maintain in v0.2.0.

This module exposes minimal read/write helpers for the limited cases
where Python code needs to inspect a draft's state.json (e.g., a
future `revise` subcommand that needs to know which slide IDs exist).
The orchestrator's contract is the source of truth for the schema;
see LAYOUT.md §6.

If the orchestrator's state.json schema grows beyond ad-hoc inspection,
promote this module to a real dataclass-based state machine (mirror
beril_paper_writer.state).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_state(draft_dir: Path) -> dict[str, Any]:
    """Read <draft_dir>/state.json and return as a dict.

    Returns an empty dict if state.json does not exist (the orchestrator
    may not have written one yet for early-phase drafts).

    Raises:
      OSError: if state.json exists but cannot be read.
      ValueError: if state.json contains malformed JSON.
    """
    path = Path(draft_dir) / "state.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed state.json at {path}: {e}") from e


def save_state(draft_dir: Path, state: dict[str, Any]) -> None:
    """Write <draft_dir>/state.json with pretty-printed JSON.

    The orchestrator owns the schema; this is a pure serialization
    helper. Callers are responsible for shape correctness.
    """
    path = Path(draft_dir) / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
