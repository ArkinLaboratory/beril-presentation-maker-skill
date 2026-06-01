#!/usr/bin/env python3
"""curate_figures.py — figure inventory + mode-aware budget selection.

Forked from beril-paper-writer-skill/extract_figures.py 2026-04-26 with
two presentation-maker-specific additions:

  - MODE_FIGURE_BUDGETS table — per SPEC §5 + §8.1, each talk mode has
    a target figure-count range (talk-30: 4–10, talk-15: 3–6,
    lightning-5: 2–3, poster: 2–4, talk-45: 6–12).

  - `curate_for_mode(inventory, mode)` — given the full figure
    inventory and a mode, picks a heuristic shortlist by source-strength
    score (REPORT-referenced > notebook-context > filename-only). The
    slide-compose prompt then makes the final throughline-aware choice
    from this curated set; this function exists to give the prompt a
    bounded starting set rather than the full project inventory.

The body — directory walking, REPORT.md image-reference parsing,
notebook savefig AST extraction, caption candidate ranking — is
unchanged from paper-writer\'s extract_figures.py.

Standalone CLI + importable module. Output filename:
`figures_inventory.md` (paper-writer convention; reused as-is).
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Image-format inference
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".svg": "svg",
    ".pdf": "pdf",
    ".webp": "webp",
    ".tif": "tiff",
    ".tiff": "tiff",
}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXTENSIONS


def infer_image_format(path: Path) -> str:
    return _IMAGE_EXTENSIONS.get(path.suffix.lower(), "unknown")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CaptionCandidate:
    """One caption candidate for a figure, with its source."""

    source: str           # "report" | "notebook_md" | "filename"
    text: str
    context: dict = field(default_factory=dict)
    # context fields by source:
    #   report:      {"line": int, "section": Optional[str]}
    #   notebook_md: {"notebook": str, "preceding_cell": int}
    #   filename:    {} (no context needed)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SavefigOrigin:
    """One savefig call that produced (or might have produced) a figure."""

    notebook: str         # relative path
    cell: int
    line: int
    raw_call: str         # snippet of the savefig call as written

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class FigureRecord:
    """All metadata for one figure file."""

    path: str             # relative to project_dir
    filename: str
    size_bytes: int
    format: str           # "png" | "jpeg" | etc.
    captions: list[CaptionCandidate] = field(default_factory=list)
    savefig_origins: list[SavefigOrigin] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "format": self.format,
            "captions": [c.to_dict() for c in self.captions],
            "savefig_origins": [s.to_dict() for s in self.savefig_origins],
        }


@dataclass
class FigureInventoryReport:
    """Top-level report from a figure-extraction run."""

    project_dir: str
    figures_dirs: list[str]   # relative paths actually scanned
    figures: list[FigureRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "project_dir": self.project_dir,
            "figures_dirs": self.figures_dirs,
            "figures": [f.to_dict() for f in self.figures],
        }
        d["summary"] = self._summary()
        return d

    def _summary(self) -> dict:
        from collections import Counter
        formats = Counter(f.format for f in self.figures)
        with_notebook = sum(1 for f in self.figures if f.savefig_origins)
        with_report = sum(
            1 for f in self.figures
            if any(c.source == "report" for c in f.captions)
        )
        with_filename_only = sum(
            1 for f in self.figures
            if not f.savefig_origins
            and not any(c.source == "report" for c in f.captions)
        )
        total_bytes = sum(f.size_bytes for f in self.figures)
        return {
            "total_figures": len(self.figures),
            "total_size_bytes": total_bytes,
            "by_format": dict(formats),
            "with_notebook_origin": with_notebook,
            "with_report_reference": with_report,
            "filename_only": with_filename_only,
        }


# ---------------------------------------------------------------------------
# Filename → caption heuristic
# ---------------------------------------------------------------------------

# Common figure-filename prefixes we strip to recover a sensible caption.
# Examples:
#   fig01_growth_curves.png   → "Growth curves"
#   01_carbon_util.png        → "Carbon util"
#   NB00_per_strain.png       → "Per strain"
#   figure_3_inhibition.png   → "Inhibition"
_FILENAME_PREFIX_RE = re.compile(
    r"^(?:fig(?:ure)?_?|nb_?|panel_?)?\d+[a-z]?[_\-]?",
    re.IGNORECASE,
)


def filename_to_caption(filename: str) -> str:
    """Convert a figure filename into a fallback caption."""
    stem = Path(filename).stem
    cleaned = _FILENAME_PREFIX_RE.sub("", stem)
    cleaned = cleaned.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        # Nothing after stripping the prefix; use the original stem.
        cleaned = stem.replace("_", " ").replace("-", " ").strip()
    # Capitalize first letter; keep rest as-is (preserves acronyms).
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


# ---------------------------------------------------------------------------
# REPORT.md image-reference parser
# ---------------------------------------------------------------------------

# Markdown image syntax: ![alt text](url)
# alt text may contain anything except a bare ']'; url is everything up to ')'.
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


@dataclass
class ReportImageRef:
    """One image reference found in REPORT.md."""

    line: int
    alt_text: str
    url: str
    section: Optional[str]  # nearest preceding H1/H2 header text


def parse_report_image_references(report_text: str) -> list[ReportImageRef]:
    """Extract every `![alt](url)` reference from REPORT.md, with context."""
    refs: list[ReportImageRef] = []
    current_section: Optional[str] = None
    for line_no, line in enumerate(report_text.split("\n"), start=1):
        # Update section context if this is a header.
        m_hdr = re.match(r"^#{1,2}\s+(.+?)\s*#*\s*$", line)
        if m_hdr:
            current_section = m_hdr.group(1).strip()
        for m in _MD_IMAGE_RE.finditer(line):
            refs.append(ReportImageRef(
                line=line_no,
                alt_text=m.group(1).strip(),
                url=m.group(2).strip(),
                section=current_section,
            ))
    return refs


# ---------------------------------------------------------------------------
# Notebook savefig walker
# ---------------------------------------------------------------------------

_MAGIC_RE = re.compile(r"^\s*[%!?]")


def _strip_jupyter_magics(source: str) -> str:
    """Replace IPython magics / shell calls with blank lines (preserves
    line numbers). Vendored from extract_methods.py to keep this script
    independent — same 10-line helper, no shared-module dance."""
    out_lines: list[str] = []
    for line in source.split("\n"):
        out_lines.append("" if _MAGIC_RE.match(line) else line)
    return "\n".join(out_lines)


def _last_string_in_path_expr(node: ast.AST) -> Optional[str]:
    """Walk a path-construction expression and return the rightmost
    string literal. Handles common patterns:

      'foo.png'                        → 'foo.png'
      FIGS / 'foo.png'                 → 'foo.png'
      FIGS / 'sub' / 'foo.png'         → 'foo.png'
      Path(...) / 'foo.png'            → 'foo.png'
      os.path.join(FIGS, 'foo.png')    → 'foo.png'
      str(FIGS / 'foo.png')            → 'foo.png'
      f'foo.png'                       → 'foo.png'  (constant joined-str)
    """
    # Simple string literal
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # f-string with no interpolation — single Constant inside JoinedStr
    if isinstance(node, ast.JoinedStr):
        if len(node.values) == 1 and isinstance(node.values[0], ast.Constant):
            return node.values[0].value
        # Joined-str with interpolation: try to recover the trailing literal
        # if the last value is a Constant.
        if node.values and isinstance(node.values[-1], ast.Constant):
            tail = node.values[-1].value
            if isinstance(tail, str) and "." in tail:
                return tail
        return None
    # BinOp with `/`: take the right side
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = _last_string_in_path_expr(node.right)
        if right:
            return right
        # Fall through to the left side just in case
        return _last_string_in_path_expr(node.left)
    # Call: os.path.join, Path(...), str(...)
    if isinstance(node, ast.Call):
        # Check the function being called
        func_path = []
        f = node.func
        while isinstance(f, ast.Attribute):
            func_path.insert(0, f.attr)
            f = f.value
        if isinstance(f, ast.Name):
            func_path.insert(0, f.id)
        full = ".".join(func_path)
        if full in ("os.path.join", "Path", "pathlib.Path", "str"):
            # Look at the last positional arg
            if node.args:
                return _last_string_in_path_expr(node.args[-1])
    return None


def _is_savefig_call(node: ast.Call) -> bool:
    """True if this Call looks like a `*.savefig(...)` call.

    Catches `plt.savefig`, `fig.savefig`, `ax.figure.savefig`,
    `pyplot.savefig`, etc. — any Attribute call where the trailing
    attribute name is 'savefig'.
    """
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "savefig"
    )


@dataclass
class SavefigCall:
    """One savefig call discovered in a notebook cell."""

    notebook: str
    cell: int
    line: int
    saved_basename: Optional[str]   # extracted figure filename, if recoverable
    raw_call: str
    preceding_md_cell_index: Optional[int]


def _walk_notebook_savefigs(
    notebook_path: Path, project_dir: Path
) -> tuple[list[SavefigCall], dict[int, str]]:
    """Walk one notebook for savefig calls.

    Returns (savefig_calls, markdown_cells_by_index) where markdown_cells
    is keyed by CODE-CELL index (so a code cell at index N's preceding
    markdown cell is in the dict at key N).
    """
    import nbformat
    rel_path = str(notebook_path.relative_to(project_dir))
    try:
        nb = nbformat.read(str(notebook_path), as_version=4)
    except Exception:
        return [], {}

    cells = list(nb.cells)
    savefigs: list[SavefigCall] = []

    # Map: code-cell index → text of the most recent preceding markdown cell.
    # We iterate in document order, tracking the last-seen markdown cell.
    last_md_text: Optional[str] = None
    md_by_code_index: dict[int, str] = {}
    code_index = 0
    for cell in cells:
        if cell.cell_type == "markdown":
            text = cell.source if isinstance(cell.source, str) else "".join(cell.source)
            if text.strip():
                last_md_text = text.strip()
        elif cell.cell_type == "code":
            code_index += 1
            if last_md_text is not None:
                md_by_code_index[code_index] = last_md_text
                last_md_text = None  # consume — only attribute to one code cell

    # Now AST-walk each code cell looking for savefig calls.
    code_index = 0
    for cell in cells:
        if cell.cell_type != "code":
            continue
        code_index += 1
        source = cell.source if isinstance(cell.source, str) else "".join(cell.source)
        cleaned = _strip_jupyter_magics(source)
        if not cleaned.strip():
            continue
        try:
            tree = ast.parse(cleaned)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_savefig_call(node):
                continue
            # First positional arg is the path
            saved = None
            if node.args:
                saved = _last_string_in_path_expr(node.args[0])
            if saved is not None:
                # Reduce to basename for matching
                saved_basename: Optional[str] = Path(saved).name
            else:
                saved_basename = None
            try:
                raw = ast.unparse(node)
                if len(raw) > 200:
                    raw = raw[:197] + "..."
            except Exception:
                raw = "(unparseable)"
            savefigs.append(SavefigCall(
                notebook=rel_path,
                cell=code_index,
                line=node.lineno,
                saved_basename=saved_basename,
                raw_call=raw,
                preceding_md_cell_index=code_index if code_index in md_by_code_index else None,
            ))

    return savefigs, md_by_code_index


# ---------------------------------------------------------------------------
# Figure inventory
# ---------------------------------------------------------------------------

# Directories where figures might live, relative to project_dir.
_FIGURE_DIR_CANDIDATES = ("figures", "figs", "plots", "output/figures", "results/figures")


def find_figures_dirs(project_dir: Path) -> list[Path]:
    """Return all candidate figure directories that exist."""
    found: list[Path] = []
    for cand in _FIGURE_DIR_CANDIDATES:
        p = project_dir / cand
        if p.is_dir():
            found.append(p)
    return found


def find_figure_files(project_dir: Path) -> list[Path]:
    """Walk all candidate figure dirs and return image files (sorted)."""
    out: set[Path] = set()
    for fd in find_figures_dirs(project_dir):
        for p in fd.rglob("*"):
            if p.is_file() and is_image_file(p) and not p.name.startswith("."):
                out.add(p)
    return sorted(out)


def find_notebooks(project_dir: Path) -> list[Path]:
    """Find all .ipynb files (mirrors extract_methods.py logic)."""
    patterns = ["notebooks/*.ipynb", "*.ipynb", "src/*.ipynb", "analysis/*.ipynb"]
    found: set[Path] = set()
    for pat in patterns:
        for p in project_dir.glob(pat):
            if not p.name.startswith("."):
                found.add(p)
    return sorted(found)


# ---------------------------------------------------------------------------
# Caption candidate construction
# ---------------------------------------------------------------------------

def _truncate(text: str, n: int) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[:n - 3].rstrip() + "..."


def _last_paragraph(text: str) -> str:
    """Return the last non-empty paragraph of a markdown cell."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    return paragraphs[-1]


