"""Tests for v0.3.3 merge_compose_fragments image-manifest integration.

Per V0_3_3_ARCHITECTURE.md §13 Tier 4 plan: synthetic spec with one
concept_illustration slide + manifest entry → bound figure path.
Negative test: manifest entry for non-existent slide_id → no crash,
no binding. Backwards-compat: missing manifest → behavior unchanged
from v0.3.2.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SKILL_TOOLS = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_presentation_maker" / "skill" / "tools"
)
sys.path.insert(0, str(_SKILL_TOOLS))

import image_gen_manifest as igm  # noqa: E402
import merge_compose_fragments as mcf  # noqa: E402


# ---------------------------------------------------------------------------
# apply_image_manifest — direct unit tests on the binding helper
# ---------------------------------------------------------------------------

def _concept_stub_slide() -> dict:
    """Build a concept_illustration slide stub matching slide_compose's
    {TBD}-placeholder convention (slide_compose.v1.md L756-760)."""
    return {
        "layout": "concept_illustration",
        "content": {
            "title": "Inner-loop iteration of dark-matter annotation.",
            "image_path": "{TBD}",
            "image_prompt": "test prompt",
            "style": "scientific_illustration",
            "provenance": {
                "model": "TBD",
                "cost_usd": 0,
                "channel": "A",
                "approved_at": "TBD",
            },
        },
    }


def test_apply_with_no_manifest_is_noop():
    """Backwards-compat: manifest=None → slide unchanged."""
    slide = _concept_stub_slide()
    out = mcf.apply_image_manifest(slide, None, "S2-pos4")
    assert out is slide
    assert slide["content"]["image_path"] == "{TBD}"


def test_apply_with_no_entry_is_noop():
    """Manifest exists but slide_id_target not in it → slide unchanged."""
    manifest = igm.Manifest()
    manifest.add_approved(
        slide_id="S99-pos99", image_path="other.png",
        request_path="other.json", channel="A", model="m", cost_usd=0.01,
    )
    slide = _concept_stub_slide()
    out = mcf.apply_image_manifest(slide, manifest, "S2-pos4")
    assert out is slide
    assert slide["content"]["image_path"] == "{TBD}"


def test_apply_approved_binds_image_path_and_provenance():
    manifest = igm.Manifest()
    manifest.add_approved(
        slide_id="S2-pos4",
        image_path="working/05_images/S2-pos4.png",
        request_path="working/05_image_requests/S2-pos4_request.json",
        channel="A",
        model="gemini-3-pro-image",
        cost_usd=0.014,
        approved_at="2026-05-03T14:32:11Z",
    )
    slide = _concept_stub_slide()
    out = mcf.apply_image_manifest(slide, manifest, "S2-pos4")
    assert out is slide
    # image_path bound
    assert slide["content"]["image_path"] == \
        "working/05_images/S2-pos4.png"
    # provenance fields populated from manifest entry
    prov = slide["content"]["provenance"]
    assert prov["model"] == "gemini-3-pro-image"
    assert prov["cost_usd"] == 0.014
    assert prov["channel"] == "A"
    assert prov["approved_at"] == "2026-05-03T14:32:11Z"


def test_apply_approved_creates_content_dict_when_absent():
    """If somehow the slide has no content dict yet, the helper
    creates one rather than crashing."""
    manifest = igm.Manifest()
    manifest.add_approved(
        slide_id="S2-pos4", image_path="img.png",
        request_path="r.json", channel="A", model="m", cost_usd=0.01,
    )
    slide = {"layout": "concept_illustration"}
    out = mcf.apply_image_manifest(slide, manifest, "S2-pos4")
    assert out is slide
    assert slide["content"]["image_path"] == "img.png"


def test_apply_rejected_returns_none():
    """Rejected entries → None (caller drops the slide)."""
    manifest = igm.Manifest()
    manifest.add_rejected(
        slide_id="S2-pos4", reason="user-rejected: drift from substory"
    )
    slide = _concept_stub_slide()
    out = mcf.apply_image_manifest(slide, manifest, "S2-pos4")
    assert out is None


def test_apply_skipped_returns_none():
    """Budget-skipped entries also drop (Option A applies to both)."""
    manifest = igm.Manifest()
    manifest.add_skipped(
        slide_id="S2-pos4", reason="budget cap exhausted"
    )
    slide = _concept_stub_slide()
    out = mcf.apply_image_manifest(slide, manifest, "S2-pos4")
    assert out is None


# ---------------------------------------------------------------------------
# load_image_manifest — defensive loader
# ---------------------------------------------------------------------------

def test_load_returns_none_when_path_is_none():
    assert mcf.load_image_manifest(None) is None


def test_load_returns_none_when_path_missing(tmp_path):
    assert mcf.load_image_manifest(tmp_path / "no_such.json") is None


def test_load_returns_manifest_when_present(tmp_path):
    target = tmp_path / "manifest.json"
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1", image_path="i", request_path="r",
        channel="A", model="m", cost_usd=0.01,
    )
    m.write(target)
    loaded = mcf.load_image_manifest(target)
    assert loaded is not None
    assert loaded.has_slide("S1-pos1")


def test_load_returns_none_when_malformed(tmp_path, capsys):
    """Malformed manifest doesn't crash merge — warn + None."""
    target = tmp_path / "manifest.json"
    target.write_text("{not valid json")
    out = mcf.load_image_manifest(target)
    assert out is None
    captured = capsys.readouterr()
    assert "warning" in captured.err
    assert "not loadable" in captured.err


