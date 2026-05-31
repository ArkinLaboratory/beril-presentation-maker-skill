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
#
# v0.8 Tier-G fix: auto-detect dev vs install layout. The script
# ships in TWO contexts with different on-disk shapes:
#
#   DEV LAYOUT:
#     <repo_root>/
#       src/beril_presentation_maker/skill/tools/smoke_v3_prompt.py
#       src/beril_presentation_maker/skill/prompts/*.md
#       tests/fixtures/smoke_v3/
#       audit/   (← pass record lands here)
#
#   INSTALLED LAYOUT (after `install-skill .`):
#     <beril_root>/.claude/skills/beril-presentation-maker/
#       tools/smoke_v3_prompt.py
#       prompts/*.md
#       audit/   (← pass record SHOULD land here)
#       (no tests/fixtures — `install-skill` doesn't ship them;
#        smoke can only run from the dev repo today, v0.8.1 fix
#        will ship fixtures via `_SHIPPED_SUBDIRS`)
#
# Auto-detection: walk up from __file__ until we find a directory
# containing either `src/beril_presentation_maker/skill/` (dev) OR
# `SKILL.md` (installed-skill root + dev-skill root both have this).
# Then resolve PROMPTS_DIR, FIXTURE_DIR, SMOKE_DIR relative to that.
# Falls back to the legacy parents[4] dev-layout assumption if no
# marker is found (preserves existing test-suite behavior in the
# dev repo).


def _resolve_skill_repo_root(start: Path) -> tuple[Path, str]:
    """Walk upward from `start` looking for a layout marker that
    identifies whether we're in the DEV layout or the INSTALLED
    layout. Returns (repo_root, layout_label).

    Detection rules (first match wins):
      1. If we find a parent dir containing
         `src/beril_presentation_maker/skill/tools/`, that's the
         DEV repo root. Layout = "dev".
      2. If we find a parent dir whose name is the installed-skill
         dir (`beril-presentation-maker`) AND contains a `tools/`
         subdir AND a sibling `audit/` IS allowed, that's the
         INSTALLED layout. The skill dir itself IS the root.
         Layout = "installed".
      3. Fallback: parents[4] of start (the legacy dev-layout
         assumption). Layout = "fallback".
    """
    # Rule 1: dev layout — look upward for src/...skill/tools/
    for ancestor in [start, *start.parents]:
        candidate_skill = (ancestor / "src" / "beril_presentation_maker"
                           / "skill" / "tools")
        if candidate_skill.is_dir():
            return ancestor, "dev"
    # Rule 2: installed layout — the script's parents[1] is the
    # skill dir itself (.../tools/smoke_v3_prompt.py → parents[1] is
    # .../beril-presentation-maker/). Detect via name + tools/ sibling.
    if (len(start.parents) >= 2
            and start.parents[0].name == "tools"
            and start.parents[1].name == "beril-presentation-maker"):
        return start.parents[1], "installed"
    # Rule 3: fallback to legacy parents[4]
    return start.parents[4], "fallback"


_SCRIPT_PATH = Path(__file__).resolve()
SKILL_REPO_ROOT, _LAYOUT = _resolve_skill_repo_root(_SCRIPT_PATH)


def _resolve_prompts_dir(root: Path, layout: str) -> Path:
    """PROMPTS_DIR location depends on layout. Dev: nested under
    src/...skill/prompts/. Installed: prompts/ is direct child of
    the skill dir."""
    if layout == "installed":
        return root / "prompts"
    return root / "src" / "beril_presentation_maker" / "skill" / "prompts"


def _resolve_fixture_dir(root: Path, layout: str) -> Path:
    """Fixtures live under tests/fixtures/ in dev. Not shipped in
    install today (v0.8.1 fix). For installed layout we return the
    expected path — the smoke will fail loudly with a clear error
    pointing operators to run from the dev repo until v0.8.1."""
    if layout == "installed":
        return root / "tests" / "fixtures" / "smoke_v3"
    return root / "tests" / "fixtures" / "smoke_v3"


SMOKE_DIR = SKILL_REPO_ROOT / "audit"
PASS_RECORD = SMOKE_DIR / "v3_smoke_pass.json"
FAIL_RECORD = SMOKE_DIR / "v3_smoke_fail.json"