def build_figure_records(
    figure_files: list[Path],
    project_dir: Path,
    report_refs: list[ReportImageRef],
    notebook_savefigs: list[SavefigCall],
    notebook_md_by_code_index: dict[str, dict[int, str]],
) -> list[FigureRecord]:
    """For each figure file, attach captions and savefig origins."""
    # Index report refs by basename for fast lookup.
    report_by_basename: dict[str, list[ReportImageRef]] = {}
    for r in report_refs:
        bn = Path(r.url).name
        report_by_basename.setdefault(bn, []).append(r)

    # Index savefig calls by basename.
    savefig_by_basename: dict[str, list[SavefigCall]] = {}
    for s in notebook_savefigs:
        if s.saved_basename:
            savefig_by_basename.setdefault(s.saved_basename, []).append(s)

    out: list[FigureRecord] = []
    for fp in figure_files:
        rel = str(fp.relative_to(project_dir))
        fname = fp.name
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        rec = FigureRecord(
            path=rel,
            filename=fname,
            size_bytes=size,
            format=infer_image_format(fp),
        )

        # 1. REPORT.md captions (highest priority)
        for r in report_by_basename.get(fname, []):
            if r.alt_text:
                rec.captions.append(CaptionCandidate(
                    source="report",
                    text=_truncate(r.alt_text, 280),
                    context={"line": r.line, "section": r.section},
                ))

        # 2. Notebook savefig + preceding markdown context
        for s in savefig_by_basename.get(fname, []):
            rec.savefig_origins.append(SavefigOrigin(
                notebook=s.notebook,
                cell=s.cell,
                line=s.line,
                raw_call=s.raw_call,
            ))
            md_for_nb = notebook_md_by_code_index.get(s.notebook, {})
            preceding_md = md_for_nb.get(s.cell)
            if preceding_md:
                last_para = _last_paragraph(preceding_md)
                if last_para:
                    rec.captions.append(CaptionCandidate(
                        source="notebook_md",
                        text=_truncate(last_para, 280),
                        context={
                            "notebook": s.notebook,
                            "preceding_cell": s.cell,
                        },
                    ))

        # 3. Filename-derived (always available)
        rec.captions.append(CaptionCandidate(
            source="filename",
            text=filename_to_caption(fname),
            context={},
        ))

        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------

