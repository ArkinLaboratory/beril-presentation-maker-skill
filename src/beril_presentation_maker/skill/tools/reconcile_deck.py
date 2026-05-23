#!/usr/bin/env python3
"""reconcile_deck.py — post-merge deck reconciliation checker (v0.4 M3).

V0_4_ARCHITECTURE.md §20.4: the v0.4 per-substory composers run in
parallel and cannot see each other's in-flight output. The deck outline
pre-assigns the scarce / conflict-prone resources (figures, headline
slots, the image budget); this checker is the backstop that flags
*residual* cross-section conflicts in the merged ``slide_spec.json`` —
conflicts no single composer could have detected alone.

Three conflict classes (M3_PUNCH_LIST.md Tier C; §20.4):

  duplicate_figure   — the same reused figure asset (``content.figure``
                       or ``content.supporting_graphic``) appears on
                       more than one slide.
  duplicate_headline — two or more ``big_number`` slides carry the same
                       headline value: the deck shouts one number twice.
  image_budget       — the count of ``concept_illustration`` (AI-image)
                       slides exceeds the deck outline's ``Image budget``.

This is an ADVISORY checker, modelled on ``check_quantitative_grounding.py``
and ``check_no_artifact_refs.py``: it always exits 0 (a conflict is a
finding for the hand-edit pass, not a pipeline halt) and writes
``audit/deck_reconciliation.{md,json}`` for the user / a later stage to
consult. It detects *conflicts*, not contract adherence — it replaces
the M0 design's ``check_architecture_drift.py`` (dropped with the rigid
``01_deck_architecture.json`` contract; D-044).

Layout: v0.3.1+ 4-zone draft directory. Reads
``<draft_dir>/working/slide_spec.json`` and, if present, the deck
outline at ``<draft_dir>/narrative/02_substories.md`` (the ``Image
budget`` line is only emitted by the v0.4 ``deck_outline.v1`` prompt;
on a v0.3.x draft the image_budget class is simply skipped).

CLI:
    python3 reconcile_deck.py <draft_dir> [--quiet]

Exit code: always 0 (advisory).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "deck-reconciliation.v1"

# Content keys that hold a *reused* figure asset (a curated figure that
# could legitimately appear once but not twice). NOT image_path: that is
# a concept_illustration's AI-generated image — distinct per slide by
# construction, and the literal "{TBD}" placeholder pre-image-gen would
# otherwise read as a deck-wide duplicate.
_FIGURE_KEYS = ("figure", "supporting_graphic")


def _norm(value: str) -> str:
    """Whitespace-insensitive, case-insensitive key for value comparison."""
    return re.sub(r"\s+", "", value).lower()


def _slide_label(slide: dict) -> str:
    """Human pointer for a slide in findings text."""
    sid = slide.get("id")
    layout = slide.get("layout", "?")
    return f"slide {sid} ({layout})"


def detect_duplicate_figures(slides: list[dict]) -> list[dict]:
    """A reused figure asset appearing on more than one slide."""
    by_fig: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for slide in slides:
        content = slide.get("content") or {}
        sid = slide.get("id")
        for key in _FIGURE_KEYS:
            fig = content.get(key)
            if isinstance(fig, str) and fig.strip():
                norm = _norm(fig)
                by_fig.setdefault(norm, [])
                if sid not in by_fig[norm]:
                    by_fig[norm].append(sid)
                display.setdefault(norm, fig.strip())
    findings: list[dict] = []
    for norm, ids in sorted(by_fig.items()):
        if len(ids) > 1:
            findings.append({
                "kind": "duplicate_figure",
                "severity": "warning",
                "detail": (
                    f"figure {display[norm]!r} is used on "
                    f"{len(ids)} slides: {ids}. A curated figure should "
                    f"carry one slide; reuse usually means two composers "
                    f"independently reached for the same asset."
                ),
                "slide_ids": ids,
            })
    return findings


def detect_duplicate_headlines(slides: list[dict]) -> list[dict]:
    """Two or more big_number slides carrying the same headline value."""
    by_headline: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for slide in slides:
        if slide.get("layout") != "big_number":
            continue
        content = slide.get("content") or {}
        headline = content.get("headline")
        if isinstance(headline, str) and headline.strip():
            norm = _norm(headline)
            by_headline.setdefault(norm, []).append(slide.get("id"))
            display.setdefault(norm, headline.strip())
    findings: list[dict] = []
    for norm, ids in sorted(by_headline.items()):
        if len(ids) > 1:
            findings.append({
                "kind": "duplicate_headline",
                "severity": "warning",
                "detail": (
                    f"big_number headline {display[norm]!r} appears on "
                    f"{len(ids)} slides: {ids}. The deck headlines the "
                    f"same number twice — one section's headline slot "
                    f"should land it; the other should reframe."
                ),
                "slide_ids": ids,
            })
    return findings


def _extract_image_budget_cap(outline_text: str | None) -> int | None:
    """Pull the integer cap from the outline's `**Image budget:**` line.

    Returns None when there is no outline, no Image-budget line, or no
    integer in it — in every such case the image_budget class is skipped.
    """
    if not outline_text:
        return None
    m = re.search(r"\*\*Image budget:\*\*\s*(.+)", outline_text)
    if not m:
        return None
    digits = re.search(r"\d+", m.group(1))
    return int(digits.group(0)) if digits else None


def detect_image_budget_overflow(
    slides: list[dict], outline_text: str | None
) -> list[dict]:
    """concept_illustration (AI-image) slide count over the deck budget."""
    cap = _extract_image_budget_cap(outline_text)
    if cap is None:
        return []
    ai_ids = [
        s.get("id") for s in slides
        if s.get("layout") == "concept_illustration"
    ]
    if len(ai_ids) > cap:
        return [{
            "kind": "image_budget",
            "severity": "warning",
            "detail": (
                f"{len(ai_ids)} concept_illustration (AI-image) slides "
                f"vs the deck outline's image budget of {cap}: "
                f"slides {ai_ids}. Parallel composers each flagged an "
                f"illustration without deck-level budget awareness."
            ),
            "slide_ids": ai_ids,
        }]
    return []


def reconcile(spec: dict, outline_text: str | None) -> list[dict]:
    """Run all three conflict detectors over a merged slide_spec dict."""
    slides = spec.get("slides")
    if not isinstance(slides, list):
        return []
    findings: list[dict] = []
    findings += detect_duplicate_figures(slides)
    findings += detect_duplicate_headlines(slides)
    findings += detect_image_budget_overflow(slides, outline_text)
    return findings


def render_md(findings: list[dict], draft_dir: str, *, note: str = "") -> str:
    """Human-readable reconciliation report for the draft's audit/."""
    lines = ["# Deck reconciliation report", "", f"Draft: `{draft_dir}`", ""]
    if note:
        lines += [f"_{note}_", ""]
    if not findings:
        lines += ["No cross-section conflicts detected — figures unique, "
                  "no duplicated headline, image budget respected."]
        return "\n".join(lines) + "\n"
    lines += [f"**{len(findings)} conflict(s) flagged** (advisory — review "
              "during the hand-edit pass):", ""]
    for f in findings:
        lines += [f"## {f['kind']} ({f['severity']})",
                  "",
                  f["detail"],
                  ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Post-merge deck reconciliation checker (advisory).",
    )
    p.add_argument("draft_dir", help="v0.3.1+ draft directory (talks/draft_N/).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the per-finding stderr summary.")
    args = p.parse_args(argv)

    draft = Path(args.draft_dir)
    audit_dir = draft / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    out_json = audit_dir / "deck_reconciliation.json"
    out_md = audit_dir / "deck_reconciliation.md"

    spec_path = draft / "working" / "slide_spec.json"
    outline_path = draft / "narrative" / "02_substories.md"

    note = ""
    findings: list[dict] = []
    if not spec_path.is_file():
        note = (f"slide_spec.json not found at {spec_path} — nothing to "
                f"reconcile (advisory checker, no-op).")
    else:
        try:
            spec = json.loads(spec_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            note = f"slide_spec.json unreadable ({exc}) — reconciliation skipped."
            spec = None
        if note:
            pass
        else:
            outline_text = None
            if outline_path.is_file():
                try:
                    outline_text = outline_path.read_text()
                except OSError:
                    outline_text = None
            findings = reconcile(spec, outline_text)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "draft_dir": str(draft),
        "n_findings": len(findings),
        "findings": findings,
    }
    if note:
        payload["note"] = note
    out_json.write_text(json.dumps(payload, indent=2) + "\n")
    out_md.write_text(render_md(findings, str(draft), note=note))

    if not args.quiet:
        if note:
            print(f"  deck reconciliation: {note}", file=sys.stderr)
        elif findings:
            print(f"  deck reconciliation: {len(findings)} conflict(s) "
                  f"flagged — see {out_md}", file=sys.stderr)
            for f in findings:
                print(f"    - {f['kind']}: slides {f['slide_ids']}",
                      file=sys.stderr)
        else:
            print("  deck reconciliation: no cross-section conflicts",
                  file=sys.stderr)

    # Advisory: always exit 0. A conflict is a hand-edit finding, never
    # a pipeline halt.
    return 0


if __name__ == "__main__":
    sys.exit(main())
