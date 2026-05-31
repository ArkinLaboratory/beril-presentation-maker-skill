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
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

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
    # v0.7/D-086: deck_close is the closing-synthesis slot. Composer
    # reads structured fields verbatim from deck_close_signal.json
    # (unified_point + key_takeaways + forward_call + data_source);
    # adding an AI image would conflict with the "verbatim from
    # curator" contract + the 3-5 key_takeaways bullet structure
    # already fills the slide body.
    "deck_close",
})

_HAS_OWN_FIGURE = frozenset({
    "data_figure",
    "data_table",
})

# Layouts where a supplemental image MIGHT help — judged per-slide by
# the LLM-judgment layer (v0.3.7+) rather than deterministically. When
# called without a `judge_fn`, decide() falls back to emit=False with
# a reason indicating the judgment was skipped (preserving pre-v0.3.7
# conservative behavior for non-CLI callers and tests).
#
# Live failure that motivated wiring this up: ibd_phage_targeting
# talk-45 hub run 2026-05-06 — 15 of 33 candidate slides were in this
# set, all returned emit=false, deck shipped 0 AI illustrations
# despite mode=talk-45 with 6 substantive substories that would have
# benefited from conceptual visuals (mechanism cartoons, framework
# diagrams, cocktail-strategy schematics). See V0_4_0_PUNCH_LIST.md
# task #90.
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


# Type alias: judge_fn callbacks take a slide_stub + tier/mode context and
# return (emit, reason). Used to inject the LLM-judgment layer (or a stub
# in tests) without coupling decide() to subprocess.
JudgeFn = Callable[[dict, str, str], tuple[bool, str]]


# v0.7/D-088 Tier D.0: minimum bullet count for claim_evidence to be
# image-eligible. Adam Tier-0 DQ4: "claim_evidence with ≥3 distinct
# bullets" — the structure that maps naturally to multi-panel diagram
# illustration (e.g. "three mechanisms", "four phases"). Below this,
# the slide is a short claim that doesn't benefit from panel-diagram
# AI illustration; skip the judge call (saves ~$0.005 per skipped
# slide and prevents the judge from approving generic art for a 2-bullet
# claim that the audience can read at a glance).
_MIN_CLAIM_EVIDENCE_BULLETS_FOR_IMAGE: int = 3


def _count_distinct_bullets(slide_stub: dict) -> int:
    """Count usable bullets on a claim_evidence slide.

    A bullet "counts" if it's a non-empty string (or a dict with a
    non-empty `claim` / `text` field — claim_evidence supports both
    shapes per slide_spec). Empty strings and structurally-invalid
    entries don't count.

    v0.7 ships count-only; the semantic "distinctness" check (are
    these three bullets describing different concepts vs near-
    duplicates?) is delegated to the LLM judge's technical-specificity
    criterion per D-088. Pure mechanical count here keeps the pre-
    filter cheap + predictable. v0.8+ may upgrade to a heuristic
    distinctness check if v0.7 live-A/B surfaces false positives.
    """
    content = slide_stub.get("content", {})
    if not isinstance(content, dict):
        return 0
    bullets = content.get("bullets", [])
    if not isinstance(bullets, list):
        return 0
    count = 0
    for b in bullets:
        if isinstance(b, str) and b.strip():
            count += 1
        elif isinstance(b, dict):
            text = b.get("claim") or b.get("text") or ""
            if isinstance(text, str) and text.strip():
                count += 1
    return count


