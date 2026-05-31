#!/usr/bin/env python3
"""check_curator_figure_floor.py — per-substory figure-floor validator
(v0.8/D-093).

Adam's v0.7 Tier-I finding 1: "I am still surprised at how often a
sub-arc has no figures." Mechanically the v0.7 D-085 figure-relevance
contract was 100% satisfied (every curated figure used; 0
`relevant_figure_not_used` findings on both decks), but the
**curator-stage** shortlist was too narrow — substories had 0 curated
figures despite their analyses' notebooks containing candidate
figures in the project's full inventory. The slide_compose stage
can't conjure figures the curator didn't surface; the existing
figure-provenance validator gave empty-shortlist substories a free
pass (no curated figure → no contract to violate).

This validator closes that gap. Per substory:

  - Inventory candidates: figures in `figures/` whose NB-id prefix
    matches any of the substory's analyses notebooks (from
    02_substories.md `**Critical analyses covered:**`).
  - Curated coverage: curated figures (in `working/curated_figures.md`)
    whose NB-id prefix matches.

  Finding: `substory_no_curated_figure_despite_candidates`
  fires when `inventory_candidates > 0 AND curated_coverage == 0`.
  P1 soft-warning (advisory; never gates the cascade). Adam reads
  the cascade summary to decide whether to re-run curation or accept
  the gap (a substory may legitimately have no figure even when
  candidates exist — e.g., the candidate is a hyperparameter scan
  not worth showing).

D-093 belt-and-suspenders pairing: this validator IS the
suspenders. The belt is `curate_figures.curate_for_mode(...,
substory_analyses=...)` extension which deterministically promotes
≥1 figure per substory at curation time. The validator catches
regressions when the orchestrator stops passing substory-analyses,
when the inventory grows but the curator's heuristic doesn't, or
when the per-substory NB-id-match rule misses a candidate the
filename heuristic should have caught.

NB-id matching rules (mirror check_figure_provenance.py):

  - Pattern: `\\b(NB\\d+)[a-z]?` — strips optional trailing single
    letter (NB04b → NB04). A figure may map to multiple NB-ids
    (a re-saved figure across notebooks); a substory may cite
    multiple notebooks. Coverage = any-overlap.
  - Inventory candidates source: `figures/*` filenames + (when
    figures_inventory.md is parseable) the inventory's full
    notebook-origin records. Validator prefers the inventory MD
    when present (richer signal); falls back to filename scan.
  - Curated source: `working/curated_figures.md` numbered headings
    of shape `### N. \\`figures/NB##_*.png\\``.

Output:

  - Standalone CLI: writes
    `audit/curator_figure_floor.json`
    (`curator-figure-floor.v1`) by default. Schema:

      {
        "schema_version": "curator-figure-floor.v1",
        "substories_path": "...",
        "curated_figures_path": "...",
        "figures_dir": "...",
        "n_substories": N,
        "n_curated_figures": M,
        "findings": [
          {
            "kind": "substory_no_curated_figure_despite_candidates",
            "severity": "soft-warning",
            "substory_id": "S2",
            "message": "...",
            "evidence": {
              "candidate_nb_ids": ["NB04", "NB07"],
              "candidate_figures": ["figures/NB04_x.png", ...],
              "curated_nb_ids": ["NB01", "NB13"]
            }
          },
          ...
        ],
        "summary": {
          "n_substories_with_candidates": ...,
          "n_substories_uncovered": ...,
          "n_substories_no_candidates": ...,
          "coverage_rate": float
        }
      }

  - Cascade integration: `review_cascade.py::_read_curator_figure_floor`
    reads the audit JSON (read-if-present pattern; cascade never
    invokes this script) and lifts each finding into cascade Tier-1
    as `curator_figure_floor:<finding-kind>` at P1 (soft-warning;
    never gates).

Test coverage: `tests/unit/test_check_curator_figure_floor.py`.

Refs: D-093 (this validator's spec); D-080 (the figure-provenance
validator pattern this mirrors); D-085 (the v0.7 D-085 contract this
complements by catching the upstream curator-stage gap); D-089 (the
parallel cross-tenant-grounding validator pattern).
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

SCHEMA_VERSION = "curator-figure-floor.v1"

# NB-id pattern: matches `NB04`, `NB04b`, `NB12h`, etc. Strips
# trailing single letter so NB04b and NB04h both group under NB04
# (cross-sub-analysis figure association — same rule as
# check_figure_provenance.py).
_NB_ID_RE = re.compile(r"\b(NB\d+)[a-z]?", re.IGNORECASE)

# Substory header pattern (02_substories.md template).
_SUBSTORY_HEADER_RE = re.compile(
    r"^### (S\d+)\s*[—–\-]", re.MULTILINE)

# Notebook filename pattern in the **Critical analyses covered:** bullets.
# v3/v3.1/v3.2 substory_design overlays produced lines like:
#   - A1: ... — REPORT.md §"..." / NB04b_refit.ipynb ...
# This pattern matches the full filename.
_NB_FULL_RE = re.compile(
    r"\b(NB\d+[a-z]?_\w+\.ipynb)", re.IGNORECASE)

# v0.8 Tier G live discovery: v3.3 substory_design produces
# analyses lines citing bare NB-id tokens instead of full filenames:
#   - A1: ... — REPORT.md §Pillar 1 item 1; NB01b
#   - A3: ... — REPORT.md §Pillar 1 item 2; NB02 / NB16
# The bare-token fallback matches these. Used only when the line has
# NO _NB_FULL_RE match (so v3/v3.1/v3.2 output still produces full
# filenames; v3.3 output produces bare tokens). The substory NB-id
# set is then computed from BOTH sources.
_NB_BARE_RE = re.compile(r"\b(NB\d+[a-z]?)\b", re.IGNORECASE)

# Curated figure path pattern (mirrors check_figure_provenance.py).
_CURATED_PATH_RE = re.compile(
    r"`(figures/[^`]+\.(?:png|jpg|jpeg|svg|pdf))`",
    re.IGNORECASE,
)

# Inventory figure-heading path pattern (figures_inventory.md format).
# Lines look like `### \`figures/NB17_synthesis.png\``.
_INVENTORY_PATH_RE = re.compile(
    r"^### `(figures/[^`]+\.(?:png|jpg|jpeg|svg|pdf))`",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class FigureFloorFinding:
    """One curator-figure-floor finding."""
    kind: str            # "substory_no_curated_figure_despite_candidates"
    severity: str        # "soft-warning" (D-093 P1 advisory)
    substory_id: Optional[str]
    message: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class FigureFloorReport:
    schema_version: str
    substories_path: str
    curated_figures_path: str
    figures_dir: str
    n_substories: int
    n_curated_figures: int
    findings: list[FigureFloorFinding]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "substories_path": self.substories_path,
            "curated_figures_path": self.curated_figures_path,
            "figures_dir": self.figures_dir,
            "n_substories": self.n_substories,
            "n_curated_figures": self.n_curated_figures,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_substory_analyses(
    substories_path: Path,
) -> dict[str, list[str]]:
    """Parse `02_substories.md` for {substory_id: [notebook_filename, ...]}.

    Mirrors check_figure_provenance.py::parse_substory_analyses(). Each
    substory's body is scanned for `NBXX_name.ipynb` tokens; bullets
    typically appear under `**Critical analyses covered:**` but the
    parser doesn't gate on that header — any NB filename in the body
    counts (defensive against prompt-overlay drift).
    """
    if not substories_path.is_file():
        return {}
    try:
        text = substories_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    headers = list(_SUBSTORY_HEADER_RE.finditer(text))
    out: dict[str, list[str]] = {}
    for i, h in enumerate(headers):
        sid = h.group(1)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end]
        notebooks: list[str] = []
        for line in body.splitlines():
            # Prefer full filenames (v3/v3.1/v3.2 format) when present —
            # they're richer signal for traceability + figure-provenance
            # cross-reference. Fall back to bare NB-id tokens (v3.3
            # format) only when no full filename matched on the line.
            # The downstream NB-id matcher strips suffixes/extensions
            # uniformly, so both shapes contribute equivalent NB-ids.
            full_matches = list(_NB_FULL_RE.finditer(line))
            if full_matches:
                for m in full_matches:
                    notebooks.append(m.group(1))
            else:
                for m in _NB_BARE_RE.finditer(line):
                    notebooks.append(m.group(1))
        out[sid] = notebooks
    return out


def parse_curated_figures(curated_path: Path) -> list[str]:
    """Return ordered list of curated figure paths from
    `working/curated_figures.md`. Empty list if file missing or
    malformed."""
    if not curated_path.is_file():
        return []
    try:
        text = curated_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [m.group(1) for m in _CURATED_PATH_RE.finditer(text)]


def parse_inventory_figures(inventory_path: Path) -> list[str]:
    """Return ordered list of inventory figure paths from
    `working/figures_inventory.md`. Empty list if file missing or
    malformed."""
    if not inventory_path.is_file():
        return []
    try:
        text = inventory_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [m.group(1) for m in _INVENTORY_PATH_RE.finditer(text)]


def scan_figures_dir(figures_dir: Path) -> list[str]:
    """Return ordered list of `figures/<filename>` paths under
    `figures_dir`. Filesystem fallback when figures_inventory.md is
    unavailable. Recurses one level (matches the figure-discovery
    convention used by curate_figures.py)."""
    if not figures_dir.is_dir():
        return []
    paths: list[str] = []
    exts = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".webp",
            ".gif", ".tif", ".tiff"}
    for p in sorted(figures_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in exts:
            paths.append(f"figures/{p.name}")
        elif p.is_dir():
            for q in sorted(p.iterdir()):
                if q.is_file() and q.suffix.lower() in exts:
                    paths.append(f"figures/{p.name}/{q.name}")
    return paths


# ---------------------------------------------------------------------------
# NB-id helpers
# ---------------------------------------------------------------------------

def _nb_ids(token: str) -> set[str]:
    """All NB-ids in a string (normalized uppercase, no trailing letter)."""
    return {m.group(1).upper() for m in _NB_ID_RE.finditer(token)}


def figures_by_nb_id(figure_paths: list[str]) -> dict[str, list[str]]:
    """Index figure paths by NB-id. A figure with no NB-id is skipped
    (it can't be matched against an analysis)."""
    out: dict[str, list[str]] = {}
    for fp in figure_paths:
        for nbid in _nb_ids(fp):
            out.setdefault(nbid, []).append(fp)
    return out


def substory_nb_ids(notebook_filenames: list[str]) -> set[str]:
    """NB-id set for a substory's analyses notebook filenames."""
    ids: set[str] = set()
    for fn in notebook_filenames:
        ids |= _nb_ids(fn)
    return ids


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def check_figure_floor(
    substories_path: Path,
    curated_figures_path: Path,
    inventory_figures_path: Path | None = None,
    figures_dir: Path | None = None,
) -> FigureFloorReport:
    """Run the per-substory figure-floor check.

    Inventory source preference:
      1. If `inventory_figures_path` parses, use it (richest signal
         — captures notebook savefig origins via the path itself).
      2. Else `scan_figures_dir(figures_dir)` (filesystem fallback).

    Both are NB-id-prefix-matched against substory analyses.

    Returns a FigureFloorReport (always; never raises on missing
    inputs — findings list may be empty if inputs are missing).
    """
    substory_analyses = parse_substory_analyses(substories_path)
    curated_paths = parse_curated_figures(curated_figures_path)
    inv_paths: list[str] = []
    if inventory_figures_path is not None:
        inv_paths = parse_inventory_figures(inventory_figures_path)
    if not inv_paths and figures_dir is not None:
        inv_paths = scan_figures_dir(figures_dir)

    curated_idx = figures_by_nb_id(curated_paths)
    inventory_idx = figures_by_nb_id(inv_paths)

    findings: list[FigureFloorFinding] = []
    n_with_candidates = 0
    n_uncovered = 0
    n_no_candidates = 0

    for sid, analyses in substory_analyses.items():
        sub_ids = substory_nb_ids(analyses)
        if not sub_ids:
            n_no_candidates += 1
            continue
        candidate_ids = sub_ids & set(inventory_idx.keys())
        if not candidate_ids:
            n_no_candidates += 1
            continue
        n_with_candidates += 1
        curated_ids_for_sub = sub_ids & set(curated_idx.keys())
        if curated_ids_for_sub:
            # At least one curated figure covers this substory.
            continue
        # Uncovered: inventory has candidates but curator picked none.
        n_uncovered += 1
        # Collect the candidate figures for evidence.
        candidate_figs = sorted({
            fp for nbid in candidate_ids
            for fp in inventory_idx.get(nbid, [])
        })
        findings.append(FigureFloorFinding(
            kind="substory_no_curated_figure_despite_candidates",
            severity="soft-warning",
            substory_id=sid,
            message=(
                f"substory {sid} has 0 curated figures despite "
                f"{len(candidate_ids)} candidate NB-id(s) "
                f"{sorted(candidate_ids)} in the inventory "
                f"(curator dropped them)"),
            evidence={
                "candidate_nb_ids": sorted(candidate_ids),
                "candidate_figures": candidate_figs,
                "curated_nb_ids": sorted(curated_idx.keys()),
            },
        ))

    total_with_or_uncovered = n_with_candidates  # by construction
    if total_with_or_uncovered > 0:
        coverage_rate = (
            (n_with_candidates - n_uncovered) / total_with_or_uncovered)
    else:
        coverage_rate = 1.0  # no relevant substories → trivially 100%

    summary = {
        "n_substories_with_candidates": n_with_candidates,
        "n_substories_uncovered": n_uncovered,
        "n_substories_no_candidates": n_no_candidates,
        "coverage_rate": coverage_rate,
    }

    return FigureFloorReport(
        schema_version=SCHEMA_VERSION,
        substories_path=str(substories_path),
        curated_figures_path=str(curated_figures_path),
        figures_dir=str(figures_dir) if figures_dir else "",
        n_substories=len(substory_analyses),
        n_curated_figures=len(curated_paths),
        findings=findings,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_curator_figure_floor.py",
        description=(
            "Per-substory curator figure-floor validator (D-093). "
            "Emits soft-warnings when a substory has 0 curated "
            "figures despite candidates existing in the project's "
            "figure inventory. Writes audit/curator_figure_floor.json."
        ),
    )
    p.add_argument(
        "--project-dir", type=Path, required=True,
        help="BERIL project directory. The validator looks for "
             "figures/ relative to this path as a fallback when "
             "--inventory is unavailable.")
    p.add_argument(
        "--substories", type=Path, required=True,
        help="Path to narrative/02_substories.md.")
    p.add_argument(
        "--curated-figures", type=Path, required=True,
        help="Path to working/curated_figures.md.")
    p.add_argument(
        "--inventory", type=Path, default=None,
        help="Path to working/figures_inventory.md (preferred "
             "inventory source). Falls back to filesystem scan of "
             "PROJECT_DIR/figures/ if omitted or unreadable.")
    p.add_argument(
        "--output", type=Path, default=None,
        help="Where to write the audit JSON. Defaults to "
             "PROJECT_DIR/talks/draft_*/audit/curator_figure_floor.json "
             "if --draft-dir is supplied; otherwise stdout.")
    p.add_argument(
        "--draft-dir", type=Path, default=None,
        help="Draft directory under talks/. When supplied, the audit "
             "JSON lands at DRAFT_DIR/audit/curator_figure_floor.json.")

    args = p.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"project_dir not found: {args.project_dir}", file=sys.stderr)
        return 2

    figures_dir = args.project_dir / "figures"
    report = check_figure_floor(
        substories_path=args.substories,
        curated_figures_path=args.curated_figures,
        inventory_figures_path=args.inventory,
        figures_dir=figures_dir,
    )

    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    elif args.draft_dir is not None:
        out_path = args.draft_dir / "audit" / "curator_figure_floor.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(f"wrote {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(payload)

    # Non-zero exit ONLY on hard errors (missing required inputs).
    # P1 findings are advisory — exit 0 so the orchestrator + cascade
    # treat them as soft signals, mirroring check_figure_provenance.py.
    return 0


if __name__ == "__main__":
    sys.exit(main())
