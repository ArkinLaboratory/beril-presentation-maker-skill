"""Unit tests for tools/validate_claim_inventory.py.

Authored for presentation-maker v0.4 M1 (2026-05-12). The validator
is vendored byte-portable from paper-writer; re-vendored 2026-05-21 to
paper-writer v1.0.0 (validator 0.2.0-stage3-tierI), which added the
Stage 3 Tier I notebook-repair pass. Coverage below combines the
original Stage 1 base-behavior tests with repair-pass tests adapted
from paper-writer's own suite.

Coverage:
  - Valid notebook resolves (no row changes).
  - Fabricated notebook is cleared + notes prefixed with `unresolved-notebook:`.
  - Idempotent re-run (already-marked rows skipped).
  - Tolerates `notebooks/` prefix variants the LLM emits.
  - Empty source_notebook rows pass through unchanged.
  - Audit JSON written when --audit supplied.
  - Total / updated / already-marked counts in diagnostic.
  - Malformed TSV raises ValueError.
  - Missing TSV raises FileNotFoundError.
  - CLI returns 2 on missing --project-root directory.
  - Existing notes are preserved when prefixing.
  - Stage 3 Tier I repair pass: bare stem / parenthetical /
    wrong-descriptive-suffix / missing-extension recovered via an
    unambiguous notebook-ID match.
  - Repair pass still clears placeholders, slash-joined, two-notebook,
    and unknown-id values.
  - New diagnostic fields rows_repaired_this_run + repaired_notebooks.
  - _notebook_id helper id extraction.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from beril_presentation_maker.skill.tools import validate_claim_inventory as vci


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TSV_HEADER = [
    "claim_id", "claim_text", "source_notebook", "source_cell",
    "figure_or_table", "effect_size_present", "ci_present",
    "pvalue_present", "notes",
]


def _write_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=TSV_HEADER, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for r in rows:
            for k in TSV_HEADER:
                r.setdefault(k, "")
            writer.writerow(r)


def _read_tsv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _make_project(tmp_path: Path, notebooks: list[str]) -> Path:
    """Build a synthetic project root with `notebooks/<name>.ipynb` stubs."""
    proj = tmp_path / "synthetic_project"
    nb_dir = proj / "notebooks"
    nb_dir.mkdir(parents=True, exist_ok=True)
    for nb in notebooks:
        (nb_dir / nb).write_text("{}", encoding="utf-8")
    return proj


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------

def test_valid_notebook_resolves(tmp_path):
    proj = _make_project(tmp_path, ["NB01_intro.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C001", "claim_text": "x",
         "source_notebook": "notebooks/NB01_intro.ipynb",
         "source_cell": "14"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_updated_this_run"] == 0
    assert diag["unique_invalid_notebooks"] == []
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == "notebooks/NB01_intro.ipynb"
    assert rows[0]["notes"] == ""


def test_fabricated_notebook_cleared_and_marked(tmp_path):
    proj = _make_project(tmp_path, ["NB01_intro.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C002", "claim_text": "fabricated",
         "source_notebook": "notebooks/NB99_fabricated.ipynb",
         "source_cell": "5"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_updated_this_run"] == 1
    assert "notebooks/NB99_fabricated.ipynb" in diag["unique_invalid_notebooks"]
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == ""
    assert rows[0]["notes"].startswith(vci.UNRESOLVED_PREFIX)
    assert "NB99_fabricated.ipynb" in rows[0]["notes"]


def test_idempotent_rerun(tmp_path):
    """File-state idempotency: second pass produces byte-identical output.

    Upstream-validator semantic note: when the first pass clears
    source_notebook, the second pass sees an empty source_notebook
    and short-circuits on `if not nb: continue` BEFORE reaching the
    already-marked check. So `rows_already_marked_unresolved` reports 0
    on pass 2 even though the row IS effectively already-marked. The
    `rows_updated_this_run == 0` is the load-bearing idempotency
    assertion; the file-state snapshot equality is the byte-level proof.
    """
    proj = _make_project(tmp_path, ["NB01_intro.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C003", "claim_text": "x",
         "source_notebook": "notebooks/NB99_fabricated.ipynb"},
    ])
    # First pass: marks
    vci.validate_tsv(tsv_path=tsv, project_root=proj)
    snapshot_after_first = _read_tsv(tsv)
    # Second pass: byte-identical output, no new updates
    diag2 = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag2["rows_updated_this_run"] == 0
    snapshot_after_second = _read_tsv(tsv)
    assert snapshot_after_first == snapshot_after_second


def test_tolerates_missing_notebooks_prefix(tmp_path):
    """LLM sometimes emits bare 'NB01.ipynb', sometimes 'notebooks/NB01.ipynb'."""
    proj = _make_project(tmp_path, ["NB01.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C004", "claim_text": "x",
         "source_notebook": "NB01.ipynb"},  # no notebooks/ prefix
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_updated_this_run"] == 0  # resolved despite missing prefix


def test_empty_source_notebook_passes_through(tmp_path):
    proj = _make_project(tmp_path, ["NB01.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C005", "claim_text": "no notebook", "source_notebook": ""},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_updated_this_run"] == 0
    assert diag["rows_with_source_notebook"] == 0


def test_preserves_existing_notes_when_marking(tmp_path):
    proj = _make_project(tmp_path, ["NB01.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C006", "claim_text": "fabricated with note",
         "source_notebook": "notebooks/NB99.ipynb",
         "notes": "primary endpoint"},
    ])
    vci.validate_tsv(tsv_path=tsv, project_root=proj)
    rows = _read_tsv(tsv)
    assert rows[0]["notes"].startswith(vci.UNRESOLVED_PREFIX)
    assert "primary endpoint" in rows[0]["notes"]


# ---------------------------------------------------------------------------
# Diagnostic + audit JSON
# ---------------------------------------------------------------------------

def test_audit_json_written_when_path_supplied(tmp_path):
    proj = _make_project(tmp_path, ["NB01.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    audit = tmp_path / "audit" / "claim_inventory_validation.json"
    _write_tsv(tsv, [
        {"claim_id": "C007", "claim_text": "x",
         "source_notebook": "notebooks/NB99.ipynb"},
    ])
    vci.validate_tsv(tsv_path=tsv, project_root=proj, audit_path=audit)
    assert audit.is_file()
    parsed = json.loads(audit.read_text(encoding="utf-8"))
    assert parsed["tool"] == "validate_claim_inventory"
    assert parsed["unique_invalid_notebooks"] == ["notebooks/NB99.ipynb"]
    assert parsed["rows_updated_this_run"] == 1


def test_diagnostic_counts(tmp_path):
    """Diagnostic counter semantics: counts computed AFTER validation.

    `rows_with_source_notebook` reports the count after fabricated rows
    have had their source_notebook cleared. With 4 rows (2 valid, 1
    fabricated, 1 empty), pass-1 clears the fabricated row's notebook,
    leaving 2 rows with non-empty source_notebook. This is the upstream
    semantic; the counter reports post-validation state, not pre-state.
    """
    proj = _make_project(tmp_path, ["NB01.ipynb", "NB02.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C008", "source_notebook": "notebooks/NB01.ipynb"},
        {"claim_id": "C009", "source_notebook": "notebooks/NB99.ipynb"},  # bad
        {"claim_id": "C010", "source_notebook": ""},
        {"claim_id": "C011", "source_notebook": "notebooks/NB02.ipynb"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["total_rows"] == 4
    # 2 valid notebooks remain after the fabricated row is cleared.
    assert diag["rows_with_source_notebook"] == 2
    assert diag["rows_updated_this_run"] == 1
    assert len(diag["unique_invalid_notebooks"]) == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_missing_tsv_raises_filenotfound(tmp_path):
    proj = _make_project(tmp_path, [])
    with pytest.raises(FileNotFoundError):
        vci.validate_tsv(tsv_path=tmp_path / "nope.tsv", project_root=proj)


def test_malformed_tsv_no_header_raises_valueerror(tmp_path):
    proj = _make_project(tmp_path, [])
    tsv = tmp_path / "malformed.tsv"
    tsv.write_text("", encoding="utf-8")  # zero rows; no header
    with pytest.raises(ValueError):
        vci.validate_tsv(tsv_path=tsv, project_root=proj)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_exits_2_on_missing_project_root(tmp_path):
    """CLI smoke-test via subprocess: missing project root → exit 2."""
    proj_nonexistent = tmp_path / "does_not_exist"
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [])
    validator_path = (
        Path(__file__).resolve().parents[2]
        / "src" / "beril_presentation_maker" / "skill"
        / "tools" / "validate_claim_inventory.py"
    )
    proc = subprocess.run(
        [sys.executable, str(validator_path),
         "--tsv", str(tsv),
         "--project-root", str(proj_nonexistent)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr


def test_cli_success_exits_0(tmp_path):
    proj = _make_project(tmp_path, ["NB01.ipynb"])
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [{"claim_id": "C012", "source_notebook": "notebooks/NB01.ipynb"}])
    validator_path = (
        Path(__file__).resolve().parents[2]
        / "src" / "beril_presentation_maker" / "skill"
        / "tools" / "validate_claim_inventory.py"
    )
    proc = subprocess.run(
        [sys.executable, str(validator_path),
         "--tsv", str(tsv),
         "--project-root", str(proj)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "validate_claim_inventory:" in proc.stderr


# ---------------------------------------------------------------------------
# Stage 3 Tier I — notebook-repair pass (re-vendored 2026-05-21)
# ---------------------------------------------------------------------------
# The repair pass recovers source_notebook values that do not resolve
# as-is but map UNAMBIGUOUSLY to a real notebook (bare stem,
# stem-plus-parenthetical, wrong-descriptive-suffix, missing-extension).
# Genuinely-invented names, placeholders, slash-joined values, and values
# naming two notebooks still get cleared. See validator docstring.

# Notebook set with unique NBxx[L] ids — every repair below depends on
# the id mapping to exactly one real notebook. NB04 / NB04b / NB04c are
# three DISTINCT ids (NB04, NB04B, NB04C); a bare "NB04" must resolve to
# NB04_* only, never to a sibling.
_SIBLING_NOTEBOOKS = [
    "NB00_data_audit.ipynb",
    "NB01_ecotype_training.ipynb",
    "NB01b_ecotype_refit.ipynb",
    "NB04_within_ecotype_DA.ipynb",
    "NB04b_analytical_rigor_repair.ipynb",
    "NB04c_rigor_repair_completion.ipynb",
    "NB07a_pathway_DA_H3a_falsifiability.ipynb",
    "NB12_phage_targetability.ipynb",
]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("NB04", "NB04"),
        ("NB07a", "NB07A"),                          # uppercased
        ("NB07a_pathway_DA", "NB07A"),               # strips descriptive suffix
        ("NB12_phage_targetability.ipynb", "NB12"),
        ("nb04b", "NB04B"),                          # case-insensitive
        ("—", None),                                 # placeholder, no id
        ("", None),
        ("random_file.ipynb", None),                 # no NB id
    ],
)
def test_notebook_id_extraction(value, expected):
    """_notebook_id extracts the canonical NBxx[L] id, uppercased."""
    assert vci._notebook_id(value) == expected


def test_repair_bare_stem(tmp_path):
    """`NB04` → NB04_within_ecotype_DA.ipynb via unique ID match."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [{"claim_id": "C001", "source_notebook": "NB04"}])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 1
    assert diag["rows_updated_this_run"] == 0
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == "NB04_within_ecotype_DA.ipynb"
    assert rows[0]["notes"].startswith(vci.REPAIRED_PREFIX)