# Fixture location.
FIXTURE_DIR = _resolve_fixture_dir(SKILL_REPO_ROOT, _LAYOUT)

# Prompt sources (the v1/v2 body + v3 overlay files that get
# concatenated). Mirrors `build_v3_concat_prompts` in
# `presentation_maker.sh`.
PROMPTS_DIR = _resolve_prompts_dir(SKILL_REPO_ROOT, _LAYOUT)
SLIDE_V2 = PROMPTS_DIR / "slide_compose.v2.md"
SLIDE_OVERLAY = PROMPTS_DIR / "slide_compose.v3_overlay.md"
SUBSTORY_V1 = PROMPTS_DIR / "substory_design.v1.md"
SUBSTORY_OVERLAY = PROMPTS_DIR / "substory_design.v3_overlay.md"
# v0.6/D-080: v3.1 overlay stacks on the v3 chain. We include it in
# the prompt-sha computation so a v3.1 invocation requires a fresh
# smoke that validated the stacked concat — a v3-only pass record
# would otherwise satisfy the gate erroneously. Tier C will extend
# the smoke runner to actually compose against the v3.1 stack;
# until then, including this file in the sha invalidates any v3
# pass record and forces a re-smoke that exercises both versions'
# overlays.
SLIDE_OVERLAY_V3_1 = PROMPTS_DIR / "slide_compose.v3.1_overlay.md"

# v0.7/D-085 + D-086 + D-087: v3.2 overlays stack on the v3.1 chain
# (slide_compose) + on the v3 chain (substory_design). v3.2 introduces
# three contracts:
#   D-085 — figure-relevance rule (no budgeting; use every relevant
#           curated figure)
#   D-086 — deck_close composer authoring rule (consumed in v3.2
#           overlay; the deck_close slide itself is produced by
#           the dedicated deck_close.v1.md agent in Tier C.3)
#   D-087 — `Transition from prior:` field emission in
#           substory_design (cross-substory arc-bridge data)
# Including both v3.2 overlays in the prompt-sha forces a re-smoke
# on any v3.2 invocation when a v3 or v3.1 pass record exists —
# matching the v0.6 sha-invalidation discipline.
SLIDE_OVERLAY_V3_2 = PROMPTS_DIR / "slide_compose.v3.2_overlay.md"
SUBSTORY_OVERLAY_V3_2 = PROMPTS_DIR / "substory_design.v3.2_overlay.md"

# v0.8/D-095: v3.3 substory_design is a CLEAN overlay on v1 (NOT
# stacked on v3 or v3.2). Designed to fix the v3.2 prompt-layering
# recency-bias field-drop bug live-discovered at v0.7 Tier G.
# Consolidates v3 Q/A/R/C + v3.2 transition_from_prior into ONE
# unified template with explicit "v3.3 supersedes" mitigation.
# slide_compose stack UNCHANGED from v3.2 per D-095 scope.
# Including the v3.3 overlay in the prompt-sha forces a re-smoke
# when a v3.x earlier pass record exists + a v3.3 invocation is
# attempted (same sha-invalidation discipline as prior versions).
SUBSTORY_OVERLAY_V3_3 = PROMPTS_DIR / "substory_design.v3.3_overlay.md"


# ---------------------------------------------------------------------------
# Prompt-body sha
# ---------------------------------------------------------------------------

