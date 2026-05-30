#!/usr/bin/env python3
"""extract_cross_tenant.py — discover tenant/DB/sibling-project signal.

Per SPEC §3.3 and §7, every talk includes a required cross-tenant
integration slide. This module scans a project directory for the three
kinds of signal that populate that slide:

  1. **Tenant mentions** — known KBase tenant names appearing in prose
     (README.md, RESEARCH_PLAN.md, REPORT.md).
  2. **K-BERDL database queries** — `berdl_query(...)` calls in
     notebooks, plus URL references to *.kbase.us / *.berdl.lbl.gov.
  3. **Sibling-project references** — patterns like "see project X",
     "results from <id>", "from project <id>" in prose / references.md.

If all three counts are zero, `no_signal_fallback=True` and the slide
will render an honest "All data sourced from <tenant>; this project
did not integrate across tenants" line per SPEC §3.3 / §7.3.

Atlas-style cross-corpus citation graphs are out of v0.1 scope (D-010).
We may borrow algorithmic code from atlas's source if cross-tenant
quantification ever needs deeper signal than project-local artifacts
provide.

CLI:

    python3 extract_cross_tenant.py <project_dir> [--out signal.md]
                                                  [--json signal.json]

Library:

    from extract_cross_tenant import extract_cross_tenant
    report = extract_cross_tenant(Path("projects/<id>/"))
    print(report.tenant_list, report.kberdl_db_list, report.no_signal_fallback)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import nbformat
except ImportError:
    nbformat = None  # type: ignore


# ---------------------------------------------------------------------------
# Known signals — small, hand-curated lists. The orchestrator + slide-compose
# prompt clean up exact spelling; this module errs on the side of recall.
# ---------------------------------------------------------------------------

# KBase tenants per the 2026-and-beyond deck + MEMORY references.
# Match is case-insensitive on word boundaries.
KNOWN_TENANTS: tuple[str, ...] = (
    "enigma", "pmi", "phage_foundry", "phage-foundry",
    "pnnl_soil", "pnnl-soil",
    "ale", "usgs", "nih_protect", "nih-protect", "protect",
    "nmdc", "netl", "jgi", "emsl",
    "opal", "lambda", "famous", "beril", "bsat",
    "kbase", "kberdl", "k-berdl", "berdl", "bridge",
    "phage_foundry_brave", "amp2",
)

# Common K-BERDL database names per MEMORY reference_berdl_knowledge.
# Used both as bare-token matches in prose AND as table-namespace
# matches in `berdl_query("SELECT ... FROM <db>.<table>")` SQL parsing.
KNOWN_KBERDL_DBS: tuple[str, ...] = (
    "fitnessbrowser", "paperblast", "rast", "isolates",
    "pubmed", "kegg", "interpro", "uniprot", "ena",
    "go", "ec", "tcdb", "pfam", "cazy",
    "biolog", "amplicon", "metagenomics", "metabolomics",
    "rb_tnseq", "rb-tnseq",
)


# v0.7/D-089 Tier E.0: external reference databases used for
# annotation but NOT hosted within K-BERDL. These appear in the
# methods/data-sources slide content separately from primary
# K-BERDL DBs because they're external dependencies (the audience
# needs to know the project depends on annotations from outside
# the BERDL platform).
#
# Adam Tier-F (D-084 finding 5) flagged the ibd v0.6 slide-27 as
# missing exactly these — the slide said "8 K-BERDL DBs, 31
# notebooks" but the substory analyses cited MIBiG (BGC catalog),
# MetaCyc (pathway ontology), GTDB (taxonomy), BRENDA (enzyme),
# INPHARED (phage genomes) as annotation sources. v0.7 lifts them
# to first-class signal so the composer can enumerate them.
KNOWN_REFERENCE_DATABASES: tuple[str, ...] = (
    "MIBiG", "MetaCyc", "GTDB", "BRENDA", "INPHARED",
    "ModelSEEDDatabase", "ModelSEED",
    "RefSeq", "GenBank",  # NCBI databases used as annotation refs
    "AntiSMASH", "antiSMASH",
    "HUMAnN3", "HUMANn3",  # HMP analysis tool referenced as a DB
    "PATRIC", "BV-BRC",
    "JGI-IMG", "IMG",  # JGI Integrated Microbial Genomes
)


# v0.7/D-089 Tier E.0: external cohorts (named patient/sample
# collections from outside the project's primary data source).
# Adam Tier-F flagged ibd v0.6 as missing the HMP2 cohort
# acknowledgment despite HMP2 being cited 15+ times across
# substories (external validation, metabolomics, viromics,
# serology). The composer needs the cohort list explicitly so
# it can attribute external data sources.
KNOWN_EXTERNAL_COHORTS: tuple[str, ...] = (
    "HMP2", "HMP",
    "iHMP",  # Integrative HMP
    "FRANZOSA_2019", "Franzosa_2019",  # canonical IBD cohort
    "PRISM", "RISK", "PROTECT",
    "MetaHIT",  # European metagenomics cohort
    "AGP", "American_Gut",  # American Gut Project
    "ELDERMET",
    "MetaCardis",
    "TwinsUK",
    "NMDC",  # National Microbiome Data Collaborative
    "NEON",  # National Ecological Observatory
)


# Sibling-project reference patterns. The matched group is the project_id.
# Project IDs are lowercase identifiers with underscores (BERIL convention).
SIBLING_PROJECT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(?:see|from|results? from|leveraging|building on|"
               r"as in|per|based on)\s+(?:the\s+)?project\s+"
               r"[`'\"]?([a-z][a-z0-9_]+)[`'\"]?", re.IGNORECASE),
    re.compile(r"`projects/([a-z][a-z0-9_]+)/?`"),
    re.compile(r"\bprojects/([a-z][a-z0-9_]+)/", re.IGNORECASE),
)

# berdl_query SQL: extract the FROM clause's namespace.
# Permissive: matches `berdl_query(\"SELECT ... FROM <ns>.<table>\")` and the
# bare `FROM <ns>.<table>` substring even outside berdl_query (other SQL
# helpers may exist).
BERDL_QUERY_RE = re.compile(
    r"berdl_query\s*\(\s*[fr]?[\"']{1,3}([\s\S]*?)[\"']{1,3}\s*[,\)]",
    re.IGNORECASE,
)
SQL_FROM_NS_RE = re.compile(
    r"\bFROM\s+`?([a-z][a-z0-9_]+)`?\s*\.\s*`?([a-z][a-z0-9_]+)`?",
    re.IGNORECASE,
)

# K-BERDL / KBase URL patterns. Use [^\s)"]* (not +) before the host so
# bare https://kbase.us/... matches (host is right after ://, no preceding
# subdomain required).
KBASE_URL_RE = re.compile(
    r"https?://[^\s)\"]*(?:kbase\.us|berdl\.lbl\.gov|lbl\.gov)[^\s)\"]*",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SignalEvidence:
    """One specific piece of evidence (file + line + matched text)."""
    source_file: str
    line: Optional[int]
    matched_text: str
    kind: str  # 'tenant' | 'kberdl_db' | 'sibling_project' | 'kbase_url'


@dataclass
class CrossTenantReport:
    """Aggregated cross-tenant signal for a project.

    Used to fill the cross_tenant_integration slide content.

    v0.7/D-089 Tier E.0: extended with three new fields per the
    Adam-Tier-F D-084 finding 5 fix — the ibd v0.6 slide-27 was
    missing external reference databases (MIBiG/MetaCyc/GTDB/
    BRENDA), external cohorts (HMP2), and correct notebook count.
    The new fields are first-class signal the composer
    (cross_tenant.v1 Tier E.1) reads to enumerate all four tiers
    in title + speaker_notes verbatim (no free-text invention).
    """
    project_id: str
    tenant_list: list[str] = field(default_factory=list)
    kberdl_db_list: list[str] = field(default_factory=list)
    sibling_project_refs: list[dict[str, str]] = field(default_factory=list)
    kbase_urls: list[str] = field(default_factory=list)
    no_signal_fallback: bool = False
    raw_evidence: list[SignalEvidence] = field(default_factory=list)
    files_scanned: list[str] = field(default_factory=list)
    notebooks_scanned: list[str] = field(default_factory=list)
    # v0.7/D-089 Tier E.0 additions
    reference_databases: list[str] = field(default_factory=list)
    external_cohorts: list[str] = field(default_factory=list)
    notebook_count: int = 0

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "tenant_list": self.tenant_list,
            "kberdl_db_list": self.kberdl_db_list,
            "sibling_project_refs": self.sibling_project_refs,
            "kbase_urls": self.kbase_urls,
            "no_signal_fallback": self.no_signal_fallback,
            "raw_evidence": [dataclasses.asdict(e) for e in self.raw_evidence],
            "files_scanned": self.files_scanned,
            "notebooks_scanned": self.notebooks_scanned,
            # v0.7/D-089 Tier E.0
            "reference_databases": self.reference_databases,
            "external_cohorts": self.external_cohorts,
            "notebook_count": self.notebook_count,
        }

    def to_slide_content(self, title: str | None = None) -> dict:
        """Convert to the cross_tenant_integration content schema
        consumable by assemble_pptx (per slide_spec.py)."""
        if title is None:
            if self.no_signal_fallback:
                title = "All data sourced from a single tenant"
            elif self.tenant_list:
                title = (f"This work integrates {len(self.kberdl_db_list)} "
                         f"K-BERDL database(s) across "
                         f"{len(self.tenant_list)} tenant(s)")
            else:
                title = "Data integration summary"
        return {
            "title": title,
            "tenant_list": self.tenant_list,
            "kberdl_db_list": self.kberdl_db_list,
            "sibling_project_refs": self.sibling_project_refs,
            "no_signal_fallback": self.no_signal_fallback,
        }


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _scan_text_for_terms(
    text: str, terms: tuple[str, ...], kind: str, source_file: str,
) -> list[SignalEvidence]:
    """Find case-insensitive whole-word matches of each term in text.
    Returns a SignalEvidence per match, with 1-based line numbers."""
    evidence: list[SignalEvidence] = []
    if not text:
        return evidence
    # Build one regex with all terms, escaped, joined by | with word boundaries.
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b",
        re.IGNORECASE,
    )
    for line_no, line in enumerate(text.split("\n"), start=1):
        for m in pattern.finditer(line):
            evidence.append(SignalEvidence(
                source_file=source_file,
                line=line_no,
                matched_text=m.group(0),
                kind=kind,
            ))
    return evidence


def _canonical_name(matched_text: str,
                     canonical_list: tuple[str, ...]) -> str:
    """Map a matched term back to its canonical form from the
    known-list. The scan is case-insensitive but the canonical form
    (MIBiG, MetaCyc, HMP2 — mixed case + numbers) carries meaning
    the audience reads literally on the slide; preserve it.

    Falls back to the original matched_text if no canonical match
    (shouldn't happen because _scan_text_for_terms only emits
    evidence for terms in the canonical list, but defensive)."""
    norm = matched_text.strip().lower()
    for canon in canonical_list:
        if canon.lower() == norm:
            return canon
    return matched_text.strip()


def _scan_text_for_sibling_projects(
    text: str, source_file: str,
) -> list[SignalEvidence]:
    """Find sibling-project references via SIBLING_PROJECT_PATTERNS."""
    evidence: list[SignalEvidence] = []
    if not text:
        return evidence
    for line_no, line in enumerate(text.split("\n"), start=1):
        for pat in SIBLING_PROJECT_PATTERNS:
            for m in pat.finditer(line):
                project_id = m.group(1)
                evidence.append(SignalEvidence(
                    source_file=source_file,
                    line=line_no,
                    matched_text=project_id,
                    kind="sibling_project",
                ))
    return evidence


def _scan_text_for_kbase_urls(
    text: str, source_file: str,
) -> list[SignalEvidence]:
    evidence: list[SignalEvidence] = []
    if not text:
        return evidence
    for line_no, line in enumerate(text.split("\n"), start=1):
        for m in KBASE_URL_RE.finditer(line):
            evidence.append(SignalEvidence(
                source_file=source_file,
                line=line_no,
                matched_text=m.group(0),
                kind="kbase_url",
            ))
    return evidence


def _scan_notebook_for_signals(
    notebook_path: Path,
) -> list[SignalEvidence]:
    """Walk a Jupyter notebook's code cells. Find:
    - berdl_query() / SQL FROM <db>.<table> patterns → kberdl_db evidence
    - bare references to known DB names → kberdl_db evidence
    - KBase URLs → kbase_url evidence
    - tenant mentions in markdown cells → tenant evidence
    """
    evidence: list[SignalEvidence] = []
    if nbformat is None:
        return evidence  # gracefully degrade if nbformat missing
    try:
        nb = nbformat.read(notebook_path, as_version=4)
    except Exception:
        # Fall back to raw JSON read for slightly-malformed notebooks
        # (e.g., missing per-cell metadata that nbformat strict-validates).
        # We only need cell.cell_type + cell.source.
        try:
            import json as _json
            raw = _json.loads(notebook_path.read_text(encoding="utf-8"))
            class _Cell:  # tiny duck-typed cell
                def __init__(self, d):
                    self.cell_type = d.get("cell_type", "")
                    src = d.get("source", "")
                    self.source = "".join(src) if isinstance(src, list) else src
                def get(self, k, default=None):
                    return getattr(self, k, default)
            class _Nb:
                pass
            nb = _Nb()
            nb.cells = [_Cell(c) for c in raw.get("cells", []) if isinstance(c, dict)]
        except Exception:
            return evidence

    label = str(notebook_path)
    for cell in nb.cells:
        source = cell.get("source", "")
        if not source:
            continue
        if cell.get("cell_type") == "code":
            # berdl_query parsing
            for m in BERDL_QUERY_RE.finditer(source):
                sql = m.group(1)
                for sm in SQL_FROM_NS_RE.finditer(sql):
                    db = sm.group(1).lower()
                    evidence.append(SignalEvidence(
                        source_file=label, line=None,
                        matched_text=db, kind="kberdl_db",
                    ))
            # bare SQL FROM <ns>.<table> outside berdl_query
            for sm in SQL_FROM_NS_RE.finditer(source):
                db = sm.group(1).lower()
                if db in KNOWN_KBERDL_DBS:
                    evidence.append(SignalEvidence(
                        source_file=label, line=None,
                        matched_text=db, kind="kberdl_db",
                    ))
            # bare known-DB tokens
            for ev in _scan_text_for_terms(
                source, KNOWN_KBERDL_DBS, "kberdl_db", label,
            ):
                evidence.append(ev)
            # URLs
            for ev in _scan_text_for_kbase_urls(source, label):
                evidence.append(ev)
        elif cell.get("cell_type") == "markdown":
            # Tenant + sibling-project mentions in markdown narration
            evidence.extend(_scan_text_for_terms(
                source, KNOWN_TENANTS, "tenant", label,
            ))
            evidence.extend(_scan_text_for_sibling_projects(source, label))
    return evidence


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------

PROJECT_DOC_FILES = ("README.md", "RESEARCH_PLAN.md", "REPORT.md", "references.md",
                     "REVIEW.md")


def extract_cross_tenant(project_dir: Path) -> CrossTenantReport:
    """Walk a BERIL project directory and aggregate cross-tenant signal.

    Args:
      project_dir: Path to projects/<id>/.

    Returns:
      CrossTenantReport with deduplicated tenant_list, kberdl_db_list,
      sibling_project_refs, plus raw_evidence for audit.
    """
    project_dir = Path(project_dir).resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"project_dir not found: {project_dir}")

    project_id = project_dir.name
    report = CrossTenantReport(project_id=project_id)

    # Doc files
    for doc in PROJECT_DOC_FILES:
        p = project_dir / doc
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        report.files_scanned.append(str(p.relative_to(project_dir)))
        report.raw_evidence.extend(
            _scan_text_for_terms(text, KNOWN_TENANTS, "tenant", str(p)))
        report.raw_evidence.extend(
            _scan_text_for_terms(text, KNOWN_KBERDL_DBS, "kberdl_db", str(p)))
        report.raw_evidence.extend(
            _scan_text_for_sibling_projects(text, str(p)))
        report.raw_evidence.extend(_scan_text_for_kbase_urls(text, str(p)))
        # v0.7/D-089 Tier E.0: external reference DBs + cohorts
        report.raw_evidence.extend(
            _scan_text_for_terms(text, KNOWN_REFERENCE_DATABASES,
                                  "reference_db", str(p)))
        report.raw_evidence.extend(
            _scan_text_for_terms(text, KNOWN_EXTERNAL_COHORTS,
                                  "external_cohort", str(p)))

    # Notebooks (recursive)
    notebooks_dir = project_dir / "notebooks"
    if notebooks_dir.is_dir():
        for nb_path in sorted(notebooks_dir.rglob("*.ipynb")):
            # skip checkpoint files
            if ".ipynb_checkpoints" in nb_path.parts:
                continue
            report.notebooks_scanned.append(
                str(nb_path.relative_to(project_dir)))
            report.raw_evidence.extend(_scan_notebook_for_signals(nb_path))

    # Aggregate distinct values
    tenant_counter: Counter[str] = Counter()
    kberdl_counter: Counter[str] = Counter()
    sibling_counter: Counter[str] = Counter()
    urls: list[str] = []
    # v0.7/D-089 Tier E.0: separate counters for reference DBs +
    # external cohorts. These are tracked verbatim (preserve case)
    # because the canonical names (MIBiG, MetaCyc, HMP2, etc.) carry
    # meaning the audience reads literally on the slide.
    reference_db_counter: Counter[str] = Counter()
    external_cohort_counter: Counter[str] = Counter()

    for ev in report.raw_evidence:
        norm = ev.matched_text.strip().lower().replace("-", "_")
        if ev.kind == "tenant" and norm not in ("kbase", "kberdl", "k_berdl",
                                                "berdl", "bridge"):
            # Filter the platform-as-tenant tokens — KBase / BERDL / BRIDGE are
            # the platform names, not tenants. Keep them in raw_evidence but
            # don't promote to tenant_list.
            tenant_counter[norm] += 1
        elif ev.kind == "kberdl_db":
            kberdl_counter[norm] += 1
        elif ev.kind == "sibling_project":
            # Don't count the project itself as its own sibling
            if norm != project_id.lower():
                sibling_counter[norm] += 1
        elif ev.kind == "kbase_url":
            if ev.matched_text not in urls:
                urls.append(ev.matched_text)
        elif ev.kind == "reference_db":
            # Preserve canonical case (MIBiG, MetaCyc, etc.) — the
            # match-text is whatever the doc had; the canonical form
            # is in KNOWN_REFERENCE_DATABASES. Map back to canonical
            # by case-insensitive lookup.
            canonical = _canonical_name(ev.matched_text,
                                         KNOWN_REFERENCE_DATABASES)
            reference_db_counter[canonical] += 1
        elif ev.kind == "external_cohort":
            canonical = _canonical_name(ev.matched_text,
                                         KNOWN_EXTERNAL_COHORTS)
            external_cohort_counter[canonical] += 1

    # Most-mentioned first; drop singletons that are also in URL list
    report.tenant_list = sorted(tenant_counter.keys())
    report.kberdl_db_list = sorted(kberdl_counter.keys())
    # Sibling projects: convert to slide-content shape
    # `what_was_leveraged` is best-effort — we don't have semantic context
    # at this layer. The slide-compose prompt fills that field with
    # narrative. Here we record the project_id and a neutral default.
    report.sibling_project_refs = [
        {"project_id": pid,
         "what_was_leveraged": f"({sibling_counter[pid]} reference(s) in project artifacts)"}
        for pid in sorted(sibling_counter.keys())
    ]
    report.kbase_urls = urls
    # v0.7/D-089 Tier E.0: populate the new structured fields
    report.reference_databases = sorted(reference_db_counter.keys())
    report.external_cohorts = sorted(external_cohort_counter.keys())
    report.notebook_count = len(report.notebooks_scanned)
    report.no_signal_fallback = (
        not report.tenant_list
        and not report.kberdl_db_list
        and not report.sibling_project_refs
    )
    return report


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def format_signal_md(report: CrossTenantReport) -> str:
    out = []
    out.append("# Cross-tenant signal")
    out.append("")
    out.append(f"**Project:** `{report.project_id}`")
    out.append(f"**Files scanned:** {len(report.files_scanned)} doc files, "
               f"{len(report.notebooks_scanned)} notebooks")
    out.append("")
    if report.no_signal_fallback:
        out.append("## No cross-tenant signal detected")
        out.append("")
        out.append("This project did not integrate across tenants. The "
                   "cross-tenant slide will render the honest fallback "
                   "(SPEC §7.3).")
        out.append("")
        return "\n".join(out) + "\n"

    out.append("## Quantitative summary")
    out.append("")
    out.append(f"- **Tenants mentioned:** {len(report.tenant_list)}")
    out.append(f"- **K-BERDL databases queried:** {len(report.kberdl_db_list)}")
    out.append(f"- **Sibling-project references:** {len(report.sibling_project_refs)}")
    out.append(f"- **KBase URLs found:** {len(report.kbase_urls)}")
    out.append("")

    if report.tenant_list:
        out.append("## Tenants")
        out.append("")
        for t in report.tenant_list:
            out.append(f"- {t}")
        out.append("")

    if report.kberdl_db_list:
        out.append("## K-BERDL databases")
        out.append("")
        for d in report.kberdl_db_list:
            out.append(f"- {d}")
        out.append("")

    if report.sibling_project_refs:
        out.append("## Sibling-project references")
        out.append("")
        for ref in report.sibling_project_refs:
            out.append(f"- `{ref['project_id']}` — {ref['what_was_leveraged']}")
        out.append("")

    if report.kbase_urls:
        out.append("## KBase / K-BERDL URLs found")
        out.append("")
        for u in report.kbase_urls:
            out.append(f"- {u}")
        out.append("")

    out.append("## Raw evidence")
    out.append("")
    out.append("| Kind | File | Line | Matched |")
    out.append("|---|---|---:|---|")
    for ev in report.raw_evidence:
        line = ev.line if ev.line is not None else ""
        # Truncate matched text for table readability
        matched = ev.matched_text.replace("|", "\\|")[:80]
        rel_file = ev.source_file
        if isinstance(rel_file, str) and len(rel_file) > 60:
            rel_file = "..." + rel_file[-57:]
        out.append(f"| {ev.kind} | `{rel_file}` | {line} | {matched} |")
    out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extract_cross_tenant",
        description="Extract cross-tenant signal from a BERIL project directory.",
    )
    parser.add_argument("project_dir",
                        help="Path to projects/<id>/")
    parser.add_argument("--out",
                        help="Output markdown path (default: cross_tenant_signal.md "
                             "in project_dir; '-' for stdout)")
    parser.add_argument("--json",
                        help="Also emit a JSON sidecar at this path")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress summary line on stderr")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).resolve()
    try:
        report = extract_cross_tenant(project_dir)
    except FileNotFoundError as e:
        print(f"extract_cross_tenant: {e}", file=sys.stderr)
        return 2

    md = format_signal_md(report)
    if args.out == "-":
        sys.stdout.write(md)
    else:
        out_path = (Path(args.out).resolve() if args.out
                    else project_dir / "cross_tenant_signal.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        if not args.quiet:
            print(f"wrote {out_path}", file=sys.stderr)

    if args.json:
        json_path = Path(args.json).resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report.to_dict(), indent=2),
                             encoding="utf-8")
        if not args.quiet:
            print(f"wrote {json_path}", file=sys.stderr)

    if not args.quiet:
        if report.no_signal_fallback:
            print("[extract_cross_tenant] no signal — fallback slide will be emitted",
                  file=sys.stderr)
        else:
            print(f"[extract_cross_tenant] tenants={len(report.tenant_list)}, "
                  f"kberdl_dbs={len(report.kberdl_db_list)}, "
                  f"siblings={len(report.sibling_project_refs)}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
