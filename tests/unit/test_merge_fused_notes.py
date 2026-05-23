"""Contract test — the v0.4 `compose-fragment.v2` fused-notes shape
against `merge_compose_fragments.py` (M3 Tier D, D-033).

The v0.4 composer (`slide_compose.v2.md`) authors speaker notes inline:
each slide carries a finished `speaker_notes` string and the fragment
declares `schema_version: "compose-fragment.v2"`. `merge_compose_fragments.py`
must (1) keep that inline `speaker_notes` on the merged slide and
(2) derive `working/04_speaker_notes/{sid}_notes.json` from it so
beril-adversarial's `--type presentation` reviewer still finds the
notes. These tests pin both halves of that contract — if the field
name or the derived shape drifts, they fail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)
sys.path.insert(0, str(TOOLS_DIR))

import merge_compose_fragments as mcf  # noqa: E402


def _v2_fragment(sid: str, notes: list[str]) -> dict:
    """A compose-fragment.v2 fragment: notes inline on each slide."""
    return {
        "schema_version": "compose-fragment.v2",
        "substory_id": sid,
        "slides": [
            {"position": i, "layout": "claim_evidence",
             "content": {"title": f"t{i}", "bullets": ["b"]},
             "speaker_notes": note,
             "evidence_anchors": [{"kind": "report_section", "ref": "§1"}]}
            for i, note in enumerate(notes)
        ],
    }


# ----------------------------------------------------------------------
# strip_orchestrator_metadata — the inline-notes contract
# ----------------------------------------------------------------------

def test_strip_keeps_inline_speaker_notes() -> None:
    """The merged slide must retain a v2 fragment's inline speaker_notes."""
    slide = {"position": 0, "layout": "claim_evidence",
             "content": {"title": "t"}, "speaker_notes": "finished notes",
             "evidence_anchors": [{"kind": "notebook", "ref": "c1"}]}
    cleaned = mcf.strip_orchestrator_metadata(slide)
    assert cleaned["speaker_notes"] == "finished notes"
    # orchestrator-only metadata is still dropped
    assert "evidence_anchors" not in cleaned
    assert "position" not in cleaned


def test_strip_drops_v1_seed() -> None:
    """v0.3.x raw seed is still dropped (not promoted)."""
    slide = {"position": 0, "layout": "claim_evidence",
             "content": {"title": "t"}, "speaker_notes_seed": "raw seed"}
    cleaned = mcf.strip_orchestrator_metadata(slide)
    assert "speaker_notes_seed" not in cleaned
    assert "speaker_notes" not in cleaned


# ----------------------------------------------------------------------
# derive_speaker_notes_files — the cross-skill contract
# ----------------------------------------------------------------------

def test_derive_writes_notes_json_for_v2(tmp_path: Path) -> None:
    fragments = {"S1": _v2_fragment("S1", ["note zero", "note one"])}
    substories = [{"id": "S1"}]
    n = mcf.derive_speaker_notes_files(fragments, substories, tmp_path)
    assert n == 1
    derived = json.loads((tmp_path / "S1_notes.json").read_text())
    assert derived["substory_id"] == "S1"
    assert derived["notes_by_position"] == {"0": "note zero", "1": "note one"}


def test_derived_shape_roundtrips_through_the_loader(tmp_path: Path) -> None:
    """The derived file must read back through the same loader the v0.3.x
    path uses — that loader's shape is what beril-adversarial also reads."""
    fragments = {"S2": _v2_fragment("S2", ["alpha", "beta", "gamma"])}
    mcf.derive_speaker_notes_files(fragments, [{"id": "S2"}], tmp_path)
    loaded = mcf.load_speaker_notes_for_substory(tmp_path, "S2")
    assert loaded == {0: "alpha", 1: "beta", 2: "gamma"}


def test_derive_is_noop_for_v1_fragment(tmp_path: Path) -> None:
    """A compose-fragment.v1 fragment must NOT trigger derivation — the
    v0.3.x path's speaker_notes stage owns those files."""
    v1 = {"schema_version": "compose-fragment.v1", "substory_id": "S1",
          "slides": [{"position": 0, "layout": "claim_evidence",
                      "content": {"title": "t"},
                      "speaker_notes_seed": "seed"}]}
    n = mcf.derive_speaker_notes_files({"S1": v1}, [{"id": "S1"}], tmp_path)
    assert n == 0
    assert list(tmp_path.glob("*.json")) == []


def test_derive_is_noop_when_dir_is_none() -> None:
    fragments = {"S1": _v2_fragment("S1", ["x"])}
    assert mcf.derive_speaker_notes_files(fragments, [{"id": "S1"}], None) == 0


def test_derive_skips_slides_with_empty_notes(tmp_path: Path) -> None:
    """A slide missing speaker_notes is omitted from notes_by_position,
    not written as an empty string."""
    frag = {
        "schema_version": "compose-fragment.v2", "substory_id": "S1",
        "slides": [
            {"position": 0, "layout": "section_divider",
             "content": {}, "speaker_notes": "divider notes"},
            {"position": 1, "layout": "claim_evidence", "content": {}},
            {"position": 2, "layout": "claim_evidence",
             "content": {}, "speaker_notes": "   "},
        ],
    }
    mcf.derive_speaker_notes_files({"S1": frag}, [{"id": "S1"}], tmp_path)
    derived = json.loads((tmp_path / "S1_notes.json").read_text())
    assert derived["notes_by_position"] == {"0": "divider notes"}


def test_derive_handles_multiple_substories(tmp_path: Path) -> None:
    fragments = {
        "S1": _v2_fragment("S1", ["s1n0"]),
        "S2": _v2_fragment("S2", ["s2n0", "s2n1"]),
    }
    n = mcf.derive_speaker_notes_files(
        fragments, [{"id": "S1"}, {"id": "S2"}], tmp_path)
    assert n == 2
    assert (tmp_path / "S1_notes.json").is_file()
    assert (tmp_path / "S2_notes.json").is_file()
