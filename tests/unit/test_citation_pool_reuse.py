"""Tests for the presentation-maker-specific additions to citation_pool.py:
load_from_disk filename fallback, merge_pools, load_pool_from_paper_draft,
and the reuse-from-paper CLI subcommand.

The bulk of citation_pool.py (10-field schema, validate_entry, format_*,
serialize_to_disk) is unchanged from paper-writer's tested fork; we don't
re-test that here.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CP_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "citation_pool.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cp():
    return _import("citation_pool", CP_PY)


def _make_entry(cp, title="Test", doi=None, pmid=None):
    """Build a minimal valid CitationEntry."""
    return cp.CitationEntry(
        authors=["Doe, J."],
        year=2024,
        title=title,
        venue="J. Test",
        doi=doi,
        pmid=pmid,
        studied="test population",
        finding="test result",
        scope_alignment="direct",
        assessment="supports",
    )


# ---------------------------------------------------------------------------
# load_from_disk filename fallback
# ---------------------------------------------------------------------------

def test_load_from_disk_prefers_citation_pool_json(cp, tmp_path):
    """When both citation_pool.json and pool.json exist, citation_pool.json wins."""
    pool_a = cp.CitationPool(entries=[_make_entry(cp, title="A")])
    pool_b = cp.CitationPool(entries=[_make_entry(cp, title="B")])
    (tmp_path / "citation_pool.json").write_text(
        json.dumps(pool_a.to_dict()))
    (tmp_path / "pool.json").write_text(
        json.dumps(pool_b.to_dict()))
    loaded = cp.load_from_disk(tmp_path)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].title == "A"


def test_load_from_disk_falls_back_to_pool_json(cp, tmp_path):
    """Paper-writer's filename (pool.json) is loadable for reuse."""
    pool = cp.CitationPool(entries=[_make_entry(cp, title="From paper-writer")])
    (tmp_path / "pool.json").write_text(json.dumps(pool.to_dict()))
    loaded = cp.load_from_disk(tmp_path)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].title == "From paper-writer"


def test_load_from_disk_returns_empty_when_neither_file(cp, tmp_path):
    loaded = cp.load_from_disk(tmp_path)
    assert loaded.entries == []


# ---------------------------------------------------------------------------
# merge_pools
# ---------------------------------------------------------------------------

def test_merge_pools_appends_new_entries(cp):
    target = cp.CitationPool(entries=[_make_entry(cp, title="A", doi="10.1/a")])
    source = cp.CitationPool(entries=[_make_entry(cp, title="B", doi="10.1/b")])
    summary = cp.merge_pools(target, source)
    assert summary["added"] == 1
    assert summary["skipped_duplicate"] == 0
    assert {e.title for e in target.entries} == {"A", "B"}


def test_merge_pools_dedups_by_doi(cp):
    target = cp.CitationPool(entries=[_make_entry(cp, title="A", doi="10.1/x")])
    source = cp.CitationPool(entries=[_make_entry(cp, title="A-dup", doi="10.1/X")])
    summary = cp.merge_pools(target, source)
    assert summary["added"] == 0
    assert summary["skipped_duplicate"] == 1
    assert len(target.entries) == 1


def test_merge_pools_dedups_by_pmid(cp):
    target = cp.CitationPool(entries=[_make_entry(cp, title="A", pmid="12345678")])
    source = cp.CitationPool(entries=[_make_entry(cp, title="A-dup", pmid="12345678")])
    summary = cp.merge_pools(target, source)
    assert summary["added"] == 0
    assert summary["skipped_duplicate"] == 1


def test_merge_pools_respects_pool_size_cap(cp):
    cap = cp.POOL_SIZE_CAP
    target_entries = [_make_entry(cp, title=f"T{i}", doi=f"10.1/t{i}")
                      for i in range(cap)]
    target = cp.CitationPool(entries=target_entries)
    source = cp.CitationPool(entries=[
        _make_entry(cp, title="overflow", doi="10.1/over"),
    ])
    summary = cp.merge_pools(target, source)
    assert summary["added"] == 0
    assert summary["skipped_full"] == 1
    assert len(target.entries) == cap


def test_merge_pools_doi_match_is_case_insensitive(cp):
    target = cp.CitationPool(entries=[_make_entry(cp, doi="10.1/Smith2023")])
    source = cp.CitationPool(entries=[_make_entry(cp, title="lower-doi",
                                                  doi="10.1/smith2023")])
    summary = cp.merge_pools(target, source)
    assert summary["skipped_duplicate"] == 1


