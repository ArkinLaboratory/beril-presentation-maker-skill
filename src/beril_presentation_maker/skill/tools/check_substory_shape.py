#!/usr/bin/env python3
"""check_substory_shape.py — v0.5 Tier B / D-071 + D-073.

Post-composer / post-merge check that each substory has Q/A/R/C
shape per the v0.5 D-071 contract. Emits findings into
`<draft_dir>/audit/substory_shape.json`; the M4b cascade Tier-1
reads it (matches `_read_quantitative_grounding` pattern). Soft
enforcement per D-073 — findings are advisory; pipeline doesn't
halt.

Contract (D-071 slide-shape mapping option (b)):

  Each substory MUST have:
    - A `question:` field (≤25 words) on the substory metadata in
      02_substories.md.
    - A `conclusion_for_next_substory:` field (≤25 words) unless
      this is the final substory (in which case the field is
      optional; if absent, the throughline conclusion is the implicit
      handoff).
    - At least one Q-slide (section_divider OR opening big_idea —
      typically the substory's first slide; matches SPEC §6.2).
    - At least one R-slide (data_figure OR data_table OR big_number)
      — the substory's results.
    - At least one C-slide (claim_evidence OR big_idea closing the
      substory — typically the substory's last content slide before
      the next divider).

Soft-enforcement per D-073: violations land as cascade Tier-1
findings with `kind=substory_arc`, severity P1. Pipeline doesn't
halt. Revise loop OR operator can act on them.

Output: `audit/substory_shape.json` (`schema_version:
substory-shape.v1`). The cascade reads it via a new
`_read_substory_shape` helper in `review_cascade.py` (Tier B
follow-up commit).

CLI:

    python3 check_substory_shape.py \\
        --draft-dir <path/to/draft_N> \\
        [--out <path/to/audit/substory_shape.json>] \\
        [--report-format json|text]

Pure stdlib; importable for unit tests.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = "substory-shape.v1"

# Per D-071: word cap on Q/handoff fields.
MAX_QUESTION_WORDS = 25
MAX_CONCLUSION_WORDS = 25

# Q-slide / R-slide / C-slide layout vocabulary per D-071.
# Q-slide = section_divider OR opening big_idea (substory's first
# content slide; matches SPEC §6.2 substory-opener rule).
Q_SLIDE_LAYOUTS = frozenset({"section_divider", "big_idea"})

# R-slide = the substory's evidentiary slides.
R_SLIDE_LAYOUTS = frozenset({
    "data_figure", "data_table", "big_number", "two_column_compare",
    "workflow_diagram",  # also methods-bearing but counts toward results
})

# C-slide = the substory's closing claim. Often claim_evidence;
# big_idea can close too if it's the substory's terminal slide.
C_SLIDE_LAYOUTS = frozenset({"claim_evidence", "big_idea"})

# Field-name patterns in 02_substories.md (extended D-071 v3 fields).
# Existing v1/v2 prompts only emit `Punchline:`. v3 prompts will add
# Question + Conclusion; this validator detects absence on v1/v2-shape
# input + presence on v3-shape input.
QUESTION_FIELD_RE = re.compile(
    r"^\*\*(?:Question|Scientific question):\*\*\s*(.+?)\s*$",
    re.MULTILINE,
)
CONCLUSION_FIELD_RE = re.compile(
    r"^\*\*(?:Conclusion(?: for next substory)?|"
    r"Hands off to|Next substory):\*\*\s*(.+?)\s*$",
    re.MULTILINE,
)
PUNCHLINE_FIELD_RE = re.compile(
    r"^\*\*Punchline:\*\*\s*(.+?)\s*$",
    re.MULTILINE,
)
SUBSTORY_HEADER_RE = re.compile(
    r"^### (S\d+)\s*[—–-]\s*(.+?)\s*$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SubstoryFinding:
    """One substory-shape violation."""
    substory_id: str
    kind: str               # missing_question | missing_conclusion |
                            # question_too_long | conclusion_too_long |
                            # missing_q_slide | missing_r_slide |
                            # missing_c_slide | substory_has_no_slides
    severity: str           # "P1" per D-073
    message: str
    slide_id: Optional[int] = None  # the affected slide if applicable

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SubstoryRecord:
    """Per-substory inventory used by the checker (exposed for tests/
    operator inspection via the JSON output)."""
    substory_id: str
    title: str
    question: Optional[str]            # None when v1/v2-shape input
    conclusion_for_next: Optional[str]  # None when last substory OR v1/v2
    punchline: Optional[str]            # legacy v1/v2 field
    is_last: bool
    slide_ids: list[int] = field(default_factory=list)
    slide_layouts: list[str] = field(default_factory=list)
    has_q_slide: bool = False
    has_r_slide: bool = False
    has_c_slide: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SubstoryShapeReport:
    schema_version: str
    draft_dir: str
    substories_path: str
    slide_spec_path: str
    n_substories: int
    substories: list[SubstoryRecord]
    findings: list[SubstoryFinding]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "draft_dir": self.draft_dir,
            "substories_path": self.substories_path,
            "slide_spec_path": self.slide_spec_path,
            "n_substories": self.n_substories,
            "substories": [s.to_dict() for s in self.substories],
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Substory-metadata extractors (v0.5 D-071 extensions of parse_substories.py)
# ---------------------------------------------------------------------------

def extract_substory_fields(content: str) -> list[dict]:
    """Walk 02_substories.md; for each substory, extract id + title +
    optional question + optional conclusion + optional punchline.

    Returns a list[dict] in document order. Missing fields are None
    (substory_design.v1.md / .v2.md don't emit Question/Conclusion;
    substory_design.v3.md per D-071 will).
    """
    headers = list(SUBSTORY_HEADER_RE.finditer(content))
    out: list[dict] = []
    for i, m in enumerate(headers):
        sid = m.group(1)
        title = m.group(2).strip()
        section_start = m.end()
        section_end = (headers[i + 1].start() if i + 1 < len(headers)
                       else len(content))
        section = content[section_start:section_end]

        q_match = QUESTION_FIELD_RE.search(section)
        c_match = CONCLUSION_FIELD_RE.search(section)
        p_match = PUNCHLINE_FIELD_RE.search(section)

        out.append({
            "substory_id": sid,
            "title": title,
            "question": q_match.group(1).strip() if q_match else None,
            "conclusion_for_next": c_match.group(1).strip() if c_match else None,
            "punchline": p_match.group(1).strip() if p_match else None,
        })
    return out


# ---------------------------------------------------------------------------
# Slide-to-substory inventory
# ---------------------------------------------------------------------------

def inventory_slides_per_substory(
    spec: dict, substory_ids: list[str],
) -> dict[str, list[tuple[int, str]]]:
    """Walk slide_spec.json; return {substory_id: [(slide_id, layout), ...]}
    in slide-order. Slides without a substory_id (e.g., title,
    references, acknowledgments) are excluded.
    """
    out: dict[str, list[tuple[int, str]]] = {sid: [] for sid in substory_ids}
    for slide in spec.get("slides", []) or []:
        sid = slide.get("substory_id")
        if sid in out:
            out[sid].append((slide["id"], slide.get("layout", "?")))
    return out


# ---------------------------------------------------------------------------
# Shape checker
# ---------------------------------------------------------------------------

def _word_count(s: str) -> int:
    return len(s.split())


def check_substory(record_meta: dict, slides: list[tuple[int, str]],
                   is_last: bool) -> tuple[SubstoryRecord, list[SubstoryFinding]]:
    """Check one substory's shape. Returns (SubstoryRecord, findings)."""
    sid = record_meta["substory_id"]
    findings: list[SubstoryFinding] = []

    # Build the record skeleton.
    record = SubstoryRecord(
        substory_id=sid,
        title=record_meta["title"],
        question=record_meta["question"],
        conclusion_for_next=record_meta["conclusion_for_next"],
        punchline=record_meta["punchline"],
        is_last=is_last,
        slide_ids=[s[0] for s in slides],
        slide_layouts=[s[1] for s in slides],
    )

    # Empty-substory check (substory declared but no slides assigned).
    if not slides:
        findings.append(SubstoryFinding(
            substory_id=sid,
            kind="substory_has_no_slides",
            severity="P1",
            message=(f"Substory {sid} '{record_meta['title']}' has no "
                     f"slides assigned. Either remove the substory "
                     f"from 02_substories.md or assign slides to it "
                     f"in slide_compose."),
        ))
        # Skip the rest of the checks; nothing to validate against
        return record, findings

    # D-071 question field check
    if record.question is None:
        findings.append(SubstoryFinding(
            substory_id=sid,
            kind="missing_question",
            severity="P1",
            message=(f"Substory {sid} missing the **Question:** field "
                     f"(D-071). Each substory MUST name the one "
                     f"scientific question it answers (≤25 words). "
                     f"Add `**Question:** <one sentence>` after the "
                     f"### S{sid[1:]} header in 02_substories.md."),
        ))
    elif _word_count(record.question) > MAX_QUESTION_WORDS:
        findings.append(SubstoryFinding(
            substory_id=sid,
            kind="question_too_long",
            severity="P1",
            message=(f"Substory {sid} **Question:** field is "
                     f"{_word_count(record.question)} words "
                     f"(cap: {MAX_QUESTION_WORDS}). Audience should "
                     f"hold the question in working memory; tighten "
                     f"to a single sentence."),
        ))

    # D-071 conclusion_for_next_substory check (skip if last substory)
    if not is_last:
        if record.conclusion_for_next is None:
            findings.append(SubstoryFinding(
                substory_id=sid,
                kind="missing_conclusion",
                severity="P1",
                message=(f"Substory {sid} missing the "
                         f"**Conclusion for next substory:** field "
                         f"(D-071). Each non-final substory MUST "
                         f"explicitly hand a question forward (≤25 "
                         f"words) to bridge into the next substory. "
                         f"Add `**Conclusion for next substory:** "
                         f"<one sentence>` to 02_substories.md."),
            ))
        elif _word_count(record.conclusion_for_next) > MAX_CONCLUSION_WORDS:
            findings.append(SubstoryFinding(
                substory_id=sid,
                kind="conclusion_too_long",
                severity="P1",
                message=(f"Substory {sid} **Conclusion for next "
                         f"substory:** field is "
                         f"{_word_count(record.conclusion_for_next)} "
                         f"words (cap: {MAX_CONCLUSION_WORDS}). The "
                         f"handoff should be a single sentence the "
                         f"audience can hold while transitioning."),
            ))

    # Slide-shape mapping per D-071 (b):
    # Q-slide presence (section_divider OR opening big_idea)
    layouts_present = set(record.slide_layouts)
    record.has_q_slide = bool(layouts_present & Q_SLIDE_LAYOUTS)
    record.has_r_slide = bool(layouts_present & R_SLIDE_LAYOUTS)
    record.has_c_slide = bool(layouts_present & C_SLIDE_LAYOUTS)

    if not record.has_q_slide:
        findings.append(SubstoryFinding(
            substory_id=sid,
            kind="missing_q_slide",
            severity="P1",
            message=(f"Substory {sid} has no Q-slide "
                     f"(section_divider or big_idea opener). SPEC §6.2 "
                     f"+ D-071 require each substory to open with a "
                     f"question-naming slide. Add a section_divider "
                     f"or big_idea as the substory's first slide."),
            slide_id=record.slide_ids[0] if record.slide_ids else None,
        ))

    if not record.has_r_slide:
        findings.append(SubstoryFinding(
            substory_id=sid,
            kind="missing_r_slide",
            severity="P1",
            message=(f"Substory {sid} has no R-slide "
                     f"(data_figure, data_table, big_number, "
                     f"two_column_compare, or workflow_diagram). "
                     f"D-071 requires each substory to present "
                     f"evidentiary results — without one, the "
                     f"substory is structurally empty between Q and "
                     f"C. Add at least one results slide."),
        ))

    if not record.has_c_slide:
        findings.append(SubstoryFinding(
            substory_id=sid,
            kind="missing_c_slide",
            severity="P1",
            message=(f"Substory {sid} has no C-slide "
                     f"(claim_evidence or big_idea closing). D-071 "
                     f"requires each substory to close on a claim "
                     f"that hands the question forward (handoff "
                     f"text lives in the **Conclusion for next "
                     f"substory:** field). Add a claim_evidence or "
                     f"big_idea as the substory's terminal content "
                     f"slide."),
            slide_id=record.slide_ids[-1] if record.slide_ids else None,
        ))

    return record, findings


