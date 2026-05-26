#!/usr/bin/env python3
"""check_register_discipline.py — v0.5 Tier A.1 / D-072.

Field-class-aware register-discipline validator: detect specialist
references (notebook IDs, REPORT section markers, figure filenames,
schema versions) in audience-facing slide prose. Soft-warning by
default per D-053 / D-068 / D-072 (matches the M4a Tier B + M6 Tier
C.1 length-cap posture). Per-project allowlist via
`references/register_allowlist.md`.

The validator's contract (D-072):

  - operator-facing fields (`data_source`, `notes`): all patterns
    permitted (these are audit/provenance fields, NOT audience-
    facing). Provenance markers like
    `"REPORT.md §Finding 13; 09_final_synthesis.ipynb"` are
    legitimate here.
  - audience-facing fields (`title`, `headline`, `subtitle`,
    `caption`, `bullets`, `answer_summary`, `step_caption`,
    `context`, `implication`, `concession`, `metric_value`,
    `left_col_content`, `right_col_content`): notebook IDs / cell
    refs / .ipynb filenames / §section markers / figure filenames
    / schema versions → soft-warning. Tool versions (`Bakta v1.12.0`)
    allowed by default (sometimes audience-relevant); per-project
    allowlist can extend.
  - structural fields (`workflow_diagram.nodes[].label`,
    `methods_summary.method_*`, etc.): treated as audience-facing
    by default; allowlist applies.

Output: extends `audit/presentation_validation.json` with a P11
entry via the wrapper in validate_presentation.py
(validate_p11_register_discipline). Standalone CLI emits a
report directly for operator inspection.

Per D-072, the heuristic is intentionally regex+allowlist —
cheap, explainable, debuggable. Promote to error severity (or to
LLM-as-judge classification) only if v0.5 cut-over A/B shows
soft-warning is insufficient.
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


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "register-discipline.v1"


# ---------------------------------------------------------------------------
# Field-class taxonomy (per D-072)
# ---------------------------------------------------------------------------

# Operator-facing fields: audit/provenance — patterns permitted regardless.
OPERATOR_FIELDS: frozenset[str] = frozenset({
    "data_source",
    "notes",
    "speaker_notes",
    "speaker_notes_provenance",  # v0.3 legacy; retired per D-059 but
                                  # kept here for back-compat audit reads
})

# Audience-facing fields: the slide's user-facing text. Patterns →
# soft-warning unless allowlisted.
AUDIENCE_FIELDS: frozenset[str] = frozenset({
    # Core text fields
    "title",
    "headline",
    "subtitle",
    "punchline",
    "caption",
    "metric_value",
    # Bullet/text-list containers (member strings checked)
    "bullets",
    "step_caption",
    "answer_summary",
    "answer_detail",
    # Layout-specific audience fields
    "context",
    "implication",
    "concession",
    "left_col_content",
    "right_col_content",
    "question",         # v0.5 Q-slide field (D-071)
    "conclusion_for_next_substory",  # v0.5 handoff field (D-071)
})


# ---------------------------------------------------------------------------
# Patterns (per D-072 Tier-0 audit)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    """One register-violation pattern."""
    name: str
    regex: re.Pattern
    description: str
    permits_in_operator_fields: bool = True
    # Audience-field severity: "soft-warning" (default per D-072) or
    # "allowed" (e.g., tool versions audience-relevance).
    audience_severity: str = "soft-warning"


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        name="notebook_id",
        regex=re.compile(r'\bNB\d+\w?(?:\s*§\d+(?:[\-,]\d+)?)?\b'),
        description="Notebook ID reference (e.g., 'NB10', 'NB04b', 'NB10 §3')",
    ),
    Pattern(
        name="notebook_filename",
        regex=re.compile(r'\b\d{2,3}_\w+\.ipynb\b'),
        description="Notebook filename reference (e.g., '01_demo.ipynb')",
    ),
    Pattern(
        name="section_marker",
        regex=re.compile(r'§(?:Finding|Step|Interpretation|Hypothesis)\s+\d+'),
        description="REPORT.md section marker (e.g., '§Finding 7', '§Step 13')",
    ),
    Pattern(
        name="notebook_cell",
        regex=re.compile(r'\bcell\s+\d+\b', re.IGNORECASE),
        description="Notebook cell reference (e.g., 'cell 21')",
    ),
    Pattern(
        name="figure_filename",
        # Match patterns like `F03_recovery.png` (capital-prefixed)
        # OR `fig28_domain.svg` (lowercase `fig` prefix). The `[Ff]ig?`
        # variant tried `?ig` which doesn't match `F03_` because `F`
        # consumes the optional char and `i` isn't optional.
        regex=re.compile(
            r'\b(?:[Ff]ig|F|fig)\d{1,3}[a-z]?_\w+\.(?:png|jpg|jpeg|svg|pdf)\b'),
        description="Figure filename reference (e.g., 'F03_recovery_by_method.png')",
    ),
    Pattern(
        name="schema_version",
        regex=re.compile(r'\b[a-z_]+\.v\d+\b'),
        description="Internal schema version (e.g., 'slide_spec.v1')",
    ),
    Pattern(
        name="tool_version",
        regex=re.compile(r'\b[A-Z][a-z]+\s+v\d+(?:\.\d+){1,3}\b'),
        description="Tool/software version (e.g., 'Bakta v1.12.0')",
        # Per D-072: tool versions often audience-relevant; allowed by
        # default. Per-project allowlist can DEMOTE specific tool
        # names if a particular talk doesn't want to name versions.
        audience_severity="allowed",
    ),
)


# ---------------------------------------------------------------------------
# Allowlist (per-project; D-072)
# ---------------------------------------------------------------------------

def load_allowlist(project_dir: Optional[Path]) -> frozenset[str]:
    """Load per-project allowlist from `<project_dir>/references/
    register_allowlist.md`. Returns frozenset of allowed terms
    (case-sensitive substring matches against violation text).

    Format: one allowed term per line. Lines starting with `#` are
    comments. Empty lines ignored.

    Returns empty frozenset if file absent or unreadable (defensive;
    matches D-072 "allowlist file is optional").
    """
    if project_dir is None:
        return frozenset()
    path = project_dir / "references" / "register_allowlist.md"
    if not path.is_file():
        return frozenset()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    terms = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.add(line)
    return frozenset(terms)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RegisterViolation:
    """One register-discipline finding."""
    slide_id: Optional[int]
    field_path: str           # e.g., "title", "bullets[2]"
    field_class: str          # "operator" | "audience" | "other"
    pattern_name: str
    matched_text: str
    context_snippet: str      # ~40 chars around the match
    severity: str             # "soft-warning" | "allowed"
    allowlisted: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class RegisterReport:
    """The full register-discipline report."""
    schema_version: str
    slide_spec_path: str
    n_slides: int
    n_violations_by_severity: dict[str, int]
    n_violations_by_pattern: dict[str, int]
    allowlist_terms: list[str]
    violations: list[RegisterViolation]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "slide_spec_path": self.slide_spec_path,
            "n_slides": self.n_slides,
            "n_violations_by_severity": self.n_violations_by_severity,
            "n_violations_by_pattern": self.n_violations_by_pattern,
            "allowlist_terms": self.allowlist_terms,
            "violations": [v.to_dict() for v in self.violations],
        }


# ---------------------------------------------------------------------------
# Field-class classifier
# ---------------------------------------------------------------------------

def classify_field(field_name: str) -> str:
    """Return 'operator' | 'audience' | 'other' for a content-field name."""
    if field_name in OPERATOR_FIELDS:
        return "operator"
    if field_name in AUDIENCE_FIELDS:
        return "audience"
    return "other"


# ---------------------------------------------------------------------------
# Per-slide scanner
# ---------------------------------------------------------------------------

def _iter_prose_strings(content: dict, parent_key: str = ""):
    """Walk a slide's content dict. Yield (field_name, text) tuples
    for every leaf string. `field_name` is the immediate parent key
    (NOT a path) — matches the field-class classifier's contract.

    Lists: each element yields with its container's field name as
    `field_name` (so `bullets[3]` → field_name="bullets").

    Nested dicts (e.g., diagram.nodes[].label): each leaf takes its
    immediate parent key as field_name (so `label`, not
    `diagram.nodes[].label`). This matches D-072's field-class
    taxonomy which is keyed by leaf field name.
    """
    if isinstance(content, dict):
        for k, v in content.items():
            yield from _iter_prose_strings(v, k)
    elif isinstance(content, list):
        for item in content:
            yield from _iter_prose_strings(item, parent_key)
    elif isinstance(content, str):
        if parent_key:
            yield (parent_key, content)


def scan_slide(
    slide: dict, *, allowlist: frozenset[str] = frozenset(),
) -> list[RegisterViolation]:
    """Scan one slide for register violations. Returns a list of
    RegisterViolation entries (empty if clean).

    `allowlist` is the per-project allowlist; if any pattern match
    is a substring of an allowlisted term, the violation is marked
    `allowlisted=True` (still emitted for audit but severity becomes
    `allowed`).
    """
    slide_id = slide.get("id")
    out: list[RegisterViolation] = []
    content = slide.get("content") or {}
    for field_name, text in _iter_prose_strings(content):
        field_class = classify_field(field_name)
        for pattern in PATTERNS:
            for match in pattern.regex.finditer(text):
                matched = match.group(0)
                # Determine severity per field-class + pattern
                if field_class == "operator" and pattern.permits_in_operator_fields:
                    # Patterns are legitimate in operator fields per D-072
                    continue
                if field_class == "audience" or field_class == "other":
                    severity = pattern.audience_severity
                else:
                    severity = "soft-warning"
                # Allowlist check (substring match — case-sensitive
                # per D-072)
                is_allowlisted = any(
                    matched in term or term in matched for term in allowlist)
                if is_allowlisted:
                    severity = "allowed"
                if severity == "allowed" and not is_allowlisted:
                    # Default-allowed (e.g., tool_version in audience).
                    # Skip — not a violation worth reporting.
                    continue
                # Build context snippet (40 chars around match)
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                snippet = text[start:end].replace("\n", " ")
                out.append(RegisterViolation(
                    slide_id=slide_id,
                    field_path=field_name,
                    field_class=field_class,
                    pattern_name=pattern.name,
                    matched_text=matched,
                    context_snippet=snippet,
                    severity=severity,
                    allowlisted=is_allowlisted,
                ))
    return out


# ---------------------------------------------------------------------------
# Top-level: scan_spec + build report
# ---------------------------------------------------------------------------

def check_register_discipline(
    spec: dict,
    *,
    project_dir: Optional[Path] = None,
    slide_spec_path: str = "(unknown)",
) -> RegisterReport:
    """Run register-discipline check across all slides in a spec.

    Args:
      spec: parsed slide_spec.json dict.
      project_dir: optional project root (for loading allowlist from
        `<project_dir>/references/register_allowlist.md`).
      slide_spec_path: path string for the report's metadata (display only).

    Returns a RegisterReport. Soft-warning violations live in
    `violations` with severity="soft-warning"; allowlisted matches
    are emitted but tagged severity="allowed" + allowlisted=True
    (audit visibility).
    """
    allowlist = load_allowlist(project_dir)
    slides = spec.get("slides", []) or []
    all_violations: list[RegisterViolation] = []
    for slide in slides:
        all_violations.extend(scan_slide(slide, allowlist=allowlist))

    # Stats
    by_severity: dict[str, int] = {}
    by_pattern: dict[str, int] = {}
    for v in all_violations:
        by_severity[v.severity] = by_severity.get(v.severity, 0) + 1
        by_pattern[v.pattern_name] = by_pattern.get(v.pattern_name, 0) + 1

    return RegisterReport(
        schema_version=SCHEMA_VERSION,
        slide_spec_path=slide_spec_path,
        n_slides=len(slides),
        n_violations_by_severity=by_severity,
        n_violations_by_pattern=by_pattern,
        allowlist_terms=sorted(allowlist),
        violations=all_violations,
    )


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def format_text_report(report: RegisterReport) -> str:
    """Operator-facing Markdown summary of a register-discipline run."""
    lines = []
    lines.append(f"# Register-discipline check ({report.schema_version})")
    lines.append("")
    lines.append(f"**slide_spec:** {report.slide_spec_path}")
    lines.append(f"**slides:** {report.n_slides}")
    lines.append(f"**violations:** {len(report.violations)} "
                 f"({report.n_violations_by_severity})")
    if report.allowlist_terms:
        lines.append(f"**allowlist terms:** "
                     f"{', '.join(report.allowlist_terms[:10])}"
                     + (f" (+{len(report.allowlist_terms) - 10} more)"
                        if len(report.allowlist_terms) > 10 else ""))
    lines.append("")
    lines.append(f"**by pattern:** {report.n_violations_by_pattern}")
    lines.append("")
    if not report.violations:
        lines.append("✓ Clean — no register-discipline violations.")
        return "\n".join(lines) + "\n"

    # Group violations by slide for readability
    by_slide: dict[Optional[int], list[RegisterViolation]] = {}
    for v in report.violations:
        by_slide.setdefault(v.slide_id, []).append(v)

    lines.append("## Per-slide violations")
    lines.append("")
    for sid in sorted(by_slide.keys(), key=lambda x: (x is None, x)):
        viols = by_slide[sid]
        lines.append(f"### Slide {sid}  ({len(viols)} violation(s))")
        lines.append("")
        for v in viols:
            tag = f"[{v.severity}]" + (" [allowlisted]" if v.allowlisted else "")
            lines.append(
                f"- `{v.field_path}` ({v.field_class}) — "
                f"{v.pattern_name} `{v.matched_text}` {tag}")
            lines.append(f"    context: ...{v.context_snippet}...")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_register_discipline",
        description="v0.5 register-discipline validator (D-072). "
                    "Detect specialist refs in audience-facing slide prose.")
    p.add_argument("slide_spec", type=Path,
                   help="Path to slide_spec.json")
    p.add_argument("--project-dir", type=Path, default=None,
                   help="Project root (for loading "
                        "references/register_allowlist.md if present).")
    p.add_argument("--out", type=Path, default=None,
                   help="Output JSON path. Default: stdout as JSON.")
    p.add_argument("--report-format", choices=("json", "text"),
                   default="text",
                   help="Output format (default: text).")
    args = p.parse_args(argv)

    if not args.slide_spec.is_file():
        print(f"error: slide_spec not found: {args.slide_spec}",
              file=sys.stderr)
        return 2
    try:
        spec = json.loads(args.slide_spec.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: slide_spec JSON parse failed: {e}", file=sys.stderr)
        return 2

    report = check_register_discipline(
        spec, project_dir=args.project_dir,
        slide_spec_path=str(args.slide_spec))

    if args.report_format == "json":
        text = json.dumps(report.to_dict(), indent=2) + "\n"
    else:
        text = format_text_report(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)

    # Exit code: 0 if no soft-warnings; 0 still if soft-warnings only
    # (D-072 = soft-warning is advisory, not failing). Distinguish via
    # the report content if needed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
