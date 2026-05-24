#!/usr/bin/env python3
"""review_cascade.py — tiered review cascade orchestrator (v0.4 M4b).

V0_4_ARCHITECTURE.md §8 (Phase 4 — Tiered review cascade, fail-fast)
+ §16 M4b + M4b_PUNCH_LIST.md. Wraps three existing pieces under a
single fail-fast contract:

  Tier 1 — deterministic + visual-QA aggregation (~$0.00 — $0.05).
           Aggregates validate_presentation (P1–P10),
           check_quantitative_grounding.py, check_no_artifact_refs.py,
           reconcile_deck.py, and audit/visual_qa.json (when present
           per the M4a opt-in posture, D-050 → DQ2 ship as (b)).
           Tier-1 P0 (P3 numeric / P4 citation / P5 brand) SHORT-
           CIRCUITS Tiers 2+3.

  Tier 2 — Haiku narrative-light (~$0.05). Four detection classes per
           §8.1 (register_drift, qa_softball, unbacked_quantitative,
           substory_arc). ALWAYS ADVISORY per DQ4 — never gates Tier 3.

  Tier 3 — canonical adversarial (~$0.50–$1.50). Wraps
           `beril-adversarial review --type presentation` (the same
           call stage_adversarial_review makes today). Runs unless
           Tier-1 short-circuited OR the operator passed
           --no-adversarial. Produces the same audit/adversarial_review.json
           the revise loop already consumes — cascade integrates, doesn't
           replace.

This is an ADVISORY orchestrator (rc=0 always, like reconcile_deck.py +
visual_qa.py). Findings inform the revise loop / hand-edit; per-tier
short-circuit decisions affect WHAT runs, never what exits the
orchestrator non-zero.

DQ resolutions (Adam 2026-05-24; land as D-054..D-057 in Tier F):
  DQ1 → auto-run by default; opt out via `--no-review-cascade` on the
        orchestrator.
  DQ2 → cascade reads audit/visual_qa.json if present; never invokes
        visual_qa.py itself. Operator opts in to visual-QA via the
        existing --visual-qa flag.
  DQ3 → Tier 2 ships with the §8.1 candidate-four detection classes
        as v1; empirical calibration is a one-off probe + ship-then-
        iterate.
  DQ4 → operator-gated short-circuit: Tier-1 P0 skips Tier 2+3;
        Tier-2 findings are always advisory (never gate Tier 3);
        Tier 3 runs unless --no-adversarial.

CLI:
    python3 review_cascade.py <draft_dir>
                              [--no-tier2] [--no-tier3]
                              [--quiet]

Exit code: always 0 (advisory). The cascade JSON's
short_circuited_at field tells the orchestrator whether to skip the
standalone stage_adversarial_review.

Layout: v0.3.1+ 4-zone draft directory. Reads
<draft_dir>/working/slide_spec.json and the existing audit/ artifacts
(quantitative_grounding.json, no_artifact_refs.json,
deck_reconciliation.json, visual_qa.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "review-cascade.v1"
VERSION = "0.4.0-m4b-tierA"

_THIS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Cascade schema
# ---------------------------------------------------------------------------
#
# Tier status values:
#   "pass"              — tier ran and emitted no P0 findings
#   "advisory"          — tier ran; emitted findings; NONE were P0
#                         (Tier 2 always lands here per DQ4)
#   "fail"              — tier ran and emitted at least one P0 finding
#                         (Tier 1 only; Tier 2 cannot fail; Tier 3 may
#                         emit central_objection but the cascade
#                         classifies it as advisory — revise loop owns
#                         the response)
#   "skipped"           — tier did not run (--no-tierN flag, missing
#                         dependency, OR earlier tier short-circuited)
#   "not-implemented"   — Tier A scaffolding placeholder; B/C/D fill in
#   "error"             — tier crashed; cascade still completes with
#                         rc=0 but the tier is marked error for the
#                         operator

TIER_STATUSES = (
    "pass", "advisory", "fail", "skipped", "not-implemented", "error",
)


@dataclass
class CascadeFinding:
    """A single finding from any tier. Tier-specific detail goes in
    `evidence` (free-form dict for the cascade JSON consumer)."""
    tier: str            # "tier1" | "tier2" | "tier3"
    kind: str            # validator id ("P3"), check name, or class
    severity: str        # "P0" | "P1" | "P2" | "advisory"
    slide_id: int | None
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TierResult:
    """One tier's outcome in the cascade."""
    name: str            # "tier1" | "tier2" | "tier3"
    status: str          # see TIER_STATUSES
    findings: list[CascadeFinding] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_sec: float = 0.0
    note: str = ""       # free-form (e.g., "skipped — Tier 1 short-circuited")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "cost_usd": self.cost_usd,
            "duration_sec": self.duration_sec,
            "note": self.note,
        }

    @property
    def has_p0(self) -> bool:
        return any(f.severity == "P0" for f in self.findings)


