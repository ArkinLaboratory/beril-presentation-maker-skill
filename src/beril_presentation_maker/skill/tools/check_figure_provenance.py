#!/usr/bin/env python3
"""check_figure_provenance.py — v0.6 figure-utilization validator
(D-080 + D-081).

Adam-rubric pin from D-079: *"every arc should back a claim or
finding by relevant figure if possible."* The v0.5.1 Tier-E read
surfaced figure under-use as a load-bearing weakness; v0.6 ships
the contract.

Per-substory contract (D-080):

  IF a curated figure exists for any of a substory's critical
  analyses, THEN at least one R-slide in that substory MUST be a
  `data_figure` slide whose `content.figure` field matches the
  curated path.

Curated-figure ↔ analysis matching (D-081 strict counting):

- The curated-figure inventory at `working/curated_figures.md`
  lists figures as `figures/NB##_name.png`.
- The substory's `**Critical analyses covered:**` lines cite
  notebooks like `NB01b_ecotype_refit.ipynb` (NB## prefix on the
  filename).
- An analysis MATCHES a curated figure iff the curated figure's
  filename's NB-id prefix matches the analysis's notebook
  filename's NB-id prefix (case-insensitive; with or without the
  trailing letter suffix — `NB04` matches both `NB04b_*` and
  `NB04h_*`).

A "data_figure used" iff (D-081):

- The slide's `layout` is `data_figure`, AND
- The slide's `content.figure` non-empty, AND
- That path exactly matches a path listed in
  `working/curated_figures.md`.

Output:

- Standalone CLI: writes `audit/figure_provenance.json`
  (`figure-provenance.v1`) by default.
- Cascade integration: `review_cascade.py::_read_figure_provenance`
  reads the audit JSON (M5b/D-073 read-if-present pattern;
  cascade never invokes this script) and lifts each finding into
  cascade Tier-1 as `figure_provenance:<finding-kind>` at P1
  (soft-warning; never gates).

Findings (kinds):

- `missing_data_figure_for_curated_analysis` — substory has ≥1
  analysis whose NB-id matches a curated figure, but the substory
  has 0 data_figure slides using any curated figure.
- `data_figure_path_not_in_curated_inventory` — a `data_figure`
  slide cites a `figure:` path that's not in the curated
  inventory (drift / fabrication).

Test coverage: `tests/unit/test_check_figure_provenance.py`.

Refs: D-080 (the contract); D-081 (strict counting rule);
D-072 (the register-discipline precedent this mirrors);
`prompts/slide_compose.v3.1_overlay.md` (the prompt-side companion).
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

SCHEMA_VERSION = "figure-provenance.v1"

# Pattern that pulls the NB-id prefix from a filename. Matches:
#   NB01b_ecotype_refit.ipynb  → NB01
#   NB04h_hmp2_external_replication.ipynb → NB04
#   NB13_phagefoundry_cocktail.png → NB13
# Strips the optional trailing letter for normalization so
# NB04b_* and NB04h_* both group under NB04 (the figure may be
# cross-referenced across sub-analyses).
_NB_PATTERN = re.compile(r"\b(NB\d+)[a-z]?_", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class FigureFinding:
    """One figure-provenance finding."""
    kind: str            # see module docstring "Findings (kinds)"
    severity: str        # "soft-warning" (D-080/D-081)
    substory_id: Optional[str]
    slide_id: Optional[int]
    message: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class FigureProvenanceReport:
    schema_version: str
    slide_spec_path: str
    substories_path: str
    curated_figures_path: str
    n_substories: int
    n_curated_figures: int
    findings: list[FigureFinding]
    n_data_figure_slides: int
    n_data_figure_using_curated: int
    utilization_rate: float  # n_data_figure_using_curated / n_curated_referenced

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        # Stable JSON field order for readability + diff-friendliness.
        return d


# ---------------------------------------------------------------------------
# Curated-figure inventory parsing
# ---------------------------------------------------------------------------

# A line that lists a curated figure path. The curator writes the
# path inside backticks at the start of a numbered heading:
#   ### 1. `figures/NB17_synthesis.png` _(source-strength: ...)_
_CURATED_PATH_RE = re.compile(
    r"`(figures/[^`]+\.(?:png|jpg|jpeg|svg|pdf))`",
    re.IGNORECASE,
)


def parse_curated_figures(curated_path: Path) -> set[str]:
    """Read `working/curated_figures.md` and return the set of
    figure paths (relative to project root). Empty set if file
    missing or malformed (defensive — same posture as the v0.5
    allowlist loader)."""
    if not curated_path.is_file():
        return set()
    try:
        text = curated_path.read_text(encoding="utf-8")
    except OSError:
        return set()
    paths = set()
    for m in _CURATED_PATH_RE.finditer(text):
        paths.add(m.group(1))
    return paths


# ---------------------------------------------------------------------------
# Substory analysis extraction
# ---------------------------------------------------------------------------

# Per 02_substories.md template: substory sections start with
#   ### S{N} — {name}
# and contain a `**Critical analyses covered:**` block of bullets.
_SUBSTORY_HEADER_RE = re.compile(
    r"^### (S\d+)\s*[—–-]", re.MULTILINE)


def parse_substory_analyses(
    substories_path: Path,
) -> dict[str, list[str]]:
    """Return {substory_id: [analysis_notebook_filename, ...]} extracted
    from `narrative/02_substories.md`. Each substory's `Critical
    analyses covered:` block is parsed; the notebook filename
    (`NBXX_name.ipynb`) is pulled from each analysis line.

    Per D-080: matching curated-figure-to-analysis is by NB-id prefix
    on the notebook filename, NOT by analysis content.
    """
    if not substories_path.is_file():
        return {}
    text = substories_path.read_text(encoding="utf-8")
    headers = list(_SUBSTORY_HEADER_RE.finditer(text))
    out: dict[str, list[str]] = {}
    for i, h in enumerate(headers):
        sid = h.group(1)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end]
        # Find the analyses block + parse out notebook filenames.
        notebooks: list[str] = []
        for line in body.splitlines():
            # Analysis bullets look like:
            #   - A1: ... — REPORT.md §"..." / NBXX_name.ipynb ...
            for nb in _NB_PATTERN.findall(line):
                # _NB_PATTERN captures the "NB##" prefix; we also
                # want the full filename for traceability. Pull it
                # via the original line — find the .ipynb token if
                # present, else fall back to the prefix alone.
                m_full = re.search(
                    r"(NB\d+[a-z]?_\w+\.ipynb)", line, re.IGNORECASE)
                if m_full:
                    notebooks.append(m_full.group(1))
                else:
                    notebooks.append(nb)
        if notebooks:
            out[sid] = notebooks
        else:
            out[sid] = []
    return out


def _nb_id(filename: str) -> Optional[str]:
    """Extract normalized NB-id from a filename. Strips trailing
    letter so `NB04b_*` and `NB04h_*` both → `NB04`. Returns None
    if no NB-id matched."""
    m = _NB_PATTERN.search(filename + "_")  # appended _ helps regex anchor
    if not m:
        # The figure case (no trailing _ after NB-id token).
        m2 = re.search(r"\b(NB\d+)", filename, re.IGNORECASE)
        if not m2:
            return None
        return m2.group(1).upper()
    return m.group(1).upper()


# ---------------------------------------------------------------------------
# slide_spec inspection
# ---------------------------------------------------------------------------

def inventory_data_figure_slides(spec: dict) -> list[tuple[int, str, str]]:
    """Return [(slide_index, substory_id, figure_path), ...] for every
    `data_figure` slide in the spec. substory_id is pulled from the
    slide's `substory_id` field (or None for boilerplate slides).
    """
    out = []
    for i, s in enumerate(spec.get("slides", [])):
        if s.get("layout") != "data_figure":
            continue
        content = s.get("content", {})
        fig = content.get("figure", "")
        sid = s.get("substory_id")
        out.append((i, sid, fig))
    return out


def slides_by_substory(spec: dict) -> dict[str, list[tuple[int, str]]]:
    """Return {substory_id: [(slide_index, layout), ...]} for every
    substory-attributed slide. Boilerplate slides (intro / acks /
    references / qa) typically have substory_id=None or "intro"; the
    figure-utilization contract per D-080 only applies to substory
    slides."""
    out: dict[str, list[tuple[int, str]]] = {}
    for i, s in enumerate(spec.get("slides", [])):
        sid = s.get("substory_id")
        if not sid or not isinstance(sid, str):
            continue
        if not sid.startswith("S"):
            continue  # intro / acks / references / qa get sid like "intro"
        out.setdefault(sid, []).append((i, s.get("layout", "?")))
    return out


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_figure_provenance(
    slide_spec_path: Path,
    substories_path: Path,
    curated_figures_path: Path,
) -> FigureProvenanceReport:
    """Run the figure-provenance check.

    Per D-080 + D-081:
    - For each substory: gather its analyses' NB-ids; gather the
      curated figures whose NB-ids match. If any curated figure
      exists for any of the substory's analyses AND the substory
      has 0 data_figure slides using a curated figure, emit
      `missing_data_figure_for_curated_analysis`.
    - For each `data_figure` slide: if its `content.figure` path
      isn't in the curated inventory, emit
      `data_figure_path_not_in_curated_inventory`.

    Both findings are P1 soft-warning per D-080.
    """
    try:
        spec = json.loads(slide_spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        spec = {"slides": []}
    curated = parse_curated_figures(curated_figures_path)
    analyses_per_substory = parse_substory_analyses(substories_path)

    # Build NB-id index from curated figures: {NB##: [figure_path, ...]}
    curated_by_nb: dict[str, list[str]] = {}
    for fig in curated:
        nb = _nb_id(Path(fig).name)
        if nb:
            curated_by_nb.setdefault(nb, []).append(fig)

    # Build per-substory slide inventory.
    substory_slides = slides_by_substory(spec)
    df_slides = inventory_data_figure_slides(spec)

    findings: list[FigureFinding] = []

    # Per-substory check.
    n_substories_with_curated = 0
    n_substories_covered = 0
    for sid, notebooks in analyses_per_substory.items():
        # Which curated figures map to this substory's analyses?
        nb_ids = {_nb_id(nb) for nb in notebooks if _nb_id(nb)}
        relevant_curated = set()
        for nb_id in nb_ids:
            for fig in curated_by_nb.get(nb_id, []):
                relevant_curated.add(fig)
        if not relevant_curated:
            # No curated figure for this substory's analyses; the
            # rule doesn't apply. (D-080 explicitly: rule fires
            # only when curated figure exists.)
            continue
        n_substories_with_curated += 1
        # Count data_figure slides in THIS substory that point at
        # any of the relevant curated figures.
        used = []
        for slide_idx, slide_sid, fig in df_slides:
            if slide_sid != sid:
                continue
            if fig in relevant_curated:
                used.append((slide_idx, fig))
        if not used:
            n_curated = len(relevant_curated)
            findings.append(FigureFinding(
                kind="missing_data_figure_for_curated_analysis",
                severity="soft-warning",
                substory_id=sid,
                slide_id=None,
                message=(
                    f"substory {sid} cites analyses with "
                    f"{n_curated} curated figure(s) available "
                    f"({', '.join(sorted(relevant_curated))}) but "
                    f"has 0 data_figure slides using them — per "
                    f"D-080, at least one R-slide must be a "
                    f"data_figure using a curated figure when one "
                    f"exists for the analysis."),
                evidence={
                    "substory_analyses_notebooks": notebooks,
                    "relevant_curated_figures": sorted(relevant_curated),
                    "n_data_figure_slides_in_substory": sum(
                        1 for (_, ssid, _) in df_slides if ssid == sid),
                },
            ))
        else:
            n_substories_covered += 1

    # Per-data_figure-slide check: figure path must be in curated
    # inventory (D-081 strict counting + per-prompt "Curated-figure-
    # substitution" anti-pattern).
    n_df_using_curated = 0
    for slide_idx, slide_sid, fig in df_slides:
        if not fig:
            # data_figure slide with empty `figure` — different
            # validator's territory (slide_spec.py validation).
            continue
        if fig in curated:
            n_df_using_curated += 1
            continue
        findings.append(FigureFinding(
            kind="data_figure_path_not_in_curated_inventory",
            severity="soft-warning",
            substory_id=slide_sid,
            slide_id=slide_idx,
            message=(
                f"data_figure slide {slide_idx} references "
                f"figure path {fig!r} which is NOT in the "
                f"curated-figures inventory at "
                f"{curated_figures_path}. Either the curator "
                f"missed this figure (regenerate curated_figures.md) "
                f"or the composer fabricated a non-curated path "
                f"(D-080 anti-pattern: curated-figure-substitution; "
                f"prefer the curator's shortlist)."),
            evidence={
                "figure_path": fig,
                "curated_inventory_size": len(curated),
            },
        ))

    # Utilization rate: fraction of substories with curated figures
    # available that actually placed a data_figure for one.
    rate = (n_substories_covered / n_substories_with_curated
            if n_substories_with_curated > 0 else 1.0)

    return FigureProvenanceReport(
        schema_version=SCHEMA_VERSION,
        slide_spec_path=str(slide_spec_path),
        substories_path=str(substories_path),
        curated_figures_path=str(curated_figures_path),
        n_substories=len(analyses_per_substory),
        n_curated_figures=len(curated),
        findings=findings,
        n_data_figure_slides=len(df_slides),
        n_data_figure_using_curated=n_df_using_curated,
        utilization_rate=rate,
    )


# ---------------------------------------------------------------------------
# Text report formatter (mirrors check_register_discipline.format_text_report)
# ---------------------------------------------------------------------------

def format_text_report(report: FigureProvenanceReport) -> str:
    lines = []
    lines.append(f"# Figure-provenance check ({report.schema_version})")
    lines.append("")
    lines.append(f"**slide_spec:** {report.slide_spec_path}")
    lines.append(f"**substories:** {report.substories_path}")
    lines.append(f"**curated_figures:** {report.curated_figures_path}")
    lines.append(f"**substories scanned:** {report.n_substories}")
    lines.append(f"**curated figures available:** {report.n_curated_figures}")
    lines.append(f"**data_figure slides:** {report.n_data_figure_slides}")
    lines.append(f"**data_figure slides using curated:** "
                 f"{report.n_data_figure_using_curated}")
    lines.append(f"**utilization rate:** {report.utilization_rate:.2%} "
                 f"(target ≥70% per D-081)")
    lines.append("")
    if not report.findings:
        lines.append("No findings — figure-provenance contract satisfied.")
        return "\n".join(lines)
    lines.append(f"## {len(report.findings)} finding(s)")
    lines.append("")
    for f in report.findings:
        loc = []
        if f.substory_id:
            loc.append(f"substory={f.substory_id}")
        if f.slide_id is not None:
            loc.append(f"slide={f.slide_id}")
        loc_str = " ".join(loc) if loc else "(deck-level)"
        lines.append(f"### {f.kind} [{f.severity}] — {loc_str}")
        lines.append("")
        lines.append(f.message)
        lines.append("")
        if f.evidence:
            lines.append("Evidence:")
            for k, v in f.evidence.items():
                lines.append(f"  - {k}: {v}")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="check_figure_provenance.py",
        description=(
            "v0.6 figure-utilization validator (D-080/D-081). "
            "Per Adam-rubric: every arc should back a claim or "
            "finding by relevant figure if possible. Soft-warning "
            "(advisory)."),
    )
    ap.add_argument(
        "--draft-dir", type=Path, required=True,
        help="Path to the draft directory "
             "(<BERIL_ROOT>/projects/<id>/talks/draft_N).")
    ap.add_argument(
        "--slide-spec-path", type=Path,
        help="Override: path to slide_spec.json "
             "(default: <draft-dir>/working/slide_spec.json).")
    ap.add_argument(
        "--substories-path", type=Path,
        help="Override: path to 02_substories.md "
             "(default: <draft-dir>/narrative/02_substories.md).")
    ap.add_argument(
        "--curated-figures-path", type=Path,
        help="Override: path to curated_figures.md "
             "(default: <draft-dir>/working/curated_figures.md).")
    ap.add_argument(
        "--out", type=Path,
        help="Output path. Default for json: "
             "<draft-dir>/audit/figure_provenance.json. "
             "Default for text: stdout.")
    ap.add_argument(
        "--report-format", choices=["json", "text"], default="text",
        help="Output format (default: text).")
    args = ap.parse_args(argv)

    draft_dir = args.draft_dir
    slide_spec = (args.slide_spec_path
                  or (draft_dir / "working" / "slide_spec.json"))
    substories = (args.substories_path
                  or (draft_dir / "narrative" / "02_substories.md"))
    curated = (args.curated_figures_path
               or (draft_dir / "working" / "curated_figures.md"))

    report = check_figure_provenance(slide_spec, substories, curated)

    if args.report_format == "json":
        out_path = args.out or (draft_dir / "audit"
                                / "figure_provenance.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"wrote {out_path}", file=sys.stderr)
    else:
        text = format_text_report(report)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
