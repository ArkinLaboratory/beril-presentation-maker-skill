#!/usr/bin/env python3
"""image_gen_decision.py — Tier 1 decision layer for v0.3.3 image-gen.

Per V0_3_3_ARCHITECTURE.md §6, the v0.3.3 decision layer is a pure
Python deterministic gate over slide layout + tier + flags. No LLM
call. The full closed-set of 16 layouts (slide_spec.LAYOUTS) is
covered with explicit rules; unknown layouts raise UnknownLayoutError
to force explicit handling on layout additions.

Design rationale (vs the punch list's 3-layer plan): the existing
ai_image_prompt.v1.md prompt is the brief AND the prompt — there is
no missing layer between slide-stub and request-JSON. And
concept_illustration is the only layout that needs an AI image in
v0.3.3 (image_path: "{TBD}" placeholder is the slide-compose
signal). LLM-decision on claim_evidence / supplemental images is
deferred to v0.3.4 if smoke shows the deterministic gate misses
real cases.

CLI:
    python3 image_gen_decision.py emit-decisions \\
        --slides-dir <draft>/working/03_slides \\
        --tier STRONG --mode talk-30 \\
        [--allow-exploratory] \\
        --out <draft>/working/05_image_decisions.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# slide_spec.LAYOUTS is the closed-set source of truth. Importing
# directly from the sibling tool (no package layer between them).
_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))
import slide_spec  # noqa: E402

SCHEMA_VERSION = "image-decisions.v1"

# Layout categorization. Three sets that must partition slide_spec.LAYOUTS.
# Defined explicitly so that adding a layout requires a categorization
# decision (the closed-set assertion at module load surfaces drift).

_AI_IMAGE_VEHICLE = frozenset({
    "concept_illustration",
})

_STRUCTURAL_NO_IMAGE = frozenset({
    "title",
    "section_divider",
    "acknowledgments",
    "references",
    "qa_anticipated",
    "methods_summary",
    "cross_tenant_integration",
})

_HAS_OWN_FIGURE = frozenset({
    "data_figure",
    "data_table",
})

# Layouts where a supplemental image MIGHT help but the decision is
# deferred to v0.3.4's LLM-judgment layer. v0.3.3 says NO for all of
# them.
_DEFERRED_LLM_DECISION = frozenset({
    "claim_evidence",
    "workflow_diagram",
    "two_column_compare",
    "big_idea",
    "big_number",
    "implications",
})


def _validate_partition() -> None:
    """Sanity-check at import time: the four sets must partition
    slide_spec.LAYOUTS exactly. Drift surfaces immediately on any
    layout addition that didn't update this module."""
    catalogued = (
        _AI_IMAGE_VEHICLE
        | _STRUCTURAL_NO_IMAGE
        | _HAS_OWN_FIGURE
        | _DEFERRED_LLM_DECISION
    )
    spec_layouts = set(slide_spec.LAYOUTS)
    missing = spec_layouts - catalogued
    extra = catalogued - spec_layouts
    if missing or extra:
        raise RuntimeError(
            f"image_gen_decision: layout partition drift detected. "
            f"slide_spec.LAYOUTS = {sorted(spec_layouts)!r}; "
            f"catalogued = {sorted(catalogued)!r}; "
            f"missing from this module: {sorted(missing)!r}; "
            f"extra in this module: {sorted(extra)!r}. "
            f"Update image_gen_decision.py to categorize all layouts."
        )
    # Disjointness: no layout in two categories.
    overlaps = (
        (_AI_IMAGE_VEHICLE & _STRUCTURAL_NO_IMAGE)
        | (_AI_IMAGE_VEHICLE & _HAS_OWN_FIGURE)
        | (_AI_IMAGE_VEHICLE & _DEFERRED_LLM_DECISION)
        | (_STRUCTURAL_NO_IMAGE & _HAS_OWN_FIGURE)
        | (_STRUCTURAL_NO_IMAGE & _DEFERRED_LLM_DECISION)
        | (_HAS_OWN_FIGURE & _DEFERRED_LLM_DECISION)
    )
    if overlaps:
        raise RuntimeError(
            f"image_gen_decision: category overlap: {sorted(overlaps)!r}"
        )


_validate_partition()


class UnknownLayoutError(ValueError):
    """Raised when a slide carries a layout not in slide_spec.LAYOUTS.

    The caller must surface this loud — silently skipping unknown
    layouts would let a misspelled / forward-compatible layout slip
    past the decision gate without a verdict."""


@dataclass
class Decision:
    """One slide's decision verdict."""
    slide_id: str       # "S2-pos4" pattern; substory_id + 0-indexed position
    layout: str
    emit: bool
    reason: str
    # Optional: the substory_id and position split out for downstream
    # consumers that don't want to re-parse slide_id.
    substory_id: str = ""
    position: int = -1


