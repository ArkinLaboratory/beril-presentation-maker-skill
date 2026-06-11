"""Tests for visual_qa.py — opt-in visual-QA pass (v0.4 M4a Tier C).

Coverage:
- Toolchain probe (probe_toolchain).
- Stub-report writers (write_stub_reports).
- Render pipeline pieces (pptx_to_pdf, pdf_to_pngs) with subprocess mocked.
- claude -p invocation (invoke_vision_pass) — argv shape, model pin,
  allowedTools, diagnostic shape, cost parsing.
- Top-level run_visual_qa happy path (everything mocked).
- Failure paths: missing toolchain, missing spec, render failure,
  vision-pass failure — each writes a stub report, returns 0.
- CLI smoke.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VQ_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "visual_qa.py")
SLIDE_SPEC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
                 / "tools" / "slide_spec.py")
ASSEMBLE_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "tools" / "assemble_pptx.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vq():
    # Load slide_spec + assemble_pptx first so visual_qa's importlib
    # lookups succeed.
    _import("slide_spec", SLIDE_SPEC_PY)
    _import("assemble_pptx", ASSEMBLE_PY)
    return _import("visual_qa", VQ_PY)


# ---------------------------------------------------------------------------
# Toolchain probe
# ---------------------------------------------------------------------------

def test_probe_toolchain_status_ok_property(vq):
    """ok=True only when all three binaries resolve."""
    s = vq.ToolchainStatus(soffice="/u/soffice", pdftoppm="/u/pdftoppm",
                           claude="/u/claude")
    assert s.ok is True
    assert s.missing() == []


def test_probe_toolchain_status_missing(vq):
    """Missing binaries are named in the missing() report."""
    s = vq.ToolchainStatus(soffice=None, pdftoppm="/u/pdftoppm",
                           claude=None)
    assert s.ok is False
    miss = s.missing()
    assert any("soffice" in m for m in miss)
    assert any("claude" in m for m in miss)
    assert not any("pdftoppm" in m for m in miss)


def test_probe_toolchain_uses_shutil_which(vq, monkeypatch):
    """probe_toolchain delegates to shutil.which for each binary."""
    fakes = {"soffice": "/u/soffice", "pdftoppm": None, "my-claude": "/u/c"}

    def fake_which(name):
        return fakes.get(name)

    monkeypatch.setattr(vq.shutil, "which", fake_which)
    status = vq.probe_toolchain(claude_bin="my-claude")
    assert status.soffice == "/u/soffice"
    assert status.pdftoppm is None
    assert status.claude == "/u/c"


# ---------------------------------------------------------------------------
# Stub-report writers
# ---------------------------------------------------------------------------

def test_write_stub_reports_emits_advisory_schema(vq, tmp_path):
    """The stub report carries schema_version + draft_dir + note +
    empty findings, plus a parallel .md."""
    j = tmp_path / "audit" / "visual_qa.json"
    m = tmp_path / "audit" / "visual_qa.md"
    vq.write_stub_reports(j, m, tmp_path, note="missing dependency: pdftoppm")
    payload = json.loads(j.read_text())
    assert payload["schema_version"] == vq.SCHEMA_VERSION
    assert payload["n_slides_reviewed"] == 0
    assert payload["findings"] == []
    assert "pdftoppm" in payload["note"]
    md = m.read_text()
    assert "Visual QA report" in md
    assert "pdftoppm" in md


# ---------------------------------------------------------------------------
# Render pipeline (subprocess-mocked)
# ---------------------------------------------------------------------------

def test_pptx_to_pdf_invokes_soffice_with_outdir(vq, tmp_path):
    """soffice --headless --convert-to pdf --outdir <dir> <pptx>"""
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"fake-pptx")
    out_dir = tmp_path / "audit"

    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        # Simulate soffice writing the pdf
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "deck.pdf").write_bytes(b"fake-pdf")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(vq.subprocess, "run", side_effect=fake_run):
        pdf = vq.pptx_to_pdf(pptx, out_dir, soffice_bin="/u/soffice")

    assert captured[0] == "/u/soffice"
    assert "--headless" in captured
    assert "--convert-to" in captured
    assert "pdf" in captured
    assert "--outdir" in captured
    assert pdf == out_dir / "deck.pdf"


def test_pptx_to_pdf_raises_when_pdf_missing(vq, tmp_path):
    """If soffice exits 0 but the expected .pdf isn't produced,
    raise RuntimeError so the caller logs + bails."""
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"fake-pptx")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(vq.subprocess, "run", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="did not produce"):
            vq.pptx_to_pdf(pptx, tmp_path / "audit",
                           soffice_bin="/u/soffice")


def test_pdf_to_pngs_invokes_pdftoppm_and_returns_sorted_pngs(vq, tmp_path):
    """pdftoppm -png -r <dpi> <pdf> <prefix> ; result PNGs returned sorted."""
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"fake-pdf")
    out_dir = tmp_path / "pngs"

    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        # Simulate pdftoppm emitting 3 PNGs in non-sorted file-creation order
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in (2, 1, 3):
            (out_dir / f"deck-{i:02d}.png").write_bytes(b"fake-png")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(vq.subprocess, "run", side_effect=fake_run):
        pngs = vq.pdf_to_pngs(pdf, out_dir, pdftoppm_bin="/u/pdftoppm",
                              dpi=150)

    assert captured[0] == "/u/pdftoppm"
    assert "-png" in captured
    assert "-r" in captured
    assert "150" in captured
    # Sorted naturally → 01, 02, 03
    assert [p.name for p in pngs] == ["deck-01.png", "deck-02.png", "deck-03.png"]


def test_build_slide_png_mapping_aligns_by_position(vq, tmp_path):
    """spec.slides[i] pairs with png_paths[i]; carries slide_id + layout."""
    spec = {"slides": [
        {"id": 1, "layout": "title", "content": {}},
        {"id": 2, "layout": "big_number", "content": {}},
        {"id": 3, "layout": "data_figure", "content": {}},
    ]}
    pngs = [tmp_path / f"deck-{i:02d}.png" for i in (1, 2, 3)]
    for p in pngs:
        p.write_bytes(b"x")
    m = vq.build_slide_png_mapping(spec, pngs)
    assert len(m) == 3
    assert m[0]["slide_id"] == 1 and m[0]["layout"] == "title"
    assert m[1]["slide_id"] == 2 and m[1]["layout"] == "big_number"
    assert m[2]["png_path"].endswith("deck-03.png")


def test_build_slide_png_mapping_truncates_to_shorter_png_list(vq, tmp_path):
    """If pdftoppm produced fewer PNGs than spec slides, truncate."""
    spec = {"slides": [
        {"id": 1, "layout": "title", "content": {}},
        {"id": 2, "layout": "big_number", "content": {}},
    ]}
    pngs = [tmp_path / "deck-01.png"]
    pngs[0].write_bytes(b"x")
    m = vq.build_slide_png_mapping(spec, pngs)
    assert len(m) == 1
    assert m[0]["slide_id"] == 1


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------

def test_invoke_vision_pass_builds_argv(vq, tmp_path):
    """argv carries -p, --model, --system-prompt, --allowedTools Read,Write,
    --output-format json, --dangerously-skip-permissions, plus the user
    prompt."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"slides": []}))
    out_json = tmp_path / "audit" / "visual_qa.json"
    out_md = tmp_path / "audit" / "visual_qa.md"

    envelope = json.dumps({"type": "result", "total_cost_usd": 0.0321})
    fake_proc = MagicMock(returncode=0, stdout=envelope, stderr="")

    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        # Simulate the model writing the JSON output
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({"findings": []}))
        return fake_proc

    with patch.object(vq.subprocess, "run", side_effect=fake_run):
        diag = vq.invoke_vision_pass(
            draft_dir=tmp_path,
            slide_spec_path=spec_path,
            slide_png_mapping=[{"slide_id": 1, "layout": "title",
                                "png_path": "/tmp/x.png"}],
            out_json_path=out_json,
            out_md_path=out_md,
            claude_bin="claude",
        )

    assert captured[0] == "claude"
    assert "-p" in captured
    assert "--system-prompt" in captured
    assert "--allowedTools" in captured
    # Vision pass uses Read+Write only (NOT Bash) — structured review.
    assert "Read,Write" in captured
    assert "--dangerously-skip-permissions" in captured
    assert "--model" in captured
    # Default model pinned (DEFAULT_MODEL)
    assert captured[captured.index("--model") + 1] == vq.DEFAULT_MODEL
    assert "--output-format" in captured
    assert captured[captured.index("--output-format") + 1] == "json"

    # Diagnostic shape mirrors extract_claims (same envelope pattern)
    assert diag["tool"] == "visual_qa"
    assert diag["phase"] == "vision_review"
    assert diag["exit_status"] == 0
    assert diag["output_present"] is True
    assert diag["cost_usd"] == 0.0321
    assert "stdout_tail" in diag
    assert "stderr_tail" in diag
    assert diag["model"] == vq.DEFAULT_MODEL


