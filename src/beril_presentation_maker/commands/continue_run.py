"""`beril-presentation-maker continue <draft_dir> [--pick TLN | --resume-from <stage>]` — resume a paused draft.

Thin Python wrapper around `presentation_maker.sh`. Two resume modes:

1. **--pick TLN** (v0.3.6+): the throughline-pick gate handoff path. After
   `draft` halts at the throughline gate (writes `<draft_dir>/.handoff.json`
   with `phase=throughline_pick` + candidates), the user (or slash command
   agent) reads candidates, picks one, and runs `continue <draft_dir>
   --pick TL2`. The continue command:
     - Validates TLN against `.handoff.json` candidates
     - Invokes `parse_throughline_candidates.py --pick TLN` to write
       `narrative/00_throughline.md`
     - Removes `.handoff.json` (gate consumed)
     - Dispatches bash with `--resume-from substory_design`
   This is the path 100% of hub participants take, since Claude Code
   auto-backgrounds bash invocations and the gate's TTY-block fails
   without --auto-advance.

2. **--resume-from <stage>** (legacy v0.3.0+): explicit stage replay. Re-runs
   from the named stage onward, reusing the on-disk artifacts of earlier
   stages. Useful for prompt-iteration on a single stage or recovery after
   a mid-pipeline failure.
   Stages: plan | throughline | substory_design | curate_figures |
   citation_pool | cross_tenant | intro | slide_compose | qa_prep |
   speaker_notes | image_gen | merge | adversarial_review | revise_slides
   Cost savings:
     from intro:         ~$1.50 (saves plan+throughline+substory)
     from slide_compose: ~$1.20 (saves plan+throughline+substory+intro)
     from merge:         FREE (no LLM; assembly only)

`--pick` and `--resume-from` are mutually exclusive. If neither is passed
and `.handoff.json` exists with `phase=throughline_pick`, the command
errors helpfully showing the candidate list. Full state.json + Phase enum
(paper-writer's complete pattern) is v0.4.0 work; this v0.3.6 ships a
single-purpose handoff at the one gate that 100% of participants hit.
"""

from __future__ import annotations

import argparse
import json
import re
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
    # v0.3.6: --pick and --resume-from are mutually exclusive resume paths.
    # Neither is required at argparse-level (so we can error helpfully when
    # both are absent and surface the candidate list from .handoff.json).
    p.add_argument(
        "--pick",
        default=None,
        help=(
            "Throughline candidate id (e.g. TL2). Use this when the previous "
            "`draft` invocation halted at the throughline-pick gate (look "
            "for <draft_dir>/.handoff.json with phase=throughline_pick). "
            "Mutually exclusive with --resume-from."
        ),
    )
    p.add_argument(
        "--resume-from",
        default=None,
        choices=_VALID_STAGES,
        help=(
            "Stage to resume from (legacy power-user mode). Earlier-stage "
            "artifacts are reused. Mutually exclusive with --pick."
        ),
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


def _read_handoff(draft_dir: Path) -> dict | None:
    """Read <draft_dir>/.handoff.json if it exists. Returns None otherwise.

    Failed reads (corrupt JSON, etc.) are treated as absent — they'd surface
    via the bash dispatch path's normal error handling.
    """
    handoff_path = draft_dir / ".handoff.json"
    if not handoff_path.is_file():
        return None
    try:
        with handoff_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


_TLN_RE = re.compile(r"^TL\d+$")


def _validate_pick_against_handoff(pick: str, handoff: dict) -> tuple[bool, str]:
    """Validate that `pick` matches a candidate in `handoff['candidates']`.

    Returns (ok, message). On failure, message is human-readable error text.
    On success, message is the candidate's label.
    """
    if not _TLN_RE.match(pick):
        return False, (
            f"--pick value {pick!r} doesn't match the TLN shape (TL1, TL2, ...). "
            f"Pass an explicit candidate id from the handoff."
        )
    candidates = handoff.get("candidates", [])
    for c in candidates:
        if c.get("id") == pick:
            return True, c.get("label", "")
    valid = ", ".join(c.get("id", "?") for c in candidates) or "(none)"
    return False, (
        f"--pick {pick!r} not in the throughline-pick handoff candidates. "
        f"Valid choices: {valid}. See <draft_dir>/.handoff.json for the full list."
    )


def _resolve_pick_to_resume_stage(
    draft_dir: Path, pick: str, sh_path: Path
) -> tuple[str, int]:
    """Run parse_throughline_candidates.py with the chosen pick to write
    narrative/00_throughline.md. Remove .handoff.json on success (gate consumed).

    Returns ("substory_design", 0) on success — the resume_from stage to
    dispatch with. On failure, returns ("", non_zero_rc).
    """
    handoff = _read_handoff(draft_dir)
    if handoff is None:
        print(
            f"error: --pick {pick!r} requires <draft_dir>/.handoff.json "
            f"(was the previous `draft` invocation halted at the "
            f"throughline-pick gate?). If you're trying to do a stage-replay, "
            f"use --resume-from <stage> instead.",
            file=sys.stderr,
        )
        return "", 3
    if handoff.get("phase") != "throughline_pick":
        print(
            f"error: handoff phase is {handoff.get('phase')!r}, not "
            f"'throughline_pick'. --pick TLN is only valid at the "
            f"throughline-pick gate.",
            file=sys.stderr,
        )
        return "", 3

    ok, msg = _validate_pick_against_handoff(pick, handoff)
    if not ok:
        print(f"error: {msg}", file=sys.stderr)
        return "", 3

    candidates_md = handoff.get("candidates_md")
    if not candidates_md or not Path(candidates_md).is_file():
        print(
            f"error: handoff candidates_md path missing or doesn't exist: "
            f"{candidates_md!r}",
            file=sys.stderr,
        )
        return "", 3

    # Locate parse_throughline_candidates.py via package data, sibling to the
    # orchestrator shell script.
    parse_py = sh_path.parent / "parse_throughline_candidates.py"
    if not parse_py.is_file():
        print(
            f"error: parse_throughline_candidates.py not found beside "
            f"{sh_path}. Reinstall beril-presentation-maker-skill.",
            file=sys.stderr,
        )
        return "", 3

    out_path = draft_dir / "narrative" / "00_throughline.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rc = subprocess.run(
        [
            sys.executable,
            str(parse_py),
            "--candidates", str(candidates_md),
            "--pick", pick,
            "--out", str(out_path),
        ]
    ).returncode
    if rc != 0:
        print(
            f"error: parse_throughline_candidates.py failed with rc={rc} "
            f"on pick={pick!r}",
            file=sys.stderr,
        )
        return "", rc

    print(f"  picked {pick}: {msg!r}", file=sys.stderr)
    print(f"  wrote {out_path}", file=sys.stderr)

    # Consume the handoff so a subsequent re-run doesn't re-prompt.
    try:
        (draft_dir / ".handoff.json").unlink()
    except OSError:
        pass

    return "substory_design", 0


