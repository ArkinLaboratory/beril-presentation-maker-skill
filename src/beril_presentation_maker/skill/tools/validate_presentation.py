#!/usr/bin/env python3
"""validate_presentation.py — P1–P10 mechanized validators per SPEC §13.

Standalone script invoked by the orchestrator (and by `assemble` after
each pass):

    python3 "$SKILL_DIR/tools/validate_presentation.py" <slide_spec.json> \\
        [--citation-pool <path>] [--draft-dir <path>] \\
        [--mode auto|<mode>] [--strict] [--write-back] \\
        [--report-format json|text]

Exit code semantics:
  0 — no errors (pass / soft-warning / not-applicable / accepted-* statuses)
  1 — at least one validator FAILED (escalation paths to be acted on)
  2 — invocation / I/O error (couldn't read inputs)
  3 — pre-flight schema validation failed (slide_spec.json malformed)

Per SPEC §13.1, P3 (numeric provenance) is the most-load-bearing
validator. Default escalation is `escalate-as-analysis-request` —
the orchestrator emits a structured request to the slide-compose or
speaker-notes prompt to either re-extract or remove the unprovenanced
claim. Auto-fix is forbidden for P3 because it would require
fabricating numbers.

Per SPEC §13.2 dispatch table:
  | Validator | Section/file | Notes |
  | P1 | (orchestrator) | re-allocate slide count |
  | P2 | (orchestrator) | re-allocate time |
  | P3 | slide_compose.v1 or speaker_notes.v1 | unprovenanced claim source |
  | P4 | slide_compose.v1 or citation_pool.v1 | pool gap vs drift |
  | P5 | (orchestrator) | mechanical color swap from brand tokens |
  | P6 | (orchestrator or escalation) | unstretch / regen at higher res |
  | P7 | substory_design.v1 | structural |
  | P8 | (orchestrator) | boilerplate insert |
  | P9 | (orchestrator) | mechanical |
  | P10 | slide_compose.v1 | density is composition concern |

Pure stdlib + Pillow (already a runtime dep). Importable as a module
for unit tests; individual validator functions are pure (spec in,
ValidatorResult out).
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
from typing import Any, Optional

try:
    from PIL import Image
except ImportError:  # graceful: P6 degrades to "skipped" if Pillow missing
    Image = None  # type: ignore


# ---------------------------------------------------------------------------
# Sibling-module loaders
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent


def _load_slide_spec_module():
    path = _THIS_DIR / "slide_spec.py"
    spec = importlib.util.spec_from_file_location("slide_spec", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load slide_spec from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["slide_spec"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Mode budgets (per SPEC §5)
# ---------------------------------------------------------------------------

# (min_slides, max_slides) inclusive
MODE_SLIDE_BUDGETS: dict[str, tuple[int, int]] = {
    "talk-30":     (25, 32),
    "talk-15":     (13, 17),
    "talk-45":     (35, 48),
    "lightning-5": (5, 8),
    "poster-h":    (1, 1),
    "poster-v":    (1, 1),
}

# (target_minutes, tolerance_fraction). Slides → time at 1 min/slide
# (Naegle 2021 Rule 2). Tolerance is ±20% of the mode's nominal time.
MODE_TIME_BUDGETS: dict[str, tuple[int, float]] = {
    "talk-30":     (30, 0.20),
    "talk-15":     (15, 0.20),
    "talk-45":     (45, 0.20),
    "lightning-5": (5, 0.20),
    # Posters: time budget not applicable
}

# Required slide layouts that must appear at least once per SPEC §6/§7/§8
REQUIRED_LAYOUTS_TALK = (
    "title",
    "cross_tenant_integration",
    "acknowledgments",
    "references",
)

REQUIRED_LAYOUTS_POSTER: tuple[str, ...] = ()  # poster has its own template

# Layouts that are themselves substory transitions (SPEC §6.2)
SUBSTORY_OPENING_LAYOUTS = ("section_divider", "big_idea")


# ---------------------------------------------------------------------------
# Status + escalation enums (mirrors slide_spec.VALIDATOR_STATUS plus "fail"
# and "not-applicable" for the report format)
# ---------------------------------------------------------------------------

VALID_STATUSES = (
    "pass",
    "soft-warning",
    "fail",
    "accepted-with-warning",
    "escalated",
    "user-fixed",
    "accepted-as-limitation",
    "not-applicable",
    "skipped",   # e.g., P6 when Pillow missing
)

VALID_ESCALATION_PATHS = (
    "auto-fix",
    "escalate",
    "user-modify",
    "accept-as-limitation",
    "accept-with-warning",
    "n/a",
)


# ---------------------------------------------------------------------------
# Result dataclasses (mirror paper-writer's validate_manuscript shape)
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """One specific violation identified by a validator."""

    severity: str  # "error" | "warning"
    where: str     # e.g., "slide[5]" | "(global)" | "slide[3].speaker_notes"
    message: str
    escalation_path: str  # one of VALID_ESCALATION_PATHS

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class ValidatorResult:
    """One validator's outcome."""

    id: str        # "P1" .. "P10"
    name: str      # short human-readable name
    status: str    # one of VALID_STATUSES
    violations: list[Violation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "violations": [v.to_dict() for v in self.violations],
        }


