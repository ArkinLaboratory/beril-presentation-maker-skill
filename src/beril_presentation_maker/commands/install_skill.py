"""`beril-presentation-maker install-skill <BERIL_ROOT>` — copy shipped skill files into BERIL.

Copies SKILL.md, commands/, prompts/, references/, and tools/ from the
installed package's bundled skill data into
`<BERIL_ROOT>/.claude/skills/beril-presentation-maker/`.

PRESERVES (never overwritten): state/  (runtime state, install-local).
CREATES if missing: state/.

Sets executable bit on tools/*.sh and tools/*.py after copy
(belt-and-suspenders even though hatchling should preserve it through
the wheel).

After copy succeeds: optionally runs a LIGHT post-install check —
verifies the `claude` CLI is on PATH and prints a pointer to the next
step. This intentionally does NOT invoke `configure`: configure has
side effects (extends `.env`, writes `.claude/settings.json`, runs a
live `claude -p` ping) that must not run silently as a sub-step of
install-skill. The user runs `beril-presentation-maker configure
--beril-root <root>` themselves, when they're ready (CRAFT-CONTRACT
§3.4 requirement #5; canary round-2 fixup-2).

Honors --no-smoke-test by skipping the post-install check entirely.
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
from importlib import resources
from pathlib import Path

from beril_presentation_maker import __version__, discovery

# Directories inside the shipped skill/ dir that should be overwritten on install
# v0.8.0: "tests" added so smoke_v3 fixtures ship to the installed layout
# (single source of truth: fixtures live in the package tree, not the repo
# root; smoke_v3_prompt.py resolves them under <skill_dir>/tests/fixtures/
# in installed mode).
_SHIPPED_SUBDIRS = ("commands", "prompts", "references", "tools", "tests")

# Directories that must exist in the installed skill dir but are install-local
# (never shipped, never overwritten)
_LOCAL_SUBDIRS = ("state",)

# Files at the skill-dir root that ship
_SHIPPED_FILES = ("SKILL.md",)

# Files inside shipped subdirs that need executable bit set after copy.
# Includes the orchestrator + every Python tool the orchestrator might
# spawn as a subprocess.
_EXECUTABLE_FILES = (
    "tools/presentation_maker.sh",
    "tools/stream_progress.py",
    "tools/curate_figures.py",
    "tools/citation_pool.py",
    "tools/extract_cross_tenant.py",
    "tools/parse_substories.py",
    "tools/parse_throughline_candidates.py",
    "tools/parse_speaker_notes.py",
    "tools/merge_compose_fragments.py",
    "tools/repair_diagram_stubs.py",
    "tools/diagram_render.py",
    "tools/build_master.py",
    "tools/assemble_pptx.py",
    "tools/slide_spec.py",
    "tools/poster_fill.py",
    "tools/image_client.py",
    "tools/validate_presentation.py",
    "tools/check_quantitative_grounding.py",
    "tools/revise_loop.py",
    "tools/image_gen_calibration.py",
    "tools/draft_paths.py",
    # v0.8.0 Tier G.10-A: deterministic layout-overlap detector
    "tools/check_slide_layout_overlaps.py",
    # v0.8.1: content_overflow → revise_loop routing merger
    "tools/merge_content_overflow_into_review.py",
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "install-skill",
        help="Copy shipped skill files into a BERIL checkout.",
        description=(
            "Copy the beril-presentation-maker skill files from the installed "
            "package into <BERIL_ROOT>/.claude/skills/beril-presentation-maker/. "
            "Preserves the install-local state/ subdirectory."
        ),
    )
    p.add_argument(
        "beril_root",
        nargs="?",
        default=".",
        help="Path to the BERIL checkout root (default: current directory).",
    )
    p.add_argument(
        "--force",
        "-f",
        action="store_true",
        help=(
            "Overwrite shipped files without confirmation. Does NOT remove "
            "the install-local state/ subdirectory."
        ),
    )
    p.add_argument(
        "--no-smoke-test",
        action="store_true",
        help=(
            "Skip the post-install light check (claude on PATH + next-step "
            "hint). Default: run it advisory (non-fatal)."
        ),
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    try:
        beril_root = discovery.find_beril_root(explicit=args.beril_root)
    except discovery.BerilRootNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    skill_target = discovery.get_skill_dir(beril_root)
    skill_target.mkdir(parents=True, exist_ok=True)

    # Locate the shipped skill/ dir inside the installed package.
    try:
        skill_src_trav = resources.files("beril_presentation_maker") / "skill"
    except Exception as e:
        print(
            f"Error: could not locate shipped skill data inside "
            f"beril_presentation_maker package: {e}. "
            f"This is an install-level bug. Please file an issue.",
            file=sys.stderr,
        )
        return 2

    try:
        with resources.as_file(skill_src_trav) as skill_src:
            if not skill_src.is_dir():
                print(
                    f"Error: no shipped skill/ data in this release "
                    f"({__version__}). Skill directory created at "
                    f"{skill_target}, but no files were copied. Reinstall "
                    f"the package.",
                    file=sys.stderr,
                )
                return 2
            _copy_shipped_files(skill_src, skill_target, force=args.force)
            _copy_shipped_subdirs(skill_src, skill_target, force=args.force)
            _set_executable_bits(skill_target)
    except FileNotFoundError:
        print(
            f"Error: skill/ data not found inside the installed package "
            f"({__version__}). Reinstall the package.",
            file=sys.stderr,
        )
        return 2

    _ensure_local_subdirs(skill_target)

    print(f"Skill directory: {skill_target}")
    print(f"Preserved (never overwritten): {', '.join(_LOCAL_SUBDIRS)}")
    print(f"Package version: {__version__}")

    if args.no_smoke_test:
        return 0

    # Light post-install check — advisory, NEVER invokes configure.
    # configure has real side effects (extends .env, writes
    # .claude/settings.json + settings.local.json, runs a live
    # `claude -p` ping) and must not run silently as a sub-step of
    # install-skill. CRAFT-CONTRACT §3.4 requirement #5 (canary
    # round-2 fixup-2, adversarial main @37088d8).
    print("")
    claude_path = shutil.which("claude")
    if claude_path is None:
        print(
            "  [WARN] claude CLI not found on PATH. Install Claude Code "
            "(https://docs.claude.com) before running configure.",
            file=sys.stderr,
        )
    else:
        print(f"  [OK] claude — {claude_path}")
    print("")
    print(
        f"Next: run `beril-presentation-maker configure --beril-root {beril_root}` "
        "to bootstrap CRAFT runtime config."
    )
    return 0


def _copy_shipped_files(src: Path, dst: Path, *, force: bool) -> None:
    for name in _SHIPPED_FILES:
        s = src / name
        if not s.is_file():
            continue
        d = dst / name
        if d.exists() and not force and _files_identical(s, d):
            continue
        shutil.copy2(s, d)


def _copy_shipped_subdirs(src: Path, dst: Path, *, force: bool) -> None:
    # Filter __pycache__ and .pyc out of the source tree. These can appear
    # in editable installs (`pip install -e .`) where the package data IS
    # the source tree. Wheel-installed copies exclude them via hatch's
    # build target excludes.
    ignore_pycache = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    for subdir in _SHIPPED_SUBDIRS:
        s = src / subdir
        if not s.is_dir():
            continue
        d = dst / subdir
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(s, d, ignore=ignore_pycache)


def _set_executable_bits(skill_dir: Path) -> None:
    """Ensure shipped scripts have +x. Hatchling should preserve this through
    the wheel, but we set it explicitly as a safety net."""
    for rel in _EXECUTABLE_FILES:
        path = skill_dir / rel
        if path.is_file():
            current = path.stat().st_mode
            path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _ensure_local_subdirs(skill_dir: Path) -> None:
    for subdir in _LOCAL_SUBDIRS:
        p = skill_dir / subdir
        p.mkdir(exist_ok=True)
    state_readme = skill_dir / "state" / "README.md"
    if not state_readme.exists():
        state_readme.write_text(_STATE_README, encoding="utf-8")


def _files_identical(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


_STATE_README = """# state/ — install-local runtime state

Files in this directory are written at runtime by the presentation maker
and are NEVER shipped or overwritten by
`beril-presentation-maker install-skill`.

Per-draft state lives under each
`<BERIL_ROOT>/projects/<project_id>/talks/draft_N/state.json`, not here.
This directory is reserved for cross-draft persistence (learned
patterns, brand-token overrides, etc.) per LAYOUT.md §6.

If empty, that's fine — the orchestrator creates files on demand.
"""
