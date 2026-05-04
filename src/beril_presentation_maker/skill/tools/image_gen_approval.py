#!/usr/bin/env python3
"""image_gen_approval.py — Tier 5 approval-gate helper for v0.3.3 image-gen.

The gate is a thin UI primitive: it presents a request.json summary to
the user via stderr + reads a single keystroke from stdin (typically
/dev/tty when invoked from the orchestrator), and returns a structured
Verdict. The orchestrator owns the consequences (calling image_client,
mutating the manifest, etc).

Architecture per V0_3_3_ARCHITECTURE.md §8 with one v0.3.3 narrowing
(per Adam 2026-05-03): the [e]dit choice is OMITTED. Power users
hand-edit request.json between runs via --resume-from image_gen
instead. Documented in SKILL.md §image-generation.

This module also contains the post-write slide_id_target verifier
that Adam green-lit (architecture doc R3 trust-but-verify):
verify_request_slide_id() loads a request.json and confirms its
slide_id_target field matches what the orchestrator passed in.

Choices presented per slide:
  [a]pprove this slide / [r]eject this / [v]iew full prompt /
  [A]pprove all remaining / [R]eject all remaining / [q]uit

Bulk-mode signalling: when the user picks [A] or [R], the
orchestrator stores the bulk_mode and short-circuits subsequent
calls. This module reports that the user picked it; the
orchestrator owns the state.

Public API:

  prompt_approval(request_dict, *, budget_remaining_usd,
                  input_fn=input, output_stream=sys.stderr,
                  bulk_mode=None)
      → Verdict

  format_request_summary(request_dict, *, budget_remaining_usd)
      → str (multi-line preview shown to user)

  verify_request_slide_id(request_path, expected_slide_id_target)
      → list[str] of error strings; empty list means OK

  Verdict: enum {APPROVE, REJECT, APPROVE_ALL, REJECT_ALL, QUIT}
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, TextIO


PROMPT_PREVIEW_CHARS = 280  # full text available via [v]


class Verdict(Enum):
    """Per-slide verdict from the approval gate."""
    APPROVE = "approve"
    REJECT = "reject"
    APPROVE_ALL = "approve_all"
    REJECT_ALL = "reject_all"
    QUIT = "quit"

    @property
    def is_bulk(self) -> bool:
        return self in (Verdict.APPROVE_ALL, Verdict.REJECT_ALL)

    @property
    def is_approve(self) -> bool:
        return self in (Verdict.APPROVE, Verdict.APPROVE_ALL)

    @property
    def is_reject(self) -> bool:
        return self in (Verdict.REJECT, Verdict.REJECT_ALL)


# --------------------------------------------------------------------------
# Bulk-mode signalling
# --------------------------------------------------------------------------

class BulkMode(Enum):
    """When the user has previously chosen [A] or [R], the orchestrator
    sets a bulk_mode and the gate auto-resolves without prompting."""
    APPROVE_ALL = "approve_all"
    REJECT_ALL = "reject_all"


# --------------------------------------------------------------------------
# Summary formatting
# --------------------------------------------------------------------------

def format_request_summary(
    request_dict: dict,
    *,
    budget_remaining_usd: float,
) -> str:
    """Build the per-slide summary shown to the user.

    Multi-line stderr block; ANSI-free so it logs cleanly to non-tty
    audit captures. The full prompt is truncated to PROMPT_PREVIEW_CHARS
    in this view; [v] shows the rest.
    """
    slide_id = request_dict.get("slide_id_target", "?")
    layout_hint = request_dict.get("originator", "?")
    style = request_dict.get("style", "?")
    cost = float(request_dict.get("worst_case_cost_usd", 0.0))
    full_prompt = str(request_dict.get("image_prompt", ""))
    preview = (
        full_prompt
        if len(full_prompt) <= PROMPT_PREVIEW_CHARS
        else full_prompt[:PROMPT_PREVIEW_CHARS] + "..."
    )
    title = request_dict.get("slide_title")  # if orchestrator copied it through
    title_line = (
        f"   Slide title:  {title!r}\n"
        if title
        else ""
    )
    return (
        "=" * 66 + "\n"
        f"Image request: {slide_id} ({layout_hint})\n"
        f"{title_line}"
        f"   Style:        {style}\n"
        f"   Worst-case:   ${cost:.3f} (budget remaining: ${budget_remaining_usd:.3f})\n"
        f"   Prompt ({len(preview)}/{len(full_prompt)} chars):\n"
        f"     {preview!r}\n"
        + "=" * 66 + "\n"
    )


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

# Choice characters. Defined as constants so tests don't drift from
# the prompt's documented set.
_CHAR_APPROVE = "a"
_CHAR_REJECT = "r"
_CHAR_VIEW = "v"
_CHAR_APPROVE_ALL = "A"  # case-sensitive on purpose
_CHAR_REJECT_ALL = "R"
_CHAR_QUIT = "q"


def _menu_line() -> str:
    return (
        f"[{_CHAR_APPROVE}]pprove / "
        f"[{_CHAR_REJECT}]eject / "
        f"[{_CHAR_VIEW}]iew full prompt / "
        f"[{_CHAR_APPROVE_ALL}]pprove all remaining / "
        f"[{_CHAR_REJECT_ALL}]eject all remaining / "
        f"[{_CHAR_QUIT}]uit: "
    )


def prompt_approval(
    request_dict: dict,
    *,
    budget_remaining_usd: float,
    input_fn: Callable[[str], str] = input,
    output_stream: TextIO = sys.stderr,
    bulk_mode: Optional[BulkMode] = None,
) -> Verdict:
    """Show the per-slide approval prompt and return the user's verdict.

    Args:
      request_dict: parsed request.json contents.
      budget_remaining_usd: cumulative budget remaining for the deck.
        Displayed to the user; this function does NOT enforce the cap
        (caller checks before calling).
      input_fn: read-a-line function (defaults to builtin input()).
        Tests inject a deterministic stub.
      output_stream: where the summary is printed (defaults to stderr).
      bulk_mode: if set, the gate auto-resolves without prompting.
        APPROVE_ALL → APPROVE_ALL verdict, REJECT_ALL → REJECT_ALL
        verdict. Used when a previous slide chose the bulk option.

    Returns:
      Verdict value indicating the user's choice (or auto-resolved
      from bulk_mode).
    """
    if bulk_mode is BulkMode.APPROVE_ALL:
        return Verdict.APPROVE_ALL
    if bulk_mode is BulkMode.REJECT_ALL:
        return Verdict.REJECT_ALL

    summary = format_request_summary(
        request_dict, budget_remaining_usd=budget_remaining_usd,
    )
    print(summary, file=output_stream, flush=True)

    while True:
        try:
            raw = input_fn(_menu_line())
        except (EOFError, KeyboardInterrupt):
            # No interactive input available → treat as quit. Quieter
            # than crashing during a non-interactive smoke run.
            return Verdict.QUIT
        choice = raw.strip()
        if choice == _CHAR_APPROVE:
            return Verdict.APPROVE
        if choice == _CHAR_REJECT:
            return Verdict.REJECT
        if choice == _CHAR_APPROVE_ALL:
            return Verdict.APPROVE_ALL
        if choice == _CHAR_REJECT_ALL:
            return Verdict.REJECT_ALL
        if choice == _CHAR_QUIT:
            return Verdict.QUIT
        if choice == _CHAR_VIEW:
            full_prompt = str(request_dict.get("image_prompt", ""))
            negative_prompt = str(request_dict.get("negative_prompt", ""))
            print("", file=output_stream)
            print(f"  full image_prompt ({len(full_prompt)} chars):",
                  file=output_stream)
            print(f"    {full_prompt!r}", file=output_stream)
            print(f"  negative_prompt ({len(negative_prompt)} chars):",
                  file=output_stream)
            print(f"    {negative_prompt!r}", file=output_stream)
            print("", file=output_stream, flush=True)
            continue
        # Unrecognized input → re-prompt with a one-line nudge.
        print(
            f"  unrecognized choice {choice!r}; "
            f"valid: {_CHAR_APPROVE}/{_CHAR_REJECT}/{_CHAR_VIEW}/"
            f"{_CHAR_APPROVE_ALL}/{_CHAR_REJECT_ALL}/{_CHAR_QUIT}",
            file=output_stream,
            flush=True,
        )


# --------------------------------------------------------------------------
# Post-write slide_id_target verification
# --------------------------------------------------------------------------

def verify_request_slide_id(
    request_path: Path | str,
    expected_slide_id_target: str,
) -> list[str]:
    """Load a request.json and verify its slide_id_target field.

    The orchestrator passes SLIDE_ID_TARGET=S2-pos4 in the user prompt
    to ai_image_prompt.v1.md; the LLM is expected to copy it into the
    output JSON's slide_id_target field. This function is the
    trust-but-verify check (Adam green-lit 2026-05-03): if the LLM
    drops or mangles the field, the orchestrator catches it here
    before the request goes to user-approval.

    Returns:
      Empty list when verification passes.
      List of error strings when verification fails (suitable for
      stderr printing).
    """
    request_path = Path(request_path)
    errors: list[str] = []
    if not request_path.is_file():
        errors.append(f"request file not found: {request_path}")
        return errors
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"request file is not valid JSON: {request_path}: {e}")
        return errors
    if not isinstance(data, dict):
        errors.append(f"request file is not a JSON object: {request_path}")
        return errors
    if data.get("schema_version") != "image-request.v1":
        errors.append(
            f"request schema_version mismatch: expected "
            f"'image-request.v1', got {data.get('schema_version')!r}"
        )
    actual = data.get("slide_id_target")
    if actual != expected_slide_id_target:
        errors.append(
            f"slide_id_target mismatch: expected "
            f"{expected_slide_id_target!r}, got {actual!r} "
            f"(LLM dropped or mangled the field; reject this request)"
        )
    if data.get("approval_required") is not True:
        errors.append(
            f"approval_required must be true; got "
            f"{data.get('approval_required')!r} (D-029 violation)"
        )
    if data.get("channel") not in ("A", "B"):
        errors.append(
            f"channel must be 'A' or 'B'; got {data.get('channel')!r}"
        )
    return errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cmd_verify(args) -> int:
    errors = verify_request_slide_id(args.request_path, args.expected_slide_id)
    if errors:
        print(
            f"image_gen_approval: {len(errors)} error(s) verifying request:",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2
    print(
        f"image_gen_approval: OK ({args.request_path} → {args.expected_slide_id})",
        file=sys.stderr,
    )
    return 0


def _cmd_prompt(args) -> int:
    """CLI dispatch for the orchestrator. Reads the request.json,
    presents the approval prompt against /dev/tty, and exits with a
    code that maps to a verdict:

      0 → APPROVE
      1 → REJECT
      10 → APPROVE_ALL (bulk)
      11 → REJECT_ALL (bulk)
      20 → QUIT
      2 → bad inputs
    """
    request_path = Path(args.request_path)
    if not request_path.is_file():
        print(f"image_gen_approval: request file not found: {request_path}",
              file=sys.stderr)
        return 2
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"image_gen_approval: malformed request JSON: {e}",
              file=sys.stderr)
        return 2

    bulk_mode = None
    if args.bulk_mode == "approve_all":
        bulk_mode = BulkMode.APPROVE_ALL
    elif args.bulk_mode == "reject_all":
        bulk_mode = BulkMode.REJECT_ALL

    # Read from /dev/tty so this works when stdin is piped.
    def _tty_input(prompt: str) -> str:
        try:
            with open("/dev/tty", "r", encoding="utf-8") as tty:
                print(prompt, end="", file=sys.stderr, flush=True)
                line = tty.readline()
                if not line:
                    raise EOFError
                return line.rstrip("\n")
        except OSError:
            # No tty (e.g., CI) → fall back to builtin input(); will
            # raise EOFError if stdin is closed.
            return input(prompt)

    verdict = prompt_approval(
        data,
        budget_remaining_usd=args.budget_remaining_usd,
        input_fn=_tty_input,
        bulk_mode=bulk_mode,
    )
    return _verdict_to_exit_code(verdict)


def _verdict_to_exit_code(verdict: Verdict) -> int:
    """Translate Verdict → CLI exit code per the documented contract."""
    return {
        Verdict.APPROVE: 0,
        Verdict.REJECT: 1,
        Verdict.APPROVE_ALL: 10,
        Verdict.REJECT_ALL: 11,
        Verdict.QUIT: 20,
    }[verdict]


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="image_gen_approval",
        description="v0.3.3 image-gen approval gate + slide_id verifier.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser(
        "verify",
        help="Verify a request.json's slide_id_target matches expected.",
    )
    p_verify.add_argument("request_path", help="Path to <slide>_request.json")
    p_verify.add_argument("expected_slide_id",
                          help="Expected slide_id_target value")
    p_verify.set_defaults(func=_cmd_verify)

    p_prompt = sub.add_parser(
        "prompt",
        help="Show approval prompt; exit code maps to verdict.",
    )
    p_prompt.add_argument("request_path",
                          help="Path to <slide>_request.json")
    p_prompt.add_argument("--budget-remaining-usd", type=float, required=True,
                          help="Cumulative budget remaining for the deck.")
    p_prompt.add_argument(
        "--bulk-mode", default=None,
        choices=("approve_all", "reject_all"),
        help="If set, auto-resolve without prompting.",
    )
    p_prompt.set_defaults(func=_cmd_prompt)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