def compute_prompt_sha() -> str:
    """SHA-256 of all prompt source files (v1/v2 + v3/v3.1/v3.2/v3.3
    overlays for both substory_design and slide_compose). Captures
    the exact prompt content the smoke validated against. Used by
    the orchestrator's gate-check to detect prompt drift after a
    pass.

    Order: substory_v1, substory_overlay (v3), substory_overlay_v3.2,
    substory_overlay_v3.3, slide_v2, slide_overlay (v3),
    slide_overlay_v3.1, slide_overlay_v3.2 — alphabetical-by-stage +
    within-stage-by-version for stability.

    v0.7/D-085 et al.: including later overlays in the sha forces a
    re-smoke when an earlier pass record exists and a later-version
    invocation is attempted. Same sha-invalidation discipline as
    v0.6 used for v3.1.

    v0.8/D-095: v3.3 substory_design overlay added to sha source
    list. A v3.2 pass record will sha-invalidate on a v3.3
    invocation, forcing operators to re-run smoke for the v3.3
    contract.
    """
    h = hashlib.sha256()
    for path in (SUBSTORY_V1, SUBSTORY_OVERLAY, SUBSTORY_OVERLAY_V3_2,
                 SUBSTORY_OVERLAY_V3_3,
                 SLIDE_V2, SLIDE_OVERLAY, SLIDE_OVERLAY_V3_1,
                 SLIDE_OVERLAY_V3_2):
        if not path.is_file():
            raise FileNotFoundError(
                f"prompt source missing: {path}; cannot compute sha")
        h.update(path.read_bytes())
        h.update(b"\n--sep--\n")  # explicit separator
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Concat prompt builder (mirrors orchestrator's build_v3_concat_prompts)
# ---------------------------------------------------------------------------

def build_concat(*sources: Path, out: Path) -> None:
    """Write `cat <sources...>` to `out`. Mirrors the orchestrator's
    `build_v3_concat_prompts` for the smoke. Variadic so v3 = (v2,
    overlay_v3) and v3.1 = (v2, overlay_v3, overlay_v3.1)."""
    body = b""
    for src in sources:
        body += src.read_bytes()
    out.write_bytes(body)


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
# v0.8/D-095 — substory_design field-presence validator
# ---------------------------------------------------------------------------
#
# The v3.2 substory_design overlay had a recency-bias displacement
# bug: live ibd v0.7 runs produced 4-substory output with ZERO
# Conclusion-for-next-substory + ZERO Transition-from-prior fields,
# despite both contracts being in the concatenated prompt. The unit
# suite couldn't catch this — it's emergent LLM behavior the static
# tests don't see.
#
# v3.3 fixes the prompt structurally (clean overlay on v1
# consolidating the contracts). This validator is the smoke-time
# backstop: it parses the produced `02_substories.md` markdown and
# asserts the required fields appear per substory, per the
# field-requirements table in substory_design.v3.3_overlay.md:
#
#   - Every substory: **Question:** present
#   - Non-final substories: **Conclusion for next substory:** present
#   - Non-first substories: **Transition from prior:** present
#
# If any required field is absent on a substory where it applies,
# the smoke FAILS. The orchestrator's D-076 gate refuses the v3.3
# invocation until a fresh smoke pass is recorded.


def validate_substory_design_fields(
    substories_md_text: str,
) -> list[FragmentIssue]:
    """Validate that substory_design output (parsed from
    02_substories.md markdown) contains v3.3 required fields per
    substory.

    Per substory_design.v3.3_overlay.md field-requirements table:
      - All substories: **Question:** required
      - Non-final substories: **Conclusion for next substory:**
        required
      - Non-first substories: **Transition from prior:** required

    Returns list of FragmentIssue per ISSUE found. Empty list means
    all substories satisfy the v3.3 contract.

    Severity strategy (post-v0.8-Tier-G live discovery):

    HARD fails (returned in the issues list; these fail the smoke):
      - Missing **Question:** on any substory
      - Missing **Conclusion for next substory:** on a non-final
        substory (this is THE load-bearing v3.2 bug class D-095
        was designed to catch)
      - Missing **Transition from prior:** on a non-first substory
      - Empty or unparseable substory_md

    SOFT advisories (printed to stderr; do NOT fail the smoke):
      - **Conclusion for next substory:** present on the FINAL
        substory (LLM was over-zealous; harmless wart, not a
        content bug)
      - **Transition from prior:** present on the FIRST substory
        (same class of over-zealous)

    Rationale for the soft-advisory split: v0.8 Tier-G live smoke
    on the single-substory fixture caught the LLM emitting
    Conclusion-for-next on the only substory (which is both first
    AND final), even though the user_prompt explicitly said to omit
    both. The v3.3 system-prompt template overrides the
    user_prompt's exception language. Production decks have 3-5
    substories where the edge cases don't apply; a slightly
    over-zealous LLM on the deck-end is a wart, not a bug. The
    load-bearing assertion (the missing-on-required case) is what
    D-095 is for; that stays a hard fail.
    """
    import re as _re
    issues: list[FragmentIssue] = []

    if not substories_md_text:
        issues.append(FragmentIssue(
            None, None, "substories_md",
            "substories markdown is empty — substory_design stage "
            "produced no output"))
        return issues

    # Find all substory headers (### S1, ### S2, etc.). Each
    # header marks the start of a substory's field block.
    header_pattern = _re.compile(
        r"^###\s+(S\d+)\s*[—\-]", _re.MULTILINE)
    headers = list(header_pattern.finditer(substories_md_text))

    if not headers:
        issues.append(FragmentIssue(
            None, None, "substory_headers",
            "no ### S{N} substory headers found in output — "
            "substory_design stage produced malformed markdown"))
        return issues

    n_substories = len(headers)
    for i, header in enumerate(headers):
        sid = header.group(1)
        is_first = (i == 0)
        is_final = (i == n_substories - 1)
        # Slice this substory's block: from this header to the
        # next header (or end of text on the final substory).
        start = header.end()
        end = headers[i + 1].start() if i + 1 < n_substories \
            else len(substories_md_text)
        block = substories_md_text[start:end]

        # Required on ALL substories: Question
        if "**Question:**" not in block:
            issues.append(FragmentIssue(
                None, None, "Question",
                f"{sid}: missing v3.3 **Question:** field "
                f"(required on every substory)"))

        # Required on non-final substories: Conclusion for next
        if not is_final:
            if "**Conclusion for next substory:**" not in block:
                issues.append(FragmentIssue(
                    None, None, "Conclusion for next substory",
                    f"{sid}: missing v3.3 **Conclusion for next "
                    f"substory:** field (required on non-final "
                    f"substories; this is the load-bearing v3.2 "
                    f"bug class v3.3 was designed to prevent)"))
        else:
            # Final substory SHOULD NOT have Conclusion for next
            # (no next substory to hand off to). v0.8 Tier-G live
            # smoke discovery: the LLM tends to emit it anyway when
            # the template makes it look required. Demoted to
            # advisory: printed to stderr, doesn't fail smoke.
            if "**Conclusion for next substory:**" in block:
                print(
                    f"[smoke advisory] {sid}: **Conclusion for "
                    f"next substory:** present on FINAL substory; "
                    f"omit when no next exists (over-zealous LLM "
                    f"on deck-end; harmless wart, not a content "
                    f"bug — v0.8 Tier-G discovery)",
                    file=sys.stderr,
                )

        # Required on non-first substories: Transition from prior
        if not is_first:
            if "**Transition from prior:**" not in block:
                issues.append(FragmentIssue(
                    None, None, "Transition from prior",
                    f"{sid}: missing v3.3 **Transition from "
                    f"prior:** field (required on non-first "
                    f"substories; this is the other v3.2 bug "
                    f"class v3.3 was designed to prevent)"))
        else:
            # S1 SHOULD NOT have Transition from prior. Same
            # advisory-demotion rationale as Conclusion-on-final
            # above.
            if "**Transition from prior:**" in block:
                print(
                    f"[smoke advisory] {sid}: **Transition from "
                    f"prior:** present on FIRST substory; omit "
                    f"when no prior exists (over-zealous LLM on "
                    f"deck-start; harmless wart, not a content "
                    f"bug — v0.8 Tier-G discovery)",
                    file=sys.stderr,
                )

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
              version: str = "v3.3",
              ) -> tuple[bool, list[FragmentIssue], dict]:
    """Run the smoke. Returns (passed, issues, evidence-dict).

    fragment_only=True skips the substory_design stage and reuses
    the pre-canned fixture 02_substories.md. fragment_only=False
    runs both stages (~$0.60 vs ~$0.30).

    keep_tmpdir=True leaves the per-run temp dir around for
    inspection on failure.

    version: "v3", "v3.1", "v3.2", or "v3.3". Selects the stacked
    concat the smoke composes against. Default "v3.3" (v0.8 —
    validates: slide_compose stack UNCHANGED from v3.2 (v2 + v3 +
    v3.1 + v3.2 overlays); substory_design is the CLEAN v3.3
    overlay on v1 (NOT stacked on v3 or v3.2, per D-095 — fixes
    the v3.2 recency-bias displacement bug). Use "v3", "v3.1", or
    "v3.2" explicitly to regression-check earlier contracts in
    isolation.

    When version="v3.3" and not fragment_only, an extra
    validate_substory_design_fields() pass runs on the produced
    02_substories.md to assert Question / Conclusion-for-next /
    Transition-from-prior fields appear per substory — the
    load-bearing piece that would have caught the v3.2 field-drop
    bug live (per D-095).
    """
    if version not in ("v3", "v3.1", "v3.2", "v3.3"):
        raise ValueError(
            f"version must be 'v3', 'v3.1', 'v3.2', or 'v3.3'; "
            f"got: {version!r}")
    if not FIXTURE_DIR.is_dir():
        raise FileNotFoundError(
            f"smoke fixture missing at {FIXTURE_DIR}")

    tmpdir = Path(tempfile.mkdtemp(prefix=f"smoke_{version}_"))
    evidence: dict = {
        "tmpdir": str(tmpdir),
        "prompts_sha": compute_prompt_sha(),
        "fragment_only": fragment_only,
        "version": version,
    }
    try:
        # Concat the prompts inside the tmpdir (mirrors what
        # `build_v3_concat_prompts` does at orchestrator start).
        #
        # slide_compose stacking (v3.3 keeps the v3.2 stack — D-095
        # scopes v3.3 to substory_design only):
        #   v3:   cat v2.md + v3_overlay.md
        #   v3.1: cat v2.md + v3_overlay.md + v3.1_overlay.md
        #   v3.2: cat v2.md + v3_overlay.md + v3.1_overlay.md
        #               + v3.2_overlay.md
        #   v3.3: SAME as v3.2 (slide_compose UNCHANGED)
        #
        # substory_design stacking (v3.3 BREAKS the chain — clean
        # overlay on v1, per D-095, to fix v3.2 field-drop bug):
        #   v3:   cat v1.md + v3_overlay.md
        #   v3.1: cat v1.md + v3_overlay.md (unchanged from v3)
        #   v3.2: cat v1.md + v3_overlay.md + v3.2_overlay.md
        #   v3.3: cat v1.md + v3.3_overlay.md (CLEAN; NOT stacked)
        concat_dir = tmpdir / "_prompts"
        concat_dir.mkdir()
        # slide_compose: v3.3 reuses v3.2's concat (same stack).
        slide_concat_version = "v3.2" if version == "v3.3" else version
        slide_concat = (
            concat_dir / f"slide_compose.{slide_concat_version}.concat.md")
        slide_sources = [SLIDE_V2, SLIDE_OVERLAY]
        if version in ("v3.1", "v3.2", "v3.3"):
            slide_sources.append(SLIDE_OVERLAY_V3_1)
        if version in ("v3.2", "v3.3"):
            slide_sources.append(SLIDE_OVERLAY_V3_2)
        build_concat(*slide_sources, out=slide_concat)
        # substory_design: v3 + v3.1 share the v1+v3 chain; v3.2
        # stacks the new substory overlay (D-087's
        # transition_from_prior field); v3.3 BREAKS the chain — it
        # is a clean v1+v3.3_overlay concat (NOT stacked on v3 or
        # v3.2), per D-095. Distinct concat path per version so
        # each isolates cleanly.
        if version == "v3.3":
            substory_concat_name = "substory_design.v3.3.concat.md"
        elif version == "v3.2":
            substory_concat_name = "substory_design.v3.2.concat.md"
        else:
            substory_concat_name = "substory_design.v3.concat.md"
        substory_concat = concat_dir / substory_concat_name
        if version == "v3.3":
            # CLEAN overlay: v1 + v3.3 ONLY. No v3 or v3.2 overlay
            # in the chain — that's the whole point of D-095.
            substory_sources = [SUBSTORY_V1, SUBSTORY_OVERLAY_V3_3]
        else:
            substory_sources = [SUBSTORY_V1, SUBSTORY_OVERLAY]
            if version == "v3.2":
                substory_sources.append(SUBSTORY_OVERLAY_V3_2)
        build_concat(*substory_sources, out=substory_concat)

        # Stage the fixture into tmpdir. The smoke composes against
        # a copy so the fixture stays read-only.
        smoke_dir = tmpdir / "smoke_project"
        shutil.copytree(FIXTURE_DIR, smoke_dir)

        # --- Stage 1: substory_design (optional) ---
        substories_path = smoke_dir / "narrative" / "02_substories.md"
        if not fragment_only:
            substory_out = smoke_dir / "narrative" / "02_substories.smoke.md"
            # Single-substory smoke: the fixture has one finding
            # cluster, so the produced output is ONE substory only.
            # This means Conclusion-for-next + Transition-from-prior
            # are BOTH omitted (final and first apply on the only
            # substory). validate_substory_design_fields() handles
            # that case — it only checks fields where they apply.
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
                f"Follow the contract in the system prompt: Question "
                f"(required on every substory) + Punchline + "
                f"analyses + cluster rationale + slide budget. "
                f"Conclusion-for-next-substory and "
                f"Transition-from-prior are BOTH omitted on this "
                f"single-substory smoke (no next; no prior)."
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

        # --- v0.8/D-095: substory_design field-presence check ---
        # Only meaningful on v3.3 (the version designed to fix the
        # v3.2 field-drop bug). On v3/v3.1 the produced output may
        # legitimately omit these fields (they weren't required by
        # those contracts). Skip on fragment_only — there's no
        # produced substory_design output to validate; the fixture
        # is canned and known-good.
        if version == "v3.3" and not fragment_only:
            substory_text = substories_path.read_text(encoding="utf-8")
            sd_issues = validate_substory_design_fields(substory_text)
            evidence["substory_design_field_issues"] = [
                i.to_dict() for i in sd_issues]
            if sd_issues:
                return False, sd_issues, evidence

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
    ap.add_argument(
        "--version", choices=["v3", "v3.1", "v3.2", "v3.3"],
        default="v3.3",
        help="Which stacked concat to compose against. "
             "v3 = cat v2.md + v3_overlay.md. "
             "v3.1 = cat v2.md + v3_overlay.md + v3.1_overlay.md. "
             "v3.2 (v0.7) = cat v2.md + v3_overlay.md + "
             "v3.1_overlay.md + v3.2_overlay.md (slide_compose); "
             "+ cat substory_design v1 + v3_overlay + v3.2_overlay "
             "(substory_design). "
             "v3.3 (default; v0.8) = slide_compose stack UNCHANGED "
             "from v3.2; substory_design is CLEAN v1 + "
             "v3.3_overlay (NOT stacked on v3 or v3.2 — D-095 "
             "fixes the v3.2 recency-bias field-drop bug). v3.3 "
             "additionally runs validate_substory_design_fields() "
             "on the produced 02_substories.md output.")
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

    print(f"[smoke_{args.version}] starting; "
          f"fragment_only={args.fragment_only}; version={args.version}",
          file=sys.stderr)
    try:
        passed, issues, evidence = run_smoke(
            fragment_only=args.fragment_only,
            keep_tmpdir=args.keep_tmpdir,
            timeout_s=args.timeout_s,
            version=args.version)
    except (FileNotFoundError, ValueError) as e:
        print(f"[smoke_{args.version}] setup error: {e}",
              file=sys.stderr)
        return 2

    if passed:
        write_record(PASS_RECORD, True, issues, evidence)
        # Remove any stale fail record (next gate-check would
        # otherwise read it instead of the new pass).
        if FAIL_RECORD.exists():
            FAIL_RECORD.unlink()
        print(f"[smoke_{args.version}] PASS — wrote {PASS_RECORD}",
              file=sys.stderr)
        return 0
    else:
        write_record(FAIL_RECORD, False, issues, evidence)
        print(f"[smoke_{args.version}] FAIL — {len(issues)} issue(s):",
              file=sys.stderr)
        for issue in issues:
            print(f"  {issue.format()}", file=sys.stderr)
        print(f"[smoke_{args.version}] wrote {FAIL_RECORD}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