@dataclass
class ValidationReport:
    """The full report from running all validators against a slide_spec."""

    slide_spec_path: str
    mode: str
    n_slides: int
    validators: list[ValidatorResult]

    def to_dict(self) -> dict:
        passed = sum(1 for v in self.validators if v.status == "pass")
        failed = sum(1 for v in self.validators if v.status == "fail")
        soft = sum(1 for v in self.validators if v.status == "soft-warning")
        na = sum(1 for v in self.validators if v.status == "not-applicable")
        skipped = sum(1 for v in self.validators if v.status == "skipped")
        if failed > 0:
            overall = "fail"
        elif soft > 0:
            overall = "warn"
        else:
            overall = "pass"
        return {
            "slide_spec": self.slide_spec_path,
            "mode": self.mode,
            "n_slides": self.n_slides,
            "validators": [v.to_dict() for v in self.validators],
            "summary": {
                "passed": passed,
                "failed": failed,
                "soft_warnings": soft,
                "not_applicable": na,
                "skipped": skipped,
                "overall_status": overall,
            },
        }

    @property
    def overall_status(self) -> str:
        return self.to_dict()["summary"]["overall_status"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Numeric pattern: integer or decimal, optionally with comma thousands
# separators, optionally followed by % or unit suffix. Matches the kinds of
# numeric claims that appear on slides ("90%", "27,000,000", "p<0.05",
# "12 minutes", "~$0.18", "n=120").
_NUMERIC_RE = re.compile(
    r"\b("                              # token boundary
    r"(?:\d{1,3}(?:,\d{3})+)"           # 1,234 or 1,234,567
    r"|(?:\d+\.\d+)"                    # 0.05, 3.14
    r"|(?:\d{2,})"                      # 27 or larger (skip 0–9 alone)
    r")"
    r"(?:\s*[%×x]|\s*[a-zA-Z]+/[a-zA-Z]+)?"  # 90% or 12 mg/L
    r"\b"
)

# Patterns that should NOT count as numeric claims (false positives we
# learned from the first run on example_slide_spec):
#  - ISO dates / datetimes (2026-04-26, 2026-04-26T15:12:00Z, with TZ offsets)
#  - Section references (§4.1, §3.2.1)
#  - Bare years (1900–2099)
#  - Slide IDs in the form "slide[N]" or "id=N"
_FALSE_POSITIVE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:Z|[+\-]\d{2}:\d{2})?)?\b"),
    re.compile(r"§\d+(?:\.\d+)*"),
    re.compile(r"\b(?:19\d{2}|20\d{2})\b"),
    re.compile(r"slide\[\d+\]"),
    re.compile(r"\bid=\d+\b"),
]


def _extract_numeric_claims(text: str) -> list[str]:
    """Return distinct numeric tokens that look like substantive claims.

    Filters out false positives we know about: ISO dates/timestamps, year
    references, section refs (§4.1), and slide-id markers. The remaining
    tokens are the kinds of numbers that need provenance — counts,
    percentages, p-values, unit-bearing measurements, etc.
    """
    if not text:
        return []
    masked = text
    for pat in _FALSE_POSITIVE_PATTERNS:
        masked = pat.sub("[X]", masked)

    found: list[str] = []
    seen: set[str] = set()
    for m in _NUMERIC_RE.finditer(masked):
        token = m.group(0).strip()
        # Defensive: bare 4-digit year-looking tokens that snuck through
        if len(token) == 4 and token.isdigit():
            continue
        if token not in seen:
            seen.add(token)
            found.append(token)
    return found


