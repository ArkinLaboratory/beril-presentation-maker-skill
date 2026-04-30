#!/usr/bin/env python3
"""image_gen_calibration.py — live test harness for AI image generation.

A standalone CLI that exercises image_client.py against CBORG and produces
calibration evidence for the v0.3.x image-gen pipeline. Not a production
stage; this is a one-off (or per-model-change) calibration utility.

What it does:

  - T0  smoke           One image, basic prompt. Confirms CBORG endpoint
                        + API key + response shape work end-to-end.
  - T1  brand_color     Two images of the same subject, one with hex-
                        explicit palette, one with descriptive ("KBase
                        brand colors"). Compare which renders cleaner.
  - T2  style_baseline  Four images of the same subject, in 4 styles
                        (scientific_illustration, watercolor, minimalist,
                        abstract). Choose the style that fits KBase
                        aesthetic.
  - T3  text_handling   Two images, one with specified text, one with
                        "no text" prohibition. Confirms the model honors
                        both modes (per nanobanana-pro / OpenAI text
                        capabilities).
  - T4  slide2          4-6 images for draft_10 slide 2 ("One in four
                        bacterial genes lacks functional annotation"),
                        per Adam's two design ideas: literal "dark matter"
                        + metaphorical "bringing dark into the light".

Outputs:

    <out_dir>/
      report.md                Comparison report; what was tested, costs.
      T0_smoke/img.png
      T1_brand_color/
        a_hex.png
        b_descriptive.png
      T2_style_baseline/
        scientific_illustration.png
        watercolor.png
        minimalist.png
        abstract.png
      T3_text_handling/
        with_text.png
        no_text.png
      T4_slide2/
        a_dark_matter_v1.png
        a_dark_matter_v2.png
        b_dark_to_light_v1.png
        b_dark_to_light_v2.png
      provenance.json          Per-image cost + model + elapsed time.

Cost cap: --max-cost-usd 20.00 default. The harness counts cumulative
worst-case before each call; if a call would exceed, halts cleanly.

Usage:

    image_gen_calibration.py [--out-dir DIR] [--api-key KEY]
                             [--model MODEL] [--max-cost-usd N]
                             [smoke | calibrate | slide2 | all]

Examples:

    # Quickest: smoke test only, ~$1
    image_gen_calibration.py smoke

    # Full calibration (T0-T4), ~$13-15
    image_gen_calibration.py all

    # Just slide 2 design candidates (~$4-6)
    image_gen_calibration.py slide2

API key resolution:

    1. --api-key flag (highest priority)
    2. $CBORG_API_KEY env var
    3. <BERIL_ROOT>/.env CBORG_API_KEY=... (parsed; never echoed)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Load image_client as a sibling module
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent


def _load_image_client():
    spec = importlib.util.spec_from_file_location(
        "image_client", _THIS_DIR / "image_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["image_client"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Test definitions (data-driven)
# ---------------------------------------------------------------------------

@dataclass
class Trial:
    """One image generation trial — what to render, where to save."""
    test_id: str             # e.g., "T1_brand_color"
    variant: str             # e.g., "a_hex"
    prompt: str
    rationale: str           # one-line explanation of what we're testing
    out_subdir: str          # relative to out_dir
    filename: str            # e.g., "a_hex.png"
    expect: str              # what a "passing" image looks like, plain English


# T0 — smoke. Single basic prompt; confirm CBORG works.
T0_TRIALS = [
    Trial(
        test_id="T0_smoke",
        variant="basic",
        prompt=(
            "A single bacterial cell, simple scientific illustration, "
            "clean lines, white background. Do not include any text, "
            "labels, or annotations."
        ),
        rationale="Smoke test — confirms CBORG endpoint + API key + response shape work.",
        out_subdir="T0_smoke",
        filename="img.png",
        expect="A recognizable bacterial cell, no text overlays, clean white background.",
    ),
]


# T1 — brand color: hex-explicit vs descriptive
_T1_PROMPT_BASE = (
    "Three abstract circular cells side by side on a white background, "
    "rendered as a flat illustration with no shading and no shadows. "
    "Each cell is a different color from {palette}. "
    "Do not include any text, labels, or annotations."
)
T1_TRIALS = [
    Trial(
        test_id="T1_brand_color",
        variant="a_hex",
        prompt=_T1_PROMPT_BASE.format(
            palette="this exact palette: #007DC3 (blue), #5E9732 (green), #F78E1E (orange)"
        ),
        rationale="Hex-explicit palette specification.",
        out_subdir="T1_brand_color",
        filename="a_hex.png",
        expect="Three circles in roughly the named hex colors.",
    ),
    Trial(
        test_id="T1_brand_color",
        variant="b_descriptive",
        prompt=_T1_PROMPT_BASE.format(
            palette="the KBase brand palette of freshwater blue, grass green, and microbe orange"
        ),
        rationale="Descriptive palette specification (color names only).",
        out_subdir="T1_brand_color",
        filename="b_descriptive.png",
        expect="Three circles in colors approximately matching the named tones.",
    ),
]


# T2 — style baseline. Same subject, 4 styles.
_T2_SUBJECT = (
    "A diagram representing functional dark matter in a bacterial genome — "
    "an arc of small abstract gene shapes, with about a quarter of them "
    "obscured or shaded gray to represent unknown function, the rest in "
    "color to represent known function. Clean composition. White or very "
    "light background. Do not include any text, labels, or annotations."
)
T2_TRIALS = [
    Trial(
        test_id="T2_style_baseline",
        variant="scientific_illustration",
        prompt=(
            f"{_T2_SUBJECT} "
            f"Style: clean scientific illustration in the style of a textbook "
            f"figure or Nature publication graphical abstract. Flat colors, "
            f"thin black outlines, professional academic aesthetic."
        ),
        rationale="Scientific-illustration style baseline.",
        out_subdir="T2_style_baseline",
        filename="scientific_illustration.png",
        expect="Textbook-figure aesthetic; readable at presentation distance.",
    ),
    Trial(
        test_id="T2_style_baseline",
        variant="watercolor",
        prompt=(
            f"{_T2_SUBJECT} "
            f"Style: soft watercolor with visible brushstrokes. Muted earth "
            f"tones with selective color. Slightly textured background."
        ),
        rationale="Watercolor style — softer, more evocative.",
        out_subdir="T2_style_baseline",
        filename="watercolor.png",
        expect="Watercolor texture visible; muted palette; evocative not literal.",
    ),
    Trial(
        test_id="T2_style_baseline",
        variant="minimalist",
        prompt=(
            f"{_T2_SUBJECT} "
            f"Style: minimalist flat design. Very simple geometric shapes, "
            f"limited color palette (3-4 colors max), generous whitespace, "
            f"strong negative space."
        ),
        rationale="Minimalist style — slide-friendly clean look.",
        out_subdir="T2_style_baseline",
        filename="minimalist.png",
        expect="Reduced complexity; presentation-friendly visual hierarchy.",
    ),
    Trial(
        test_id="T2_style_baseline",
        variant="abstract",
        prompt=(
            f"{_T2_SUBJECT} "
            f"Style: abstract data-art aesthetic. Geometric forms suggesting "
            f"information density. Color gradients. Modern, contemporary feel "
            f"like an infographic or magazine illustration."
        ),
        rationale="Abstract style — modern infographic feel.",
        out_subdir="T2_style_baseline",
        filename="abstract.png",
        expect="Less literal; more graphic-design feel; presentation-floor appropriate.",
    ),
]


# T3 — text handling. With-text + no-text.
T3_TRIALS = [
    Trial(
        test_id="T3_text_handling",
        variant="with_text",
        prompt=(
            "A bacterial cell on the left labeled \"Known\" and a darker, "
            "shadowed cell on the right labeled \"Unknown\". The label "
            "\"Known\" appears in clean sans-serif font directly below "
            "the left cell. The label \"Unknown\" appears in clean sans-"
            "serif font directly below the right cell. Do not include any "
            "other text, captions, titles, or annotations anywhere in the "
            "image. Plain white background. Scientific illustration style."
        ),
        rationale="Confirms model honors specified text exactly + suppresses other text.",
        out_subdir="T3_text_handling",
        filename="with_text.png",
        expect="Both cells labeled with the exact text 'Known' and 'Unknown'; no garbled extra text.",
    ),
    Trial(
        test_id="T3_text_handling",
        variant="no_text",
        prompt=(
            "A bacterial cell on the left, lit and visible. A darker, "
            "shadowed cell on the right, partially obscured. Plain white "
            "background. Scientific illustration style. Do not include any "
            "text, labels, captions, titles, words, or letters anywhere in "
            "the image."
        ),
        rationale="Confirms model honors blanket text prohibition.",
        out_subdir="T3_text_handling",
        filename="no_text.png",
        expect="Two cells; ZERO text or label artifacts.",
    ),
]


# T4 — slide 2 design candidates. Adam's two design ideas.
T4_TRIALS = [
    # Idea A: Dark matter representation
    Trial(
        test_id="T4_slide2",
        variant="a_dark_matter_v1",
        prompt=(
            "A scientific illustration of a circular bacterial genome ring, "
            "viewed from above. About a quarter of the genome (~25 percent) "
            "is rendered as dark gray empty regions, and the remaining "
            "~75 percent is filled with vibrant color showing annotated "
            "genes. The contrast between dark and colored regions is the "
            "visual focus. Subtle radial gradient suggests cosmic dark "
            "matter analogy. Modern, clean style suitable for a scientific "
            "talk opener. White background. Do not include any text, "
            "labels, or annotations."
        ),
        rationale="Idea A v1 — literal dark/light genome regions, cosmic analogy.",
        out_subdir="T4_slide2",
        filename="a_dark_matter_v1.png",
        expect="Genome ring visualization; dark regions ~25 percent, colored ~75 percent; opener-quality.",
    ),
    Trial(
        test_id="T4_slide2",
        variant="a_dark_matter_v2",
        prompt=(
            "An abstract conceptual illustration: a field of small "
            "bacterial-cell-shaped icons arranged in a grid, where about "
            "one in four cells is rendered as a featureless dark silhouette "
            "and the remaining cells are colorful and detailed. The dark "
            "cells are clustered in some areas, scattered in others, "
            "suggesting the unknown distribution of dark genes across "
            "biology. White background, modern editorial style. Do not "
            "include any text, labels, or annotations."
        ),
        rationale="Idea A v2 — population-level dark vs annotated cells.",
        out_subdir="T4_slide2",
        filename="a_dark_matter_v2.png",
        expect="Grid of cells; ~1-in-4 are dark silhouettes; remaining are colorful/detailed.",
    ),
    # Idea B: Bringing dark into the light (process/flow)
    Trial(
        test_id="T4_slide2",
        variant="b_dark_to_light_v1",
        prompt=(
            "A horizontal flow visualization: on the left, a cluster of "
            "completely dark, featureless bacterial-cell silhouettes. "
            "Moving rightward, beams of soft light progressively illuminate "
            "the cells, revealing internal structure and color. On the far "
            "right, the cells are fully illuminated and detailed. The "
            "transition from dark to illuminated is the visual focus. "
            "Clean editorial illustration style, white background. Do not "
            "include any text, labels, or annotations."
        ),
        rationale="Idea B v1 — left-to-right transition from dark to illuminated cells.",
        out_subdir="T4_slide2",
        filename="b_dark_to_light_v1.png",
        expect="Clear left-to-right narrative; dark cells progressively illuminated.",
    ),
    Trial(
        test_id="T4_slide2",
        variant="b_dark_to_light_v2",
        prompt=(
            "A scientific illustration: in the center, a dark, featureless "
            "bacterial cell. Three converging beams of color enter the "
            "cell from different angles — one beam orange, one blue, one "
            "green — each beam representing a stream of evidence. Where "
            "the beams meet inside the cell, the cell's internal structure "
            "becomes visible and colorful. Modern, clean style. White "
            "background. Do not include any text, labels, or annotations."
        ),
        rationale="Idea B v2 — three evidence streams converging to illuminate one cell.",
        out_subdir="T4_slide2",
        filename="b_dark_to_light_v2.png",
        expect="One central cell; three converging colored beams; cell illuminated where beams meet.",
    ),
]


# ---------------------------------------------------------------------------
# Calibration runner
# ---------------------------------------------------------------------------

@dataclass
class TrialResult:
    trial: Trial
    success: bool
    out_path: Optional[Path] = None
    cost_usd: float = 0.0
    elapsed_s: float = 0.0
    error: Optional[str] = None


@dataclass
class CalibrationRun:
    out_dir: Path
    started_at: str = ""
    finished_at: str = ""
    cumulative_cost_usd: float = 0.0
    results: list[TrialResult] = field(default_factory=list)
    halted_reason: Optional[str] = None


def _resolve_api_key(explicit: Optional[str], beril_root: Optional[Path]) -> Optional[str]:
    """API key from --api-key, env, or beril_root/.env (in order)."""
    if explicit:
        return explicit
    env_key = os.environ.get("CBORG_API_KEY")
    if env_key:
        return env_key
    if beril_root:
        env_file = beril_root / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("CBORG_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
            except OSError:
                pass
    return None


def _run_trial(trial: Trial,
               client,
               out_dir: Path,
               run: CalibrationRun,
               max_cost_usd: float,
               *,
               channel: str = "A") -> TrialResult:
    """Run a single trial. Updates the run's cumulative cost."""
    image_client = sys.modules["image_client"]
    sub = out_dir / trial.out_subdir
    sub.mkdir(parents=True, exist_ok=True)
    out_path = sub / trial.filename

    # Pre-flight cost cap
    worst_cost = client.estimate_cost_usd(
        client.model, input_tokens=10_000, output_tokens=32_000)
    if run.cumulative_cost_usd + worst_cost > max_cost_usd:
        msg = (f"trial {trial.test_id}/{trial.variant}: would exceed "
               f"--max-cost-usd ${max_cost_usd:.2f} "
               f"(cumulative ${run.cumulative_cost_usd:.2f} + worst-case "
               f"${worst_cost:.2f}); halting")
        print(f"  HALT: {msg}", file=sys.stderr)
        return TrialResult(trial=trial, success=False, error=msg)

    print(f"  {trial.test_id} :: {trial.variant} → {out_path}", file=sys.stderr)
    print(f"    rationale: {trial.rationale}", file=sys.stderr)
    start = time.time()
    try:
        result = client.generate(
            prompt=trial.prompt,
            budget_remaining_usd=max_cost_usd - run.cumulative_cost_usd,
            channel=channel,
        )
    except image_client.BudgetExceeded as e:
        err = f"BudgetExceeded: {e}"
        print(f"    FAIL: {err}", file=sys.stderr)
        return TrialResult(trial=trial, success=False, error=err)
    except image_client.ImageClientError as e:
        err = f"ImageClientError: {e}"
        print(f"    FAIL: {err}", file=sys.stderr)
        return TrialResult(trial=trial, success=False, error=err)
    except Exception as e:  # noqa: BLE001
        err = f"unexpected: {type(e).__name__}: {e}"
        print(f"    FAIL: {err}", file=sys.stderr)
        return TrialResult(trial=trial, success=False, error=err)
    elapsed = time.time() - start

    out_path.write_bytes(result.image_bytes)
    run.cumulative_cost_usd += result.cost_usd
    print(f"    ok: {len(result.image_bytes):,} bytes; "
          f"~${result.cost_usd:.3f}; {elapsed:.1f}s; "
          f"cumulative ${run.cumulative_cost_usd:.3f}",
          file=sys.stderr)
    return TrialResult(
        trial=trial, success=True, out_path=out_path,
        cost_usd=result.cost_usd, elapsed_s=elapsed,
    )


