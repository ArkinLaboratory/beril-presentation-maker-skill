#!/usr/bin/env python3
"""check_cross_tenant_grounding.py — v0.7 Tier E.2 / D-089 validator.

Per D-089 (the narrow fix to the v0.6 Tier-F slide-27 bug
identified at D-084 finding 5): the cross_tenant_integration
slide's title + speaker_notes must be GROUNDED in the structured
signal that `extract_cross_tenant.py` emitted, not free-text
composed.

This validator compares the composed slide against the signal:

- **Hallucination**: a database/cohort named in the slide's title
  or speaker_notes that is NOT in the signal. Indicates composer
  fabrication.
- **Omission**: an entry in the signal's `kberdl_db_list` /
  `reference_databases` / `external_cohorts` that is NOT named in
  the slide's title or speaker_notes. Indicates the composer
  dropped a load-bearing source from the audience's awareness.

Both finding kinds emit at P1 soft-warning per D-080 lineage
(advisory; never gates the cascade). The composer + Adam at
Tier-F own the final synthesis decision; this validator is the
audit backstop.

Counted entities (D-089 scope):

- K-BERDL databases (`signal.kberdl_db_list`)
- External reference databases (`signal.reference_databases`,
  v0.7/D-089 new field)
- External cohorts (`signal.external_cohorts`, v0.7/D-089 new field)

NOT counted (out of scope for this validator):

- `sibling_project_refs` — already audited at the slide-content
  level via the cross_tenant_integration validator
  (`tools/slide_spec.py::_check_cross_tenant_integration`).
- `kbase_urls` — informational only; no audience-facing
  naming on the slide.

Output:

- Standalone CLI: writes `audit/cross_tenant_grounding.json`
  (`cross-tenant-grounding.v1`) by default.
- Cascade integration: `review_cascade.py::_read_cross_tenant_grounding`
  reads the audit JSON (read-if-present pattern, parallel to
  `_read_figure_provenance`) and lifts each finding into cascade
  Tier-1 as `cross_tenant_grounding:<finding-kind>` at P1.

Findings (kinds):

- `database_hallucination` — slide names a K-BERDL DB or
  reference DB that's NOT in the signal.
- `cohort_hallucination` — slide names an external cohort
  that's NOT in the signal.
- `database_omission` — signal entry (K-BERDL DB or reference
  DB) is NOT named anywhere in slide title + speaker_notes.
- `cohort_omission` — signal entry (cohort) is NOT named
  anywhere in slide title + speaker_notes.
- `notebook_count_mismatch` — title or speaker_notes claims a
  notebook count that doesn't match signal.notebook_count.

Test coverage: `tests/unit/test_check_cross_tenant_grounding.py`.

Refs: D-089 (v0.7 narrow fix to the slide-27 bug); D-084 finding
5 (the Tier-F veto that opened Tier E); D-080 (the figure-
provenance precedent this validator mirrors); D-072 (the
register-discipline validator-precedent pattern); D-091 (the C2
audit confirming this is the localized fix scope);
`extract_cross_tenant.py` (v0.7 signal extractor populating
the reference_databases + external_cohorts + notebook_count
fields this validator audits against).
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


SCHEMA_VERSION = "cross-tenant-grounding.v1"


# ---------------------------------------------------------------------------
# Data shapes (mirror check_figure_provenance.py for cascade-reader
# consistency)
# ---------------------------------------------------------------------------

@dataclass
class GroundingFinding:
    """One cross-tenant-grounding finding."""
    kind: str            # see module docstring "Findings (kinds)"
    severity: str        # always "soft-warning" per D-089 (advisory)
    slide_id: Optional[int]
    message: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class CrossTenantGroundingReport:
    schema_version: str
    slide_spec_path: str
    signal_path: str
    n_kberdl_dbs_in_signal: int
    n_reference_dbs_in_signal: int
    n_external_cohorts_in_signal: int
    notebook_count_in_signal: int
    findings: list[GroundingFinding]
    cross_tenant_slide_present: bool

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Slide-spec inspection
# ---------------------------------------------------------------------------

def find_cross_tenant_slide(spec: dict) -> Optional[dict]:
    """Return the cross_tenant_integration slide from spec, or None
    if absent. Per SPEC §7 every talk should have one; absence is
    a separate concern from grounding (slide_spec.py's
    validate_slide_spec checks presence)."""
    for slide in spec.get("slides", []):
        if isinstance(slide, dict) and slide.get("layout") == \
                "cross_tenant_integration":
            return slide
    return None


def extract_slide_text(slide: dict) -> str:
    """Concatenate the title + speaker_notes into a single search
    blob. This is the surface the grounding check searches against.
    Other content fields (tenant_list, kberdl_db_list, etc.) are
    structured; only the free-text fields can hallucinate."""
    parts: list[str] = []
    content = slide.get("content", {})
    if isinstance(content, dict):
        title = content.get("title", "")
        if isinstance(title, str):
            parts.append(title)
    notes = slide.get("speaker_notes", "")
    if isinstance(notes, str):
        parts.append(notes)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Term-matching helpers
# ---------------------------------------------------------------------------

def _term_in_text(term: str, text: str) -> bool:
    """Case-insensitive whole-word match for `term` in `text`.

    Uses word boundaries so 'GO' doesn't match 'going', and so
    'HMP' doesn't false-match 'HMP2' (each cohort is searched
    independently)."""
    if not term:
        return False
    pattern = r"\b" + re.escape(term) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


# Common false-positive tokens for the "named in slide" check.
# Some K-BERDL DB names (`ec`, `go`) are 2-letter abbreviations
# that false-match common English words ("Etc.", "Go forward").
# Require these to appear with their parent context ("EC numbers",
# "GO terms", "EC database", "GO annotations") to count as a
# slide-side mention. We do that by widening the search pattern.
_AMBIGUOUS_KBERDL_TERMS = {"ec", "go"}


def _kberdl_db_in_text(db: str, text: str) -> bool:
    """Whole-word match for K-BERDL DB names, with extra precision
    on 2-letter abbreviations that false-match English words.

    For ambiguous short names (ec, go), require an adjacent
    keyword (EC numbers, GO terms, EC database, GO annotations,
    etc.) so a casual "go forward" in speaker notes doesn't count
    as a GO database mention."""
    if db.lower() not in _AMBIGUOUS_KBERDL_TERMS:
        return _term_in_text(db, text)
    # Ambiguous; look for the term followed by a discriminator
    # within ~30 chars (e.g. "GO annotations", "EC numbers",
    # "EC database", "GO terms").
    discriminators = (
        r"number", r"term", r"annot", r"data", r"databas", r"catalog",
        r"ontolog", r"identifi", r"classif", r"hierar",
    )
    disc_alt = "|".join(discriminators)
    pattern = (r"\b" + re.escape(db)
               + r"\b\s+\w*(?:" + disc_alt + r")")
    return bool(re.search(pattern, text, re.IGNORECASE))


def _names_mentioned_in_text(names: list[str],
                              text: str,
                              kind: str) -> tuple[list[str], list[str]]:
    """Return (mentioned, missing) — names found vs not found in text."""
    mentioned: list[str] = []
    missing: list[str] = []
    for n in names:
        # Different match precision per kind
        if kind == "kberdl_db":
            hit = _kberdl_db_in_text(n, text)
        else:
            hit = _term_in_text(n, text)
        if hit:
            mentioned.append(n)
        else:
            missing.append(n)
    return mentioned, missing


# ---------------------------------------------------------------------------
# Hallucination detection (text mentions of names not in signal)
# ---------------------------------------------------------------------------

# Vocabularies the validator imports from extract_cross_tenant so the
# two stay in sync. The slide can only "hallucinate" names that ARE
# known DB/cohort identifiers (otherwise we'd flag any noun as a
# potential hallucination); we restrict the hallucination search to
# the canonical lists.
def _load_canonical_lists() -> tuple[tuple[str, ...], tuple[str, ...],
                                       tuple[str, ...]]:
    """Import the canonical lists from extract_cross_tenant. Defensive:
    if the import fails, return empty tuples (hallucination check
    silently no-ops; omission check still runs)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import extract_cross_tenant as ect  # type: ignore
        return (ect.KNOWN_KBERDL_DBS,
                ect.KNOWN_REFERENCE_DATABASES,
                ect.KNOWN_EXTERNAL_COHORTS)
    except Exception:
        return ((), (), ())


