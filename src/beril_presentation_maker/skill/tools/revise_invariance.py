#!/usr/bin/env python3
"""revise_invariance.py — revise-verb semantic-invariance post-check
(v0.4 M5a).

V0_4_ARCHITECTURE.md §13 + M5a_PUNCH_LIST.md Tier A. After every
revise-loop invocation produces a post-edit slide, this tool diffs
pre-edit vs post-edit content and runs five semantic invariants:

  1. claim_id cross-walk — every claim_id mention in pre-edit
     appears in post-edit at the same slide. Heuristic per DQ1:
     reads `claim_inventory.tsv`, extracts the claim_id column,
     scans both pre and post slide text for any of those IDs;
     per-slide set must be equal. Misses claims referenced
     without quoting the id; catches the common case where
     composer reuses the id in `evidence_pointer` fields.
  2. Citation cross-walk — every `[citation_key]` token in pre-edit
     MUST appear in post-edit. Insertions AND deletions forbidden
     (revise should only edit prose AROUND citations).
  3. Numeric token preservation — every numeric literal in pre-edit
     appears in post-edit at least as often. Removal allowed (for
     de-dup); invention forbidden.
  4. Hedge-marker level — per-slide aggregation per DQ2. Sum of
     §13-listed marker counts (`may`, `suggests`, `appears`,
     `candidate`, `preliminary`) across all text fields. Post
     count may decrease by ≤1 but not increase.
  5. Layout preservation — slide["layout"] field must not change
     (layout changes require re-architecting; user must run
     `--re-evaluate-architecture` instead).

Per DQ3 (Adam 2026-05-24): hard reject on any failed invariant.
The revise loop reads this tool's verdict and rejects the revision
wholesale, no retry-counter increment.

CLI:
    python3 revise_invariance.py <pre.json> <post.json>
                                  [--finding-id ID]
                                  [--claim-inventory PATH]
                                  [--out PATH]
                                  [--quiet]

Exit code: 0 if all checked invariants pass; 1 if any fail.
Always emits the invariance-report JSON to --out (or stdout if
absent).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util as _u
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "revise-invariance.v1"
VERSION = "0.4.0-m5a-tierA"

_THIS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Hedge dictionary (DQ2 — §13's 5 markers as constant)
# ---------------------------------------------------------------------------
#
# Match as whole words (`\b`) case-insensitively. Per DQ2 recommendation
# (a): per-slide aggregation; sum hedge counts across all text-bearing
# fields. §13's 5 markers are the v1 dictionary; per the ship-then-
# iterate posture, future iterations can extend (e.g. `consistent
# with`, `might`, `hint`, `indicate`) once we have revise-failure
# data showing the current set is too narrow.

HEDGE_MARKERS: tuple[str, ...] = (
    "may", "suggests", "appears", "candidate", "preliminary",
)


# ---------------------------------------------------------------------------
# Token-extraction regexes
# ---------------------------------------------------------------------------
#
# Citation: `[<key>]` where key is alphanumeric + hyphens/underscores
# (matches CONTRACT.md citation_pool.json key shape — Author2024 +
# pmid:XXXX + doi:10.XXXX/YYY). Excludes pure-number `[1]` matches
# (those are reference numbers, not citation_pool keys).
_CITATION_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_\-:.]*?)\]")

# Hedge: whole-word case-insensitive match across the §13 list.
_HEDGE_RE = re.compile(
    r"\b(" + "|".join(re.escape(m) for m in HEDGE_MARKERS) + r")\b",
    re.IGNORECASE,
)


def _load_check_grounding_helpers():
    """Lazily load `extract_numbers` from check_quantitative_grounding.py.

    The sibling-module load matches the pattern used by
    `review_cascade._invoke_review_tier2` etc. — keeps the dependency
    one-way (revise_invariance can use check_grounding's helpers; the
    reverse is never needed).
    """
    spec = _u.spec_from_file_location(
        "_check_grounding_for_invariance",
        _THIS_DIR / "check_quantitative_grounding.py",
    )
    mod = _u.module_from_spec(spec)
    sys.modules["_check_grounding_for_invariance"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Slide text extraction
# ---------------------------------------------------------------------------

def _extract_all_text(slide: dict) -> str:
    """Concatenate every text-bearing field of a slide into one string
    for token extraction. Walks `content` recursively (lists, dicts,
    nested structures) AND `speaker_notes` (top-level slide field).

    The concatenation is whitespace-joined; we never need positional
    spans (the invariants are set/multiset comparisons, not regex
    over fixed offsets). String values become text; non-string values
    (ints, floats, bools, None) are skipped — they're structural
    metadata (slide_id, position, validator_status) that should not
    feed into the textual invariants.
    """
    parts: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
        # ints / floats / bools / None — skip

    # Top-level fields: content (the textual body) + speaker_notes
    # (the notes pane, edited inline per M3 D-033).
    _walk(slide.get("content"))
    _walk(slide.get("speaker_notes"))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# claim_inventory.tsv reader
# ---------------------------------------------------------------------------

def _load_claim_ids(claim_inventory_path: Path | None) -> set[str]:
    """Return the set of claim_id strings from the TSV's first column.

    Tolerates a missing path / unreadable file by returning empty set
    (the claim_id invariant then no-ops; invariance check note
    captures the skipped state). The TSV shape is pinned by M1 +
    paper-writer's vendored `claim_inventory.py`: header row, first
    column = `claim_id`.
    """
    if claim_inventory_path is None or not claim_inventory_path.is_file():
        return set()
    ids: set[str] = set()
    try:
        with claim_inventory_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                cid = row.get("claim_id", "").strip()
                if cid:
                    ids.add(cid)
    except (OSError, csv.Error):
        return set()
    return ids


def _claim_id_mentions(text: str, claim_ids: set[str]) -> set[str]:
    """Find claim_ids mentioned in `text` (substring match).

    Substring is sufficient here — claim_ids are unique enough
    (`C-001`, `H1a`, etc.) that false positives are negligible.
    Whole-word matching via regex would be more robust but tighter
    than the DQ1 heuristic intent; substring matches `evidence_pointer`
    fields like "see C-001" / "C-001 (NB02 §3)" / "Claim C-001 …".
    """
    return {cid for cid in claim_ids if cid in text}


# ---------------------------------------------------------------------------
# Invariance violation + verdict
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """One failed invariant."""
    invariant: str       # "claim_id_cross_walk" | "citation_preservation" |
                         # "numeric_preservation" | "hedge_level" |
                         # "layout_preservation"
    severity: str        # "fail" — invariance is hard-reject per DQ3
    detail: str
    pre_value: Any = None
    post_value: Any = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InvarianceReport:
    """Full revise-invariance verdict for one revise call."""
    finding_id: str
    slide_id: int | None
    pre_edit_slide_path: str
    post_edit_slide_path: str
    checked_invariants: list[str] = field(default_factory=list)
    skipped_invariants: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    note: str = ""

    @property
    def verdict(self) -> str:
        return "fail" if self.violations else "pass"

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "finding_id": self.finding_id,
            "slide_id": self.slide_id,
            "pre_edit_slide_path": self.pre_edit_slide_path,
            "post_edit_slide_path": self.post_edit_slide_path,
            "checked_invariants": self.checked_invariants,
            "skipped_invariants": self.skipped_invariants,
            "violations": [v.to_dict() for v in self.violations],
            "verdict": self.verdict,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Per-invariant checkers
# ---------------------------------------------------------------------------

def _check_claim_id_cross_walk(
    pre_slide: dict, post_slide: dict,
    claim_ids: set[str],
) -> Violation | None:
    """Invariant (1) — per DQ1 heuristic. Pre-edit and post-edit must
    mention the same set of claim_ids per slide.

    Reading discipline: if `claim_ids` is empty (no claim_inventory or
    none loaded), the invariant is skipped (the caller records it in
    `skipped_invariants`); returns None.
    """
    if not claim_ids:
        return None
    pre_text = _extract_all_text(pre_slide)
    post_text = _extract_all_text(post_slide)
    pre_mentions = _claim_id_mentions(pre_text, claim_ids)
    post_mentions = _claim_id_mentions(post_text, claim_ids)
    if pre_mentions == post_mentions:
        return None
    removed = sorted(pre_mentions - post_mentions)
    added = sorted(post_mentions - pre_mentions)
    parts = []
    if removed:
        parts.append(f"removed: {removed}")
    if added:
        parts.append(f"added: {added}")
    return Violation(
        invariant="claim_id_cross_walk",
        severity="fail",
        detail=("claim_id mentions changed across revise (heuristic — "
                "substring match of claim_inventory.tsv ids in slide "
                "text + speaker_notes); " + "; ".join(parts)),
        pre_value=sorted(pre_mentions),
        post_value=sorted(post_mentions),
    )


def _check_citation_preservation(
    pre_slide: dict, post_slide: dict,
) -> Violation | None:
    """Invariant (2) — citation tokens must be set-equal across revise."""
    pre_text = _extract_all_text(pre_slide)
    post_text = _extract_all_text(post_slide)
    pre_cites = set(_CITATION_RE.findall(pre_text))
    post_cites = set(_CITATION_RE.findall(post_text))
    if pre_cites == post_cites:
        return None
    removed = sorted(pre_cites - post_cites)
    added = sorted(post_cites - pre_cites)
    parts = []
    if removed:
        parts.append(f"removed: {removed}")
    if added:
        parts.append(f"added: {added}")
    return Violation(
        invariant="citation_preservation",
        severity="fail",
        detail=("citation tokens changed across revise (insertions AND "
                "deletions forbidden; revise edits prose AROUND "
                "citations only); " + "; ".join(parts)),
        pre_value=sorted(pre_cites),
        post_value=sorted(post_cites),
    )


def _check_numeric_preservation(
    pre_slide: dict, post_slide: dict,
) -> Violation | None:
    """Invariant (3) — every numeric literal in pre-edit appears in
    post-edit at least as often (per-canonical-form multiset).
    Removal allowed for de-dup; invention forbidden.
    """
    cg = _load_check_grounding_helpers()
    pre_text = _extract_all_text(pre_slide)
    post_text = _extract_all_text(post_slide)
    pre_nums = Counter(n.canonical for n in cg.extract_numbers(pre_text))
    post_nums = Counter(n.canonical for n in cg.extract_numbers(post_text))
    # Pre - post = numbers that were in pre but not in post AT LEAST
    # as often. Multiset subtraction.
    removed = pre_nums - post_nums   # missing tokens (allowed per spec)
    invented = post_nums - pre_nums  # NEW tokens in post (forbidden)
    if not invented:
        return None
    invented_list = sorted(invented.elements())
    return Violation(
        invariant="numeric_preservation",
        severity="fail",
        detail=("numeric literals invented in revise (post-edit "
                "contains numbers not present in pre-edit); invented: "
                f"{invented_list}"),
        pre_value=sorted(pre_nums.elements()),
        post_value=sorted(post_nums.elements()),
    )


def _check_hedge_level(
    pre_slide: dict, post_slide: dict,
) -> Violation | None:
    """Invariant (4) — per-slide hedge aggregation per DQ2.

    Sum of §13-listed marker counts across all text fields. Post
    count may DECREASE by ≤1 (rephrasing is fine) but must NOT
    INCREASE (would flip a declarative claim to hedged) and must
    NOT decrease by >1 (would flip multiple hedges to declarative —
    a scope-change disguised as a revise).
    """
    pre_text = _extract_all_text(pre_slide)
    post_text = _extract_all_text(post_slide)
    pre_count = len(_HEDGE_RE.findall(pre_text))
    post_count = len(_HEDGE_RE.findall(post_text))
    delta = post_count - pre_count
    if -1 <= delta <= 0:
        return None
    if delta > 0:
        return Violation(
            invariant="hedge_level",
            severity="fail",
            detail=(f"hedge-marker count INCREASED across revise "
                    f"({pre_count} → {post_count}; +{delta}); revise "
                    f"should not flip declarative claims to hedged. "
                    f"Markers: {HEDGE_MARKERS}"),
            pre_value=pre_count,
            post_value=post_count,
        )
    # delta < -1
    return Violation(
        invariant="hedge_level",
        severity="fail",
        detail=(f"hedge-marker count DECREASED by >1 across revise "
                f"({pre_count} → {post_count}; {delta}); revise should "
                f"not flip multiple hedged claims to declarative in "
                f"one pass (per §13: ≤1 decrease allowed). Markers: "
                f"{HEDGE_MARKERS}"),
        pre_value=pre_count,
        post_value=post_count,
    )


def _check_layout_preservation(
    pre_slide: dict, post_slide: dict,
) -> Violation | None:
    """Invariant (5) — slide['layout'] must not change."""
    pre_layout = pre_slide.get("layout")
    post_layout = post_slide.get("layout")
    if pre_layout == post_layout:
        return None
    return Violation(
        invariant="layout_preservation",
        severity="fail",
        detail=(f"slide layout changed across revise ({pre_layout!r} → "
                f"{post_layout!r}); layout changes require re-architecting. "
                f"Run --re-evaluate-architecture instead."),
        pre_value=pre_layout,
        post_value=post_layout,
    )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def check_invariance(
    pre_slide: dict,
    post_slide: dict,
    *,
    finding_id: str = "",
    claim_inventory_path: Path | None = None,
    pre_path: str = "",
    post_path: str = "",
) -> InvarianceReport:
    """Run all five invariants. Returns an InvarianceReport.

    `claim_inventory_path` is optional; if None or unreadable, the
    claim_id cross-walk invariant (1) is recorded as skipped.
    """
    report = InvarianceReport(
        finding_id=finding_id,
        slide_id=pre_slide.get("id"),
        pre_edit_slide_path=pre_path,
        post_edit_slide_path=post_path,
    )

    # Invariant 1 — claim_id cross-walk (DQ1 heuristic)
    claim_ids = _load_claim_ids(claim_inventory_path)
    if not claim_ids:
        report.skipped_invariants.append("claim_id_cross_walk")
        report.note = (
            "claim_id_cross_walk skipped — claim_inventory.tsv missing "
            "or unreadable; revise discipline on claim_id mentions is "
            "not enforced for this finding."
        )
    else:
        report.checked_invariants.append("claim_id_cross_walk")
        v1 = _check_claim_id_cross_walk(pre_slide, post_slide, claim_ids)
        if v1 is not None:
            report.violations.append(v1)

    # Invariant 2 — citation preservation
    report.checked_invariants.append("citation_preservation")
    v2 = _check_citation_preservation(pre_slide, post_slide)
    if v2 is not None:
        report.violations.append(v2)

    # Invariant 3 — numeric preservation
    report.checked_invariants.append("numeric_preservation")
    v3 = _check_numeric_preservation(pre_slide, post_slide)
    if v3 is not None:
        report.violations.append(v3)

    # Invariant 4 — hedge level (DQ2 per-slide aggregation)
    report.checked_invariants.append("hedge_level")
    v4 = _check_hedge_level(pre_slide, post_slide)
    if v4 is not None:
        report.violations.append(v4)

    # Invariant 5 — layout preservation
    report.checked_invariants.append("layout_preservation")
    v5 = _check_layout_preservation(pre_slide, post_slide)
    if v5 is not None:
        report.violations.append(v5)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="revise_invariance",
        description="Semantic-invariance post-check for the revise verb "
                    "(v0.4 M5a Tier A). Five invariants per "
                    "V0_4_ARCHITECTURE §13: claim_id cross-walk, citation "
                    "preservation, numeric preservation, hedge level, "
                    "layout preservation. Per DQ3: hard reject (rc=1) on "
                    "any fail.",
    )
    p.add_argument("pre_slide", help="Path to pre-edit slide JSON.")
    p.add_argument("post_slide", help="Path to post-edit slide JSON.")
    p.add_argument("--finding-id", default="",
                   help="Finding id this revise addressed (for the report).")
    p.add_argument("--claim-inventory", default=None,
                   help="Path to claim_inventory.tsv (for invariant 1 "
                        "heuristic per DQ1). If absent, invariant 1 is "
                        "skipped.")
    p.add_argument("--out", default=None,
                   help="Output path for the invariance JSON report. If "
                        "absent, JSON is written to stdout.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the stderr summary line.")
    args = p.parse_args(argv)

    pre_path = Path(args.pre_slide)
    post_path = Path(args.post_slide)
    if not pre_path.is_file():
        print(f"revise_invariance: pre-edit slide not found: {pre_path}",
              file=sys.stderr)
        return 2
    if not post_path.is_file():
        print(f"revise_invariance: post-edit slide not found: {post_path}",
              file=sys.stderr)
        return 2
    try:
        pre_slide = json.loads(pre_path.read_text(encoding="utf-8"))
        post_slide = json.loads(post_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"revise_invariance: cannot parse slide JSON ({exc})",
              file=sys.stderr)
        return 2

    claim_inv = Path(args.claim_inventory) if args.claim_inventory else None
    report = check_invariance(
        pre_slide, post_slide,
        finding_id=args.finding_id,
        claim_inventory_path=claim_inv,
        pre_path=str(pre_path),
        post_path=str(post_path),
    )

    payload = report.to_dict()
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n",
                            encoding="utf-8")
    else:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")

    if not args.quiet:
        if report.verdict == "pass":
            print(f"  revise_invariance: pass "
                  f"({len(report.checked_invariants)} invariants checked"
                  + (f"; {len(report.skipped_invariants)} skipped"
                     if report.skipped_invariants else "")
                  + ")", file=sys.stderr)
        else:
            print(f"  revise_invariance: fail "
                  f"({len(report.violations)} violation(s) — see "
                  f"{args.out or '(stdout JSON)'})", file=sys.stderr)
            for v in report.violations:
                print(f"    - {v.invariant}: {v.detail[:140]}",
                      file=sys.stderr)

    # Per DQ3: hard reject — rc=1 on any violation
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