def test_repair_stem_with_parenthetical(tmp_path):
    """`NB07a (pathway_DA)` → trailing paren stripped → unique ID NB07A."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C001", "source_notebook": "NB07a (pathway_DA)"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 1
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == "NB07a_pathway_DA_H3a_falsifiability.ipynb"


def test_repair_wrong_descriptive_suffix(tmp_path):
    """draft_8-style `NB07a_pathway_DA.ipynb` → ID NB07A → unique match."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C001", "source_notebook": "NB07a_pathway_DA.ipynb"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 1
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == "NB07a_pathway_DA_H3a_falsifiability.ipynb"


def test_repair_missing_extension(tmp_path):
    """`NB01_ecotype_training` (no .ipynb) → exact filename + extension."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C001", "source_notebook": "NB01_ecotype_training"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 1
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == "NB01_ecotype_training.ipynb"


def test_repair_distinguishes_stem_from_suffixed_siblings(tmp_path):
    """`NB04` resolves to NB04_*, NOT NB04b_* / NB04c_* — exact-ID match,
    not arbitrary prefix. NB04 / NB04b / NB04c are three distinct ids."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C001", "source_notebook": "NB04"},
        {"claim_id": "C002", "source_notebook": "NB04b"},
        {"claim_id": "C003", "source_notebook": "NB04c"},
    ])
    vci.validate_tsv(tsv_path=tsv, project_root=proj)
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == "NB04_within_ecotype_DA.ipynb"
    assert rows[1]["source_notebook"] == "NB04b_analytical_rigor_repair.ipynb"
    assert rows[2]["source_notebook"] == "NB04c_rigor_repair_completion.ipynb"


