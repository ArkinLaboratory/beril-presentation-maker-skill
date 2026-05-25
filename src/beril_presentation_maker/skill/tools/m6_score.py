#!/usr/bin/env python3
"""m6_score.py — M6 A/B cut-over scoring script.

Per V0_4_ARCHITECTURE §15 + M6_PUNCH_LIST.md Tier A. Reads 4 draft
audit dirs (2 projects × 2 pipelines) and emits a comparison Markdown
applying the ≥4/6 advisory decision rule (D-065 + D-066).

Per D-067, this script reads existing per-stage audit JSONs +
`runs/run-N/summary.json` files — no centralized state.json is
required. The orchestrator's `finalize_run.py` EXIT trap (and the
existing v0.3 audit-file conventions) already emit everything we
need.

Six metrics (metric 7 dropped per D-065):

  1. Wall-clock           — sum `total_elapsed_seconds` across all
                            runs in the draft's audit/runs/run-N/
                            summary.json files (lower is better)
  2. Token cost           — sum `total_cost_usd` likewise
  3. Adversarial findings — `audit/adversarial_review.json`
                            `summary.total_findings` (lower is better);
                            fall back to `audit/review_cascade.json`
                            tiers[2].findings count
  4. Validator failures   — `audit/presentation_validation.json`
                            count of P-validators where status == 'fail'
                            (the count, not the violation count;
                            violation counts vary by validator design)
  5. Arc coherence        — Adam-subjective (1–5 Likert); read from
                            a user-supplied JSON file via
                            --subjective-scores, OR rendered as
                            "REVIEW REQUIRED" if not supplied
  6. Image budget         — `audit/image_provenance.json` cumulative
                            image cost; reported as USD spent + count;
                            "tie" if both pipelines produced 0 images

Decision rule (advisory per D-066):
  - v0.4 wins if it dominates v0.3 on ≥4 of 6 metrics on the target
    project (ibd_phage_targeting) AND wall-clock ≥40% reduction on
    at least one project.
  - "Dominates" on lower-is-better metrics: v0.4 < v0.3 by more
    than the tie band (default 5%).
  - Adam-veto is final regardless (Tier D).

CLI:

    python3 m6_score.py \\
        --v0_3-target <audit_dir> --v0_4-target <audit_dir> \\
        --v0_3-sanity <audit_dir> --v0_4-sanity <audit_dir> \\
        [--subjective-scores <path/to/scores.json>] \\
        [--out <path/to/m6_score_report.md>] \\
        [--tie-band-pct 5]

Subjective scores JSON shape:
    {
      "target": {"v0_3": 3, "v0_4": 4, "comment": "..."},
      "sanity": {"v0_3": 2, "v0_4": 3, "comment": "..."}
    }

Exit codes:
    0   report rendered (regardless of A/B outcome)
    1   any audit dir missing or unreadable
    2   metric-extraction error (one of the audit JSONs malformed)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "m6-score.v1"
DEFAULT_TIE_BAND_PCT = 5.0


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

@dataclass
class RunSummary:
    """Aggregated stats across all runs/run-N/summary.json files in
    one draft's audit dir."""
    n_runs: int = 0
    total_cost_usd: float = 0.0
    total_elapsed_seconds: float = 0.0  # sum of per-stage elapsed (kept for ref)
    wall_clock_seconds: float = 0.0     # (latest_finished - earliest_started)
    earliest_started: Optional[str] = None
    latest_finished: Optional[str] = None
    exit_codes: list[int] = field(default_factory=list)


