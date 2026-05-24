#!/usr/bin/env python3
"""review_cascade.py — tiered review cascade orchestrator (v0.4 M4b).

V0_4_ARCHITECTURE.md §8 (Phase 4 — Tiered review cascade, fail-fast)
+ §16 M4b + M4b_PUNCH_LIST.md. Wraps three existing pieces under a
single fail-fast contract:

  Tier 1 — deterministic + visual-QA aggregation (~$0.00 — $0.05).
           Aggregates validate_presentation (P1–P10),
           check_quantitative_grounding.py, check_no_artifact_refs.py,
           reconcile_deck.py, and audit/visual_qa.json (when present
           per the M4a opt-in posture, D-050 → DQ2 ship as (b)).
           Tier-1 P0 (P3 numeric / P4 citation / P5 brand) SHORT-
           CIRCUITS Tiers 2+3.

  Tier 2 — Haiku narrative-light (~$0.05). Four detection classes per
           §8.1 (register_drift, qa_softball, unbacked_quantitative,
           substory_arc). ALWAYS ADVISORY per DQ4 — never gates Tier 3.

  Tier 3 — canonical adversarial (~$0.50–$1.50). Wraps
           `beril-adversarial review --type presentation` (the same
           call stage_adversarial_review makes today). Runs unless
           Tier-1 short-circuited OR the operator passed
           --no-adversarial. Produces the same audit/adversarial_review.json
           the revise loop already consumes — cascade integrates, doesn't
           replace.

This is an ADVISORY orchestrator (rc=0 always, like reconcile_deck.py +
visual_qa.py). Findings inform the revise loop / hand-edit; per-tier
short-circuit decisions affect WHAT runs, never what exits the
orchestrator non-zero.

DQ resolutions (Adam 2026-05-24; land as D-054..D-057 in Tier F):
  DQ1 → auto-run by default; opt out via `--no-review-cascade` on the
        orchestrator.
  DQ2 → cascade reads audit/visual_qa.json if present; never invokes
        visual_qa.py itself. Operator opts in to visual-QA via the
        existing --visual-qa flag.
  DQ3 → Tier 2 ships with the §8.1 candidate-four detection classes
        as v1; empirical calibration is a one-off probe + ship-then-
        iterate.
  DQ4 → operator-gated short-circuit: Tier-1 P0 skips Tier 2+3;
        Tier-2 findings are always advisory (never gate Tier 3);
        Tier 3 runs unless --no-adversarial.

CLI:
    python3 review_cascade.py <draft_dir>
                              [--no-tier2] [--no-tier3]
                              [--quiet]

Exit code: always 0 (advisory). The cascade JSON's
short_circuited_at field tells the orchestrator whether to skip the
standalone stage_adversarial_review.

Layout: v0.3.1+ 4-zone draft directory. Reads
<draft_dir>/working/slide_spec.json and the existing audit/ artifacts
(quantitative_grounding.json, no_artifact_refs.json,
deck_reconciliation.json, visual_qa.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "review-cascade.v1"
VERSION = "0.4.0-m4b-tierE"

_THIS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Tier-B P0/P1/P2 severity map for P-validators (DQ4 + D-058)
# ---------------------------------------------------------------------------
#
# Per M4b_PUNCH_LIST.md DQ4 + SPEC §13's tier classification: only the
# load-bearing mechanical validators short-circuit. Every other
# validator fail is P1 (advisory, no short-circuit).
#
# **P3 demoted from P0 to P1 (M4b Tier E, 2026-05-24 — see D-058):**
# P3 validates a `speaker_notes_provenance` index that v0.3 composers
# emitted but v0.4 composer (`slide_compose.v2.md`, M3) does not.
# On the M4a-closed `ibd_phage_targeting/draft_1` deck, the Tier E
# probe found P3 fires on 282 numbers (every number on every slide,
# because the index is empty) — Tier 1 short-circuits before Tier 2
# + Tier 3 can run, defeating the cascade's value prop on EVERY v0.4
# draft. The REPORT-walking `quantitative_grounding.json` (already
# read by Tier 1) is the v0.4 authoritative numeric-provenance check
# (273/278 grounded on the same deck = 98.2% pass rate). P3
# retirement / rewrite-to-wrap-quantitative_grounding is scheduled
# for M5; until then, P3 is advisory-P1 on the v0.4 cascade.
#
# P4 (citation pool) and P5 (brand color) remain P0 — they're
# orthogonal to v0.3/v0.4 composer differences and their contracts
# hold across both paths.

_P0_VALIDATORS: frozenset[str] = frozenset({"P4", "P5"})


# ---------------------------------------------------------------------------
# Cascade schema
# ---------------------------------------------------------------------------
#
# Tier status values:
#   "pass"              — tier ran and emitted no P0 findings
#   "advisory"          — tier ran; emitted findings; NONE were P0
#                         (Tier 2 always lands here per DQ4)
#   "fail"              — tier ran and emitted at least one P0 finding
#                         (Tier 1 only; Tier 2 cannot fail; Tier 3 may
#                         emit central_objection but the cascade
#                         classifies it as advisory — revise loop owns
#                         the response)
#   "skipped"           — tier did not run (--no-tierN flag, missing
#                         dependency, OR earlier tier short-circuited)
#   "not-implemented"   — Tier A scaffolding placeholder; B/C/D fill in
#   "error"             — tier crashed; cascade still completes with
#                         rc=0 but the tier is marked error for the
#                         operator

TIER_STATUSES = (
    "pass", "advisory", "fail", "skipped", "not-implemented", "error",
)


@dataclass
class CascadeFinding:
    """A single finding from any tier. Tier-specific detail goes in
    `evidence` (free-form dict for the cascade JSON consumer)."""
    tier: str            # "tier1" | "tier2" | "tier3"
    kind: str            # validator id ("P3"), check name, or class
    severity: str        # "P0" | "P1" | "P2" | "advisory"
    slide_id: int | None
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TierResult:
    """One tier's outcome in the cascade."""
    name: str            # "tier1" | "tier2" | "tier3"
    status: str          # see TIER_STATUSES
    findings: list[CascadeFinding] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_sec: float = 0.0
    note: str = ""       # free-form (e.g., "skipped — Tier 1 short-circuited")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "cost_usd": self.cost_usd,
            "duration_sec": self.duration_sec,
            "note": self.note,
        }

    @property
    def has_p0(self) -> bool:
        return any(f.severity == "P0" for f in self.findings)