def check_substory_shape(
    draft_dir: Path,
    *,
    substories_path: Optional[Path] = None,
    slide_spec_path: Optional[Path] = None,
) -> SubstoryShapeReport:
    """Top-level entry. Loads 02_substories.md + working/slide_spec.json
    from the draft_dir (or explicit overrides), validates Q/A/R/C
    shape per D-071, and returns a SubstoryShapeReport.

    Args:
      draft_dir: path to the draft directory (e.g.,
        `<BERIL_ROOT>/projects/<id>/talks/draft_N`).
      substories_path: override; default `<draft_dir>/narrative/02_substories.md`.
      slide_spec_path: override; default `<draft_dir>/working/slide_spec.json`.
    """
    if substories_path is None:
        substories_path = draft_dir / "narrative" / "02_substories.md"
    if slide_spec_path is None:
        slide_spec_path = draft_dir / "working" / "slide_spec.json"

    # Read inputs defensively (operator-friendly: degrade rather than
    # crash if a path is missing — cascade is advisory).
    if not substories_path.is_file():
        return SubstoryShapeReport(
            schema_version=SCHEMA_VERSION,
            draft_dir=str(draft_dir),
            substories_path=str(substories_path),
            slide_spec_path=str(slide_spec_path),
            n_substories=0,
            substories=[],
            findings=[SubstoryFinding(
                substory_id="(global)",
                kind="missing_input",
                severity="P1",
                message=(f"02_substories.md not found at "
                         f"{substories_path}. Substory-shape check "
                         f"requires the substory list to be on disk; "
                         f"run stage_substory_design (v0.3) OR "
                         f"stage_deck_outline (v0.4) first."),
            )],
        )
    if not slide_spec_path.is_file():
        return SubstoryShapeReport(
            schema_version=SCHEMA_VERSION,
            draft_dir=str(draft_dir),
            substories_path=str(substories_path),
            slide_spec_path=str(slide_spec_path),
            n_substories=0,
            substories=[],
            findings=[SubstoryFinding(
                substory_id="(global)",
                kind="missing_input",
                severity="P1",
                message=(f"slide_spec.json not found at "
                         f"{slide_spec_path}. Substory-shape check "
                         f"needs the merged spec to inventory each "
                         f"substory's slides; run "
                         f"stage_merge_and_assemble first."),
            )],
        )

    substories_text = substories_path.read_text(encoding="utf-8")
    spec = json.loads(slide_spec_path.read_text(encoding="utf-8"))

    metas = extract_substory_fields(substories_text)
    substory_ids = [m["substory_id"] for m in metas]
    slides_by_substory = inventory_slides_per_substory(spec, substory_ids)

    all_records: list[SubstoryRecord] = []
    all_findings: list[SubstoryFinding] = []
    n = len(metas)
    for i, meta in enumerate(metas):
        is_last = (i == n - 1)
        sid = meta["substory_id"]
        slides = slides_by_substory.get(sid, [])
        record, findings = check_substory(meta, slides, is_last)
        all_records.append(record)
        all_findings.extend(findings)

    return SubstoryShapeReport(
        schema_version=SCHEMA_VERSION,
        draft_dir=str(draft_dir),
        substories_path=str(substories_path),
        slide_spec_path=str(slide_spec_path),
        n_substories=len(metas),
        substories=all_records,
        findings=all_findings,
    )


