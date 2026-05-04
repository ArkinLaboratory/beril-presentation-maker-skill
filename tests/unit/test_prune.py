"""Tests for v0.3.4.1 `beril-presentation-maker prune` subcommand.

Covers: dry-run output, --apply deletion, --archive move, .kept marker
pinning, orphan detection + --also-orphans handling, --keep N
parameterization, missing project handling, plan_prune logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Load the prune module via the package import path that pipx
# installs into. From repo root, src/ is the package root.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "src")
)

from beril_presentation_maker.commands import prune  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_with_drafts(tmp_path):
    """Build a synthetic <BERIL_ROOT>/projects/myproj/talks/ tree
    with 5 drafts of varying sizes, returning (project_dir, talks_dir)."""
    beril_root = tmp_path
    project_dir = beril_root / "projects" / "myproj"
    talks_dir = project_dir / "talks"
    talks_dir.mkdir(parents=True)

    for n in range(1, 6):
        d = talks_dir / f"draft_{n}"
        d.mkdir()
        # Add varied content to make sizes non-trivial
        (d / "deliverable").mkdir()
        (d / "deliverable" / "draft.pptx").write_bytes(b"X" * (n * 1024))
        (d / "audit").mkdir()
        (d / "audit" / "state.json").write_text("{}")

    return project_dir, talks_dir


@pytest.fixture
def project_with_kept_marker(project_with_drafts):
    """Same as project_with_drafts but pin draft_2 with .kept marker."""
    project_dir, talks_dir = project_with_drafts
    (talks_dir / "draft_2" / ".kept").write_text("pinned for May talk")
    return project_dir, talks_dir


# ---------------------------------------------------------------------------
# _enumerate_drafts
# ---------------------------------------------------------------------------

def test_enumerate_finds_all_drafts(project_with_drafts):
    _, talks_dir = project_with_drafts
    drafts, orphans = prune._enumerate_drafts(talks_dir)
    assert len(drafts) == 5
    assert [d.n for d in drafts] == [1, 2, 3, 4, 5]
    assert orphans == []


def test_enumerate_detects_orphans(project_with_drafts):
    _, talks_dir = project_with_drafts
    # Add some orphan entries
    (talks_dir / "scratch.txt").write_text("notes")
    (talks_dir / "old_backup").mkdir()
    drafts, orphans = prune._enumerate_drafts(talks_dir)
    assert len(drafts) == 5  # unchanged
    assert len(orphans) == 2
    orphan_names = {o.name for o in orphans}
    assert "scratch.txt" in orphan_names
    assert "old_backup" in orphan_names


def test_enumerate_detects_kept_marker(project_with_kept_marker):
    _, talks_dir = project_with_kept_marker
    drafts, _ = prune._enumerate_drafts(talks_dir)
    by_n = {d.n: d for d in drafts}
    assert by_n[2].kept is True
    assert by_n[1].kept is False


def test_enumerate_handles_missing_dir(tmp_path):
    drafts, orphans = prune._enumerate_drafts(tmp_path / "no_such_dir")
    assert drafts == []
    assert orphans == []


def test_enumerate_ignores_non_draft_pattern_dirs(tmp_path):
    """draft_v2/, draft-1/, drafts/ etc. are NOT matched."""
    talks = tmp_path / "talks"
    talks.mkdir()
    for name in ("draft_v2", "draft-1", "drafts", "old_draft_1"):
        (talks / name).mkdir()
    (talks / "draft_99").mkdir()  # this DOES match
    drafts, orphans = prune._enumerate_drafts(talks)
    assert len(drafts) == 1
    assert drafts[0].n == 99
    assert len(orphans) == 4


# ---------------------------------------------------------------------------
# plan_prune
# ---------------------------------------------------------------------------

def _drafts(*ns_kept):
    """Helper: build [DraftEntry] from list of (n, kept) tuples."""
    return [
        prune.DraftEntry(
            path=Path(f"/tmp/draft_{n}"),
            n=n,
            size_bytes=n * 1000,
            kept=kept,
        )
        for n, kept in ns_kept
    ]


def test_plan_prune_keeps_latest_n():
    drafts = _drafts((1, False), (2, False), (3, False), (4, False), (5, False))
    decisions = prune.plan_prune(drafts, keep=3)
    by_n = {d.entry.n: d for d in decisions}
    # Latest 3 (5, 4, 3) → keep
    assert by_n[5].action == "keep"
    assert by_n[4].action == "keep"
    assert by_n[3].action == "keep"
    # Older (2, 1) → prune
    assert by_n[2].action == "prune"
    assert by_n[1].action == "prune"


def test_plan_prune_kept_marker_pins_regardless_of_window():
    drafts = _drafts((1, True), (2, False), (3, False), (4, False), (5, False))
    decisions = prune.plan_prune(drafts, keep=3)
    by_n = {d.entry.n: d for d in decisions}
    # draft_1 has .kept → pinned despite being oldest
    assert by_n[1].action == "kept-marker"
    # Latest 3 (5, 4, 3) still keep
    assert by_n[5].action == "keep"
    assert by_n[4].action == "keep"
    assert by_n[3].action == "keep"
    # draft_2 → prune
    assert by_n[2].action == "prune"


def test_plan_prune_keep_zero_prunes_everything():
    drafts = _drafts((1, False), (2, False), (3, False))
    decisions = prune.plan_prune(drafts, keep=0)
    actions = [d.action for d in decisions]
    assert all(a == "prune" for a in actions)


def test_plan_prune_keep_larger_than_count_keeps_all():
    drafts = _drafts((1, False), (2, False))
    decisions = prune.plan_prune(drafts, keep=10)
    assert all(d.action == "keep" for d in decisions)


def test_plan_prune_kept_marker_doesnt_count_against_keep_quota():
    """If draft_1 has .kept and keep=3, the latest 3 NON-kept drafts
    should still all be kept (no displacement)."""
    drafts = _drafts(
        (1, True),    # kept-marker
        (2, False),
        (3, False),
        (4, False),
        (5, False),
    )
    decisions = prune.plan_prune(drafts, keep=3)
    by_n = {d.entry.n: d for d in decisions}
    assert by_n[1].action == "kept-marker"
    assert by_n[5].action == "keep"
    assert by_n[4].action == "keep"
    assert by_n[3].action == "keep"
    assert by_n[2].action == "prune"  # NOT pinned by .kept and outside top 3


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def test_format_bytes_units():
    assert prune._format_bytes(0) == "0 B"
    assert prune._format_bytes(512) == "512 B"
    assert prune._format_bytes(1024) == "1.0 KiB"
    assert prune._format_bytes(1024 * 1024) == "1.0 MiB"
    assert prune._format_bytes(1024 * 1024 * 1024) == "1.0 GiB"


# ---------------------------------------------------------------------------
# CLI integration — dry-run by default
# ---------------------------------------------------------------------------

def test_cli_dry_run_does_not_delete(project_with_drafts, capsys):
    project_dir, talks_dir = project_with_drafts
    rc = prune.run(_args(project=str(project_dir), keep=2, apply=False))
    assert rc == 0
    # All drafts still exist
    for n in range(1, 6):
        assert (talks_dir / f"draft_{n}").is_dir()
    captured = capsys.readouterr()
    # Confirms dry-run output
    assert "DRY-RUN" in captured.err
    assert "would delete" in captured.err or "would " in captured.err


def test_cli_apply_deletes(project_with_drafts):
    project_dir, talks_dir = project_with_drafts
    rc = prune.run(_args(project=str(project_dir), keep=2, apply=True))
    assert rc == 0
    # Latest 2 (4, 5) kept
    assert (talks_dir / "draft_5").is_dir()
    assert (talks_dir / "draft_4").is_dir()
    # Earlier ones gone
    assert not (talks_dir / "draft_3").exists()
    assert not (talks_dir / "draft_2").exists()
    assert not (talks_dir / "draft_1").exists()


def test_cli_archive_moves(project_with_drafts, tmp_path):
    project_dir, talks_dir = project_with_drafts
    archive_dir = tmp_path / "archive"
    rc = prune.run(_args(
        project=str(project_dir), keep=2,
        apply=False, archive=str(archive_dir),
    ))
    assert rc == 0
    # --archive implies apply: drafts moved
    assert not (talks_dir / "draft_1").exists()
    assert (archive_dir / "myproj" / "draft_1").is_dir()
    assert (archive_dir / "myproj" / "draft_3").is_dir()
    # Latest 2 still in original
    assert (talks_dir / "draft_5").is_dir()
    assert (talks_dir / "draft_4").is_dir()


def test_cli_kept_marker_not_pruned(project_with_kept_marker):
    """draft_2 has .kept; even with keep=1, it survives."""
    project_dir, talks_dir = project_with_kept_marker
    rc = prune.run(_args(project=str(project_dir), keep=1, apply=True))
    assert rc == 0
    # draft_5 (latest) and draft_2 (kept-marker) survive
    assert (talks_dir / "draft_5").is_dir()
    assert (talks_dir / "draft_2").is_dir()
    # Others gone (draft_1, draft_3, draft_4)
    assert not (talks_dir / "draft_1").exists()
    assert not (talks_dir / "draft_3").exists()
    assert not (talks_dir / "draft_4").exists()


def test_cli_orphans_listed_but_not_pruned_by_default(
    project_with_drafts, capsys
):
    project_dir, talks_dir = project_with_drafts
    (talks_dir / "scratch.txt").write_text("notes")
    rc = prune.run(_args(project=str(project_dir), keep=2, apply=True))
    assert rc == 0
    # Orphan not touched
    assert (talks_dir / "scratch.txt").exists()
    captured = capsys.readouterr()
    assert "orphans found" in captured.err


def test_cli_also_orphans_prunes_them(project_with_drafts):
    project_dir, talks_dir = project_with_drafts
    (talks_dir / "scratch.txt").write_text("notes")
    rc = prune.run(_args(
        project=str(project_dir), keep=2, apply=True, also_orphans=True,
    ))
    assert rc == 0
    assert not (talks_dir / "scratch.txt").exists()


def test_cli_no_drafts_exits_clean(tmp_path, capsys):
    project_dir = tmp_path / "projects" / "empty"
    (project_dir / "talks").mkdir(parents=True)
    rc = prune.run(_args(project=str(project_dir), keep=3, apply=True))
    assert rc == 0
    captured = capsys.readouterr()
    assert "no draft_<N>/" in captured.err


def test_cli_no_talks_dir_exits_clean(tmp_path, capsys):
    project_dir = tmp_path / "projects" / "no_talks"
    project_dir.mkdir(parents=True)
    rc = prune.run(_args(project=str(project_dir), keep=3, apply=True))
    assert rc == 0
    captured = capsys.readouterr()
    assert "no talks/" in captured.err


def test_cli_missing_project_returns_1(tmp_path, capsys):
    # Setup beril root with no such project
    beril_root = tmp_path
    (beril_root / "projects").mkdir()
    rc = prune.run(_args(
        project="ghost",
        beril_root=str(beril_root),
        keep=3, apply=True,
    ))
    assert rc == 1
    captured = capsys.readouterr()
    assert "project not found" in captured.err


def test_cli_keep_negative_returns_1(project_with_drafts, capsys):
    project_dir, _ = project_with_drafts
    rc = prune.run(_args(project=str(project_dir), keep=-1, apply=True))
    assert rc == 1
    captured = capsys.readouterr()
    assert "keep" in captured.err.lower()


def test_cli_archive_directory_collision(tmp_path, project_with_drafts):
    """Archive twice into the same dir → second invocation timestamps
    the colliding entry instead of overwriting."""
    project_dir, talks_dir = project_with_drafts
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    # Pre-create a colliding draft_1 in archive
    (archive_dir / "myproj").mkdir()
    (archive_dir / "myproj" / "draft_1").mkdir()
    (archive_dir / "myproj" / "draft_1" / "old.txt").write_text("old")

    rc = prune.run(_args(
        project=str(project_dir), keep=4,
        apply=False, archive=str(archive_dir),
    ))
    assert rc == 0
    # Original collision preserved
    assert (archive_dir / "myproj" / "draft_1" / "old.txt").is_file()
    # New one got timestamped variant
    timestamped = list((archive_dir / "myproj").glob("draft_1.*"))
    assert len(timestamped) == 1
    assert timestamped[0].is_dir()


# ---------------------------------------------------------------------------
# Auto-detect BERIL_ROOT
# ---------------------------------------------------------------------------

def test_resolve_project_dir_with_explicit_beril_root(project_with_drafts):
    project_dir, _ = project_with_drafts
    beril_root = project_dir.parent.parent  # tmp_path
    resolved = prune._resolve_project_dir(
        "myproj", str(beril_root)
    )
    assert resolved == project_dir.resolve()


def test_resolve_project_dir_with_path_arg_uses_path_directly(
    project_with_drafts
):
    project_dir, _ = project_with_drafts
    resolved = prune._resolve_project_dir(str(project_dir), None)
    assert resolved == project_dir.resolve()


# ---------------------------------------------------------------------------
# argparse + main()-level integration
# ---------------------------------------------------------------------------

def test_main_prune_dispatches_via_cli(project_with_drafts):
    """End-to-end: invoke via the top-level cli.main() to confirm the
    subparser is registered and dispatches correctly."""
    from beril_presentation_maker import cli
    project_dir, talks_dir = project_with_drafts
    rc = cli.main([
        "prune", str(project_dir), "--keep", "2",
    ])
    assert rc == 0
    # Dry-run by default; nothing deleted
    for n in range(1, 6):
        assert (talks_dir / f"draft_{n}").is_dir()


def test_main_prune_apply_dispatches_via_cli(project_with_drafts):
    from beril_presentation_maker import cli
    project_dir, talks_dir = project_with_drafts
    rc = cli.main([
        "prune", str(project_dir), "--keep", "1", "--apply",
    ])
    assert rc == 0
    # draft_5 kept, others gone
    assert (talks_dir / "draft_5").is_dir()
    for n in range(1, 5):
        assert not (talks_dir / f"draft_{n}").exists()


# ---------------------------------------------------------------------------
# argparse stub
# ---------------------------------------------------------------------------

def _args(**kw):
    """Build an argparse.Namespace stub for run() tests."""
    import argparse
    defaults = {
        "project": "",
        "beril_root": None,
        "keep": 3,
        "apply": False,
        "archive": None,
        "also_orphans": False,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)
