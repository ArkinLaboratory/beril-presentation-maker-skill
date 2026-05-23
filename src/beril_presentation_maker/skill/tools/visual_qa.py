#!/usr/bin/env python3
"""visual_qa.py — opt-in visual-QA pass for an assembled deck (v0.4 M4a).

V0_4_ARCHITECTURE.md §16 M4a + M4_PUNCH_LIST.md Tier C: M3's live smoke
on ibd_phage_targeting surfaced render-quality defects (text overflow,
element overlap, footer collisions, headline↔body mismatch) that the
LLM composers and deterministic validators could not catch — they only
become visible once the slide is actually rendered. Visual QA closes
that gap: render the deck, hand the per-slide PNGs to a vision-capable
``claude -p`` invocation, and write advisory findings to
``audit/visual_qa.{md,json}``.

This is an OPT-IN, ADVISORY pass (DQ1 — Adam 2026-05-23):

- Opt-in via ``beril-presentation-maker visual-qa <draft>`` (CLI verb)
  or the orchestrator's ``--visual-qa`` flag.
- rc=0 always; findings are advisory, never block assembly.
- Costs a LibreOffice render + a vision-LLM call (Sonnet 4.6, not Opus
  — the review is a structured pass, not free-form authoring).

Pipeline (DQ2 — soffice → pdf → pdftoppm):

  1. Load slide_spec.json from <draft_dir>/working/slide_spec.json.
  2. Assemble to .pptx via assemble_pptx.assemble() (or reuse an
     existing draft.pptx if present and --reuse-pptx given).
  3. ``soffice --headless --convert-to pdf`` → .pdf
  4. ``pdftoppm`` → per-slide PNGs in audit/visual_qa_pngs/.
  5. Invoke ``claude -p`` with prompts/visual_qa.v1.md as system prompt
     and the SLIDE_PNG_MAPPING as user input.
  6. The model writes audit/visual_qa.json + audit/visual_qa.md
     (advisory findings, schema visual-qa.v1).

The five defect classes the vision pass flags (see visual_qa.v1.md):
  container_breach, element_overlap, footer_or_title_collision,
  illegible_scale, headline_body_mismatch.

CLI:
    python3 visual_qa.py <draft_dir> [--quiet] [--keep-pngs]
                                     [--reuse-pptx] [--model NAME]
                                     [--claude-bin PATH]

Exit code: always 0 (advisory; like reconcile_deck.py).

Dependencies: LibreOffice (`soffice`), Poppler (`pdftoppm`), `claude`
CLI on PATH. The configure subcommand should probe for these (deferred
to a future ``configure.py`` extension; for now, the tool emits a clear
diagnostic when a dependency is missing and exits 0).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "visual-qa.v1"
VERSION = "0.4.0-m4a-tierC"

_THIS_DIR = Path(__file__).resolve().parent
_PROMPT_PATH = _THIS_DIR.parent / "prompts" / "visual_qa.v1.md"

# Default model for the vision pass. Sonnet 4.6 is vision-capable and
# substantially cheaper than Opus for a structured-output review — the
# task is "scan and flag," not "compose." Override via --model.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Allowed tools for the claude -p subprocess. Vision pass needs Read
# (loads PNGs as vision inputs + reads slide_spec.json) + Write (emits
# the two audit files). NOT Bash — visual_qa is a structured review,
# not a tool-using agent.
_ALLOWED_TOOLS = "Read,Write"


# ---------------------------------------------------------------------------
# Dependency probes
# ---------------------------------------------------------------------------

def _which(binary: str) -> str | None:
    """Return absolute path to binary on PATH, or None."""
    return shutil.which(binary)


@dataclass
class ToolchainStatus:
    """Result of probing the visual-QA dependencies."""
    soffice: str | None
    pdftoppm: str | None
    claude: str | None

    @property
    def ok(self) -> bool:
        return bool(self.soffice and self.pdftoppm and self.claude)

    def missing(self) -> list[str]:
        return [
            name for name, path in (
                ("soffice (LibreOffice)", self.soffice),
                ("pdftoppm (Poppler)", self.pdftoppm),
                ("claude (Claude Code CLI)", self.claude),
            )
            if not path
        ]


def probe_toolchain(claude_bin: str = "claude") -> ToolchainStatus:
    """Probe the three external binaries needed for the visual-QA pass."""
    return ToolchainStatus(
        soffice=_which("soffice"),
        pdftoppm=_which("pdftoppm"),
        claude=_which(claude_bin),
    )


# ---------------------------------------------------------------------------
# Render pipeline (.pptx → .pdf → per-slide PNGs)
# ---------------------------------------------------------------------------

def assemble_pptx_for_qa(
    slide_spec_path: Path,
    out_pptx: Path,
) -> tuple[int, list[str]]:
    """Assemble slide_spec.json to a .pptx for the QA render.

    Returns (n_slides, warnings). Raises on assembler failure — that's
    the caller's signal to bail with a clear note.
    """
    spec = importlib.util.spec_from_file_location(
        "assemble_pptx", _THIS_DIR / "assemble_pptx.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load assemble_pptx.py for visual-QA render")
    module = importlib.util.module_from_spec(spec)
    sys.modules["assemble_pptx"] = module
    spec.loader.exec_module(module)
    result = module.assemble(slide_spec_path, out_pptx)
    return result.n_slides, list(result.warnings)


def pptx_to_pdf(
    pptx_path: Path,
    out_dir: Path,
    *,
    soffice_bin: str = "soffice",
    timeout_sec: int = 120,
) -> Path:
    """Convert .pptx → .pdf via LibreOffice.

    Returns the produced .pdf path. Raises subprocess.CalledProcessError
    on non-zero exit; the caller logs + bails advisory.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice_bin, "--headless",
        "--convert-to", "pdf",
        "--outdir", str(out_dir),
        str(pptx_path),
    ]
    subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout_sec,
    )
    pdf_path = out_dir / (pptx_path.stem + ".pdf")
    if not pdf_path.is_file():
        raise RuntimeError(
            f"soffice ran but did not produce expected {pdf_path}"
        )
    return pdf_path