@dataclass
class CascadeReport:
    """The full cascade outcome."""
    draft_dir: str
    tiers: list[TierResult]
    short_circuited_at: str | None = None
    note: str = ""

    @property
    def total_cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.tiers)

    @property
    def total_duration_sec(self) -> float:
        return sum(t.duration_sec for t in self.tiers)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "draft_dir": self.draft_dir,
            "tiers": [t.to_dict() for t in self.tiers],
            "short_circuited_at": self.short_circuited_at,
            "total_cost_usd": self.total_cost_usd,
            "total_duration_sec": self.total_duration_sec,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Per-tier dispatchers (Tier A: scaffolding only; B/C/D fill in)
# ---------------------------------------------------------------------------

def _parse_slide_id_from_location(where: str) -> int | None:
    """Extract slide id from a ValidatorResult location string like
    'slide[5]' or 'slide[5].speaker_notes'. Returns None on (global)
    or unparseable locations.
    """
    import re
    if not isinstance(where, str):
        return None
    m = re.match(r"slide\[(\d+)\]", where)
    return int(m.group(1)) if m else None


def _load_json_safe(path: Path) -> dict | None:
    """Read + parse JSON; return None on any failure. Cascade is
    advisory — a missing/malformed audit artifact is logged, not raised.
    """
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _validate_p1_p10(
    draft_dir: Path, write_audit: bool = True,
) -> list[CascadeFinding]:
    """Run validate_presentation.py P1–P10 against working/slide_spec.json.

    Cascade Tier B runs validate_presentation directly because the
    orchestrator doesn't run it as a separate stage today (no
    audit/presentation_validation.json was being written). When
    write_audit=True, we persist the report so future cascade runs
    (e.g., --resume-from merge with --no-review-cascade) still have
    the artifact for forensic review.

    Returns CascadeFinding list per the DQ4 P0/P1/P2 classification:
      - P3/P4/P5 fail → severity="P0" (short-circuits later tiers)
      - other validator fail → severity="P1" (advisory)
      - soft-warning / skipped / not-applicable / pass → no finding
    """
    import importlib.util as _u
    spec_path = draft_dir / "working" / "slide_spec.json"
    if not spec_path.is_file():
        return []

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    # Pre-flight via slide_spec.validate_slide_spec — validate_presentation
    # assumes the spec is structurally valid (per its docstring) and will
    # KeyError on a malformed spec. Skip the P1-P10 pass on a malformed
    # spec; the assembler's own pre-flight is the authoritative gate for
    # structural validity, and the cascade is advisory.
    ss_spec = _u.spec_from_file_location(
        "_ss_for_cascade", _THIS_DIR / "slide_spec.py")
    ss_mod = _u.module_from_spec(ss_spec)
    sys.modules["_ss_for_cascade"] = ss_mod
    ss_spec.loader.exec_module(ss_mod)
    structural_issues = ss_mod.validate_slide_spec(spec)
    structural_errors = [
        i for i in structural_issues
        if getattr(i, "severity", "error") == "error"
    ]
    if structural_errors:
        # Spec is structurally invalid — P1-P10 would crash. Skip
        # gracefully (cascade is advisory; the assembler is the
        # authoritative gate).
        return []

    # Load validate_presentation as a sibling module (same pattern as
    # assemble_pptx.assemble_pptx_for_qa in visual_qa.py).
    vp_spec = _u.spec_from_file_location(
        "_vp_for_cascade", _THIS_DIR / "validate_presentation.py")
    vp_mod = _u.module_from_spec(vp_spec)
    sys.modules["_vp_for_cascade"] = vp_mod
    vp_spec.loader.exec_module(vp_mod)

    # Pre-load the citation pool if present (P4 needs it; otherwise P4
    # skips).
    citation_pool_path = draft_dir / "working" / "citation_pool.json"
    citation_pool = None
    if citation_pool_path.is_file():
        try:
            citation_pool = json.loads(
                citation_pool_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            citation_pool = None

    report = vp_mod.validate_presentation(
        spec,
        citation_pool=citation_pool,
        draft_dir=draft_dir,
        slide_spec_path=str(spec_path),
    )

    # Persist the audit artifact for forensic review.
    if write_audit:
        audit_dir = draft_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        try:
            (audit_dir / "presentation_validation.json").write_text(
                json.dumps(report.to_dict(), indent=2) + "\n"
            )
        except OSError:
            pass   # advisory; don't block the cascade

    findings: list[CascadeFinding] = []
    for vr in report.validators:
        if vr.status != "fail":
            continue
        severity = "P0" if vr.id in _P0_VALIDATORS else "P1"
        for viol in vr.violations:
            findings.append(CascadeFinding(
                tier="tier1",
                kind=vr.id,
                severity=severity,
                slide_id=_parse_slide_id_from_location(viol.where),
                detail=f"{vr.name}: {viol.message}",
                evidence={
                    "where": viol.where,
                    "severity": viol.severity,
                    "escalation_path": viol.escalation_path,
                },
            ))
    return findings


def _read_quantitative_grounding(draft_dir: Path) -> list[CascadeFinding]:
    """Read audit/quantitative_grounding.json (written by orchestrator
    in stage_merge_and_assemble) and emit cascade findings.

    Severity map: GroundingReport.findings carry their own severity
    ("high", "medium", "low") → cascade severity "P1" / "P2" / "P2".
    All advisory (no P0 from this check).
    """
    payload = _load_json_safe(draft_dir / "audit" / "quantitative_grounding.json")
    if payload is None:
        return []
    findings: list[CascadeFinding] = []
    for f in payload.get("findings", []) or []:
        sev_in = f.get("severity", "low")
        sev_out = "P1" if sev_in == "high" else "P2"
        number = f.get("number") or {}
        n_text = number.get("text") or number.get("raw") or "<num>"
        findings.append(CascadeFinding(
            tier="tier1",
            kind="quantitative_grounding",
            severity=sev_out,
            slide_id=f.get("slide_id"),
            detail=(f"ungrounded number {n_text!r}: "
                    f"{f.get('note', '<no note>')}"),
            evidence={"slide_position": f.get("slide_position"),
                      "slide_layout": f.get("slide_layout"),
                      "number": number,
                      "input_severity": sev_in},
        ))
    return findings


def _read_no_artifact_refs(draft_dir: Path) -> list[CascadeFinding]:
    """Read audit/no_artifact_refs.json (process-detail-bleed checker)
    and emit cascade findings. All P2 — these are advisory hints, not
    contract violations.
    """
    payload = _load_json_safe(draft_dir / "audit" / "no_artifact_refs.json")
    if payload is None:
        return []
    findings: list[CascadeFinding] = []
    for hit in payload.get("hits", []) or []:
        findings.append(CascadeFinding(
            tier="tier1",
            kind="no_artifact_refs",
            severity="P2",
            slide_id=hit.get("slide_id"),
            detail=(f"{hit.get('pattern', '?')}: "
                    f"{hit.get('matched_text', '<text>')!r} — "
                    f"{hit.get('explanation', '')}"),
            evidence={"slide_position": hit.get("slide_position"),
                      "slide_layout": hit.get("slide_layout"),
                      "location": hit.get("location"),
                      "context": hit.get("context"),
                      "suggestion": hit.get("suggestion")},
        ))
    return findings


def _read_deck_reconciliation(draft_dir: Path) -> list[CascadeFinding]:
    """Read audit/deck_reconciliation.json (M3 cross-section conflict
    checker) and emit cascade findings. All P1 — cross-section
    conflicts are real defects but never load-bearing-P0 (composers
    can land a clean spec with a duplicate-headline conflict; revise
    fixes).
    """
    payload = _load_json_safe(draft_dir / "audit" / "deck_reconciliation.json")
    if payload is None:
        return []
    findings: list[CascadeFinding] = []
    for f in payload.get("findings", []) or []:
        # deck_reconciliation findings name multiple slide_ids; emit
        # one cascade finding per group with the slide_ids list in
        # evidence (cascade's slide_id field is single-int).
        slide_ids = f.get("slide_ids") or []
        findings.append(CascadeFinding(
            tier="tier1",
            kind=f.get("kind", "deck_reconciliation"),
            severity="P1",
            slide_id=slide_ids[0] if slide_ids else None,
            detail=f.get("detail", "<no detail>"),
            evidence={"slide_ids": slide_ids,
                      "input_severity": f.get("severity")},
        ))
    return findings


def _read_visual_qa(draft_dir: Path) -> list[CascadeFinding]:
    """Read audit/visual_qa.json (M4a opt-in --visual-qa output) if
    present. Per DQ2 (Adam 2026-05-24 — ship as (b)), cascade reads
    this artifact but NEVER invokes visual_qa.py. Skill ships portable;
    operator opts in to visual-QA via the existing --visual-qa flag.

    Severity map (per visual_qa.v1.md): confidence="high" → P1;
    "medium"/"low" → P2. No P0 from visual-QA — render-quality
    defects don't gate the cascade.
    """
    payload = _load_json_safe(draft_dir / "audit" / "visual_qa.json")
    if payload is None:
        return []
    # M4a stub posture: if the visual-QA pass was skipped (toolchain
    # incomplete / spec missing), it writes a stub with note + zero
    # findings. We ignore the stub.
    findings_raw = payload.get("findings") or []
    if not findings_raw:
        return []
    findings: list[CascadeFinding] = []
    for f in findings_raw:
        conf = f.get("confidence", "medium")
        sev_out = "P1" if conf == "high" else "P2"
        findings.append(CascadeFinding(
            tier="tier1",
            kind=f"visual_qa:{f.get('kind', '?')}",
            severity=sev_out,
            slide_id=f.get("slide_id"),
            detail=f.get("detail", "<no detail>"),
            evidence={"confidence": conf,
                      "evidence_locator": f.get("evidence_locator")},
        ))
    return findings


def run_tier1(draft_dir: Path) -> TierResult:
    """Tier 1 — deterministic + visual-QA aggregation (M4b Tier B).

    Aggregates five sources in fail-fast cost order (cheapest first):
      1. validate_presentation P1–P10 — run directly (no orchestrator
         stage today); writes audit/presentation_validation.json as
         a side-effect.
      2. audit/quantitative_grounding.json (orchestrator wrote it)
      3. audit/no_artifact_refs.json
      4. audit/deck_reconciliation.json
      5. audit/visual_qa.json (DQ2: read-if-present; never invoke)

    DQ4 short-circuit semantics: a P3/P4/P5 fail (per _P0_VALIDATORS)
    marks the tier 'fail' and triggers cascade short-circuit; otherwise
    the tier is 'advisory' (when there are P1/P2 findings) or 'pass'
    (no findings).
    """
    t0 = datetime.now(timezone.utc)
    findings: list[CascadeFinding] = []
    notes: list[str] = []

    # 1. P1–P10 mechanical validators.
    try:
        findings.extend(_validate_p1_p10(draft_dir, write_audit=True))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"validate_presentation raised: {exc}")

    # 2. Quantitative-grounding hits.
    try:
        findings.extend(_read_quantitative_grounding(draft_dir))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"quantitative_grounding read raised: {exc}")

    # 3. Process-detail-bleed hits.
    try:
        findings.extend(_read_no_artifact_refs(draft_dir))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"no_artifact_refs read raised: {exc}")

    # 4. Deck reconciliation conflicts.
    try:
        findings.extend(_read_deck_reconciliation(draft_dir))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"deck_reconciliation read raised: {exc}")

    # 5. Visual-QA (opt-in; read-if-present per DQ2).
    try:
        findings.extend(_read_visual_qa(draft_dir))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"visual_qa read raised: {exc}")

    duration = (datetime.now(timezone.utc) - t0).total_seconds()
    has_p0 = any(f.severity == "P0" for f in findings)
    if has_p0:
        status = "fail"
    elif findings:
        status = "advisory"
    else:
        status = "pass"

    return TierResult(
        name="tier1",
        status=status,
        findings=findings,
        cost_usd=0.0,            # Tier 1 is deterministic + free
        duration_sec=duration,
        note=" · ".join(notes),
    )


