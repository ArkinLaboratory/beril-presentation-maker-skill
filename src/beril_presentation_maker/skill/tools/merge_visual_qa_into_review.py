#!/usr/bin/env python3
"""merge_visual_qa_into_review.py — v0.8 Tier G.7.

Reads `audit/visual_qa_final.json` (produced post-revise) + appends
synthetic adversarial-shape findings to `audit/adversarial_review.json`
so the second revise loop pass can process them.

The visual-QA finding shape (visual_qa.v1):
  {
    "slide_id": int,
    "kind": "illegible_scale|container_breach|element_overlap|
             headline_body_mismatch|footer_or_title_collision",
    "severity": "warning",   # always warning at the visual-QA layer
    "confidence": "high|medium|low",
    "detail": "...",
    "evidence_locator": "..."
  }

Maps to adversarial-shape:
  {
    "id": "VQ001" (numbered V[Q for visual-Quality]),
    "class": <mapped — see below>,
    "severity": "P1" (confidence=high) or "P2" (medium|low),
    "confidence": "high|medium|low",
    "slide_id": int,
    "slide_layout": <looked up from slide_spec>,
    "title_quote": "<visual-QA detail truncated to ~100 chars>",
    "issue": "<full visual-QA detail>",
    "fix_target": <mapped per class>,
    "fix_hint": "<generic per-class hint>",
    "report_evidence": []    # visual-QA isn't claim-evidence-based,
                              # so no report_evidence
  }

Class mapping (visual-QA kind → adversarial class):
  - illegible_scale → register_drift
    (content is too long; revise_slide.v1 should shorten)
  - container_breach → register_drift
    (text overflowing slot; shorten)
  - element_overlap → register_drift
    (elements collide; usually a content-length issue)
  - footer_or_title_collision → register_drift
    (citation footer hitting body; shorten body or footnote)
  - headline_body_mismatch → claim_evidence
    (title promises content body doesn't deliver; rewrite body)

Severity mapping: confidence=high → P1; medium|low → P2.

Why these mappings:
  - Most visual-QA findings (illegible_scale + container_breach +
    element_overlap + footer_or_title_collision) reduce to "content
    too long; shorten." That's exactly what register_drift findings
    target via revise_slide.v1.
  - headline_body_mismatch is unique: the body content is wrong, not
    just too long. Routes to claim_evidence (same class as adversarial
    review uses for body-content mismatches).

The merged JSON preserves the original adversarial_review.json
structure + summary counts; only `findings[]` grows. The summary
counters are recomputed.

Idempotent: re-running this tool against an already-merged file
detects entries with `id` starting `VQ` and refuses to add duplicates
(by slide_id+kind+detail-prefix). Safe for re-runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Class + severity mappings
# ---------------------------------------------------------------------------

_KIND_TO_CLASS = {
    "illegible_scale":          "register_drift",
    "container_breach":         "register_drift",
    "element_overlap":          "register_drift",
    "footer_or_title_collision": "register_drift",
    "headline_body_mismatch":   "claim_evidence",
}

_KIND_TO_FIX_TARGET = {
    "illegible_scale":          "slide_compose.v1.md",
    "container_breach":         "slide_compose.v1.md",
    "element_overlap":          "slide_compose.v1.md",
    "footer_or_title_collision": "slide_compose.v1.md",
    "headline_body_mismatch":   "slide_compose.v1.md",
}

_KIND_TO_FIX_HINT = {
    "illegible_scale": (
        "Body content is too long for the slot; shrink-to-fit dropped "
        "below the projection-legibility threshold. Shorten the on-slide "
        "content; move depth to speaker_notes if needed."
    ),
    "container_breach": (
        "Text overflows the slot's container. Shorten the on-slide text "
        "or split into a separate slide."
    ),
    "element_overlap": (
        "Two elements occupy the same space. Usually a length issue: "
        "shorten the longer one or reflow the layout."
    ),
    "footer_or_title_collision": (
        "The data-source/caveat footnote overlaps the body or title. "
        "Trim the footnote string to fit the 0.30-in footer band, or "
        "shorten the body content above it."
    ),
    "headline_body_mismatch": (
        "Title promises content the body doesn't deliver. Either trim "
        "the title scope or expand the body to match the title's claim."
    ),
}


def _vq_to_adversarial(vq_finding: dict[str, Any],
                       index: int,
                       slide_layouts: dict[int, str]) -> dict[str, Any]:
    """Convert one visual-QA finding to an adversarial-shape finding.

    `index` is the synthetic id sequence number (1-based). Produces
    `id="VQ{index:03d}"` so the second revise loop's iteration order
    is deterministic and the synthetic findings sort after the
    original adversarial findings (F001..F999) alphabetically.
    """
    kind = vq_finding.get("kind", "unknown")
    conf = vq_finding.get("confidence", "medium")
    detail = vq_finding.get("detail") or ""
    slide_id = vq_finding.get("slide_id")
    if isinstance(slide_id, int):
        slide_layout = slide_layouts.get(slide_id, "unknown")
    else:
        slide_layout = "unknown"
    return {
        "id": f"VQ{index:03d}",
        "class": _KIND_TO_CLASS.get(kind, "register_drift"),
        "severity": "P1" if conf == "high" else "P2",
        "confidence": conf,
        "slide_id": slide_id,
        "slide_position": slide_id,
        "slide_layout": slide_layout,
        "substory_id": None,
        "title_quote": detail[:120].rstrip(),
        "issue": detail,
        "report_evidence": [],
        "fix_target": _KIND_TO_FIX_TARGET.get(kind, "slide_compose.v1.md"),
        "fix_hint": _KIND_TO_FIX_HINT.get(
            kind, "Visual-QA flagged this slide; review on the rendered "
                  "deck and adjust content length or layout."),
        "_visual_qa_origin": {
            "kind": kind,
            "evidence_locator": vq_finding.get("evidence_locator"),
        },
    }


def _load_slide_layouts(spec_path: Path) -> dict[int, str]:
    """Build {slide_id: layout} index from slide_spec.json for
    enriching visual-QA findings with layout context."""
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


def _existing_vq_fingerprints(review: dict[str, Any]) -> set[tuple[int, str, str]]:
    """Set of (slide_id, vq_kind, detail-prefix) tuples already in the
    review — used to dedupe re-runs."""
    fingerprints: set[tuple[int, str, str]] = set()
    for f in review.get("findings", []):
        fid = f.get("id", "")
        if not fid.startswith("VQ"):
            continue
        vq_origin = f.get("_visual_qa_origin") or {}
        sid = f.get("slide_id")
        if not isinstance(sid, int):
            continue
        fingerprints.add((
            sid,
            vq_origin.get("kind") or "unknown",
            (f.get("issue") or "")[:80],
        ))
    return fingerprints


def _recompute_summary(review: dict[str, Any]) -> None:
    """Recompute review['summary'] from findings. The original
    adversarial review's summary has shape:

      {
        "by_severity": {"P0": N, "P1": N, "P2": N, "info": N},
        "by_class": {<class>: N, ...}
      }

    Visual-QA additions land in by_severity[P1] or P2 and
    by_class[register_drift] or [claim_evidence]."""
    sev_counter: Counter[str] = Counter()
    class_counter: Counter[str] = Counter()
    for f in review.get("findings", []):
        sev_counter[f.get("severity", "?")] += 1
        class_counter[f.get("class", "?")] += 1
    summary = review.setdefault("summary", {})
    summary["by_severity"] = dict(sev_counter)
    summary["by_class"] = dict(class_counter)


def merge(
    visual_qa_path: Path,
    review_path: Path,
    slide_spec_path: Path,
    vq_only_review_path: Path | None = None,
) -> tuple[int, int]:
    """Read visual-QA findings + append to adversarial review.

    Returns (n_added, n_skipped_duplicates). Mutates review_path in
    place (with idempotency via dedupe). Raises FileNotFoundError if
    either input is missing; that's a hard error (caller should have
    checked).

    v0.8 Tier G.8 — when `vq_only_review_path` is supplied, ALSO writes
    a standalone adversarial-review-shaped JSON containing ONLY the
    synthetic VQ findings. This file is used by the orchestrator's
    2nd revise loop pass so it doesn't re-iterate the original
    F-prefixed findings and exhaust max_revisions before reaching any
    VQ finding (the G.7 architectural bug live-discovered on draft_12).
    The merged review_path still gets the VQ findings appended for
    cascade-reader / next_actions consumption.
    """
    if not visual_qa_path.is_file():
        raise FileNotFoundError(
            f"visual_qa_final.json not found at {visual_qa_path}")
    if not review_path.is_file():
        raise FileNotFoundError(
            f"adversarial_review.json not found at {review_path}")

    vq = json.loads(visual_qa_path.read_text(encoding="utf-8"))
    vq_findings = vq.get("findings", []) or []
    if not vq_findings:
        # v0.8 Tier G.8: even when no VQ findings, write an empty
        # standalone file so the orchestrator's 2nd revise pass has
        # a stable artifact to read (revise_loop crashes on missing
        # --review-path; an empty findings[] array is the cleanest
        # no-op signal).
        if vq_only_review_path is not None:
            _write_vq_only_review(vq_only_review_path, [], review_path)
        return (0, 0)

    review = json.loads(review_path.read_text(encoding="utf-8"))
    slide_layouts = _load_slide_layouts(slide_spec_path)
    existing = _existing_vq_fingerprints(review)

    findings = review.setdefault("findings", [])
    # Start VQ-id numbering from 1 + max existing VQ id (in case the
    # tool was run twice and the operator wants stable ids).
    existing_vq_max = 0
    for f in findings:
        fid = f.get("id", "")
        if fid.startswith("VQ"):
            try:
                existing_vq_max = max(existing_vq_max, int(fid[2:]))
            except ValueError:
                pass

    new_vq_synthetic: list[dict[str, Any]] = []
    n_dup = 0
    for vq_f in vq_findings:
        sid = vq_f.get("slide_id")
        kind = vq_f.get("kind", "unknown")
        detail_prefix = (vq_f.get("detail") or "")[:80]
        if isinstance(sid, int):
            fp = (sid, kind, detail_prefix)
            if fp in existing:
                n_dup += 1
                continue
        existing_vq_max += 1
        synth = _vq_to_adversarial(vq_f, existing_vq_max, slide_layouts)
        new_vq_synthetic.append(synth)
        findings.append(synth)

    n_added = len(new_vq_synthetic)

    _recompute_summary(review)

    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # v0.8 Tier G.8 — write standalone VQ-only review file for the
    # 2nd revise pass (only when path requested).
    if vq_only_review_path is not None:
        _write_vq_only_review(vq_only_review_path, new_vq_synthetic, review_path)

    return (n_added, n_dup)


def _write_vq_only_review(
    out_path: Path,
    vq_findings: list[dict[str, Any]],
    source_review_path: Path,
) -> None:
    """Write a standalone adversarial-review-shaped JSON containing
    ONLY the VQ-prefixed synthetic findings.

    v0.8 Tier G.8 — used by the orchestrator's 2nd revise pass so it
    iterates only the visual-QA findings, not the original F-prefixed
    adversarial findings. Each revise pass has its own max_revisions
    budget this way.

    The shape mirrors adversarial_review.json's envelope but with
    findings[] holding only the VQ entries. tier + verdict + summary
    fields are copied from the source review (or defaulted) so any
    downstream consumer expecting that shape doesn't choke.
    """
    try:
        source = json.loads(source_review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        source = {}
    out = {
        "schema_version": source.get("schema_version", "adversarial-review.v3"),
        "tier": source.get("tier", "STRONG"),
        "verdict": "PASS",  # VQ-only file is always advisory
        "_origin": "visual_qa_final (Tier G.8 standalone for 2nd revise pass)",
        "findings": list(vq_findings),
        "summary": {
            "by_severity": _count_by(vq_findings, "severity"),
            "by_class": _count_by(vq_findings, "class"),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _count_by(findings: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for f in findings:
        counts[f.get(key, "?")] += 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="merge_visual_qa_into_review.py",
        description=(
            "v0.8 Tier G.7: append visual_qa_final.json findings to "
            "adversarial_review.json as synthetic adversarial-shape "
            "findings so the post-revise revise loop can act on them."
        ),
    )
    p.add_argument(
        "--draft-dir", type=Path, required=True,
        help="Draft directory containing audit/ + working/.")
    p.add_argument(
        "--visual-qa", type=Path, default=None,
        help="Override path to visual_qa_final.json (default: "
             "DRAFT/audit/visual_qa_final.json).")
    p.add_argument(
        "--review", type=Path, default=None,
        help="Override path to adversarial_review.json (default: "
             "DRAFT/audit/adversarial_review.json).")
    p.add_argument(
        "--slide-spec", type=Path, default=None,
        help="Override path to slide_spec.json (default: "
             "DRAFT/working/slide_spec.json).")
    p.add_argument(
        "--vq-only-review", type=Path, default=None,
        help="v0.8 Tier G.8: also write a standalone "
             "adversarial-review-shaped JSON containing ONLY the new "
             "VQ-prefixed synthetic findings to this path. Used by the "
             "orchestrator's 2nd revise pass so it iterates only VQ "
             "findings (each pass has its own max_revisions budget). "
             "Default: DRAFT/audit/adversarial_review_vq_only.json when "
             "--draft-dir resolved.")
    args = p.parse_args(argv)

    draft = args.draft_dir
    vq_path = args.visual_qa or (draft / "audit" / "visual_qa_final.json")
    review_path = args.review or (draft / "audit" / "adversarial_review.json")
    spec_path = args.slide_spec or (draft / "working" / "slide_spec.json")
    vq_only_path = (args.vq_only_review
                    or (draft / "audit" / "adversarial_review_vq_only.json"))

    if not vq_path.is_file():
        print(
            f"merge_visual_qa_into_review: no visual_qa_final.json at "
            f"{vq_path}; nothing to merge",
            file=sys.stderr,
        )
        return 0  # not an error — caller may invoke us speculatively

    if not review_path.is_file():
        print(
            f"merge_visual_qa_into_review: ERROR — adversarial_review.json "
            f"not found at {review_path}",
            file=sys.stderr,
        )
        return 2

    try:
        n_added, n_dup = merge(
            vq_path, review_path, spec_path,
            vq_only_review_path=vq_only_path)
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"merge_visual_qa_into_review: ERROR merging — {e}",
            file=sys.stderr,
        )
        return 2

    print(
        f"merge_visual_qa_into_review: appended {n_added} synthetic "
        f"finding(s) to {review_path} (deduped {n_dup}); wrote "
        f"VQ-only review for 2nd revise pass to {vq_only_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