def _short_ref_to_key(short_ref: str) -> str:
    """Convert a short-form citation like 'Smith 2023' to a normalized key.
    Used for orphan-citation cross-checking. Rough heuristic — the citation
    pool entries should carry their own short-ref form, but until that
    lands in v0.2 we normalize permissively."""
    return re.sub(r"[^a-z0-9]", "", short_ref.lower())


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_p1_mode_budget(spec: dict) -> ValidatorResult:
    """Slide count within the mode's [min, max] range."""
    mode = spec["mode"]
    n = len(spec["slides"])
    budget = MODE_SLIDE_BUDGETS.get(mode)
    if budget is None:
        return ValidatorResult("P1", "Mode slide budget", "not-applicable")
    lo, hi = budget
    if lo <= n <= hi:
        return ValidatorResult("P1", "Mode slide budget", "pass")
    msg = (f"slide count {n} is outside mode '{mode}' budget {lo}-{hi}; "
           f"orchestrator should re-allocate")
    return ValidatorResult(
        "P1", "Mode slide budget", "fail",
        [Violation(
            severity="error", where="(global)", message=msg,
            escalation_path="auto-fix",
        )],
    )


def validate_p2_time_budget(spec: dict) -> ValidatorResult:
    """Estimated time-per-slide × slide count is within the mode's time budget."""
    mode = spec["mode"]
    if mode not in MODE_TIME_BUDGETS:
        return ValidatorResult("P2", "Mode time budget", "not-applicable")
    target_min, tol = MODE_TIME_BUDGETS[mode]
    est_min = len(spec["slides"]) * 1  # 1 min/slide (Naegle 2021 Rule 2)
    lo = target_min * (1 - tol)
    hi = target_min * (1 + tol)
    if lo <= est_min <= hi:
        return ValidatorResult("P2", "Mode time budget", "pass")
    msg = (f"estimated {est_min}min for {len(spec['slides'])} slides "
           f"vs target {target_min}min (±{int(tol*100)}%, range {lo:.0f}-{hi:.0f})")
    return ValidatorResult(
        "P2", "Mode time budget", "fail",
        [Violation(severity="error", where="(global)", message=msg,
                   escalation_path="auto-fix")],
    )


def validate_p3_numeric_provenance(spec: dict) -> ValidatorResult:
    """Every numeric claim on slide or in speaker notes traces to
    speaker_notes_provenance entries.

    Per SPEC §13.1, this is the most-load-bearing validator. Auto-fix
    is FORBIDDEN — fixing P3 by removing or fabricating numbers is the
    failure mode we design against. Default escalation is 'escalate'
    (re-extract from notebook OR remove the claim).
    """
    violations: list[Violation] = []
    for slide in spec["slides"]:
        sid = slide["id"]
        layout = slide["layout"]
        # Build the corpus of text where numeric claims could appear:
        # slide content texts + speaker_notes
        texts: list[tuple[str, str]] = []  # (where_label, text)
        content = slide.get("content", {})
        # Walk content for string fields
        def _walk(prefix: str, obj: Any) -> None:
            if isinstance(obj, str):
                texts.append((prefix, obj))
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _walk(f"{prefix}[{i}]", item)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    _walk(f"{prefix}.{k}", v)
        _walk("content", content)
        if "speaker_notes" in slide and slide["speaker_notes"]:
            texts.append(("speaker_notes", slide["speaker_notes"]))

        # Find all numeric claims
        all_claims: set[str] = set()
        for _, text in texts:
            for claim in _extract_numeric_claims(text):
                all_claims.add(claim)

        if not all_claims:
            continue

        # Provenance: lookup table from claim → source ref
        provenance = slide.get("speaker_notes_provenance", []) or []
        provenanced_claims: set[str] = set()
        for entry in provenance:
            if not isinstance(entry, dict):
                continue
            claim_text = entry.get("claim", "")
            for token in _extract_numeric_claims(claim_text):
                provenanced_claims.add(token)

        unprovenanced = all_claims - provenanced_claims
        # big_number's headline is itself a numeric claim that's allowed
        # without provenance-entry IF it appears in REPORT or notebook —
        # but we can't verify that here. Treat big_number's headline as
        # auto-provenance only when speaker_notes_provenance has at
        # least one entry referencing the headline (or any source).
        # In practice, the slide-compose prompt is responsible for
        # populating provenance. If absent on a big_number, escalate.
        for claim in sorted(unprovenanced):
            violations.append(Violation(
                severity="error",
                where=f"slide[{sid}].layout={layout}",
                message=(f"numeric claim '{claim}' has no entry in "
                         f"speaker_notes_provenance; either add a provenance "
                         f"entry pointing to notebook/REPORT, or remove the "
                         f"claim. Auto-fix forbidden (would require fabrication)."),
                escalation_path="escalate",
            ))

    if not violations:
        return ValidatorResult("P3", "Numeric provenance", "pass")
    return ValidatorResult("P3", "Numeric provenance", "fail", violations)


