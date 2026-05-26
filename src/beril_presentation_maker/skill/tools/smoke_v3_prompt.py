#!/usr/bin/env python3
"""smoke_v3_prompt.py — live-LLM single-substory smoke for the v3
concatenated prompts (D-076).

The 1404-test suite catches static issues, but every test mocks the
LLM's output. Per the 2026-05-26 morning-abort lesson (see
auto-memory `project_presentation_maker_v0_5_morning_abort.md`):
mocked-LLM tests can't catch prompt-vs-schema drift. This smoke
addresses that gap by composing ONE substory fragment against the
real LLM using the orchestrator's concatenated v3 prompt, then
validating the fragment against the same schema the orchestrator's
merge stage validates.

Scope (per Tier B DQ resolution):
- BOTH stages: substory_design.v3 (writes 02_substories.md) AND
  slide_compose.v3 (writes a compose-fragment.v3 JSON).
- Total cost ~$0.60 per smoke run.
- Substory_design step is skipped if a pre-canned 02_substories.md
  already exists in the fixture (we want to exercise it on the
  first invocation; subsequent runs can skip it via --fragment-only).

Fixture (per Tier B DQ resolution):
- Lives at tests/fixtures/smoke_v3/ — a tiny synthetic project with
  one finding, two numbers, one substory.

Outputs:
- On pass: writes `audit/v3_smoke_pass.json` at the skill repo
  root (per D-076: prompt-level, not project-level). Sidecar JSON
  carries timestamp + sha of the concatenated v3 prompt bodies +
  the validated fragment as evidence.
- On fail: writes `audit/v3_smoke_fail.json` + the broken artifacts
  for inspection. Returns rc=1.

Exit codes:
  0 — smoke passed; pass record written.
  1 — smoke failed (validation errors); fail record written.
  2 — invocation error (claude CLI missing, fixture missing,
      malformed args).

Usage:
  python tools/smoke_v3_prompt.py [--fragment-only] [--keep-tmpdir]
  python tools/smoke_v3_prompt.py --check-recent  # gate-check only;
      no LLM invocation. Returns rc=0 if a fresh pass record exists,
      rc=1 if stale / absent / sha-mismatched.

Tests: tests/unit/test_smoke_v3_prompt.py — unit tests for the
sha computation + record-write/read + gate-check helpers. The live
LLM path is gated behind BERIL_PRESENTATION_MAKER_RUN_LIVE=1 (same
gate as existing integration tests).

Refs: D-076 (the smoke gating decision); D-075 (the v3 concat the
smoke validates); slide_compose.v2.md §"What you produce" (the
per-layout schema the smoke validates against);
project_presentation_maker_v0_5_morning_abort.md (root-cause).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Default model + tools mirror the orchestrator's settings. If the
# orchestrator changes these, the smoke should follow.
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TOOLS = "Bash,Glob,Grep,Read,Write"

# How fresh a pass record must be to satisfy the gate (D-076).
SMOKE_FRESHNESS_DAYS = 7

# Where the pass/fail records live. Per D-076 this is at the skill
# repo root (not a per-project audit dir) — the smoke is
# prompt-level, not project-level.
SKILL_REPO_ROOT = Path(__file__).resolve().parents[4]
SMOKE_DIR = SKILL_REPO_ROOT / "audit"
PASS_RECORD = SMOKE_DIR / "v3_smoke_pass.json"
FAIL_RECORD = SMOKE_DIR / "v3_smoke_fail.json"

# Fixture location.
FIXTURE_DIR = SKILL_REPO_ROOT / "tests" / "fixtures" / "smoke_v3"

# Prompt sources (the v1/v2 body + v3 overlay files that get
# concatenated). Mirrors `build_v3_concat_prompts` in
# `presentation_maker.sh`.
PROMPTS_DIR = (SKILL_REPO_ROOT / "src" / "beril_presentation_maker"
               / "skill" / "prompts")
SLIDE_V2 = PROMPTS_DIR / "slide_compose.v2.md"
SLIDE_OVERLAY = PROMPTS_DIR / "slide_compose.v3_overlay.md"
SUBSTORY_V1 = PROMPTS_DIR / "substory_design.v1.md"
SUBSTORY_OVERLAY = PROMPTS_DIR / "substory_design.v3_overlay.md"


# ---------------------------------------------------------------------------
# Prompt-body sha
# ---------------------------------------------------------------------------

def compute_prompt_sha() -> str:
    """SHA-256 of the four prompt source files (v1/v2 + v3 overlay
    for both substory_design and slide_compose). Captures the exact
    prompt content the smoke validated against. Used by the
    orchestrator's gate-check to detect prompt drift after a pass.

    Order: substory_v1, substory_overlay, slide_v2, slide_overlay
    (alphabetical for stability).
    """
    h = hashlib.sha256()
    for path in (SUBSTORY_V1, SUBSTORY_OVERLAY, SLIDE_V2, SLIDE_OVERLAY):
        if not path.is_file():
            raise FileNotFoundError(
                f"prompt source missing: {path}; cannot compute sha")
        h.update(path.read_bytes())
        h.update(b"\n--sep--\n")  # explicit separator
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Concat prompt builder (mirrors orchestrator's build_v3_concat_prompts)
# ---------------------------------------------------------------------------

def build_concat(v1_v2_body: Path, overlay: Path, out: Path) -> None:
    """Write `cat v1_v2_body overlay` to `out`. Mirrors the
    orchestrator's `build_v3_concat_prompts` for the smoke."""
    out.write_bytes(v1_v2_body.read_bytes() + overlay.read_bytes())