def extract_figures(project_dir: Path) -> FigureInventoryReport:
    """Run the full figure-extraction pipeline against a project directory."""
    figures = find_figure_files(project_dir)
    figures_dirs = [
        str(d.relative_to(project_dir)) for d in find_figures_dirs(project_dir)
    ]

    # REPORT.md image references
    report_refs: list[ReportImageRef] = []
    report_path = project_dir / "REPORT.md"
    if report_path.is_file():
        try:
            report_refs = parse_report_image_references(
                report_path.read_text(encoding="utf-8")
            )
        except OSError:
            pass

    # Notebook savefig calls + per-notebook markdown mappings
    all_savefigs: list[SavefigCall] = []
    md_by_notebook: dict[str, dict[int, str]] = {}
    for nb in find_notebooks(project_dir):
        savefigs, md_map = _walk_notebook_savefigs(nb, project_dir)
        all_savefigs.extend(savefigs)
        rel = str(nb.relative_to(project_dir))
        md_by_notebook[rel] = md_map

    figure_records = build_figure_records(
        figures, project_dir, report_refs, all_savefigs, md_by_notebook,
    )
    return FigureInventoryReport(
        project_dir=str(project_dir),
        figures_dirs=figures_dirs,
        figures=figure_records,
    )


# ---------------------------------------------------------------------------
# figures_inventory.md formatter
# ---------------------------------------------------------------------------

