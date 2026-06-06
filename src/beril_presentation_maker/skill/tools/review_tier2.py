#!/usr/bin/env python3
"""review_tier2.py — Tier 2 narrative-light Haiku review (v0.4 M4b).

V0_4_ARCHITECTURE.md §8.1 Tier 2 + M4b_PUNCH_LIST.md Tier C. Invokes
`claude -p` with `prompts/review_tier2.v1.md` as system prompt against
the merged `working/slide_spec.json` + the narrative artifacts. Flags
the four detection classes from §8.1:

  - register_drift           — voice / hedge / acronym inconsistency
                               across or within substories.
  - qa_softball              — qa_anticipated questions with low
                               information value (leading, low-novelty,
                               procedural-not-substantive).
  - unbacked_quantitative    — rhetorical numbers that look like
                               evidence (calc-on-slide; comparison
                               unquantified in REPORT; aggregate not
                               in source table). Distinct from Tier 1's
                               strict P3 numeric-provenance check.
  - substory_arc             — slides assigned to a substory don't
                               LAND that substory's declared punchline
                               (open / develop / close drift).

Per DQ4 (M4b — Adam 2026-05-24), Tier 2 is ALWAYS ADVISORY: every
finding is severity P1 or P2; the cascade never short-circuits on a
Tier-2 finding; Tier 3 always runs. Per DQ3, the four-class scope
ships as v1 with calibration as a one-off probe + ship-then-iterate.

This is an ADVISORY tool (rc=0 always, like visual_qa.py +
reconcile_deck.py). Findings inform the revise loop + Tier-3 reviewer.

Pinned model: claude-haiku-4-5-20251001 (Haiku 4.5; cheap fast review,
matches §8.1 Tier-2 cost target ~$0.05/run). Override via --model.

CLI:
    python3 review_tier2.py <draft_dir>
                            [--quiet]
                            [--model NAME]
                            [--claude-bin PATH]

Exit code: always 0 (advisory). The cascade JSON consumer reads
audit/review_tier2.json; missing audit file → cascade emits no Tier-2
findings (cascade Tier C → Tier-2 dispatcher returns empty findings).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "review-tier2.v1"
VERSION = "0.4.0-m4b-tierC"

_THIS_DIR = Path(__file__).resolve().parent
_PROMPT_PATH = _THIS_DIR.parent / "prompts" / "review_tier2.v1.md"

# CRAFT-CONTRACT §3.4 / Round 2a fixup (2): Tier-2 review is the
# narrative-light Haiku pass by design — DQ3 "Haiku 4.5 ~$0.05/run
# target" stays in force; this is the cheap mechanical review, not
# the high-leverage critique tier. Claude Code resolves the alias
# via ANTHROPIC_DEFAULT_HAIKU_MODEL in
# <BERIL_ROOT>/.claude/settings.json (written by `configure`).
# Operators wanting to escalate can pin `--model sonnet` on the call
# site; the floor default stays fast/haiku.
DEFAULT_MODEL = "haiku"

# Allowed tools for the claude -p subprocess. Tier 2 reads structured
# inputs (slide_spec.json, throughline.md, substories.md, the Tier 1
# quantitative_grounding.json) and writes the two output files. No
# Bash; no Edit; this is a structured review, not a tool-using agent.
_ALLOWED_TOOLS = "Read,Write"


# ---------------------------------------------------------------------------
# Toolchain probe (just claude — no soffice/pdftoppm; Tier 2 has no
# render pipeline)
# ---------------------------------------------------------------------------


def _which(binary: str) -> str | None:
    """Return absolute path to binary on PATH, or None."""
    return shutil.which(binary)


@dataclass
class ToolchainStatus:
    """Result of probing the Tier-2 dependencies (just claude)."""

    claude: str | None

    @property
    def ok(self) -> bool:
        return bool(self.claude)

    def missing(self) -> list[str]:
        return [] if self.claude else ["claude (Claude Code CLI)"]


def probe_toolchain(claude_bin: str = "claude") -> ToolchainStatus:
    """Probe the claude CLI."""
    return ToolchainStatus(claude=_which(claude_bin))


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_cost_from_envelope(stdout: str) -> tuple[float, str]:
    """Parse total_cost_usd from a claude -p --output-format json envelope.

    Same pattern as extract_claims.py + visual_qa.py — a telemetry miss
    never fails the call; cost_usd falls back to 0.0 with a cost_note
    explaining why.
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