# ---------------------------------------------------------------------------
# Per-layout required fields (from slide_compose.v2.md ground truth)
# ---------------------------------------------------------------------------
#
# These are the load-bearing field-name pins from v2's "Per-layout
# authoring rules" section. The morning abort produced
# layout-wrong field names (e.g., `title` on section_divider where
# v2 requires `punchline`); this map is the validator's authority.
#
# Source: slide_compose.v2.md §"Per-layout authoring rules" — each
# "- **Required:** ..." line. Verified at v0.5.1 Tier A.1 (D-077).

LAYOUT_REQUIRED_FIELDS = {
    "section_divider":      ["punchline", "substory_number"],
    "big_idea":             ["title"],
    "big_number":           ["headline", "subtitle"],
    "claim_evidence":       ["title", "bullets"],
    "two_column_compare":   ["title", "left_col_title", "left_col_content",
                             "right_col_title", "right_col_content"],
    "data_figure":          ["title", "figure", "caption"],
    "data_table":           ["title", "columns", "rows"],
    "workflow_diagram":     ["title", "diagram"],
    "methods_summary":      ["title", "bullets"],
    "concept_illustration": ["title", "image_path", "image_prompt", "style"],
    "implications":         ["title", "bullets"],
    "qa_anticipated":       ["question", "answer_summary", "evidence_pointer"],
}


# ---------------------------------------------------------------------------
# Fragment validation
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FragmentIssue:
    slide_index: int | None
    layout: str | None
    field: str | None
    message: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def format(self) -> str:
        loc = []
        if self.slide_index is not None:
            loc.append(f"slide[{self.slide_index}]")
        if self.layout:
            loc.append(f"layout={self.layout}")
        if self.field:
            loc.append(f"field={self.field}")
        prefix = "/".join(loc) if loc else "fragment"
        return f"{prefix}: {self.message}"


def validate_fragment(data: dict) -> list[FragmentIssue]:
    """Validate a compose-fragment.v3 (or v2) shape against v2's
    per-layout required-fields schema. Returns a list of issues;
    empty list = valid.

    Catches both bug classes from the morning abort:
    - Class 1 (top-level shape): missing/non-list `slides[]`,
      missing `schema_version`, wrong schema_version value.
    - Class 2 (per-layout field names): missing required-by-layout
      fields per LAYOUT_REQUIRED_FIELDS.
    """
    issues: list[FragmentIssue] = []

    # --- Class 1: top-level shape ---
    if "schema_version" not in data:
        issues.append(FragmentIssue(
            None, None, "schema_version",
            "missing schema_version"))
    elif data["schema_version"] not in (
            "compose-fragment.v2", "compose-fragment.v3"):
        issues.append(FragmentIssue(
            None, None, "schema_version",
            f"unexpected schema_version: {data['schema_version']!r} "
            f"(expected compose-fragment.v2 or .v3)"))

    if "substory_id" not in data:
        issues.append(FragmentIssue(
            None, None, "substory_id", "missing substory_id"))

    if "slides" not in data:
        issues.append(FragmentIssue(
            None, None, "slides",
            "missing slides[] array (the morning-abort top-level "
            "shape bug — D-075). The merger expects flat slides[]; "
            "do NOT emit section_divider/content_slides as "
            "top-level keys."))
        return issues  # can't validate per-slide without slides[]
    if not isinstance(data["slides"], list):
        issues.append(FragmentIssue(
            None, None, "slides",
            "slides must be a list"))
        return issues
    if len(data["slides"]) == 0:
        issues.append(FragmentIssue(
            None, None, "slides", "slides[] is empty"))
        return issues

    # --- Class 2: per-slide layout+content required fields ---
    for i, slide in enumerate(data["slides"]):
        if not isinstance(slide, dict):
            issues.append(FragmentIssue(
                i, None, None, "slide is not a dict"))
            continue
        layout = slide.get("layout")
        if not layout:
            issues.append(FragmentIssue(
                i, None, "layout", "missing layout field"))
            continue
        content = slide.get("content")
        if not isinstance(content, dict):
            issues.append(FragmentIssue(
                i, layout, "content",
                "content is missing or not a dict"))
            continue
        required = LAYOUT_REQUIRED_FIELDS.get(layout)
        if required is None:
            issues.append(FragmentIssue(
                i, layout, None,
                f"unknown layout {layout!r} (not in v2 16-layout "
                f"vocabulary)"))
            continue
        for field in required:
            if field not in content:
                issues.append(FragmentIssue(
                    i, layout, field,
                    f"required field missing on {layout}"))
    return issues


# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------

def invoke_claude(system_prompt_path: Path, user_prompt: str,
                  expected_write_path: Path,
                  model: str = DEFAULT_MODEL,
                  tools: str = DEFAULT_TOOLS,
                  timeout_s: int = 600,
                  ) -> tuple[int, str, str]:
    """Invoke `claude -p` with the given system-prompt + user
    prompt. Mirrors `invoke_claude()` in presentation_maker.sh
    (line 718).

    Returns (rc, stdout, stderr). Does NOT pipe through
    stream_progress.py — the smoke is short enough that we don't
    need the parser overhead.

    Per orchestrator: CLAUDECODE= clears the env var that would
    otherwise make claude run as a "Claude Code" subagent (the
    orchestrator clears it so the child agent doesn't inherit
    parent-agent state).
    """
    if shutil.which("claude") is None:
        return 2, "", "claude CLI not on PATH"
    sys_prompt = system_prompt_path.read_text(encoding="utf-8")
    cmd = [
        "claude", "-p",
        "--model", model,
        "--system-prompt", sys_prompt,
        "--allowedTools", tools,
        "--dangerously-skip-permissions",
        user_prompt,
    ]
    env = {**os.environ, "CLAUDECODE": ""}
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            timeout=timeout_s, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        return 2, "", f"claude timed out after {timeout_s}s: {e}"
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Smoke execution
# ---------------------------------------------------------------------------

