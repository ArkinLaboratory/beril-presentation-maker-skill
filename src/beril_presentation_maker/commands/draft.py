"""`beril-presentation-maker draft <project>` — start a fresh presentation draft.

Thin Python wrapper around `tools/presentation_maker.sh`. The shell script
is the canonical orchestrator for the 14-stage drafting pipeline (plan →
throughline → substory_design → curate_figures → citation_pool →
cross_tenant → intro → slide_compose → qa_prep → speaker_notes →
merge_and_assemble). This command:

  1. Resolves the project argument (path or project_id under projects/)
  2. Locates presentation_maker.sh from the package's bundled skill data
     (importlib.resources)
  3. Forwards CLI flags to the shell
  4. Runs the shell in the foreground, streams its output, returns the
     exit code

Unlike beril-paper-writer's draft, this does NOT have a paused
throughline-pick handoff. Presentation-maker's interactive gates are
handled inside the orchestrator (--auto-advance to skip them); paper-
writer's two-phase pattern is not yet implemented here.

See SPEC.md for the drafting flow and LAYOUT.md for the user-facing
CLI shape.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib import resources
from pathlib import Path

from beril_presentation_maker import __version__, discovery


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "draft",
        help="Start a fresh presentation draft for a BERDL project.",
        description=(
            "Initialize a new draft directory under "
            "<project>/talks/draft_N/ and run the full 11-stage drafting "
            "pipeline (plan → throughline → substory_design → "
            "curate_figures → citation_pool → cross_tenant → intro → "
            "slide_compose → qa_prep → speaker_notes → "
            "merge_and_assemble). Stops at the merge_and_assemble pause "
            "or runs through to .pptx if --auto-advance is set."
        ),
    )
    p.add_argument(
        "project",
        help=(
            "Project path or project_id. If a directory: used directly. "
            "Otherwise interpreted as a project_id under "
            "<BERIL_ROOT>/projects/<id>/."
        ),
    )
    p.add_argument(
        "--beril-root",
        default=None,
        help="Override BERIL_ROOT auto-detection.",
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=["talk-30", "talk-15", "talk-45", "lightning-5",
                 "poster-h", "poster-v"],
        help="Presentation mode (default: talk-30).",
    )
    p.add_argument(
        "--tier",
        default=None,
        choices=["STRONG", "THIN", "EXPLORATORY"],
        help="Evidence tier (default: STRONG).",
    )
    p.add_argument(
        "--audience",
        default=None,
        help="Audience descriptor (default: peer; only peer supported in v0.2).",
    )
    p.add_argument(
        "--auto-advance",
        action="store_true",
        help=(
            "Skip interactive gates: pick TL1 throughline, escalate-mode "
            "on overflow. For unattended runs against known-shape projects."
        ),
    )
    p.add_argument(
        "--skip-assembly",
        action="store_true",
        help="Stop after fragment merge; do not run assemble_pptx.py.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override default Claude model.",
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable stream-json parser pipe (loses cost summary + Write verification).",
    )
    # v0.3.0 adversarial review-rewrite loop flags
    p.add_argument(
        "--no-adversarial",
        action="store_true",
        help="Skip adversarial review + revise-loop stages (v0.3.0+).",
    )
    p.add_argument(
        "--max-revise-cost-usd",
        default=None,
        help="Cost cap for the revise loop in USD (default: 5.00).",
    )
    p.add_argument(
        "--max-revisions",
        default=None,
        help="Max findings the revise loop will process per run (default: 6).",
    )
    # v0.3.3 image-gen flags
    p.add_argument(
        "--no-images",
        action="store_true",
        help="Skip the image_gen stage entirely (v0.3.3+).",
    )
    p.add_argument(
        "--auto-approve-images",
        action="store_true",
        help=(
            "Bypass per-slide image-approval gate for image_gen "
            "(CI / power users). Cost cap still enforced."
        ),
    )
    p.add_argument(
        "--image-allow-exploratory",
        action="store_true",
        help=(
            "Allow concept_illustration on EXPLORATORY tier "
            "(default: skipped per architecture R6)."
        ),
    )
    p.add_argument(
        "--max-image-cost-usd",
        default=None,
        help="Cumulative image-gen cap in USD (default: 0.50).",
    )
    p.add_argument(
        "--image-style",
        default=None,
        help="Force style override across all images this run.",
    )
    # v0.5.1 D-076 prompt-version + smoke-gate flags
    p.add_argument(
        "--prompts-version",
        default=None,
        choices=["v1", "v2", "v3", "v3.1", "v3.2", "v3.3"],
        help=(
            "Select the prompt-stack version for substory_design + "
            "slide_compose (v0.8.0 stack: v3.3 substory_design + "
            "v3.2 slide_compose; default v2)."
        ),
    )
    p.add_argument(
        "--force-v3-smoke-stale",
        action="store_true",
        help=(
            "Bypass the D-076 live-LLM smoke-pass gate. Use ONLY "
            "when you have just edited prompts and accept that "
            "the next run isn't smoke-verified."
        ),
    )
    # v0.4 architecture pipeline (opt-in)
    p.add_argument(
        "--architecture-pipeline",
        default=None,
        choices=["v0_3", "v0_4"],
        help=(
            "v0_3 (default; sequential per-substory) or v0_4 "
            "(architect-then-parallel-compose; opt-in)."
        ),
    )
    # Resume mechanism (existing draft, skip upstream stages)
    p.add_argument(
        "--resume-from",
        default=None,
        help=(
            "Resume an existing draft at a specific stage "
            "(plan|throughline|substory_design|phase0_tooling|"
            "deck_outline|curate_figures|citation_pool|cross_tenant|"
            "intro|slide_compose|qa_prep|deck_close|speaker_notes|"
            "image_gen|merge|adversarial_review|revise_slides). "
            "Requires --draft-dir."
        ),
    )
    p.add_argument(
        "--draft-dir",
        default=None,
        help=(
            "Existing draft_N directory to resume into. Required "
            "when --resume-from is set."
        ),
    )
    # v0.8 revise + visual-QA flags
    p.add_argument(
        "--revise-severity-floor",
        default=None,
        choices=["P0", "P1", "P2"],
        help=(
            "Lowest severity the revise loop will process "
            "(v0.8 default: P1). P0 = only blockers; P1 = "
            "blockers + significant gaps; P2 = also nits."
        ),
    )
    p.add_argument(
        "--visual-qa",
        action="store_true",
        help=(
            "Force-enable the visual-QA stage even when mode/tier "
            "wouldn't auto-on it (D-096)."
        ),
    )
    p.add_argument(
        "--no-visual-qa",
        action="store_true",
        help=(
            "Force-disable the visual-QA stage (overrides D-096 "
            "auto-on for talk-30 STRONG + talk-15 STRONG/BRIEF)."
        ),
    )
    # M5b image-provider override
    p.add_argument(
        "--image-provider",
        default=None,
        help=(
            "Force image-gen provider (cbiorg | google-ai-studio | "
            "auto). Default: auto-discovery per M5b/D-062."
        ),
    )
    p.add_argument(
        "--max-image-approvals",
        default=None,
        help=(
            "Cap on how many AI images may be approved per run "
            "(D-088; v0.8 default: 4)."
        ),
    )
    p.set_defaults(func=run)
    return p


def _locate_orchestrator() -> Path:
    """Locate presentation_maker.sh in the package data."""
    try:
        ref = resources.files("beril_presentation_maker").joinpath(
            "skill", "tools", "presentation_maker.sh"
        )
        with resources.as_file(ref) as p:
            return Path(p)
    except (ModuleNotFoundError, FileNotFoundError) as e:
        raise FileNotFoundError(
            "presentation_maker.sh not found in package data. "
            "Reinstall beril-presentation-maker-skill (pipx install --force ...)."
        ) from e


def run(args: argparse.Namespace) -> int:
    try:
        sh_path = _locate_orchestrator()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # v0.3.4.6: auto-detect BERIL_ROOT when --beril-root not passed.
    # The bash orchestrator requires it explicitly; relying on
    # subprocess inheriting $BERIL_ROOT works only if the user
    # `export`-ed it, which hub users routinely forget. Use the
    # discovery module's walk-up logic (matches paper-writer +
    # adversarial behavior).
    beril_root = args.beril_root
    if not beril_root:
        try:
            beril_root = str(discovery.find_beril_root())
        except discovery.BerilRootNotFound as e:
            print(f"Error: {e}", file=sys.stderr)
            print(
                "\nHint: cd into your BERIL checkout, OR pass "
                "--beril-root <path>, OR `export BERIL_ROOT=<path>` "
                "before invoking.",
                file=sys.stderr,
            )
            return 1

    argv = ["bash", str(sh_path), args.project, "--beril-root", beril_root]
    if args.mode:
        argv += ["--mode", args.mode]
    if args.tier:
        argv += ["--tier", args.tier]
    if args.audience:
        argv += ["--audience", args.audience]
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
    # v0.5.1 D-076 prompt-version + smoke-gate
    if args.prompts_version:
        argv += ["--prompts-version", args.prompts_version]
    if args.force_v3_smoke_stale:
        argv += ["--force-v3-smoke-stale"]
    # v0.4 architecture pipeline
    if args.architecture_pipeline:
        argv += ["--architecture-pipeline", args.architecture_pipeline]
    # Resume mechanism
    if args.resume_from:
        argv += ["--resume-from", args.resume_from]
    if args.draft_dir:
        argv += ["--draft-dir", args.draft_dir]
    # v0.8 revise + visual-QA
    if args.revise_severity_floor:
        argv += ["--revise-severity-floor", args.revise_severity_floor]
    if args.visual_qa:
        argv += ["--visual-qa"]
    if args.no_visual_qa:
        argv += ["--no-visual-qa"]
    # M5b image-provider override
    if args.image_provider:
        argv += ["--image-provider", args.image_provider]
    if args.max_image_approvals is not None:
        argv += ["--max-image-approvals", str(args.max_image_approvals)]

    print(f"▸ Running: {' '.join(argv)}", file=sys.stderr)
    print("", file=sys.stderr)
    return subprocess.run(argv).returncode