@dataclass
class CascadeReport:
    """The full cascade outcome."""
    draft_dir: str
    tiers: list[TierResult]
    short_circuited_at: str | None = None
    note: str = ""

    @property
    def total_cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.tiers)

    @property
    def total_duration_sec(self) -> float:
        return sum(t.duration_sec for t in self.tiers)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "draft_dir": self.draft_dir,
            "tiers": [t.to_dict() for t in self.tiers],
            "short_circuited_at": self.short_circuited_at,
            "total_cost_usd": self.total_cost_usd,
            "total_duration_sec": self.total_duration_sec,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Per-tier dispatchers (Tier A: scaffolding only; B/C/D fill in)
# ---------------------------------------------------------------------------

def run_tier1(draft_dir: Path) -> TierResult:
    """Tier 1 — deterministic + visual-QA aggregation.

    M4b Tier A SCAFFOLDING: returns 'not-implemented'. Tier B fills in
    the aggregation logic (P1–P10 + the three advisory checkers + the
    opt-in visual-QA JSON).
    """
    return TierResult(
        name="tier1",
        status="not-implemented",
        note="Tier A scaffolding — Tier B will aggregate "
             "validate_presentation + check_* + visual_qa.json.",
    )


def run_tier2(draft_dir: Path) -> TierResult:
    """Tier 2 — Haiku narrative-light (4 detection classes).

    M4b Tier A SCAFFOLDING: returns 'not-implemented'. Tier C builds
    tools/review_tier2.py + prompts/review_tier2.v1.md.
    """
    return TierResult(
        name="tier2",
        status="not-implemented",
        note="Tier A scaffolding — Tier C will invoke claude-haiku-4-5 "
             "with the §8.1 candidate-four detection classes.",
    )


def run_tier3(draft_dir: Path) -> TierResult:
    """Tier 3 — canonical adversarial (wraps beril-adversarial).

    M4b Tier A SCAFFOLDING: returns 'not-implemented'. Tier D wraps
    the existing stage_adversarial_review invocation.
    """
    return TierResult(
        name="tier3",
        status="not-implemented",
        note="Tier A scaffolding — Tier D will wrap "
             "beril-adversarial review --type presentation.",
    )


# ---------------------------------------------------------------------------
# Cascade orchestrator
# ---------------------------------------------------------------------------