def decide(
    slide_stub: dict,
    *,
    tier: str,
    mode: str,
    user_opt_in_exploratory: bool = False,
    substory_id: str = "",
    position: int = -1,
    judge_fn: Optional[JudgeFn] = None,
) -> Decision:
    """Apply the deterministic decision rules to one slide stub.

    Args:
      slide_stub: parsed slide dict from working/03_slides/<sid>_slides.json.
        Must have "layout" key. "content" is read for image_path on
        concept_illustration slides (verifies the "{TBD}" marker is
        present — its absence means slide_compose already-resolved
        the image, e.g., from cache, and we should not re-generate).
      tier: STRONG | THIN | EXPLORATORY (slide_spec.TIERS).
      mode: talk-30 | talk-15 | etc. (informational; no deterministic
        rule depends on it but the LLM-judgment layer reads it as input).
      user_opt_in_exploratory: if True, allow concept_illustration on
        EXPLORATORY tier. Default False (rule 6).
      substory_id, position: pass-through context for the Decision record.
      judge_fn: callable to consult for layouts in _DEFERRED_LLM_DECISION.
        Signature: (slide_stub, tier, mode) -> (emit_bool, reason_str).
        When None (default), deferred layouts return emit=False with a
        "no LLM judge available" reason. Pass `llm_judge` for the live
        Sonnet-driven judgment, or a stub for tests. v0.3.7+ wires
        llm_judge as the CLI default when claude is on PATH.

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

    # Rule 5: deferred to LLM judgment. v0.3.7+ consults judge_fn (typically
    # llm_judge invoking claude -p with a per-slide judgment prompt). If no
    # judge_fn is provided, fall back to the pre-v0.3.7 conservative behavior
    # (emit=False with a reason indicating the judgment was skipped). Tests
    # pass stub callbacks; the bash orchestrator passes llm_judge.
    if layout in _DEFERRED_LLM_DECISION:
        # v0.7/D-088 Tier D.0: pre-filter claim_evidence on bullet count.
        # Per Adam Tier-0 DQ4: claim_evidence is eligible ONLY when it has
        # ≥3 distinct bullets (a "three mechanisms" / "four phases" /
        # "five categories" structure that maps naturally to a multi-
        # panel diagram). Slides with <3 bullets are short claims that
        # don't benefit from a panel-diagram-shaped AI illustration; skip
        # the judge call to save its cost.
        # "Distinct" is enforced by the judge's new technical-specificity
        # criterion in _build_judge_prompt — a slide with 3 near-
        # identical bullets fails the judge's distinctness bar. The
        # mechanical pre-filter is just the count; the LLM handles the
        # semantic distinctness call.
        if layout == "claim_evidence":
            bullet_count = _count_distinct_bullets(slide_stub)
            if bullet_count < _MIN_CLAIM_EVIDENCE_BULLETS_FOR_IMAGE:
                return Decision(
                    slide_id=slide_id, layout=layout, emit=False,
                    reason=(
                        f"claim_evidence has {bullet_count} bullet(s); "
                        f"per D-088 needs ≥{_MIN_CLAIM_EVIDENCE_BULLETS_FOR_IMAGE} "
                        f"distinct bullets to be image-eligible (short "
                        f"claims don't fit panel-diagram illustration)"
                    ),
                    substory_id=substory_id, position=position,
                )
        if judge_fn is None:
            return Decision(
                slide_id=slide_id, layout=layout, emit=False,
                reason=(
                    f"{layout} supplemental-image decision needs LLM "
                    f"judgment but no judge_fn was provided; default no"
                ),
                substory_id=substory_id, position=position,
            )
        try:
            emit, reason = judge_fn(slide_stub, tier, mode)
        except Exception as e:
            # LLM judgment is advisory — never crash the decision pipeline
            # over a failed judgment. Default to conservative no with the
            # error surfaced in the reason for downstream visibility.
            return Decision(
                slide_id=slide_id, layout=layout, emit=False,
                reason=f"LLM judgment failed ({type(e).__name__}); default no",
                substory_id=substory_id, position=position,
            )
        return Decision(
            slide_id=slide_id, layout=layout, emit=bool(emit),
            reason=f"LLM-judged: {reason}",
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
    judge_fn: Optional[JudgeFn] = None,
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

    `judge_fn` (v0.3.7+) is forwarded to decide() for deferred-layout
    decisions; see decide() for semantics.
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
                judge_fn=judge_fn,
            )
        )
    return decisions


def emit_decisions(
    slides_dir: Path,
    *,
    tier: str,
    mode: str,
    user_opt_in_exploratory: bool = False,
    judge_fn: Optional[JudgeFn] = None,
) -> dict:
    """Walk every fragment under slides_dir; return the
    image-decisions.v1 envelope. Caller writes the JSON.

    Skips fragments named cross_tenant.json / qa_anticipated.json / etc.
    that contain only structural slides — those are processed normally
    via decide_fragment, so their slides will all emit=False with a
    structural-no-image reason. No filtering needed at the caller level.

    `judge_fn` (v0.3.7+) is forwarded to decide_fragment(); the CLI
    `_cmd_emit_decisions` wires `llm_judge` as the default when claude is
    on PATH (or `None` when --no-llm-judge is passed).
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
                judge_fn=judge_fn,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "mode": mode,
        "user_opt_in_exploratory": user_opt_in_exploratory,
        "llm_judgment_used": judge_fn is not None,
        "decisions": [_decision_to_dict(d) for d in decisions],
    }