def _invoke_review_tier2(draft_dir: Path, claude_bin: str = "claude") -> int:
    """Load + invoke the review_tier2 sibling module.

    Extracted as a separate function so unit tests can monkeypatch it
    without wrestling with the importlib spec_from_file_location
    machinery. Same sibling-module-load pattern as _validate_p1_p10.
    """
    import importlib.util as _u
    rt2_spec = _u.spec_from_file_location(
        "_rt2_for_cascade", _THIS_DIR / "review_tier2.py")
    rt2_mod = _u.module_from_spec(rt2_spec)
    sys.modules["_rt2_for_cascade"] = rt2_mod
    rt2_spec.loader.exec_module(rt2_mod)
    return rt2_mod.run_tier2(
        draft_dir, quiet=True, claude_bin=claude_bin)


def run_tier2(
    draft_dir: Path,
    *,
    claude_bin: str = "claude",
) -> TierResult:
    """Tier 2 — Haiku narrative-light (4 detection classes; M4b Tier C).

    Invokes tools/review_tier2.py (claude-haiku-4-5 + the 4 detection
    classes from §8.1: register_drift, qa_softball,
    unbacked_quantitative, substory_arc). Reads
    audit/review_tier2.json and lifts findings into cascade
    findings.

    DQ4: Tier 2 NEVER emits P0 — every finding is severity P1 or P2.
    The cascade's short-circuit logic in run_cascade reads
    TierResult.has_p0, so a Tier-2 result always has has_p0=False
    and Tier 3 always runs after Tier 2.
    """
    t0 = datetime.now(timezone.utc)

    # Invoke review_tier2 — handles its own toolchain probe, stub-report
    # fallback, and audit/review_tier2.{md,json} writes. Always rc=0.
    try:
        _invoke_review_tier2(draft_dir, claude_bin=claude_bin)
    except Exception as exc:  # noqa: BLE001
        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        return TierResult(
            name="tier2",
            status="error",
            note=f"review_tier2 raised: {exc}",
            duration_sec=duration,
        )

    duration = (datetime.now(timezone.utc) - t0).total_seconds()
    payload = _load_json_safe(draft_dir / "audit" / "review_tier2.json")
    if payload is None:
        return TierResult(
            name="tier2",
            status="error",
            note="review_tier2 did not produce audit/review_tier2.json",
            duration_sec=duration,
        )

    # Stub posture: empty findings + a note (missing claude, missing
    # spec, LLM error). Map to 'skipped' so the cascade reflects the
    # degraded path without claiming a clean pass.
    findings_raw = payload.get("findings") or []
    if not findings_raw and payload.get("note"):
        return TierResult(
            name="tier2",
            status="skipped",
            note=payload.get("note", ""),
            duration_sec=duration,
        )

    findings: list[CascadeFinding] = []
    for f in findings_raw:
        sev = f.get("severity", "P2")
        # Pin DQ4 invariant: Tier 2 cannot emit P0. If the model
        # tries (it shouldn't per the prompt), demote to P1.
        if sev not in ("P1", "P2"):
            sev = "P1"
        findings.append(CascadeFinding(
            tier="tier2",
            kind=f.get("kind", "unknown"),
            severity=sev,
            slide_id=f.get("slide_id"),
            detail=f.get("detail", "<no detail>"),
            evidence={"confidence": f.get("confidence", "medium"),
                      "evidence_locator": f.get("evidence_locator")},
        ))

    return TierResult(
        name="tier2",
        status="advisory" if findings else "pass",
        findings=findings,
        # cost_usd reads come from the diagnostic written into
        # audit/review_tier2.json by the rt2 module's stub on failure
        # paths; on the happy path the rt2 module doesn't currently
        # write cost back into the JSON (it goes to stderr). Future
        # iteration: persist diag.cost_usd into the JSON envelope.
        cost_usd=0.0,
        duration_sec=duration,
    )