def validate_p4_citation_pool_integrity(
    spec: dict, citation_pool: dict | None
) -> ValidatorResult:
    """Every citation key in slide content resolves to a verified entry
    in the citation pool.

    If no pool is provided, returns 'skipped' — the orchestrator should
    pass --citation-pool when one exists.
    """
    if citation_pool is None:
        return ValidatorResult("P4", "Citation pool integrity", "skipped",
                               [Violation(severity="warning", where="(global)",
                                          message=("no citation pool provided "
                                                   "(--citation-pool path missing)"),
                                          escalation_path="user-modify")])

    pool_keys: set[str] = set()
    if isinstance(citation_pool, dict) and "entries" in citation_pool:
        for entry in citation_pool["entries"]:
            key = entry.get("key") if isinstance(entry, dict) else None
            if key:
                pool_keys.add(key)
    elif isinstance(citation_pool, list):
        for entry in citation_pool:
            key = entry.get("key") if isinstance(entry, dict) else None
            if key:
                pool_keys.add(key)

    violations: list[Violation] = []
    for slide in spec["slides"]:
        sid = slide["id"]
        content = slide.get("content", {})
        cites = content.get("citations", []) if isinstance(content, dict) else []
        if not isinstance(cites, list):
            continue
        for c in cites:
            if c not in pool_keys:
                violations.append(Violation(
                    severity="error",
                    where=f"slide[{sid}].content.citations",
                    message=(f"citation key '{c}' not in pool ({len(pool_keys)} "
                             f"keys present); either scope-down (drop the "
                             f"claim), gap-fill (add to pool), or accept-as-"
                             f"limitation"),
                    escalation_path="user-modify",
                ))
    if not violations:
        return ValidatorResult("P4", "Citation pool integrity", "pass")
    return ValidatorResult("P4", "Citation pool integrity", "fail", violations)


def validate_p5_contrast(spec: dict, brand_tokens: dict | None) -> ValidatorResult:
    """KBase Style Guide forbids spring_green / golden_yellow as a contrast
    pair. v0.1 checks: no slide content explicitly references both forbidden
    colors as fg/bg pair. (Full WCAG ratio computation deferred — most
    color usage is master-driven, not slide_spec-driven.)
    """
    if brand_tokens is None:
        # No brand tokens loaded; we can still check for the forbidden pair
        # name appearing in diagram nodes' fill_color / text_color.
        forbidden_pair = {"spring_green", "golden_yellow"}
    else:
        warnings = brand_tokens.get("palette", {}).get("contrast_warnings", []) \
            if isinstance(brand_tokens, dict) else []
        forbidden_pair = set()
        for w in warnings:
            if isinstance(w, dict) and "pair" in w:
                forbidden_pair.update(w["pair"])
    violations: list[Violation] = []
    for slide in spec["slides"]:
        sid = slide["id"]
        diagram = (slide.get("content", {}) or {}).get("diagram") or {}
        if not isinstance(diagram, dict):
            continue
        for i, node in enumerate(diagram.get("nodes", []) or []):
            fc = node.get("fill_color")
            tc = node.get("text_color")
            if fc and tc and fc in forbidden_pair and tc in forbidden_pair:
                violations.append(Violation(
                    severity="error",
                    where=f"slide[{sid}].content.diagram.nodes[{i}]",
                    message=(f"forbidden contrast pair (fill={fc}, text={tc}); "
                             f"KBase Style Guide §5 prohibits spring_green / "
                             f"golden_yellow as contrasting colors"),
                    escalation_path="auto-fix",
                ))
    if not violations:
        return ValidatorResult("P5", "Contrast (forbidden pairs)", "pass")
    return ValidatorResult("P5", "Contrast (forbidden pairs)", "fail", violations)


