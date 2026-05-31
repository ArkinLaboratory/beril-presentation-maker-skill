#!/usr/bin/env python3
"""extract_deck_close.py — emit the deck-spanning closing-synthesis signal.

Per D-086 (v0.7 Tier C closing-synthesis layout): for STRONG-mode
talks (talk-30+), the deck must end with a `deck_close` slide that
unifies all substories into a single takeaway. The composer (per
slide_compose.v3.2_overlay.md §"Closing synthesis (D-086)") reads
the structured signal verbatim — no ad-hoc LLM synthesis.

This module produces that signal from the curator-side artifacts
already on disk:

- `<draft_dir>/narrative/00_throughline.md` — the chosen throughline
  claim is the natural source for `unified_point`. The throughline
  IS the deck's overall takeaway.
- `<draft_dir>/narrative/02_substories.md` — per-substory
  `Conclusion for next substory:` fields (v3 / D-071 contract) +
  `Transition from prior:` fields (v3.2 / D-087) are the per-arc
  key takeaways. The handoff chain S1→...→SN is the
  arc-by-arc synthesis spine.
- `<project_dir>/REPORT.md` — synthesis / conclusion / next-directions
  sections feed `forward_call` (the forward-looking actionable
  statement the audience leaves with). Pattern matches on common
  section headings (`## Next directions`, `## Future work`,
  `## Open questions`, `## Synthesis`, `## Conclusion(s)`).

Output schema (writes `<draft_dir>/working/deck_close_signal.json`):

    {
      "schema_version": "deck-close-signal.v1",
      "project_id": "<id>",
      "unified_point": "<string>",
      "key_takeaways": ["<string>", ...],   # 3-5 items
      "forward_call": "<string>",
      "data_source": "<string>",
      "raw_evidence": {
        "throughline_path": "<path>",
        "substories_path": "<path>",
        "report_path": "<path or null>",
        "substory_ids_seen": ["S1", "S2", ...],
        "report_sections_matched": ["Next directions", ...]
      },
      "no_signal_fallback": <bool>
    }

The `no_signal_fallback` field is True when the substories file is
missing OR no per-substory conclusions could be extracted —
indicating the composer should not author a deck_close slide
(absence is a curator-stage signal; D-086 specifies absence is
silent on sub-STRONG modes; for STRONG-mode talks the
validate_slide_spec soft-warning fires per Tier C.0).

Mode-gating: the EXTRACTOR is mode-agnostic. The orchestrator
(`stage_deck_close` per Tier C.3) decides whether to invoke this
based on `--mode`. Allows operators to opt in to deck_close on
talk-15 etc. without re-running curator stages.

CLI:

    python3 extract_deck_close.py <draft_dir> [--out signal.json]
                                              [--quiet]

Library:

    from extract_deck_close import extract_deck_close
    report = extract_deck_close(Path("path/to/draft_dir"))
    print(report.unified_point, report.key_takeaways)

Refs: D-086 (deck_close layout); D-071 (substory Q/A/R/C contract
giving us the Conclusion-for-next-substory handoff); D-087
(substory_design.v3.2 transition_from_prior — used as evidence
of v3.2-aware curator output); V0_7_PUNCH_LIST.md Tier C.2 row;
`prompts/slide_compose.v3.2_overlay.md` §"Closing synthesis" (the
composer-side contract that reads this signal).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = "deck-close-signal.v1"

# Throughline parsing — the file has a top-of-document chosen claim.
# Multiple formats observed in the wild:
#   1. HTML-comment punchline at top: `<!-- punchline: <claim> -->`
#      (current v0.6/v0.7 throughline generator). This is the
#      authoritative form because the orchestrator's downstream
#      stages READ this comment.
#   2. `## Candidate TLN: <claim>` heading where N matches the
#      `<!-- chosen: TL1 -->` comment (also current).
#   3. `**Chosen throughline:** <claim>` field — older v0.5 format.
#   4. The first non-heading paragraph after the H1 title — older
#      v0.3 fallback.
# Match in priority order so v0.6+ files use the punchline comment.
_THROUGHLINE_PUNCHLINE_COMMENT_RE = re.compile(
    r"<!--\s*punchline:\s*(.+?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_THROUGHLINE_CHOSEN_COMMENT_RE = re.compile(
    r"<!--\s*chosen:\s*(TL\d+)\s*-->",
    re.IGNORECASE,
)
_THROUGHLINE_CANDIDATE_HEADING_RE = re.compile(
    r"^##\s+Candidate\s+(TL\d+):\s*(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)
# Match both colon-inside (`**Chosen throughline:**`) and
# colon-outside (`**Chosen throughline**:`) variants — both have
# appeared in v0.5-era throughline files.
_THROUGHLINE_CHOSEN_RE = re.compile(
    r"^\*\*(?:Chosen\s+throughline|Throughline|Selected)"
    r":?\*\*\s*:?\s*(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)

# Substory header — same pattern check_figure_provenance.py uses.
_SUBSTORY_HEADER_RE = re.compile(r"^###\s+(S\d+)\s*[—–-]", re.MULTILINE)

# Conclusion-for-next-substory field (v3 / D-071).
_CONCLUSION_RE = re.compile(
    r"^\*\*Conclusion\s+for\s+next\s+substory:\*\*\s*(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)

# Transition-from-prior field (v3.2 / D-087). Used as evidence the
# curator emitted v3.2-aware substory_design; signal still works
# without it (we fall back to Conclusion fields).
_TRANSITION_RE = re.compile(
    r"^\*\*Transition\s+from\s+prior:\*\*\s*(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)

# Punchline field (v3 / D-071) — the section_divider's headline;
# also the substory's compressed summary. Useful as a final-substory
# takeaway when the final substory has no Conclusion-for-next-substory
# (because there IS no next substory).
_PUNCHLINE_RE = re.compile(
    r"^\*\*Punchline:\*\*\s*(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)

# REPORT.md forward-call sections. The composer prefers
# "Next directions" because it's most operationally actionable; we
# rank in this order. Section heading match is loose to accept
# "## Next directions" / "## Next Directions" / "### Next directions".
_REPORT_FORWARD_SECTIONS: tuple[str, ...] = (
    "Next directions",
    "Next steps",
    "Future work",
    "Future directions",
    "Open questions",
    "Outstanding questions",
    "Implications",
    "Conclusions",
    "Conclusion",
    "Synthesis",
    "Summary",
)

# Template uses %s for the section-name substitution because the
# regex contains brace-quantifiers (e.g. {2,4}) that str.format()
# would misinterpret. Use as: _SECTION_HEADING_RE_TMPL % re.escape(name).
_SECTION_HEADING_RE_TMPL = (
    r"^(#{2,4})\s+(?:[\d.]+\s+)?%s\b[^\n]*$"
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DeckCloseReport:
    """Signal for the deck_close slide (D-086 schema)."""
    project_id: str
    unified_point: str = ""
    key_takeaways: list[str] = field(default_factory=list)
    forward_call: str = ""
    data_source: str = ""
    raw_evidence: dict = field(default_factory=dict)
    no_signal_fallback: bool = False

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": self.project_id,
            "unified_point": self.unified_point,
            "key_takeaways": self.key_takeaways,
            "forward_call": self.forward_call,
            "data_source": self.data_source,
            "raw_evidence": self.raw_evidence,
            "no_signal_fallback": self.no_signal_fallback,
        }

    def to_slide_content(self) -> dict:
        """Convert to the deck_close content schema consumable by
        slide_spec / assemble_pptx. Used when bypassing the composer
        (e.g., direct merge from signal without LLM polish — useful
        for testing the renderer + validator without the composer
        stage). The composer (Tier C.3) reads this same shape
        VERBATIM per D-086."""
        return {
            "unified_point": self.unified_point,
            "key_takeaways": self.key_takeaways,
            "forward_call": self.forward_call,
            "data_source": self.data_source,
        }


# ---------------------------------------------------------------------------
# Per-source parsers
# ---------------------------------------------------------------------------

def parse_throughline(throughline_path: Path) -> str:
    """Extract the chosen throughline claim from
    `narrative/00_throughline.md`. Returns the empty string if the
    file is missing or no claim is parsable.

    Priority order (matches actual on-disk formats seen across
    v0.3-v0.7 throughline generators):
    1. `<!-- punchline: ... -->` HTML comment at top of file
       (v0.6+ canonical; downstream stages read this same comment).
    2. `## Candidate TLN: <claim>` where N matches the
       `<!-- chosen: TLN -->` comment (also v0.6+).
    3. `**Chosen throughline:** <claim>` field (older v0.5).
    4. First non-heading, non-italic-meta paragraph after H1
       (last-resort fallback for older v0.3 files).
    """
    if not throughline_path.is_file():
        return ""
    try:
        text = throughline_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    # Format 1: <!-- punchline: ... --> (v0.6+ authoritative)
    m = _THROUGHLINE_PUNCHLINE_COMMENT_RE.search(text)
    if m:
        return _strip_md(m.group(1).strip())

    # Format 2: ## Candidate TLN: <claim>, gated by <!-- chosen: TLN -->
    chosen_m = _THROUGHLINE_CHOSEN_COMMENT_RE.search(text)
    if chosen_m:
        chosen_id = chosen_m.group(1)
        for cm in _THROUGHLINE_CANDIDATE_HEADING_RE.finditer(text):
            if cm.group(1).upper() == chosen_id.upper():
                return _strip_md(cm.group(2).strip())
    # If no `<!-- chosen: -->` comment but candidate headings exist,
    # take the first candidate (single-candidate v0.5 fallback).
    cm0 = _THROUGHLINE_CANDIDATE_HEADING_RE.search(text)
    if cm0:
        return _strip_md(cm0.group(2).strip())

    # Format 3: **Chosen throughline:** field
    m = _THROUGHLINE_CHOSEN_RE.search(text)
    if m:
        return _strip_md(m.group(1).strip())

    # Format 4: first non-heading, non-italic paragraph after H1.
    # The v0.7 throughline generator writes an italic `_Picked
    # from .../candidates.md..._` meta-line right after the H1; skip
    # italic-only paragraphs (they're meta-prose, not the claim).
    in_body = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            in_body = True
            continue
        if not in_body:
            continue
        # Skip italic-only meta-prose (e.g. "_Picked from ..._")
        if re.fullmatch(r"_[^_]+_", stripped):
            continue
        # Skip HTML comments + horizontal rules
        if stripped.startswith("<!--") or stripped in ("---", "***"):
            continue
        return _strip_md(stripped)
    return ""


@dataclass
class SubstoryRecord:
    """One substory's parsed fields."""
    substory_id: str
    conclusion_for_next: str = ""
    transition_from_prior: str = ""
    punchline: str = ""