@pytest.mark.parametrize("placeholder", ["—", "-", "N/A", "n/a", "TBD", "None"])
def test_repair_pass_still_clears_placeholders(tmp_path, placeholder):
    """Placeholder values are hard-rejected — cleared, never repaired."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [{"claim_id": "C001", "source_notebook": placeholder}])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 0
    assert diag["rows_updated_this_run"] == 1
    rows = _read_tsv(tsv)
    assert rows[0]["source_notebook"] == ""
    assert rows[0]["notes"].startswith(vci.UNRESOLVED_PREFIX)


def test_repair_pass_still_clears_slash_joined(tmp_path):
    """`NB04b/c` names two notebooks ambiguously — must NOT be repaired."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [{"claim_id": "C001", "source_notebook": "NB04b/c"}])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 0
    assert diag["rows_updated_this_run"] == 1
    assert _read_tsv(tsv)[0]["source_notebook"] == ""


def test_repair_pass_still_clears_value_naming_two_notebooks(tmp_path):
    """A value with >1 NBxx occurrence cannot be disambiguated."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [{"claim_id": "C001", "source_notebook": "NB04 and NB07a"}])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 0
    assert diag["rows_updated_this_run"] == 1


def test_repair_pass_still_clears_unknown_notebook_id(tmp_path):
    """`NB99` has no matching real notebook — stays cleared."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [
        {"claim_id": "C001", "source_notebook": "NB99_imaginary.ipynb"},
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    assert diag["rows_repaired_this_run"] == 0
    assert diag["rows_updated_this_run"] == 1
    assert _read_tsv(tsv)[0]["source_notebook"] == ""