def test_invoke_vision_pass_model_override(vq, tmp_path):
    """A non-default --model is threaded into argv + diagnostic."""
    out_json = tmp_path / "audit" / "visual_qa.json"
    out_md = tmp_path / "audit" / "visual_qa.md"
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{}")

    fake_proc = MagicMock(returncode=0, stdout="{}", stderr="")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.extend(cmd)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text("{}")
        return fake_proc

    with patch.object(vq.subprocess, "run", side_effect=fake_run):
        diag = vq.invoke_vision_pass(
            draft_dir=tmp_path,
            slide_spec_path=spec_path,
            slide_png_mapping=[],
            out_json_path=out_json,
            out_md_path=out_md,
            claude_bin="claude",
            model="claude-opus-4-7",
        )

    assert captured[captured.index("--model") + 1] == "claude-opus-4-7"
    assert diag["model"] == "claude-opus-4-7"


def test_invoke_vision_pass_missing_prompt_raises(vq, tmp_path):
    """A missing system prompt file is operator error → FileNotFoundError."""
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("{}")
    bogus = tmp_path / "no-such-prompt.md"
    with pytest.raises(FileNotFoundError):
        vq.invoke_vision_pass(
            draft_dir=tmp_path,
            slide_spec_path=spec_path,
            slide_png_mapping=[],
            out_json_path=out_json,
            out_md_path=out_md,
            prompt_path=bogus,
            claude_bin="claude",
        )


