"""Tests for extract_cross_tenant.py — REPORT/PLAN/notebook scan for
tenant + DB + sibling-project signal.

Covers:
- Tenant token detection in prose
- K-BERDL DB token detection in prose + notebook source
- berdl_query SQL parsing (FROM <db>.<table>)
- Sibling-project reference patterns
- KBase URL detection
- no_signal_fallback when nothing found
- Filtering of platform tokens (KBase/BERDL/BRIDGE) from tenant_list
- Self-reference filtering (project doesn't list itself as a sibling)
- to_slide_content shape matches slide_spec contract
- CLI surface
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACT_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
              / "tools" / "extract_cross_tenant.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ect():
    return _import("extract_cross_tenant", EXTRACT_PY)


@pytest.fixture
def project_with_signal(tmp_path: Path):
    """Build a synthetic project directory with cross-tenant signal."""
    proj = tmp_path / "functional_dark_matter"
    proj.mkdir()
    (proj / "README.md").write_text(
        "# functional_dark_matter\n\n"
        "Builds on results from the ENIGMA SFA and integrates phage_foundry data.\n"
    )
    (proj / "RESEARCH_PLAN.md").write_text(
        "# Plan\n\nQuery fitnessbrowser for chromate-stress fitness scores. "
        "See project annotation_agent_v1 for baseline annotations.\n"
    )
    (proj / "REPORT.md").write_text(
        "# Report\n\n"
        "We pulled 27,000,000 fitness scores from fitnessbrowser and joined "
        "with paperblast hits. Tenants involved: enigma, pmi.\n"
        "URL: https://kbase.us/data/enigma\n"
    )
    (proj / "references.md").write_text(
        "Per `projects/metal_atlas/`, prior metal-stress profiles are available.\n"
    )
    nb_dir = proj / "notebooks"
    nb_dir.mkdir()
    nb_text = json.dumps({
        "cells": [
            {"cell_type": "markdown", "metadata": {},
             "source": "Building on the ENIGMA pilot."},
            {"cell_type": "code", "metadata": {},
             "outputs": [], "execution_count": None,
             "source":
                "result = berdl_query(\"SELECT * FROM fitnessbrowser.fitness_score \"\n"
                "                     \"JOIN paperblast.hit USING (gene_id)\")"},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })
    (nb_dir / "01_demo.ipynb").write_text(nb_text)
    return proj


@pytest.fixture
def project_no_signal(tmp_path: Path):
    """Synthetic project with NO cross-tenant signal."""
    proj = tmp_path / "lonely_project"
    proj.mkdir()
    (proj / "README.md").write_text("# lonely_project\n\nA self-contained analysis.\n")
    (proj / "REPORT.md").write_text("Results: 42% growth rate. No external data.\n")
    return proj


# ---------------------------------------------------------------------------
# Term-extraction primitives
# ---------------------------------------------------------------------------

def test_scan_text_for_terms_finds_known_tenants(ect):
    text = "ENIGMA results match PMI estimates. KBase platform integration works."
    ev = ect._scan_text_for_terms(
        text, ect.KNOWN_TENANTS, "tenant", "test.md",
    )
    matches = [e.matched_text.lower() for e in ev]
    assert "enigma" in matches
    assert "pmi" in matches
    # KBase IS in KNOWN_TENANTS but should be filtered later by the platform
    # token rule in the aggregate step (not the raw scan)


def test_scan_text_for_terms_case_insensitive(ect):
    text = "Enigma. ENIGMA. eNiGmA."
    ev = ect._scan_text_for_terms(text, ("enigma",), "tenant", "test.md")
    assert len(ev) == 3


def test_scan_text_for_terms_word_boundary(ect):
    """'pmi' should not match inside 'pmidA' or 'tempinage'."""
    text = "PMI metrics. tempinage and pmidA."
    ev = ect._scan_text_for_terms(text, ("pmi",), "tenant", "test.md")
    assert len(ev) == 1


def test_sibling_project_pattern_simple(ect):
    text = "see project annotation_agent_v1 for baseline."
    ev = ect._scan_text_for_sibling_projects(text, "test.md")
    assert any(e.matched_text == "annotation_agent_v1" for e in ev)


def test_sibling_project_pattern_path(ect):
    text = "Per `projects/metal_atlas/`, prior fitness profiles are available."
    ev = ect._scan_text_for_sibling_projects(text, "test.md")
    assert any(e.matched_text == "metal_atlas" for e in ev)


def test_kbase_url_detection(ect):
    text = "URL: https://kbase.us/data/x and https://api.berdl.lbl.gov/q?id=42."
    ev = ect._scan_text_for_kbase_urls(text, "test.md")
    urls = [e.matched_text for e in ev]
    assert any("kbase.us" in u for u in urls)
    assert any("berdl.lbl.gov" in u for u in urls)


# ---------------------------------------------------------------------------
# Notebook scanning
# ---------------------------------------------------------------------------

def test_notebook_berdl_query_extraction(ect, tmp_path):
    if ect.nbformat is None:
        pytest.skip("nbformat not installed")
    nb_path = tmp_path / "demo.ipynb"
    nb_text = json.dumps({
        "cells": [
            {"cell_type": "code", "metadata": {},
             "outputs": [], "execution_count": None,
             "source":
                "x = berdl_query(\"SELECT g, s FROM fitnessbrowser.fitness_score WHERE x=1\")"},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })
    nb_path.write_text(nb_text)
    ev = ect._scan_notebook_for_signals(nb_path)
    dbs = [e.matched_text for e in ev if e.kind == "kberdl_db"]
    assert "fitnessbrowser" in dbs


def test_notebook_markdown_picks_up_tenant_mentions(ect, tmp_path):
    if ect.nbformat is None:
        pytest.skip("nbformat not installed")
    nb_path = tmp_path / "narration.ipynb"
    nb_text = json.dumps({
        "cells": [
            {"cell_type": "markdown", "metadata": {},
             "source": "## Building on the ENIGMA SFA's metal-stress data."},
            {"cell_type": "code", "metadata": {},
             "outputs": [], "execution_count": None,
             "source": "import pandas as pd"},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })
    nb_path.write_text(nb_text)
    ev = ect._scan_notebook_for_signals(nb_path)
    tenants = [e.matched_text.lower() for e in ev if e.kind == "tenant"]
    assert "enigma" in tenants


# ---------------------------------------------------------------------------
# End-to-end extract_cross_tenant
# ---------------------------------------------------------------------------

def test_extract_with_signal_yields_full_report(ect, project_with_signal):
    report = ect.extract_cross_tenant(project_with_signal)
    assert report.project_id == "functional_dark_matter"
    assert not report.no_signal_fallback
    # Tenants found
    assert "enigma" in report.tenant_list
    assert "pmi" in report.tenant_list
    assert "phage_foundry" in report.tenant_list
    # Platform tokens excluded from tenant_list
    assert "kbase" not in report.tenant_list
    assert "berdl" not in report.tenant_list
    assert "kberdl" not in report.tenant_list
    # K-BERDL DBs found
    assert "fitnessbrowser" in report.kberdl_db_list
    assert "paperblast" in report.kberdl_db_list
    # Sibling projects found
    pids = [r["project_id"] for r in report.sibling_project_refs]
    assert "annotation_agent_v1" in pids
    assert "metal_atlas" in pids
    # Self-reference filtered out
    assert "functional_dark_matter" not in pids
    # KBase URL captured
    assert any("kbase.us" in u for u in report.kbase_urls)


def test_extract_no_signal_sets_fallback(ect, project_no_signal):
    report = ect.extract_cross_tenant(project_no_signal)
    assert report.no_signal_fallback
    assert report.tenant_list == []
    assert report.kberdl_db_list == []
    assert report.sibling_project_refs == []


def test_extract_handles_missing_optional_files(ect, tmp_path):
    """Project with only README.md should still work."""
    proj = tmp_path / "minimal"
    proj.mkdir()
    (proj / "README.md").write_text("# minimal\n")
    report = ect.extract_cross_tenant(proj)
    assert report.no_signal_fallback


def test_extract_raises_on_missing_project_dir(ect, tmp_path):
    with pytest.raises(FileNotFoundError):
        ect.extract_cross_tenant(tmp_path / "nope")


# ---------------------------------------------------------------------------
# to_slide_content + format_signal_md
# ---------------------------------------------------------------------------

def test_to_slide_content_with_signal(ect, project_with_signal):
    report = ect.extract_cross_tenant(project_with_signal)
    content = report.to_slide_content()
    # Matches slide_spec.cross_tenant_integration content shape
    assert "title" in content
    assert "tenant_list" in content
    assert "kberdl_db_list" in content
    assert "sibling_project_refs" in content
    assert content["no_signal_fallback"] is False
    assert "K-BERDL" in content["title"] or "tenant" in content["title"].lower()


def test_to_slide_content_no_signal_sets_fallback_title(ect, project_no_signal):
    report = ect.extract_cross_tenant(project_no_signal)
    content = report.to_slide_content()
    assert content["no_signal_fallback"] is True
    assert "single tenant" in content["title"].lower()


def test_format_signal_md_with_signal(ect, project_with_signal):
    report = ect.extract_cross_tenant(project_with_signal)
    md = ect.format_signal_md(report)
    assert "# Cross-tenant signal" in md
    assert "fitnessbrowser" in md
    assert "enigma" in md
    assert "Quantitative summary" in md


def test_format_signal_md_no_signal(ect, project_no_signal):
    report = ect.extract_cross_tenant(project_no_signal)
    md = ect.format_signal_md(report)
    assert "No cross-tenant signal detected" in md


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_writes_default_path(ect, project_with_signal):
    rc = ect.main([str(project_with_signal), "--quiet"])
    assert rc == 0
    out = project_with_signal / "cross_tenant_signal.md"
    assert out.is_file()
    text = out.read_text()
    assert "Quantitative summary" in text


def test_cli_with_explicit_paths(ect, project_with_signal, tmp_path):
    md_out = tmp_path / "out.md"
    json_out = tmp_path / "out.json"
    rc = ect.main([
        str(project_with_signal),
        "--out", str(md_out),
        "--json", str(json_out),
        "--quiet",
    ])
    assert rc == 0
    assert md_out.is_file()
    assert json_out.is_file()
    parsed = json.loads(json_out.read_text())
    assert parsed["project_id"] == "functional_dark_matter"


def test_cli_missing_project_dir_returns_2(ect, tmp_path):
    rc = ect.main([str(tmp_path / "nope"), "--quiet"])
    assert rc == 2