def format_figures_inventory_md(report: FigureInventoryReport) -> str:
    """Render the figure inventory as a human-readable markdown document.

    The Figure-selection prompt (Phase 3) consumes this to choose 4–8
    figures that support the chosen throughline. The format prioritizes
    the REPORT-derived caption (when available) and the notebook origin.
    """
    out: list[str] = []
    out.append("# Figures Inventory")
    out.append("")
    out.append(
        f"Auto-generated from `extract_figures.py` over `{report.project_dir}`. "
        f"Each figure below comes with caption candidates ranked by source: "
        f"REPORT-derived first (project's own authored caption), then "
        f"notebook-context (preceding markdown cell), then filename-derived "
        f"as a fallback. The Figure-selection prompt picks 4–8 figures from "
        f"this inventory based on the chosen throughline; figures NOT in "
        f"this inventory cannot be embedded (per SPEC §6 / D-004 — no "
        f"figure regeneration in v1)."
    )
    out.append("")

    s = report.to_dict()["summary"]
    out.append("## Summary")
    out.append("")
    out.append(f"- Total figures: **{s['total_figures']}**")
    out.append(f"- Total size: {s['total_size_bytes']:,} bytes")
    fmts = ", ".join(f"{k}: {v}" for k, v in sorted(s["by_format"].items()))
    out.append(f"- Formats: {fmts or '(none)'}")
    out.append(f"- With notebook-savefig origin: {s['with_notebook_origin']}")
    out.append(f"- Referenced in REPORT.md: {s['with_report_reference']}")
    out.append(f"- Filename-only (no notebook or REPORT context): {s['filename_only']}")
    out.append("")

    if report.figures_dirs:
        out.append(
            f"Scanned figure directories: "
            f"{', '.join('`' + d + '`' for d in report.figures_dirs)}"
        )
    else:
        out.append("**No figures directory found** at any of the standard paths.")
    out.append("")

    if not report.figures:
        out.append("_(no figure files found in this project)_")
        return "\n".join(out)

    out.append("## Figures")
    out.append("")
    for fig in report.figures:
        out.append(f"### `{fig.path}`")
        out.append("")
        size_kb = fig.size_bytes / 1024
        out.append(f"_{fig.format.upper()}, {size_kb:.1f} KB_")
        out.append("")
        # Caption candidates, in order of authority
        if fig.captions:
            out.append("**Caption candidates:**")
            out.append("")
            for c in fig.captions:
                src_label = {
                    "report": "REPORT.md",
                    "notebook_md": "notebook context",
                    "filename": "filename",
                }.get(c.source, c.source)
                ctx = ""
                if c.source == "report" and c.context.get("section"):
                    ctx = f" _(in {c.context['section']})_"
                elif c.source == "notebook_md" and c.context.get("notebook"):
                    ctx = (
                        f" _({c.context['notebook']}, preceding cell "
                        f"{c.context.get('preceding_cell')})_"
                    )
                out.append(f"- **{src_label}{ctx}**: {c.text}")
            out.append("")
        # Savefig origins
        if fig.savefig_origins:
            out.append("**Generated by:**")
            out.append("")
            for o in fig.savefig_origins:
                out.append(
                    f"- `{o.notebook}` cell {o.cell}, line {o.line}: "
                    f"`{o.raw_call}`"
                )
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="extract_figures.py",
        description=(
            "Inventory figures in a BERIL project and gather caption "
            "candidates from REPORT.md / notebook savefig context / "
            "filename. Writes JSON to stdout and (optionally) "
            "figures_inventory.md to --output-dir. Selection of which "
            "4–8 figures to embed is done downstream by a prompt."
        ),
    )
    p.add_argument(
        "project_dir",
        type=Path,
        help="Path to the BERIL project directory (projects/<id>/).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write figures_inventory.md (default: do not "
            "write a file; JSON-only)."
        ),
    )
    p.add_argument(
        "--no-md",
        action="store_true",
        help="Suppress figures_inventory.md write even if --output-dir set.",
    )
    args = p.parse_args(argv)

    if not args.project_dir.is_dir():
        print(
            f"Error: project_dir does not exist or is not a directory: "
            f"{args.project_dir}",
            file=sys.stderr,
        )
        return 1

    report = extract_figures(args.project_dir)
    payload = json.dumps(report.to_dict(), indent=2)
    sys.stdout.write(payload + "\n")

    if args.output_dir is not None and not args.no_md:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        md_path = args.output_dir / "figures_inventory.md"
        md_path.write_text(format_figures_inventory_md(report), encoding="utf-8")
        print(f"Wrote figures_inventory.md to {md_path}", file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# Mode-aware curation (presentation-maker addition; not in paper-writer)
# ---------------------------------------------------------------------------

# Per SPEC §5 + §8.1: each mode has a target figure count range.
# (min, max, default_target). The slide-compose prompt does the final
# throughline-aware selection; this is the bounded shortlist.
MODE_FIGURE_BUDGETS: dict[str, tuple[int, int, int]] = {
    "talk-30":     (4, 10, 7),
    "talk-15":     (3, 6, 4),
    "talk-45":     (6, 12, 9),
    "lightning-5": (2, 3, 2),
    "poster-h":    (2, 4, 3),
    "poster-v":    (2, 4, 3),
}


@dataclass
class CuratedFigureSelection:
    """A mode-bounded shortlist drawn from a FigureInventoryReport."""
    mode: str
    target_count: int
    selected: list[FigureRecord] = field(default_factory=list)
    inventory_size: int = 0
    budget_min: int = 0
    budget_max: int = 0

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "target_count": self.target_count,
            "selected": [f.to_dict() for f in self.selected],
            "inventory_size": self.inventory_size,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
        }