def _parse_iso_to_seconds(ts: str) -> Optional[float]:
    """Parse an ISO-8601 UTC timestamp like `2026-05-25T11:16:59Z` to
    POSIX seconds. Returns None on parse failure. Handles trailing 'Z'."""
    from datetime import datetime, timezone
    try:
        # Python 3.14's fromisoformat handles trailing Z natively, but
        # be defensive for older formats.
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.fromisoformat(s).replace(
            tzinfo=datetime.fromisoformat(s).tzinfo or timezone.utc
        ).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def aggregate_runs(audit_dir: Path) -> RunSummary:
    """Sum cost + elapsed across all runs/run-N/summary.json files.

    A draft may have multiple runs (initial + resume-from-stage
    re-runs). The A/B comparison sums everything — both pipelines
    get the same opportunity to iterate.

    Two elapsed measures are captured:

    - `wall_clock_seconds` (load-bearing for M6 metric 1): the
      orchestrator-observed duration from earliest_started to
      latest_finished across all runs. This is what the user
      experiences and what V0_4_ARCHITECTURE §15 metric 1 means
      ("first-byte to last-byte"). It correctly attributes v0.4's
      parallel-compose architecture as a wall-clock win — when 4
      substories compose in parallel for 10min each, this measure
      adds 10min.

    - `total_elapsed_seconds` (kept for reference): the sum of per-
      stage `elapsed_seconds` values from finalize_run.py's
      stage-metadata aggregation. Double-counts parallel work; not
      used by the M6 decision rule. Useful for "where did the
      pipeline spend its compute" diagnostics.

    M6 Tier A.1 (2026-05-25): added wall_clock_seconds + parsing
    logic. Tier-B clean run on ibd_phage_targeting surfaced the
    mismatch: wrapper wall-clock was 85min v0.3 vs 72min v0.4
    (-15%), while sum(stage-elapsed) was 65.5min vs 66.4min
    (+1.5%, false tie). The wrapper is correct.
    """
    runs_dir = audit_dir / "runs"
    out = RunSummary()
    if not runs_dir.is_dir():
        return out
    for p in sorted(runs_dir.glob("run-*/summary.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.n_runs += 1
        out.total_cost_usd += float(d.get("total_cost_usd", 0.0))
        out.total_elapsed_seconds += float(d.get("total_elapsed_seconds", 0.0))
        started = d.get("started_at")
        finished = d.get("finished_at")
        if started and (out.earliest_started is None
                        or started < out.earliest_started):
            out.earliest_started = started
        if finished and (out.latest_finished is None
                         or finished > out.latest_finished):
            out.latest_finished = finished
        ec = d.get("exit_code")
        if ec is not None:
            out.exit_codes.append(int(ec))

    # Compute wall_clock_seconds from the orchestrator-level
    # timestamp delta. Falls back to total_elapsed_seconds if either
    # timestamp is missing or unparseable (defensive — the M6 fixture
    # expectations include malformed-JSON skipping).
    if out.earliest_started and out.latest_finished:
        start_s = _parse_iso_to_seconds(out.earliest_started)
        end_s = _parse_iso_to_seconds(out.latest_finished)
        if start_s is not None and end_s is not None and end_s >= start_s:
            out.wall_clock_seconds = end_s - start_s
        else:
            out.wall_clock_seconds = out.total_elapsed_seconds
    else:
        out.wall_clock_seconds = out.total_elapsed_seconds
    return out


def count_adversarial_findings(audit_dir: Path) -> Optional[int]:
    """Read `audit/adversarial_review.json`'s `summary.total_findings`.

    Three failure-distinguishing branches (M6 Tier C.1, live-discovered
    on fdm draft_2 2026-05-25: beril-adversarial's LLM emitted
    invalid JSON — unescaped " inside string values — so the file
    exists but doesn't parse):

    1. adversarial_review.json parses cleanly → return its count.
    2. adversarial_review.json is PRESENT but malformed → return None
       ("couldn't determine" → metric shows n/a, NOT a misleading 0).
       The file's existence signals adversarial WAS run; the parse
       failure is upstream (beril-adversarial bug), not a missing
       capability.
    3. adversarial_review.json is ABSENT → fall back to
       `review_cascade.json` tiers[2] (the cascade's Tier-3 adversarial
       wrapper, which may have run during the cascade); return None
       if that's also absent or malformed.

    This distinguishes "adversarial wasn't run" (legitimate cascade
    fallback) from "adversarial ran but produced unparseable output"
    (data quality issue worth surfacing).
    """
    advers = audit_dir / "adversarial_review.json"
    if advers.is_file():
        try:
            d = json.loads(advers.read_text(encoding="utf-8"))
            return int(d.get("summary", {}).get("total_findings", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            # File exists but malformed — adversarial ran but emitted
            # bad JSON (upstream beril-adversarial issue). Don't fall
            # through to cascade (would conflate with "adversarial
            # not run"); return None so metric shows n/a.
            return None
        except OSError:
            # I/O error reading the file — distinct from JSON parse;
            # treat as absent and try cascade fallback.
            pass
    # adversarial_review.json absent: fall back to cascade tier 3
    cascade = audit_dir / "review_cascade.json"
    if cascade.is_file():
        try:
            d = json.loads(cascade.read_text(encoding="utf-8"))
            tiers = d.get("tiers", [])
            if len(tiers) >= 3:
                return len(tiers[2].get("findings", []) or [])
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
    return None


def count_validator_failures(audit_dir: Path) -> Optional[int]:
    """Read `audit/presentation_validation.json` and count validators
    with status == 'fail'. (Not the count of violations — different
    validators emit different violation cardinalities. The cleaner
    'how many checks failed' is the count of failing validators.)
    Returns None if file absent/unreadable."""
    p = audit_dir / "presentation_validation.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        validators = d.get("validators", [])
        return sum(1 for v in validators if v.get("status") == "fail")
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


@dataclass
class ImageBudget:
    n_images: int = 0
    total_cost_usd: float = 0.0


def aggregate_image_budget(audit_dir: Path) -> ImageBudget:
    """Sum cost + count across all entries in image_provenance.json.
    Returns ImageBudget(0, 0.0) if file absent (image-gen disabled
    for the run)."""
    p = audit_dir / "image_provenance.json"
    out = ImageBudget()
    if not p.is_file():
        return out
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        entries = d.get("entries", [])
        out.n_images = len(entries)
        out.total_cost_usd = sum(float(e.get("cost_usd", 0.0)) for e in entries)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return out


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    """One metric's value across both pipelines + winner."""
    name: str
    v0_3: Optional[float]
    v0_4: Optional[float]
    unit: str
    winner: str             # "v0_3" | "v0_4" | "tie" | "n/a"
    delta_pct: Optional[float] = None
    note: Optional[str] = None


def compare_lower_is_better(
    v0_3: Optional[float],
    v0_4: Optional[float],
    *,
    tie_band_pct: float = DEFAULT_TIE_BAND_PCT,
) -> tuple[str, Optional[float]]:
    """Return (winner, delta_pct) where winner is 'v0_3' | 'v0_4' |
    'tie' | 'n/a'. delta_pct is (v0_4 - v0_3) / v0_3 * 100 (negative
    means v0_4 is lower = better). Within ±tie_band_pct → 'tie'."""
    if v0_3 is None or v0_4 is None:
        return "n/a", None
    if v0_3 == 0:
        if v0_4 == 0:
            return "tie", 0.0
        # v0_3 baseline is zero, v0_4 added cost — v0_3 wins
        return "v0_3", None
    delta_pct = (v0_4 - v0_3) / v0_3 * 100.0
    if abs(delta_pct) <= tie_band_pct:
        return "tie", delta_pct
    if delta_pct < 0:  # v0_4 is lower → v0_4 wins
        return "v0_4", delta_pct
    return "v0_3", delta_pct


def compare_subjective_higher_is_better(
    v0_3: Optional[float],
    v0_4: Optional[float],
) -> tuple[str, Optional[float]]:
    """For Adam-subjective Likert metric 5 (higher = better)."""
    if v0_3 is None or v0_4 is None:
        return "n/a", None
    if v0_3 == v0_4:
        return "tie", 0.0
    if v0_4 > v0_3:
        return "v0_4", float(v0_4 - v0_3)
    return "v0_3", float(v0_4 - v0_3)


# ---------------------------------------------------------------------------
# Per-project scoring
# ---------------------------------------------------------------------------

@dataclass
class ProjectScore:
    """All 6 metrics for one project (v0.3 vs v0.4)."""
    project_label: str
    metrics: list[MetricResult] = field(default_factory=list)

    @property
    def v0_4_wins(self) -> int:
        return sum(1 for m in self.metrics if m.winner == "v0_4")

    @property
    def v0_3_wins(self) -> int:
        return sum(1 for m in self.metrics if m.winner == "v0_3")

    @property
    def ties(self) -> int:
        return sum(1 for m in self.metrics if m.winner == "tie")

    @property
    def n_a(self) -> int:
        return sum(1 for m in self.metrics if m.winner == "n/a")


def score_project(
    project_label: str,
    v0_3_audit: Path,
    v0_4_audit: Path,
    *,
    subjective: Optional[dict] = None,
    tie_band_pct: float = DEFAULT_TIE_BAND_PCT,
) -> ProjectScore:
    """Compute all 6 metrics for one project comparison."""
    v3_runs = aggregate_runs(v0_3_audit)
    v4_runs = aggregate_runs(v0_4_audit)

    score = ProjectScore(project_label=project_label)

    # Metric 1: wall-clock (lower is better). Per M6 Tier A.1, this
    # is the orchestrator-observed (finished_at - started_at) duration,
    # NOT sum(per-stage elapsed) — the latter double-counts parallel
    # work and would erase v0.4's architectural win.
    winner, delta = compare_lower_is_better(
        v3_runs.wall_clock_seconds, v4_runs.wall_clock_seconds,
        tie_band_pct=tie_band_pct)
    score.metrics.append(MetricResult(
        name="1. wall-clock",
        v0_3=v3_runs.wall_clock_seconds,
        v0_4=v4_runs.wall_clock_seconds,
        unit="s",
        winner=winner, delta_pct=delta,
    ))

    # Metric 2: token cost (lower is better)
    winner, delta = compare_lower_is_better(
        v3_runs.total_cost_usd, v4_runs.total_cost_usd,
        tie_band_pct=tie_band_pct)
    score.metrics.append(MetricResult(
        name="2. token cost",
        v0_3=v3_runs.total_cost_usd,
        v0_4=v4_runs.total_cost_usd,
        unit="USD",
        winner=winner, delta_pct=delta,
    ))

    # Metric 3: adversarial findings count (lower is better)
    v3_adv = count_adversarial_findings(v0_3_audit)
    v4_adv = count_adversarial_findings(v0_4_audit)
    winner, delta = compare_lower_is_better(
        v3_adv if v3_adv is None else float(v3_adv),
        v4_adv if v4_adv is None else float(v4_adv),
        tie_band_pct=tie_band_pct)
    score.metrics.append(MetricResult(
        name="3. adversarial findings",
        v0_3=v3_adv, v0_4=v4_adv, unit="findings",
        winner=winner, delta_pct=delta,
    ))

    # Metric 4: validator failures at Tier 1 (lower is better)
    v3_vf = count_validator_failures(v0_3_audit)
    v4_vf = count_validator_failures(v0_4_audit)
    winner, delta = compare_lower_is_better(
        v3_vf if v3_vf is None else float(v3_vf),
        v4_vf if v4_vf is None else float(v4_vf),
        tie_band_pct=tie_band_pct)
    score.metrics.append(MetricResult(
        name="4. validator failures",
        v0_3=v3_vf, v0_4=v4_vf, unit="failing-validators",
        winner=winner, delta_pct=delta,
    ))

    # Metric 5: arc coherence (Adam-subjective; higher is better)
    sub_v3 = subjective.get("v0_3") if subjective else None
    sub_v4 = subjective.get("v0_4") if subjective else None
    winner, delta = compare_subjective_higher_is_better(sub_v3, sub_v4)
    note = None
    if subjective is None:
        note = "REVIEW REQUIRED — supply via --subjective-scores"
    elif subjective.get("comment"):
        note = subjective["comment"]
    score.metrics.append(MetricResult(
        name="5. arc coherence (Adam)",
        v0_3=sub_v3, v0_4=sub_v4, unit="Likert 1-5",
        winner=winner, delta_pct=delta, note=note,
    ))

    # Metric 6: image budget (lower cost is better; treat as
    # 'tie' if both produced 0 images)
    v3_img = aggregate_image_budget(v0_3_audit)
    v4_img = aggregate_image_budget(v0_4_audit)
    if v3_img.n_images == 0 and v4_img.n_images == 0:
        winner_img, delta_img = "tie", 0.0
    else:
        winner_img, delta_img = compare_lower_is_better(
            v3_img.total_cost_usd, v4_img.total_cost_usd,
            tie_band_pct=tie_band_pct)
    score.metrics.append(MetricResult(
        name="6. image budget",
        v0_3=v3_img.total_cost_usd,
        v0_4=v4_img.total_cost_usd,
        unit=f"USD ({v3_img.n_images} vs {v4_img.n_images} images)",
        winner=winner_img, delta_pct=delta_img,
        note=("both 0 images — tie" if (v3_img.n_images == 0
                                         and v4_img.n_images == 0) else None),
    ))

    return score


# ---------------------------------------------------------------------------
# Decision rule (D-065 + D-066)
# ---------------------------------------------------------------------------

@dataclass
class DecisionResult:
    target_v0_4_wins: int = 0
    target_n_metrics: int = 0
    sanity_v0_4_wins: int = 0
    sanity_n_metrics: int = 0
    wall_clock_40pct_met: bool = False  # at least one project
    rule_passes: bool = False           # ≥4/6 on TARGET + wall-clock ≥40% on any
    decision_text: str = ""


def evaluate_decision(
    target: ProjectScore,
    sanity: Optional[ProjectScore] = None,
) -> DecisionResult:
    """Apply the D-065 / D-066 advisory decision rule:
      - v0.4 must win ≥4 of 6 on the TARGET project.
      - wall-clock primary gate: ≥40% reduction on at least one
        project (target OR sanity).
    Returns the mechanical evaluation; Adam-veto (D-066) overrides
    this at Tier D.
    """
    res = DecisionResult()
    res.target_v0_4_wins = target.v0_4_wins
    res.target_n_metrics = len([m for m in target.metrics if m.winner != "n/a"])

    if sanity is not None:
        res.sanity_v0_4_wins = sanity.v0_4_wins
        res.sanity_n_metrics = len(
            [m for m in sanity.metrics if m.winner != "n/a"])

    # Wall-clock 40% reduction check (any project)
    projects = [target] + ([sanity] if sanity else [])
    for p in projects:
        wall_metric = next(
            (m for m in p.metrics if m.name.startswith("1.")), None)
        if (wall_metric and wall_metric.delta_pct is not None
                and wall_metric.delta_pct <= -40.0):
            res.wall_clock_40pct_met = True
            break

    rule = (res.target_v0_4_wins >= 4 and res.wall_clock_40pct_met)
    res.rule_passes = rule
    if rule:
        res.decision_text = (
            f"PASS (mechanical): v0.4 wins {res.target_v0_4_wins}/"
            f"{res.target_n_metrics} on target + wall-clock ≥40% met."
        )
    else:
        reasons = []
        if res.target_v0_4_wins < 4:
            reasons.append(
                f"v0.4 wins {res.target_v0_4_wins}/{res.target_n_metrics} "
                f"on target (need ≥4)")
        if not res.wall_clock_40pct_met:
            reasons.append("wall-clock ≥40% reduction not met on any project")
        res.decision_text = "FAIL (mechanical): " + "; ".join(reasons)
    return res


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _fmt_value(v: Optional[float], unit: str) -> str:
    if v is None:
        return "—"
    if unit == "s":
        return f"{v:.0f}s ({v/60:.1f}m)" if v >= 60 else f"{v:.1f}s"
    if unit == "USD" or unit.startswith("USD"):
        return f"${v:.4f}"
    if unit == "findings" or unit == "failing-validators":
        return f"{int(v)}"
    if unit.startswith("Likert"):
        return f"{v:.0f}/5"
    return f"{v}"


def _fmt_delta(delta_pct: Optional[float], unit: str) -> str:
    if delta_pct is None:
        return "—"
    if unit.startswith("Likert"):
        return f"{delta_pct:+.0f}"
    return f"{delta_pct:+.1f}%"


def _fmt_winner(winner: str) -> str:
    return {
        "v0_4": "✓ v0.4",
        "v0_3": "✗ v0.3",
        "tie": "~ tie",
        "n/a": "—",
    }.get(winner, winner)


def render_report(
    target: ProjectScore,
    sanity: Optional[ProjectScore],
    decision: DecisionResult,
    *,
    tie_band_pct: float = DEFAULT_TIE_BAND_PCT,
) -> str:
    """Render the comparison Markdown."""
    lines: list[str] = []
    lines.append(f"# M6 A/B comparison report")
    lines.append("")
    lines.append(f"**Schema:** `{SCHEMA_VERSION}`")
    lines.append(f"**Tie band:** ±{tie_band_pct:.0f}% (per metric)")
    lines.append(f"**Decision rule:** ≥4/6 on target + ≥40% wall-clock"
                 " reduction on any project (D-065 + D-066 advisory)")
    lines.append("")

    for label, score in (("Target", target),
                          ("Sanity-check", sanity) if sanity else (None, None)):
        if label is None:
            continue
        lines.append(f"## {label}: {score.project_label}")
        lines.append("")
        lines.append("| Metric | v0.3 | v0.4 | Δ | Winner | Note |")
        lines.append("|---|---|---|---|---|---|")
        for m in score.metrics:
            note = (m.note or "")
            lines.append(
                f"| {m.name} | {_fmt_value(m.v0_3, m.unit)} | "
                f"{_fmt_value(m.v0_4, m.unit)} | "
                f"{_fmt_delta(m.delta_pct, m.unit)} | "
                f"{_fmt_winner(m.winner)} | {note} |"
            )
        lines.append("")
        lines.append(
            f"**Sub-total:** v0.4 wins **{score.v0_4_wins}** / "
            f"v0.3 wins **{score.v0_3_wins}** / ties **{score.ties}** / "
            f"n/a **{score.n_a}**"
        )
        lines.append("")

    lines.append("## Decision (mechanical, per D-065 rule)")
    lines.append("")
    lines.append(f"- v0.4 wins on target: {decision.target_v0_4_wins} / "
                 f"{decision.target_n_metrics}")
    if sanity:
        lines.append(f"- v0.4 wins on sanity: {decision.sanity_v0_4_wins} / "
                     f"{decision.sanity_n_metrics}")
    lines.append(f"- Wall-clock ≥40% reduction met: "
                 f"{'YES' if decision.wall_clock_40pct_met else 'NO'}")
    lines.append("")
    lines.append(f"**Mechanical result:** {decision.decision_text}")
    lines.append("")
    lines.append("## Adam-veto (D-066 — final)")
    lines.append("")
    lines.append("- [ ] Ship v0.4 as default")
    lines.append("- [ ] Don't ship; keep v0.3 default + v0.4 opt-in")
    lines.append("- [ ] Ship-but-flag (default + experimental warning)")
    lines.append("")
    lines.append(
        "_Adam reads both deck pairs back-to-back, scores metric 5, "
        "casts ship / don't ship / ship-but-flag. Veto overrides the "
        "mechanical rule in either direction (per D-066)._")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="m6_score",
        description="M6 A/B cut-over scoring (V0_4_ARCHITECTURE §15; "
                    "D-065 / D-066 / D-067).")
    p.add_argument("--v0_3-target", required=True, type=Path,
                   help="v0.3 audit dir for the TARGET project "
                        "(per D-041, this is the must-dominate project).")
    p.add_argument("--v0_4-target", required=True, type=Path,
                   help="v0.4 audit dir for the TARGET project.")
    p.add_argument("--v0_3-sanity", type=Path, default=None,
                   help="v0.3 audit dir for the SANITY-check project "
                        "(per D-041, optional second data point).")
    p.add_argument("--v0_4-sanity", type=Path, default=None,
                   help="v0.4 audit dir for the SANITY-check project.")
    p.add_argument("--subjective-scores", type=Path, default=None,
                   help="JSON with metric-5 (arc coherence) scores. "
                        "Shape: {\"target\":{\"v0_3\":N,\"v0_4\":N,\"comment\":\"\"},"
                        "\"sanity\":{\"v0_3\":N,\"v0_4\":N,\"comment\":\"\"}}.")
    p.add_argument("--out", type=Path, default=None,
                   help="Output Markdown path. Default: stdout.")
    p.add_argument("--tie-band-pct", type=float, default=DEFAULT_TIE_BAND_PCT,
                   help=f"Per-metric tie band (default: "
                        f"{DEFAULT_TIE_BAND_PCT}%%).")
    p.add_argument("--target-label", default=None,
                   help="Override the TARGET project label "
                        "(default: derived from --v0_4-target path).")
    p.add_argument("--sanity-label", default=None,
                   help="Override the SANITY project label.")
    args = p.parse_args(argv)

    # Validate audit dirs
    for path_arg in ("v0_3-target", "v0_4-target", "v0_3-sanity", "v0_4-sanity"):
        attr = path_arg.replace("-", "_")
        path = getattr(args, attr)
        if path is None:
            continue
        if not path.is_dir():
            print(f"error: {path_arg} dir does not exist: {path}",
                  file=sys.stderr)
            return 1

    # Sanity arg-pairing check
    if (args.v0_3_sanity is None) != (args.v0_4_sanity is None):
        print("error: --v0_3-sanity and --v0_4-sanity must be supplied "
              "together (or both omitted)", file=sys.stderr)
        return 1

    # Subjective scores (optional)
    subjective: dict = {}
    if args.subjective_scores is not None:
        if not args.subjective_scores.is_file():
            print(f"error: --subjective-scores file not found: "
                  f"{args.subjective_scores}", file=sys.stderr)
            return 1
        try:
            subjective = json.loads(
                args.subjective_scores.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: --subjective-scores parse failed: {e}",
                  file=sys.stderr)
            return 2

    # Derive labels if not overridden
    target_label = (args.target_label
                    or _label_from_audit_path(args.v0_4_target))
    sanity_label = (args.sanity_label
                    or (_label_from_audit_path(args.v0_4_sanity)
                        if args.v0_4_sanity else None))

    # Score each project
    target = score_project(
        target_label, args.v0_3_target, args.v0_4_target,
        subjective=subjective.get("target"),
        tie_band_pct=args.tie_band_pct,
    )
    sanity = None
    if args.v0_3_sanity is not None:
        sanity = score_project(
            sanity_label, args.v0_3_sanity, args.v0_4_sanity,
            subjective=subjective.get("sanity"),
            tie_band_pct=args.tie_band_pct,
        )

    decision = evaluate_decision(target, sanity)

    report = render_report(target, sanity, decision,
                            tie_band_pct=args.tie_band_pct)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(report)

    return 0


def _label_from_audit_path(audit_dir: Path) -> str:
    """Derive a human-friendly label from an audit dir path like
    `.../projects/<project>/talks/<draft>/audit` →
    `<project>/<draft>`."""
    parts = audit_dir.parts
    try:
        proj_idx = parts.index("projects")
        return "/".join(parts[proj_idx + 1: proj_idx + 4])
    except ValueError:
        return audit_dir.parent.name


if __name__ == "__main__":
    raise SystemExit(main())