def invoke_tier2_review(
    *,
    draft_dir: Path,
    slide_spec_path: Path,
    throughline_path: Path,
    substories_path: Path,
    quant_grounding_path: Path,
    out_json_path: Path,
    out_md_path: Path,
    prompt_path: Path = _PROMPT_PATH,
    claude_bin: str = "claude",
    model: str = DEFAULT_MODEL,
    env: dict | None = None,
) -> dict:
    """Invoke ``claude -p`` with the review_tier2.v1 system prompt.

    The user prompt names all five inputs (draft_dir, slide_spec_path,
    throughline_path, substories_path, quant_grounding_path) + the two
    output paths. The system prompt is review_tier2.v1.md which tells
    the model to read each input, scan for the 4 detection classes,
    and write audit/review_tier2.{json,md}.

    Returns a diagnostic dict (exit_status, output_present, duration_sec,
    cost_usd, cost_note, stdout_tail, stderr_tail, model). Does NOT
    raise on subprocess failure — the caller decides escalation.
    """
    if not prompt_path.is_file():
        raise FileNotFoundError(
            f"review_tier2 prompt not found at {prompt_path}; "
            f"check that the skill package is installed correctly."
        )
    system_prompt = prompt_path.read_text(encoding="utf-8")

    # Build the user prompt. Each path is named explicitly so the model
    # can Read each one. Optional paths (throughline + substories +
    # quant_grounding) are passed as-is; the system prompt's escape-
    # hatch section tells the model to skip the affected class if the
    # path is missing.
    user_prompt = (
        "Please execute the Tier 2 review task.\n"
        f"- DRAFT_DIR: {draft_dir}\n"
        f"- SLIDE_SPEC_PATH: {slide_spec_path}\n"
        f"- THROUGHLINE_PATH: {throughline_path}\n"
        f"- SUBSTORIES_PATH: {substories_path}\n"
        f"- QUANT_GROUNDING_PATH: {quant_grounding_path}\n"
        f"- OUT_PATH: {out_json_path}\n"
        f"- OUT_PATH_MD: {out_md_path}\n"
        "\n"
        "Read each input path with the Read tool, scan the slide_spec "
        "for the four detection classes from your system prompt "
        "(register_drift, qa_softball, unbacked_quantitative, "
        "substory_arc), and write the JSON + MD reports to the OUT paths."
    )

    cmd = [
        claude_bin,
        "-p",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
        "--allowedTools",
        _ALLOWED_TOOLS,
        "--output-format",
        "json",
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
        "tool": "review_tier2",
        "version": VERSION,
        "phase": "narrative_review",
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
# Stub-report writer (degrades gracefully on missing deps / missing spec)
# ---------------------------------------------------------------------------


def write_stub_reports(
    out_json_path: Path,
    out_md_path: Path,
    draft_dir: Path,
    note: str,
) -> None:
    """Write minimal advisory reports when Tier 2 cannot run end-to-end
    (missing claude, missing spec, LLM error). Always rc=0 so the
    cascade still completes. Mirrors visual_qa.py's stub-report pattern
    + the M4a portability posture."""
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
        "# Tier 2 review report\n\n"
        f"Draft: `{draft_dir}`\n\n"
        f"_{note}_\n\n"
        "No findings. Tier 2 is advisory; the cascade proceeded with rc=0.\n"
    )
    out_md_path.write_text(md)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def run_tier2(
    draft_dir: Path,
    *,
    quiet: bool = False,
    claude_bin: str = "claude",
    model: str = DEFAULT_MODEL,
) -> int:
    """Run the Tier-2 review end-to-end. Always returns 0 (advisory).

    On any failure path (missing claude, missing spec, LLM error),
    writes a stub report explaining what happened, prints a single-line
    stderr summary, and returns 0.
    """
    audit_dir = draft_dir / "audit"
    out_json = audit_dir / "review_tier2.json"
    out_md = audit_dir / "review_tier2.md"

    # --- 1. Probe toolchain ---
    status = probe_toolchain(claude_bin)
    if not status.ok:
        write_stub_reports(
            out_json,
            out_md,
            draft_dir,
            note=f"Tier 2 toolchain incomplete (missing: "
            f"{', '.join(status.missing())}); install Claude Code CLI "
            f"to enable narrative-light review.",
        )
        if not quiet:
            print(
                f"  review-tier2: skipped — missing dependencies: {', '.join(status.missing())}",
                file=sys.stderr,
            )
        return 0

    # --- 2. Locate slide_spec.json + the narrative artifacts ---
    slide_spec_path = draft_dir / "working" / "slide_spec.json"
    if not slide_spec_path.is_file():
        write_stub_reports(
            out_json,
            out_md,
            draft_dir,
            note=f"slide_spec.json not found at {slide_spec_path} — nothing to review.",
        )
        if not quiet:
            print(
                f"  review-tier2: skipped — no slide_spec.json at {slide_spec_path}",
                file=sys.stderr,
            )
        return 0

    # Optional inputs — pass the paths even if absent; the system
    # prompt's escape-hatch tells the model to skip the affected class.
    throughline_path = draft_dir / "narrative" / "00_throughline.md"
    substories_path = draft_dir / "narrative" / "02_substories.md"
    quant_grounding_path = draft_dir / "audit" / "quantitative_grounding.json"

    # --- 3. Vision pass (claude -p Haiku) ---
    diag = invoke_tier2_review(
        draft_dir=draft_dir,
        slide_spec_path=slide_spec_path,
        throughline_path=throughline_path,
        substories_path=substories_path,
        quant_grounding_path=quant_grounding_path,
        out_json_path=out_json,
        out_md_path=out_md,
        claude_bin=status.claude,
        model=model,
    )

    if diag["exit_status"] != 0 or not diag["output_present"]:
        # The Tier-2 call failed — write a stub explaining the LLM
        # failure. Cascade continues regardless.
        note = (
            f"claude -p Tier-2 call failed (rc={diag['exit_status']}, "
            f"output_present={diag['output_present']}). "
            f"stderr tail: {diag['stderr_tail'][:200]}"
        )
        write_stub_reports(out_json, out_md, draft_dir, note=note)
        if not quiet:
            print(
                f"  review-tier2: failed (rc={diag['exit_status']}); see {out_md}", file=sys.stderr
            )
        return 0

    if not quiet:
        try:
            payload = json.loads(out_json.read_text())
            n = len(payload.get("findings", []))
            n_reviewed = payload.get("n_slides_reviewed", 0)
            if n == 0:
                print(
                    f"  review-tier2: no findings across {n_reviewed} "
                    f"slide(s) (${diag['cost_usd']:.4f})",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  review-tier2: {n} finding(s) across {n_reviewed} "
                    f"slide(s) — see {out_md} (${diag['cost_usd']:.4f})",
                    file=sys.stderr,
                )
        except (json.JSONDecodeError, OSError):
            print(f"  review-tier2: completed (rc=0); see {out_md}", file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="review_tier2",
        description="Tier 2 narrative-light review (advisory; v0.4 M4b). "
        "Haiku-pinned; 4 detection classes (register_drift, "
        "qa_softball, unbacked_quantitative, substory_arc); "
        "always advisory (cascade never short-circuits on "
        "Tier-2 findings).",
    )
    p.add_argument("draft_dir", help="v0.3.1+ draft directory (talks/draft_N/).")
    p.add_argument("--quiet", action="store_true", help="Suppress the stderr summary line.")
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model for the Tier-2 review (default: {DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--claude-bin", default="claude", help="Path to the claude CLI (default: claude on PATH)."
    )
    args = p.parse_args(argv)

    draft = Path(args.draft_dir)
    return run_tier2(
        draft,
        quiet=args.quiet,
        claude_bin=args.claude_bin,
        model=args.model,
    )


if __name__ == "__main__":
    sys.exit(main())