def test_load_returns_none_on_wrong_schema_version(tmp_path, capsys):
    target = tmp_path / "manifest.json"
    target.write_text('{"schema_version": "image-manifest.v0", "entries": []}')
    out = mcf.load_image_manifest(target)
    assert out is None
    captured = capsys.readouterr()
    assert "warning" in captured.err


# ---------------------------------------------------------------------------
# CLI integration via main()
# ---------------------------------------------------------------------------

def _write_min_inputs_for_merge(tmp_path: Path,
                                 *, manifest_path: Path | None = None,
                                 concept_slides_in_s1: bool = True
                                 ) -> dict:
    """Write the minimum throughline / substory / fragment files
    merge_compose_fragments.main() needs. Returns argv dict."""
    import json
    throughline_path = tmp_path / "00_throughline.md"
    throughline_path.write_text(
        "<!-- chosen: TL1 -->\n"
        "<!-- punchline: Test punchline. -->\n"
        "## TL1: test\n"
        "**Tier:** STRONG\n"
    )
    substory_path = tmp_path / "02_substories.md"
    substory_path.write_text(
        "### S1 — First substory\n"
        "**Punchline:** test substory.\n"
    )
    fragments_dir = tmp_path / "03_slides"
    fragments_dir.mkdir()
    s1_slides = [
        {
            "layout": "section_divider",
            "content": {"title": "S1.", "punchline": "Test."},
        },
    ]
    if concept_slides_in_s1:
        s1_slides.append({
            "layout": "concept_illustration",
            "content": {
                "title": "Concept illustration test.",
                "image_path": "{TBD}",
                "image_prompt": "test prompt",
                "style": "scientific_illustration",
                "provenance": {
                    "model": "TBD",
                    "cost_usd": 0,
                    "channel": "A",
                    "approved_at": "TBD",
                },
            },
        })
    (fragments_dir / "S1_slides.json").write_text(json.dumps({
        "schema_version": "compose-fragment.v1",
        "kind": "substory",
        "substory_id": "S1",
        "slides": s1_slides,
    }))
    out_path = tmp_path / "spec.json"
    return {
        "throughline_path": str(throughline_path),
        "substory_path": str(substory_path),
        "fragments_dir": str(fragments_dir),
        "out_path": str(out_path),
        "manifest_path": str(manifest_path) if manifest_path else None,
    }