def run_cascade(
    draft_dir: Path,
    *,
    run_tier2_enabled: bool = True,
    run_tier3_enabled: bool = True,
) -> CascadeReport:
    """Run the cascade with operator-gated short-circuit semantics (DQ4).

    Order: Tier 1 → (if no Tier-1 P0) Tier 2 → (if Tier 2 ran) Tier 3.

    Short-circuit semantics:
      - Tier 1 emits a P0 → Tier 2 + Tier 3 SKIPPED (short_circuited_at
        = "tier1").
      - Tier 1 clears OR emits only advisory (P1/P2) → Tier 2 runs.
      - Tier 2 ALWAYS advisory per DQ4 — even if it emits findings,
        Tier 3 still runs (short_circuited_at stays null unless --no-
        tier3 was passed).
      - --no-tier2 / --no-tier3 flags skip the respective tier and mark
        it "skipped"; the next tier still runs.
    """
    tiers: list[TierResult] = []
    short_circuited_at: str | None = None

    # Tier 1
    t1 = run_tier1(draft_dir)
    tiers.append(t1)
    if t1.has_p0:
        short_circuited_at = "tier1"

    # Tier 2
    if short_circuited_at:
        tiers.append(TierResult(
            name="tier2", status="skipped",
            note=f"skipped — short-circuited at {short_circuited_at}",
        ))
    elif not run_tier2_enabled:
        tiers.append(TierResult(
            name="tier2", status="skipped",
            note="skipped — --no-tier2",
        ))
    else:
        t2 = run_tier2(draft_dir)
        tiers.append(t2)
        # DQ4: Tier 2 never short-circuits Tier 3. If t2 has 'findings'
        # they're always advisory; do NOT set short_circuited_at.

    # Tier 3
    if short_circuited_at:
        tiers.append(TierResult(
            name="tier3", status="skipped",
            note=f"skipped — short-circuited at {short_circuited_at}",
        ))
    elif not run_tier3_enabled:
        tiers.append(TierResult(
            name="tier3", status="skipped",
            note="skipped — --no-tier3",
        ))
    else:
        t3 = run_tier3(draft_dir)
        tiers.append(t3)

    return CascadeReport(
        draft_dir=str(draft_dir),
        tiers=tiers,
        short_circuited_at=short_circuited_at,
    )


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def render_md(report: CascadeReport) -> str:
    """Human-readable cascade report for audit/review_cascade.md."""
    lines = [
        "# Review cascade report",
        "",
        f"Draft: `{report.draft_dir}`",
        f"Total cost: ${report.total_cost_usd:.4f}  "
        f"·  duration: {report.total_duration_sec:.1f}s",
    ]
    if report.short_circuited_at:
        lines += [
            "",
            f"**Short-circuited at {report.short_circuited_at}** — "
            "later tiers skipped per DQ4 operator-gated semantics.",
        ]
    if report.note:
        lines += ["", f"_{report.note}_"]
    lines += [""]
    for tier in report.tiers:
        lines += [f"## {tier.name} — {tier.status}"]
        if tier.note:
            lines += ["", f"_{tier.note}_"]
        if tier.findings:
            lines += [
                "",
                f"**{len(tier.findings)} finding(s):**",
                "",
            ]
            for f in tier.findings:
                slide = f" [slide {f.slide_id}]" if f.slide_id is not None else ""
                lines += [
                    f"- **{f.severity}** {f.kind}{slide}: {f.detail}",
                ]
        if tier.cost_usd > 0 or tier.duration_sec > 0:
            lines += [
                "",
                f"_cost ${tier.cost_usd:.4f}  ·  {tier.duration_sec:.1f}s_",
            ]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: CascadeReport, audit_dir: Path) -> tuple[Path, Path]:
    """Write cascade JSON + MD to audit_dir. Returns (json_path, md_path)."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    json_path = audit_dir / "review_cascade.json"
    md_path = audit_dir / "review_cascade.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    md_path.write_text(render_md(report))
    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="review_cascade",
        description="Tiered review cascade orchestrator (advisory). "
                    "v0.4 M4b — wraps Tier 1 (deterministic + visual-QA), "
                    "Tier 2 (Haiku), Tier 3 (canonical adversarial) with "
                    "fail-fast short-circuit on Tier-1 P0 (DQ4).",
    )
    p.add_argument("draft_dir", help="v0.3.1+ draft directory (talks/draft_N/).")
    p.add_argument("--no-tier2", action="store_true",
                   help="Skip Tier 2 (Haiku narrative-light review).")
    p.add_argument("--no-tier3", action="store_true",
                   help="Skip Tier 3 (canonical adversarial). Use this when "
                        "the orchestrator has already run adversarial as a "
                        "separate stage; cascade Tier 3 wraps the same call.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the per-tier stderr summary.")
    args = p.parse_args(argv)

    draft_dir = Path(args.draft_dir)
    audit_dir = draft_dir / "audit"

    spec_path = draft_dir / "working" / "slide_spec.json"
    if not spec_path.is_file():
        # No spec → cascade is a no-op + stub report (mirrors visual_qa.py
        # + reconcile_deck.py degradation posture).
        report = CascadeReport(
            draft_dir=str(draft_dir),
            tiers=[
                TierResult(name="tier1", status="skipped",
                           note=f"slide_spec.json not found at {spec_path}"),
                TierResult(name="tier2", status="skipped",
                           note=f"slide_spec.json not found at {spec_path}"),
                TierResult(name="tier3", status="skipped",
                           note=f"slide_spec.json not found at {spec_path}"),
            ],
            note=f"slide_spec.json missing at {spec_path}; "
                 "cascade is a no-op.",
        )
        write_reports(report, audit_dir)
        if not args.quiet:
            print(f"  review-cascade: skipped — no slide_spec.json at "
                  f"{spec_path}", file=sys.stderr)
        return 0

    report = run_cascade(
        draft_dir,
        run_tier2_enabled=not args.no_tier2,
        run_tier3_enabled=not args.no_tier3,
    )
    json_path, md_path = write_reports(report, audit_dir)

    if not args.quiet:
        n_findings = sum(len(t.findings) for t in report.tiers)
        sc = (f", short-circuited at {report.short_circuited_at}"
              if report.short_circuited_at else "")
        print(
            f"  review-cascade: {n_findings} finding(s) across "
            f"{len(report.tiers)} tier(s) (${report.total_cost_usd:.4f}{sc}) "
            f"— see {md_path}",
            file=sys.stderr,
        )
        for tier in report.tiers:
            marker = "✓" if tier.status == "pass" else (
                "!" if tier.status == "fail" else "·"
            )
            print(f"    {marker} {tier.name}: {tier.status}"
                  + (f" ({len(tier.findings)} finding(s))" if tier.findings else ""),
                  file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