def validate_p6_figure_resolution(
    spec: dict, draft_dir: Path | None, min_long_edge_px: int = 1024,
) -> ValidatorResult:
    """Embedded image dimensions are ≥ min_long_edge_px in the longer
    dimension. Pillow-based; degrades to 'skipped' if Pillow missing.
    """
    if Image is None:
        return ValidatorResult("P6", "Figure resolution", "skipped",
                               [Violation(severity="warning", where="(global)",
                                          message="Pillow not installed",
                                          escalation_path="n/a")])
    if draft_dir is None:
        return ValidatorResult("P6", "Figure resolution", "skipped",
                               [Violation(severity="warning", where="(global)",
                                          message="--draft-dir not provided",
                                          escalation_path="n/a")])

    draft_dir = Path(draft_dir).resolve()
    violations: list[Violation] = []
    for slide in spec["slides"]:
        sid = slide["id"]
        content = slide.get("content", {}) or {}
        for key in ("figure", "supporting_graphic", "image_path"):
            rel = content.get(key)
            if not rel:
                continue
            p = Path(rel)
            if not p.is_absolute():
                p = draft_dir / p
            if not p.is_file():
                # Asset missing is its own concern (assembler warns); P6
                # only checks dimensions of files that exist.
                continue
            try:
                with Image.open(p) as img:
                    w, h = img.size
            except Exception as e:  # noqa: BLE001
                violations.append(Violation(
                    severity="warning",
                    where=f"slide[{sid}].content.{key}",
                    message=f"could not read image dimensions: {e}",
                    escalation_path="user-modify",
                ))
                continue
            long_edge = max(w, h)
            if long_edge < min_long_edge_px:
                violations.append(Violation(
                    severity="warning",
                    where=f"slide[{sid}].content.{key}",
                    message=(f"image '{p.name}' long edge {long_edge}px < "
                             f"{min_long_edge_px}px target; may appear blurry "
                             f"projected at 1080p+. Consider regenerating at "
                             f"higher resolution."),
                    escalation_path="escalate",
                ))
    if not violations:
        return ValidatorResult("P6", "Figure resolution", "pass")
    # All P6 violations are warnings; status is soft-warning, not fail
    return ValidatorResult("P6", "Figure resolution", "soft-warning", violations)


def validate_p7_divider_slides(spec: dict) -> ValidatorResult:
    """Each substory begins with a section_divider OR big_idea slide.
    Substories are declared in spec.substories; their slide_ids list the
    slide IDs in order. The first slide_id of each substory must be one
    of the SUBSTORY_OPENING_LAYOUTS.
    """
    substories = spec.get("substories", []) or []
    slides_by_id = {s["id"]: s for s in spec.get("slides", [])}
    violations: list[Violation] = []
    for sub in substories:
        sid = sub.get("id", "?")
        slide_ids = sub.get("slide_ids", []) or []
        if not slide_ids:
            violations.append(Violation(
                severity="warning", where=f"substory[{sid}]",
                message="substory has no slide_ids",
                escalation_path="user-modify",
            ))
            continue
        first_id = slide_ids[0]
        first_slide = slides_by_id.get(first_id)
        if first_slide is None:
            violations.append(Violation(
                severity="error", where=f"substory[{sid}].slide_ids[0]",
                message=(f"substory's first slide_id {first_id} not found in "
                         f"spec.slides"),
                escalation_path="user-modify",
            ))
            continue
        layout = first_slide.get("layout")
        if layout not in SUBSTORY_OPENING_LAYOUTS:
            violations.append(Violation(
                severity="error", where=f"slide[{first_id}]",
                message=(f"substory '{sid}' opens with layout '{layout}'; "
                         f"must be one of {SUBSTORY_OPENING_LAYOUTS}. "
                         f"Substory transitions need an explicit divider."),
                escalation_path="auto-fix",
            ))
    if not violations:
        return ValidatorResult("P7", "Divider slides at substory transitions", "pass")
    return ValidatorResult("P7", "Divider slides at substory transitions",
                           "fail", violations)


