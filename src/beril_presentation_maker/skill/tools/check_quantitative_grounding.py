#!/usr/bin/env python3
"""check_quantitative_grounding.py — verify slide numbers ground in REPORT.md.

Mechanical post-checker for presentation-maker. Walks slide_spec.json,
extracts every numeric / percentage / ratio claim from slide title and
content text fields, and searches REPORT.md verbatim for each. Reports
any claim whose number does not appear in the project's truth source.

Why this exists (v0.2.1):
  Live test of presentation-maker v0.2.0 surfaced semantic-content issues
  (register drift, caveat omission, narrative-arc gaps) that need
  LLM-in-the-loop adversarial review (deferred to beril-adversarial
  --type presentation, planned v0.4.0). But ONE class of failure IS
  mechanically detectable: a number on a slide that does not appear in
  REPORT.md is unambiguously unbacked. This checker catches that class
  with high precision.

What this is NOT:
  - Not a register-drift checker. Whether "validates" is appropriate
    given REPORT's hedging is judgment, not regex.
  - Not a caveat-surfacing checker. Whether a slide should mention a
    limitation requires reading the source paragraph semantically.
  - Not a citation-grounding checker. Whether a citation supports the
    claim it's attached to is judgment.
  See SPEC_TYPE_PRESENTATION.md (in beril-adversarial-skill) for the
  semantic checks; this one stays in its lane.

Output:
  - <draft_dir>/audit/quantitative_grounding.md (human-readable)
  - <draft_dir>/audit/quantitative_grounding.json (machine-readable)

Exit codes:
  0 — all numbers grounded (or zero numbers found)
  1 — at least one ungrounded number (advisory; orchestrator decides
      whether to halt)
  2 — runtime error (missing inputs, malformed JSON, etc.)

Normalization:
  - Commas: "57,011" matches "57011" and vice-versa
  - Percent vs decimal: "24.9%" matches "24.9 percent" and "0.249"
  - Approximation prefixes: "~", "≈", "approximately" stripped
  - Rounding tolerance: "82%" matches "82.0%", "82.4%" (within 0.5)
    when the slide's number has fewer significant digits
  - Ratios: "4/4" matches "4 of 4", "4 out of 4"
  - "n=" prefixes: "n=142" matches "n = 142" matches "142"
  - Year filter: 4-digit numbers in the range 1900-2099 are skipped
    (citation years are not project claims)

Limitations (false-positive risk):
  - Paraphrased magnitudes: "17,344" vs "approximately 17k" won't match.
  - Derived numbers: "7,787 + 9,557 = 17,344" — if 17,344 is reported
    only as the sum, it might not appear verbatim in REPORT.md. The
    checker flags but the orchestrator can mark these as advisory.
  - Numbers from cited papers: a paper cited in the slide may quote a
    number from external work that REPORT.md doesn't surface. False
    positive — fix is to add the number to REPORT.md or accept the
    advisory flag.

Usage:
  check_quantitative_grounding.py <draft_dir> [--severity-floor LOW|MEDIUM|HIGH]
                                  [--quiet] [--json-only]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------

# Match common scientific number forms:
#   - Integers with optional commas: 57,011 / 17344
#   - Decimals: 24.9 / 0.249
#   - Percentages: 24.9% / 24.9 percent
#   - Scientific notation: 1.5e-4 / 2.3e-4
#   - Ratios with slash: 4/4 / 18/50
#   - n= prefixes: n=142 / n = 142
#
# Captured groups don't include trailing punctuation. Multi-pass to avoid
# greedy-overlap issues.

# Comma-separated integer (e.g., 57,011 / 1,256,789)
_NUM_COMMA_INT = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")

# Plain integer or decimal (e.g., 17344 / 24.9 / 0.249)
# Followed optionally by % or 'percent'.
_NUM_DECIMAL = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(%|percent\b)?",
    re.IGNORECASE,
)

# Scientific notation (1.5e-4, 2.3e+04, etc.)
_NUM_SCIENTIFIC = re.compile(
    r"\b(\d+(?:\.\d+)?)[eE]([+\-]?\d+)\b",
)

# Ratios: 4/4, 18/50
_NUM_RATIO = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")

# n= prefix: n=142, n = 142, N=10
_NUM_NEQ = re.compile(r"\b[nN]\s*=\s*(\d+(?:\.\d+)?)\b")

# Year filter: 4-digit numbers in plausible publication-year range
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class ExtractedNumber:
    """One numeric claim extracted from slide content."""
    raw: str               # exact substring as it appears
    canonical: str         # normalized form for matching ("57011", "0.249", etc.)
    kind: str              # "integer", "decimal", "percent", "scientific", "ratio", "n_eq"
    context_before: str    # ~30 chars preceding the number (lowercased)
    context_after: str     # ~30 chars following

    def is_year(self) -> bool:
        return bool(_YEAR_RE.match(self.canonical))

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "canonical": self.canonical,
            "kind": self.kind,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }


def _strip_approx_prefix(text: str) -> str:
    """Strip "~", "≈", "approximately", "approx" prefixes before number."""
    return re.sub(
        r"\b(approximately|approx\.?|about|roughly|nearly)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).replace("~", "").replace("≈", "")


def _canonical_int(s: str) -> str:
    """Normalize an integer with optional commas to plain digits."""
    return s.replace(",", "")


def _canonical_decimal_or_int(s: str, is_percent: bool) -> str:
    """Normalize a decimal or integer for matching.

    If the source says "24.9%" we canonicalize to "24.9" + percent flag;
    matching code tries both "24.9%" and "0.249" forms.
    """
    s = s.replace(",", "")
    return s


def _extract_window(text: str, start: int, end: int, window: int = 30) -> tuple[str, str]:
    """Return (before, after) context windows around a span [start, end)."""
    before = text[max(0, start - window):start].lower()
    after = text[end:min(len(text), end + window)].lower()
    return before, after


def extract_numbers(text: str) -> list[ExtractedNumber]:
    """Extract all numeric claims from `text`. Order-preserving; no
    deduplication across positions (the same number may appear in
    multiple contexts on a slide).

    Multi-pass with overlap suppression: first scan for the most-specific
    forms (n=, ratio, scientific, comma-int), then plain decimal/integer,
    skipping spans already claimed by an earlier pass.
    """
    out: list[ExtractedNumber] = []
    claimed: list[tuple[int, int]] = []  # spans already extracted

    def _is_claimed(start: int, end: int) -> bool:
        return any(s <= start < e or s < end <= e for s, e in claimed)

    def _record(m: re.Match, raw: str, canonical: str, kind: str) -> None:
        if _is_claimed(m.start(), m.end()):
            return
        before, after = _extract_window(text, m.start(), m.end())
        out.append(ExtractedNumber(
            raw=raw,
            canonical=canonical,
            kind=kind,
            context_before=before,
            context_after=after,
        ))
        claimed.append((m.start(), m.end()))

    # Pass 1: n= prefixes (most specific; "n=142" should not match as just "142")
    for m in _NUM_NEQ.finditer(text):
        _record(m, f"n={m.group(1)}", m.group(1), "n_eq")

    # Pass 2: ratios (4/4, 18/50)
    for m in _NUM_RATIO.finditer(text):
        _record(m, f"{m.group(1)}/{m.group(2)}",
                f"{m.group(1)}/{m.group(2)}", "ratio")

    # Pass 3: scientific (1.5e-4)
    for m in _NUM_SCIENTIFIC.finditer(text):
        raw = f"{m.group(1)}e{m.group(2)}"
        _record(m, raw, raw.lower(), "scientific")

    # Pass 4: comma-separated integers (57,011)
    for m in _NUM_COMMA_INT.finditer(text):
        _record(m, m.group(1), _canonical_int(m.group(1)), "integer")

    # Pass 5: plain decimals and integers, with optional % suffix
    for m in _NUM_DECIMAL.finditer(text):
        if _is_claimed(m.start(), m.end()):
            continue
        digit_part = m.group(1)
        pct = m.group(2)
        if pct:
            raw = f"{digit_part}{'%' if pct == '%' else ' percent'}"
            kind = "percent"
        elif "." in digit_part:
            raw = digit_part
            kind = "decimal"
        else:
            raw = digit_part
            kind = "integer"
        canonical = _canonical_decimal_or_int(digit_part, pct is not None)
        _record(m, raw, canonical, kind)

    # Sort by start position (claimed list is unordered)
    return sorted(out, key=lambda n: text.find(n.raw))


# ---------------------------------------------------------------------------
# REPORT.md verification
# ---------------------------------------------------------------------------

@dataclass
class ReportIndex:
    """Pre-built searchable index of REPORT.md numeric content."""
    raw_text: str
    normalized_text: str   # commas stripped, lowercased; for fuzzy match
    text_no_approx: str    # also with approximation-prefix words stripped


def build_report_index(report_path: Path) -> ReportIndex:
    """Read REPORT.md and prepare normalized search variants."""
    raw = report_path.read_text(encoding="utf-8")
    normalized = raw.replace(",", "").lower()
    no_approx = _strip_approx_prefix(normalized)
    return ReportIndex(raw_text=raw, normalized_text=normalized,
                       text_no_approx=no_approx)


def _find_in_report(num: ExtractedNumber, idx: ReportIndex) -> dict | None:
    """Search REPORT for a verbatim or normalized match of `num`.

    Returns a match-dict {match_form, line_number, line_quote} on hit,
    or None on miss.

    Match forms tried, in priority order:
      1. Verbatim raw (e.g., "57,011" exactly)
      2. Comma-stripped (e.g., "57011")
      3. Percent ↔ decimal (e.g., "24.9%" ↔ "0.249")
      4. Ratio variants ("4/4" ↔ "4 of 4" ↔ "4 out of 4")
      5. n= variants (n=142 ↔ "n = 142" ↔ "142")
      6. Rounding tolerance (slide's "82%" matches REPORT's "82.4%"
         when slide has fewer sig figs)
    """
    # 1. Verbatim raw
    if num.raw.lower() in idx.raw_text.lower():
        return _locate_line(idx.raw_text, num.raw, "verbatim")

    # 2. Comma-stripped (works for both raw with commas and without)
    canonical_lower = num.canonical.lower()
    if canonical_lower in idx.normalized_text:
        return _locate_line(idx.raw_text, num.canonical,
                            "comma_normalized", normalized=idx.normalized_text)

    # 3. Percent ↔ decimal cross-form
    if num.kind == "percent":
        try:
            pct_val = float(num.canonical)
            decimal_form = f"{pct_val / 100:.4f}".rstrip("0").rstrip(".")
            if decimal_form in idx.normalized_text:
                return _locate_line(idx.raw_text, decimal_form,
                                    "percent_to_decimal",
                                    normalized=idx.normalized_text)
        except ValueError:
            pass
    elif num.kind == "decimal":
        try:
            dec_val = float(num.canonical)
            if 0 <= dec_val <= 1:
                pct_form = f"{dec_val * 100:.4f}".rstrip("0").rstrip(".")
                if pct_form in idx.normalized_text:
                    return _locate_line(idx.raw_text, pct_form,
                                        "decimal_to_percent",
                                        normalized=idx.normalized_text)
        except ValueError:
            pass

    # 4. Ratio variants
    if num.kind == "ratio":
        a, b = num.canonical.split("/")
        for variant in (f"{a} of {b}", f"{a} out of {b}", f"{a}/{b}"):
            if variant.lower() in idx.normalized_text:
                return _locate_line(idx.raw_text, variant,
                                    "ratio_variant",
                                    normalized=idx.normalized_text)

    # 5. n= variants
    if num.kind == "n_eq":
        bare = num.canonical
        if bare in idx.normalized_text:
            return _locate_line(idx.raw_text, bare,
                                "n_eq_bare_match",
                                normalized=idx.normalized_text)

    # 6. Rounding tolerance — slide's number has fewer sig figs than REPORT's
    if num.kind in ("decimal", "percent"):
        try:
            slide_val = float(num.canonical)
            slide_str = num.canonical
            if "." in slide_str:
                sig_figs = len(slide_str.split(".")[1])
            else:
                sig_figs = 0
            # Search REPORT for floats that round to slide_val at slide's precision
            float_pattern = re.compile(r"\b(\d+\.\d+)\b")
            for fm in float_pattern.finditer(idx.normalized_text):
                report_val = float(fm.group(1))
                rounded = round(report_val, sig_figs)
                if abs(rounded - slide_val) < (10 ** -(sig_figs + 1)):
                    return _locate_line(idx.raw_text, fm.group(1),
                                        "rounding_tolerance",
                                        normalized=idx.normalized_text)
        except ValueError:
            pass

    return None


def _locate_line(report_text: str, search_str: str, match_form: str,
                 *, normalized: str | None = None) -> dict:
    """Find the line number in REPORT.md containing the match."""
    target_text = normalized if normalized is not None else report_text
    pos = target_text.lower().find(search_str.lower())
    if pos < 0:
        return {"match_form": match_form, "line_number": -1, "line_quote": ""}
    # Map normalized position back to raw if needed
    if normalized is not None:
        # Approximate: find the same number in raw text
        pos_in_raw = report_text.lower().find(search_str.lower())
        if pos_in_raw < 0:
            # Try comma-inserted form
            for variant in (search_str,
                            _maybe_add_commas(search_str)):
                pos_in_raw = report_text.lower().find(variant.lower())
                if pos_in_raw >= 0:
                    break
        if pos_in_raw < 0:
            pos_in_raw = pos  # best-effort
    else:
        pos_in_raw = pos

    line_no = report_text[:pos_in_raw].count("\n") + 1
    line_start = report_text.rfind("\n", 0, pos_in_raw) + 1
    line_end = report_text.find("\n", pos_in_raw)
    if line_end < 0:
        line_end = len(report_text)
    line_quote = report_text[line_start:line_end].strip()
    if len(line_quote) > 200:
        line_quote = line_quote[:197] + "..."
    return {
        "match_form": match_form,
        "line_number": line_no,
        "line_quote": line_quote,
    }


def _maybe_add_commas(s: str) -> str:
    """Insert commas every 3 digits from the right (for the integer part)."""
    if "." in s:
        int_part, dec_part = s.split(".", 1)
        return f"{_add_commas_int(int_part)}.{dec_part}"
    return _add_commas_int(s)


def _add_commas_int(s: str) -> str:
    if not s.isdigit() or len(s) <= 3:
        return s
    out = []
    for i, ch in enumerate(reversed(s)):
        if i > 0 and i % 3 == 0:
            out.append(",")
        out.append(ch)
    return "".join(reversed(out))


# ---------------------------------------------------------------------------
# Slide content traversal
# ---------------------------------------------------------------------------

# Slide content fields that contain prose-form numeric claims.
_TEXT_FIELDS = (
    "title", "headline", "subtitle", "punchline",
    "caption", "data_source", "answer_summary", "answer_detail",
    "evidence_pointer", "claim",
)
_LIST_FIELDS = (
    "bullets", "tenant_list", "kberdl_db_list", "step_caption",
    "refs_short", "contributors",
)


def _collect_slide_text(slide: dict) -> str:
    """Concatenate all prose-bearing fields on a slide into one searchable
    string. Order-preserving so position-relative findings make sense."""
    content = slide.get("content", {})
    parts: list[str] = []
    for field_name in _TEXT_FIELDS:
        val = content.get(field_name)
        if isinstance(val, str) and val:
            parts.append(val)
    for field_name in _LIST_FIELDS:
        val = content.get(field_name)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    # bullets-as-objects (implications layout)
                    for k in ("claim", "evidence_pointer"):
                        if k in item and isinstance(item[k], str):
                            parts.append(item[k])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """One ungrounded number finding."""
    slide_id: int | None
    slide_position: int
    slide_layout: str
    number: ExtractedNumber
    severity: str           # "high", "medium", "low"
    note: str               # human-readable explanation

    def to_dict(self) -> dict:
        return {
            "slide_id": self.slide_id,
            "slide_position": self.slide_position,
            "slide_layout": self.slide_layout,
            "number": self.number.to_dict(),
            "severity": self.severity,
            "note": self.note,
        }


@dataclass
class GroundedHit:
    """One verified number — slide claim ↔ REPORT match."""
    slide_id: int | None
    slide_position: int
    slide_layout: str
    number: ExtractedNumber
    match: dict             # {match_form, line_number, line_quote}

    def to_dict(self) -> dict:
        return {
            "slide_id": self.slide_id,
            "slide_position": self.slide_position,
            "slide_layout": self.slide_layout,
            "number": self.number.to_dict(),
            "match": self.match,
        }


@dataclass
class GroundingReport:
    schema_version: str = "quantitative-grounding.v1"
    draft_dir: str = ""
    report_path: str = ""
    total_numbers_found: int = 0
    total_grounded: int = 0
    total_ungrounded: int = 0
    total_skipped_years: int = 0
    findings: list[Finding] = field(default_factory=list)
    hits: list[GroundedHit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "draft_dir": self.draft_dir,
            "report_path": self.report_path,
            "summary": {
                "total_numbers_found": self.total_numbers_found,
                "total_grounded": self.total_grounded,
                "total_ungrounded": self.total_ungrounded,
                "total_skipped_years": self.total_skipped_years,
            },
            "findings": [f.to_dict() for f in self.findings],
            "hits": [h.to_dict() for h in self.hits],
        }


def check_grounding(draft_dir: Path, report_path: Path | None = None) -> GroundingReport:
    """Run the grounding check on a draft directory.

    Args:
      draft_dir: path to talks/draft_N/. Must contain slide_spec.json.
      report_path: path to REPORT.md. If None, derived from
                   draft_dir.parent.parent / 'REPORT.md'.

    Returns:
      GroundingReport with findings list (ungrounded) and hits list (grounded).
    """
    draft_dir = Path(draft_dir).resolve()
    spec_path = draft_dir / "slide_spec.json"
    if not spec_path.is_file():
        raise FileNotFoundError(f"slide_spec.json not found at {spec_path}")
    if report_path is None:
        report_path = draft_dir.parent.parent / "REPORT.md"
    if not report_path.is_file():
        raise FileNotFoundError(
            f"REPORT.md not found at {report_path}. "
            f"Derived from draft_dir={draft_dir}; pass --report-path to override."
        )

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    idx = build_report_index(report_path)
    out = GroundingReport(
        draft_dir=str(draft_dir),
        report_path=str(report_path),
    )

    for slide in spec.get("slides", []):
        # Skip layouts that legitimately contain numbers from external
        # sources (citations, page numbers, issue numbers in references).
        # These never appear in REPORT.md; flagging them produces noise.
        if slide.get("layout") in ("references", "acknowledgments"):
            continue
        text = _collect_slide_text(slide)
        if not text.strip():
            continue
        numbers = extract_numbers(text)
        for num in numbers:
            out.total_numbers_found += 1
            if num.is_year():
                out.total_skipped_years += 1
                continue
            match = _find_in_report(num, idx)
            if match is not None:
                out.total_grounded += 1
                out.hits.append(GroundedHit(
                    slide_id=slide.get("id"),
                    slide_position=slide.get("position", -1),
                    slide_layout=slide.get("layout", "?"),
                    number=num,
                    match=match,
                ))
            else:
                out.total_ungrounded += 1
                severity = _classify_severity(num)
                out.findings.append(Finding(
                    slide_id=slide.get("id"),
                    slide_position=slide.get("position", -1),
                    slide_layout=slide.get("layout", "?"),
                    number=num,
                    severity=severity,
                    note=_finding_note(num),
                ))
    return out


def _classify_severity(num: ExtractedNumber) -> str:
    """Heuristic severity grading.

    HIGH: large numbers (>1000), n= claims, ratios — these are usually
          load-bearing project claims.
    MEDIUM: percentages, decimals — easy to mis-cite.
    LOW: small integers (≤100) without other context — could be section
         numbers, figure indices, etc. that legitimately don't appear in
         REPORT.md.
    """
    if num.kind in ("ratio", "n_eq"):
        return "high"
    if num.kind == "scientific":
        return "high"
    if num.kind == "integer":
        try:
            v = int(num.canonical)
            if v > 1000:
                return "high"
            if v > 100:
                return "medium"
            return "low"
        except ValueError:
            return "medium"
    if num.kind == "percent":
        return "medium"
    if num.kind == "decimal":
        return "medium"
    return "medium"


def _finding_note(num: ExtractedNumber) -> str:
    """Build a human-readable explanation for an ungrounded number."""
    return (
        f"Number {num.raw!r} (context: {num.context_before!r}/{num.context_after!r}) "
        f"does not appear in REPORT.md in any normalized form. "
        f"Either add the number to REPORT.md, mark this finding as "
        f"advisory (a derived/cited number), or revise the slide."
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(report: GroundingReport) -> str:
    """Human-readable report."""
    lines: list[str] = []
    lines.append("# Quantitative Grounding Audit")
    lines.append("")
    lines.append(f"**Draft:** `{report.draft_dir}`")
    lines.append(f"**REPORT:** `{report.report_path}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Numbers extracted: **{report.total_numbers_found}**")
    lines.append(f"- Grounded (verified in REPORT.md): **{report.total_grounded}**")
    lines.append(f"- Ungrounded: **{report.total_ungrounded}**")
    lines.append(f"- Skipped (years 1900-2099): {report.total_skipped_years}")
    lines.append("")
    if report.total_ungrounded == 0:
        lines.append("✓ All numbers grounded in REPORT.md.")
        return "\n".join(lines) + "\n"

    # Group findings by severity
    by_sev = {"high": [], "medium": [], "low": []}
    for f in report.findings:
        by_sev[f.severity].append(f)

    for sev in ("high", "medium", "low"):
        if not by_sev[sev]:
            continue
        lines.append(f"## {sev.upper()} severity ({len(by_sev[sev])} findings)")
        lines.append("")
        for f in by_sev[sev]:
            lines.append(
                f"- **Slide {f.slide_position} (id={f.slide_id}, layout={f.slide_layout}):** "
                f"`{f.number.raw}`"
            )
            ctx = f"{f.number.context_before}{f.number.raw}{f.number.context_after}"
            ctx = ctx.replace("\n", " ").strip()
            lines.append(f"  - context: …{ctx}…")
            lines.append(f"  - kind: {f.number.kind}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_quantitative_grounding.py",
        description=__doc__.split("\n\n")[0] if __doc__ else "",
    )
    p.add_argument("draft_dir", type=Path,
                   help="Path to talks/draft_N/ containing slide_spec.json.")
    p.add_argument("--report-path", type=Path, default=None,
                   help="Override REPORT.md location (default: derive from draft_dir).")
    p.add_argument("--severity-floor",
                   choices=["low", "medium", "high"], default="low",
                   help="Don't report findings below this severity (default: low = report all).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress markdown report; still write JSON.")
    p.add_argument("--json-only", action="store_true",
                   help="Skip the .md report; emit JSON only.")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Directory to write outputs (default: <draft_dir>/audit/).")
    args = p.parse_args(argv)

    try:
        report = check_grounding(args.draft_dir, args.report_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # Apply severity floor
    sev_order = {"low": 0, "medium": 1, "high": 2}
    floor = sev_order[args.severity_floor]
    report.findings = [f for f in report.findings
                       if sev_order[f.severity] >= floor]

    out_dir = args.out_dir or (args.draft_dir / "audit")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "quantitative_grounding.json"
    json_path.write_text(json.dumps(report.to_dict(), indent=2),
                         encoding="utf-8")
    if not args.quiet and not args.json_only:
        md_path = out_dir / "quantitative_grounding.md"
        md_path.write_text(render_markdown(report), encoding="utf-8")
        print(f"Wrote {md_path}", file=sys.stderr)
    print(f"Wrote {json_path}", file=sys.stderr)

    print(f"Grounded: {report.total_grounded} / {report.total_numbers_found}",
          file=sys.stderr)
    if report.total_ungrounded > 0:
        print(f"Ungrounded ({len([f for f in report.findings])} after severity floor): "
              f"{report.total_ungrounded} (advisory)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