def _figure_score(record: FigureRecord) -> tuple[int, str]:
    """Score a figure for inclusion in the curated shortlist.
    Higher first-tuple-element = stronger candidate.

    Tier 3: figure has a REPORT.md reference (strongest authored caption).
    Tier 2: figure has a notebook savefig origin AND markdown context.
    Tier 1: figure has a notebook savefig origin only.
    Tier 0: figure has filename caption only.

    Tie-break by filename for deterministic ordering.
    """
    has_report = any(c.source == "report" for c in record.captions)
    has_notebook_md = any(c.source == "notebook_md" for c in record.captions)
    has_notebook_origin = bool(record.savefig_origins)
    if has_report:
        tier = 3
    elif has_notebook_md:
        tier = 2
    elif has_notebook_origin:
        tier = 1
    else:
        tier = 0
    return (tier, record.path)


# v0.8/D-093: substory-NB-id matching for per-substory floor.
# Mirrors the matching rule in check_figure_provenance.py — NB-id
# prefix on filenames (e.g. NB04b_* and NB04h_* both group under
# NB04). Strips the optional single-letter suffix for cross-analysis
# figure association.
_NB_ID_RE = re.compile(r"\b(NB\d+)[a-z]?", re.IGNORECASE)


def _figure_nb_ids(record: "FigureRecord") -> set[str]:
    """Return the set of NB-ids associated with a figure record.

    Looks at the figure's filename + every savefig-origin notebook
    + every notebook_md caption notebook. A figure may map to
    multiple NB-ids (e.g., re-saved by a different notebook), so
    the result is a set rather than a single id.
    """
    ids: set[str] = set()
    for token in [record.filename, record.path]:
        for m in _NB_ID_RE.finditer(token):
            ids.add(m.group(1).upper())
    for origin in record.savefig_origins:
        for m in _NB_ID_RE.finditer(origin.notebook):
            ids.add(m.group(1).upper())
    for cap in record.captions:
        nb = cap.context.get("notebook", "") if cap.context else ""
        for m in _NB_ID_RE.finditer(nb):
            ids.add(m.group(1).upper())
    return ids