def pdf_to_pngs(
    pdf_path: Path,
    out_dir: Path,
    *,
    pdftoppm_bin: str = "pdftoppm",
    dpi: int = 100,
    timeout_sec: int = 60,
) -> list[Path]:
    """Convert .pdf → per-slide PNGs via Poppler's pdftoppm.

    Filenames follow ``<stem>-NN.png`` (1-indexed, zero-padded by
    pdftoppm). Returns the sorted list of PNG paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    cmd = [
        pdftoppm_bin,
        "-png",
        "-r", str(dpi),
        str(pdf_path),
        str(out_dir / stem),
    ]
    subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout_sec,
    )
    pngs = sorted(out_dir.glob(f"{stem}-*.png"))
    return pngs


def build_slide_png_mapping(
    spec: dict, png_paths: list[Path]
) -> list[dict]:
    """Pair each slide_spec slide with the matching PNG by position.

    pdftoppm emits 1-indexed PNGs in document order; assemble_pptx
    writes slides in spec.slides order; the two orderings are aligned.
    """
    slides = spec.get("slides", []) or []
    mapping: list[dict] = []
    for i, slide in enumerate(slides):
        if i >= len(png_paths):
            break
        mapping.append({
            "slide_id": slide.get("id", i + 1),
            "layout": slide.get("layout", "?"),
            "png_path": str(png_paths[i].resolve()),
        })
    return mapping


# ---------------------------------------------------------------------------
# claude -p vision invocation
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_cost_from_envelope(stdout: str) -> tuple[float, str]:
    """Parse total_cost_usd from a claude -p --output-format json envelope.

    Same pattern as extract_claims.py — a telemetry miss never fails
    the call; cost_usd falls back to 0.0 with a cost_note explaining
    why.
    """
    if not stdout:
        return 0.0, "no stdout captured"
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return 0.0, "stdout not parseable as JSON"
    if not isinstance(envelope, dict):
        return 0.0, "stdout JSON is not an object"
    cost = envelope.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        return float(cost), ""
    return 0.0, "total_cost_usd missing from envelope"


def invoke_vision_pass(
    *,
    draft_dir: Path,
    slide_spec_path: Path,
    slide_png_mapping: list[dict],
    out_json_path: Path,
    out_md_path: Path,
    prompt_path: Path = _PROMPT_PATH,
    claude_bin: str = "claude",
    model: str = DEFAULT_MODEL,
    env: dict | None = None,
) -> dict:
    """Invoke ``claude -p`` with the visual_qa.v1 system prompt.

    The user prompt names the inputs (draft_dir, slide_spec_path,
    slide_png_mapping, the two output paths); the system prompt is
    visual_qa.v1.md which tells the model to read the PNGs, scan for
    the five defect classes, and write audit/visual_qa.{json,md}.

    Returns a diagnostic dict (exit_status, output_present, duration_sec,
    cost_usd, cost_note, stdout_tail, stderr_tail, model). Does NOT
    raise on subprocess failure — the caller decides escalation.
    """
    if not prompt_path.is_file():
        raise FileNotFoundError(
            f"visual_qa prompt not found at {prompt_path}; "
            f"check that the skill package is installed correctly."
        )
    system_prompt = prompt_path.read_text(encoding="utf-8")

    # User prompt names the inputs + outputs. SLIDE_PNG_MAPPING is a JSON
    # array so the model can iterate; the system prompt instructs Read
    # on each PNG path to load it as a vision input.
    mapping_json = json.dumps(slide_png_mapping, indent=2)
    user_prompt = (
        "Please execute the visual-QA review task.\n"
        f"- DRAFT_DIR: {draft_dir}\n"
        f"- SLIDE_SPEC_PATH: {slide_spec_path}\n"
        f"- OUT_PATH: {out_json_path}\n"
        f"- OUT_PATH_MD: {out_md_path}\n"
        f"- SLIDE_PNG_MAPPING:\n{mapping_json}\n"
        "\n"
        "For each slide: Read the PNG path with the Read tool (loads "
        "it as a vision input), inspect for the five defect classes "
        "from your system prompt, and accumulate findings. Then write "
        "the JSON + MD reports to the OUT paths."
    )

    cmd = [
        claude_bin, "-p",
        "--model", model,
        "--system-prompt", system_prompt,
        "--allowedTools", _ALLOWED_TOOLS,
        "--output-format", "json",
        "--dangerously-skip-permissions",
        user_prompt,
    ]

    out_json_path.parent.mkdir(parents=True, exist_ok=True)

    start = _utc_now_iso()
    t0 = datetime.now(timezone.utc)
    proc = subprocess.run(
        cmd,
        env=env if env is not None else os.environ.copy(),
        capture_output=True,
        text=True,
    )
    duration = (datetime.now(timezone.utc) - t0).total_seconds()

    cost_usd, cost_note = _parse_cost_from_envelope(proc.stdout)

    return {
        "tool": "visual_qa",
        "version": VERSION,
        "phase": "vision_review",
        "timestamp": start,
        "duration_sec": duration,
        "exit_status": proc.returncode,
        "output_present": out_json_path.is_file(),
        "cost_usd": cost_usd,
        "cost_note": cost_note,
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
        "claude_bin": claude_bin,
        "model": model,
    }


# ---------------------------------------------------------------------------
# Stub-report writers (used when the pass can't run end-to-end)
# ---------------------------------------------------------------------------

def write_stub_reports(
    out_json_path: Path,
    out_md_path: Path,
    draft_dir: Path,
    note: str,
) -> None:
    """Write minimal advisory reports when the pass cannot run (missing
    toolchain, missing spec, render failure). Always exits 0, so the
    operator gets *some* artifact explaining what happened."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "draft_dir": str(draft_dir),
        "n_slides_reviewed": 0,
        "findings": [],
        "note": note,
    }
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(payload, indent=2) + "\n")
    md = (
        "# Visual QA report\n\n"
        f"Draft: `{draft_dir}`\n\n"
        f"_{note}_\n\n"
        "No slides reviewed. The visual-QA pass is advisory; the "
        "pipeline proceeded with rc=0.\n"
    )
    out_md_path.write_text(md)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run_visual_qa(
    draft_dir: Path,
    *,
    quiet: bool = False,
    keep_pngs: bool = False,
    reuse_pptx: bool = False,
    claude_bin: str = "claude",
    model: str = DEFAULT_MODEL,
) -> int:
    """Run the full pipeline end-to-end. Always returns 0 (advisory).

    On any failure path (missing toolchain, missing spec, render error,
    LLM error), writes a stub report explaining what happened, prints
    a single-line stderr summary, and returns 0.
    """
    audit_dir = draft_dir / "audit"
    out_json = audit_dir / "visual_qa.json"
    out_md = audit_dir / "visual_qa.md"
    pngs_dir = audit_dir / "visual_qa_pngs"

    # --- 1. Probe toolchain ---
    status = probe_toolchain(claude_bin)
    if not status.ok:
        missing = ", ".join(status.missing())
        write_stub_reports(
            out_json, out_md, draft_dir,
            note=f"visual-QA toolchain incomplete (missing: {missing}); "
                 f"install LibreOffice + Poppler + Claude Code CLI to enable.",
        )
        if not quiet:
            print(f"  visual-qa: skipped — missing dependencies: {missing}",
                  file=sys.stderr)
        return 0

    # --- 2. Locate slide_spec.json ---
    slide_spec_path = draft_dir / "working" / "slide_spec.json"
    if not slide_spec_path.is_file():
        write_stub_reports(
            out_json, out_md, draft_dir,
            note=f"slide_spec.json not found at {slide_spec_path} — "
                 f"nothing to review.",
        )
        if not quiet:
            print(f"  visual-qa: skipped — no slide_spec.json at "
                  f"{slide_spec_path}", file=sys.stderr)
        return 0

    try:
        spec = json.loads(slide_spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        write_stub_reports(
            out_json, out_md, draft_dir,
            note=f"slide_spec.json unreadable ({exc}) — visual QA skipped.",
        )
        if not quiet:
            print(f"  visual-qa: skipped — slide_spec unreadable ({exc})",
                  file=sys.stderr)
        return 0

    # --- 3. Render .pptx ---
    pptx_path = audit_dir / "visual_qa_render.pptx"
    if reuse_pptx and (draft_dir / "deliverable" / "draft.pptx").is_file():
        # Operator opt-in: reuse the final-render pptx rather than
        # re-assembling. Saves a few seconds; only safe when the spec
        # hasn't changed since the deliverable was assembled.
        existing = draft_dir / "deliverable" / "draft.pptx"
        shutil.copyfile(existing, pptx_path)
        n_slides = len(spec.get("slides", []) or [])
        warnings: list[str] = []
    else:
        try:
            n_slides, warnings = assemble_pptx_for_qa(slide_spec_path, pptx_path)
        except Exception as exc:  # noqa: BLE001
            write_stub_reports(
                out_json, out_md, draft_dir,
                note=f"assemble_pptx failed ({exc}); visual QA skipped.",
            )
            if not quiet:
                print(f"  visual-qa: skipped — assemble failed ({exc})",
                      file=sys.stderr)
            return 0

    # --- 4. .pptx → .pdf ---
    try:
        pdf_path = pptx_to_pdf(pptx_path, audit_dir, soffice_bin=status.soffice)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            RuntimeError) as exc:
        write_stub_reports(
            out_json, out_md, draft_dir,
            note=f"soffice pptx→pdf conversion failed ({exc}); "
                 f"visual QA skipped.",
        )
        if not quiet:
            print(f"  visual-qa: skipped — soffice failed ({exc})",
                  file=sys.stderr)
        return 0

    # --- 5. .pdf → PNGs ---
    try:
        png_paths = pdf_to_pngs(pdf_path, pngs_dir, pdftoppm_bin=status.pdftoppm)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        write_stub_reports(
            out_json, out_md, draft_dir,
            note=f"pdftoppm pdf→png conversion failed ({exc}); "
                 f"visual QA skipped.",
        )
        if not quiet:
            print(f"  visual-qa: skipped — pdftoppm failed ({exc})",
                  file=sys.stderr)
        return 0

    if not png_paths:
        write_stub_reports(
            out_json, out_md, draft_dir,
            note=f"pdftoppm produced no PNGs from {pdf_path.name}; "
                 f"visual QA skipped.",
        )
        if not quiet:
            print(f"  visual-qa: skipped — no PNGs produced",
                  file=sys.stderr)
        return 0

    # --- 6. Vision pass ---
    mapping = build_slide_png_mapping(spec, png_paths)
    diag = invoke_vision_pass(
        draft_dir=draft_dir,
        slide_spec_path=slide_spec_path,
        slide_png_mapping=mapping,
        out_json_path=out_json,
        out_md_path=out_md,
        claude_bin=status.claude,
        model=model,
    )

    if diag["exit_status"] != 0 or not diag["output_present"]:
        # The vision pass failed but we have PNGs + a partial state —
        # write a stub explaining the LLM failure but preserve the
        # rendered artifacts under audit/visual_qa_pngs/ for manual
        # review.
        note = (
            f"claude -p vision pass failed (rc={diag['exit_status']}, "
            f"output_present={diag['output_present']}); PNGs preserved "
            f"in {pngs_dir} for manual review. "
            f"stderr tail: {diag['stderr_tail'][:200]}"
        )
        write_stub_reports(out_json, out_md, draft_dir, note=note)
        if not quiet:
            print(f"  visual-qa: vision pass failed (rc={diag['exit_status']});"
                  f" PNGs at {pngs_dir}", file=sys.stderr)
        return 0

    # --- 7. Cleanup ---
    if not keep_pngs:
        for p in png_paths:
            try:
                p.unlink()
            except OSError:
                pass
        try:
            pngs_dir.rmdir()
        except OSError:
            pass   # non-empty (kept-pngs / extra files) — leave it
    # Drop intermediate pptx + pdf — the deliverable's pptx is the
    # canonical render artifact; visual_qa's renders are throwaway.
    for p in (pptx_path, pdf_path):
        try:
            p.unlink()
        except OSError:
            pass

    if not quiet:
        # Read back the findings count for the stderr summary
        try:
            payload = json.loads(out_json.read_text())
            n = len(payload.get("findings", []))
            n_reviewed = payload.get("n_slides_reviewed", len(mapping))
            if n == 0:
                print(f"  visual-qa: no findings across {n_reviewed} slide(s) "
                      f"(${diag['cost_usd']:.4f})", file=sys.stderr)
            else:
                print(f"  visual-qa: {n} finding(s) across {n_reviewed} "
                      f"slide(s) — see {out_md} (${diag['cost_usd']:.4f})",
                      file=sys.stderr)
        except (json.JSONDecodeError, OSError):
            print(f"  visual-qa: completed (rc=0); see {out_md}",
                  file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Opt-in visual-QA pass for an assembled deck (advisory).",
    )
    p.add_argument("draft_dir", help="v0.3.1+ draft directory (talks/draft_N/).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the stderr summary line.")
    p.add_argument("--keep-pngs", action="store_true",
                   help="Keep audit/visual_qa_pngs/ after the pass for "
                        "manual review (default: cleaned up).")
    p.add_argument("--reuse-pptx", action="store_true",
                   help="Reuse deliverable/draft.pptx if present instead of "
                        "re-assembling. Safe when the spec hasn't changed.")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Claude model for the vision pass (default: "
                        f"{DEFAULT_MODEL}).")
    p.add_argument("--claude-bin", default="claude",
                   help="Path to the claude CLI (default: claude on PATH).")
    args = p.parse_args(argv)

    draft = Path(args.draft_dir)
    return run_visual_qa(
        draft,
        quiet=args.quiet,
        keep_pngs=args.keep_pngs,
        reuse_pptx=args.reuse_pptx,
        claude_bin=args.claude_bin,
        model=args.model,
    )


if __name__ == "__main__":
    sys.exit(main())