# ---------------------------------------------------------------------------
# v0.3.7+ LLM-judgment layer
# ---------------------------------------------------------------------------

# Default model for per-slide judgment calls. Sonnet 4.6 is the cheap default;
# overridable via the CLI / function argument. Each judgment call costs
# ~$0.005-0.01, so 15 deferred slides per draft → ~$0.10-0.20 added cost.
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"

# Per-call timeout (seconds). Sonnet typically returns in 2-5s for a short
# prompt; 60s is generous and prevents a stuck call from hanging the whole
# decision pass.
JUDGE_TIMEOUT_SEC = 60

# Bounded max length on the content summary we feed into the judgment prompt.
# Keeps the prompt small (~300 tokens) regardless of how content-rich the
# slide is. The model only needs the gist to decide whether an illustration
# would add value.
_CONTENT_SUMMARY_MAX_CHARS = 800


def _summarize_slide_for_judgment(slide_stub: dict) -> str:
    """Produce a compact, human-readable summary of slide content for the
    judgment prompt. Keeps within _CONTENT_SUMMARY_MAX_CHARS so we don't
    blow up the prompt token count on bullet-rich slides."""
    layout = slide_stub.get("layout", "?")
    content = slide_stub.get("content", {})
    parts: list[str] = []

    # Title is the most informative single field for most layouts.
    title = content.get("title") or content.get("headline") or content.get("punchline") or ""
    if title:
        parts.append(f"Title: {title}")

    # Bullets / body content (claim_evidence, methods_summary, implications, etc.)
    bullets = content.get("bullets", [])
    if isinstance(bullets, list) and bullets:
        bullet_strs = []
        for b in bullets[:4]:  # cap at first 4 bullets
            if isinstance(b, str):
                bullet_strs.append(b)
            elif isinstance(b, dict):
                bullet_strs.append(b.get("claim", "") or b.get("text", ""))
        if bullet_strs:
            parts.append("Bullets: " + " | ".join(bullet_strs))

    # Subtitle / sub_pointer (big_idea, big_number)
    for k in ("subtitle", "sub_pointer", "headline"):
        v = content.get(k)
        if v and isinstance(v, str) and v != title:
            parts.append(f"{k}: {v}")

    # two_column_compare specifics
    if layout == "two_column_compare":
        for col in ("left_col_title", "right_col_title"):
            v = content.get(col)
            if v:
                parts.append(f"{col}: {v}")

    # workflow_diagram step captions
    if layout == "workflow_diagram":
        steps = content.get("step_caption", [])
        if isinstance(steps, list) and steps:
            parts.append("Steps: " + " → ".join(s for s in steps if isinstance(s, str)))

    summary = "\n".join(parts)
    if len(summary) > _CONTENT_SUMMARY_MAX_CHARS:
        summary = summary[:_CONTENT_SUMMARY_MAX_CHARS - 3] + "..."
    return summary