# ---------------------------------------------------------------------------
# load_pool_from_paper_draft
# ---------------------------------------------------------------------------

def test_load_pool_from_paper_draft_reads_pool_json(cp, tmp_path):
    """A paper-writer draft directory has pool.json; reuse helper loads it."""
    paper_dir = tmp_path / "papers" / "draft_1"
    paper_dir.mkdir(parents=True)
    pool = cp.CitationPool(entries=[
        _make_entry(cp, title="X", doi="10.1/x"),
        _make_entry(cp, title="Y", doi="10.1/y"),
    ])
    (paper_dir / "pool.json").write_text(json.dumps(pool.to_dict()))
    loaded = cp.load_pool_from_paper_draft(paper_dir)
    assert len(loaded.entries) == 2


# ---------------------------------------------------------------------------
# CLI: reuse-from-paper subcommand
# ---------------------------------------------------------------------------

def test_cli_reuse_from_paper_creates_target_pool(cp, tmp_path):
    paper_dir = tmp_path / "papers" / "draft_1"
    paper_dir.mkdir(parents=True)
    pool = cp.CitationPool(entries=[_make_entry(cp, title="X", doi="10.1/x")])
    (paper_dir / "pool.json").write_text(json.dumps(pool.to_dict()))

    talk_dir = tmp_path / "talks" / "draft_1"
    rc = cp.main(["reuse-from-paper", str(paper_dir), str(talk_dir), "--quiet"])
    assert rc == 0
    out = talk_dir / "citation_pool.json"
    assert out.is_file()
    parsed = json.loads(out.read_text())
    titles = [e["title"] for e in parsed["entries"]]
    assert "X" in titles


def test_cli_reuse_from_paper_no_pool_in_paper_returns_0(cp, tmp_path):
    """Paper-writer draft has no pool yet — reuse is a no-op (rc 0)."""
    paper_dir = tmp_path / "papers" / "draft_1"
    paper_dir.mkdir(parents=True)
    talk_dir = tmp_path / "talks" / "draft_1"
    rc = cp.main(["reuse-from-paper", str(paper_dir), str(talk_dir), "--quiet"])
    assert rc == 0
    # No citation_pool.json should have been written
    assert not (talk_dir / "citation_pool.json").exists()


def test_cli_reuse_from_paper_missing_paper_dir_returns_2(cp, tmp_path):
    rc = cp.main(["reuse-from-paper",
                  str(tmp_path / "nope"),
                  str(tmp_path / "talks/draft_1"), "--quiet"])
    assert rc == 2


def test_cli_reuse_from_paper_merges_into_existing_target(cp, tmp_path):
    """If talk_dir already has a pool, reuse merges into it (no overwrite)."""
    paper_dir = tmp_path / "papers" / "draft_1"
    paper_dir.mkdir(parents=True)
    paper_pool = cp.CitationPool(entries=[
        _make_entry(cp, title="paper-entry", doi="10.1/p"),
    ])
    (paper_dir / "pool.json").write_text(json.dumps(paper_pool.to_dict()))

    talk_dir = tmp_path / "talks" / "draft_1"
    talk_dir.mkdir(parents=True)
    talk_pool = cp.CitationPool(entries=[
        _make_entry(cp, title="talk-entry", doi="10.1/t"),
    ])
    (talk_dir / "citation_pool.json").write_text(json.dumps(talk_pool.to_dict()))

    rc = cp.main(["reuse-from-paper", str(paper_dir), str(talk_dir), "--quiet"])
    assert rc == 0
    parsed = json.loads((talk_dir / "citation_pool.json").read_text())
    titles = [e["title"] for e in parsed["entries"]]
    assert "talk-entry" in titles
    assert "paper-entry" in titles


# ---------------------------------------------------------------------------
# Output filename: citation_pool.json (LAYOUT.md convention)
# ---------------------------------------------------------------------------

def test_serialize_writes_citation_pool_json(cp, tmp_path):
    pool = cp.CitationPool(entries=[_make_entry(cp, title="X", doi="10.1/x")])
    paths = cp.serialize_to_disk(pool, tmp_path)
    assert (tmp_path / "citation_pool.json").is_file()
    assert "citation_pool.json" in paths
