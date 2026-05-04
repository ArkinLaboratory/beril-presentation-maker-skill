"""Tests for v0.3.3 image_gen_orchestrate Tier 6a helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import draft_paths as dp  # noqa: E402
import image_gen_manifest as igm  # noqa: E402
import image_gen_orchestrate as igo  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def initialized_draft(tmp_path):
    """A tmp_path with v0.3.1+ layout initialized + a synthetic
    S1_slides.json fragment with one section_divider + one
    concept_illustration with TBD placeholders."""
    paths = dp.DraftPaths.from_draft_dir(tmp_path)
    paths.init_layout()
    fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": [
            {"layout": "section_divider",
             "content": {"title": "S1.", "punchline": "Test."}},
            {"layout": "concept_illustration",
             "content": {
                 "title": "Test concept.",
                 "image_path": "{TBD}",
                 "image_prompt": "test prompt",
                 "style": "scientific_illustration",
                 "provenance": {
                     "model": "TBD",
                     "cost_usd": 0,
                     "channel": "A",
                     "approved_at": "TBD",
                 },
             }},
        ],
    }
    (paths.slides_dir / "S1_slides.json").write_text(json.dumps(fragment))
    intro_fragment = {
        "schema_version": "compose-fragment.v1",
        "kind": "intro",
        "slides": [
            {"layout": "claim_evidence",
             "content": {"title": "Intro.", "bullets": ["a"]}},
        ],
    }
    (paths.slides_dir / "intro.json").write_text(json.dumps(intro_fragment))
    return paths


# ---------------------------------------------------------------------------
# Slide-id parsing
# ---------------------------------------------------------------------------

def test_parse_slide_id_substory():
    assert igo._parse_slide_id("S2-pos4") == ("S2", 4)
    assert igo._parse_slide_id("S99-pos0") == ("S99", 0)


def test_parse_slide_id_intro():
    assert igo._parse_slide_id("intro-pos0") == ("intro", 0)


def test_parse_slide_id_invalid_raises():
    with pytest.raises(ValueError, match="convention"):
        igo._parse_slide_id("S2_pos4")  # underscore, wrong separator
    with pytest.raises(ValueError):
        igo._parse_slide_id("garbage")
    with pytest.raises(ValueError):
        igo._parse_slide_id("X1-pos4")  # neither S{N} nor intro


def test_fragment_id_for_slide_id():
    assert igo.fragment_id_for_slide_id("S2-pos4") == "S2_slides"
    assert igo.fragment_id_for_slide_id("intro-pos0") == "intro"


# ---------------------------------------------------------------------------
# fragment_path_for_slide_id
# ---------------------------------------------------------------------------

def test_fragment_path_for_substory(initialized_draft):
    p = igo.fragment_path_for_slide_id(initialized_draft, "S1-pos1")
    assert p == initialized_draft.slides_dir / "S1_slides.json"


def test_fragment_path_for_intro(initialized_draft):
    p = igo.fragment_path_for_slide_id(initialized_draft, "intro-pos0")
    assert p == initialized_draft.slides_dir / "intro.json"


# ---------------------------------------------------------------------------
# snapshot_fragment
# ---------------------------------------------------------------------------

def test_snapshot_fragment_creates_copy(initialized_draft):
    snapshot = igo.snapshot_fragment(initialized_draft, "S1-pos1")
    assert snapshot.is_file()
    assert snapshot.parent == initialized_draft.pre_image_gen_snapshots_dir
    assert snapshot.name == "S1_slides.json"
    # Content matches the original
    src = (initialized_draft.slides_dir / "S1_slides.json").read_text()
    assert snapshot.read_text() == src


def test_snapshot_fragment_idempotent_per_fragment(initialized_draft):
    """Multiple slides in the same fragment → only one snapshot.
    The pristine pre-image-gen state must be preserved even if a
    second slide in the same fragment goes through image-gen."""
    snap1 = igo.snapshot_fragment(initialized_draft, "S1-pos0")
    original_mtime = snap1.stat().st_mtime
    # Mutate the working fragment to simulate first-slide image-gen
    fragment_path = initialized_draft.slides_dir / "S1_slides.json"
    data = json.loads(fragment_path.read_text())
    data["slides"][0]["content"]["title"] = "MUTATED"
    fragment_path.write_text(json.dumps(data))
    # Second snapshot call should NOT overwrite the first.
    snap2 = igo.snapshot_fragment(initialized_draft, "S1-pos1")
    assert snap2 == snap1
    snap_data = json.loads(snap2.read_text())
    # Snapshot still has the pristine data, not the mutation.
    assert snap_data["slides"][0]["content"]["title"] == "S1."


def test_snapshot_fragment_missing_fragment_raises(initialized_draft):
    with pytest.raises(FileNotFoundError):
        igo.snapshot_fragment(initialized_draft, "S99-pos0")


# ---------------------------------------------------------------------------
# mutate_fragment_bind
# ---------------------------------------------------------------------------

def test_mutate_fragment_bind_writes_image_path_and_provenance(initialized_draft):
    igo.mutate_fragment_bind(
        initialized_draft,
        slide_id="S1-pos1",
        image_path="working/05_images/S1-pos1.png",
        model="gemini-3-pro-image",
        cost_usd=0.014,
        channel="A",
        approved_at="2026-05-03T14:32:11Z",
    )
    fragment = json.loads(
        (initialized_draft.slides_dir / "S1_slides.json").read_text()
    )
    slide = fragment["slides"][1]
    assert slide["content"]["image_path"] == \
        "working/05_images/S1-pos1.png"
    prov = slide["content"]["provenance"]
    assert prov["model"] == "gemini-3-pro-image"
    assert prov["cost_usd"] == 0.014
    assert prov["channel"] == "A"
    assert prov["approved_at"] == "2026-05-03T14:32:11Z"


def test_mutate_fragment_bind_rejects_non_concept_layout(initialized_draft):
    """Position 0 is section_divider; mutating its image_path is wrong."""
    with pytest.raises(ValueError, match="not 'concept_illustration'"):
        igo.mutate_fragment_bind(
            initialized_draft,
            slide_id="S1-pos0",
            image_path="img.png",
            model="m",
            cost_usd=0.01,
            channel="A",
            approved_at="2026-05-03T14:32:11Z",
        )


def test_mutate_fragment_bind_position_out_of_range(initialized_draft):
    with pytest.raises(IndexError, match="out of range"):
        igo.mutate_fragment_bind(
            initialized_draft,
            slide_id="S1-pos99",
            image_path="img.png",
            model="m",
            cost_usd=0.01,
            channel="A",
            approved_at="2026-05-03T14:32:11Z",
        )


# ---------------------------------------------------------------------------
# remaining_budget
# ---------------------------------------------------------------------------

def test_remaining_budget_with_no_manifest(initialized_draft):
    assert igo.remaining_budget(initialized_draft, cap_usd=0.50) == 0.50


def test_remaining_budget_subtracts_approved_cost(initialized_draft):
    # Pre-populate manifest with one approved entry
    igo.record_approved(
        initialized_draft,
        slide_id="S1-pos1",
        image_path="img.png",
        request_path="r.json",
        channel="A",
        model="m",
        cost_usd=0.10,
    )
    remaining = igo.remaining_budget(initialized_draft, cap_usd=0.50)
    assert remaining == pytest.approx(0.40)


def test_remaining_budget_floors_at_zero(initialized_draft):
    igo.record_approved(
        initialized_draft,
        slide_id="S1-pos1",
        image_path="img.png", request_path="r.json",
        channel="A", model="m", cost_usd=0.60,
    )
    assert igo.remaining_budget(initialized_draft, cap_usd=0.50) == 0.0


def test_remaining_budget_ignores_rejected_skipped(initialized_draft):
    igo.record_rejected(
        initialized_draft, slide_id="S1-pos1", reason="r"
    )
    igo.record_skipped(
        initialized_draft, slide_id="intro-pos0", reason="cap"
    )
    # No approved entries → full cap remains.
    assert igo.remaining_budget(initialized_draft, cap_usd=0.50) == 0.50


# ---------------------------------------------------------------------------
# record_approved / record_rejected / record_skipped
# ---------------------------------------------------------------------------

def test_record_approved_persists(initialized_draft):
    igo.record_approved(
        initialized_draft,
        slide_id="S1-pos1",
        image_path="working/05_images/S1-pos1.png",
        request_path="working/05_image_requests/S1-pos1_request.json",
        channel="A",
        model="gemini-3-pro-image",
        cost_usd=0.014,
        approved_at="2026-05-03T14:32:11Z",
    )
    assert initialized_draft.image_manifest_json.is_file()
    manifest = igm.Manifest.load(initialized_draft.image_manifest_json)
    assert manifest.has_slide("S1-pos1")
    entry = manifest.get("S1-pos1")
    assert entry["approved"] is True
    assert entry["model"] == "gemini-3-pro-image"


def test_record_rejected_persists(initialized_draft):
    igo.record_rejected(
        initialized_draft,
        slide_id="S1-pos1",
        reason="user rejected: drift from substory",
    )
    manifest = igm.Manifest.load(initialized_draft.image_manifest_json)
    entry = manifest.get("S1-pos1")
    assert entry["approved"] is False
    assert "drift" in entry["reason"]


def test_record_skipped_persists(initialized_draft):
    igo.record_skipped(
        initialized_draft,
        slide_id="S1-pos1",
        reason="budget cap exhausted",
    )
    manifest = igm.Manifest.load(initialized_draft.image_manifest_json)
    entry = manifest.get("S1-pos1")
    assert entry["approved"] is False
    assert entry["skipped"] is True


def test_record_approved_seeds_draft_dir(initialized_draft):
    igo.record_approved(
        initialized_draft,
        slide_id="S1-pos1",
        image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.01,
    )
    raw = json.loads(initialized_draft.image_manifest_json.read_text())
    assert raw["draft_dir"] == str(initialized_draft.draft_dir)


def test_record_approved_then_rejected_keeps_both(initialized_draft):
    """Multiple slides → multiple entries."""
    igo.record_approved(
        initialized_draft, slide_id="S1-pos1",
        image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.014,
    )
    igo.record_rejected(
        initialized_draft, slide_id="S2-pos1",
        reason="user rejected",
    )
    manifest = igm.Manifest.load(initialized_draft.image_manifest_json)
    assert len(manifest.entries) == 2
    assert manifest.has_slide("S1-pos1")
    assert manifest.has_slide("S2-pos1")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_find_fragment_substory(initialized_draft, capsys):
    rc = igo.main([
        "find-fragment",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "S1_slides.json" in captured.out


def test_cli_find_fragment_intro(initialized_draft, capsys):
    rc = igo.main([
        "find-fragment",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "intro-pos0",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "intro.json" in captured.out


def test_cli_find_fragment_invalid_slide_id(initialized_draft, capsys):
    rc = igo.main([
        "find-fragment",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "garbage",
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "convention" in captured.err


def test_cli_snapshot_fragment(initialized_draft, capsys):
    rc = igo.main([
        "snapshot-fragment",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "S1_slides.json" in captured.out


def test_cli_budget_remaining(initialized_draft, capsys):
    rc = igo.main([
        "budget-remaining",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--cap-usd", "0.50",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "0.5000"


def test_cli_record_approved(initialized_draft, capsys):
    rc = igo.main([
        "record-approved",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
        "--image-path", "working/05_images/S1-pos1.png",
        "--request-path", "working/05_image_requests/S1-pos1_request.json",
        "--channel", "A",
        "--model", "gemini-3-pro-image",
        "--cost-usd", "0.014",
        "--approved-at", "2026-05-03T14:32:11Z",
    ])
    assert rc == 0
    manifest = igm.Manifest.load(initialized_draft.image_manifest_json)
    assert manifest.has_slide("S1-pos1")


def test_cli_mutate_fragment_bind(initialized_draft, capsys):
    rc = igo.main([
        "mutate-fragment-bind",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
        "--image-path", "working/05_images/S1-pos1.png",
        "--model", "gemini-3-pro-image",
        "--cost-usd", "0.014",
        "--channel", "A",
        "--approved-at", "2026-05-03T14:32:11Z",
    ])
    assert rc == 0
    fragment = json.loads(
        (initialized_draft.slides_dir / "S1_slides.json").read_text()
    )
    assert fragment["slides"][1]["content"]["image_path"] == \
        "working/05_images/S1-pos1.png"


def test_cli_record_rejected_with_request_path(initialized_draft):
    rc = igo.main([
        "record-rejected",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
        "--reason", "drift from substory",
        "--request-path", "working/05_image_requests/S1-pos1_request.json",
    ])
    assert rc == 0
    manifest = igm.Manifest.load(initialized_draft.image_manifest_json)
    entry = manifest.get("S1-pos1")
    assert "drift" in entry["reason"]
    assert entry["request_path"].endswith("_request.json")


def test_cli_duplicate_record_returns_error(initialized_draft, capsys):
    igo.main([
        "record-approved",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
        "--image-path", "i", "--request-path", "r",
        "--channel", "A", "--model", "m",
        "--cost-usd", "0.01",
    ])
    rc = igo.main([
        "record-approved",
        "--draft-dir", str(initialized_draft.draft_dir),
        "--slide-id", "S1-pos1",
        "--image-path", "i2", "--request-path", "r2",
        "--channel", "A", "--model", "m",
        "--cost-usd", "0.02",
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "already in manifest" in captured.err


# ---------------------------------------------------------------------------
# image_gen_decision list-yes CLI subcommand (added in Tier 6a)
# ---------------------------------------------------------------------------

def test_image_gen_decision_list_yes_subcommand(tmp_path, capsys):
    """The bash orchestrator iterates emit=true slide_ids via this
    subcommand. Verify it prints one slide_id per line on stdout."""
    import image_gen_decision as igd  # noqa: PLC0415

    decisions = {
        "schema_version": "image-decisions.v1",
        "tier": "STRONG",
        "mode": "talk-30",
        "user_opt_in_exploratory": False,
        "decisions": [
            {"slide_id": "S1-pos0", "layout": "section_divider",
             "emit": False, "reason": "structural"},
            {"slide_id": "S1-pos1", "layout": "concept_illustration",
             "emit": True, "reason": "AI-image vehicle"},
            {"slide_id": "S2-pos1", "layout": "concept_illustration",
             "emit": True, "reason": "AI-image vehicle"},
        ],
    }
    target = tmp_path / "decisions.json"
    target.write_text(json.dumps(decisions))
    rc = igd.main(["list-yes", str(target)])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line]
    assert lines == ["S1-pos1", "S2-pos1"]