def _substory_nb_ids(notebook_filenames: list[str]) -> set[str]:
    """Return NB-id set for a substory's analyses notebook filenames."""
    ids: set[str] = set()
    for fn in notebook_filenames:
        for m in _NB_ID_RE.finditer(fn):
            ids.add(m.group(1).upper())
    return ids


def curate_for_mode(
    inventory: FigureInventoryReport,
    mode: str,
    target_count: int | None = None,
    substory_analyses: dict[str, list[str]] | None = None,
) -> CuratedFigureSelection:
    """Pick a shortlist of figures from `inventory` for downstream
    slide composition.

    v0.8 Tier G.5 — Adam-clarified semantics (2026-06-01):
    Figures are pre-generated assets sitting on disk. Including
    one in the curated shortlist costs NOTHING; the only downstream
    cost is the slide_compose LLM deciding whether to USE one on a
    given slide (slide-budget territory). So the curator's job is
    NOT to enforce a figure-count budget on the talk deck.

    Two operating modes:

      WITH `substory_analyses` (the talk-deck path, --substories-path
      flag set): include EVERY inventory figure whose NB-ids match
      ANY substory's analyses notebooks, ordered by source-strength.
      MODE_FIGURE_BUDGETS is IGNORED for the selection size; the
      `budget_min`/`budget_max` fields still reflect the mode's
      paper-writer-parity numbers for reporting consistency.
      Rationale: the v0.8 Tier-G live read on ibd_phage_targeting
      draft_10 found S1+S2 had ZERO data_figure slides because the
      budget-bound 7-figure pick happened to land entirely on NB11-
      NB17 (S3 territory). With substory_analyses, the curator now
      surfaces ~25-30 figures across all three substories, giving
      slide_compose real choice per substory.

      WITHOUT `substory_analyses` (paper-writer parity, no --substories-path):
      keep the legacy MODE_FIGURE_BUDGETS behavior — pick top-N by
      source-strength up to the mode's `default` target_count
      (clamped to `[min, max]` if `target_count` is overridden).
      The per-substory floor never engages because there are no
      substories defined.

    Args:
      inventory: FigureInventoryReport from extract_figures().
      mode: One of MODE_FIGURE_BUDGETS keys (talk-30 / talk-15 / ...).
        Still required for the report's budget_min/budget_max
        metadata + the legacy fallback path.
      target_count: Legacy fallback only — override the mode's
        default target when substory_analyses is None. Ignored when
        substory_analyses is supplied (the substory-driven path
        ignores numeric budgets).
      substory_analyses: When provided, switches the curator to
        substory-driven mode (no figure-count budget; include all
        substory-relevant figures).

    Returns:
      CuratedFigureSelection. With substory_analyses, `target_count`
      reflects the actual size of the selection (could be 25-30+).

    Raises:
      ValueError: if mode is unknown.
    """
    if mode not in MODE_FIGURE_BUDGETS:
        raise ValueError(
            f"unknown mode '{mode}'; valid: {sorted(MODE_FIGURE_BUDGETS.keys())}"
        )
    lo, hi, default = MODE_FIGURE_BUDGETS[mode]

    # Sort by score (descending tier, then filename)
    ranked = sorted(inventory.figures,
                    key=lambda r: _figure_score(r), reverse=True)

    if substory_analyses:
        # v0.8 Tier G.5 substory-driven mode: include EVERY figure
        # whose NB-ids match ANY substory's analyses. No budget cap.
        # The selection is still source-strength-ordered.
        all_substory_nb_ids: set[str] = set()
        for analyses in substory_analyses.values():
            all_substory_nb_ids |= _substory_nb_ids(analyses)
        if all_substory_nb_ids:
            selected = [
                f for f in ranked
                if _figure_nb_ids(f) & all_substory_nb_ids
            ]
        else:
            # Defensive: substory_analyses passed but no parseable
            # NB-ids (e.g., empty analyses on every substory). Fall
            # back to the legacy budget pick rather than emit an
            # empty curated_figures.md.
            selected = list(ranked[:default])
    else:
        # Legacy fallback path (paper-writer parity, no
        # --substories-path): apply MODE_FIGURE_BUDGETS as a hard
        # ceiling on the top-N source-strength pick.
        if target_count is None:
            target = default
        else:
            target = max(lo, min(hi, target_count))
        selected = list(ranked[:target])

    return CuratedFigureSelection(
        mode=mode,
        target_count=len(selected),
        selected=selected,
        inventory_size=len(inventory.figures),
        budget_min=lo,
        budget_max=hi,
    )