def parse_substory_records(substories_path: Path) -> list[SubstoryRecord]:
    """Walk `narrative/02_substories.md` and pull the per-substory
    fields relevant to deck_close: conclusion_for_next + punchline +
    (when present) transition_from_prior."""
    if not substories_path.is_file():
        return []
    try:
        text = substories_path.read_text(encoding="utf-8")
    except OSError:
        return []
    headers = list(_SUBSTORY_HEADER_RE.finditer(text))
    records: list[SubstoryRecord] = []
    for i, h in enumerate(headers):
        sid = h.group(1)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end]
        rec = SubstoryRecord(substory_id=sid)
        cm = _CONCLUSION_RE.search(body)
        if cm:
            rec.conclusion_for_next = _strip_md(cm.group(1).strip())
        tm = _TRANSITION_RE.search(body)
        if tm:
            rec.transition_from_prior = _strip_md(tm.group(1).strip())
        pm = _PUNCHLINE_RE.search(body)
        if pm:
            rec.punchline = _strip_md(pm.group(1).strip())
        records.append(rec)
    return records


def parse_report_forward_call(report_path: Path) -> tuple[str, list[str]]:
    """Pull the first 1-2 sentences from the first matching
    forward-looking section in REPORT.md. Returns
    (forward_call_text, matched_section_names).

    Sections are ranked per _REPORT_FORWARD_SECTIONS; we stop at the
    first match so "Next directions" wins over "Conclusions" when
    both exist. Returns ("", []) if REPORT is missing or no matching
    section is found.
    """
    if not report_path.is_file():
        return "", []
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError:
        return "", []

    matched_sections: list[str] = []
    for section_name in _REPORT_FORWARD_SECTIONS:
        pattern = re.compile(
            _SECTION_HEADING_RE_TMPL % re.escape(section_name),
            re.IGNORECASE | re.MULTILINE,
        )
        m = pattern.search(text)
        if not m:
            continue
        matched_sections.append(section_name)
        # Pull the section body (until the next equal-or-higher-level heading).
        heading_level = len(m.group(1))
        start = m.end()
        # Match any heading at >= heading_level depth as a stopper.
        next_heading_re = re.compile(
            rf"^#{{{1},{heading_level}}}\s",
            re.MULTILINE,
        )
        next_m = next_heading_re.search(text, pos=start)
        body = text[start:next_m.start() if next_m else len(text)].strip()
        # Try prose first (most operationally informative).
        first_para = _first_paragraph(body)
        if first_para:
            sentences = _first_n_sentences(first_para, n=2)
            if sentences:
                return sentences, matched_sections
        # Fallback: section is a bulleted list (very common in
        # REPORT.md "Next directions" / "Future work"). Take the
        # first 1-2 bullets, strip the markers, and concatenate
        # into a single sentence-style string the composer can
        # use verbatim.
        bullets = _first_bullets(body, n=2)
        if bullets:
            return " ".join(bullets), matched_sections
    return "", matched_sections


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------