def _render_report(run: CalibrationRun) -> str:
    """Markdown report summarizing the calibration run."""
    lines = []
    lines.append("# Image-gen calibration report")
    lines.append("")
    lines.append(f"**Started:** {run.started_at}")
    lines.append(f"**Finished:** {run.finished_at}")
    lines.append(f"**Cumulative cost:** ~${run.cumulative_cost_usd:.3f}")
    lines.append(f"**Trials run:** {len(run.results)} "
                 f"({sum(1 for r in run.results if r.success)} ok, "
                 f"{sum(1 for r in run.results if not r.success)} fail)")
    if run.halted_reason:
        lines.append(f"**Halted early:** {run.halted_reason}")
    lines.append("")

    # Group by test_id
    by_test = {}
    for r in run.results:
        by_test.setdefault(r.trial.test_id, []).append(r)

    for test_id in sorted(by_test):
        results = by_test[test_id]
        lines.append(f"## {test_id}")
        lines.append("")
        for r in results:
            t = r.trial
            lines.append(f"### {t.variant}")
            lines.append("")
            lines.append(f"**Rationale:** {t.rationale}")
            lines.append("")
            lines.append(f"**Expected:** {t.expect}")
            lines.append("")
            if r.success and r.out_path is not None:
                # Relative path for portability of the report.md
                rel = r.out_path.relative_to(run.out_dir)
                lines.append(f"**Image:** `{rel}` "
                             f"(~${r.cost_usd:.3f}, {r.elapsed_s:.1f}s)")
                lines.append("")
                lines.append(f"![{t.variant}]({rel})")
            else:
                lines.append(f"**FAILED:** {r.error}")
            lines.append("")
            lines.append("**Prompt used:**")
            lines.append("")
            lines.append("```")
            lines.append(t.prompt)
            lines.append("```")
            lines.append("")

    # Decision rubric
    lines.append("## Decision rubric (after viewing all images)")
    lines.append("")
    lines.append("- **T0 smoke** — pass if CBORG returned a usable image. Fail = "
                 "investigate auth / endpoint / model availability.")
    lines.append("- **T1 brand_color** — compare a_hex.png vs b_descriptive.png. "
                 "Pick the rendering that matches KBase brand most precisely. The "
                 "winning approach goes into `ai_image_prompt.v1.md`'s color "
                 "section.")
    lines.append("- **T2 style_baseline** — pick the style that fits KBase aesthetic "
                 "and projection-distance readability. The winning style becomes "
                 "the default for `concept_illustration` slides; other styles "
                 "remain available via explicit `image_brief.style` override.")
    lines.append("- **T3 text_handling** — both should pass. If `with_text.png` "
                 "fails (garbled text or extra text), the model can't be trusted "
                 "with text and we revert to no-text default. If `no_text.png` "
                 "has stray text, we add stronger anti-prompts.")
    lines.append("- **T4 slide2** — pick which idea (a or b) and which variant "
                 "best fits draft_10 slide 2. The winning brief becomes the "
                 "first production image.")
    lines.append("")

    return "\n".join(lines) + "\n"


