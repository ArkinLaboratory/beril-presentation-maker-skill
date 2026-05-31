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
    curated_figures.md emitted (canonical name as of v0.3.2.1; the
    legacy name `figures_curated.md` is no longer written)."""
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
    assert (out_dir / "curated_figures.md").is_file()
    # Legacy name must NOT be written (kills the v0.3.0–v0.3.2 duplicate)
    assert not (out_dir / "figures_curated.md").is_file()


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


# ===========================================================================
# v0.8 Tier A — curate_for_mode substory-aware per-substory floor (D-093)
# ===========================================================================
#
# When the caller passes substory_analyses, curate_for_mode must
# guarantee ≥1 figure per substory whose analyses cite a notebook
# with figures in the inventory. May exceed budget by up to
# N_substories (per-substory coverage wins per D-093). When
# substory_analyses is None, curator behavior is unchanged
# (paper-writer parity).


def test_curate_for_mode_unchanged_without_substory_analyses(cf, tmp_path):
    """Baseline: without substory_analyses, curate_for_mode behaves
    exactly as before — strict budget cap (target_count figures)."""
    figs = [
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(10)
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    sel = cf.curate_for_mode(inv, "talk-15")  # default target=4
    assert sel.target_count == 4
    assert len(sel.selected) == 4


def test_curate_for_mode_promotes_uncovered_substory_candidate(cf, tmp_path):
    """When a substory has 0 selected figures despite candidates in
    inventory, curate_for_mode promotes the highest-scoring candidate."""
    figs = [
        # Top 4 (would naturally be selected at talk-15 default 4):
        # all NB01-NB04 with REPORT tier
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(1, 5)
    ] + [
        # NB99 — only available for S2 — lower tier (notebook_md only)
        _make_figure(cf, "figures/NB99_y.png", ("notebook_md",)),
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    substories = {
        "S1": ["NB01_a.ipynb", "NB02_b.ipynb"],   # covered by top-4
        "S2": ["NB99_z.ipynb"],                    # NEEDS promotion
    }
    sel = cf.curate_for_mode(inv, "talk-15",
                             substory_analyses=substories)
    # Promoted: 4 baseline + 1 promotion for S2 = 5 selected
    assert len(sel.selected) == 5, (
        f"expected 5 selected (4 baseline + 1 S2 promotion); "
        f"got {len(sel.selected)}: {[f.path for f in sel.selected]}")
    paths = {f.path for f in sel.selected}
    assert "figures/NB99_y.png" in paths, (
        f"NB99 figure should be promoted for S2; selected: {paths}")


def test_curate_for_mode_skips_substory_with_no_inventory_candidate(cf, tmp_path):
    """A substory whose analyses cite a notebook with NO figures in
    inventory cannot be covered — curate_for_mode must NOT make
    something up. Selection stays at the budget."""
    figs = [
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(1, 4)  # NB01, NB02, NB03
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    substories = {
        "S1": ["NB01_a.ipynb"],   # covered
        "S2": ["NB99_z.ipynb"],   # NO candidate in inventory
    }
    sel = cf.curate_for_mode(inv, "talk-15",
                             substory_analyses=substories)
    # All 3 figures selected; no promotion (no NB99 in inv)
    assert len(sel.selected) == 3
    paths = {f.path for f in sel.selected}
    assert "figures/NB99_y.png" not in paths


def test_curate_for_mode_promotes_one_per_uncovered_substory(cf, tmp_path):
    """3 substories all uncovered → 3 promotions; final count = budget + 3."""
    figs = [
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(1, 5)
    ] + [
        _make_figure(cf, "figures/NB10_y.png", ("notebook_md",)),
        _make_figure(cf, "figures/NB11_y.png", ("notebook_md",)),
        _make_figure(cf, "figures/NB12_y.png", ("notebook_md",)),
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    substories = {
        "S1": ["NB01_a.ipynb"],     # covered (NB01 in top-4)
        "S2": ["NB10_a.ipynb"],     # promote
        "S3": ["NB11_b.ipynb"],     # promote
        "S4": ["NB12_c.ipynb"],     # promote
    }
    sel = cf.curate_for_mode(inv, "talk-15",
                             substory_analyses=substories)
    # 4 baseline + 3 promotions = 7
    assert len(sel.selected) == 7
    paths = {f.path for f in sel.selected}
    assert {"figures/NB10_y.png", "figures/NB11_y.png",
            "figures/NB12_y.png"}.issubset(paths)


def test_curate_for_mode_nb_id_matches_letter_suffix(cf, tmp_path):
    """NB04b_* and NB04h_* both group under NB04 (mirrors
    check_figure_provenance.py matching rule). A substory citing
    NB04b should be covered by a NB04h figure in inventory."""
    figs = [
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(1, 5)
    ] + [
        _make_figure(cf, "figures/NB04h_external.png", ("notebook_md",)),
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    # S2 cites NB04b — already covered by NB04_x in the baseline pick
    # (NB04 prefix matches both NB04 and NB04b/h), so NO promotion needed.
    substories = {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB04b_refit.ipynb"],
    }
    sel = cf.curate_for_mode(inv, "talk-15",
                             substory_analyses=substories)
    # 4 baseline; no promotion (NB04_x already covers S2 via NB04 prefix)
    assert len(sel.selected) == 4


def test_curate_for_mode_uses_highest_score_promotion(cf, tmp_path):
    """When multiple NB-id-matching candidates exist for an uncovered
    substory, the highest-scoring one is promoted."""
    figs = [
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(1, 5)
    ] + [
        # NB99 with low tier (filename only)
        _make_figure(cf, "figures/NB99_low.png", ()),
        # NB99 with REPORT tier (highest)
        _make_figure(cf, "figures/NB99_high.png", ("report",)),
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    substories = {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB99_z.ipynb"],
    }
    sel = cf.curate_for_mode(inv, "talk-15",
                             substory_analyses=substories)
    paths = {f.path for f in sel.selected}
    # The REPORT-tier one should be promoted, not the filename-only one
    assert "figures/NB99_high.png" in paths
    assert "figures/NB99_low.png" not in paths


def test_curate_for_mode_skips_substory_with_no_nb_ids(cf, tmp_path):
    """Substory with empty analyses list → no NB-ids → no promotion."""
    figs = [
        _make_figure(cf, f"figures/NB{i:02d}_x.png", ("report",))
        for i in range(1, 4)
    ]
    inv = _make_inventory(cf, tmp_path, figs)
    substories = {
        "S1": [],   # no notebooks cited
    }
    sel = cf.curate_for_mode(inv, "talk-15",
                             substory_analyses=substories)
    assert len(sel.selected) == 3


# ---------------------------------------------------------------------------
# _parse_substory_analyses_simple — helper used by --substories-path
# ---------------------------------------------------------------------------

def test_parse_substory_analyses_simple_extracts_notebook_filenames(
        cf, tmp_path):
    """Parse a minimal 02_substories.md fragment + extract NB filenames."""
    p = tmp_path / "02_substories.md"
    p.write_text(
        "# Substories\n"
        "\n"
        "### S1 — first arc\n"
        "**Critical analyses covered:**\n"
        "- A1: ... — REPORT.md §X / NB01_analysis.ipynb\n"
        "- A2: ... — REPORT.md §Y / NB02b_refit.ipynb\n"
        "\n"
        "### S2 — second arc\n"
        "**Critical analyses covered:**\n"
        "- A3: ... — REPORT.md §Z / NB99_other.ipynb\n",
        encoding="utf-8",
    )
    out = cf._parse_substory_analyses_simple(p)
    assert set(out.keys()) == {"S1", "S2"}
    assert "NB01_analysis.ipynb" in out["S1"]
    assert "NB02b_refit.ipynb" in out["S1"]
    assert out["S2"] == ["NB99_other.ipynb"]


def test_parse_substory_analyses_simple_returns_empty_on_missing_file(
        cf, tmp_path):
    out = cf._parse_substory_analyses_simple(tmp_path / "no_such.md")
    assert out == {}


def test_parse_substory_analyses_simple_v3_3_bare_token_fallback(
        cf, tmp_path):
    """v0.8 Tier G live discovery: v3.3 substory_design uses bare
    NB-id tokens (`NB02`, `NB04b`) rather than full `NBXX_name.ipynb`
    filenames. Without fallback, the curator's --substories-path
    forwarding silently produced empty NB-id sets per substory →
    per-substory floor never engaged. Pin the bare-token fallback so
    v3.3 output engages the floor properly.

    Format mirrors actual draft_8/narrative/02_substories.md content.
    """
    p = tmp_path / "02_substories.md"
    p.write_text(
        "### S1 — Ecotype stratification\n"
        "**Critical analyses covered:**\n"
        "- A1: K=4 ecotype framework — REPORT.md §Pillar 1; NB01b\n"
        "- A3: Longitudinal drift — REPORT.md §Pillar 1; NB02 / NB16\n",
        encoding="utf-8",
    )
    out = cf._parse_substory_analyses_simple(p)
    assert "S1" in out
    # All three bare-token NB references captured
    assert "NB01b" in out["S1"]
    assert "NB02" in out["S1"]
    assert "NB16" in out["S1"]


def test_parse_substory_analyses_simple_prefers_full_filename(
        cf, tmp_path):
    """When a line has both a full filename and bare tokens, the
    full filename wins (richer signal). Preserves v3/v3.1/v3.2
    behavior on backwards-compat decks."""
    p = tmp_path / "02_substories.md"
    p.write_text(
        "### S1 — first\n"
        "- A1: ... NB04b_refit.ipynb / NB99 / NB77 reference\n",
        encoding="utf-8",
    )
    out = cf._parse_substory_analyses_simple(p)
    # Only the full filename is captured (bare tokens on same line skipped)
    assert out["S1"] == ["NB04b_refit.ipynb"]


# ---------------------------------------------------------------------------
# --substories-path CLI flag wiring
# ---------------------------------------------------------------------------

def test_cli_curate_substories_path_flag_enables_floor(
        cf, tmp_path, capsys, monkeypatch):
    """CLI --substories-path forwards to curate_for_mode's
    substory_analyses arg; promotion behavior visible in stderr message."""
    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "figures").mkdir()
    # Create real figure files so extract_figures picks them up
    for i in range(1, 5):
        (proj / "figures" / f"NB{i:02d}_x.png").write_bytes(b"\x89PNG\r\n")
    (proj / "figures" / "NB99_y.png").write_bytes(b"\x89PNG\r\n")

    subs = proj / "02_substories.md"
    subs.write_text(
        "### S1 — a\n- NB01_a.ipynb\n"
        "### S2 — b\n- NB99_z.ipynb\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    rc = cf._cmd_curate([
        str(proj),
        "--mode", "talk-15",
        "--output-dir", str(out_dir),
        "--substories-path", str(subs),
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "per-substory floor enabled" in err, (
        f"expected stderr message about floor being enabled; got: {err}")
    # Curated should include NB99 (promoted for S2)
    curated_text = (out_dir / "curated_figures.md").read_text(encoding="utf-8")
    assert "NB99_y.png" in curated_text
