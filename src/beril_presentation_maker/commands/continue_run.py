"""`beril-presentation-maker continue <draft_dir> --resume-from <stage>` — resume a paused draft.

Thin Python wrapper around `presentation_maker.sh --resume-from <stage>
--draft-dir <path>`. Re-runs from a named stage onward, reusing the
on-disk artifacts of earlier stages.

Stages (in order): plan | throughline | substory_design |
curate_figures | citation_pool | cross_tenant | intro | slide_compose |
qa_prep | speaker_notes | merge

Cost savings on prompt-iteration:
  from intro:         ~$1.50 (saves plan+throughline+substory)
  from slide_compose: ~$1.20 (saves plan+throughline+substory+intro)
  from merge:         FREE (no LLM; assembly only)

Unlike beril-paper-writer, presentation-maker does not yet have a paused
throughline-pick state. The `continue` command exists for re-running
from a named stage on prompt iteration / failure recovery.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib import resources
from pathlib import Path


_VALID_STAGES = (
    "plan",
    "throughline",
    "substory_design",
    "curate_figures",
    "citation_pool",
    "cross_tenant",
    "intro",
    "slide_compose",
    "qa_prep",
    "speaker_notes",
    "image_gen",          # v0.3.3
    "merge",
    "adversarial_review",
    "revise_slides",
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "continue",
        help="Resume a draft from a named stage.",
        description=(
            "Re-run the orchestrator starting from --resume-from <stage>, "
            "reusing the existing draft_dir's earlier-stage artifacts. "
            "Useful for prompt-iteration on a single stage or recovery "
            "after a mid-pipeline failure."
        ),
    )
    p.add_argument(
        "draft_dir",
        help="Path to the existing draft_N directory to resume into.",
    )
    p.add_argument(
        "--resume-from",
        required=True,
        choices=_VALID_STAGES,
        help="Stage to resume from. Earlier-stage artifacts are reused.",
    )
    p.add_argument(
        "--beril-root",
        default=None,
        help=(
            "Override BERIL_ROOT. If unset, auto-derived from "
            "<draft_dir>/../../../.. (the path layout is "
            "BERIL_ROOT/projects/<id>/talks/draft_N), since the "
            "orchestrator requires this even when resuming."
        ),
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=["talk-30", "talk-15", "talk-45", "lightning-5",
                 "poster-h", "poster-v"],
        help="Presentation mode (must match the draft's original mode).",
    )
    p.add_argument(
        "--tier",
        default=None,
        choices=["STRONG", "THIN", "EXPLORATORY"],
    )
    p.add_argument(
        "--auto-advance",
        action="store_true",
    )
    p.add_argument(
        "--skip-assembly",
        action="store_true",
    )
    p.add_argument(
        "--model",
        default=None,
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
    )
    # v0.3.0 review-rewrite loop flags
    p.add_argument("--no-adversarial", action="store_true")
    p.add_argument("--max-revise-cost-usd", default=None)
    p.add_argument("--max-revisions", default=None)
    # v0.3.3 image-gen flags
    p.add_argument("--no-images", action="store_true")
    p.add_argument("--auto-approve-images", action="store_true")
    p.add_argument("--image-allow-exploratory", action="store_true")
    p.add_argument("--max-image-cost-usd", default=None)
    p.add_argument("--image-style", default=None)
    p.set_defaults(func=run)
    return p


def _locate_orchestrator() -> Path:
    try:
        ref = resources.files("beril_presentation_maker").joinpath(
            "skill", "tools", "presentation_maker.sh"
        )
        with resources.as_file(ref) as p:
            return Path(p)
    except (ModuleNotFoundError, FileNotFoundError) as e:
        raise FileNotFoundError(
            "presentation_maker.sh not found in package data. "
            "Reinstall beril-presentation-maker-skill."
        ) from e


def run(args: argparse.Namespace) -> int:
    draft_dir = Path(args.draft_dir).expanduser().resolve()
    if not draft_dir.is_dir():
        print(f"error: draft_dir does not exist: {draft_dir}", file=sys.stderr)
        return 1

    try:
        sh_path = _locate_orchestrator()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # The orchestrator requires a project_id positional arg even when
    # --resume-from + --draft-dir are set; it derives the project from
    # the draft_dir's parent path. We pass a placeholder; the orchestrator
    # ignores it when resuming.
    project_id_placeholder = draft_dir.parent.parent.name

    # The orchestrator also requires --beril-root unconditionally (even
    # in resume mode, since it validates BERIL_ROOT/projects/<id>/ exists
    # before any stage runs). Derive from the draft_dir layout if the
    # user didn't override: draft_N → talks → project → projects → BERIL_ROOT.
    if args.beril_root:
        beril_root = Path(args.beril_root).expanduser().resolve()
    else:
        beril_root = draft_dir.parents[3]

    argv = [
        "bash", str(sh_path),
        project_id_placeholder,
        "--beril-root", str(beril_root),
        "--resume-from", args.resume_from,
        "--draft-dir", str(draft_dir),
    ]
    if args.mode:
        argv += ["--mode", args.mode]
    if args.tier:
        argv += ["--tier", args.tier]
    if args.auto_advance:
        argv += ["--auto-advance"]
    if args.skip_assembly:
        argv += ["--skip-assembly"]
    if args.model:
        argv += ["--model", args.model]
    if args.no_stream:
        argv += ["--no-stream"]
    # v0.3.0 review-rewrite loop flags
    if args.no_adversarial:
        argv += ["--no-adversarial"]
    if args.max_revise_cost_usd is not None:
        argv += ["--max-revise-cost-usd", str(args.max_revise_cost_usd)]
    if args.max_revisions is not None:
        argv += ["--max-revisions", str(args.max_revisions)]
    # v0.3.3 image-gen flags
    if args.no_images:
        argv += ["--no-images"]
    if args.auto_approve_images:
        argv += ["--auto-approve-images"]
    if args.image_allow_exploratory:
        argv += ["--image-allow-exploratory"]
    if args.max_image_cost_usd is not None:
        argv += ["--max-image-cost-usd", str(args.max_image_cost_usd)]
    if args.image_style:
        argv += ["--image-style", args.image_style]

    print(f"▸ Running: {' '.join(argv)}", file=sys.stderr)
    print("", file=sys.stderr)
    return subprocess.run(argv).returncode
