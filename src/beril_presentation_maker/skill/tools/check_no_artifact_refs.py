#!/usr/bin/env python3
"""check_no_artifact_refs.py — flag internal artifact references on slides.

Mechanical post-checker for presentation-maker. Walks slide_spec.json,
extracts text from slide content + speaker_notes, and matches against
regex patterns for internal-project artifact references that have no
business appearing on a peer-facing slide:

  - Notebook IDs:        NB01b, NB04c-e, NB07 v1.8, ...
  - Notebook filenames:  NB04h_hmp2_external_replication.ipynb
  - REPORT.md sections:  REPORT.md §Pillar 2 opener #6, REPORT §16 NB09b
  - Data file paths:     data/nb09b_theme_replication.tsv,
                         data/nb05_tier_a_scored.tsv
  - Pillar / section codes: §Pillar 2, §Pillar 3
  - Analysis-layer abbreviations: A16, H3c, L13 (project-internal jargon)

Why this exists (v0.3.8)
  Live test of the v0.3.6 ibd_phage_targeting talk-45 deck (37 slides)
  surfaced ~11 slides leaking these patterns into bullet text, captions,
  and speaker notes. Verbatim examples flagged by the memoryless
  reviewer:
    - "REPORT.md §Pillar 2 opener #6; NB04h_hmp2_external_replication.ipynb"
    - "Five-layer pipeline ... NB01b ... NB02 ... NB04c-e"
    - "data/nb05_tier_a_scored.tsv"
    - "OR=44.4 is an upper bound: catalog-wide comparator inflates
       enrichment (L13); E. coli-specificity qualitatively robust
       across comparator choices. H3c interaction-term test not run"

  These artifacts are useful inside the project's documentation chain but
  unreadable to peer audiences. The post-checker flags them so authors
  hand-edit before showing the deck publicly.

What this is NOT
  - Not a citation-quality checker. Whether a citation supports the claim
    is judgment.
  - Not a register checker. Whether wording is appropriate is judgment.
  - Not a content checker. The slide may be otherwise correct; it just
    needs its citations replaced with peer-readable forms.

Output
  - <draft_dir>/audit/no_artifact_refs.md (human-readable)
  - <draft_dir>/audit/no_artifact_refs.json (machine-readable)

Exit codes
  0 — zero hits (clean) OR hits found but ADVISORY mode (default)
  1 — hits found AND --strict mode (orchestrator-callable for CI)
  2 — runtime error (missing inputs, malformed JSON)

False positives accepted
  - "TL1", "S1", "S2" et al. — substory and throughline IDs are
    legitimate project structure, not internal artifacts. Whitelisted
    via shape (TL\\d+ / S\\d+) so they're not caught by the generic
    [A-Z]\\d+ pattern.
  - Citation years like "2024" — the existing year filter from
    check_quantitative_grounding doesn't apply here; we look for
    artifact patterns directly, not arbitrary numbers.
  - Method names with embedded digits ("MetaPhlAn3", "GTDB r214") —
    not in our patterns; should be fine.
  - True false positive risk: "p<0.001" or other statistical notation
    that happens to resemble a code (unlikely; our patterns are
    specific to NB / REPORT / data/ prefixes).

Usage
  check_no_artifact_refs.py <draft_dir> [--strict] [--quiet] [--json-only]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------

# Each pattern has: a regex, a category label, and a one-sentence
# explanation of why it's an artifact reference (used in the report).
#
# Patterns are intentionally tight — false positives are worse than
# missed hits because they erode trust in the post-checker.

@dataclass(frozen=True)
class ArtifactPattern:
    name: str           # human-readable category
    regex: re.Pattern   # compiled pattern (case-sensitive unless noted)
    explanation: str    # why it's flagged
    suggestion: str     # what to do instead


_PATTERNS: tuple[ArtifactPattern, ...] = (
    ArtifactPattern(
        name="notebook-id",
        # Match NB followed by digits, optionally followed by lowercase letter
        # qualifier (NB04b), optional version (v1.8), or range (NB04c-e).
        # \\b boundary on the left so we don't match e.g. "MNBK". Trailing \\b
        # on the right catches "NB01b" + "NB04c-e" (the dash-letter run is
        # captured by the optional [a-z]-[a-z] segment).
        regex=re.compile(
            r"\bNB\d+(?:[a-z](?:[-–][a-z])?)?(?:\s+v\d+(?:\.\d+)*)?\b"
        ),
        explanation=(
            "Notebook ID (project-internal). Peer audiences don't read "
            "your notebook inventory."
        ),
        suggestion=(
            "Replace with the cohort + sample size + primary author/year, "
            "e.g. 'NB04h' → 'Lloyd-Price 2019 (HMP2 cohort, n=1,627)'."
        ),
    ),
    ArtifactPattern(
        name="notebook-file",
        # Note: character class includes 0-9 because notebook filenames
        # frequently embed digits (e.g., NB04h_hmp2_external.ipynb,
        # NB07-v18.ipynb). Without 0-9 the regex would stop at the
        # first digit in the suffix.
        regex=re.compile(r"\bNB\d+[a-zA-Z0-9_-]*\.ipynb\b"),
        explanation=(
            "Notebook filename (project-internal). Belongs in audit/ logs, "
            "not on slides."
        ),
        suggestion=(
            "Move the path to <draft_dir>/audit/ and replace the slide "
            "citation with the underlying paper or cohort reference."
        ),
    ),
    ArtifactPattern(
        name="data-tsv-path",
        regex=re.compile(r"\bdata/[A-Za-z0-9_/-]+\.(?:tsv|csv|json|parquet)\b"),
        explanation=(
            "Internal data-file path. Peer audiences can't access it; "
            "what they need is the figure / number that came from it."
        ),
        suggestion=(
            "Drop the path. If the data is shareable, cite the supplementary "
            "table or the published dataset; otherwise just state the result."
        ),
    ),
    ArtifactPattern(
        name="report-md-section",
        # REPORT.md or REPORT (no .md) followed by optional § + identifier
        # (e.g., "§Pillar 2 opener #6", "§16 NB09b", "section 4")
        regex=re.compile(
            r"\bREPORT(?:\.md)?(?:\s+§[^\s.,;]+(?:\s+[^\s.,;]+){0,4})?\b"
        ),
        explanation=(
            "Reference to REPORT.md (project-internal documentation). "
            "Peers don't have access to your REPORT."
        ),
        suggestion=(
            "Replace with the underlying citation (paper + author + year) "
            "or, if the result is original to this project, present it "
            "directly without the meta-citation."
        ),
    ),
    ArtifactPattern(
        name="pillar-section",
        # §Pillar followed by digit (sometimes with words after)
        # — a project-internal organizing concept, not peer-readable
        regex=re.compile(r"§Pillar\s+\d+\b"),
        explanation=(
            "'§Pillar' is the project's internal section vocabulary. "
            "Peers don't know what Pillar 2 is."
        ),
        suggestion=(
            "Replace with the actual claim or method; pillars are an "
            "organizing aid for the project team, not a citation."
        ),
    ),
    ArtifactPattern(
        name="analysis-layer-code",
        # Patterns like A16, H3c, L13, E1, E3 — single uppercase letter +
        # digit(s), optionally followed by a single lowercase letter.
        # Used in this project as analysis-layer abbreviations.
        #
        # Whitelist: TL\\d+ (throughline IDs), S\\d+ (substory IDs) are
        # legitimate project structure that DOES appear in slide IDs and
        # references; not flagged.
        regex=re.compile(r"\b(?!TL\d|S\d)[A-Z]\d+[a-z]?\b"),
        explanation=(
            "Looks like a project-internal analysis-layer code (A16, H3c, "
            "L13). Reads as jargon to peers; the underlying claim is what "
            "they need."
        ),
        suggestion=(
            "Replace with what the code REFERS TO — e.g., 'L13' → "
            "'comparator-choice sensitivity analysis'. If the code is "
            "defined elsewhere on the deck, define it inline; if not, "
            "state the actual finding."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Slide-text traversal (mirrors check_quantitative_grounding._collect_slide_text)
# ---------------------------------------------------------------------------

# Slide content fields that contain prose-form text.
_TEXT_FIELDS = (
    "title", "headline", "subtitle", "punchline",
    "caption", "data_source", "answer_summary", "answer_detail",
    "evidence_pointer", "claim",
    "image_prompt",  # concept_illustration prompt text
)
_LIST_FIELDS = (
    "bullets", "tenant_list", "kberdl_db_list", "step_caption",
    "refs_short", "contributors",
)


@dataclass(frozen=True)
class SlideTextSpan:
    """One labeled span of text from a slide, suitable for regex scanning."""
    location: str   # "title", "bullets[2]", "speaker_notes", etc.
    text: str

    def to_dict(self) -> dict:
        return {"location": self.location, "text": self.text}


def _collect_slide_spans(slide: dict) -> list[SlideTextSpan]:
    """Walk a slide and collect (location, text) spans for every prose-
    bearing field. Per-field labels make findings actionable
    ('hit in bullets[2]' vs 'hit in caption')."""
    spans: list[SlideTextSpan] = []
    content = slide.get("content", {})
    for field_name in _TEXT_FIELDS:
        val = content.get(field_name)
        if isinstance(val, str) and val:
            spans.append(SlideTextSpan(location=field_name, text=val))
    for field_name in _LIST_FIELDS:
        val = content.get(field_name)
        if isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, str):
                    spans.append(SlideTextSpan(
                        location=f"{field_name}[{i}]", text=item,
                    ))
                elif isinstance(item, dict):
                    # bullets-as-objects (implications layout): {claim, evidence_pointer}
                    for k in ("claim", "evidence_pointer"):
                        v = item.get(k)
                        if isinstance(v, str) and v:
                            spans.append(SlideTextSpan(
                                location=f"{field_name}[{i}].{k}", text=v,
                            ))
    # Speaker notes are a slide-level field, not under content.
    notes = slide.get("speaker_notes")
    if isinstance(notes, str) and notes:
        spans.append(SlideTextSpan(location="speaker_notes", text=notes))
    return spans


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    """One artifact-reference hit on a slide."""
    slide_id: int | None
    slide_position: int        # 0-indexed position in slides[]
    slide_layout: str
    location: str              # field where the match occurred
    pattern_name: str          # which ArtifactPattern caught it
    matched_text: str          # the exact substring that matched
    context: str               # ±30 chars around the match
    explanation: str
    suggestion: str

    def to_dict(self) -> dict:
        return {
            "slide_id": self.slide_id,
            "slide_position": self.slide_position,
            "slide_layout": self.slide_layout,
            "location": self.location,
            "pattern": self.pattern_name,
            "matched_text": self.matched_text,
            "context": self.context,
            "explanation": self.explanation,
            "suggestion": self.suggestion,
        }


@dataclass
class CheckReport:
    draft_dir: Path
    schema_version: str = "no-artifact-refs.v1"
    n_slides: int = 0
    n_slides_with_hits: int = 0
    n_total_hits: int = 0
    hits_by_pattern: dict = field(default_factory=dict)  # name → count
    hits: list[Hit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "draft_dir": str(self.draft_dir),
            "n_slides": self.n_slides,
            "n_slides_with_hits": self.n_slides_with_hits,
            "n_total_hits": self.n_total_hits,
            "hits_by_pattern": self.hits_by_pattern,
            "hits": [h.to_dict() for h in self.hits],
        }


def _make_context(text: str, start: int, end: int, window: int = 30) -> str:
    """Excerpt ±window chars around the match. Replace newlines with spaces
    for one-line context display."""
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    excerpt = text[lo:hi].replace("\n", " ").replace("\r", " ")
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"


def scan_slide(slide: dict, slide_position: int) -> list[Hit]:
    """Return all ArtifactPattern hits on one slide."""
    slide_id = slide.get("id")
    layout = slide.get("layout", "?")
    hits: list[Hit] = []
    for span in _collect_slide_spans(slide):
        for pattern in _PATTERNS:
            for m in pattern.regex.finditer(span.text):
                hits.append(Hit(
                    slide_id=slide_id if isinstance(slide_id, int) else None,
                    slide_position=slide_position,
                    slide_layout=layout,
                    location=span.location,
                    pattern_name=pattern.name,
                    matched_text=m.group(0),
                    context=_make_context(span.text, m.start(), m.end()),
                    explanation=pattern.explanation,
                    suggestion=pattern.suggestion,
                ))
    return hits


def scan_slide_spec(spec: dict, draft_dir: Path) -> CheckReport:
    """Walk slide_spec.json's slides and produce a CheckReport."""
    slides = spec.get("slides") or []
    report = CheckReport(draft_dir=draft_dir)
    report.n_slides = len(slides)

    slides_with_hits: set[int] = set()
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue
        slide_hits = scan_slide(slide, slide_position=i)
        if slide_hits:
            slides_with_hits.add(i)
            report.hits.extend(slide_hits)

    report.n_slides_with_hits = len(slides_with_hits)
    report.n_total_hits = len(report.hits)
    for h in report.hits:
        report.hits_by_pattern[h.pattern_name] = (
            report.hits_by_pattern.get(h.pattern_name, 0) + 1
        )
    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_markdown(report: CheckReport) -> str:
    """Human-readable findings report for inclusion in the draft's audit/."""
    lines: list[str] = []
    lines.append("# Process-detail bleed check")
    lines.append("")
    lines.append(
        f"Scanned {report.n_slides} slides for internal-artifact references "
        f"(notebook IDs, file paths, REPORT.md sections, analysis-layer "
        f"codes). These patterns make the deck unreadable to fresh peer "
        f"audiences."
    )
    lines.append("")
    lines.append(f"- **Total hits:** {report.n_total_hits}")
    lines.append(
        f"- **Slides with hits:** {report.n_slides_with_hits}/{report.n_slides}"
    )
    if report.hits_by_pattern:
        lines.append("- **Hits by pattern:**")
        for name, n in sorted(
            report.hits_by_pattern.items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"  - `{name}`: {n}")
    lines.append("")

    if not report.hits:
        lines.append("✓ No artifact references found. The deck reads cleanly "
                     "for peer audiences (at least mechanically).")
        return "\n".join(lines) + "\n"

    # Group hits by slide for readable output.
    by_slide: dict[int, list[Hit]] = {}
    for h in report.hits:
        by_slide.setdefault(h.slide_position, []).append(h)

    lines.append("## Per-slide hits")
    lines.append("")
    for pos in sorted(by_slide.keys()):
        slide_hits = by_slide[pos]
        first = slide_hits[0]
        sid = (
            f"slide_id={first.slide_id}"
            if first.slide_id is not None else "(no slide_id)"
        )
        lines.append(
            f"### Slide {pos} — {first.slide_layout} ({sid})"
        )
        lines.append("")
        for h in slide_hits:
            lines.append(
                f"- **{h.pattern_name}** in `{h.location}`: "
                f"`{h.matched_text}`"
            )
            lines.append(f"  - Context: `{h.context}`")
            lines.append(f"  - Why: {h.explanation}")
            lines.append(f"  - Fix: {h.suggestion}")
        lines.append("")

    lines.append("## Recommended hand-edit pass")
    lines.append("")
    lines.append(
        "Open the .pptx in PowerPoint or LibreOffice. For each hit above, "
        "replace the matched text with peer-readable evidence (cohort + "
        "sample size + primary author/year for citations; "
        "actual claim or method name for analysis-layer codes; nothing "
        "for file paths)."
    )
    lines.append("")
    lines.append(
        "This check is **advisory** — the orchestrator does not block on "
        "hits. It exists to surface a class of writing failure that "
        "consistently slips past the writer prompts."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

def check_artifact_refs(draft_dir: Path) -> CheckReport:
    """Read <draft_dir>/working/slide_spec.json and run the checker."""
    spec_path = draft_dir / "working" / "slide_spec.json"
    if not spec_path.is_file():
        raise FileNotFoundError(
            f"slide_spec.json not found at {spec_path}; "
            f"run merge stage before this checker"
        )
    with spec_path.open(encoding="utf-8") as f:
        spec = json.load(f)
    return scan_slide_spec(spec, draft_dir)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_no_artifact_refs",
        description=(
            "Flag internal-artifact references on presentation-maker slides. "
            "Advisory by default; exit 1 on hits in --strict mode."
        ),
    )
    p.add_argument(
        "draft_dir",
        help="Path to a draft_N directory (must contain working/slide_spec.json).",
    )
    p.add_argument(
        "--strict", action="store_true",
        help=(
            "Exit 1 if any hits are found (for orchestrators / CI). "
            "Default: exit 0 (advisory) — let the user hand-edit."
        ),
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress the human-readable summary on stderr.",
    )
    p.add_argument(
        "--json-only", action="store_true",
        help="Skip writing the .md report; emit only the .json.",
    )
    args = p.parse_args(argv)

    draft_dir = Path(args.draft_dir).resolve()
    if not draft_dir.is_dir():
        print(
            f"check_no_artifact_refs: error — draft_dir not found: {draft_dir}",
            file=sys.stderr,
        )
        return 2

    try:
        report = check_artifact_refs(draft_dir)
    except FileNotFoundError as e:
        print(f"check_no_artifact_refs: error — {e}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, OSError) as e:
        print(
            f"check_no_artifact_refs: error reading slide_spec.json: {e}",
            file=sys.stderr,
        )
        return 2

    audit_dir = draft_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    json_path = audit_dir / "no_artifact_refs.json"
    md_path = audit_dir / "no_artifact_refs.md"

    json_path.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    if not args.json_only:
        md_path.write_text(render_markdown(report), encoding="utf-8")

    if not args.quiet:
        if report.n_total_hits == 0:
            print(
                f"check_no_artifact_refs: ✓ {report.n_slides} slides clean "
                f"(no artifact references)",
                file=sys.stderr,
            )
        else:
            print(
                f"check_no_artifact_refs: {report.n_total_hits} hit(s) "
                f"on {report.n_slides_with_hits}/{report.n_slides} slides "
                f"→ {md_path.relative_to(draft_dir)} (advisory)",
                file=sys.stderr,
            )

    if args.strict and report.n_total_hits > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