def validate_p8_required_slides(spec: dict) -> ValidatorResult:
    """The deck contains the required boilerplate slides per SPEC §6/§7/§8.
    Posters skip this check (they have a different render path)."""
    mode = spec["mode"]
    if mode in ("poster-h", "poster-v"):
        return ValidatorResult("P8", "Required slides present", "not-applicable")

    layouts_used: dict[str, list[int]] = {}
    for slide in spec.get("slides", []):
        layouts_used.setdefault(slide["layout"], []).append(slide["id"])

    violations: list[Violation] = []
    for required in REQUIRED_LAYOUTS_TALK:
        if required not in layouts_used:
            violations.append(Violation(
                severity="error", where="(global)",
                message=(f"required layout '{required}' not present; "
                         f"orchestrator should insert from boilerplate"),
                escalation_path="auto-fix",
            ))

    # title must be the FIRST slide
    if "title" in layouts_used:
        first_title_id = min(layouts_used["title"])
        all_slide_ids = sorted(s["id"] for s in spec.get("slides", []))
        if all_slide_ids and first_title_id != all_slide_ids[0]:
            violations.append(Violation(
                severity="warning", where=f"slide[{first_title_id}]",
                message=(f"title slide is at id={first_title_id} but the first "
                         f"slide is id={all_slide_ids[0]}; title should open the deck"),
                escalation_path="user-modify",
            ))

    # cross_tenant_integration must be exactly 1
    if "cross_tenant_integration" in layouts_used:
        n = len(layouts_used["cross_tenant_integration"])
        if n != 1:
            violations.append(Violation(
                severity="warning", where="(global)",
                message=(f"cross_tenant_integration appears {n} times; "
                         f"SPEC §7 expects exactly 1"),
                escalation_path="user-modify",
            ))

    if not violations:
        return ValidatorResult("P8", "Required slides present", "pass")
    if any(v.severity == "error" for v in violations):
        return ValidatorResult("P8", "Required slides present", "fail", violations)
    return ValidatorResult("P8", "Required slides present", "soft-warning", violations)


def validate_p9_no_orphan_citations(spec: dict) -> ValidatorResult:
    """Every short-form citation appearing on a slide is also represented
    on the references slide's refs_short list. (Full pool entries live
    in citation_pool.json — this validator only checks the on-slide
    cross-reference between claim_evidence.citations and references.refs_short.)
    """
    refs_short_normalized: set[str] = set()
    for slide in spec.get("slides", []):
        if slide.get("layout") == "references":
            content = slide.get("content", {}) or {}
            for ref in content.get("refs_short", []) or []:
                refs_short_normalized.add(_short_ref_to_key(ref))

    violations: list[Violation] = []
    for slide in spec.get("slides", []):
        sid = slide["id"]
        content = slide.get("content", {}) or {}
        cites = content.get("citations", []) if isinstance(content, dict) else []
        if not isinstance(cites, list):
            continue
        for c in cites:
            # c is a citation pool key. Try to find a refs_short entry
            # that matches its normalized form. If neither the full key
            # nor any contained surname appears in refs_short, flag.
            norm = _short_ref_to_key(c)
            # Permissive: substring-on-normalized
            if not any(norm in r or r in norm for r in refs_short_normalized):
                violations.append(Violation(
                    severity="warning",
                    where=f"slide[{sid}].content.citations",
                    message=(f"citation '{c}' not represented on the references "
                             f"slide; orchestrator should append to refs_short"),
                    escalation_path="auto-fix",
                ))
    if not violations:
        return ValidatorResult("P9", "No orphan citations", "pass")
    return ValidatorResult("P9", "No orphan citations", "soft-warning", violations)