def test_repair_diagnostic_fields_present(tmp_path):
    """New Tier I diagnostic fields: rows_repaired_this_run +
    repaired_notebooks. Additive — extract_claims.py does not parse them,
    but the audit JSON must carry them for downstream M2 architect logic
    (M1_PUNCH_LIST.md Tier F4)."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    audit = tmp_path / "audit" / "claim_inventory_validation.json"
    _write_tsv(tsv, [
        {"claim_id": "C001", "source_notebook": "NB00_data_audit.ipynb"},  # ok
        {"claim_id": "C002", "source_notebook": "NB04"},                   # repaired
        {"claim_id": "C003", "source_notebook": "—"},                      # cleared
    ])
    diag = vci.validate_tsv(tsv_path=tsv, project_root=proj, audit_path=audit)
    assert diag["rows_repaired_this_run"] == 1
    assert diag["rows_updated_this_run"] == 1
    assert diag["repaired_notebooks"] == {"NB04": "NB04_within_ecotype_DA.ipynb"}
    parsed = json.loads(audit.read_text(encoding="utf-8"))
    assert parsed["rows_repaired_this_run"] == 1
    assert parsed["repaired_notebooks"] == {"NB04": "NB04_within_ecotype_DA.ipynb"}
    assert parsed["version"] == "0.2.0-stage3-tierI"


def test_repaired_row_is_idempotent(tmp_path):
    """A repaired row holds a full real filename — the second pass resolves
    it as-is and makes no further change. File is byte-stable."""
    proj = _make_project(tmp_path, _SIBLING_NOTEBOOKS)
    tsv = tmp_path / "claim_inventory.tsv"
    _write_tsv(tsv, [{"claim_id": "C001", "source_notebook": "NB04"}])
    vci.validate_tsv(tsv_path=tsv, project_root=proj)
    first = _read_tsv(tsv)
    diag2 = vci.validate_tsv(tsv_path=tsv, project_root=proj)
    second = _read_tsv(tsv)
    assert diag2["rows_repaired_this_run"] == 0
    assert diag2["rows_updated_this_run"] == 0
    assert first == second