def _invoke_beril_adversarial(
    draft_dir: Path,
    adversarial_bin: str = "beril-adversarial",
) -> tuple[int, str, str, float]:
    """Invoke `beril-adversarial review --type presentation <draft_dir>`.

    Returns (exit_status, stdout_tail, stderr_tail, duration_sec).
    Does NOT raise — caller decides escalation based on the tuple.
    Extracted as a separate function so unit tests can monkey-patch
    it without subprocess wrangling.
    """
    import subprocess
    t0 = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            [adversarial_bin, "review",
             "--type", "presentation", str(draft_dir)],
            capture_output=True, text=True,
            timeout=900,   # 15 min max for a 27-slide adversarial pass
        )
        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        return (proc.returncode,
                (proc.stdout or "")[-1000:],
                (proc.stderr or "")[-1000:],
                duration)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        return (1, "", f"subprocess exception: {exc}", duration)


def _adversarial_cli_available(adversarial_bin: str = "beril-adversarial") -> bool:
    """Probe for beril-adversarial CLI on PATH. Returns True if found."""
    import shutil
    return shutil.which(adversarial_bin) is not None


def run_tier3(
    draft_dir: Path,
    *,
    adversarial_bin: str = "beril-adversarial",
) -> TierResult:
    """Tier 3 — canonical adversarial (M4b Tier D).

    Invokes `beril-adversarial review --type presentation <draft_dir>`
    — same call stage_adversarial_review makes today. Parses the v3
    output at audit/adversarial_review.json into cascade findings.
    Cascade is the load-bearing caller now; orchestrator's standalone
    stage_adversarial_review elides when cascade Tier 3 ran (the
    orchestrator reads audit/review_cascade.json's tier3.status to
    decide).

    DQ4: Tier 3 has full editorial authority — its v3 findings
    (including central_objection) are lifted as P1 (cascade severity)
    but never short-circuit. The revise loop owns the response;
    cascade just surfaces.

    Status mapping:
      adversarial CLI missing  → "skipped" (note: install hint)
      adversarial rc=0 + JSON  → "pass" / "advisory" based on findings
      adversarial rc != 0      → "error" (note: stderr tail)
      JSON missing post-run    → "error" (note: invocation succeeded
                                  but contract violation)
    """
    t0 = datetime.now(timezone.utc)
    if not _adversarial_cli_available(adversarial_bin):
        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        return TierResult(
            name="tier3",
            status="skipped",
            note=("beril-adversarial CLI not on PATH; install via "
                  "pipx (see HUB_INSTALL.md) to enable canonical Tier 3."),
            duration_sec=duration,
        )

    rc, stdout_tail, stderr_tail, sub_duration = _invoke_beril_adversarial(
        draft_dir, adversarial_bin=adversarial_bin,
    )

    review_path = draft_dir / "audit" / "adversarial_review.json"
    duration = (datetime.now(timezone.utc) - t0).total_seconds()

    if rc != 0:
        return TierResult(
            name="tier3",
            status="error",
            note=(f"beril-adversarial review failed (rc={rc}); "
                  f"stderr tail: {stderr_tail[:200]}"),
            duration_sec=duration,
        )

    if not review_path.is_file():
        return TierResult(
            name="tier3",
            status="error",
            note=(f"beril-adversarial review exited rc=0 but did not "
                  f"produce {review_path} — contract violation."),
            duration_sec=duration,
        )

    payload = _load_json_safe(review_path)
    if payload is None:
        return TierResult(
            name="tier3",
            status="error",
            note=(f"beril-adversarial review wrote unreadable JSON at "
                  f"{review_path}."),
            duration_sec=duration,
        )

    # Lift v3 findings into cascade findings. beril-adversarial v3
    # schema (per CONTRACT.md) names findings under top-level
    # `findings` and a separate `central_objection` (singular, may be
    # absent). Both are surfaced as P1 (advisory) — Tier 3 has full
    # editorial authority but the cascade doesn't gate Tier 3's
    # findings beyond surfacing them (the revise loop owns response).
    findings: list[CascadeFinding] = []
    for f in payload.get("findings", []) or []:
        # v3 finding shape (per CONTRACT.md): {id, slide_id?, kind,
        # severity?, summary, evidence?, recommendation?, ...}
        findings.append(CascadeFinding(
            tier="tier3",
            kind=f.get("kind", "adversarial"),
            severity="P1",
            slide_id=f.get("slide_id"),
            detail=f.get("summary", "<no summary>"),
            evidence={"id": f.get("id"),
                      "input_severity": f.get("severity"),
                      "recommendation": f.get("recommendation")},
        ))
    central = payload.get("central_objection")
    if isinstance(central, dict):
        findings.append(CascadeFinding(
            tier="tier3",
            kind="central_objection",
            severity="P1",
            slide_id=central.get("slide_id"),
            detail=central.get("summary", "<no summary>"),
            evidence={"id": central.get("id"),
                      "recommendation": central.get("recommendation"),
                      "kind": "central_objection"},
        ))

    return TierResult(
        name="tier3",
        status="advisory" if findings else "pass",
        findings=findings,
        cost_usd=0.0,        # beril-adversarial's own cost log is the
                              # source of truth; cascade doesn't double-count
        duration_sec=duration,
    )


