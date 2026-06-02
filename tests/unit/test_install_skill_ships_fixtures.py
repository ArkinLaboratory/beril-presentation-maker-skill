"""v0.8.0: install-skill must ship the smoke_v3 fixture tree so
`smoke_v3_prompt.py` works from the installed-skill location
(promoted from v0.8.1 carry to v0.8.0 release-blocker per Adam's
"clean install for users" packaging criterion).

Before v0.8.0:
  - fixtures lived at repo-root tests/fixtures/smoke_v3/ (NOT in
    the package tree)
  - install_skill._SHIPPED_SUBDIRS = ("commands", "prompts",
    "references", "tools") — no "tests"
  - smoke_v3_prompt.py from the installed path failed with
    "smoke fixture missing at .../tests/fixtures/smoke_v3"

v0.8.0 fix:
  - fixtures moved INSIDE the package at
    src/beril_presentation_maker/skill/tests/fixtures/smoke_v3/
    (single source of truth)
  - "tests" added to _SHIPPED_SUBDIRS so install-skill copies them
  - smoke_v3_prompt._resolve_fixture_dir() updated to find the
    new location in both dev and installed layouts
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path


# ---------------------------------------------------------------------------
# Package-side: fixtures live INSIDE the package tree
# ---------------------------------------------------------------------------

def test_fixtures_live_inside_package() -> None:
    """The smoke_v3 fixture tree must be inside the package so it
    ships via the wheel + via install-skill. v0.8.0 SoT."""
    skill = resources.files("beril_presentation_maker") / "skill"
    with resources.as_file(skill) as p:
        fixture = Path(p) / "tests" / "fixtures" / "smoke_v3"
        assert fixture.is_dir(), (
            f"smoke_v3 fixtures must live inside the package at "
            f"{fixture} per v0.8.0 — outside the package they "
            f"don't ship via install-skill"
        )


def test_fixture_tree_has_expected_files() -> None:
    """Sanity: fixture tree contains the files smoke_v3_prompt.py
    expects (REPORT.md, narrative/, working/)."""
    skill = resources.files("beril_presentation_maker") / "skill"
    with resources.as_file(skill) as p:
        fixture = Path(p) / "tests" / "fixtures" / "smoke_v3"
        assert (fixture / "REPORT.md").is_file()
        assert (fixture / "narrative" / "02_substories.md").is_file()
        assert (fixture / "narrative" / "00_throughline.md").is_file()
        assert (fixture / "working" / "00_plan.md").is_file()
        assert (fixture / "working" / "citation_pool.json").is_file()


# ---------------------------------------------------------------------------
# install-skill: ships the tests/ subdir
# ---------------------------------------------------------------------------

def test_install_skill_lists_tests_in_shipped_subdirs() -> None:
    """_SHIPPED_SUBDIRS must include 'tests' so install-skill copies
    the fixture tree to the installed location. Without this, the
    fixture-shipping inside the package is moot (the package data
    travels with the wheel but never lands in the BERIL_ROOT
    install dir)."""
    from beril_presentation_maker.commands import install_skill
    assert "tests" in install_skill._SHIPPED_SUBDIRS, (
        "install_skill._SHIPPED_SUBDIRS must include 'tests' "
        "(v0.8.0) so smoke_v3 fixtures ship to the installed "
        "<skill_dir>/tests/fixtures/smoke_v3/ location"
    )


def test_install_skill_shipped_subdirs_set_unchanged_except_tests() -> None:
    """Defensive: the v0.8.0 fix should ADD 'tests' without
    removing any prior shipped subdir."""
    from beril_presentation_maker.commands import install_skill
    expected = {"commands", "prompts", "references", "tools", "tests"}
    assert set(install_skill._SHIPPED_SUBDIRS) == expected, (
        f"v0.8.0 _SHIPPED_SUBDIRS must equal {expected}; "
        f"got {set(install_skill._SHIPPED_SUBDIRS)}"
    )


# ---------------------------------------------------------------------------
# smoke_v3_prompt resolver: finds fixtures in both layouts
# ---------------------------------------------------------------------------

def test_smoke_resolver_dev_layout_points_into_package() -> None:
    """In dev layout the resolver must point at the in-package
    fixture path (NOT repo-root tests/fixtures/, which v0.8.0
    retires as the SoT)."""
    from beril_presentation_maker.skill.tools import smoke_v3_prompt
    expected_segment = Path("src") / "beril_presentation_maker" / \
        "skill" / "tests" / "fixtures" / "smoke_v3"
    assert str(expected_segment) in str(smoke_v3_prompt.FIXTURE_DIR), (
        f"v0.8.0 dev layout: FIXTURE_DIR must point into the "
        f"package tree; got {smoke_v3_prompt.FIXTURE_DIR}"
    )
    assert smoke_v3_prompt.FIXTURE_DIR.is_dir(), (
        "FIXTURE_DIR must exist (the fixture move must have "
        "preserved the contents)"
    )


def test_smoke_resolver_installed_layout_uses_skill_dir_tests(
    tmp_path: Path,
) -> None:
    """In installed layout (skill_dir as repo root), fixtures live
    at <skill_dir>/tests/fixtures/smoke_v3/."""
    from beril_presentation_maker.skill.tools.smoke_v3_prompt import (
        _resolve_fixture_dir,
    )
    fake_installed = tmp_path / "beril-presentation-maker"
    result = _resolve_fixture_dir(fake_installed, "installed")
    expected = fake_installed / "tests" / "fixtures" / "smoke_v3"
    assert result == expected, (
        f"installed layout fixture dir must be "
        f"<skill_dir>/tests/fixtures/smoke_v3; got {result}"
    )


# ---------------------------------------------------------------------------
# Regression guard: the repo-root tests/fixtures/smoke_v3/ is gone
# ---------------------------------------------------------------------------

def test_repo_root_smoke_v3_fixture_no_longer_exists() -> None:
    """After v0.8.0 the repo-root fixture path is RETIRED — the
    single source of truth lives inside the package. Pin this so a
    future commit doesn't accidentally re-create the repo-root copy
    (which would diverge silently from the package copy)."""
    repo_root = Path(__file__).resolve().parents[2]
    legacy = repo_root / "tests" / "fixtures" / "smoke_v3"
    assert not legacy.exists(), (
        f"v0.8.0 retired the repo-root smoke_v3 fixture; the "
        f"in-package path is now the single source of truth. "
        f"Re-creating {legacy} would diverge silently from the "
        f"package copy."
    )