def extract_deck_close(
    draft_dir: Path,
    project_dir: Optional[Path] = None,
) -> DeckCloseReport:
    """Build the DeckCloseReport for `draft_dir`.

    Args:
      draft_dir: Path to <BERIL_ROOT>/projects/<id>/talks/draft_N.
      project_dir: Path to <BERIL_ROOT>/projects/<id>/. If None,
        derived as draft_dir.parent.parent.

    Returns:
      DeckCloseReport. If the substories file is missing or yields no
      per-substory conclusions, no_signal_fallback=True and the
      orchestrator should NOT emit a deck_close slide (the
      validate_slide_spec mode-gated soft-warning per Tier C.0 will
      surface this on a STRONG-mode talk for Tier-F review).
    """
    draft_dir = Path(draft_dir).resolve()
    if not draft_dir.is_dir():
        raise FileNotFoundError(f"draft_dir not found: {draft_dir}")
    if project_dir is None:
        project_dir = draft_dir.parent.parent
    project_dir = Path(project_dir).resolve()

    project_id = project_dir.name
    report = DeckCloseReport(project_id=project_id)

    throughline_path = draft_dir / "narrative" / "00_throughline.md"
    substories_path = draft_dir / "narrative" / "02_substories.md"
    report_path = project_dir / "REPORT.md"

    # unified_point ← throughline
    report.unified_point = parse_throughline(throughline_path)

    # key_takeaways ← per-substory Conclusion-for-next + universal
    # punchline fallback.
    #
    # v0.7 Tier G live-discovered bug: v3.2 substory_design overlays
    # don't always emit `Conclusion for next substory:` on
    # non-final substories (the v3 contract requires it, but v3.2's
    # overlay layering apparently displaces some prompt instructions
    # for that field). The prompt contract drift is a v0.8 follow-up;
    # the extractor's job is to be robust to the actual on-disk
    # shape.
    #
    # Recovery: fall back to Punchline for ANY substory missing
    # Conclusion-for-next (not just the final). This matches what
    # the live curator produces in v0.7 and prevents the
    # "1 takeaway from a 4-substory deck" failure mode that
    # crashed Tier G ibd at validation time
    # (key_takeaways must have 3-5 items per D-086 schema).
    records = parse_substory_records(substories_path)
    takeaways: list[str] = []
    for i, rec in enumerate(records):
        if rec.conclusion_for_next:
            takeaways.append(rec.conclusion_for_next)
        elif rec.punchline:
            # Universal punchline fallback (was: final-only at Tier C.2).
            takeaways.append(rec.punchline)
    # Cap at 5 per D-086 / Tier C.0 schema. If a curator emits 6+
    # substories (talk-45 territory), the composer picks; here we
    # just preserve the first 5 + flag in evidence.
    capped_takeaways = takeaways[:5]
    report.key_takeaways = capped_takeaways

    # forward_call ← REPORT.md section scan
    forward_call, sections_matched = parse_report_forward_call(report_path)
    report.forward_call = forward_call

    # data_source ← mechanical synthesis of which artifacts we read
    substory_ids = [r.substory_id for r in records]
    data_source_bits: list[str] = []
    if substory_ids:
        data_source_bits.append(
            "Substory conclusions: " + " + ".join(
                f"{sid} (C-slot)" for sid in substory_ids[:len(capped_takeaways)]
            )
        )
    if report.unified_point:
        data_source_bits.append(
            f"narrative/00_throughline.md")
    if sections_matched and forward_call:
        data_source_bits.append(
            f"REPORT.md §{sections_matched[0]}"
        )
    report.data_source = "; ".join(data_source_bits)

    # raw_evidence — for audit + cascade-reader debugging
    report.raw_evidence = {
        "throughline_path": str(throughline_path.relative_to(draft_dir))
                            if throughline_path.is_file() else None,
        "substories_path": str(substories_path.relative_to(draft_dir))
                           if substories_path.is_file() else None,
        "report_path": str(report_path.relative_to(project_dir))
                       if report_path.is_file() else None,
        "substory_ids_seen": substory_ids,
        "n_substories": len(records),
        "n_takeaways_capped": len(capped_takeaways) < len(takeaways),
        "n_takeaways_total_before_cap": len(takeaways),
        "report_sections_matched": sections_matched,
        "v3_2_transition_field_present": any(
            r.transition_from_prior for r in records
        ),
    }

    # no_signal_fallback when the substory contract failed entirely.
    # Even an empty unified_point + empty forward_call is "no signal" —
    # but the load-bearing test is "did we get any per-arc takeaways?"
    # because that's what defines the deck_close slide's content.
    report.no_signal_fallback = not capped_takeaways

    return report


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _strip_md(text: str) -> str:
    """Strip common inline-markdown formatting from a single line:
    bold, italic, backticks. Curated content fields are stored
    plain-text in the slide_spec; the source markdown often wraps
    proper nouns in backticks or emphasis."""
    out = text
    # Strip backtick code spans
    out = re.sub(r"`([^`]+)`", r"\1", out)
    # Strip bold + italic markers (paired)
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
    out = re.sub(r"\*([^*]+)\*", r"\1", out)
    out = re.sub(r"__([^_]+)__", r"\1", out)
    out = re.sub(r"_([^_]+)_", r"\1", out)
    # Strip trailing parenthetical "(audit)" footnotes that curators
    # sometimes append; keep main content
    return out.strip()


