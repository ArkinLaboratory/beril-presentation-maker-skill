#!/usr/bin/env python3
"""mode_consistency.py — DP9 hotfix (v1.1.1).

Two thin CLI helpers the bash orchestrator uses to keep the resolved
run mode (talk-15 / talk-30 / talk-45 / lightning-5 / poster-h /
poster-v) propagated and self-consistent across stages.

Why this exists
---------------
Pre-v1.1.1 the orchestrator defaulted MODE to talk-30 unconditionally.
`continue --resume-from <stage>` without `--mode talk-45` silently
re-ran downstream stages (image_gen_decision + qa_prep) at talk-30
even though the original draft was talk-45 — image affordances + Q&A
budget were sized to the smaller mode (caulobacter hub run 2026-06-07:
draft was talk-45, 05_image_decisions.json + qa_anticipated.json both
recorded talk-30). The fix has two halves, both implemented here:

  resolve-mode <draft_dir> [--fallback <mode>]
      Read working/slide_spec.json and print its `mode` field. On any
      failure (missing file, missing key, unparseable, mode not in
      MODES), print `--fallback` (default: empty string) and exit 0.
      The shell uses this on `--resume-from` to recover the original
      run mode when --mode wasn't re-passed.

  check-consistency <draft_dir> --run-mode <mode>
      Read the on-disk artifacts that record a mode field and assert
      they all equal --run-mode. Fails loud (exit 1, message to
      stderr) on any mismatch. Artifacts checked:
        working/slide_spec.json                  (top-level "mode")
        working/05_image_decisions.json          (top-level "mode")
        working/qa_anticipated.json              (envelope top-level
                                                  or nested under
                                                  "qa_anticipated_set")
      A missing artifact is NOT an error — only a present-but-
      different mode is. This lets the check run after every stage
      that touches one of these files without false-positiving when
      a later stage hasn't run yet.

Pure stdlib. No pytest dep at import time; the unit tests sit
alongside in tests/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Mirror of slide_spec.MODES — duplicated here to keep this helper
# free of cross-module imports (the orchestrator invokes it as a
# bare `python3 mode_consistency.py …`). Kept in sync by review.
MODES: tuple[str, ...] = (
    "talk-15",
    "talk-30",
    "talk-45",
    "lightning-5",
    "poster-h",
    "poster-v",
    "paper",
)


def _read_json(path: Path) -> dict | None:
    """Return parsed JSON object or None on any read/parse failure."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def resolve_mode_from_slide_spec(draft_dir: Path) -> str | None:
    """Return slide_spec.json's `mode` field, or None on any failure.

    Looks under working/slide_spec.json (the 4-zone layout). Returns
    None if the file doesn't exist, can't be parsed, lacks a `mode`
    field, or carries a mode not in MODES.
    """
    spec = _read_json(draft_dir / "working" / "slide_spec.json")
    if spec is None:
        return None
    mode = spec.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        return None
    return mode


def _extract_mode(obj: dict) -> str | None:
    """Pull the `mode` field from a top-level envelope, with one
    nested fallback for qa_anticipated.json (whose fragment shape
    nests under qa_anticipated_set in some prompt versions)."""
    mode = obj.get("mode")
    if isinstance(mode, str):
        return mode
    nested = obj.get("qa_anticipated_set")
    if isinstance(nested, dict):
        mode = nested.get("mode")
        if isinstance(mode, str):
            return mode
    return None


def check_mode_consistency(
    draft_dir: Path,
    run_mode: str,
) -> list[str]:
    """Return a list of mismatch findings; empty list means consistent.

    Checks these artifacts, skipping any that are missing:
      - working/slide_spec.json            (top-level "mode")
      - working/05_image_decisions.json    (top-level "mode")
      - working/qa_anticipated.json        (top-level or nested
                                            under "qa_anticipated_set")

    A finding is emitted only when an artifact is PRESENT and records
    a mode that DIFFERS from run_mode. Missing or unreadable artifacts
    are silently skipped — they'll be checked on the next stage that
    re-runs the consistency pass.
    """
    targets = [
        ("slide_spec.json", draft_dir / "working" / "slide_spec.json"),
        ("05_image_decisions.json",
         draft_dir / "working" / "05_image_decisions.json"),
        ("qa_anticipated.json",
         draft_dir / "working" / "03_slides" / "qa_anticipated.json"),
    ]
    findings: list[str] = []
    for label, path in targets:
        obj = _read_json(path)
        if obj is None:
            continue
        mode = _extract_mode(obj)
        if mode is None:
            continue
        if mode != run_mode:
            findings.append(
                f"{label}: mode={mode!r}, expected run mode={run_mode!r}"
            )
    return findings


def _cmd_resolve_mode(args: argparse.Namespace) -> int:
    mode = resolve_mode_from_slide_spec(Path(args.draft_dir).resolve())
    print(mode if mode is not None else args.fallback)
    return 0


def _cmd_check_consistency(args: argparse.Namespace) -> int:
    if args.run_mode not in MODES:
        print(
            f"mode_consistency: --run-mode {args.run_mode!r} not in MODES "
            f"({', '.join(MODES)})",
            file=sys.stderr,
        )
        return 2
    findings = check_mode_consistency(
        Path(args.draft_dir).resolve(),
        args.run_mode,
    )
    if findings:
        print(
            f"mode_consistency: FAIL — run mode is {args.run_mode!r} but "
            f"{len(findings)} artifact(s) disagree:",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print(
            "  Likely cause: continue/resume re-ran a stage without "
            "re-passing --mode; the orchestrator defaulted MODE and "
            "wrote the smaller mode's budget. Re-run with the correct "
            "--mode (or delete the stale artifact and let the stage "
            "rebuild it).",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="mode_consistency",
        description=(
            "DP9 hotfix: resolve run mode from slide_spec.json on resume; "
            "assert mode consistency across the artifacts that record it."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_res = sub.add_parser(
        "resolve-mode",
        help="Print mode from working/slide_spec.json (or fallback on failure).",
    )
    p_res.add_argument("draft_dir", help="Path to draft_N/.")
    p_res.add_argument(
        "--fallback", default="",
        help="String to print when mode can't be resolved (default: empty).",
    )
    p_res.set_defaults(func=_cmd_resolve_mode)

    p_chk = sub.add_parser(
        "check-consistency",
        help="Assert all on-disk artifacts that record `mode` match --run-mode.",
    )
    p_chk.add_argument("draft_dir", help="Path to draft_N/.")
    p_chk.add_argument(
        "--run-mode", required=True,
        help="The mode this run is operating in (talk-30, talk-45, …).",
    )
    p_chk.set_defaults(func=_cmd_check_consistency)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
