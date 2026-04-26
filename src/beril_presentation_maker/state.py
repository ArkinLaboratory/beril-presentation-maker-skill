"""state.json schema + read/write/diff helpers.

v0.1.0-spec: stub. The state schema is documented in LAYOUT.md §6
'state.json schema (informal)'. The mechanized validators (P1–P10)
land here as pure functions in v0.1.0-code; for now this module
documents the schema by example only.
"""
from __future__ import annotations

# The state.json schema is the source of truth for stop/resume.
# See LAYOUT.md §6 for the full informal schema.
#
# Implementation lands with code; this stub exists so that
# importlib.resources, install_skill, and CLI parsing all have a
# valid module to import from on day one.