def test_parse_cost_from_envelope_happy(vq):
    envelope = json.dumps({"type": "result", "total_cost_usd": 0.42})
    cost, note = vq._parse_cost_from_envelope(envelope)
    assert cost == 0.42
    assert note == ""


def test_parse_cost_from_envelope_missing_field(vq):
    cost, note = vq._parse_cost_from_envelope(json.dumps({"type": "result"}))
    assert cost == 0.0
    assert "missing" in note


def test_parse_cost_from_envelope_unparseable(vq):
    cost, note = vq._parse_cost_from_envelope("not json")
    assert cost == 0.0
    assert "not parseable" in note


# ---------------------------------------------------------------------------
# run_visual_qa — top-level failure paths
# ---------------------------------------------------------------------------

def test_run_visual_qa_returns_0_when_toolchain_incomplete(vq, tmp_path, monkeypatch, capsys):
    """Missing dep → stub report + rc=0 (advisory). C1-B: the stub now
    carries `skipped: true` + reason (so the orchestrator records
    skipped-with-reason), and the operator-facing message is LOUD even
    under quiet=True (a missing host binary is a P1, never a silent
    no-op)."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice=None, pdftoppm="/u/p", claude="/u/c"))
    rc = vq.run_visual_qa(tmp_path, quiet=True)  # quiet must NOT silence it
    assert rc == 0
    payload = json.loads((tmp_path / "audit" / "visual_qa.json").read_text())
    assert payload["findings"] == []
    assert "soffice" in payload["note"]
    # C1-B: explicit skipped-with-reason flag for the run-record.
    assert payload["skipped"] is True
    assert "soffice" in payload["skipped_reason"]
    # C1-B: loud P1 message on stderr despite quiet=True.
    err = capsys.readouterr().err
    assert "SKIPPED" in err and "missing host dependencies" in err
    assert "P1" in err


def test_run_visual_qa_returns_0_when_spec_missing(vq, tmp_path, monkeypatch):
    """No slide_spec.json → stub report + rc=0."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice="/u/s", pdftoppm="/u/p", claude="/u/c"))
    rc = vq.run_visual_qa(tmp_path)
    assert rc == 0
    payload = json.loads((tmp_path / "audit" / "visual_qa.json").read_text())
    assert "not found" in payload["note"]


