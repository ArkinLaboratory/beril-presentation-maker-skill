#!/usr/bin/env python3
"""image_gen_orchestrate.py — Tier 6a Python helpers for the v0.3.3
image-gen orchestrator stage.

The bash side (`presentation_maker.sh::stage_image_gen`) drives the
per-slide loop; this module provides the bookkeeping primitives so
bash stays thin:

  - snapshot-fragment    — copy a fragment to audit/snapshots/03_slides_pre_image_gen/
                           before image-gen mutates the working/03_slides/ copy
  - find-fragment        — given slide_id (e.g., "S2-pos4" or "intro-pos0"),
                           emit the fragment file path. Used by bash to know
                           which fragment to snapshot.
  - budget-remaining     — cumulative cap minus manifest.total_cost_usd
  - record-approved      — mutate manifest, append approved entry
  - record-rejected      — mutate manifest, append rejected entry
  - record-skipped       — mutate manifest, append budget-skipped entry
  - mutate-fragment-bind — write image_path + provenance into the fragment's
                           concept_illustration slide content (so revise_loop
                           and merge see the bound image)

All subcommands operate on a draft_dir with v0.3.1+ layout. Manifest
load-mutate-write is one Python invocation per call (atomic-replace
write_text). Cumulative cost across all approved entries gives the
budget-remaining computation; the bash side checks before each
candidate slide.

Slide-id format: "S{N}-pos{P}" for substory slides (substory_id +
0-indexed fragment_position) or "intro-pos{P}" for intro slides.
Convention frozen across image_gen_decision.py, manifest, and merge.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

# Sibling-tool imports.
_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))
import draft_paths as dp  # noqa: E402
import image_gen_manifest as igm  # noqa: E402


_SLIDE_ID_RE = re.compile(r"^(?P<sid>S\d+|intro)-pos(?P<pos>\d+)$")


def _parse_slide_id(slide_id: str) -> tuple[str, int]:
    """Parse 'S2-pos4' or 'intro-pos0' → ('S2', 4) / ('intro', 0).

    Raises ValueError for unrecognized shapes."""
    m = _SLIDE_ID_RE.match(slide_id)
    if not m:
        raise ValueError(
            f"slide_id {slide_id!r} doesn't match 'S{{N}}-pos{{P}}' or "
            f"'intro-pos{{P}}' convention"
        )
    return m.group("sid"), int(m.group("pos"))


def fragment_path_for_slide_id(
    paths: dp.DraftPaths,
    slide_id: str,
) -> Path:
    """Resolve the fragment JSON file containing this slide.

    Substory slides live in working/03_slides/<sid>_slides.json
    (e.g., S1_slides.json). Intro slides live in
    working/03_slides/intro.json.
    """
    sid, _pos = _parse_slide_id(slide_id)
    if sid == "intro":
        return paths.slides_dir / "intro.json"
    return paths.slides_dir / f"{sid}_slides.json"


def fragment_id_for_slide_id(slide_id: str) -> str:
    """Map slide_id → fragment_id used by DraftPaths.pre_image_gen_snapshot.

    'S2-pos4' → 'S2_slides'. 'intro-pos0' → 'intro'. Matches the
    fragment_id convention DraftPaths.slide_fragment() expects.
    """
    sid, _pos = _parse_slide_id(slide_id)
    if sid == "intro":
        return "intro"
    return f"{sid}_slides"


def snapshot_fragment(paths: dp.DraftPaths, slide_id: str) -> Path:
    """Copy the slide's fragment to audit/snapshots/03_slides_pre_image_gen/.

    Idempotent across multiple slides in the same fragment: the second
    call is a no-op (the snapshot already exists; copying again would
    overwrite with the in-progress mutation we're trying to back up).

    Raises FileNotFoundError if the fragment doesn't exist.
    """
    fragment_path = fragment_path_for_slide_id(paths, slide_id)
    if not fragment_path.is_file():
        raise FileNotFoundError(
            f"fragment file not found for slide_id={slide_id}: {fragment_path}"
        )
    fragment_id = fragment_id_for_slide_id(slide_id)
    snapshot_path = paths.pre_image_gen_snapshot(fragment_id)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot_path.is_file():
        # Already snapshotted (earlier slide in this fragment). Don't
        # overwrite — the pristine pre-image-gen state must be preserved.
        return snapshot_path
    shutil.copy2(fragment_path, snapshot_path)
    return snapshot_path


def mutate_fragment_bind(
    paths: dp.DraftPaths,
    *,
    slide_id: str,
    image_path: str,
    model: str,
    cost_usd: float,
    channel: str,
    approved_at: str,
) -> dict:
    """Mutate the fragment's concept_illustration slide content to bind
    the real image_path + provenance, replacing the {TBD} placeholders.

    Returns the mutated slide dict.

    The fragment file is rewritten via load → mutate → write. Snapshot
    of the pre-mutation state must already exist (caller should have
    invoked snapshot_fragment first); this function does NOT auto-snapshot.
    """
    sid, pos = _parse_slide_id(slide_id)
    fragment_path = fragment_path_for_slide_id(paths, slide_id)
    if not fragment_path.is_file():
        raise FileNotFoundError(
            f"fragment file not found for slide_id={slide_id}: {fragment_path}"
        )
    fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    slides = fragment.get("slides", [])
    if pos >= len(slides):
        raise IndexError(
            f"slide_id={slide_id} position {pos} out of range "
            f"(fragment has {len(slides)} slides)"
        )
    slide = slides[pos]
    if slide.get("layout") != "concept_illustration":
        raise ValueError(
            f"slide_id={slide_id} layout is "
            f"{slide.get('layout')!r}, not 'concept_illustration'; "
            f"image-gen mutate is only valid on concept_illustration slides"
        )
    content = slide.setdefault("content", {})
    content["image_path"] = image_path
    content["provenance"] = {
        "model": model,
        "cost_usd": float(cost_usd),
        "channel": channel,
        "approved_at": approved_at,
    }
    fragment_path.write_text(
        json.dumps(fragment, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return slide


def remaining_budget(
    paths: dp.DraftPaths,
    *,
    cap_usd: float,
) -> float:
    """Return cap_usd minus the manifest's cumulative approved cost.

    Floor at 0.0 so callers don't see negative remaining budget. If
    the manifest is missing, remaining = cap (no spending yet)."""
    if not paths.image_manifest_json.is_file():
        return float(cap_usd)
    manifest = igm.Manifest.load(paths.image_manifest_json)
    spent = manifest.total_cost_usd()
    return max(0.0, float(cap_usd) - spent)


def record_approved(
    paths: dp.DraftPaths,
    *,
    slide_id: str,
    image_path: str,
    request_path: str,
    channel: str,
    model: str,
    cost_usd: float,
    approved_at: Optional[str] = None,
) -> None:
    """Append an approved entry to the manifest and write."""
    paths.image_manifest_json.parent.mkdir(parents=True, exist_ok=True)
    manifest = igm.Manifest.load(paths.image_manifest_json)
    if not manifest.draft_dir:
        manifest.draft_dir = str(paths.draft_dir)
    manifest.add_approved(
        slide_id=slide_id,
        image_path=image_path,
        request_path=request_path,
        channel=channel,
        model=model,
        cost_usd=cost_usd,
        approved_at=approved_at,
    )
    manifest.write(paths.image_manifest_json)


def record_rejected(
    paths: dp.DraftPaths,
    *,
    slide_id: str,
    reason: str,
    request_path: Optional[str] = None,
) -> None:
    """Append a user-rejected entry to the manifest and write."""
    paths.image_manifest_json.parent.mkdir(parents=True, exist_ok=True)
    manifest = igm.Manifest.load(paths.image_manifest_json)
    if not manifest.draft_dir:
        manifest.draft_dir = str(paths.draft_dir)
    manifest.add_rejected(
        slide_id=slide_id,
        reason=reason,
        request_path=request_path,
    )
    manifest.write(paths.image_manifest_json)


def record_skipped(
    paths: dp.DraftPaths,
    *,
    slide_id: str,
    reason: str,
) -> None:
    """Append a budget-skipped entry to the manifest and write."""
    paths.image_manifest_json.parent.mkdir(parents=True, exist_ok=True)
    manifest = igm.Manifest.load(paths.image_manifest_json)
    if not manifest.draft_dir:
        manifest.draft_dir = str(paths.draft_dir)
    manifest.add_skipped(
        slide_id=slide_id,
        reason=reason,
    )
    manifest.write(paths.image_manifest_json)


# --------------------------------------------------------------------------
# v1.1.1/DP3 fail-loud check
# --------------------------------------------------------------------------

def find_unresolved_requests(paths: dp.DraftPaths) -> list[str]:
    """Return slide_ids whose request.json exists but neither a PNG
    nor a manifest-recorded reject/skip entry exists.

    DP3 root cause (caulobacter 2026-06-07): the ai_image_prompt stage
    wrote `05_image_requests/S4-pos3_request.json` and the approval
    gate auto-approved (`--auto-approve-images`), but generation
    never produced `05_images/S4-pos3.png` AND no rejection record
    was written. The silent miss read as success: the deck rendered
    with the slide's stock figure instead of the requested AI image,
    and audit/stage-metadata.json had no signal.

    The fail-loud rule: every request file MUST resolve to one of
        (a) the matching PNG in 05_images/  (the success path), OR
        (b) a manifest entry for that slide_id with approved=False
            (the explicit rejection / skip path).
    Anything else is `image_requested_but_not_produced`. Returns the
    list of unresolved slide_ids; caller decides exit code.
    """
    image_requests_dir = paths.image_requests_dir
    if not image_requests_dir.is_dir():
        return []

    # Build the set of manifest slide_ids that are known-rejected/skipped
    # (i.e. legitimately have no PNG). approved=True entries don't need
    # to appear here — the PNG check below catches them as resolved.
    accounted_in_manifest: set[str] = set()
    if paths.image_manifest_json.is_file():
        manifest = igm.Manifest.load(paths.image_manifest_json)
        for entry in manifest.entries:
            if not entry.get("approved", False):
                sid = entry.get("slide_id")
                if isinstance(sid, str):
                    accounted_in_manifest.add(sid)

    unresolved: list[str] = []
    for request_path in sorted(image_requests_dir.glob("*_request.json")):
        # Slide id from filename: `S4-pos3_request.json` → `S4-pos3`.
        sid = request_path.stem[: -len("_request")]
        png_path = paths.images_dir / f"{sid}.png"
        if png_path.is_file():
            continue
        if sid in accounted_in_manifest:
            continue
        unresolved.append(sid)
    return unresolved


def _cmd_assert_requests_resolved(args: argparse.Namespace) -> int:
    """CLI: fail loud (exit 1) if any request lacks a PNG and a manifest
    reject/skip entry. Exit 0 when every request is accounted for.
    Used by the bash orchestrator at the tail of stage_image_gen."""
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    unresolved = find_unresolved_requests(paths)
    if not unresolved:
        return 0
    print(
        f"image_gen_orchestrate: FAIL — {len(unresolved)} image "
        f"request(s) wrote a prompt but produced no PNG and no manifest "
        f"reject/skip entry (image_requested_but_not_produced):",
        file=sys.stderr,
    )
    for sid in unresolved:
        print(f"  - {sid}", file=sys.stderr)
    print(
        "  Likely cause: image_client.py was never invoked, or it "
        "exited without raising the failure path. Re-run image_gen "
        "(beril-presentation-maker continue <draft_dir> --resume-from "
        "image_gen) after diagnosing.",
        file=sys.stderr,
    )
    return 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cmd_find_fragment(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    try:
        fragment = fragment_path_for_slide_id(paths, args.slide_id)
    except ValueError as e:
        print(f"image_gen_orchestrate: {e}", file=sys.stderr)
        return 2
    if not fragment.is_file():
        print(
            f"image_gen_orchestrate: fragment not found: {fragment}",
            file=sys.stderr,
        )
        return 1
    print(fragment)
    return 0


def _cmd_snapshot_fragment(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    try:
        snapshot = snapshot_fragment(paths, args.slide_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"image_gen_orchestrate: {e}", file=sys.stderr)
        return 1
    print(snapshot)
    return 0


def _cmd_budget_remaining(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    remaining = remaining_budget(paths, cap_usd=args.cap_usd)
    # Print 4 decimal places — gemini-3-pro-image is ~$0.014/image,
    # so 3 decimals lose precision when comparing budgets.
    print(f"{remaining:.4f}")
    return 0


def _cmd_record_approved(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    try:
        record_approved(
            paths,
            slide_id=args.slide_id,
            image_path=args.image_path,
            request_path=args.request_path,
            channel=args.channel,
            model=args.model,
            cost_usd=args.cost_usd,
            approved_at=args.approved_at,
        )
    except igm.ManifestError as e:
        print(f"image_gen_orchestrate: {e}", file=sys.stderr)
        return 2
    return 0


def _cmd_record_rejected(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    try:
        record_rejected(
            paths,
            slide_id=args.slide_id,
            reason=args.reason,
            request_path=args.request_path,
        )
    except igm.ManifestError as e:
        print(f"image_gen_orchestrate: {e}", file=sys.stderr)
        return 2
    return 0


def _cmd_record_skipped(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    try:
        record_skipped(
            paths,
            slide_id=args.slide_id,
            reason=args.reason,
        )
    except igm.ManifestError as e:
        print(f"image_gen_orchestrate: {e}", file=sys.stderr)
        return 2
    return 0


def _cmd_mutate_fragment_bind(args: argparse.Namespace) -> int:
    paths = dp.DraftPaths.from_draft_dir(args.draft_dir)
    try:
        mutate_fragment_bind(
            paths,
            slide_id=args.slide_id,
            image_path=args.image_path,
            model=args.model,
            cost_usd=args.cost_usd,
            channel=args.channel,
            approved_at=args.approved_at,
        )
    except (FileNotFoundError, IndexError, ValueError) as e:
        print(f"image_gen_orchestrate: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="image_gen_orchestrate",
        description="v0.3.3 image-gen orchestration helpers (Tier 6a).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_find = sub.add_parser(
        "find-fragment",
        help="Print the fragment JSON path for a slide_id.",
    )
    p_find.add_argument("--draft-dir", required=True)
    p_find.add_argument("--slide-id", required=True)
    p_find.set_defaults(func=_cmd_find_fragment)

    p_snap = sub.add_parser(
        "snapshot-fragment",
        help="Copy fragment to audit/snapshots/03_slides_pre_image_gen/.",
    )
    p_snap.add_argument("--draft-dir", required=True)
    p_snap.add_argument("--slide-id", required=True)
    p_snap.set_defaults(func=_cmd_snapshot_fragment)

    p_budget = sub.add_parser(
        "budget-remaining",
        help="Print remaining budget (cap minus approved manifest cost).",
    )
    p_budget.add_argument("--draft-dir", required=True)
    p_budget.add_argument("--cap-usd", type=float, required=True)
    p_budget.set_defaults(func=_cmd_budget_remaining)

    p_appr = sub.add_parser(
        "record-approved",
        help="Append approved entry to the manifest.",
    )
    p_appr.add_argument("--draft-dir", required=True)
    p_appr.add_argument("--slide-id", required=True)
    p_appr.add_argument("--image-path", required=True)
    p_appr.add_argument("--request-path", required=True)
    p_appr.add_argument("--channel", required=True, choices=("A", "B"))
    p_appr.add_argument("--model", required=True)
    p_appr.add_argument("--cost-usd", type=float, required=True)
    p_appr.add_argument("--approved-at", default=None,
                        help="ISO-8601 UTC timestamp (default: now)")
    p_appr.set_defaults(func=_cmd_record_approved)

    p_rej = sub.add_parser(
        "record-rejected",
        help="Append user-rejected entry to the manifest.",
    )
    p_rej.add_argument("--draft-dir", required=True)
    p_rej.add_argument("--slide-id", required=True)
    p_rej.add_argument("--reason", required=True)
    p_rej.add_argument("--request-path", default=None)
    p_rej.set_defaults(func=_cmd_record_rejected)

    p_skip = sub.add_parser(
        "record-skipped",
        help="Append budget-skipped entry to the manifest.",
    )
    p_skip.add_argument("--draft-dir", required=True)
    p_skip.add_argument("--slide-id", required=True)
    p_skip.add_argument("--reason", required=True)
    p_skip.set_defaults(func=_cmd_record_skipped)

    p_mut = sub.add_parser(
        "mutate-fragment-bind",
        help="Bind image_path + provenance into a concept_illustration slide.",
    )
    p_mut.add_argument("--draft-dir", required=True)
    p_mut.add_argument("--slide-id", required=True)
    p_mut.add_argument("--image-path", required=True)
    p_mut.add_argument("--model", required=True)
    p_mut.add_argument("--cost-usd", type=float, required=True)
    p_mut.add_argument("--channel", required=True, choices=("A", "B"))
    p_mut.add_argument("--approved-at", required=True)
    p_mut.set_defaults(func=_cmd_mutate_fragment_bind)

    p_assert = sub.add_parser(
        "assert-requests-resolved",
        help=("v1.1.1/DP3 fail-loud: every 05_image_requests/*.json must "
              "either produce a 05_images/<sid>.png OR have a manifest "
              "reject/skip entry. Exit 1 with a list of unresolved "
              "slide_ids on mismatch."),
    )
    p_assert.add_argument("--draft-dir", required=True)
    p_assert.set_defaults(func=_cmd_assert_requests_resolved)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