def run_smoke(fragment_only: bool, keep_tmpdir: bool,
              timeout_s: int = 600,
              ) -> tuple[bool, list[FragmentIssue], dict]:
    """Run the smoke. Returns (passed, issues, evidence-dict).

    fragment_only=True skips the substory_design stage and reuses
    the pre-canned fixture 02_substories.md. fragment_only=False
    runs both stages (~$0.60 vs ~$0.30).

    keep_tmpdir=True leaves the per-run temp dir around for
    inspection on failure.
    """
    if not FIXTURE_DIR.is_dir():
        raise FileNotFoundError(
            f"smoke fixture missing at {FIXTURE_DIR}")

    tmpdir = Path(tempfile.mkdtemp(prefix="smoke_v3_"))
    evidence: dict = {
        "tmpdir": str(tmpdir),
        "prompts_sha": compute_prompt_sha(),
        "fragment_only": fragment_only,
    }
    try:
        # Concat the v3 prompts inside the tmpdir (mirrors what
        # `build_v3_concat_prompts` does at orchestrator start).
        concat_dir = tmpdir / "_prompts"
        concat_dir.mkdir()
        slide_concat = concat_dir / "slide_compose.v3.concat.md"
        substory_concat = concat_dir / "substory_design.v3.concat.md"
        build_concat(SLIDE_V2, SLIDE_OVERLAY, slide_concat)
        build_concat(SUBSTORY_V1, SUBSTORY_OVERLAY, substory_concat)

        # Stage the fixture into tmpdir. The smoke composes against
        # a copy so the fixture stays read-only.
        smoke_dir = tmpdir / "smoke_project"
        shutil.copytree(FIXTURE_DIR, smoke_dir)

        # --- Stage 1: substory_design (optional) ---
        substories_path = smoke_dir / "narrative" / "02_substories.md"
        if not fragment_only:
            substory_out = smoke_dir / "narrative" / "02_substories.smoke.md"
            user_prompt = (
                f"You are composing the substory list for a SMOKE TEST.\n"
                f"Read the throughline at: "
                f"{smoke_dir}/narrative/00_throughline.md\n"
                f"Read the plan at: {smoke_dir}/working/00_plan.md\n"
                f"Read REPORT.md at: {smoke_dir}/REPORT.md\n"
                f"Project ID: smoke_v3_fixture; mode: talk-15; "
                f"tier: STRONG.\n"
                f"Produce exactly ONE substory (the smoke fixture is "
                f"minimal — there's only one finding cluster).\n"
                f"Write the output via the Write tool to:\n"
                f"  {substory_out}\n"
                f"Follow the v3 contract: Question + (Conclusion for "
                f"next substory omitted for the final/only substory) "
                f"+ Punchline + analyses + cluster rationale + slide "
                f"budget."
            )
            rc, _, stderr = invoke_claude(
                substory_concat, user_prompt, substory_out,
                timeout_s=timeout_s)
            evidence["substory_design_rc"] = rc
            evidence["substory_design_stderr"] = stderr[-2000:]
            if rc != 0 or not substory_out.is_file():
                return False, [FragmentIssue(
                    None, None, None,
                    f"substory_design step failed rc={rc}; "
                    f"stderr (last 2000):\n{stderr[-2000:]}")], evidence
            substories_path = substory_out

        evidence["substories_path"] = str(substories_path)

        # --- Stage 2: slide_compose ---
        fragment_out = (smoke_dir / "working" / "03_slides"
                        / "S1_slides.smoke.json")
        user_prompt = (
            f"OUT_PATH={fragment_out}\n"
            f"PROJECT_DIR={smoke_dir}\n"
            f"SUBSTORY_PATH={substories_path}\n"
            f"SUBSTORY_ID=S1\n"
            f"THROUGHLINE_PATH={smoke_dir}/narrative/00_throughline.md\n"
            f"PLAN_PATH={smoke_dir}/working/00_plan.md\n"
            f"CURATED_FIGURES_PATH=\n"
            f"CITATION_POOL_PATH={smoke_dir}/working/citation_pool.json\n"
            f"MODE=talk-15\n"
            f"TIER=STRONG\n"
            f"PRIOR_SUBSTORY_OUTPUTS=\n"
            f"SUBSTORY_QUESTION=Which of the three reproducible "
            f"clusters carries the biomarker-X enrichment that "
            f"motivates follow-up?\n"
            f"SUBSTORY_CONCLUSION=\n"
            f"ALLOWLIST_TERMS=\n"
            f"\n"
            f"Run the slide_compose stage for substory S1 of the "
            f"smoke fixture. The substory's punchline + analyses "
            f"are in SUBSTORY_PATH. Read REPORT.md sections cited "
            f"by the analyses; emit 3-5 content slides (no images; "
            f"figures may not exist). Write the result via the "
            f"Write tool to OUT_PATH."
        )
        rc, _, stderr = invoke_claude(
            slide_concat, user_prompt, fragment_out,
            timeout_s=timeout_s)
        evidence["slide_compose_rc"] = rc
        evidence["slide_compose_stderr"] = stderr[-2000:]
        evidence["fragment_path"] = str(fragment_out)
        if rc != 0 or not fragment_out.is_file():
            return False, [FragmentIssue(
                None, None, None,
                f"slide_compose step failed rc={rc}; "
                f"stderr (last 2000):\n{stderr[-2000:]}")], evidence

        # --- Validate ---
        try:
            fragment = json.loads(
                fragment_out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return False, [FragmentIssue(
                None, None, None,
                f"fragment is not valid JSON: {e}")], evidence
        evidence["fragment"] = fragment
        issues = validate_fragment(fragment)
        return len(issues) == 0, issues, evidence
    finally:
        if not keep_tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Record I/O
# ---------------------------------------------------------------------------

def write_record(path: Path, passed: bool, issues: list[FragmentIssue],
                 evidence: dict) -> None:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "v3_smoke.v1",
        "passed": passed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts_sha": evidence.get("prompts_sha"),
        "fragment_only": evidence.get("fragment_only", False),
        "issues": [i.to_dict() for i in issues],
        "evidence": evidence,
    }
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def check_recent_pass(now: datetime | None = None,
                      record_path: Path = PASS_RECORD,
                      current_sha: str | None = None,
                      ) -> tuple[bool, str]:
    """Gate-check helper. Returns (gate_ok, reason).

    gate_ok=True iff:
      1. PASS_RECORD exists + parses,
      2. its prompts_sha matches the current source files,
      3. its timestamp is within SMOKE_FRESHNESS_DAYS.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not record_path.is_file():
        return False, (
            f"no v3 smoke-pass record at {record_path} — run "
            f"`tools/smoke_v3_prompt.py` first (~$0.60).")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"pass record at {record_path} unreadable: {e}"
    if not record.get("passed"):
        return False, "pass record exists but passed=false"
    rec_sha = record.get("prompts_sha", "")
    if current_sha is None:
        try:
            current_sha = compute_prompt_sha()
        except FileNotFoundError as e:
            return False, f"cannot compute current prompt sha: {e}"
    if rec_sha != current_sha:
        return False, (
            f"prompts_sha mismatch: record={rec_sha[:12]}.., "
            f"current={current_sha[:12]}..  Prompts changed since "
            f"last smoke pass; re-run smoke.")
    try:
        ts = datetime.fromisoformat(record["timestamp"])
    except (KeyError, ValueError) as e:
        return False, f"pass record timestamp unparseable: {e}"
    age = now - ts
    if age > timedelta(days=SMOKE_FRESHNESS_DAYS):
        return False, (
            f"pass record is {age.days} days old (max "
            f"{SMOKE_FRESHNESS_DAYS}); re-run smoke.")
    return True, (
        f"pass record ok (age {age.days}d, sha {rec_sha[:12]}..)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="smoke_v3_prompt.py",
        description=(
            "Live-LLM smoke for the v3 concatenated prompts. "
            "Composes one substory fragment, validates against "
            "v2 layout schema, writes a pass/fail record under "
            "$SKILL_REPO/audit/."),
    )
    ap.add_argument(
        "--fragment-only", action="store_true",
        help="Skip the substory_design stage; reuse the pre-canned "
             "fixture 02_substories.md. Halves cost (~$0.30 vs ~$0.60) "
             "but skips one bug class.")
    ap.add_argument(
        "--keep-tmpdir", action="store_true",
        help="Leave the per-run temp dir around for inspection.")
    ap.add_argument(
        "--timeout-s", type=int, default=600,
        help="Per-stage timeout in seconds (default: 600).")
    ap.add_argument(
        "--check-recent", action="store_true",
        help="Gate-check only; do NOT invoke the LLM. Returns rc=0 "
             "if a fresh pass record exists, rc=1 otherwise.")
    args = ap.parse_args(argv)

    if args.check_recent:
        # Resolve PASS_RECORD via globals() so monkeypatch at test
        # time is honored (a direct `PASS_RECORD` ref would bind to
        # the module-load-time constant). Works whether the script
        # is invoked standalone (`python smoke_v3_prompt.py`) or
        # via the installed package.
        ok, reason = check_recent_pass(
            record_path=globals()["PASS_RECORD"])
        print(reason, file=sys.stderr)
        return 0 if ok else 1

    print(f"[smoke_v3] starting; fragment_only={args.fragment_only}",
          file=sys.stderr)
    try:
        passed, issues, evidence = run_smoke(
            fragment_only=args.fragment_only,
            keep_tmpdir=args.keep_tmpdir,
            timeout_s=args.timeout_s)
    except FileNotFoundError as e:
        print(f"[smoke_v3] setup error: {e}", file=sys.stderr)
        return 2

    if passed:
        write_record(PASS_RECORD, True, issues, evidence)
        # Remove any stale fail record (next gate-check would
        # otherwise read it instead of the new pass).
        if FAIL_RECORD.exists():
            FAIL_RECORD.unlink()
        print(f"[smoke_v3] PASS — wrote {PASS_RECORD}", file=sys.stderr)
        return 0
    else:
        write_record(FAIL_RECORD, False, issues, evidence)
        print(f"[smoke_v3] FAIL — {len(issues)} issue(s):", file=sys.stderr)
        for issue in issues:
            print(f"  {issue.format()}", file=sys.stderr)
        print(f"[smoke_v3] wrote {FAIL_RECORD}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
