"""BERIL_ROOT discovery — vendored from beril-adversarial / beril-paper-writer.

Single source of truth across the quartet. May factor out to a shared
dependency post-MVP if drift becomes an issue. Until then: vendor literally
and keep the three implementations identical.

Resolution order:
1. Explicit `--beril-root <path>` flag (handed in by caller).
2. `BERIL_ROOT` environment variable.
3. Walk up from cwd looking for the BERIL marker set:
   - `.env` file present
   - `.claude/skills/` directory present
   - at least one BERIL-core skill folder present (`submit/`, `berdl/`,
     `suggest-research/`)
4. Fail loud with a diagnostic that names the missing markers.

v0.1.0-spec: stub only. Implementation lands with code.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn


CORE_SKILL_MARKERS = ("submit", "berdl", "suggest-research")


def discover_beril_root(explicit: str | None = None) -> Path:
    """Return the resolved BERIL_ROOT or raise BerilRootNotFound."""
    raise NotImplementedError(
        "discovery.discover_beril_root: not implemented in v0.1.0-spec. "
        "See LAYOUT.md §10 'BERIL_ROOT discovery'."
    )


class BerilRootNotFound(RuntimeError):
    """Raised when BERIL_ROOT cannot be resolved. Includes diagnostic."""


def _explain_failure(searched: list[Path], reason: str) -> NoReturn:
    """Build a verbose error message naming exactly which markers failed where."""
    raise NotImplementedError