def decide(
    slide_stub: dict,
    *,
    tier: str,
    mode: str,
    user_opt_in_exploratory: bool = False,
    substory_id: str = "",
    position: int = -1,
) -> Decision:
    """Apply the v0.3.3 deterministic decision rules to one slide stub.

    Args:
      slide_stub: parsed slide dict from working/03_slides/<sid>_slides.json.
        Must have "layout" key. "content" is read for image_path on
        concept_illustration slides (verifies the "{TBD}" marker is
        present — its absence means slide_compose already-resolved
        the image, e.g., from cache, and we should not re-generate).
      tier: STRONG | THIN | EXPLORATORY (slide_spec.TIERS).
      mode: talk-30 | talk-15 | etc. (informational; no rule depends on
        it in v0.3.3 but signature symmetry helps v0.3.4 LLM-decision).
      user_opt_in_exploratory: if True, allow concept_illustration on
        EXPLORATORY tier. Default False (rule 6).
      substory_id, position: pass-through context for the Decision record.

    Returns:
      Decision with emit + reason populated.

    Raises:
      UnknownLayoutError if slide_stub["layout"] not in slide_spec.LAYOUTS.
      KeyError if slide_stub lacks "layout".
    """
    if "layout" not in slide_stub:
        raise KeyError("slide_stub missing 'layout' key")
    layout = slide_stub["layout"]
    if layout not in slide_spec.LAYOUTS:
        raise UnknownLayoutError(
            f"layout {layout!r} not in slide_spec.LAYOUTS = "
            f"{sorted(slide_spec.LAYOUTS)!r}. v0.3.3 requires every "
            f"layout to have a decision rule; categorize this layout in "
            f"image_gen_decision.py before proceeding."
        )

    slide_id = _build_slide_id(substory_id, position)

    # Rule 1+2: layouts that already carry their own figure.
    if layout in _HAS_OWN_FIGURE:
        return Decision(
            slide_id=slide_id, layout=layout, emit=False,
            reason=f"{layout} carries its own figure; no AI image needed",
            substory_id=substory_id, position=position,
        )

    # Rule 3: structural slides (title, dividers, acks, refs, qa, methods,
    # cross_tenant). No content-image affordance.
    if layout in _STRUCTURAL_NO_IMAGE:
        return Decision(
            slide_id=slide_id, layout=layout, emit=False,
            reason=f"{layout} is structural; no AI image affordance",
            substory_id=substory_id, position=position,
        )

    # Rule 5: deferred. v0.3.3 says no; v0.3.4 will revisit with an LLM
    # judgment layer.
    if layout in _DEFERRED_LLM_DECISION:
        return Decision(
            slide_id=slide_id, layout=layout, emit=False,
            reason=(
                f"{layout} supplemental-image decision deferred to "
                f"v0.3.4 LLM-judgment layer"
            ),
            substory_id=substory_id, position=position,
        )

    # At this point only _AI_IMAGE_VEHICLE remains — concept_illustration.
    assert layout in _AI_IMAGE_VEHICLE, (
        f"partition broken: {layout} fell through all categories"
    )

    # Rule 6: EXPLORATORY tier requires explicit opt-in. Overrides rule 4.
    if tier == "EXPLORATORY" and not user_opt_in_exploratory:
        return Decision(
            slide_id=slide_id, layout=layout, emit=False,
            reason=(
                "EXPLORATORY tier requires --image-allow-exploratory to "
                "approve concept_illustration; default skip per R6"
            ),
            substory_id=substory_id, position=position,
        )

    # Sanity check: concept_illustration slides should have the
    # {TBD} placeholder per slide_compose.v1.md L756-760. If
    # image_path is already a real path, slide_compose has been
    # bypassed (resume mode? cached fragment?) — emit=False with a
    # reason rather than re-generating over an existing image.
    content = slide_stub.get("content", {})
    image_path = content.get("image_path", "")
    if image_path and image_path != "{TBD}":
        return Decision(
            slide_id=slide_id, layout=layout, emit=False,
            reason=(
                f"concept_illustration already has image_path={image_path!r} "
                f"(not the {{TBD}} placeholder); skip re-generation"
            ),
            substory_id=substory_id, position=position,
        )

    # Rule 4: concept_illustration with TBD placeholder + tier ok →
    # emit a request.
    return Decision(
        slide_id=slide_id, layout=layout, emit=True,
        reason="concept_illustration layout is the AI-image vehicle",
        substory_id=substory_id, position=position,
    )


def _build_slide_id(substory_id: str, position: int) -> str:
    """Format the slide_id_target string per ai_image_prompt.v1.md
    convention. Empty substory_id (e.g., intro slides) → 'pos{N}'."""
    if substory_id:
        return f"{substory_id}-pos{position}"
    return f"pos{position}"


def decide_fragment(
    fragment: dict,
    *,
    tier: str,
    mode: str,
    user_opt_in_exploratory: bool = False,
) -> list[Decision]:
    """Apply decide() to every slide in a slide_compose fragment.

    A fragment is the JSON written by slide_compose.v1 to
    working/03_slides/<sid>_slides.json. Shape:
        {
          "schema_version": "...",
          "kind": "...",
          "substory_id": "S2",
          "slides": [ {layout, content, ...}, ... ]
        }

    `substory_id` is taken from the fragment top-level if present,
    else inferred from the kind. Position is the 0-indexed enumerate.
    """
    substory_id = fragment.get("substory_id", "")
    if not substory_id:
        # Intro fragments don't carry a substory_id; use kind as label.
        kind = fragment.get("kind", "")
        if kind == "intro":
            substory_id = "intro"
    decisions: list[Decision] = []
    for position, slide in enumerate(fragment.get("slides", [])):
        decisions.append(
            decide(
                slide,
                tier=tier,
                mode=mode,
                user_opt_in_exploratory=user_opt_in_exploratory,
                substory_id=substory_id,
                position=position,
            )
        )
    return decisions


