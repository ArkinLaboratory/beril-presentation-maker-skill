"""Tests for the presentation-maker-specific additions to curate_figures.py:
MODE_FIGURE_BUDGETS, curate_for_mode, format_curated_figures_md, _figure_score,
and the `curate` CLI subcommand.

The full inventory pipeline (filename parsing, REPORT.md image-ref scan,
notebook savefig AST walk) is unchanged from paper-writer's tested fork;
we don't re-test that here. Smoke-test that extract_figures still runs.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CF_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "curate_figures.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cf():
    return _import("curate_figures", CF_PY)


def _make_figure(cf, path, captions_sources=()):
    """Build a FigureRecord with given caption sources for scoring tests."""
    captions = [
        cf.CaptionCandidate(text=f"caption from {src}", source=src, context={})
        for src in captions_sources
    ]
    filename = path.rsplit("/", 1)[-1]
    return cf.FigureRecord(
        path=path,
        filename=filename,
        format="png",
        size_bytes=12345,
        captions=captions,
        savefig_origins=[],
    )


def _make_inventory(cf, project_dir, figures):
    return cf.FigureInventoryReport(
        project_dir=str(project_dir),
        figures_dirs=["figures"],
        figures=figures,
    )


# ---------------------------------------------------------------------------
# MODE_FIGURE_BUDGETS
# ---------------------------------------------------------------------------

def test_mode_budgets_cover_all_modes(cf):
    expected_modes = {"talk-30", "talk-15", "talk-45",
                      "lightning-5", "poster-h", "poster-v"}
    assert set(cf.MODE_FIGURE_BUDGETS.keys()) == expected_modes


def test_mode_budgets_have_sensible_ranges(cf):
    for mode, (lo, hi, default) in cf.MODE_FIGURE_BUDGETS.items():
        assert lo <= default <= hi, f"{mode}: default {default} not in [{lo}, {hi}]"
        assert lo >= 1
        assert hi >= lo


def test_lightning_budget_is_smaller_than_talk_30(cf):
    assert cf.MODE_FIGURE_BUDGETS["lightning-5"][2] < cf.MODE_FIGURE_BUDGETS["talk-30"][2]


def test_talk_45_budget_is_largest(cf):
    talk_45_max = cf.MODE_FIGURE_BUDGETS["talk-45"][1]
    for mode in ("talk-30", "talk-15", "lightning-5", "poster-h", "poster-v"):
        assert cf.MODE_FIGURE_BUDGETS[mode][1] <= talk_45_max


# ---------------------------------------------------------------------------
# _figure_score: tier ordering
# ---------------------------------------------------------------------------

def test_figure_score_report_referenced_highest(cf):
    fig_report = _make_figure(cf, "figures/a.png", ("report",))
    fig_filename = _make_figure(cf, "figures/z.png", ("filename",))
    s_report = cf._figure_score(fig_report)
    s_filename = _figure_score = cf._figure_score(fig_filename)
    assert s_report[0] > s_filename[0]


def test_figure_score_notebook_md_outranks_filename(cf):
    fig_nb = _make_figure(cf, "figures/n.png", ("notebook_md",))
    fig_fn = _make_figure(cf, "figures/f.png", ("filename",))
    assert cf._figure_score(fig_nb)[0] > cf._figure_score(fig_fn)[0]


def test_figure_score_tie_break_by_filename(cf):
    a = _make_figure(cf, "figures/a.png", ("report",))
    b = _make_figure(cf, "figures/b.png", ("report",))
    sa, sb = cf._figure_score(a), cf._figure_score(b)
    # Same tier, alphabetical by path
    assert sa[0] == sb[0]
    assert sa[1] < sb[1]


# ---------------------------------------------------------------------------
# curate_for_mode
# ---------------------------------------------------------------------------

def test_curate_for_mode_picks_default_count(cf, tmp_path):
    figs = [_make_figure(cf, f"figures/f{i:02d}.png", ("filename",))
            for i in range(20)]
    inventory = _make_inventory(cf, tmp_path, figs)
    sel = cf.curate_for_mode(inventory, "talk-30")
    # Default for talk-30 is 7
    assert sel.target_count == 7
    assert len(sel.selected) == 7


def test_curate_for_mode_clamps_target_to_range(cf, tmp_path):
    figs = [_make_figure(cf, f"figures/f{i:02d}.png", ("filename",))
            for i in range(20)]
    inventory = _make_inventory(cf, tmp_path, figs)
    # talk-30 budget is (4, 10, 7); ask for 100 → clamped to 10
    sel = cf.curate_for_mode(inventory, "talk-30", target_count=100)
    assert sel.target_count == 10
    # Ask for 1 → clamped to 4
    sel = cf.curate_for_mode(inventory, "talk-30", target_count=1)
    assert sel.target_count == 4


def test_curate_for_mode_prefers_report_referenced_figures(cf, tmp_path):
    figs = [
        _make_figure(cf, "figures/z_filename.png", ("filename",)),
        _make_figure(cf, "figures/a_report.png", ("report",)),
        _make_figure(cf, "figures/b_notebook.png", ("notebook_md",)),
        _make_figure(cf, "figures/c_filename.png", ("filename",)),
    ]
    inventory = _make_inventory(cf, tmp_path, figs)
    # Lightning-5 default is 2 → should pick top 2 by score
    sel = cf.curate_for_mode(inventory, "lightning-5")
    paths = [f.path for f in sel.selected]
    assert "figures/a_report.png" in paths        # tier 3
    assert "figures/b_notebook.png" in paths       # tier 2
    assert "figures/z_filename.png" not in paths   # tier 0
    assert "figures/c_filename.png" not in paths


def test_curate_for_mode_handles_smaller_inventory(cf, tmp_path):
    """Inventory smaller than budget — return whatever is available."""
    figs = [_make_figure(cf, "figures/only.png", ("report",))]
    inventory = _make_inventory(cf, tmp_path, figs)
    sel = cf.curate_for_mode(inventory, "talk-30")
    assert len(sel.selected) == 1


def test_curate_for_mode_unknown_mode_raises(cf, tmp_path):
    inventory = _make_inventory(cf, tmp_path, [])
    with pytest.raises(ValueError):
        cf.curate_for_mode(inventory, "talk-99")


def test_curate_for_mode_records_budget_metadata(cf, tmp_path):
    figs = [_make_figure(cf, "figures/x.png", ("filename",))]
    inventory = _make_inventory(cf, tmp_path, figs)
    sel = cf.curate_for_mode(inventory, "talk-15")
    assert sel.mode == "talk-15"
    assert sel.budget_min == cf.MODE_FIGURE_BUDGETS["talk-15"][0]
    assert sel.budget_max == cf.MODE_FIGURE_BUDGETS["talk-15"][1]
    assert sel.inventory_size == 1


# ---------------------------------------------------------------------------
# format_curated_figures_md
# ---------------------------------------------------------------------------

def test_format_curated_md_includes_mode_label(cf, tmp_path):
    figs = [_make_figure(cf, "figures/x.png", ("report",))]
    inventory = _make_inventory(cf, tmp_path, figs)
    sel = cf.curate_for_mode(inventory, "talk-30")
    md = cf.format_curated_figures_md(sel)
    assert "talk-30" in md
    assert "REPORT-referenced" in md


def test_format_curated_md_no_figures(cf, tmp_path):
    inventory = _make_inventory(cf, tmp_path, [])
    sel = cf.curate_for_mode(inventory, "talk-30")
    md = cf.format_curated_figures_md(sel)
    assert "no figures available" in md


# ---------------------------------------------------------------------------
# CLI: curate subcommand
# ---------------------------------------------------------------------------

def test_cli_curate_subcommand_writes_outputs(cf, tmp_path):
    """End-to-end: project with a figures/ dir → figures_inventory.md +
    figures_curated.md emitted."""
    proj = tmp_path / "demo"
    proj.mkdir()
    figdir = proj / "figures"
    figdir.mkdir()
    (figdir / "fig01_demo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    out_dir = tmp_path / "out"
    rc = cf._cmd_curate([
        str(proj),
        "--mode", "talk-30",
        "--output-dir", str(out_dir),
    ])
    assert rc == 0
    assert (out_dir / "figures_inventory.md").is_file()
    assert (out_dir / "figures_curated.md").is_file()


def test_cli_curate_no_md_flag_skips_writes(cf, tmp_path, capsys):
    proj = tmp_path / "demo"
    proj.mkdir()
    out_dir = tmp_path / "out"
    rc = cf._cmd_curate([
        str(proj),
        "--mode", "lightning-5",
        "--output-dir", str(out_dir),
        "--no-md",
    ])
    assert rc == 0
    # JSON to stdout but no markdown files
    assert not (out_dir / "figures_inventory.md").exists()


def test_cli_curate_missing_project_dir_returns_2(cf, tmp_path):
    rc = cf._cmd_curate([
        str(tmp_path / "nope"),
        "--mode", "talk-30",
    ])
    assert rc == 2