def _print_handoff_error(draft_dir: Path, handoff: dict) -> None:
    """Print a helpful error when the user invoked continue without --pick
    or --resume-from but a throughline_pick handoff is waiting."""
    print(
        f"error: <draft_dir>/.handoff.json is waiting at the "
        f"throughline-pick gate. Pass --pick TLN to resume.",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("  Available candidates:", file=sys.stderr)
    for c in handoff.get("candidates", []):
        cid = c.get("id", "?")
        label = c.get("label", "(no label)")
        print(f"    {cid}: {label}", file=sys.stderr)
    candidates_md = handoff.get("candidates_md")
    if candidates_md:
        print("", file=sys.stderr)
        print(
            f"  Open {candidates_md} for the full evidence map per candidate.",
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    print(
        f"  Then run: beril-presentation-maker continue {draft_dir} --pick TLN",
        file=sys.stderr,
    )


def run(args: argparse.Namespace) -> int:
    draft_dir = Path(args.draft_dir).expanduser().resolve()
    if not draft_dir.is_dir():
        print(f"error: draft_dir does not exist: {draft_dir}", file=sys.stderr)
        return 1

    # v0.3.6: --pick and --resume-from are mutually exclusive.
    if args.pick and args.resume_from:
        print(
            "error: --pick and --resume-from are mutually exclusive. "
            "Use --pick TLN for throughline-pick gate resume; use "
            "--resume-from <stage> for explicit stage replay.",
            file=sys.stderr,
        )
        return 2

    try:
        sh_path = _locate_orchestrator()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # v0.3.6: --pick path — consume the handoff, derive resume_from.
    if args.pick:
        resume_from, rc = _resolve_pick_to_resume_stage(
            draft_dir, args.pick, sh_path
        )
        if rc != 0:
            return rc
    elif args.resume_from:
        resume_from = args.resume_from
    else:
        # Neither flag passed — error helpfully if a handoff is waiting,
        # otherwise tell the user one of the flags is required.
        handoff = _read_handoff(draft_dir)
        if handoff is not None and handoff.get("phase") == "throughline_pick":
            _print_handoff_error(draft_dir, handoff)
            return 3
        print(
            "error: continue requires either --pick TLN (throughline-pick "
            "gate resume) or --resume-from <stage> (explicit stage replay).",
            file=sys.stderr,
        )
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
        "--resume-from", resume_from,
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