def test_run_visual_qa_returns_0_when_spec_unreadable(vq, tmp_path, monkeypatch):
    """Malformed slide_spec.json → stub report + rc=0."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice="/u/s", pdftoppm="/u/p", claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("{ not json")
    rc = vq.run_visual_qa(tmp_path)
    assert rc == 0
    payload = json.loads((tmp_path / "audit" / "visual_qa.json").read_text())
    assert "unreadable" in payload["note"]


def test_run_visual_qa_returns_0_when_assemble_fails(vq, tmp_path, monkeypatch):
    """assemble_pptx failure → stub report + rc=0."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice="/u/s", pdftoppm="/u/p", claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({"slides": []}))   # invalid spec; assemble will raise

    def fake_assemble(slide_spec_path, out_pptx):
        raise RuntimeError("synthetic assembler failure")

    monkeypatch.setattr(vq, "assemble_pptx_for_qa", fake_assemble)
    rc = vq.run_visual_qa(tmp_path)
    assert rc == 0
    payload = json.loads((tmp_path / "audit" / "visual_qa.json").read_text())
    assert "synthetic assembler failure" in payload["note"]


def test_run_visual_qa_returns_0_when_vision_pass_fails(vq, tmp_path, monkeypatch):
    """claude -p non-zero exit → stub report + rc=0; PNGs preserved
    for manual review."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice="/u/s", pdftoppm="/u/p", claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({
        "schema_version": "v1", "slides": [{"id": 1, "layout": "title"}],
    }))

    # Stub each pipeline step
    monkeypatch.setattr(vq, "assemble_pptx_for_qa",
                        lambda spec, pptx: (1, []))
    monkeypatch.setattr(vq, "pptx_to_pdf",
                        lambda pptx, outdir, **kw: outdir / "deck.pdf")
    fake_png = tmp_path / "audit" / "visual_qa_pngs" / "deck-01.png"

    def _fake_pngs(pdf, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        fake_png.write_bytes(b"png")
        return [fake_png]

    monkeypatch.setattr(vq, "pdf_to_pngs", _fake_pngs)
    monkeypatch.setattr(vq, "invoke_vision_pass",
                        lambda **kw: {
                            "tool": "visual_qa", "exit_status": 2,
                            "output_present": False, "cost_usd": 0.0,
                            "cost_note": "", "stdout_tail": "",
                            "stderr_tail": "model rate-limited",
                            "model": vq.DEFAULT_MODEL, "duration_sec": 1,
                            "version": vq.VERSION, "phase": "vision_review",
                            "timestamp": "x", "claude_bin": "/u/c",
                        })
    rc = vq.run_visual_qa(tmp_path, quiet=True)
    assert rc == 0
    payload = json.loads((tmp_path / "audit" / "visual_qa.json").read_text())
    assert "rate-limited" in payload["note"]
    # PNGs preserved for manual review on LLM failure
    assert fake_png.is_file(), "PNGs must be preserved when vision pass fails"


# ---------------------------------------------------------------------------
# run_visual_qa — happy path (everything mocked)
# ---------------------------------------------------------------------------

def _stub_assemble(pptx, n_slides):
    """Return a no-op assemble_pptx_for_qa fake that writes a stub pptx."""
    def _fake(spec_path, out_pptx):
        out_pptx.parent.mkdir(parents=True, exist_ok=True)
        out_pptx.write_bytes(b"pptx")
        return (n_slides, [])
    return _fake


def _stub_pptx_to_pdf():
    def _fake(pptx, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        pdf = outdir / (pptx.stem + ".pdf")
        pdf.write_bytes(b"pdf")
        return pdf
    return _fake


def _stub_pdf_to_pngs(n):
    def _fake(pdf, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        out = []
        for i in range(1, n + 1):
            p = outdir / f"{pdf.stem}-{i:02d}.png"
            p.write_bytes(b"png")
            out.append(p)
        return out
    return _fake


def _stub_vision(vq, *, findings):
    def _fake(*, out_json_path, out_md_path, **kw):
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        out_json_path.write_text(json.dumps({
            "schema_version": vq.SCHEMA_VERSION,
            "draft_dir": str(kw["draft_dir"]),
            "n_slides_reviewed": len(kw.get("slide_png_mapping", [])),
            "findings": findings,
        }))
        out_md_path.write_text("# Visual QA report\n")
        return {
            "tool": "visual_qa", "exit_status": 0, "output_present": True,
            "cost_usd": 0.012, "cost_note": "", "stdout_tail": "",
            "stderr_tail": "", "model": vq.DEFAULT_MODEL, "duration_sec": 5,
            "version": vq.VERSION, "phase": "vision_review",
            "timestamp": "x", "claude_bin": "/u/c",
        }
    return _fake


def test_run_visual_qa_happy_path_cleans_up_pngs_by_default(vq, tmp_path, monkeypatch):
    """End-to-end stub: tool runs clean, rc=0, intermediate PNGs cleaned."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice="/u/s", pdftoppm="/u/p", claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({
        "schema_version": "v1",
        "slides": [{"id": 1, "layout": "title"},
                   {"id": 2, "layout": "big_number"}],
    }))

    monkeypatch.setattr(vq, "assemble_pptx_for_qa", _stub_assemble(None, 2))
    monkeypatch.setattr(vq, "pptx_to_pdf", _stub_pptx_to_pdf())
    monkeypatch.setattr(vq, "pdf_to_pngs", _stub_pdf_to_pngs(2))
    monkeypatch.setattr(vq, "invoke_vision_pass",
                        _stub_vision(vq, findings=[{
                            "slide_id": 1, "kind": "container_breach",
                            "severity": "warning", "confidence": "medium",
                            "detail": "synthetic finding for test",
                            "evidence_locator": "title",
                        }]))

    rc = vq.run_visual_qa(tmp_path, quiet=True)
    assert rc == 0
    payload = json.loads((tmp_path / "audit" / "visual_qa.json").read_text())
    assert payload["n_slides_reviewed"] == 2
    assert len(payload["findings"]) == 1
    # PNGs cleaned by default (no --keep-pngs)
    pngs_dir = tmp_path / "audit" / "visual_qa_pngs"
    assert not pngs_dir.exists() or not list(pngs_dir.iterdir()), \
        f"expected pngs cleaned; found {list(pngs_dir.iterdir()) if pngs_dir.exists() else []}"