def run_calibration(out_dir: Path,
                    api_key: str,
                    *,
                    model: str,
                    suite: str,
                    max_cost_usd: float) -> CalibrationRun:
    """Run the requested suite of trials. Writes images + report.md."""
    image_client = _load_image_client()
    client = image_client.ImageClient.cborg(api_key=api_key, model=model)
    out_dir.mkdir(parents=True, exist_ok=True)

    suites = {
        "smoke": T0_TRIALS,
        "calibrate": T0_TRIALS + T1_TRIALS + T2_TRIALS + T3_TRIALS,
        "slide2": T4_TRIALS,
        "all": T0_TRIALS + T1_TRIALS + T2_TRIALS + T3_TRIALS + T4_TRIALS,
    }
    if suite not in suites:
        raise ValueError(f"unknown suite {suite!r}; valid: {list(suites.keys())}")
    trials = suites[suite]

    run = CalibrationRun(
        out_dir=out_dir,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    print(f"calibration: {len(trials)} trial(s); model={model}; "
          f"max_cost=${max_cost_usd:.2f}; out={out_dir}", file=sys.stderr)

    for trial in trials:
        result = _run_trial(trial, client, out_dir, run, max_cost_usd)
        run.results.append(result)
        if (not result.success and result.error
                and "would exceed" in result.error):
            run.halted_reason = result.error
            break
        # Append provenance live (so partial state persists if we interrupt)
        if result.success and result.out_path:
            prov_path = out_dir / "provenance.json"
            try:
                existing = (json.loads(prov_path.read_text(encoding="utf-8"))
                            if prov_path.is_file() else
                            {"version": "1.0", "entries": []})
            except json.JSONDecodeError:
                existing = {"version": "1.0", "entries": []}
            existing["entries"].append({
                "test_id": result.trial.test_id,
                "variant": result.trial.variant,
                "image_path": str(result.out_path.relative_to(out_dir)),
                "model": model,
                "cost_usd": round(result.cost_usd, 4),
                "elapsed_s": round(result.elapsed_s, 2),
            })
            prov_path.write_text(json.dumps(existing, indent=2) + "\n",
                                 encoding="utf-8")

    run.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out_dir / "report.md").write_text(_render_report(run), encoding="utf-8")
    return run


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="image_gen_calibration.py",
        description="Live test harness for AI image generation.",
    )
    p.add_argument("suite", nargs="?", default="all",
                   choices=["smoke", "calibrate", "slide2", "all"],
                   help="Which trial suite to run (default: all)")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Output directory (default: image_gen_calibration_<timestamp>/)")
    p.add_argument("--api-key", default=None,
                   help="Override CBORG_API_KEY env var")
    p.add_argument("--beril-root", type=Path, default=None,
                   help="Path to BERIL root (used to read .env if --api-key absent)")
    p.add_argument("--model", default=None,
                   help="Override default model (DEFAULT_MODEL from image_client.py)")
    p.add_argument("--max-cost-usd", type=float, default=20.00,
                   help="Cumulative cost cap; halts cleanly if exceeded (default: $20)")
    args = p.parse_args(argv)

    if args.out_dir is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out_dir = Path(f"image_gen_calibration_{ts}").resolve()

    api_key = _resolve_api_key(args.api_key, args.beril_root)
    if not api_key:
        print("error: no CBORG_API_KEY found "
              "(--api-key, env, or <beril-root>/.env)", file=sys.stderr)
        return 3

    image_client = _load_image_client()
    model = args.model or image_client.DEFAULT_MODEL

    try:
        run = run_calibration(
            args.out_dir, api_key,
            model=model, suite=args.suite,
            max_cost_usd=args.max_cost_usd,
        )
    except KeyboardInterrupt:
        print("interrupted; partial outputs preserved", file=sys.stderr)
        return 130

    n_ok = sum(1 for r in run.results if r.success)
    n_fail = sum(1 for r in run.results if not r.success)
    print(f"\n--- summary ---", file=sys.stderr)
    print(f"  trials: {n_ok} ok, {n_fail} fail", file=sys.stderr)
    print(f"  cost:   ~${run.cumulative_cost_usd:.3f}", file=sys.stderr)
    print(f"  report: {args.out_dir}/report.md", file=sys.stderr)
    if run.halted_reason:
        print(f"  HALTED: {run.halted_reason}", file=sys.stderr)
        return 4
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
