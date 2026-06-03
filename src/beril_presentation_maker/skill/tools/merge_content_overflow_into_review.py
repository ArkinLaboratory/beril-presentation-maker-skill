#!/usr/bin/env python3
"""merge_content_overflow_into_review.py — fold content_overflow
findings (G.10-C) into adversarial_review.json so revise_loop
processes them as `class="content_overflow"` findings.

Mirrors the merge_visual_qa_into_review.py pattern, with one key
difference in TIMING:

  - VQ merger runs AFTER the 1st revise loop (G.7/G.8 pattern;
    visual-QA judges the post-revise deck).
  - This merger runs BEFORE the 1st revise loop. The renderer
    emits content_overflow findings as a side-effect of assemble;
    they're known at the moment adversarial_review.json is read,
    so they should ride into the 1st revise pass directly.

Synthetic id sequence:  CO001, CO002, ... (sortable AFTER F-prefixed
adversarial findings but BEFORE VQ-prefixed VQ findings, so the
revise queue processes them in the order operators expect:
  1. F-findings (adversarial)
  2. CO-findings (renderer geometry)
  3. VQ-findings (post-revise visual-QA, in the 2nd pass)

Per V0_8_PUNCH_LIST.md v0.8.1 carry: this closes the wiring gap
Tier H surfaced — content_overflow findings emit cleanly from the
renderer + lift into the cascade summary, but revise_loop.py only
read adversarial_review.json, so they never triggered a revise
pass. This merger makes them findable by the existing
revise_loop without any revise_loop.py change.

Cascade interaction: review_cascade.py already lifts content_overflow
findings from audit/content_overflow.json into Tier-1 (the
_read_content_overflow reader landed in G.10-C). That lift gives
the cascade summary + next_actions view. This merger is parallel:
it lifts them into adversarial_review.json so they ride through
revise_loop's existing F-prefix queue mechanics. The two lifts
serve different consumers (cascade summary vs revise loop).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# slot_kind + layout → adversarial-shape finding
# ---------------------------------------------------------------------------

# Per slot_kind: which adversarial-review class to route through.
# All content_overflow findings route to the `content_overflow` class
# we added to revise_loop.REVISE_CLASSES in G.10-C. This is intentional:
# revise_slide.v1 has a per-class section specifically for the
# rewrite-shorter semantic. Don't reuse register_drift / claim_evidence
# (those have different revise discipline — register softening,
# evidence reweighting — that's NOT the right fix for "title is too
# long for its slot at the legibility floor").
_DEFAULT_CLASS = "content_overflow"
_DEFAULT_FIX_TARGET = "slide_compose.v1.md"

# Per slot_kind: operator-readable fix hint. The G.10-C content_overflow
# section of revise_slide.v1 is the authoritative guidance; these hints
# point the LLM at the right slot to edit on a given finding.
_SLOT_KIND_TO_FIX_HINT: dict[str, str] = {
    "title": (
        "The slide's title overflows its slot at the 60% projection-"
        "legibility floor. Edit the title field (content.title, or "
        "content.unified_point / content.headline / content.question "
        "depending on layout) to be ≤120 chars for talk-30 mode. "
        "Preserve the substantive claim; cut hedges, qualifiers, "
        "parenthetical asides. A title is one tight clause, not a "
        "summary paragraph."
    ),
    "body": (
        "The slide's body bullets overflow the body region at the 60% "
        "projection-legibility floor. Edit the body field "
        "(content.bullets, content.key_takeaways, content.answer_summary "
        "depending on layout) — shorter bullets (preserve the arc; "
        "tighten the prose), or move load-bearing caveats to "
        "speaker_notes."
    ),
    "textbox": (
        "A freeform textbox slot (e.g., deck_close forward_call, "
        "data_table caption, methods_summary footer) overflows at the "
        "60% legibility floor. Trim the slot's content to fit."
    ),
}


def _content_overflow_to_adversarial(
    co_finding: dict[str, Any],
    index: int,
    slide_layouts: dict[int, str],
) -> dict[str, Any]:
    """Convert one content_overflow finding to an adversarial-shape
    finding.

    `index` is the synthetic id sequence number (1-based). Produces
    `id="CO{index:03d}"` so the revise loop's iteration order is
    deterministic + the synthetic findings sort BETWEEN F-prefixed
    adversarial findings and VQ-prefixed visual-QA findings.

    All content_overflow findings emit at P1 (advisory; the deck still
    renders — the content is just clamped at the projection-legibility
    floor; legibility is degraded but the file opens cleanly). Matches
    the cascade reader's severity choice.
    """
    slot_kind = co_finding.get("slot_kind") or "title"
    chars = co_finding.get("chars") or 0
    base_pt = co_finding.get("base_pt") or 28
    slide_id = co_finding.get("slide_id")
    where = co_finding.get("where") or f"slot_kind={slot_kind}"
    message = co_finding.get("message") or (
        f"{where}: {chars} chars at base {base_pt}pt clamped at floor.")

    if isinstance(slide_id, int):
        slide_layout = slide_layouts.get(slide_id, co_finding.get("layout_name") or "unknown")
    else:
        slide_layout = co_finding.get("layout_name") or "unknown"

    return {
        "id": f"CO{index:03d}",
        "class": _DEFAULT_CLASS,
        "severity": "P1",
        "confidence": "high",  # geometric truth, not a judgment call
        "slide_id": slide_id,
        "slide_position": slide_id,
        "slide_layout": slide_layout,
        "substory_id": None,
        "title_quote": (message or "")[:120].rstrip(),
        "issue": message,
        "report_evidence": [],
        "fix_target": _DEFAULT_FIX_TARGET,
        "fix_hint": _SLOT_KIND_TO_FIX_HINT.get(
            slot_kind, _SLOT_KIND_TO_FIX_HINT["title"]
        ),
        "_content_overflow_origin": {
            "slot_kind": slot_kind,
            "chars": chars,
            "base_pt": base_pt,
            "box_width_emu": co_finding.get("box_width_emu"),
            "box_height_emu": co_finding.get("box_height_emu"),
            "computed_scale": co_finding.get("computed_scale"),
        },
    }


def _load_slide_layouts(spec_path: Path) -> dict[int, str]:
    """Build {slide_id: layout} index from slide_spec.json for
    enriching content_overflow findings with layout context.
    Mirrors merge_visual_qa_into_review._load_slide_layouts."""
    if not spec_path.is_file():
        return {}
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    for s in spec.get("slides", []):
        sid = s.get("id")
        if isinstance(sid, int):
            out[sid] = s.get("layout", "unknown")
    return out


def _existing_co_fingerprints(
    review: dict[str, Any],
) -> set[tuple[int, str, int]]:
    """Set of (slide_id, slot_kind, chars) tuples already in the
    review — used to dedupe re-runs (the renderer re-emits the same
    overflow findings on every reassemble; we don't want to multiply
    them across revise iterations)."""
    fingerprints: set[tuple[int, str, int]] = set()
    for f in review.get("findings", []):
        fid = f.get("id", "")
        if not fid.startswith("CO"):
            continue
        origin = f.get("_content_overflow_origin") or {}
        sid = f.get("slide_id")
        if not isinstance(sid, int):
            continue
        fingerprints.add((
            sid,
            origin.get("slot_kind") or "unknown",
            int(origin.get("chars") or 0),
        ))
    return fingerprints


def _recompute_summary(review: dict[str, Any]) -> None:
    """Recompute review['summary'] from findings. Mirrors the VQ
    merger's recompute. content_overflow findings land in
    by_severity[P1] and by_class[content_overflow]."""
    sev_counter: Counter = Counter()
    class_counter: Counter = Counter()
    for f in review.get("findings", []):
        sev_counter[f.get("severity", "?")] += 1
        class_counter[f.get("class", "?")] += 1
    review["summary"] = {
        "by_severity": dict(sev_counter),
        "by_class": dict(class_counter),
    }


def merge(
    content_overflow_path: Path,
    review_path: Path,
    slide_spec_path: Path,
) -> tuple[int, int]:
    """Read content_overflow findings + append to adversarial review.

    Returns (n_added, n_skipped_duplicates). Mutates review_path in
    place (with idempotency via dedupe).

    No-op when content_overflow_path is missing (the renderer only
    writes it when at least one overflow finding emits — that's the
    happy path; nothing to merge).

    Raises FileNotFoundError if review_path is missing; that's a hard
    error (caller should have checked — adversarial_review must exist
    before this merger runs).
    """
    if not content_overflow_path.is_file():
        # Renderer wrote no overflow findings — nothing to merge.
        return (0, 0)
    if not review_path.is_file():
        raise FileNotFoundError(
            f"adversarial_review.json not found at {review_path}")

    co_payload = json.loads(content_overflow_path.read_text(encoding="utf-8"))
    co_findings = co_payload.get("findings", []) or []
    if not co_findings:
        return (0, 0)

    review = json.loads(review_path.read_text(encoding="utf-8"))
    slide_layouts = _load_slide_layouts(slide_spec_path)
    existing = _existing_co_fingerprints(review)

    findings = review.setdefault("findings", [])

    # Start CO-id numbering at 1 + max existing CO id (idempotency:
    # running twice doesn't restart at CO001).
    existing_co_max = 0
    for f in findings:
        fid = f.get("id", "")
        if fid.startswith("CO"):
            try:
                existing_co_max = max(existing_co_max, int(fid[2:]))
            except ValueError:
                pass

    n_added = 0
    n_dup = 0
    for co_f in co_findings:
        sid = co_f.get("slide_id")
        slot_kind = co_f.get("slot_kind") or "unknown"
        chars = int(co_f.get("chars") or 0)
        if isinstance(sid, int):
            fp = (sid, slot_kind, chars)
            if fp in existing:
                n_dup += 1
                continue
        existing_co_max += 1
        synth = _content_overflow_to_adversarial(
            co_f, existing_co_max, slide_layouts)
        findings.append(synth)
        n_added += 1

    _recompute_summary(review)

    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return (n_added, n_dup)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="merge_content_overflow_into_review.py",
        description=(
            "Fold content_overflow findings (G.10-C) into "
            "adversarial_review.json so revise_loop processes them "
            "as class='content_overflow' findings (v0.8.1)."
        ),
    )
    ap.add_argument(
        "draft_dir", type=Path,
        help="Draft directory (audit/ + working/ live under here).",
    )
    args = ap.parse_args(argv)

    draft_dir = args.draft_dir.resolve()
    if not draft_dir.is_dir():
        print(f"Error: draft_dir not found: {draft_dir}", file=sys.stderr)
        return 2

    co_path = draft_dir / "audit" / "content_overflow.json"
    review_path = draft_dir / "audit" / "adversarial_review.json"
    spec_path = draft_dir / "working" / "slide_spec.json"

    try:
        n_added, n_dup = merge(co_path, review_path, spec_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(
        f"merge_content_overflow_into_review: appended {n_added} "
        f"synthetic finding(s) to {review_path} (deduped {n_dup})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