def _build_judge_prompt(slide_stub: dict, tier: str, mode: str) -> str:
    """Construct the per-slide judgment prompt sent to claude -p.

    v0.7/D-088 Tier D.0 extension: adds a "technical-specificity"
    criterion (the load-bearing change from v0.6 Tier-F D-084 finding
    4 "AI images generic / too conceptual"). The judge MUST now think
    of the eventual generated image's content and reject when that
    content would necessarily be generic / abstract / metaphorical
    rather than technically specific to the slide's substance.

    For claim_evidence specifically (the new D-088 eligibility class),
    the judge needs to envision a multi-panel diagram with labeled
    technical elements (mechanism names, method outputs, statistics);
    reject if no such concrete content is graspable from the slide's
    bullets.
    """
    layout = slide_stub.get("layout", "?")
    summary = _summarize_slide_for_judgment(slide_stub)
    return (
        "You are deciding whether a slide in a scientific presentation "
        "would benefit from a generated AI illustration as a supplemental "
        "visual aid, ON TOP OF whatever text/bullets the layout already "
        "carries. The illustration would be a small conceptual graphic "
        "(metaphor, mechanism cartoon, framework diagram) — not a data "
        "figure, not a photograph, not a logo.\n\n"
        f"SLIDE LAYOUT: {layout}\n"
        f"PRESENTATION MODE: {mode}\n"
        f"EVIDENCE TIER: {tier}\n"
        f"SLIDE CONTENT:\n{summary}\n\n"
        "DECISION CRITERIA:\n"
        "  - YES if the slide presents a CONCEPT (mechanism, framework, "
        "    abstraction, comparison) that a small illustration would "
        "    help an audience grasp faster than reading bullets.\n"
        "  - YES if it's an opening claim or section pivot that benefits "
        "    from a memorable visual hook.\n"
        "  - NO if the slide is data-heavy and an illustration would "
        "    compete with the data.\n"
        "  - NO if the slide is structural / process-oriented (workflow "
        "    steps already captioned, methods bullets, comparisons of "
        "    quantitative columns).\n"
        "  - NO if the slide content is so specific that a generic AI "
        "    illustration cannot meaningfully represent it.\n"
        "  - When uncertain, prefer NO (illustrations cost ~$0.014 each "
        "    and over-illustration distracts).\n\n"
        "TECHNICAL-SPECIFICITY CRITERION (v0.7 / D-088 — Tier D.0):\n"
        "  This criterion exists because v0.6 Tier-F (D-084 finding 4)\n"
        "  surfaced that AI images were 'generic / too conceptual'.\n"
        "  But the v0.7 Tier-G live read showed an over-strict criterion\n"
        "  rejects EVERY candidate (judge approved 0/30 ibd + 0/36 fdm\n"
        "  on the first v0.7 run). The fix (v0.7 Tier I) is to keep\n"
        "  the bar but relax 'concrete technical' to allow domain-\n"
        "  anchored metaphors — illustrations that name SOMETHING\n"
        "  specific to the slide's domain, even when they're stylized.\n"
        "\n"
        "  Approve if you can describe at least one domain-anchored\n"
        "  visual element the illustration would contain — a named\n"
        "  mechanism, a recognized molecular structure, a method-shape\n"
        "  the audience would recognize, a numbered framework, etc.\n"
        "  The element doesn't have to be Nature-figure-quality; it\n"
        "  just has to NAME something specific the slide is about.\n"
        "\n"
        "  Reject ONLY when the most-charitable image you can envision\n"
        "  would still be a pure abstraction without ANY domain anchor\n"
        "  (e.g. unlabeled colored shapes, generic 'data flowing'\n"
        "  arrows with no named source/destination, abstract\n"
        "  microbiome-as-circles patterns with no named species). The\n"
        "  null case for rejection: 'I cannot name a single thing this\n"
        "  image would contain that ties to the slide's specific\n"
        "  content.'\n"
        "\n"
        "  For claim_evidence slides with a 'three mechanisms' / 'four\n"
        "  phases' / 'N categories' structure: approve if you can name\n"
        "  AT LEAST ONE panel's content (not all of them) in domain-\n"
        "  specific terms. A 3-panel diagram where panel 1 names a\n"
        "  specific mechanism is good enough; you don't need to\n"
        "  pre-author all three panels at judge time.\n\n"
        "Respond with EXACTLY ONE LINE in this format:\n"
        "  YES <one-clause reason naming the concrete technical elements>\n"
        "or\n"
        "  NO <one-clause reason naming why it would be generic>\n"
        "Do not output anything else. Do not use markdown. The first word "
        "of your response must be YES or NO (uppercase)."
    )


def _parse_judge_response(text: str) -> tuple[bool, str]:
    """Parse the LLM response into (emit, reason). Permissive on framing
    but strict on the YES/NO prefix. Falls back to (False, reason) on
    unparseable responses (defensive default — over-illustration is
    worse than under-illustration)."""
    if not text:
        return False, "empty LLM response; default no"
    line = text.strip().splitlines()[0].strip()
    upper = line.upper()
    if upper.startswith("YES"):
        reason = line[3:].strip(" :-—–").strip()
        return True, reason or "LLM said yes (no reason given)"
    if upper.startswith("NO"):
        reason = line[2:].strip(" :-—–").strip()
        return False, reason or "LLM said no (no reason given)"
    # Unparseable — surface the head of the response in the reason for
    # debugging, default to no.
    truncated = line[:100] + ("..." if len(line) > 100 else "")
    return False, f"LLM response unparseable ({truncated!r}); default no"