def validate_p10_density(spec: dict) -> ValidatorResult:
    """Density discipline (SPEC §6.3): max 35 words per slide (excluding
    speaker notes), title looks like a punchline (not a topic word).

    Title-as-topic check looks for slides whose title is one of the
    canonical topic words.
    """
    BANNED_TITLES = {
        "methods", "results", "discussion", "background",
        "workflow", "pipeline", "approach", "overview",
        "introduction", "conclusion",
    }
    MAX_WORDS = 35

    violations: list[Violation] = []
    for slide in spec.get("slides", []):
        sid = slide["id"]
        layout = slide["layout"]
        content = slide.get("content", {}) or {}

        # Punchline-title rule (SPEC §6.1) — exempt layouts:
        # references and acknowledgments hard-code titles.
        # qa_anticipated uses 'question' not 'title'.
        # section_divider uses 'punchline'. big_number uses 'headline'.
        title_text = ""
        if layout not in ("references", "acknowledgments", "qa_anticipated",
                          "section_divider", "big_number"):
            title_text = (content.get("title") or "").strip()
            if title_text.lower().rstrip(".:") in BANNED_TITLES:
                violations.append(Violation(
                    severity="error",
                    where=f"slide[{sid}].content.title",
                    message=(f"title '{title_text}' is a topic, not a punchline; "
                             f"SPEC §6.1 requires titles to convey the slide's "
                             f"argument"),
                    escalation_path="user-modify",
                ))

        # Word-count: sum across stringy content fields (excludes speaker_notes)
        word_count = 0
        def _count(obj: Any) -> None:
            nonlocal word_count
            if isinstance(obj, str):
                word_count += len(obj.split())
            elif isinstance(obj, list):
                for item in obj:
                    _count(item)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _count(v)
        _count(content)

        # methods_summary explicitly has more text by design (5–10 bullets)
        # cross_tenant_integration may also; skip word-count for them
        if layout in ("methods_summary", "cross_tenant_integration",
                      "qa_anticipated"):
            continue
        if word_count > MAX_WORDS:
            violations.append(Violation(
                severity="warning",
                where=f"slide[{sid}].layout={layout}",
                message=(f"slide has {word_count} words on-slide (excluding "
                         f"speaker notes); SPEC §6.3 caps at {MAX_WORDS}. "
                         f"Move detail to speaker notes."),
                escalation_path="user-modify",
            ))

    if not violations:
        return ValidatorResult("P10", "Density discipline", "pass")
    if any(v.severity == "error" for v in violations):
        return ValidatorResult("P10", "Density discipline", "fail", violations)
    return ValidatorResult("P10", "Density discipline", "soft-warning", violations)


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

VALIDATOR_FUNCS: list[tuple[str, Any]] = [
    ("P1", validate_p1_mode_budget),
    ("P2", validate_p2_time_budget),
    ("P3", validate_p3_numeric_provenance),
    # P4 + P5 take extra args (citation_pool, brand_tokens) — handled below
    ("P6", validate_p6_figure_resolution),
    ("P7", validate_p7_divider_slides),
    ("P8", validate_p8_required_slides),
    ("P9", validate_p9_no_orphan_citations),
    ("P10", validate_p10_density),
]


def validate_presentation(
    spec: dict,
    *,
    citation_pool: dict | None = None,
    brand_tokens: dict | None = None,
    draft_dir: Path | None = None,
    slide_spec_path: str = "(unknown)",
) -> ValidationReport:
    """Run all P1–P10 validators against the spec. Returns a ValidationReport.

    Pre-flight: caller must have already validated spec against
    slide_spec.py::validate_slide_spec(). This function assumes the spec
    is structurally valid; behavior is undefined otherwise.
    """
    results: list[ValidatorResult] = []
    # P1, P2, P3 — spec-only
    results.append(validate_p1_mode_budget(spec))
    results.append(validate_p2_time_budget(spec))
    results.append(validate_p3_numeric_provenance(spec))
    # P4 — needs pool
    results.append(validate_p4_citation_pool_integrity(spec, citation_pool))
    # P5 — uses brand tokens (forbidden contrast pairs)
    results.append(validate_p5_contrast(spec, brand_tokens))
    # P6 — needs draft_dir + Pillow
    results.append(validate_p6_figure_resolution(spec, draft_dir))
    # P7 — spec only
    results.append(validate_p7_divider_slides(spec))
    # P8 — spec only
    results.append(validate_p8_required_slides(spec))
    # P9 — spec only
    results.append(validate_p9_no_orphan_citations(spec))
    # P10 — spec only
    results.append(validate_p10_density(spec))

    return ValidationReport(
        slide_spec_path=slide_spec_path,
        mode=spec.get("mode", "(unknown)"),
        n_slides=len(spec.get("slides", []) or []),
        validators=results,
    )


# ---------------------------------------------------------------------------
# Write-back: store validator_status onto each slide in slide_spec.json
# ---------------------------------------------------------------------------