def format_curated_figures_md(selection: CuratedFigureSelection) -> str:
    """Render the curated selection as a human-readable markdown document."""
    out: list[str] = []
    out.append(f"# Figures Curated for `{selection.mode}`")
    out.append("")
    # v0.8 Tier G.5: under substory-driven mode the selection is
    # NOT budget-bound — it's "every figure whose NB-ids match a
    # substory analysis." When the count is ≤ budget_max we keep
    # the legacy framing for backwards-compatibility readability;
    # when it exceeds budget_max, we surface the substory-driven
    # mode in the header so the slide_compose-author (LLM or human)
    # understands they're seeing a substory-scoped inventory, not a
    # budget-bound shortlist.
    if selection.target_count > selection.budget_max:
        out.append(
            f"Substory-scoped figure inventory: "
            f"{selection.target_count} figures from a "
            f"{selection.inventory_size}-figure inventory, ordered "
            f"by source-strength. v0.8 Tier G.5 — figures don't have "
            f"a budget on talk decks; every figure matching ANY "
            f"substory's analyses NB-ids is surfaced for slide_compose "
            f"to choose from. (Mode budget for paper-writer parity: "
            f"{selection.budget_min}-{selection.budget_max} figures; "
            f"NOT enforced here.) The slide-compose prompt makes the "
            f"per-slide selection; figures NOT picked stay in the "
            f"full inventory at `figures_inventory.md`."
        )
    else:
        out.append(
            f"Mode-bounded shortlist of {selection.target_count} figures "
            f"(budget {selection.budget_min}-{selection.budget_max}; "
            f"inventory had {selection.inventory_size}). The slide-compose "
            f"prompt makes the final throughline-aware selection from this "
            f"curated set; figures NOT in the shortlist are still in the full "
            f"inventory at `figures_inventory.md` if a re-curation is needed."
        )
    out.append("")
    if not selection.selected:
        out.append("_(no figures available)_")
        return "\n".join(out) + "\n"

    out.append("## Selected figures")
    out.append("")
    for i, fig in enumerate(selection.selected, start=1):
        tier, _ = _figure_score(fig)
        tier_label = {3: "REPORT-referenced", 2: "notebook-context",
                      1: "notebook-origin", 0: "filename-only"}[tier]
        out.append(f"### {i}. `{fig.path}` _(source-strength: {tier_label})_")
        out.append("")
        size_kb = fig.size_bytes / 1024
        out.append(f"_{fig.format.upper()}, {size_kb:.1f} KB_")
        out.append("")
        if fig.captions:
            best = fig.captions[0]
            out.append(f"**Best caption candidate:** {best.text}")
            out.append("")
        if fig.savefig_origins:
            origin = fig.savefig_origins[0]
            out.append(f"_Generated by `{origin.notebook}` cell {origin.cell}._")
            out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Curate CLI subcommand
# ---------------------------------------------------------------------------