# ---------------------------------------------------------------------------
# Cascade orchestrator
# ---------------------------------------------------------------------------

def run_cascade(
    draft_dir: Path,
    *,
    run_tier2_enabled: bool = True,
    run_tier3_enabled: bool = True,
) -> CascadeReport:
    """Run the cascade with operator-gated short-circuit semantics (DQ4).

    Order: Tier 1 → (if no Tier-1 P0) Tier 2 → (if Tier 2 ran) Tier 3.

    Short-circuit semantics:
      - Tier 1 emits a P0 → Tier 2 + Tier 3 SKIPPED (short_circuited_at
        = "tier1").
      - Tier 1 clears OR emits only advisory (P1/P2) → Tier 2 runs.
      - Tier 2 ALWAYS advisory per DQ4 — even if it emits findings,
        Tier 3 still runs (short_circuited_at stays null unless --no-
        tier3 was passed).
      - --no-tier2 / --no-tier3 flags skip the respective tier and mark
        it "skipped"; the next tier still runs.
    """
    tiers: list[TierResult] = []
    short_circuited_at: str | None = None

    # Tier 1
    t1 = run_tier1(draft_dir)
    tiers.append(t1)
    if t1.has_p0:
        short_circuited_at = "tier1"

    # Tier 2
    if short_circuited_at:
        tiers.append(TierResult(
            name="tier2", status="skipped",
            note=f"skipped — short-circuited at {short_circuited_at}",
        ))
    elif not run_tier2_enabled:
        tiers.append(TierResult(
            name="tier2", status="skipped",
            note="skipped — --no-tier2",
        ))
    else:
        t2 = run_tier2(draft_dir)
        tiers.append(t2)
        # DQ4: Tier 2 never short-circuits Tier 3. If t2 has 'findings'
        # they're always advisory; do NOT set short_circuited_at.

    # Tier 3
    if short_circuited_at:
        tiers.append(TierResult(
            name="tier3", status="skipped",
            note=f"skipped — short-circuited at {short_circuited_at}",
        ))
    elif not run_tier3_enabled:
        tiers.append(TierResult(
            name="tier3", status="skipped",
            note="skipped — --no-tier3",
        ))
    else:
        t3 = run_tier3(draft_dir)
        tiers.append(t3)

    return CascadeReport(
        draft_dir=str(draft_dir),
        tiers=tiers,
        short_circuited_at=short_circuited_at,
    )


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def render_md(report: CascadeReport) -> str:
    """Human-readable cascade report for audit/review_cascade.md."""
    lines = [
        "# Review cascade report",
        "",
        f"Draft: `{report.draft_dir}`",
        f"Total cost: ${report.total_cost_usd:.4f}  "
        f"·  duration: {report.total_duration_sec:.1f}s",
    ]
    if report.short_circuited_at:
        lines += [
            "",
            f"**Short-circuited at {report.short_circuited_at}** — "
            "later tiers skipped per DQ4 operator-gated semantics.",
        ]
    if report.note:
        lines += ["", f"_{report.note}_"]
    lines += [""]
    for tier in report.tiers:
        lines += [f"## {tier.name} — {tier.status}"]
        if tier.note:
            lines += ["", f"_{tier.note}_"]
        if tier.findings:
            lines += [
                "",
                f"**{len(tier.findings)} finding(s):**",
                "",
            ]
            for f in tier.findings:
                slide = f" [slide {f.slide_id}]" if f.slide_id is not None else ""
                lines += [
                    f"- **{f.severity}** {f.kind}{slide}: {f.detail}",
                ]
        if tier.cost_usd > 0 or tier.duration_sec > 0:
            lines += [
                "",
                f"_cost ${tier.cost_usd:.4f}  ·  {tier.duration_sec:.1f}s_",
            ]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: CascadeReport, audit_dir: Path) -> tuple[Path, Path]:
    """Write cascade JSON + MD to audit_dir. Returns (json_path, md_path)."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    json_path = audit_dir / "review_cascade.json"
    md_path = audit_dir / "review_cascade.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    md_path.write_text(render_md(report))
    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="review_cascade",
        description="Tiered review cascade orchestrator (advisory). "
                    "v0.4 M4b — wraps Tier 1 (deterministic + visual-QA), "
                    "Tier 2 (Haiku), Tier 3 (canonical adversarial) with "
                    "fail-fast short-circuit on Tier-1 P0 (DQ4).",
    )
    p.add_argument("draft_dir", help="v0.3.1+ draft directory (talks/draft_N/).")
    p.add_argument("--no-tier2", action="store_true",
                   help="Skip Tier 2 (Haiku narrative-light review).")
    p.add_argument("--no-tier3", action="store_true",
                   help="Skip Tier 3 (canonical adversarial). Use this when "
                        "the orchestrator has already run adversarial as a "
                        "separate stage; cascade Tier 3 wraps the same call.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the per-tier stderr summary.")
    args = p.parse_args(argv)

    draft_dir = Path(args.draft_dir)
    audit_dir = draft_dir / "audit"

    spec_path = draft_dir / "working" / "slide_spec.json"
    if not spec_path.is_file():
        # No spec → cascade is a no-op + stub report (mirrors visual_qa.py
        # + reconcile_deck.py degradation posture).
        report = CascadeReport(
            draft_dir=str(draft_dir),
            tiers=[
                TierResult(name="tier1", status="skipped",
                           note=f"slide_spec.json not found at {spec_path}"),
                TierResult(name="tier2", status="skipped",
                           note=f"slide_spec.json not found at {spec_path}"),
                TierResult(name="tier3", status="skipped",
                           note=f"slide_spec.json not found at {spec_path}"),
            ],
            note=f"slide_spec.json missing at {spec_path}; "
                 "cascade is a no-op.",
        )
        write_reports(report, audit_dir)
        if not args.quiet:
            print(f"  review-cascade: skipped — no slide_spec.json at "
                  f"{spec_path}", file=sys.stderr)
        return 0

    report = run_cascade(
        draft_dir,
        run_tier2_enabled=not args.no_tier2,
        run_tier3_enabled=not args.no_tier3,
    )
    json_path, md_path = write_reports(report, audit_dir)

    if not args.quiet:
        n_findings = sum(len(t.findings) for t in report.tiers)
        sc = (f", short-circuited at {report.short_circuited_at}"
              if report.short_circuited_at else "")
        print(
            f"  review-cascade: {n_findings} finding(s) across "
            f"{len(report.tiers)} tier(s) (${report.total_cost_usd:.4f}{sc}) "
            f"— see {md_path}",
            file=sys.stderr,
        )
        for tier in report.tiers:
            marker = "✓" if tier.status == "pass" else (
                "!" if tier.status == "fail" else "·"
            )
            print(f"    {marker} {tier.name}: {tier.status}"
                  + (f" ({len(tier.findings)} finding(s))" if tier.findings else ""),
                  file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