def _first_paragraph(body: str) -> str:
    """Return the first non-empty paragraph from a markdown section
    body. Skips list-marker lines (they're typically multi-bullet
    enumerations, not a 1-2-sentence narrative — composer can pull
    the bullets via a different code path)."""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        # Skip markdown headings + list markers entirely; we want prose.
        if stripped.startswith("#"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped):
            # If we have prose already, return it; else skip the list.
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    for p in paragraphs:
        if p:
            return _strip_md(p)
    return ""


def _first_bullets(body: str, n: int = 2) -> list[str]:
    """Pull the first n top-level bullets from a markdown section
    body. Strips the bullet marker (`- `, `* `, `+ `, `1. `) +
    inline markdown. Sub-bullets (indented) are skipped — we want
    section-level forward-call statements, not nested detail."""
    out: list[str] = []
    for line in body.splitlines():
        # Stop at next blank-then-non-list block (typically a sub-
        # heading or different content kind below the list).
        if not line.strip():
            if out:
                # Allow blank lines inside a bullet block; only stop
                # if we hit a non-bullet content line after.
                continue
            continue
        # Top-level bullets are at column 0 (no indent).
        if line.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", line):
            stripped = re.sub(r"^[-*+]\s+|\d+\.\s+", "", line, count=1).strip()
            if stripped:
                # Ensure it ends with sentence-final punctuation for
                # composer-readability.
                if not stripped.endswith((".", "!", "?", ":")):
                    stripped += "."
                out.append(_strip_md(stripped))
                if len(out) >= n:
                    break
        elif out:
            # Hit a non-bullet line after collecting bullets — stop.
            break
    return out