def write_back_validator_status(
    spec_path: Path, report: ValidationReport,
) -> None:
    """Update the slide_spec.json file with per-slide validator_status from
    the report. Only slides referenced in any violation get an updated
    status block; others are unchanged.
    """
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    # Group violations by slide id
    by_slide: dict[int, dict[str, str]] = {}
    for v_result in report.validators:
        for viol in v_result.violations:
            m = re.match(r"slide\[(\d+)\]", viol.where)
            if m:
                sid = int(m.group(1))
                # Map ValidatorResult.status to slide-level VALIDATOR_STATUS
                slide_level = (
                    "soft-warning" if v_result.status == "soft-warning"
                    else "escalated"
                )
                by_slide.setdefault(sid, {})[v_result.id] = slide_level

    # Apply to slides
    for slide in spec.get("slides", []):
        sid = slide["id"]
        if sid in by_slide:
            existing = slide.get("validator_status") or {}
            existing.update(by_slide[sid])
            slide["validator_status"] = existing

    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def format_text_report(report: ValidationReport) -> str:
    out = []
    summary = report.to_dict()["summary"]
    out.append(f"slide_spec: {report.slide_spec_path}")
    out.append(f"mode:       {report.mode}  ({report.n_slides} slides)")
    out.append(f"overall:    {summary['overall_status']}  "
               f"(passed={summary['passed']} "
               f"failed={summary['failed']} "
               f"soft_warnings={summary['soft_warnings']} "
               f"skipped={summary['skipped']} "
               f"n/a={summary['not_applicable']})")
    out.append("")
    for v in report.validators:
        out.append(f"  {v.id} {v.name}: {v.status}")
        for viol in v.violations:
            out.append(f"      [{viol.severity}] {viol.where}: {viol.message}")
            out.append(f"        → {viol.escalation_path}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_presentation",
        description="Run P1–P10 mechanized validators against slide_spec.json.",
    )
    parser.add_argument("slide_spec",
                        help="Path to slide_spec.json")
    parser.add_argument("--citation-pool",
                        help="Path to citation_pool.json (for P4)")
    parser.add_argument("--brand-tokens",
                        help="Path to kbase-brand-tokens.json (for P5). "
                             "Defaults to the shipped one.")
    parser.add_argument("--draft-dir",
                        help="Draft directory for resolving figure paths (P6). "
                             "Default: parent dir of slide_spec.json.")
    parser.add_argument("--report-format", choices=["json", "text"],
                        default="text",
                        help="Output format. Default: text.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero on any soft-warning too.")
    parser.add_argument("--write-back", action="store_true",
                        help="Update slide_spec.json with per-slide "
                             "validator_status entries.")
    args = parser.parse_args(argv)

    spec_path = Path(args.slide_spec).resolve()
    if not spec_path.is_file():
        print(f"slide_spec not found: {spec_path}", file=sys.stderr)
        return 2

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"slide_spec is not valid JSON: {e}", file=sys.stderr)
        return 2

    # Pre-flight schema validation
    ss = _load_slide_spec_module()
    issues = ss.validate_slide_spec(spec)
    if issues:
        print(f"slide_spec failed schema pre-flight ({len(issues)} issue(s)):",
              file=sys.stderr)
        for i in issues[:20]:
            print(f"  {i.format()}", file=sys.stderr)
        if len(issues) > 20:
            print(f"  ... +{len(issues)-20} more", file=sys.stderr)
        return 3

    citation_pool = None
    if args.citation_pool:
        try:
            citation_pool = json.loads(
                Path(args.citation_pool).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"--citation-pool: {e}", file=sys.stderr)
            return 2

    brand_tokens = None
    bt_path = (Path(args.brand_tokens) if args.brand_tokens
               else _THIS_DIR.parent / "references" / "kbase-brand-tokens.json")
    if bt_path.is_file():
        try:
            brand_tokens = json.loads(bt_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # silently degrade — P5 will check forbidden pair via fallback

    draft_dir = (Path(args.draft_dir).resolve() if args.draft_dir
                 else spec_path.parent)

    report = validate_presentation(
        spec,
        citation_pool=citation_pool,
        brand_tokens=brand_tokens,
        draft_dir=draft_dir,
        slide_spec_path=str(spec_path),
    )

    if args.report_format == "json":
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(format_text_report(report))

    if args.write_back:
        write_back_validator_status(spec_path, report)

    overall = report.overall_status
    if overall == "fail":
        return 1
    if args.strict and overall == "warn":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