# ---------------------------------------------------------------------------
# Notebook-count parsing
# ---------------------------------------------------------------------------

_NOTEBOOK_COUNT_RE = re.compile(
    r"(\d+)\s*(?:notebook|notebooks|\.ipynb|jupyter\s+notebooks?)",
    re.IGNORECASE,
)


def _extract_notebook_count_claims(text: str) -> list[int]:
    """Find all `N notebooks` / `N .ipynb` claims in text. Returns
    the list of integers; multiple claims is possible (title +
    notes). The grounding check compares each against signal.notebook_count."""
    return [int(m.group(1)) for m in _NOTEBOOK_COUNT_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_cross_tenant_grounding(
    slide_spec_path: Path,
    signal_path: Path,
) -> CrossTenantGroundingReport:
    """Run the grounding check.

    Per D-089:
    - For each entry in signal's kberdl_db_list + reference_databases:
      check if named in slide's title + speaker_notes; emit
      omission finding if absent.
    - For each entry in signal's external_cohorts: same check;
      emit cohort_omission if absent.
    - For each canonical K-BERDL DB / reference DB / cohort name
      NAMED in slide text but NOT in the signal: emit
      hallucination finding.
    - If slide text claims `N notebooks` and N != signal.notebook_count:
      emit notebook_count_mismatch.

    All findings P1 soft-warning per D-089.
    """
    # Load slide_spec
    try:
        spec = json.loads(slide_spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        spec = {"slides": []}

    # Load signal (the extract_cross_tenant JSON output)
    try:
        signal = json.loads(signal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        signal = {}

    signal_kberdl_dbs = signal.get("kberdl_db_list") or []
    signal_reference_dbs = signal.get("reference_databases") or []
    signal_external_cohorts = signal.get("external_cohorts") or []
    signal_notebook_count = signal.get("notebook_count", 0)

    findings: list[GroundingFinding] = []

    slide = find_cross_tenant_slide(spec)
    if slide is None:
        # Slide absence is a different concern (slide_spec.py's
        # validate_slide_spec checks SPEC §7 presence). We emit a
        # neutral report so the cascade gets the same shape.
        return CrossTenantGroundingReport(
            schema_version=SCHEMA_VERSION,
            slide_spec_path=str(slide_spec_path),
            signal_path=str(signal_path),
            n_kberdl_dbs_in_signal=len(signal_kberdl_dbs),
            n_reference_dbs_in_signal=len(signal_reference_dbs),
            n_external_cohorts_in_signal=len(signal_external_cohorts),
            notebook_count_in_signal=signal_notebook_count,
            findings=[],
            cross_tenant_slide_present=False,
        )

    slide_id = slide.get("id")
    text = extract_slide_text(slide)

    # --- Omission checks ---
    # K-BERDL DBs
    _, missing_kberdl = _names_mentioned_in_text(
        signal_kberdl_dbs, text, "kberdl_db")
    for db in missing_kberdl:
        findings.append(GroundingFinding(
            kind="database_omission",
            severity="soft-warning",
            slide_id=slide_id,
            message=(
                f"signal lists K-BERDL DB {db!r} but it is NOT named "
                f"in the cross_tenant_integration slide's title or "
                f"speaker_notes — per D-089, every signal-listed "
                f"source should be enumerated for audience awareness."
            ),
            evidence={"db": db, "kind": "kberdl_db",
                      "signal_kberdl_dbs": list(signal_kberdl_dbs)},
        ))

    # Reference DBs
    _, missing_reference = _names_mentioned_in_text(
        signal_reference_dbs, text, "reference_db")
    for db in missing_reference:
        findings.append(GroundingFinding(
            kind="database_omission",
            severity="soft-warning",
            slide_id=slide_id,
            message=(
                f"signal lists external reference database {db!r} "
                f"but it is NOT named in the cross_tenant_integration "
                f"slide — per D-089, reference DBs (MIBiG/MetaCyc/"
                f"GTDB/BRENDA-class) must be enumerated separately "
                f"from K-BERDL primary DBs."
            ),
            evidence={"db": db, "kind": "reference_db",
                      "signal_reference_dbs": list(signal_reference_dbs)},
        ))

    # External cohorts
    _, missing_cohorts = _names_mentioned_in_text(
        signal_external_cohorts, text, "external_cohort")
    for cohort in missing_cohorts:
        findings.append(GroundingFinding(
            kind="cohort_omission",
            severity="soft-warning",
            slide_id=slide_id,
            message=(
                f"signal lists external cohort {cohort!r} (cited "
                f"in project docs) but it is NOT named in the "
                f"cross_tenant_integration slide — per D-089, "
                f"external cohorts (HMP2/FRANZOSA-class) must be "
                f"attributed for audience trust."
            ),
            evidence={"cohort": cohort,
                      "signal_external_cohorts":
                          list(signal_external_cohorts)},
        ))

    # --- Hallucination checks ---
    # We compare slide-side names against canonical lists; only
    # canonical-known names that DON'T appear in the signal count as
    # hallucinations (otherwise any random word would flag).
    canon_kberdl, canon_reference, canon_cohorts = _load_canonical_lists()
    signal_kberdl_norm = {d.lower() for d in signal_kberdl_dbs}
    signal_reference_norm = {d.lower() for d in signal_reference_dbs}
    signal_cohorts_norm = {c.lower() for c in signal_external_cohorts}

    # K-BERDL hallucinations
    for db in canon_kberdl:
        if db.lower() in signal_kberdl_norm:
            continue
        if _kberdl_db_in_text(db, text):
            findings.append(GroundingFinding(
                kind="database_hallucination",
                severity="soft-warning",
                slide_id=slide_id,
                message=(
                    f"slide names K-BERDL DB {db!r} in title/notes but "
                    f"it is NOT in the extracted signal — possible "
                    f"composer fabrication (extractor scanned "
                    f"README/REPORT/RESEARCH_PLAN/references.md + "
                    f"notebooks; if the DB is genuinely used, the "
                    f"project should reference it in those docs)."
                ),
                evidence={"db": db, "kind": "kberdl_db"},
            ))

    # Reference DB hallucinations
    for db in canon_reference:
        if db.lower() in signal_reference_norm:
            continue
        if _term_in_text(db, text):
            findings.append(GroundingFinding(
                kind="database_hallucination",
                severity="soft-warning",
                slide_id=slide_id,
                message=(
                    f"slide names external reference DB {db!r} in "
                    f"title/notes but it is NOT in the extracted "
                    f"signal — possible composer fabrication."
                ),
                evidence={"db": db, "kind": "reference_db"},
            ))

    # Cohort hallucinations
    for cohort in canon_cohorts:
        if cohort.lower() in signal_cohorts_norm:
            continue
        if _term_in_text(cohort, text):
            findings.append(GroundingFinding(
                kind="cohort_hallucination",
                severity="soft-warning",
                slide_id=slide_id,
                message=(
                    f"slide names external cohort {cohort!r} in "
                    f"title/notes but it is NOT in the extracted "
                    f"signal — possible composer fabrication."
                ),
                evidence={"cohort": cohort},
            ))

    # --- Notebook count mismatch ---
    claimed_counts = _extract_notebook_count_claims(text)
    for claimed in claimed_counts:
        if claimed != signal_notebook_count:
            findings.append(GroundingFinding(
                kind="notebook_count_mismatch",
                severity="soft-warning",
                slide_id=slide_id,
                message=(
                    f"slide claims {claimed} notebook(s) but the "
                    f"extractor counted {signal_notebook_count} "
                    f".ipynb files in the project's notebooks/ tree "
                    f"— per D-089 this is the v0.6 slide-27 failure "
                    f"mode (off-by-one or wrong count). Read the "
                    f"signal's notebook_count verbatim."
                ),
                evidence={"claimed": claimed,
                          "signal_notebook_count": signal_notebook_count},
            ))

    return CrossTenantGroundingReport(
        schema_version=SCHEMA_VERSION,
        slide_spec_path=str(slide_spec_path),
        signal_path=str(signal_path),
        n_kberdl_dbs_in_signal=len(signal_kberdl_dbs),
        n_reference_dbs_in_signal=len(signal_reference_dbs),
        n_external_cohorts_in_signal=len(signal_external_cohorts),
        notebook_count_in_signal=signal_notebook_count,
        findings=findings,
        cross_tenant_slide_present=True,
    )


# ---------------------------------------------------------------------------
# Text report formatter (mirrors check_figure_provenance.format_text_report)
# ---------------------------------------------------------------------------

def format_text_report(report: CrossTenantGroundingReport) -> str:
    lines = []
    lines.append(f"# cross_tenant_integration grounding check "
                 f"({report.schema_version})")
    lines.append("")
    lines.append(f"**slide_spec:** {report.slide_spec_path}")
    lines.append(f"**signal:** {report.signal_path}")
    lines.append(f"**K-BERDL DBs in signal:** "
                 f"{report.n_kberdl_dbs_in_signal}")
    lines.append(f"**reference DBs in signal:** "
                 f"{report.n_reference_dbs_in_signal}")
    lines.append(f"**external cohorts in signal:** "
                 f"{report.n_external_cohorts_in_signal}")
    lines.append(f"**notebook count in signal:** "
                 f"{report.notebook_count_in_signal}")
    lines.append("")
    if not report.cross_tenant_slide_present:
        lines.append(
            "No cross_tenant_integration slide present in slide_spec; "
            "grounding check no-ops. (Slide presence is checked "
            "separately by tools/slide_spec.py per SPEC §7.)")
        return "\n".join(lines)
    if not report.findings:
        lines.append("No findings — grounding satisfied (slide enumerates "
                     "all signal entries; no hallucinated names; notebook "
                     "count matches).")
        return "\n".join(lines)
    lines.append(f"## {len(report.findings)} finding(s)")
    lines.append("")
    for f in report.findings:
        loc = f"slide={f.slide_id}" if f.slide_id is not None else "(deck-level)"
        lines.append(f"### {f.kind} [{f.severity}] — {loc}")
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
        prog="check_cross_tenant_grounding.py",
        description=(
            "v0.7 / D-089 cross_tenant_integration grounding validator. "
            "Compares the composed slide's title + speaker_notes "
            "against the structured signal from extract_cross_tenant.py; "
            "emits soft-warnings on hallucinations + omissions."),
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
        "--signal-path", type=Path,
        help="Override: path to cross_tenant_signal.json "
             "(default: <draft-dir>/working/cross_tenant_signal.json).")
    ap.add_argument(
        "--out", type=Path,
        help="Output path. Default for json: "
             "<draft-dir>/audit/cross_tenant_grounding.json. "
             "Default for text: stdout.")
    ap.add_argument(
        "--report-format", choices=["json", "text"], default="text",
        help="Output format (default: text).")
    args = ap.parse_args(argv)

    draft_dir = args.draft_dir
    slide_spec = (args.slide_spec_path
                  or (draft_dir / "working" / "slide_spec.json"))
    signal = (args.signal_path
              or (draft_dir / "working" / "cross_tenant_signal.json"))

    report = check_cross_tenant_grounding(slide_spec, signal)

    if args.report_format == "json":
        out_path = args.out or (draft_dir / "audit"
                                / "cross_tenant_grounding.json")
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