def llm_judge(
    slide_stub: dict,
    tier: str,
    mode: str,
    *,
    model: str = DEFAULT_JUDGE_MODEL,
    timeout_sec: int = JUDGE_TIMEOUT_SEC,
) -> tuple[bool, str]:
    """Per-slide LLM judgment. Synchronous claude -p call.

    Returns (emit, reason). Defensive: returns (False, reason) on any
    failure mode (claude not on PATH, subprocess error, timeout,
    unparseable response). The deferred-layout decision branch in
    decide() also catches exceptions, but llm_judge itself prefers
    to return a Decision-friendly tuple over raising.

    Usage:
        from image_gen_decision import llm_judge, decide
        d = decide(slide_stub, tier="STRONG", mode="talk-30",
                   judge_fn=llm_judge)

    Cost: ~$0.005-0.01 per call (Sonnet, ~300 token prompt + ~30 token
    response). Latency: 2-5s typical, 60s timeout.
    """
    if shutil.which("claude") is None:
        return False, "claude CLI not on PATH; default no"

    prompt = _build_judge_prompt(slide_stub, tier, mode)

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", model,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return False, f"LLM call timed out after {timeout_sec}s; default no"
    except (OSError, ValueError) as e:
        return False, f"LLM subprocess error ({type(e).__name__}); default no"

    if result.returncode != 0:
        # Claude exited non-zero. Return defensive default with the rc
        # surfaced for debugging.
        stderr_head = (result.stderr or "").strip()[:120]
        return False, (
            f"claude -p exited rc={result.returncode}"
            + (f" ({stderr_head!r})" if stderr_head else "")
            + "; default no"
        )

    return _parse_judge_response(result.stdout)


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

    # v0.3.7+: wire llm_judge as the default judge_fn when claude is on
    # PATH. --no-llm-judge opts out (preserves pre-v0.3.7 conservative
    # behavior — every deferred-layout slide gets emit=false).
    if args.no_llm_judge:
        judge_fn: Optional[JudgeFn] = None
        print(
            "image_gen_decision: --no-llm-judge set; deferred layouts "
            "default to no AI image",
            file=sys.stderr,
        )
    elif shutil.which("claude") is None:
        judge_fn = None
        print(
            "image_gen_decision: claude CLI not on PATH; deferred layouts "
            "default to no AI image (pass --no-llm-judge to suppress this "
            "message, or install claude to enable per-slide judgment)",
            file=sys.stderr,
        )
    else:
        # Bind the judge model from the CLI flag (default: Sonnet 4.6).
        model = args.judge_model
        def judge_fn(slide_stub, tier, mode, _model=model):  # noqa: E306
            return llm_judge(slide_stub, tier, mode, model=_model)
        print(
            f"image_gen_decision: LLM-judgment enabled for deferred layouts "
            f"(model={model}). Pass --no-llm-judge to disable.",
            file=sys.stderr,
        )

    envelope = emit_decisions(
        slides_dir,
        tier=args.tier,
        mode=args.mode,
        user_opt_in_exploratory=bool(args.allow_exploratory),
        judge_fn=judge_fn,
    )
    out_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    n_yes = sum(1 for d in envelope["decisions"] if d["emit"])
    n_total = len(envelope["decisions"])
    n_llm = sum(
        1 for d in envelope["decisions"]
        if d["reason"].startswith("LLM-judged: ")
    )
    print(
        f"image_gen_decision: wrote {out_path} "
        f"({n_yes}/{n_total} slides flagged for image-gen; "
        f"{n_llm} via LLM judgment)",
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
    p_emit.add_argument(
        "--no-llm-judge", action="store_true",
        help=(
            "Disable the v0.3.7+ LLM-judgment layer. Deferred-layout "
            "slides (claim_evidence, big_idea, big_number, "
            "workflow_diagram, two_column_compare, implications) "
            "default to emit=false. Use this to reproduce pre-v0.3.7 "
            "conservative behavior or run without claude on PATH."
        ),
    )
    p_emit.add_argument(
        "--judge-model", default=DEFAULT_JUDGE_MODEL,
        help=(
            f"Model used for per-slide LLM judgment calls. "
            f"Default: {DEFAULT_JUDGE_MODEL}. Per-call cost ~$0.005-0.01."
        ),
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
