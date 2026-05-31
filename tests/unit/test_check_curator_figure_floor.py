"""Unit tests for tools/check_curator_figure_floor.py (v0.8/D-093).

Per-substory figure-floor validator. Fires
`substory_no_curated_figure_despite_candidates` (P1 soft-warning)
when a substory has 0 curated figures despite the inventory
containing NB-id-matching candidates for its analyses.

Validator behavior:
  - Parses 02_substories.md for substory analyses notebooks.
  - Parses curated_figures.md for the curator's shortlist.
  - Either parses figures_inventory.md (preferred) OR scans
    figures/ as a fallback.
  - NB-id matching uses prefix-with-optional-letter-suffix rule
    (NB04 matches both NB04 and NB04b/h) per
    check_figure_provenance.py convention.
  - Emits one finding per uncovered substory; never gates.

This validator is the SUSPENDERS in the D-093 belt-and-suspenders
pairing — curate_for_mode's per-substory floor is the belt.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                / "tools" / "check_curator_figure_floor.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cff():
    return _import("check_curator_figure_floor", VALIDATOR_PY)


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------

def test_parse_substory_analyses_extracts_per_substory_notebooks(cff, tmp_path):
    p = tmp_path / "02_substories.md"
    p.write_text(
        "### S1 — first\n"
        "**Critical analyses covered:**\n"
        "- A1: ... — REPORT.md §X / NB01_alpha.ipynb\n"
        "- A2: ... — REPORT.md §Y / NB02b_refit.ipynb\n"
        "\n"
        "### S2 — second\n"
        "**Critical analyses covered:**\n"
        "- A3: ... — NB99_z.ipynb\n",
        encoding="utf-8",
    )
    out = cff.parse_substory_analyses(p)
    assert set(out.keys()) == {"S1", "S2"}
    assert "NB01_alpha.ipynb" in out["S1"]
    assert "NB02b_refit.ipynb" in out["S1"]
    assert out["S2"] == ["NB99_z.ipynb"]


def test_parse_substory_analyses_returns_empty_on_missing_file(cff, tmp_path):
    assert cff.parse_substory_analyses(tmp_path / "no.md") == {}


def test_parse_curated_figures_extracts_backticked_paths(cff, tmp_path):
    p = tmp_path / "curated.md"
    p.write_text(
        "# Curated\n"
        "### 1. `figures/NB01_x.png` _(source-strength: REPORT)_\n"
        "### 2. `figures/NB02_y.png` _(source-strength: notebook)_\n",
        encoding="utf-8",
    )
    paths = cff.parse_curated_figures(p)
    assert paths == ["figures/NB01_x.png", "figures/NB02_y.png"]


def test_parse_inventory_figures_extracts_heading_paths(cff, tmp_path):
    p = tmp_path / "inv.md"
    p.write_text(
        "# Figures Inventory\n"
        "## Figures\n"
        "### `figures/NB01_x.png`\n"
        "_PNG, 12.3 KB_\n"
        "### `figures/NB99_y.png`\n",
        encoding="utf-8",
    )
    paths = cff.parse_inventory_figures(p)
    assert paths == ["figures/NB01_x.png", "figures/NB99_y.png"]


def test_scan_figures_dir_returns_relative_paths(cff, tmp_path):
    figs = tmp_path / "figures"
    figs.mkdir()
    (figs / "NB01_x.png").write_bytes(b"\x89PNG")
    (figs / "NB99_y.png").write_bytes(b"\x89PNG")
    (figs / "not_an_image.txt").write_text("nope")
    out = cff.scan_figures_dir(figs)
    assert out == ["figures/NB01_x.png", "figures/NB99_y.png"]


def test_scan_figures_dir_returns_empty_on_missing(cff, tmp_path):
    assert cff.scan_figures_dir(tmp_path / "no_such") == []


# ---------------------------------------------------------------------------
# NB-id helpers
# ---------------------------------------------------------------------------

def test_nb_ids_normalize_letter_suffix(cff):
    assert cff._nb_ids("NB04b_refit.ipynb") == {"NB04"}
    assert cff._nb_ids("NB04h_external.png") == {"NB04"}
    assert cff._nb_ids("figures/NB12_x.png") == {"NB12"}


def test_nb_ids_handle_no_match(cff):
    assert cff._nb_ids("no_nb_id_here.png") == set()


def test_figures_by_nb_id_groups_by_prefix(cff):
    paths = ["figures/NB01_a.png", "figures/NB04b_x.png", "figures/NB04h_y.png"]
    idx = cff.figures_by_nb_id(paths)
    assert set(idx.keys()) == {"NB01", "NB04"}
    assert idx["NB04"] == ["figures/NB04b_x.png", "figures/NB04h_y.png"]


def test_substory_nb_ids_collects_normalized(cff):
    out = cff.substory_nb_ids(
        ["NB01_a.ipynb", "NB04b_refit.ipynb", "NB04h_other.ipynb"])
    assert out == {"NB01", "NB04"}


# ---------------------------------------------------------------------------
# check_figure_floor — happy path
# ---------------------------------------------------------------------------

def _write_substories(tmp_path, mapping: dict[str, list[str]]) -> Path:
    """Helper to write a substories MD with given mapping."""
    p = tmp_path / "02_substories.md"
    body = ["# Substories\n"]
    for sid, nbs in mapping.items():
        body.append(f"### {sid} — arc\n")
        body.append("**Critical analyses covered:**\n")
        for nb in nbs:
            body.append(f"- A: ... / {nb}\n")
        body.append("\n")
    p.write_text("".join(body), encoding="utf-8")
    return p


def _write_curated(tmp_path, figure_paths: list[str]) -> Path:
    """Helper to write a curated MD with given figure paths."""
    p = tmp_path / "curated_figures.md"
    body = ["# Curated\n"]
    for i, fp in enumerate(figure_paths, start=1):
        body.append(f"### {i}. `{fp}` _(source-strength: x)_\n")
    p.write_text("".join(body), encoding="utf-8")
    return p


def _write_inventory(tmp_path, figure_paths: list[str]) -> Path:
    p = tmp_path / "figures_inventory.md"
    body = ["# Inventory\n## Figures\n"]
    for fp in figure_paths:
        body.append(f"### `{fp}`\n")
    p.write_text("".join(body), encoding="utf-8")
    return p


def test_check_figure_floor_no_findings_when_all_covered(cff, tmp_path):
    """All substories have ≥1 curated figure matching their NB-ids → no findings."""
    subs = _write_substories(tmp_path, {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB02_b.ipynb"],
    })
    curated = _write_curated(tmp_path, [
        "figures/NB01_x.png", "figures/NB02_y.png"])
    inv = _write_inventory(tmp_path, [
        "figures/NB01_x.png", "figures/NB02_y.png",
        "figures/NB99_z.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    assert report.findings == []
    assert report.summary["n_substories_uncovered"] == 0
    assert report.summary["coverage_rate"] == 1.0


def test_check_figure_floor_emits_finding_when_substory_uncovered(cff, tmp_path):
    """S2's analyses cite NB99; inventory has NB99 figure; curated doesn't.
    Validator emits substory_no_curated_figure_despite_candidates."""
    subs = _write_substories(tmp_path, {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB99_z.ipynb"],
    })
    curated = _write_curated(tmp_path, [
        "figures/NB01_x.png"])   # NB99 missing from curated
    inv = _write_inventory(tmp_path, [
        "figures/NB01_x.png", "figures/NB99_y.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.kind == "substory_no_curated_figure_despite_candidates"
    assert f.severity == "soft-warning"
    assert f.substory_id == "S2"
    assert f.evidence["candidate_nb_ids"] == ["NB99"]
    assert "figures/NB99_y.png" in f.evidence["candidate_figures"]


def test_check_figure_floor_no_finding_when_no_candidate_in_inventory(
        cff, tmp_path):
    """Substory cites NB99 but inventory has nothing — can't be 'uncovered'
    because there's nothing to cover. Finding is suppressed (it's the
    DIFFERENT failure mode of 'no figure exists', not 'curator dropped')."""
    subs = _write_substories(tmp_path, {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB99_z.ipynb"],
    })
    curated = _write_curated(tmp_path, ["figures/NB01_x.png"])
    inv = _write_inventory(tmp_path, ["figures/NB01_x.png"])   # no NB99
    report = cff.check_figure_floor(subs, curated, inv)
    assert report.findings == []
    assert report.summary["n_substories_no_candidates"] == 1


def test_check_figure_floor_nb_id_letter_suffix_match(cff, tmp_path):
    """S2 cites NB04b_refit; curated has NB04h_external. Same NB-prefix
    NB04 → coverage; no finding."""
    subs = _write_substories(tmp_path, {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB04b_refit.ipynb"],
    })
    curated = _write_curated(tmp_path, [
        "figures/NB01_x.png", "figures/NB04h_external.png"])
    inv = _write_inventory(tmp_path, [
        "figures/NB01_x.png", "figures/NB04h_external.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    assert report.findings == []


def test_check_figure_floor_falls_back_to_figures_dir_scan(cff, tmp_path):
    """When inventory MD is missing, validator falls back to scanning
    figures/ on disk."""
    subs = _write_substories(tmp_path, {"S1": ["NB99_z.ipynb"]})
    curated = _write_curated(tmp_path, [])   # empty curated
    figs_dir = tmp_path / "figures"
    figs_dir.mkdir()
    (figs_dir / "NB99_y.png").write_bytes(b"\x89PNG")
    report = cff.check_figure_floor(
        subs, curated, inventory_figures_path=None, figures_dir=figs_dir)
    assert len(report.findings) == 1
    assert report.findings[0].substory_id == "S1"


def test_check_figure_floor_skips_substory_with_no_nb_ids(cff, tmp_path):
    """Substory with no NB-ids in its analyses → counted as 'no_candidates'."""
    subs = _write_substories(tmp_path, {"S1": []})
    curated = _write_curated(tmp_path, [])
    inv = _write_inventory(tmp_path, ["figures/NB99_y.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    assert report.findings == []
    assert report.summary["n_substories_no_candidates"] == 1


def test_check_figure_floor_multiple_uncovered_emits_one_per_substory(
        cff, tmp_path):
    """S2 + S3 both uncovered → 2 findings, one per substory."""
    subs = _write_substories(tmp_path, {
        "S1": ["NB01_a.ipynb"],
        "S2": ["NB99_z.ipynb"],
        "S3": ["NB77_w.ipynb"],
    })
    curated = _write_curated(tmp_path, ["figures/NB01_x.png"])
    inv = _write_inventory(tmp_path, [
        "figures/NB01_x.png", "figures/NB99_y.png", "figures/NB77_y.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    assert len(report.findings) == 2
    sids = sorted(f.substory_id for f in report.findings)
    assert sids == ["S2", "S3"]


def test_check_figure_floor_summary_counts_correct(cff, tmp_path):
    subs = _write_substories(tmp_path, {
        "S1": ["NB01_a.ipynb"],     # covered
        "S2": ["NB99_z.ipynb"],     # uncovered (candidate exists, not curated)
        "S3": ["NB77_w.ipynb"],     # uncovered
        "S4": ["NB88_v.ipynb"],     # no_candidates
        "S5": [],                   # no_candidates (no NB ids)
    })
    curated = _write_curated(tmp_path, ["figures/NB01_x.png"])
    inv = _write_inventory(tmp_path, [
        "figures/NB01_x.png", "figures/NB99_y.png", "figures/NB77_y.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    assert report.summary["n_substories_with_candidates"] == 3
    assert report.summary["n_substories_uncovered"] == 2
    assert report.summary["n_substories_no_candidates"] == 2
    # coverage = (3 - 2) / 3 = 0.333...
    assert abs(report.summary["coverage_rate"] - (1 / 3)) < 0.01


def test_check_figure_floor_handles_missing_inputs(cff, tmp_path):
    """Missing substories or curated files → empty findings (defensive)."""
    report = cff.check_figure_floor(
        tmp_path / "no_subs.md",
        tmp_path / "no_curated.md",
    )
    assert report.findings == []
    assert report.n_substories == 0


def test_to_dict_serializable(cff, tmp_path):
    """Report.to_dict() produces JSON-serializable output."""
    subs = _write_substories(tmp_path, {"S1": ["NB99_z.ipynb"]})
    curated = _write_curated(tmp_path, [])
    inv = _write_inventory(tmp_path, ["figures/NB99_y.png"])
    report = cff.check_figure_floor(subs, curated, inv)
    payload = report.to_dict()
    # Must round-trip through json
    serialized = json.dumps(payload)
    restored = json.loads(serialized)
    assert restored["schema_version"] == "curator-figure-floor.v1"
    assert restored["findings"][0]["kind"] == \
        "substory_no_curated_figure_despite_candidates"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_writes_audit_json_to_draft_dir(cff, tmp_path, capsys):
    """`--draft-dir` causes the audit JSON to land at
    DRAFT_DIR/audit/curator_figure_floor.json."""
    proj = tmp_path / "proj"
    proj.mkdir()
    figs = proj / "figures"
    figs.mkdir()
    (figs / "NB99_y.png").write_bytes(b"\x89PNG")

    subs = proj / "02_substories.md"
    subs.write_text(
        "### S1 — a\n- NB99_z.ipynb\n", encoding="utf-8")
    curated = proj / "curated_figures.md"
    curated.write_text("# empty\n", encoding="utf-8")

    draft = tmp_path / "draft_1"

    rc = cff.main([
        "--project-dir", str(proj),
        "--substories", str(subs),
        "--curated-figures", str(curated),
        "--draft-dir", str(draft),
    ])
    assert rc == 0
    out_json = draft / "audit" / "curator_figure_floor.json"
    assert out_json.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "curator-figure-floor.v1"
    assert len(payload["findings"]) == 1


def test_cli_writes_audit_json_to_stdout_without_draft_dir(
        cff, tmp_path, capsys):
    """No --draft-dir + no --output → stdout."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "figures").mkdir()
    subs = proj / "02_substories.md"
    subs.write_text("# empty\n", encoding="utf-8")
    curated = proj / "curated_figures.md"
    curated.write_text("# empty\n", encoding="utf-8")

    rc = cff.main([
        "--project-dir", str(proj),
        "--substories", str(subs),
        "--curated-figures", str(curated),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "curator-figure-floor.v1"


def test_cli_returns_2_on_missing_project_dir(cff, tmp_path):
    rc = cff.main([
        "--project-dir", str(tmp_path / "no_such"),
        "--substories", str(tmp_path / "subs.md"),
        "--curated-figures", str(tmp_path / "cur.md"),
    ])
    assert rc == 2