def test_main_with_no_manifest_path_is_backwards_compat(tmp_path, monkeypatch):
    """Without --image-manifest-path, merge behaves exactly as v0.3.2."""
    inputs = _write_min_inputs_for_merge(tmp_path)
    argv = [
        "merge_compose_fragments",
        "--outdir", str(tmp_path),
        "--project-id", "test_project",
        "--mode", "talk-30",
        "--tier", "STRONG",
        "--audience", "peer",
        "--throughline-path", inputs["throughline_path"],
        "--substory-path", inputs["substory_path"],
        "--fragments-dir", inputs["fragments_dir"],
        "--out", inputs["out_path"],
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = mcf.main()
    assert rc == 0
    import json
    spec = json.loads(Path(inputs["out_path"]).read_text())
    # Concept_illustration slide retains TBD placeholder (no manifest binding).
    concept_slides = [
        s for s in spec["slides"]
        if s.get("layout") == "concept_illustration"
    ]
    assert len(concept_slides) == 1
    assert concept_slides[0]["content"]["image_path"] == "{TBD}"


def test_main_with_manifest_binds_approved_image(tmp_path, monkeypatch, capsys):
    """With --image-manifest-path pointing at a manifest that approves
    the concept_illustration slide, merge binds image_path + provenance."""
    inputs = _write_min_inputs_for_merge(
        tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )
    # Build manifest that approves S1-pos1 (the concept_illustration slide;
    # pos0 is the section_divider).
    m = igm.Manifest()
    m.add_approved(
        slide_id="S1-pos1",
        image_path="working/05_images/S1-pos1.png",
        request_path="working/05_image_requests/S1-pos1_request.json",
        channel="A",
        model="gemini-3-pro-image",
        cost_usd=0.014,
        approved_at="2026-05-03T14:32:11Z",
    )
    m.write(Path(inputs["manifest_path"]))

    argv = [
        "merge_compose_fragments",
        "--outdir", str(tmp_path),
        "--project-id", "test_project",
        "--mode", "talk-30",
        "--tier", "STRONG",
        "--audience", "peer",
        "--throughline-path", inputs["throughline_path"],
        "--substory-path", inputs["substory_path"],
        "--fragments-dir", inputs["fragments_dir"],
        "--image-manifest-path", inputs["manifest_path"],
        "--out", inputs["out_path"],
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = mcf.main()
    assert rc == 0
    import json
    spec = json.loads(Path(inputs["out_path"]).read_text())
    concept_slides = [
        s for s in spec["slides"]
        if s.get("layout") == "concept_illustration"
    ]
    assert len(concept_slides) == 1
    assert concept_slides[0]["content"]["image_path"] == \
        "working/05_images/S1-pos1.png"
    assert concept_slides[0]["content"]["provenance"]["model"] == \
        "gemini-3-pro-image"
    assert concept_slides[0]["content"]["provenance"]["approved_at"] == \
        "2026-05-03T14:32:11Z"
    captured = capsys.readouterr()
    assert "bound 1 approved image" in captured.err


def test_main_with_manifest_drops_rejected_slide(tmp_path, monkeypatch, capsys):
    """A rejected concept_illustration → slide doesn't appear in output spec."""
    inputs = _write_min_inputs_for_merge(
        tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )
    m = igm.Manifest()
    m.add_rejected(
        slide_id="S1-pos1",
        reason="user-rejected: drift from substory",
    )
    m.write(Path(inputs["manifest_path"]))

    argv = [
        "merge_compose_fragments",
        "--outdir", str(tmp_path),
        "--project-id", "test_project",
        "--mode", "talk-30",
        "--tier", "STRONG",
        "--audience", "peer",
        "--throughline-path", inputs["throughline_path"],
        "--substory-path", inputs["substory_path"],
        "--fragments-dir", inputs["fragments_dir"],
        "--image-manifest-path", inputs["manifest_path"],
        "--out", inputs["out_path"],
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = mcf.main()
    assert rc == 0
    import json
    spec = json.loads(Path(inputs["out_path"]).read_text())
    # No concept_illustration slide in the output (was dropped).
    concept_slides = [
        s for s in spec["slides"]
        if s.get("layout") == "concept_illustration"
    ]
    assert len(concept_slides) == 0
    captured = capsys.readouterr()
    assert "dropped 1" in captured.err