def test_run_visual_qa_keep_pngs_preserves(vq, tmp_path, monkeypatch):
    """--keep-pngs preserves the audit/visual_qa_pngs/ directory."""
    monkeypatch.setattr(vq, "probe_toolchain",
                        lambda *a, **kw: vq.ToolchainStatus(
                            soffice="/u/s", pdftoppm="/u/p", claude="/u/c"))
    spec_path = tmp_path / "working" / "slide_spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(json.dumps({
        "slides": [{"id": 1, "layout": "title"}],
    }))
    monkeypatch.setattr(vq, "assemble_pptx_for_qa", _stub_assemble(None, 1))
    monkeypatch.setattr(vq, "pptx_to_pdf", _stub_pptx_to_pdf())
    monkeypatch.setattr(vq, "pdf_to_pngs", _stub_pdf_to_pngs(1))
    monkeypatch.setattr(vq, "invoke_vision_pass",
                        _stub_vision(vq, findings=[]))

    rc = vq.run_visual_qa(tmp_path, quiet=True, keep_pngs=True)
    assert rc == 0
    # PNGs dir must still exist and be non-empty
    pngs_dir = tmp_path / "audit" / "visual_qa_pngs"
    assert pngs_dir.is_dir() and list(pngs_dir.iterdir()), \
        "expected PNGs preserved with --keep-pngs"


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_main_returns_0_on_missing_draft(vq, tmp_path):
    """CLI on an empty directory → missing-toolchain stub OR missing-
    spec stub depending on local env; either way rc=0."""
    rc = vq.main([str(tmp_path), "--quiet"])
    assert rc == 0