# ---------------------------------------------------------------------------
# Text report (operator-facing)
# ---------------------------------------------------------------------------

def format_text_report(report: SubstoryShapeReport) -> str:
    lines = []
    lines.append(f"# Substory-shape check ({report.schema_version})")
    lines.append("")
    lines.append(f"**draft_dir:** {report.draft_dir}")
    lines.append(f"**substories:** {report.n_substories}")
    lines.append(f"**findings:** {len(report.findings)}")
    lines.append("")

    if not report.findings:
        lines.append("✓ Clean — all substories have Q/A/R/C shape per D-071.")
        return "\n".join(lines) + "\n"

    # Group findings by kind for the summary header.
    by_kind: dict[str, int] = {}
    for f in report.findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    lines.append(f"**by kind:** {by_kind}")
    lines.append("")

    # Per-substory detail.
    lines.append("## Per-substory shape")
    lines.append("")
    for rec in report.substories:
        flags = []
        if rec.has_q_slide:
            flags.append("Q✓")
        else:
            flags.append("Q✗")
        if rec.has_r_slide:
            flags.append("R✓")
        else:
            flags.append("R✗")
        if rec.has_c_slide:
            flags.append("C✓")
        else:
            flags.append("C✗")
        lines.append(f"### {rec.substory_id} — {rec.title}")
        lines.append("")
        lines.append(f"- slides: {len(rec.slide_ids)} "
                     f"({', '.join(rec.slide_layouts) or '(none)'})")
        lines.append(f"- shape: {' '.join(flags)}")
        lines.append(f"- question: "
                     f"{('✓ ' + str(_word_count(rec.question)) + 'w'
                          if rec.question else '✗ missing')}")
        lines.append(f"- conclusion_for_next: "
                     f"{('✓ ' + str(_word_count(rec.conclusion_for_next))
                          + 'w' if rec.conclusion_for_next
                          else ('— (last substory)' if rec.is_last
                                else '✗ missing'))}")
        lines.append("")

    # Findings list.
    lines.append("## Findings")
    lines.append("")
    for f in report.findings:
        lines.append(f"- **{f.substory_id}** [{f.severity}] "
                     f"`{f.kind}`{(' slide ' + str(f.slide_id)) if f.slide_id else ''}: "
                     f"{f.message}")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_substory_shape",
        description="v0.5 substory-shape validator (D-071 + D-073). "
                    "Check Q/A/R/C shape per substory.")
    p.add_argument("--draft-dir", required=True, type=Path,
                   help="Path to the draft directory "
                        "(<BERIL_ROOT>/projects/<id>/talks/draft_N).")
    p.add_argument("--substories-path", type=Path, default=None,
                   help="Override: path to 02_substories.md "
                        "(default: <draft-dir>/narrative/02_substories.md).")
    p.add_argument("--slide-spec-path", type=Path, default=None,
                   help="Override: path to slide_spec.json "
                        "(default: <draft-dir>/working/slide_spec.json).")
    p.add_argument("--out", type=Path, default=None,
                   help="Output path. Default for json: "
                        "<draft-dir>/audit/substory_shape.json. "
                        "Default for text: stdout.")
    p.add_argument("--report-format", choices=("json", "text"),
                   default="text",
                   help="Output format (default: text).")
    args = p.parse_args(argv)

    if not args.draft_dir.is_dir():
        print(f"error: --draft-dir not a directory: {args.draft_dir}",
              file=sys.stderr)
        return 2

    report = check_substory_shape(
        args.draft_dir,
        substories_path=args.substories_path,
        slide_spec_path=args.slide_spec_path,
    )

    if args.report_format == "json":
        text = json.dumps(report.to_dict(), indent=2) + "\n"
        out_path = args.out or (args.draft_dir / "audit" / "substory_shape.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"wrote {out_path}", file=sys.stderr)
    else:
        text = format_text_report(report)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            sys.stdout.write(text)

    # Exit 0 on completion regardless of findings (D-073: soft;
    # advisory not failing). Caller may inspect the report content to
    # decide whether to halt.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