def _first_n_sentences(text: str, n: int = 2) -> str:
    """Take the first n sentences. Sentence boundaries: ". " / "! " /
    "? " followed by uppercase OR end-of-string. Approximate; the
    composer (Tier C.3) reads this verbatim so over-eager splits
    are correctable by Adam at Tier-F."""
    text = text.strip()
    if not text:
        return ""
    # Split on sentence-ending punctuation followed by whitespace + capital.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    selected = parts[:n]
    return " ".join(s.strip() for s in selected if s.strip())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extract_deck_close",
        description=(
            "Extract the deck-spanning closing-synthesis signal "
            "(D-086) from a BERIL presentation draft directory."
        ),
    )
    parser.add_argument(
        "draft_dir",
        help="Path to <BERIL_ROOT>/projects/<id>/talks/draft_N",
    )
    parser.add_argument(
        "--project-dir",
        help="Override project_dir (default: draft_dir.parent.parent)",
    )
    parser.add_argument(
        "--out",
        help="Output path for the JSON signal (default: "
             "<draft_dir>/working/deck_close_signal.json; '-' for stdout)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress summary line on stderr",
    )
    args = parser.parse_args(argv)

    draft_dir = Path(args.draft_dir).resolve()
    project_dir = Path(args.project_dir).resolve() if args.project_dir else None
    try:
        report = extract_deck_close(draft_dir, project_dir=project_dir)
    except FileNotFoundError as e:
        print(f"extract_deck_close: {e}", file=sys.stderr)
        return 2

    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        sys.stdout.write(payload)
    else:
        out_path = (Path(args.out).resolve() if args.out
                    else draft_dir / "working" / "deck_close_signal.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        if not args.quiet:
            print(f"wrote {out_path}", file=sys.stderr)

    if not args.quiet:
        if report.no_signal_fallback:
            print(
                "[extract_deck_close] no signal — substories file missing "
                "or no per-arc takeaways parsable; orchestrator should NOT "
                "emit deck_close slide",
                file=sys.stderr,
            )
        else:
            print(
                f"[extract_deck_close] unified_point={'OK' if report.unified_point else 'EMPTY'}, "
                f"key_takeaways={len(report.key_takeaways)}, "
                f"forward_call={'OK' if report.forward_call else 'EMPTY'}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