def _parse_substory_analyses_simple(
    substories_path: Path,
) -> dict[str, list[str]]:
    """Parse 02_substories.md for {substory_id: [notebook_filename, ...]}.

    v0.8/D-093 — duplicate-free port of check_figure_provenance.py's
    parse_substory_analyses(). Kept inline rather than imported so
    curate_figures.py has no cross-tool import dependency (paper-
    writer parity surface). Same regex contract as the validator.

    v0.8 Tier G fallback: v3.3 substory_design produces lines that
    cite bare NB-id tokens (`NB02`, `NB04b`) rather than full
    `NBXX_name.ipynb` filenames. The full-filename regex misses these
    entirely. Fall back to bare NB-id tokens when no filename
    matched. Mirrors the same fallback in
    check_curator_figure_floor.py and check_figure_provenance.py so
    all three NB-id-matching parsers behave consistently.

    Returns empty dict if the file is missing or malformed (defensive
    — same posture as the rest of curate_figures).
    """
    if not substories_path.is_file():
        return {}
    try:
        text = substories_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    header_re = re.compile(r"^### (S\d+)\s*[—–\-]", re.MULTILINE)
    nb_full_re = re.compile(r"\b(NB\d+[a-z]?_\w+\.ipynb)", re.IGNORECASE)
    nb_bare_re = re.compile(r"\b(NB\d+[a-z]?)\b", re.IGNORECASE)
    headers = list(header_re.finditer(text))
    out: dict[str, list[str]] = {}
    for i, h in enumerate(headers):
        sid = h.group(1)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end]
        notebooks: list[str] = []
        for line in body.splitlines():
            full_matches = list(nb_full_re.finditer(line))
            if full_matches:
                for m in full_matches:
                    notebooks.append(m.group(1))
            else:
                # v0.8 Tier G: v3.3 bare-token fallback
                for m in nb_bare_re.finditer(line):
                    notebooks.append(m.group(1))
        out[sid] = notebooks
    return out


def _cmd_curate(argv: list[str] | None) -> int:
    """Top-level curate CLI: extract inventory + apply mode budget."""
    p = argparse.ArgumentParser(
        prog="curate_figures.py curate",
        description=(
            "Inventory figures and produce a mode-bounded shortlist. "
            "Writes both figures_inventory.md (full inventory) and "
            "curated_figures.md (mode shortlist; canonical name as of "
            "v0.3.2.1) to --output-dir."
        ),
    )
    p.add_argument("project_dir", type=Path)
    p.add_argument("--mode", required=True,
                   choices=sorted(MODE_FIGURE_BUDGETS.keys()))
    p.add_argument("--target-count", type=int, default=None,
                   help="Override the mode's default figure count "
                        "(clamped to [min, max] range).")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Directory to write figures_inventory.md + "
                        "curated_figures.md.")
    p.add_argument("--no-md", action="store_true",
                   help="Suppress markdown writes (JSON-only).")
    p.add_argument(
        "--substories-path", type=Path, default=None,
        help="Path to narrative/02_substories.md. v0.8/D-093: when "
             "supplied, curate_for_mode enforces a per-substory floor "
             "of ≥1 figure for every substory whose analyses cite a "
             "notebook with figures in the inventory. May exceed "
             "--target-count by up to N_substories (per-substory "
             "coverage wins over budget). When omitted, budget is "
             "the hard ceiling (paper-writer parity).")
    args = p.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"project_dir not found: {args.project_dir}", file=sys.stderr)
        return 2

    inventory = extract_figures(args.project_dir)
    substory_analyses = None
    if args.substories_path is not None:
        substory_analyses = _parse_substory_analyses_simple(
            args.substories_path)
        if substory_analyses:
            print(
                f"curate: per-substory floor enabled "
                f"(N_substories={len(substory_analyses)}; "
                f"source={args.substories_path})",
                file=sys.stderr,
            )
        else:
            print(
                f"curate: --substories-path supplied but "
                f"{args.substories_path} produced no parseable "
                f"substories; per-substory floor disabled",
                file=sys.stderr,
            )
    selection = curate_for_mode(
        inventory, args.mode, args.target_count,
        substory_analyses=substory_analyses)

    payload = {
        "inventory": inventory.to_dict(),
        "curated": selection.to_dict(),
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")

    if args.output_dir is not None and not args.no_md:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        inv_path = args.output_dir / "figures_inventory.md"
        inv_path.write_text(format_figures_inventory_md(inventory), encoding="utf-8")
        # v0.3.2.1: write the canonical name `curated_figures.md` directly.
        # The legacy `figures_curated.md` was written by v0.3.0–v0.3.2; the
        # orchestrator used to `cp` it to the canonical name. v0.3.1 removed
        # the cp; v0.3.2.1 writes the canonical name from this tool.
        cur_path = args.output_dir / "curated_figures.md"
        cur_path.write_text(format_curated_figures_md(selection), encoding="utf-8")
        print(f"wrote {inv_path}", file=sys.stderr)
        print(f"wrote {cur_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # If invoked with `curate` as the first arg, dispatch; otherwise the
    # legacy main() (inventory-only, paper-writer compatible).
    if len(sys.argv) > 1 and sys.argv[1] == "curate":
        sys.exit(_cmd_curate(sys.argv[2:]))
    sys.exit(main())