def emit_decisions(
    slides_dir: Path,
    *,
    tier: str,
    mode: str,
    user_opt_in_exploratory: bool = False,
) -> dict:
    """Walk every fragment under slides_dir; return the
    image-decisions.v1 envelope. Caller writes the JSON.

    Skips fragments named cross_tenant.json / qa_anticipated.json / etc.
    that contain only structural slides — those are processed normally
    via decide_fragment, so their slides will all emit=False with a
    structural-no-image reason. No filtering needed at the caller level.
    """
    decisions: list[Decision] = []
    fragment_paths = sorted(slides_dir.glob("*.json"))
    for path in fragment_paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                fragment = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            # Surface to stderr; skip the fragment. A malformed fragment
            # is a problem for merge, not for the decision layer.
            print(
                f"image_gen_decision: warning — could not parse {path}: {e}",
                file=sys.stderr,
            )
            continue
        if not isinstance(fragment, dict):
            print(
                f"image_gen_decision: warning — {path} is not a JSON object; "
                f"skipping",
                file=sys.stderr,
            )
            continue
        decisions.extend(
            decide_fragment(
                fragment,
                tier=tier,
                mode=mode,
                user_opt_in_exploratory=user_opt_in_exploratory,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "mode": mode,
        "user_opt_in_exploratory": user_opt_in_exploratory,
        "decisions": [_decision_to_dict(d) for d in decisions],
    }


def _decision_to_dict(d: Decision) -> dict:
    return {
        "slide_id": d.slide_id,
        "substory_id": d.substory_id,
        "position": d.position,
        "layout": d.layout,
        "emit": d.emit,
        "reason": d.reason,
    }


def yes_decisions(decisions_envelope: dict) -> list[dict]:
    """Return only the emit=True decisions from an envelope.

    Used by the orchestrator to drive the per-slide image-prompt loop.
    """
    return [
        d for d in decisions_envelope.get("decisions", [])
        if d.get("emit") is True
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_emit_decisions(args: argparse.Namespace) -> int:
    slides_dir = Path(args.slides_dir).resolve()
    if not slides_dir.is_dir():
        print(
            f"image_gen_decision: error — --slides-dir not found: {slides_dir}",
            file=sys.stderr,
        )
        return 1
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = emit_decisions(
        slides_dir,
        tier=args.tier,
        mode=args.mode,
        user_opt_in_exploratory=bool(args.allow_exploratory),
    )
    out_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    n_yes = sum(1 for d in envelope["decisions"] if d["emit"])
    n_total = len(envelope["decisions"])
    print(
        f"image_gen_decision: wrote {out_path} "
        f"({n_yes}/{n_total} slides flagged for image-gen)",
        file=sys.stderr,
    )
    return 0


def _cmd_list_yes(args: argparse.Namespace) -> int:
    """Print emit=true slide_ids one per line. Used by the bash orchestrator
    to iterate over slides flagged for image-gen without re-parsing the
    decisions envelope from shell."""
    decisions_path = Path(args.decisions_path).resolve()
    if not decisions_path.is_file():
        print(
            f"image_gen_decision: error — decisions file not found: {decisions_path}",
            file=sys.stderr,
        )
        return 1
    try:
        envelope = json.loads(decisions_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(
            f"image_gen_decision: error — decisions JSON malformed: {e}",
            file=sys.stderr,
        )
        return 2
    for entry in yes_decisions(envelope):
        print(entry["slide_id"])
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="image_gen_decision",
        description="v0.3.3 deterministic image-gen decision layer.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_emit = sub.add_parser(
        "emit-decisions",
        help="Walk a slides-dir of fragments; emit image-decisions.v1 JSON.",
    )
    p_emit.add_argument("--slides-dir", required=True,
                        help="Path to working/03_slides/.")
    p_emit.add_argument("--tier", required=True,
                        choices=list(slide_spec.TIERS))
    p_emit.add_argument("--mode", required=True,
                        choices=list(slide_spec.MODES))
    p_emit.add_argument(
        "--allow-exploratory", action="store_true",
        help="Allow concept_illustration on EXPLORATORY tier (rule 6 inversion).",
    )
    p_emit.add_argument("--out", required=True,
                        help="Output path for image-decisions.v1 JSON.")
    p_emit.set_defaults(func=_cmd_emit_decisions)

    p_list = sub.add_parser(
        "list-yes",
        help="Print emit=true slide_ids from a decisions envelope, one per line.",
    )
    p_list.add_argument("decisions_path",
                        help="Path to image-decisions.v1 JSON file.")
    p_list.set_defaults(func=_cmd_list_yes)

    args = p.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
