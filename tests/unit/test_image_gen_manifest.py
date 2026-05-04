"""Tests for v0.3.3 image_gen_manifest Tier 3 manifest writer.

Per V0_3_3_ARCHITECTURE.md §13 Tier 3 plan: schema validation, append
semantics, rejection recording, and round-trip idempotency.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import image_gen_manifest as igm  # noqa: E402


# ---------------------------------------------------------------------------
# Construction + I/O
# ---------------------------------------------------------------------------

def test_load_returns_empty_when_file_absent(tmp_path):
    m = igm.Manifest.load(tmp_path / "nonexistent.json")
    assert m.entries == []
    assert m.draft_dir == ""


def test_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "manifest.json"
    m = igm.Manifest(draft_dir=str(tmp_path))
    written = m.write(target)
    assert written.is_file()
    assert written.parent.is_dir()


def test_write_emits_valid_envelope(tmp_path):
    m = igm.Manifest(draft_dir=str(tmp_path))
    target = tmp_path / "manifest.json"
    m.write(target)
    data = json.loads(target.read_text())
    assert data["schema_version"] == "image-manifest.v1"
    assert data["entries"] == []
    assert "draft_dir" in data


def test_round_trip_preserves_data(tmp_path):
    m = igm.Manifest(draft_dir=str(tmp_path))
    m.add_approved(
        slide_id="S2-pos4",
        image_path="working/05_images/S2-pos4.png",
        request_path="working/05_image_requests/S2-pos4_request.json",
        channel="A",
        model="gemini-3-pro-image",
        cost_usd=0.014,
        approved_at="2026-05-03T14:32:11Z",
    )
    m.add_rejected(
        slide_id="S2-pos7",
        reason="user-rejected: prompt drift from substory",
        rejected_at="2026-05-03T14:32:35Z",
    )
    target = tmp_path / "manifest.json"
    m.write(target)

    reloaded = igm.Manifest.load(target)
    assert len(reloaded.entries) == 2
    assert reloaded.entries[0]["slide_id"] == "S2-pos4"
    assert reloaded.entries[0]["approved"] is True
    assert reloaded.entries[0]["cost_usd"] == 0.014
    assert reloaded.entries[1]["approved"] is False
    assert "user-rejected" in reloaded.entries[1]["reason"]


def test_load_rejects_wrong_schema_version(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({
        "schema_version": "image-manifest.v0",
        "entries": [],
    }))
    with pytest.raises(igm.ManifestError, match="schema_version"):
        igm.Manifest.load(target)


def test_load_rejects_invalid_json(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_text("{not valid json")
    with pytest.raises(igm.ManifestError, match="not valid JSON"):
        igm.Manifest.load(target)


def test_load_rejects_non_object(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_text("[]")
    with pytest.raises(igm.ManifestError, match="not a JSON object"):
        igm.Manifest.load(target)


def test_load_rejects_non_list_entries(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({
        "schema_version": "image-manifest.v1",
        "entries": "should be a list",
    }))
    with pytest.raises(igm.ManifestError, match="entries"):
        igm.Manifest.load(target)


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------

def test_add_approved_minimal_path(tmp_path):
    m = igm.Manifest()
    entry = m.add_approved(
        slide_id="S1-pos2",
        image_path="img.png",
        request_path="req.json",
        channel="A",
        model="gemini-3-pro-image",
        cost_usd=0.01,
    )
    assert entry["slide_id"] == "S1-pos2"
    assert entry["approved"] is True
    assert "approved_at" in entry  # auto-stamped
    assert entry["cost_usd"] == 0.01


def test_add_approved_rejects_invalid_channel():
    m = igm.Manifest()
    with pytest.raises(igm.ManifestError, match="channel"):
        m.add_approved(
            slide_id="S1-pos2",
            image_path="img.png",
            request_path="req.json",
            channel="X",  # not A or B
            model="m",
            cost_usd=0.01,
        )


def test_add_approved_rejects_negative_cost():
    m = igm.Manifest()
    with pytest.raises(igm.ManifestError, match="cost_usd"):
        m.add_approved(
            slide_id="S1-pos2",
            image_path="img.png",
            request_path="req.json",
            channel="A",
            model="m",
            cost_usd=-0.01,
        )


def test_add_approved_rejects_empty_slide_id():
    m = igm.Manifest()
    with pytest.raises(igm.ManifestError, match="slide_id"):
        m.add_approved(
            slide_id="",
            image_path="img.png",
            request_path="req.json",
            channel="A",
            model="m",
            cost_usd=0.01,
        )


def test_add_approved_rejects_duplicate_slide_id():
    """No silent overwrites — caller must explicitly handle re-runs."""
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos2", image_path="img.png", request_path="req.json",
        channel="A", model="m", cost_usd=0.01,
    )
    with pytest.raises(igm.ManifestError, match="already in manifest"):
        m.add_approved(
            slide_id="S1-pos2", image_path="img2.png",
            request_path="req2.json",
            channel="A", model="m", cost_usd=0.01,
        )


def test_add_rejected_minimal_path():
    m = igm.Manifest()
    entry = m.add_rejected(
        slide_id="S1-pos3",
        reason="user-rejected: drift from substory punchline",
    )
    assert entry["approved"] is False
    assert "rejected_at" in entry
    assert "drift" in entry["reason"]
    assert "skipped" not in entry  # only present on add_skipped


def test_add_rejected_requires_reason():
    m = igm.Manifest()
    with pytest.raises(igm.ManifestError, match="reason required"):
        m.add_rejected(slide_id="S1-pos3", reason="")


def test_add_rejected_optional_request_path_kept():
    m = igm.Manifest()
    entry = m.add_rejected(
        slide_id="S1-pos3",
        reason="user-rejected",
        request_path="working/05_image_requests/S1-pos3_request.json",
    )
    assert entry["request_path"].endswith("_request.json")


def test_add_skipped_distinguishable_from_rejected():
    m = igm.Manifest()
    entry = m.add_skipped(
        slide_id="S1-pos9",
        reason="budget cap exhausted ($0.50)",
    )
    assert entry["approved"] is False
    assert entry["skipped"] is True
    assert "budget" in entry["reason"]


def test_duplicate_across_categories_rejected():
    """Same slide_id can't appear in any combination of approved /
    rejected / skipped — manifest is keyed on slide_id."""
    m = igm.Manifest()
    m.add_rejected(slide_id="S1-pos5", reason="...")
    with pytest.raises(igm.ManifestError, match="already in manifest"):
        m.add_skipped(slide_id="S1-pos5", reason="...")
    with pytest.raises(igm.ManifestError, match="already in manifest"):
        m.add_approved(
            slide_id="S1-pos5", image_path="i", request_path="r",
            channel="A", model="m", cost_usd=0.01,
        )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def test_has_slide_finds_any_status():
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.01,
    )
    m.add_rejected(slide_id="S1-pos2", reason="rj")
    m.add_skipped(slide_id="S1-pos3", reason="skip")
    assert m.has_slide("S1-pos1")
    assert m.has_slide("S1-pos2")
    assert m.has_slide("S1-pos3")
    assert not m.has_slide("S1-pos99")


def test_get_returns_entry_or_none():
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="img1.png", request_path="r",
        channel="A", model="m", cost_usd=0.05,
    )
    e = m.get("S1-pos1")
    assert e is not None
    assert e["image_path"] == "img1.png"
    assert m.get("missing") is None


def test_approved_entries_filter():
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.01,
    )
    m.add_rejected(slide_id="S1-pos2", reason="rj")
    m.add_skipped(slide_id="S1-pos3", reason="skip")
    approved = m.approved_entries()
    assert len(approved) == 1
    assert approved[0]["slide_id"] == "S1-pos1"


def test_rejected_entries_includes_skipped():
    """Both user-rejected and budget-skipped entries are 'not approved';
    rejected_entries() returns both — the merge step needs to drop
    fragments for both reasons."""
    m = igm.Manifest()
    m.add_rejected(slide_id="S1-pos2", reason="rj")
    m.add_skipped(slide_id="S1-pos3", reason="skip")
    rejected = m.rejected_entries()
    assert len(rejected) == 2


def test_total_cost_usd_sums_approved_only():
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.014,
    )
    m.add_approved(
        slide_id="S2-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.012,
    )
    m.add_rejected(slide_id="S3-pos1", reason="rj")  # no cost
    assert m.total_cost_usd() == pytest.approx(0.026)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_validate_accepts_well_formed():
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.01,
    )
    assert m.validate() == []


def test_validate_catches_missing_required_fields(tmp_path):
    """An approved entry missing image_path is malformed — validate
    catches it. Direct-mutation case (skipping the mutator API)."""
    m = igm.Manifest()
    m.entries.append({
        "slide_id": "S1-pos1",
        "approved": True,
        # missing image_path, request_path, channel, model, cost_usd, approved_at
    })
    errors = m.validate()
    assert len(errors) >= 5
    assert any("image_path" in e for e in errors)
    assert any("channel" in e for e in errors)


def test_validate_catches_duplicate_slide_ids():
    """If someone manually edits the manifest and creates duplicates,
    validate catches that too."""
    m = igm.Manifest()
    m.entries.append({
        "slide_id": "S1-pos1",
        "approved": True,
        "image_path": "i",
        "request_path": "r",
        "channel": "A",
        "model": "m",
        "cost_usd": 0.01,
        "approved_at": "2026-01-01T00:00:00Z",
    })
    m.entries.append({
        "slide_id": "S1-pos1",  # duplicate
        "approved": False,
        "rejected_at": "2026-01-01T00:00:00Z",
        "reason": "rj",
    })
    errors = m.validate()
    assert any("duplicate" in e for e in errors)


def test_validate_catches_invalid_channel():
    m = igm.Manifest()
    m.entries.append({
        "slide_id": "S1-pos1",
        "approved": True,
        "image_path": "i",
        "request_path": "r",
        "channel": "Z",  # not A or B
        "model": "m",
        "cost_usd": 0.01,
        "approved_at": "2026-01-01T00:00:00Z",
    })
    errors = m.validate()
    assert any("channel" in e for e in errors)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_validate_ok(tmp_path, capsys):
    target = tmp_path / "manifest.json"
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.01,
    )
    m.write(target)
    rc = igm.main(["validate", str(target)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.err


def test_cli_validate_reports_errors(tmp_path, capsys):
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({
        "schema_version": "image-manifest.v1",
        "entries": [{"slide_id": "S1-pos1", "approved": True}],  # missing many
    }))
    rc = igm.main(["validate", str(target)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "validation error" in captured.err


def test_cli_validate_missing_file(tmp_path, capsys):
    rc = igm.main(["validate", str(tmp_path / "nope.json")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err
