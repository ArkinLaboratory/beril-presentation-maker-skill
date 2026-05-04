"""`beril-presentation-maker prune <project_id>` — clean up old drafts.

Drafts under `<project>/talks/draft_N/` accumulate over time. Each is
~10-50MB (deck + speaker notes + audit + image PNGs + snapshots).
Hub deployments accumulate dozens per project; users want a way to
prune.

Defaults:
- Dry-run by default. Pass `--apply` to actually delete (or
  `--archive <path>` to move instead).
- Keep the latest 3 drafts (`--keep 3`). Configurable via `--keep N`.
- Drafts marked with a `.kept` marker file inside the draft directory
  are NEVER pruned, regardless of `--keep`. Use this to pin specific
  drafts (e.g., a published version).
- Orphan entries (non-`draft_<N>` directories or files under `talks/`)
  are reported but NOT touched without `--also-orphans`.

The command never touches `narrative/` or `working/` files outside
draft directories, never modifies project source files (REPORT.md,
RESEARCH_PLAN.md, notebooks, figures), and never operates on `audit/`
sidecar histories that aren't inside a pruned draft.

Examples:

    # Dry-run: see what would be pruned, keeping the 3 newest drafts.
    beril-presentation-maker prune my_project

    # Actually prune, keeping the 5 newest:
    beril-presentation-maker prune my_project --keep 5 --apply

    # Archive instead of delete:
    beril-presentation-maker prune my_project --archive ~/talk-archives/ --apply

    # Pin a specific draft by hand first:
    touch projects/my_project/talks/draft_3/.kept
    beril-presentation-maker prune my_project --apply
    # ... draft_3 is preserved regardless of --keep
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_DRAFT_RE = re.compile(r"^draft_(\d+)$")
_KEEP_MARKER = ".kept"
_DEFAULT_KEEP = 3


@dataclass
class DraftEntry:
    """One draft directory under <project>/talks/."""
    path: Path
    n: int             # numeric draft index (parsed from "draft_<N>")
    size_bytes: int    # cumulative size on disk
    kept: bool         # has .kept marker file


@dataclass
class PruneDecision:
    """Per-draft decision: keep / prune / orphan."""
    entry: DraftEntry
    action: str        # "keep" | "prune" | "kept-marker"
    reason: str        # short human-readable


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "prune",
        help="Prune old drafts under projects/<id>/talks/.",
        description=(
            "Remove or archive old `draft_N/` directories under a "
            "project's talks/. Dry-run by default; pass --apply to "
            "actually delete or --archive to move. Drafts with a "
            "`.kept` marker file are preserved regardless of --keep. "
            "Never touches project source files, narrative/ outside "
            "drafts, or non-draft entries under talks/."
        ),
    )
    p.add_argument(
        "project",
        help=(
            "Project path or project_id. If a directory: used directly. "
            "Otherwise interpreted as a project_id under "
            "<BERIL_ROOT>/projects/<id>/."
        ),
    )
    p.add_argument(
        "--beril-root",
        default=None,
        help="Override BERIL_ROOT auto-detection.",
    )
    p.add_argument(
        "--keep", type=int, default=_DEFAULT_KEEP,
        help=(
            f"Number of latest drafts to keep (default: {_DEFAULT_KEEP}). "
            "Latest = highest draft_N. Drafts with .kept marker are "
            "ALWAYS kept regardless of this value."
        ),
    )
    p.add_argument(
        "--apply", action="store_true",
        help="Actually delete (or archive). Without this, dry-run only.",
    )
    p.add_argument(
        "--archive", default=None, metavar="PATH",
        help=(
            "Move pruned drafts to PATH/<project_id>/draft_N/ instead of "
            "deleting. Implies --apply when set. Use this for soft-prune "
            "with the option to restore."
        ),
    )
    p.add_argument(
        "--also-orphans", action="store_true",
        help=(
            "Also prune orphan entries under talks/ (anything not "
            "matching draft_<N>/). Default: report but don't touch."
        ),
    )
    p.set_defaults(func=run)
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_project_dir(project_arg: str,
                         beril_root_arg: Optional[str]) -> Path:
    """Resolve a project argument to an absolute project directory.

    If project_arg is itself a directory, use it. Otherwise interpret
    as project_id under BERIL_ROOT/projects/.
    """
    p = Path(project_arg).expanduser()
    if p.is_dir():
        return p.resolve()
    if beril_root_arg:
        beril_root = Path(beril_root_arg).expanduser().resolve()
    else:
        # Auto-detect: walk up from cwd looking for projects/ marker
        cwd = Path.cwd()
        beril_root = None
        for parent in [cwd] + list(cwd.parents):
            if (parent / "projects").is_dir():
                beril_root = parent
                break
        if beril_root is None:
            raise FileNotFoundError(
                f"could not auto-detect BERIL_ROOT from cwd={cwd}; "
                f"pass --beril-root explicitly or cd into a directory "
                f"containing projects/"
            )
    project_dir = beril_root / "projects" / project_arg
    if not project_dir.is_dir():
        raise FileNotFoundError(
            f"project not found: {project_dir} "
            f"(expected directory under {beril_root}/projects/)"
        )
    return project_dir.resolve()


def _dir_size_bytes(path: Path) -> int:
    """Cumulative size of a directory tree on disk. Symlinks not
    followed (size of the symlink itself, not its target). Errors
    on permission denied surface as 0 with stderr warning."""
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_symlink():
                    total += p.lstat().st_size
                elif p.is_file():
                    total += p.stat().st_size
            except OSError:
                # Permission denied / race / dangling symlink — skip
                continue
    except OSError as e:
        print(f"  warning: error walking {path}: {e}", file=sys.stderr)
    return total


def _format_bytes(n: int) -> str:
    """Human-readable size (binary units)."""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TiB"


def _enumerate_drafts(talks_dir: Path) -> tuple[list[DraftEntry], list[Path]]:
    """Walk a talks/ directory; return (drafts, orphans).

    drafts: every entry matching draft_<N>, sorted by N ascending.
    orphans: every entry NOT matching draft_<N> (any file or dir).
    """
    if not talks_dir.is_dir():
        return [], []
    drafts: list[DraftEntry] = []
    orphans: list[Path] = []
    for entry in sorted(talks_dir.iterdir()):
        m = _DRAFT_RE.match(entry.name)
        if m and entry.is_dir():
            n = int(m.group(1))
            kept = (entry / _KEEP_MARKER).is_file()
            drafts.append(DraftEntry(
                path=entry,
                n=n,
                size_bytes=_dir_size_bytes(entry),
                kept=kept,
            ))
        else:
            orphans.append(entry)
    drafts.sort(key=lambda d: d.n)
    return drafts, orphans


def plan_prune(drafts: list[DraftEntry],
               *,
               keep: int) -> list[PruneDecision]:
    """Decide which drafts to keep vs. prune.

    Rules (in order):
    1. Drafts with .kept marker → action=kept-marker.
    2. Top `keep` drafts by N (most recent) → action=keep.
    3. Everything else → action=prune.
    """
    decisions: list[PruneDecision] = []
    # Sort descending by N so "top K" is the first K
    by_recency = sorted(drafts, key=lambda d: d.n, reverse=True)
    keep_count = 0
    for d in by_recency:
        if d.kept:
            decisions.append(PruneDecision(
                entry=d, action="kept-marker",
                reason=f".kept marker found at {d.path / _KEEP_MARKER}",
            ))
        elif keep_count < keep:
            decisions.append(PruneDecision(
                entry=d, action="keep",
                reason=f"in latest-{keep} keep window",
            ))
            keep_count += 1
        else:
            decisions.append(PruneDecision(
                entry=d, action="prune",
                reason=f"older than latest-{keep} keep window",
            ))
    # Re-sort by N ascending for predictable output
    decisions.sort(key=lambda d: d.entry.n)
    return decisions


def _execute_prune(decisions: list[PruneDecision],
                   *,
                   apply: bool,
                   archive_to: Optional[Path],
                   project_id: str) -> tuple[int, int]:
    """Execute the prune plan. Returns (n_pruned, bytes_pruned).

    Dry-run when apply=False (no filesystem changes; report only).
    """
    n_pruned = 0
    bytes_pruned = 0
    for d in decisions:
        if d.action != "prune":
            continue
        n_pruned += 1
        bytes_pruned += d.entry.size_bytes
        if not apply:
            continue
        if archive_to is not None:
            dst = archive_to / project_id / d.entry.path.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                # Append timestamp to avoid overwrite
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%dT%H%M%S")
                dst = dst.parent / f"{d.entry.path.name}.{ts}"
            shutil.move(str(d.entry.path), str(dst))
            print(f"  archived: {d.entry.path} -> {dst}",
                  file=sys.stderr)
        else:
            shutil.rmtree(d.entry.path)
            print(f"  deleted: {d.entry.path}", file=sys.stderr)
    return n_pruned, bytes_pruned


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    try:
        project_dir = _resolve_project_dir(args.project, args.beril_root)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    project_id = project_dir.name

    talks_dir = project_dir / "talks"
    if not talks_dir.is_dir():
        print(f"no talks/ directory at {talks_dir}; nothing to prune",
              file=sys.stderr)
        return 0

    drafts, orphans = _enumerate_drafts(talks_dir)
    if not drafts:
        print(f"no draft_<N>/ directories under {talks_dir}",
              file=sys.stderr)
        if orphans:
            print(f"\norphans found ({len(orphans)}):", file=sys.stderr)
            for o in orphans:
                print(f"  - {o.name}", file=sys.stderr)
        return 0

    if args.keep < 0:
        print(f"error: --keep must be >= 0 (got {args.keep})",
              file=sys.stderr)
        return 1

    archive_to = None
    if args.archive:
        archive_to = Path(args.archive).expanduser().resolve()

    apply_mode = args.apply or (archive_to is not None)
    decisions = plan_prune(drafts, keep=args.keep)

    # Print plan
    print(f"project: {project_id}", file=sys.stderr)
    print(f"talks dir: {talks_dir}", file=sys.stderr)
    print(f"drafts found: {len(drafts)} "
          f"(keep latest {args.keep}; .kept marker pins always)",
          file=sys.stderr)
    print(f"mode: {'APPLY' if apply_mode else 'DRY-RUN'}"
          + (f" archive→{archive_to}" if archive_to else ""),
          file=sys.stderr)
    print("", file=sys.stderr)
    print(f"{'draft':<12} {'size':>12}  {'action':<14} reason",
          file=sys.stderr)
    print("-" * 78, file=sys.stderr)
    for d in decisions:
        print(f"draft_{d.entry.n:<6} "
              f"{_format_bytes(d.entry.size_bytes):>12}  "
              f"{d.action:<14} {d.reason}",
              file=sys.stderr)

    if orphans:
        print("", file=sys.stderr)
        print(f"orphans found ({len(orphans)}; not matching draft_<N>/):",
              file=sys.stderr)
        for o in orphans:
            kind = "dir" if o.is_dir() else "file"
            try:
                sz = (_dir_size_bytes(o) if o.is_dir() else o.stat().st_size)
            except OSError:
                sz = 0
            print(f"  - {o.name} ({kind}, {_format_bytes(sz)})",
                  file=sys.stderr)
        if not args.also_orphans:
            print("  (use --also-orphans to include these in prune)",
                  file=sys.stderr)

    # Execute
    print("", file=sys.stderr)
    n_pruned, bytes_pruned = _execute_prune(
        decisions,
        apply=apply_mode,
        archive_to=archive_to,
        project_id=project_id,
    )

    # Orphan handling — only if --also-orphans
    n_orphans_pruned = 0
    bytes_orphans_pruned = 0
    if args.also_orphans and orphans:
        for o in orphans:
            try:
                sz = (_dir_size_bytes(o) if o.is_dir() else o.stat().st_size)
            except OSError:
                sz = 0
            n_orphans_pruned += 1
            bytes_orphans_pruned += sz
            if not apply_mode:
                continue
            if archive_to is not None:
                dst = archive_to / project_id / "_orphans" / o.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(o), str(dst))
                print(f"  archived orphan: {o} -> {dst}", file=sys.stderr)
            else:
                if o.is_dir():
                    shutil.rmtree(o)
                else:
                    o.unlink()
                print(f"  deleted orphan: {o}", file=sys.stderr)

    # Summary
    total_n = n_pruned + n_orphans_pruned
    total_bytes = bytes_pruned + bytes_orphans_pruned
    verb = "would " if not apply_mode else ""
    if archive_to:
        verb += "archive" if not apply_mode else "archived"
    else:
        verb += "delete" if not apply_mode else "deleted"
    print("", file=sys.stderr)
    print(f"summary: {verb} {total_n} entries "
          f"({n_pruned} drafts + {n_orphans_pruned} orphans), "
          f"freeing {_format_bytes(total_bytes)}",
          file=sys.stderr)
    if not apply_mode and total_n > 0:
        print("", file=sys.stderr)
        print("dry-run only; pass --apply to actually delete "
              "(or --archive <path> to move instead).",
              file=sys.stderr)
    return 0
