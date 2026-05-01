"""Tests for the v0.3.1 draft layout module.

The DraftPaths class is the single source of truth for where each
artifact lives in a draft directory. These tests pin the schema —
property names, zone membership, and helper-method semantics — so
downstream tools can rely on it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (matches the pattern used by test_check_quantitative_grounding.py)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _REPO_ROOT / "src" / "beril_presentation_maker" / "skill" / "tools"


def _load_draft_paths():
    spec = importlib.util.spec_from_file_location(
        "draft_paths", _TOOLS_DIR / "draft_paths.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["draft_paths"] = module
    spec.loader.exec_module(module)
    return module


dp = _load_draft_paths()
DraftPaths = dp.DraftPaths
ZONES = dp.ZONES
LAYOUT_SUBDIRS = dp.LAYOUT_SUBDIRS


# ---------------------------------------------------------------------------
# Construction + zone membership
# ---------------------------------------------------------------------------

def test_zones_are_exactly_four():
    """The 4-zone layout is the contract. Adding zones is breaking."""
    assert ZONES == ("deliverable", "narrative", "working", "audit")


def test_top_level_paths_are_under_draft_dir(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    for zone in ZONES:
        zone_path = getattr(paths, zone)
        assert zone_path == tmp_path / zone, f"zone {zone} resolves wrong"
        assert zone_path.parent == tmp_path


def test_from_draft_dir_resolves_to_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rel = Path("subdir")
    rel.mkdir()
    paths = DraftPaths.from_draft_dir("subdir")
    assert paths.draft_dir.is_absolute()
    assert paths.draft_dir == (tmp_path / "subdir").resolve()


# ---------------------------------------------------------------------------
# Layout zone membership — every named path lives in the right zone
# ---------------------------------------------------------------------------

DELIVERABLE_ATTRS = ("deck_pptx", "deck_pdf", "speaker_notes_pdf")
NARRATIVE_ATTRS = ("throughline", "substories", "references_md", "bibliography", "citation_map")
WORKING_ATTRS = (
    "plan", "throughline_candidates", "slides_dir", "speaker_notes_dir",
    "image_requests_dir", "images_dir", "citation_pool",
    "cross_tenant_md", "cross_tenant_json",
    "curated_figures", "figures_inventory",
    "diagram_repair", "next_actions", "slide_spec",
)
AUDIT_ATTRS = (
    "state", "cost_log", "stage_metadata",
    "stage_logs_dir", "snapshots_dir", "manual_edits_dir", "runs_dir",
    "adversarial_review_json", "adversarial_review_md",
    "adversarial_review_original_summary",
    "quantitative_grounding_json", "quantitative_grounding_md",
    "revise_loop_metadata",
    "last_render_hash",
)


@pytest.mark.parametrize("attr", DELIVERABLE_ATTRS)
def test_deliverable_attrs_in_deliverable_zone(attr, tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = getattr(paths, attr)
    assert paths.deliverable in p.parents, f"{attr} not under deliverable/"


@pytest.mark.parametrize("attr", NARRATIVE_ATTRS)
def test_narrative_attrs_in_narrative_zone(attr, tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = getattr(paths, attr)
    assert paths.narrative in p.parents, f"{attr} not under narrative/"


@pytest.mark.parametrize("attr", WORKING_ATTRS)
def test_working_attrs_in_working_zone(attr, tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = getattr(paths, attr)
    assert paths.working in p.parents, f"{attr} not under working/"


@pytest.mark.parametrize("attr", AUDIT_ATTRS)
def test_audit_attrs_in_audit_zone(attr, tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = getattr(paths, attr)
    assert paths.audit in p.parents, f"{attr} not under audit/"


def test_last_render_pptx_lives_in_snapshots(tmp_path):
    """The last-render baseline lives under audit/snapshots/, not at audit
    top level (it's an immutable copy, not a current-run artifact)."""
    paths = DraftPaths.from_draft_dir(tmp_path)
    assert paths.last_render_pptx.parent == paths.snapshots_dir


def test_curated_figures_canonical_no_duplicate(tmp_path):
    """v0.3.1 killed the figures_curated.md / curated_figures.md duplicate.
    Only the canonical name should be exposed."""
    paths = DraftPaths.from_draft_dir(tmp_path)
    # Property exists
    assert paths.curated_figures.name == "curated_figures.md"
    # No duplicate property
    assert not hasattr(paths, "figures_curated"), \
        "figures_curated property should not exist (use curated_figures)"


# ---------------------------------------------------------------------------
# Helpers — fragment, snapshot, log, manual_edit_archive paths
# ---------------------------------------------------------------------------

def test_slide_fragment_path(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = paths.slide_fragment("S1_slides")
    assert p == paths.slides_dir / "S1_slides.json"


def test_speaker_notes_path(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = paths.speaker_notes("S1")
    assert p == paths.speaker_notes_dir / "S1.md"


def test_image_request_path(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = paths.image_request("S2-pos4")
    assert p == paths.image_requests_dir / "S2-pos4_request.json"


def test_generated_image_path(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = paths.generated_image("S2-pos4")
    assert p == paths.images_dir / "S2-pos4.png"
    p_jpg = paths.generated_image("S2-pos4", ext="jpg")
    assert p_jpg == paths.images_dir / "S2-pos4.jpg"


def test_slide_spec_snapshot_path(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    p = paths.slide_spec_snapshot("pre_revise")
    assert p == paths.snapshots_dir / "slide_spec.pre_revise.json"


def test_stage_log_kinds(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    assert paths.stage_log("plan", "stdout").name == "plan.stdout"
    assert paths.stage_log("plan", "stderr").name == "plan.stderr"
    assert paths.stage_log("plan", "stream.log").name == "plan.stream.log"
    with pytest.raises(ValueError):
        paths.stage_log("plan", "bogus")


def test_manual_edit_archive_uses_utc_iso_timestamp(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    fixed = datetime(2026, 5, 1, 18, 22, 14, tzinfo=timezone.utc)
    p = paths.manual_edit_archive(timestamp=fixed)
    assert p.parent == paths.manual_edits_dir
    assert p.name == "2026-05-01T18-22-14Z.pptx"


def test_run_archive_dir(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    assert paths.run_archive_dir(1) == paths.runs_dir / "run-1"
    assert paths.run_archive_dir(42) == paths.runs_dir / "run-42"


# ---------------------------------------------------------------------------
# init_layout + is_initialized + assert_initialized
# ---------------------------------------------------------------------------

def test_init_layout_creates_zones_and_subdirs(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    assert not paths.is_initialized()

    paths.init_layout()

    for zone in ZONES:
        assert (tmp_path / zone).is_dir()
    for sub in LAYOUT_SUBDIRS:
        assert (tmp_path / sub).is_dir(), f"missing subdir {sub}"
    assert paths.is_initialized()


def test_init_layout_idempotent(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    # Second call shouldn't raise
    paths.init_layout()
    assert paths.is_initialized()


def test_assert_initialized_rejects_old_layout(tmp_path):
    """v0.3.0-shape draft (no zones) must raise a clear error."""
    # Simulate v0.3.0 layout: top-level files but no zone dirs
    (tmp_path / "00_plan.md").write_text("plan")
    (tmp_path / "slide_spec.json").write_text("{}")

    paths = DraftPaths.from_draft_dir(tmp_path)
    with pytest.raises(FileNotFoundError) as exc_info:
        paths.assert_initialized()
    assert "v0.3.1+ layout" in str(exc_info.value)


def test_assert_initialized_passes_after_init(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    paths.assert_initialized()  # no raise


# ---------------------------------------------------------------------------
# snapshot_slide_spec
# ---------------------------------------------------------------------------

def test_snapshot_slide_spec_copies(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    paths.slide_spec.write_text('{"slides": []}')

    snap = paths.snapshot_slide_spec("pre_revise")

    assert snap == paths.snapshots_dir / "slide_spec.pre_revise.json"
    assert snap.is_file()
    assert snap.read_text() == '{"slides": []}'


def test_snapshot_slide_spec_missing_source_raises(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    with pytest.raises(FileNotFoundError):
        paths.snapshot_slide_spec("pre_revise")


# ---------------------------------------------------------------------------
# Manual-edit hash guard
# ---------------------------------------------------------------------------

def _write_pptx_stub(path: Path, content: bytes = b"PPTX-STUB-1"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_record_render_hash_writes_json_and_snapshot(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _write_pptx_stub(paths.deck_pptx, b"FAKE-PPTX-1")

    digest = paths.record_render_hash()

    expected = hashlib.sha256(b"FAKE-PPTX-1").hexdigest()
    assert digest == expected

    payload = json.loads(paths.last_render_hash.read_text())
    assert payload["sha256"] == expected
    assert payload["schema_version"] == "last-render.v1"
    assert paths.last_render_pptx.is_file()
    assert paths.last_render_pptx.read_bytes() == b"FAKE-PPTX-1"


def test_record_render_hash_missing_deck_raises(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    with pytest.raises(FileNotFoundError):
        paths.record_render_hash()


def test_detect_manual_edit_returns_none_when_unchanged(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _write_pptx_stub(paths.deck_pptx, b"FAKE-PPTX-1")
    paths.record_render_hash()

    # Same content → no manual edit detected
    assert paths.detect_manual_edit() is None


def test_detect_manual_edit_returns_digest_when_changed(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _write_pptx_stub(paths.deck_pptx, b"FAKE-PPTX-1")
    paths.record_render_hash()

    # Simulate user editing in PowerPoint
    _write_pptx_stub(paths.deck_pptx, b"USER-EDITED-PPTX")

    detected = paths.detect_manual_edit()
    assert detected is not None
    assert detected == hashlib.sha256(b"USER-EDITED-PPTX").hexdigest()


def test_detect_manual_edit_returns_none_when_no_prior_render(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _write_pptx_stub(paths.deck_pptx, b"FAKE-PPTX-1")
    # No record_render_hash call → no prior baseline
    assert paths.detect_manual_edit() is None


def test_detect_manual_edit_handles_corrupt_hash_file(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _write_pptx_stub(paths.deck_pptx, b"FAKE-PPTX-1")
    # Write garbage to the hash file
    paths.last_render_hash.write_text("not json {{")
    # Should treat as no-prior-render rather than raising
    assert paths.detect_manual_edit() is None


def test_archive_manual_edit_copies_to_audit(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    _write_pptx_stub(paths.deck_pptx, b"USER-EDITED-PPTX")

    archive = paths.archive_manual_edit()

    assert archive.parent == paths.manual_edits_dir
    assert archive.suffix == ".pptx"
    assert archive.read_bytes() == b"USER-EDITED-PPTX"


def test_archive_manual_edit_missing_deck_raises(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    with pytest.raises(FileNotFoundError):
        paths.archive_manual_edit()


# ---------------------------------------------------------------------------
# Frozen-dataclass sanity (callers can't mutate)
# ---------------------------------------------------------------------------

def test_draft_paths_is_frozen(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        paths.draft_dir = tmp_path / "elsewhere"  # type: ignore


# ---------------------------------------------------------------------------
# shell_exports — verifies the schema can be emitted to bash
# ---------------------------------------------------------------------------

def test_shell_exports_emits_assignments_for_all_paths(tmp_path):
    paths = DraftPaths.from_draft_dir(tmp_path)
    out = dp.shell_exports(paths)
    # Sanity check: every attribute that returns a Path appears in shell_exports
    expected_vars = {
        "DELIVERABLE_DIR", "NARRATIVE_DIR", "WORKING_DIR", "AUDIT_DIR",
        "DECK_PPTX", "DECK_PDF",
        "THROUGHLINE_PATH", "SUBSTORIES_PATH", "REFERENCES_MD",
        "BIBLIOGRAPHY", "CITATION_MAP",
        "PLAN_PATH", "THROUGHLINE_CANDIDATES",
        "SLIDES_DIR", "SPEAKER_NOTES_DIR",
        "IMAGE_REQUESTS_DIR", "IMAGES_DIR",
        "CITATION_POOL_PATH", "CROSS_TENANT_MD", "CROSS_TENANT_JSON",
        "CURATED_FIGURES", "FIGURES_INVENTORY",
        "DIAGRAM_REPAIR", "NEXT_ACTIONS", "SLIDE_SPEC",
        "STATE_JSON", "COST_LOG", "STAGE_METADATA",
        "STAGE_LOGS_DIR", "SNAPSHOTS_DIR", "MANUAL_EDITS_DIR", "RUNS_DIR",
        "ADVERSARIAL_REVIEW_JSON", "ADVERSARIAL_REVIEW_MD",
        "QUANT_GROUNDING_JSON", "QUANT_GROUNDING_MD",
        "REVISE_LOOP_METADATA",
        "LAST_RENDER_HASH", "LAST_RENDER_PPTX",
    }
    for var in expected_vars:
        assert f'{var}="' in out, f"shell_exports missing {var}"


def test_shell_exports_paths_match_python_paths(tmp_path):
    """Each shell export's value matches what the Python property returns."""
    paths = DraftPaths.from_draft_dir(tmp_path)
    lines = dp.shell_exports(paths).split("\n")
    pairs = {}
    for line in lines:
        # NAME="value" → split on first =
        assert '="' in line and line.endswith('"')
        name, _, value = line.partition('="')
        pairs[name] = value[:-1]  # strip trailing "

    assert pairs["DELIVERABLE_DIR"] == str(paths.deliverable)
    assert pairs["DECK_PPTX"] == str(paths.deck_pptx)
    assert pairs["SLIDE_SPEC"] == str(paths.slide_spec)
    assert pairs["LAST_RENDER_PPTX"] == str(paths.last_render_pptx)
