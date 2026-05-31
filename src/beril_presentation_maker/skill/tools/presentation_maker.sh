#!/usr/bin/env bash
# presentation_maker.sh — production orchestrator for the
# beril-presentation-maker drafting pipeline.
#
# Drives the staged flow. v0.3.x default:
#   plan → throughline → substory_design → curate_figures →
#   citation_pool → cross_tenant → intro → slide_compose →
#   qa_prep → speaker_notes → image_gen → merge_and_assemble →
#   adversarial_review → revise_slides
# v0.4 (--architecture-pipeline v0_4, M3): the Phase-0 producers run
# BEFORE the deck-clustering call so deck_outline sees its inputs —
#   plan → throughline → phase0_tooling → curate_figures →
#   citation_pool → cross_tenant → deck_outline → intro → … (rest as above)
#
# Each stage invokes a `claude -p` subagent against a per-stage
# system prompt under prompts/<stage>.v1.md. Output is piped through
# stream_progress.py for Write verification + cost accounting unless
# `--no-stream` is set. State is on-disk in the draft_dir (no
# centralized state.json yet — the orchestrator is canonical).
#
# Forked structurally from beril-adversarial v0.1.x adversarial_review.sh
# (claude -p invocation pattern, stream_progress.py piping, retry on
# rc=2). The 14-stage flow with one interactive gate (throughline-pick,
# unless --auto-advance is set) is the production shape; the original
# v0.1.0 "smoke" framing is now obsolete (kept the filename until v0.2.0
# rename for git-history continuity).
#
# Deferred to v0.3+: review-rewrite loop with beril-adversarial,
# ai_image_prompt staging.
#
# Usage:
#   presentation_maker.sh <project_id> [options]
#
# Options:
#   --beril-root <path>      BERIL repository root (default: auto-detect)
#   --mode <mode>            talk-30 | talk-15 | talk-45 | lightning-5
#                            (default: talk-30; posters not supported in
#                            smoke v1)
#   --tier <tier>            STRONG | THIN | EXPLORATORY (default: STRONG)
#   --audience peer          (only peer supported in v1)
#   --auto-advance           Skip interactive gates: pick TL1 throughline,
#                            escalate-mode on overflow. Use for unattended
#                            smoke runs against known-shape projects.
#   --skip-assembly          Stop after fragment merge; do not run
#                            assemble_pptx.py.
#   --model <model>          Override claude model (default: sonnet)
#   --no-stream              Disable stream-json parser pipe (loses
#                            programmatic Write verification + cost summary)
#   --resume-from <stage>    Skip earlier stages; reuse their on-disk artifacts
#                            in --draft-dir. Stages in order:
#                              plan | throughline | substory_design |
#                              intro | slide_compose | image_gen | merge
#                            Cost savings on prompt-iteration:
#                              from intro:         ~$1.50 (saves plan+throughline+substory)
#                              from slide_compose: ~$1.20 (saves plan+throughline+substory+intro)
#                              from image_gen:     re-run image generation only
#                              from merge:         FREE (no LLM; assembly only)
#                            Requires --draft-dir.
#   --draft-dir <path>       Existing draft_N directory to resume into.
#                            Required when --resume-from is set.
#   --architecture-pipeline <p>  v0_3 (default) | v0_4. v0_4 (M2-lite +
#                            M3) runs phase0_tooling, then the Phase-0
#                            producers (curate_figures / citation_pool /
#                            cross_tenant), then deck_outline — so the
#                            outline call sees its inputs. v0_3 runs
#                            substory_design at the clustering slot
#                            (V0_4_ARCHITECTURE.md §20; M3_PUNCH_LIST.md).
#   --no-images              Skip image_gen stage entirely (v0.3.3).
#   --auto-approve-images    Bypass per-slide approval gate for image_gen
#                            (CI / power users). Cost cap still enforced.
#   --image-allow-exploratory
#                            Allow concept_illustration on EXPLORATORY tier
#                            (default: skipped per architecture R6).
#   --max-image-cost-usd <n> Cumulative image-gen cap in USD (default: 0.50,
#                            ~30 images at $0.014 / gemini-3-pro-image).
#   --max-image-approvals <n> v0.7/D-088: per-deck approval count cap.
#                            Default 4 (~2 big_idea opens + ~2 claim_evidence
#                            multi-panel diagrams). Separate from the dollar
#                            cap; whichever trips first short-circuits the
#                            rest of the per-slide loop. Set to 0 to disable
#                            (cost cap still bounds spend).
#   --image-style <style>    Force style override across all images this run
#                            (e.g., scientific_illustration / metaphor).
#   --image-provider <p>     Force image-gen provider (M5b/D-062):
#                            cborg | google_ai_studio. Default: precedence —
#                            GOOGLE_AI_STUDIO_API_KEY env present → AI Studio;
#                            else CBORG_API_KEY → CBORG; else fail.
#   --prompts-version <v>    v1 | v2 | v3 | v3.1 | v3.2 | v3.3. Default: v2. Selects
#                            prompt files for substory_design + slide_compose:
#                              v1 → substory_design.v1.md + slide_compose.v1.md
#                                   (v0.3.x; pre-M3 sequential composer)
#                              v2 → substory_design.v1.md + slide_compose.v2.md
#                                   (v0.4 M3 parallel-compose + fused notes)
#                              v3 → substory_design.v1.md ++ substory_design.v3_overlay.md
#                                   slide_compose.v2.md ++ slide_compose.v3_overlay.md
#                                   (v0.5 D-071/D-072 Q/A/R/C contract +
#                                   register-discipline-aware composer;
#                                   v3 prompts are built at orchestrator start
#                                   as cat-concatenated v1/v2 body + v3
#                                   overlay per D-075 + D-078).
#                              v3.1 → substory_design.v3 (unchanged) +
#                                   slide_compose.v2.md ++ slide_compose.v3_overlay.md
#                                   ++ slide_compose.v3.1_overlay.md
#                                   (v0.6 D-080 figure-utilization contract
#                                   stacks on the v3 chain; only slide_compose
#                                   changes).
#                              v3.2 → substory_design.v1.md ++ substory_design.v3_overlay.md
#                                   ++ substory_design.v3.2_overlay.md
#                                   slide_compose.v2.md ++ slide_compose.v3_overlay.md
#                                   ++ slide_compose.v3.1_overlay.md
#                                   ++ slide_compose.v3.2_overlay.md
#                                   (v0.7 D-085 figure-relevance rule [refines
#                                   D-080; no budget, use every relevant
#                                   curated figure] + D-086 deck_close layout
#                                   + D-087 transition_from_prior field on
#                                   substory_design — Tier B; slides +
#                                   substory_design BOTH carry v3.2 overlays).
#                              v3.3 → substory_design.v1.md ++ substory_design.v3.3_overlay.md
#                                   (clean overlay on v1, NOT stacked on v3/v3.2 —
#                                   consolidates Q/A/R/C + transition_from_prior
#                                   into one unified template per D-095 / v0.8
#                                   Tier C to fix the v3.2 prompt-layering
#                                   recency-bias field-drop bug)
#                                   slide_compose.v2.md ++ slide_compose.v3_overlay.md
#                                   ++ slide_compose.v3.1_overlay.md
#                                   ++ slide_compose.v3.2_overlay.md
#                                   (slide_compose stack UNCHANGED from v3.2 —
#                                   D-095 scope clarification: slide_compose not
#                                   vulnerable to the same bug class).
#                            Independent axis from --architecture-pipeline.
#                            Default v2 per D-074 until v0.5/v0.6 cut-over
#                            A/B passes.
#                            v3 + v3.1 + v3.2 + v3.3 require a fresh smoke-pass
#                            record per D-076; see --force-v3-smoke-stale.
#   --force-v3-smoke-stale   Bypass the D-076 smoke-pass gate. Use ONLY
#                            when you intentionally want to run v3 without
#                            a fresh smoke (emergency re-runs, etc.).
#                            Logged loudly to stderr.
#   --visual-qa              Run the visual-QA pass after assembly (v0.4 M4a
#                            Tier C). Renders the deck to per-slide PNGs and
#                            runs a vision claude -p over them to flag
#                            render-quality defects (overflow, overlap,
#                            footer collisions, illegible scale, headline↔body
#                            mismatch). Advisory (rc=0). Adds ~$0.6-0.8 +
#                            ~30s per run for a talk-30 deck.
#                            v0.8/D-096: AUTO-ON for STRONG tier on
#                            talk-30/talk-15 modes (audience-facing). This
#                            flag forces ON for any mode/tier; use
#                            --no-visual-qa to suppress the auto-on for a
#                            STRONG-mode iteration where you want to skip
#                            the cost.
#                            Requires LibreOffice + Poppler on host.
#   --no-visual-qa           v0.8/D-096: suppress the mode-aware auto-on
#                            visual-QA default. Use when you want to skip
#                            visual-QA on a STRONG talk-30/talk-15 run
#                            (e.g., iteration mode where ~$1/deck is too
#                            costly). Has no effect on modes where the
#                            default is already OFF (lightning-5, poster,
#                            talk-45, any non-STRONG tier).
#   --no-review-cascade      Skip the tiered review cascade (v0.4 M4b). The
#                            cascade AUTO-RUNS by default — it wraps
#                            Tier 1 (P1-P10 + advisory checks + opt-in
#                            visual-QA findings) + Tier 2 (Haiku) + Tier 3
#                            (canonical adversarial) with fail-fast on a
#                            Tier-1 P0. Writes audit/review_cascade.{md,json}.
#                            Use this flag to skip; the standalone
#                            stage_adversarial_review still runs unless
#                            --no-adversarial is also set.
#   --help                   Show this message
#
# Subcommands:
#   resume-cascade <draft-dir>
#                            v0.7/D-090: re-run the review cascade
#                            + standalone adversarial review against
#                            an EXISTING draft directory, without
#                            re-running upstream stages (plan / outline
#                            / compose / merge / assemble). Use when
#                            the cascade was interrupted (Ctrl-C /
#                            shell close / signal) after merge/assemble
#                            but before audit/review_cascade.json +
#                            adversarial_review.* + presentation_
#                            validation.json were written (the v0.6
#                            fdm class). The cascade is idempotent;
#                            safe to re-invoke. Writes pre+post
#                            checkpoint markers (audit/cascade-
#                            started.json + cascade-completed.json)
#                            so future interruptions are diagnosable
#                            from on-disk state alone.
#                            Example:
#                              $0 resume-cascade \\
#                                $BERIL_ROOT/projects/.../talks/draft_6

set -euo pipefail

# --- Defaults ---
PROJECT_ID=""
BERIL_ROOT_OVERRIDE=""
MODE="talk-30"
TIER="STRONG"
AUDIENCE="peer"
AUTO_ADVANCE=0
SKIP_ASSEMBLY=0
MODEL="claude-sonnet-4-6"   # v0.3.2.4: bumped from claude-sonnet-4-20250514 (~12 mo old)
NO_STREAM=0
RESUME_FROM=""        # 2026-04-26 #58: skip earlier stages on prompt iteration
DRAFT_DIR_OVERRIDE="" # required when RESUME_FROM is set
NO_ADVERSARIAL=0      # 2026-04-29 v0.3.0: skip adversarial review + revise loop
MAX_REVISE_COST_USD="5.00"  # cost cap for revise loop (per-run)
MAX_REVISIONS=6       # max findings the revise loop will process per run

# v0.3.3 image-gen flags
NO_IMAGES=0                   # skip image_gen stage entirely
AUTO_APPROVE_IMAGES=0         # bypass per-slide approval gate (CI / power users)
IMAGE_ALLOW_EXPLORATORY=0     # allow concept_illustration on EXPLORATORY tier
MAX_IMAGE_COST_USD="0.50"     # cumulative cap; default ~30 images at $0.014/each
IMAGE_STYLE=""                # optional style override forwarded to ai_image_prompt
# v0.7/D-088 Tier D.2: per-deck approval count cap. D-088 widens
# eligibility (claim_evidence with ≥3 bullets becomes eligible alongside
# concept_illustration's big_idea-only scope), so a cap on the count of
# approvals — separate from the dollar cap — keeps decks from over-
# illustrating. The cost cap (MAX_IMAGE_COST_USD) bounds spend; this
# cap bounds visual density. Both gates fire independently; whichever
# trips first short-circuits the rest of the per-slide loop.
# Default 4 per D-088: ~2 big_idea opens (existing approvals) +
# ~2 claim_evidence multi-panel diagrams across the substories. Tune
# down for shorter talks; tune up if the operator deliberately wants
# a more visual-heavy deck.
MAX_IMAGE_APPROVALS=4

# M5b/D-062: image-gen provider selection. Empty default = auto-resolve
# via env-var precedence (GOOGLE_AI_STUDIO_API_KEY > CBORG_API_KEY).
# CLI --image-provider overrides; downstream image_client.py CLI uses
# snake_case provider names (cborg | google_ai_studio).
IMAGE_PROVIDER=""

# v0.5 D-074: prompts-version selection. Default v2 until v0.5 cut-over
# A/B passes (then flip to v3 at v0.5.1). v1 / v2 / v3 are valid;
# dispatch picked by _substory_design_prompt_path + _slide_compose_prompt_path
# helpers. Independent axis from --architecture-pipeline.
PROMPTS_VERSION="v2"

# v0.5.1 D-076: live-LLM smoke-pass gate for --prompts-version v3.
# Off by default; --force-v3-smoke-stale sets it to bypass the gate
# in the operator-knows-what-they're-doing case (logged loudly).
FORCE_V3_SMOKE_STALE=0

# v0.4 M4a Tier C — visual-QA pass (DQ1 — Adam 2026-05-23).
# v0.8/D-096: mode-aware default. Initialized 0 here; auto-flipped
# to 1 after MODE+TIER validation when the run is talk-30 STRONG or
# talk-15 STRONG (the audience-facing modes where the v0.7 Tier-I
# read showed visual-QA catches load-bearing render bugs that
# Adam-reads cost 30-60min to find — e.g., the fdm slide-32
# directions-leak D-094 fixed). Operator overrides:
#   --visual-qa     forces ON on any mode/tier
#   --no-visual-qa  forces OFF even on STRONG audience modes
# The NO_VISUAL_QA flag is sticky — it suppresses the auto-on
# default but DOESN'T conflict with an explicit --visual-qa on the
# same command line (last-flag-wins via flag order).
VISUAL_QA=0
NO_VISUAL_QA=0

# v0.4 M4b Tier A — tiered review cascade (DQ1 — Adam 2026-05-24).
# Auto-runs by default; opt out via --no-review-cascade. Produces
# audit/review_cascade.{md,json}. Tier A ships scaffolding only
# (per-tier dispatchers return 'not-implemented'); cascade is
# always advisory until Tiers B/C/D fill in.
NO_REVIEW_CASCADE=0

CLAUDE_TOOLS="Read,Write,Bash,Grep,Glob,WebSearch,Agent,ToolSearch"

# --- Usage ---
usage() {
  local exit_code="${1:-0}"
  # Print the file's leading comment block (everything from line 4
  # up to but not including `set -euo pipefail`). awk-driven so
  # future flag additions don't require editing magic line numbers
  # — the previous fixed-range form silently truncated the v0.3.3
  # help output mid-flag-block.
  awk '/^set -euo pipefail/{exit} NR>=4{print}' "$0"
  exit "$exit_code"
}

# --- resume-cascade subcommand (v0.7 / D-090) ---------------------------
#
# `presentation_maker.sh resume-cascade <draft-dir>` re-runs the review
# cascade (M4b) + standalone adversarial review (if cascade didn't run
# Tier 3) against an EXISTING draft directory, without re-running the
# expensive upstream stages (plan / outline / compose / merge /
# assemble). The intended use is post-mortem recovery from a v0.6 fdm-
# class interruption: the slide_spec.json + .pptx exist on disk but
# audit/review_cascade.json + adversarial_review.* + presentation_
# validation.json are missing because the orchestrator was killed
# (Ctrl-C / shell close / signal) after merge/assemble.
#
# Operates as a pre-arg-parse intercept that does its work inline and
# exits — no project-id resolution, no smoke gate, no validation, no
# function-definition load from the main flow. Safe to re-invoke; the
# cascade is idempotent (overwrites its outputs).
if [[ "${1:-}" == "resume-cascade" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "Error: resume-cascade requires a <draft-dir> argument" >&2
    echo "Usage: $0 resume-cascade <draft-dir>" >&2
    exit 2
  fi
  _RESUME_DRAFT_DIR="$2"
  if [[ ! -d "$_RESUME_DRAFT_DIR" ]]; then
    echo "Error: draft directory not found: $_RESUME_DRAFT_DIR" >&2
    exit 1
  fi
  _RESUME_OUTDIR="$(cd "$_RESUME_DRAFT_DIR" && pwd -P)"
  if [[ ! -f "$_RESUME_OUTDIR/working/slide_spec.json" ]]; then
    echo "Error: $_RESUME_OUTDIR doesn't look like a presentation-maker" >&2
    echo "       draft (missing working/slide_spec.json — was the" >&2
    echo "       pipeline interrupted BEFORE merge/assemble? if so," >&2
    echo "       resume-cascade can't recover; re-run the full" >&2
    echo "       orchestrator)" >&2
    exit 1
  fi

  # File-discovery (mirrors the main flow's SCRIPT_DIR / SKILL_DIR /
  # TOOLS_DIR / PYTHON_BIN block but hoisted to run without
  # project-id validation).
  _RESUME_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  _RESUME_SKILL_DIR="$(cd "$_RESUME_SCRIPT_DIR/.." && pwd -P)"
  _RESUME_TOOLS_DIR="$_RESUME_SKILL_DIR/tools"
  _RESUME_AUDIT_DIR="$_RESUME_OUTDIR/audit"
  _RESUME_ADVERSARIAL_JSON="$_RESUME_AUDIT_DIR/adversarial_review.json"
  _RESUME_PYTHON_BIN=""
  _RESUME_CLI_PATH="$(command -v beril-presentation-maker 2>/dev/null \
                       || true)"
  if [[ -n "$_RESUME_CLI_PATH" ]]; then
    _RESUME_PYTHON_BIN="$(head -n 1 "$_RESUME_CLI_PATH" \
                            | sed 's|^#!||' || true)"
  fi
  if [[ -z "$_RESUME_PYTHON_BIN" || ! -x "$_RESUME_PYTHON_BIN" ]]; then
    _RESUME_PYTHON_BIN="$(command -v python3 || true)"
  fi
  if [[ -z "$_RESUME_PYTHON_BIN" ]]; then
    echo "Error: no Python interpreter found for resume-cascade" >&2
    exit 1
  fi

  mkdir -p "$_RESUME_AUDIT_DIR"

  # Derive PROJECT_ID + BERIL_ROOT from the draft path. Pattern:
  # <BERIL_ROOT>/projects/<PROJECT_ID>/talks/draft_N
  # BERIL_ROOT is needed by beril-adversarial for the standalone
  # invocation; if the path doesn't match the canonical layout the
  # cascade still works (cascade only reads OUTDIR-relative paths)
  # but adversarial will fail to resolve BERIL_ROOT and emit a
  # warning instead of crashing.
  _RESUME_PROJECT_ID="$(basename \
                         "$(dirname "$(dirname "$_RESUME_OUTDIR")")")"
  _RESUME_BERIL_ROOT="$(dirname \
    "$(dirname "$(dirname "$(dirname "$_RESUME_OUTDIR")")")")"

  echo "" >&2
  echo "──────────────────────────────────────────────────" >&2
  echo "[resume-cascade] D-090 / v0.7 Tier A.2" >&2
  echo "  project:   $_RESUME_PROJECT_ID" >&2
  echo "  draft-dir: $_RESUME_OUTDIR" >&2
  echo "──────────────────────────────────────────────────" >&2

  # Pre-cascade checkpoint marker (D-090).
  _RESUME_STARTED_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  _RESUME_SKILL_SHA="$(cd "$_RESUME_SKILL_DIR" && \
    git rev-parse --short HEAD 2>/dev/null || echo "unknown")"
  cat > "$_RESUME_AUDIT_DIR/cascade-started.json" <<EOF
{
  "schema_version": "cascade-checkpoint.v1",
  "phase": "started",
  "started_at_utc": "$_RESUME_STARTED_TS",
  "skill_git_sha": "$_RESUME_SKILL_SHA",
  "draft_dir": "$_RESUME_OUTDIR",
  "stages": ["review_cascade.py", "stage_adversarial_review"],
  "invoked_via": "resume-cascade"
}
EOF

  # --- Run the cascade ---
  echo "" >&2
  echo "[resume-cascade] running review_cascade.py" >&2
  "$_RESUME_PYTHON_BIN" "$_RESUME_TOOLS_DIR/review_cascade.py" \
    "$_RESUME_OUTDIR" 2>&1 | sed 's/^/  /' >&2 || true

  # --- Standalone adversarial review if cascade didn't run Tier 3 ---
  # M4b Tier D de-dup: when cascade.tier3.status ∈ {pass, advisory, fail}
  # the cascade already wrote adversarial_review.{json,md}; skip the
  # standalone invocation. Otherwise (skipped / error / not-implemented),
  # run beril-adversarial directly to produce the artifact.
  _RESUME_CASCADE_JSON="$_RESUME_AUDIT_DIR/review_cascade.json"
  _RESUME_TIER3_STATUS=""
  if [[ -f "$_RESUME_CASCADE_JSON" ]]; then
    _RESUME_TIER3_STATUS="$("$_RESUME_PYTHON_BIN" -c "
import json, sys
try:
    d = json.load(open('$_RESUME_CASCADE_JSON'))
    tiers = d.get('tiers') or []
    print(tiers[2].get('status', '') if len(tiers) >= 3 else '')
except Exception:
    print('')
" 2>/dev/null)"
  fi
  case "$_RESUME_TIER3_STATUS" in
    pass|advisory|fail)
      echo "" >&2
      echo "[resume-cascade] cascade Tier 3 ran (status=$_RESUME_TIER3_STATUS);" >&2
      echo "                 skipping standalone adversarial_review" >&2
      ;;
    *)
      echo "" >&2
      echo "[resume-cascade] running standalone adversarial_review" >&2
      if command -v beril-adversarial >/dev/null 2>&1; then
        if beril-adversarial --help 2>&1 \
            | grep -qE "^[[:space:]]*review[[:space:]]"; then
          # beril-adversarial needs BERIL_ROOT to locate .claude/skills/;
          # pass via env (its CLI's --beril-root flag is equivalent).
          BERIL_ROOT="$_RESUME_BERIL_ROOT" \
            beril-adversarial review --type presentation \
            "$_RESUME_OUTDIR" 2>&1 | sed 's/^/  /' >&2 || true
        else
          echo "  beril-adversarial 'review' subcommand not present;" >&2
          echo "  install >=v0.6.0 to recover adversarial_review.*" >&2
        fi
      else
        echo "  beril-adversarial not on PATH; cannot recover" >&2
        echo "  adversarial_review.{json,md} — install:" >&2
        echo "    pipx install --pip-args=\"--no-cache-dir\" \\" >&2
        echo "      git+ssh://git@github.com/ArkinLaboratory/beril-adversarial-skill.git" >&2
      fi
      ;;
  esac

  # Post-cascade checkpoint marker (D-090).
  _RESUME_COMPLETED_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$_RESUME_AUDIT_DIR/cascade-completed.json" <<EOF
{
  "schema_version": "cascade-checkpoint.v1",
  "phase": "completed",
  "started_at_utc": "$_RESUME_STARTED_TS",
  "completed_at_utc": "$_RESUME_COMPLETED_TS",
  "skill_git_sha": "$_RESUME_SKILL_SHA",
  "draft_dir": "$_RESUME_OUTDIR",
  "stages": ["review_cascade.py", "stage_adversarial_review"],
  "invoked_via": "resume-cascade"
}
EOF

  echo "" >&2
  echo "──────────────────────────────────────────────────" >&2
  echo "[resume-cascade] complete" >&2
  echo "  cascade artifacts written to: $_RESUME_AUDIT_DIR" >&2
  echo "──────────────────────────────────────────────────" >&2
  exit 0
fi

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --beril-root)        BERIL_ROOT_OVERRIDE="$2"; shift 2 ;;
    --mode)              MODE="$2"; shift 2 ;;
    --tier)              TIER="$2"; shift 2 ;;
    --audience)          AUDIENCE="$2"; shift 2 ;;
    --auto-advance)      AUTO_ADVANCE=1; shift ;;
    --skip-assembly)     SKIP_ASSEMBLY=1; shift ;;
    --model)             MODEL="$2"; shift 2 ;;
    --no-stream)         NO_STREAM=1; shift ;;
    --resume-from)       RESUME_FROM="$2"; shift 2 ;;
    --architecture-pipeline) ARCH_PIPELINE="$2"; shift 2 ;;
    --draft-dir)         DRAFT_DIR_OVERRIDE="$2"; shift 2 ;;
    --no-adversarial)    NO_ADVERSARIAL=1; shift ;;
    --max-revise-cost-usd) MAX_REVISE_COST_USD="$2"; shift 2 ;;
    --max-revisions)     MAX_REVISIONS="$2"; shift 2 ;;
    # v0.3.3 image-gen flags
    --no-images)             NO_IMAGES=1; shift ;;
    --auto-approve-images)   AUTO_APPROVE_IMAGES=1; shift ;;
    --image-allow-exploratory) IMAGE_ALLOW_EXPLORATORY=1; shift ;;
    --max-image-cost-usd)    MAX_IMAGE_COST_USD="$2"; shift 2 ;;
    --max-image-approvals)   MAX_IMAGE_APPROVALS="$2"; shift 2 ;;
    --image-style)           IMAGE_STYLE="$2"; shift 2 ;;
    # M5b/D-062: image-gen provider selection (auto-resolved when empty)
    --image-provider)        IMAGE_PROVIDER="$2"; shift 2 ;;
    # v0.5/D-074: prompts version selection (default v2; v3 opt-in)
    --prompts-version)       PROMPTS_VERSION="$2"; shift 2 ;;
    # v0.5.1/D-076: bypass the v3 smoke-pass gate. Use only when
    # you intentionally want to run v3 without a fresh smoke
    # (e.g., emergency re-runs). Logged loudly to stderr.
    --force-v3-smoke-stale)  FORCE_V3_SMOKE_STALE=1; shift ;;
    # v0.4 M4a Tier C — visual-QA pass (DQ1)
    # v0.8/D-096: --visual-qa forces ON; --no-visual-qa forces OFF
    # (suppresses the mode-aware auto-on default for STRONG
    # talk-30/talk-15).
    --visual-qa)         VISUAL_QA=1; shift ;;
    --no-visual-qa)      NO_VISUAL_QA=1; shift ;;
    # v0.4 M4b Tier A — review cascade is auto-run; opt out with this flag
    --no-review-cascade) NO_REVIEW_CASCADE=1; shift ;;
    --help)              usage ;;
    -*)                  echo "Error: Unknown option $1" >&2; usage 1 ;;
    *)
      if [[ -z "$PROJECT_ID" ]]; then
        PROJECT_ID="$1"
      else
        echo "Error: Unexpected argument $1" >&2; usage 1
      fi
      shift ;;
  esac
done

# --- Validate ---
if [[ -z "$PROJECT_ID" ]]; then
  echo "Error: project_id is required" >&2; usage 1
fi
case "$MODE" in
  talk-30|talk-15|talk-45|lightning-5) ;;
  poster-h|poster-v)
    echo "Error: posters not supported in smoke v1" >&2; exit 1 ;;
  *)
    echo "Error: invalid --mode '$MODE'" >&2; exit 1 ;;
esac
case "$TIER" in
  STRONG|THIN|EXPLORATORY) ;;
  *) echo "Error: invalid --tier '$TIER'" >&2; exit 1 ;;
esac

# v0.8/D-096 — mode-aware visual-QA auto-on. Flip VISUAL_QA from 0
# to 1 when this is an audience-facing run (STRONG tier + talk-30 or
# talk-15 mode) AND the operator hasn't explicitly opted out via
# --no-visual-qa. The v0.7 Tier-I read showed visual-QA catches
# load-bearing render bugs (fdm slide-32 directions-leak; D-094)
# that Adam-reads cost 30-60min to surface; cost is ~$1 + ~30s/deck.
# Lightning-5 (rough draft) + poster (different render pipeline) +
# talk-45 stay opt-in per D-096 mode-coverage table.
if [[ "$VISUAL_QA" -eq 0 && "$NO_VISUAL_QA" -eq 0 ]]; then
  if [[ "$TIER" == "STRONG" ]] \
      && [[ "$MODE" == "talk-30" || "$MODE" == "talk-15" ]]; then
    VISUAL_QA=1
    echo "[v0.8/D-096] visual-QA auto-on for ${MODE} ${TIER} " \
         "(audience-facing mode; ~\$1 + ~30s/deck; --no-visual-qa " \
         "to opt out)" >&2
  fi
fi

# v0.4 M2: which clustering stage runs at the substory slot.
# v0_3 (default) → stage_substory_design; v0_4 → stage_deck_outline
# (M2-lite — V0_4_ARCHITECTURE.md §20). v0.3.x default unchanged.
ARCH_PIPELINE="${ARCH_PIPELINE:-v0_3}"
case "$ARCH_PIPELINE" in
  v0_3|v0_4) ;;
  *) echo "Error: invalid --architecture-pipeline '$ARCH_PIPELINE' (v0_3|v0_4)" >&2; exit 1 ;;
esac

# Validate --resume-from + --draft-dir pairing.
# v0.3.2.6: list extended to include adversarial_review + revise_slides
# (added in v0.3.0). v0.3.3: extended to include image_gen (between
# speaker_notes and merge per V0_3_3_ARCHITECTURE.md §3).
case "$RESUME_FROM" in
  ""|plan|throughline|substory_design|phase0_tooling|deck_outline|curate_figures|citation_pool|cross_tenant|intro|slide_compose|qa_prep|deck_close|speaker_notes|image_gen|merge|adversarial_review|revise_slides) ;;
  *)
    echo "Error: invalid --resume-from '$RESUME_FROM'" >&2
    echo "       valid stages: plan|throughline|substory_design|phase0_tooling|deck_outline|curate_figures|citation_pool|cross_tenant|intro|slide_compose|qa_prep|deck_close|speaker_notes|image_gen|merge|adversarial_review|revise_slides" >&2
    exit 1 ;;
esac
if [[ -n "$RESUME_FROM" && -z "$DRAFT_DIR_OVERRIDE" ]]; then
  echo "Error: --resume-from requires --draft-dir <path>" >&2
  exit 1
fi
if [[ -n "$DRAFT_DIR_OVERRIDE" && -z "$RESUME_FROM" ]]; then
  echo "Error: --draft-dir requires --resume-from <stage>" >&2
  exit 1
fi
if [[ -n "$DRAFT_DIR_OVERRIDE" && ! -d "$DRAFT_DIR_OVERRIDE" ]]; then
  echo "Error: --draft-dir '$DRAFT_DIR_OVERRIDE' does not exist" >&2
  exit 1
fi

# --- Resolve BERIL_ROOT ---
if [[ -n "$BERIL_ROOT_OVERRIDE" ]]; then
  BERIL_ROOT="$(cd "$BERIL_ROOT_OVERRIDE" && pwd)"
elif [[ -n "${BERIL_ROOT:-}" ]]; then
  BERIL_ROOT="$(cd "$BERIL_ROOT" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  # Smoke is run from the source tree, not an installed skill. Walk up
  # the package layout: tools/ → skill/ → beril_presentation_maker/ →
  # src/ → repo-root. Then expect the user to pass --beril-root for the
  # actual BERDL project location.
  echo "Error: --beril-root or \$BERIL_ROOT must be set; smoke harness" >&2
  echo "       does not auto-detect BERIL_ROOT (we live outside it)." >&2
  exit 1
fi

if [[ ! -d "$BERIL_ROOT/projects/$PROJECT_ID" ]]; then
  echo "Error: project directory not found: $BERIL_ROOT/projects/$PROJECT_ID" >&2
  exit 1
fi

PROJECT_DIR="$BERIL_ROOT/projects/$PROJECT_ID"

# --- Resolve SKILL_DIR (where prompts + tools live) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PROMPTS_DIR="$SKILL_DIR/prompts"
TOOLS_DIR="$SKILL_DIR/tools"

for f in plan.v1.md throughline.v1.md substory_design.v1.md substory_design.v3_overlay.md substory_design.v3.2_overlay.md substory_design.v3.3_overlay.md deck_outline.v1.md slide_compose.v1.md slide_compose.v2.md slide_compose.v3_overlay.md slide_compose.v3.1_overlay.md slide_compose.v3.2_overlay.md intro.v1.md; do
  if [[ ! -f "$PROMPTS_DIR/$f" ]]; then
    echo "Error: prompt missing at $PROMPTS_DIR/$f" >&2
    exit 1
  fi
done

# v0.5/D-074 + v0.6/D-080 + v0.7/D-085: validate --prompts-version flag.
# v3.1 stacks the figure-utilization overlay onto the v3 contract (D-080);
# v3.2 stacks the figure-relevance refinement + arc-transition + deck_close
# overlay on top (D-085/D-086/D-087).
case "$PROMPTS_VERSION" in
  v1|v2|v3|v3.1|v3.2|v3.3) ;;
  *)
    echo "Error: --prompts-version must be v1|v2|v3|v3.1|v3.2|v3.3, got: $PROMPTS_VERSION" >&2
    exit 2
    ;;
esac

# v0.5.1/D-076: live-LLM smoke-pass gate. When --prompts-version v3
# is passed, require a fresh smoke-pass record (per
# `tools/smoke_v3_prompt.py --check-recent`). The gate catches the
# 2026-05-26 morning-abort recurrence class: prompt-vs-schema drift
# that unit tests (which mock the LLM) can't detect. Bypass via
# --force-v3-smoke-stale.
# Gate-check fires for any v3-family version (v3, v3.1, v3.2, ...).
# v0.6/D-080: v3.1 stacks the figure-utilization overlay on v3, which
# changes the prompt-body sha; the smoke harness re-validates the
# stacked concat and writes a new pass record.
# v0.7/D-085: v3.2 further stacks the figure-relevance refinement +
# deck_close overlay; same sha-changes-on-stack-extension pattern.
case "$PROMPTS_VERSION" in
  v3|v3.1|v3.2|v3.3) _v3_family=1 ;;
  *)            _v3_family=0 ;;
esac
if [[ "$_v3_family" == "1" && "$FORCE_V3_SMOKE_STALE" != "1" ]]; then
  # Pre-flight relies on $TOOLS_DIR resolved further down; resolve it
  # locally for the gate-check.
  _v3_gate_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  _v3_gate_skill_dir="$(cd "$_v3_gate_script_dir/.." && pwd -P)"
  if ! python3 "$_v3_gate_skill_dir/tools/smoke_v3_prompt.py" \
        --check-recent >/dev/null 2>&1; then
    echo "Error: --prompts-version $PROMPTS_VERSION requires a fresh smoke-pass record." >&2
    # `| sed` pipes through with `pipefail`; the rc=1 from python3
    # would otherwise abort the shell under `set -e` before we
    # reach `exit 2`. `|| true` tolerates the non-zero rc on the
    # diagnostic call so the structured exit-2 below fires.
    python3 "$_v3_gate_skill_dir/tools/smoke_v3_prompt.py" \
        --check-recent 2>&1 | sed 's/^/  /' >&2 || true
    echo "" >&2
    echo "  Run the live-LLM smoke once (~\$0.60):" >&2
    echo "    python $_v3_gate_skill_dir/tools/smoke_v3_prompt.py" >&2
    echo "" >&2
    echo "  Or bypass the gate (only when intentional):" >&2
    echo "    $0 ... --prompts-version $PROMPTS_VERSION --force-v3-smoke-stale" >&2
    exit 2
  fi
elif [[ "$_v3_family" == "1" && "$FORCE_V3_SMOKE_STALE" == "1" ]]; then
  echo "[orchestrator] WARNING: --prompts-version $PROMPTS_VERSION with" >&2
  echo "[orchestrator]          --force-v3-smoke-stale (D-076 gate bypassed)." >&2
  echo "[orchestrator]          Recurrence of the 2026-05-26 schema-drift" >&2
  echo "[orchestrator]          bug is possible. Document why." >&2
fi

# v0.5/D-074: prompt-file dispatch by version. The substory_design
# stage uses v1 for both v1+v2 prompts-versions (v1/v2 substory_design
# shape is identical; v3 introduces the Q/A/R/C contract per D-071).
# slide_compose uses v1 for v1, v2 for v2; v3 emits a *concatenated*
# v2-body + v3-overlay built once at orchestrator start (D-075). The
# concat lives under $AUDIT_DIR/_prompts/ for per-run audit + safe
# parallel-runs isolation (Tier C + Tier D launched together cannot
# race on a shared /tmp path). Path is populated by
# build_v3_concat_prompts() after set_draft_paths.
SLIDE_COMPOSE_V3_CONCAT_PATH=""
SUBSTORY_DESIGN_V3_CONCAT_PATH=""
# v0.6/D-080: v3.1 stacks figure-utilization overlay on the v3 chain
# (cat v2.md + v3_overlay.md + v3.1_overlay.md). substory_design.v3.1
# is unchanged from v3 (only slide_compose carries v3.1 changes), so
# only slide_compose has a v3.1-specific concat path here.
SLIDE_COMPOSE_V3_1_CONCAT_PATH=""
# v0.7/D-085: v3.2 stacks figure-relevance refinement + deck_close +
# arc-transition USAGE overlays on the v3.1 chain (cat v2 +
# v3_overlay + v3.1_overlay + v3.2_overlay).
SLIDE_COMPOSE_V3_2_CONCAT_PATH=""
# v0.7/D-087 Tier B: substory_design v3.2 overlay adds the
# `transition_from_prior` field emission. v3.2 substory_design
# concat = cat v1 + v3_overlay + v3.2_overlay (stacked on the v3
# substory_design contract).
SUBSTORY_DESIGN_V3_2_CONCAT_PATH=""
# v0.8/D-095 Tier C: v3.3 substory_design is a CLEAN overlay on v1
# (NOT stacked on v3 or v3.2 overlays). Consolidates Q/A/R/C +
# transition_from_prior into one unified template with explicit
# supersedes-clause to mitigate the v3.2 prompt-layering recency-
# bias field-drop bug live-discovered at v0.7 Tier G. v3.3
# substory_design concat = cat v1 + v3.3_overlay (2 sources, NOT
# 3). slide_compose stack unchanged from v3.2 — slide_compose not
# vulnerable to the same bug class (smoke harness LAYOUT_REQUIRED_FIELDS
# map enforces shape independent of prompt-tail bias).
SUBSTORY_DESIGN_V3_3_CONCAT_PATH=""

_substory_design_prompt_path() {
  # v0.6/D-080: v3.1 reuses the v3 substory_design concat
  # (substory_design isn't changed in v3.1 — only slide_compose
  # gets the figure-utilization overlay).
  # v0.7/D-087 Tier B: v3.2 has its OWN substory_design concat
  # (the v3.2 overlay adds transition_from_prior emission).
  # v0.8/D-095 Tier C: v3.3 has its OWN clean substory_design concat
  # (cat v1 + v3.3_overlay, NOT stacked on v3 / v3.2).
  case "$PROMPTS_VERSION" in
    v1|v2)    echo "$PROMPTS_DIR/substory_design.v1.md" ;;
    v3|v3.1)  echo "$SUBSTORY_DESIGN_V3_CONCAT_PATH" ;;
    v3.2)     echo "$SUBSTORY_DESIGN_V3_2_CONCAT_PATH" ;;
    v3.3)     echo "$SUBSTORY_DESIGN_V3_3_CONCAT_PATH" ;;
  esac
}
_slide_compose_prompt_path() {
  # v0.8/D-095 Tier C: v3.3 slide_compose stack UNCHANGED from v3.2.
  # The v3.2 → v3.3 transition affects substory_design ONLY; slide_compose
  # not vulnerable to the same prompt-layering bug class per the
  # D-095 subagent investigation (smoke harness LAYOUT_REQUIRED_FIELDS
  # map enforces shape independent of prompt-tail recency bias).
  case "$PROMPTS_VERSION" in
    v1)   echo "$PROMPTS_DIR/slide_compose.v1.md" ;;
    v2)   echo "$PROMPTS_DIR/slide_compose.v2.md" ;;
    v3)   echo "$SLIDE_COMPOSE_V3_CONCAT_PATH" ;;
    v3.1) echo "$SLIDE_COMPOSE_V3_1_CONCAT_PATH" ;;
    v3.2) echo "$SLIDE_COMPOSE_V3_2_CONCAT_PATH" ;;
    v3.3) echo "$SLIDE_COMPOSE_V3_2_CONCAT_PATH" ;;
  esac
}

# v0.5.1/D-075: build concatenated v3 prompt files at orchestrator
# start. v3 is a small overlay (~250 lines) that ADDS register-
# discipline + Q/A/R/C role guidance on top of v2's full per-layout
# authoring rules. The LLM receives `cat slide_compose.v2.md
# slide_compose.v3_overlay.md` as a single --system-prompt. Concat
# order is v2 first + overlay last (LLM attention strongest at
# system-prompt tail; overlay wins on conflicts). Idempotent — if
# the file already exists (e.g., a resumed run), it gets rebuilt
# from current prompt sources rather than reused; cheap (~250 lines
# of disk I/O).
#
# Only runs when PROMPTS_VERSION=v3; v1/v2 paths skip entirely. The
# concat lives under audit/_prompts/ (per-project; audit trail) and
# is cleaned up implicitly with the audit/ tree at finalize-run
# time (not its own EXIT-trap action — keeping the concat around
# at exit is intentional so a debug-after-fail can inspect what
# prompt the LLM actually saw).
build_v3_concat_prompts() {
  # v0.6/D-080 + v0.7/D-085 + v0.8/D-095: this helper serves
  # v3 / v3.1 / v3.2 / v3.3.
  # v3:   cat v2.md + v3_overlay.md → slide_compose.v3.concat.md
  # v3.1: cat v2.md + v3_overlay.md + v3.1_overlay.md
  #       → slide_compose.v3.1.concat.md
  # v3.2: cat v2.md + v3_overlay.md + v3.1_overlay.md + v3.2_overlay.md
  #       → slide_compose.v3.2.concat.md
  # v3.3: slide_compose stack UNCHANGED from v3.2 (per D-095 scope —
  #       slide_compose not vulnerable to the v3.2 substory_design
  #       prompt-layering recency-bias bug class).
  # substory_design.v3.concat.md = cat v1 + v3_overlay (always built
  #       when in v3-family).
  # substory_design.v3.2.concat.md = cat v1 + v3_overlay + v3.2_overlay
  #       (built when v3.2).
  # substory_design.v3.3.concat.md = cat v1 + v3.3_overlay
  #       (CLEAN, NOT stacked on v3 / v3.2 — per D-095 the v3.3 overlay
  #       consolidates the v3 + v3.2 contracts into one unified
  #       template that mitigates the recency-bias displacement bug
  #       v3.2 substory_design exhibited live).
  case "$PROMPTS_VERSION" in
    v3|v3.1|v3.2|v3.3) ;;
    *) return 0 ;;
  esac

  local concat_dir="$AUDIT_DIR/_prompts"
  mkdir -p "$concat_dir"

  # --- slide_compose v3 concat (always built; v3.1 / v3.2 / v3.3 stack on this) ---
  local slide_v2="$PROMPTS_DIR/slide_compose.v2.md"
  local slide_v3_overlay="$PROMPTS_DIR/slide_compose.v3_overlay.md"
  SLIDE_COMPOSE_V3_CONCAT_PATH="$concat_dir/slide_compose.v3.concat.md"
  cat "$slide_v2" "$slide_v3_overlay" > "$SLIDE_COMPOSE_V3_CONCAT_PATH"

  # --- slide_compose v3.1 concat (stacked overlay; built only when needed) ---
  # Built for v3.1 / v3.2 / v3.3 — all stack on the v3.1 substrate
  # for any tooling that wants to inspect the intermediate stack.
  if [[ "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" \
        || "$PROMPTS_VERSION" == "v3.3" ]]; then
    local slide_v3_1_overlay="$PROMPTS_DIR/slide_compose.v3.1_overlay.md"
    SLIDE_COMPOSE_V3_1_CONCAT_PATH="$concat_dir/slide_compose.v3.1.concat.md"
    cat "$slide_v2" "$slide_v3_overlay" "$slide_v3_1_overlay" \
      > "$SLIDE_COMPOSE_V3_1_CONCAT_PATH"
  fi

  # --- slide_compose v3.2 concat (stacked overlay; built only when needed) ---
  # v3.3 also builds + uses this concat (slide_compose stack unchanged
  # from v3.2 per D-095 scope clarification).
  if [[ "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
    local slide_v3_2_overlay="$PROMPTS_DIR/slide_compose.v3.2_overlay.md"
    SLIDE_COMPOSE_V3_2_CONCAT_PATH="$concat_dir/slide_compose.v3.2.concat.md"
    cat "$slide_v2" "$slide_v3_overlay" "$slide_v3_1_overlay" "$slide_v3_2_overlay" \
      > "$SLIDE_COMPOSE_V3_2_CONCAT_PATH"
  fi

  # --- substory_design v3 concat (always built; v3.2 stacks on this) ---
  # v0.5.1 Tier A.2 / D-078: v1 body + v3 overlay; overlay last so
  # its v3 Output-format-supersede statement wins on the conflicting
  # template section.
  local substory_v1="$PROMPTS_DIR/substory_design.v1.md"
  local substory_overlay="$PROMPTS_DIR/substory_design.v3_overlay.md"
  SUBSTORY_DESIGN_V3_CONCAT_PATH="$concat_dir/substory_design.v3.concat.md"
  cat "$substory_v1" "$substory_overlay" > "$SUBSTORY_DESIGN_V3_CONCAT_PATH"

  # --- substory_design v3.2 concat (stacked overlay; built only when needed) ---
  # v0.7/D-087 Tier B: v3.2 substory_design adds transition_from_prior
  # emission. Stacked order: v1 body + v3 overlay + v3.2 overlay
  # (overlay-last attention rule per D-075). NOTE: v0.7 Tier-I found
  # this stack drops fields live due to recency-bias displacement;
  # v3.3 (below) consolidates into a clean overlay.
  if [[ "$PROMPTS_VERSION" == "v3.2" ]]; then
    local substory_v3_2_overlay="$PROMPTS_DIR/substory_design.v3.2_overlay.md"
    SUBSTORY_DESIGN_V3_2_CONCAT_PATH="$concat_dir/substory_design.v3.2.concat.md"
    cat "$substory_v1" "$substory_overlay" "$substory_v3_2_overlay" \
      > "$SUBSTORY_DESIGN_V3_2_CONCAT_PATH"
  fi

  # --- substory_design v3.3 concat (CLEAN overlay; built only when needed) ---
  # v0.8/D-095 Tier C: v3.3 is a CLEAN overlay on v1 (NOT stacked on
  # v3 or v3.2). Consolidates the v3 Q/A/R/C contract (D-071) +
  # v3.2 transition_from_prior field (D-087) into one unified
  # template with explicit "v3.3 supersedes" recency-bias mitigation.
  # Concat order: v1 body + v3.3 overlay (2 sources, NOT 3).
  if [[ "$PROMPTS_VERSION" == "v3.3" ]]; then
    local substory_v3_3_overlay="$PROMPTS_DIR/substory_design.v3.3_overlay.md"
    SUBSTORY_DESIGN_V3_3_CONCAT_PATH="$concat_dir/substory_design.v3.3.concat.md"
    cat "$substory_v1" "$substory_v3_3_overlay" \
      > "$SUBSTORY_DESIGN_V3_3_CONCAT_PATH"
  fi

  echo "[orchestrator] v$PROMPTS_VERSION concat prompts:" >&2
  case "$PROMPTS_VERSION" in
    v3.2|v3.3) echo "  slide_compose:   $SLIDE_COMPOSE_V3_2_CONCAT_PATH" >&2 ;;
    v3.1)      echo "  slide_compose:   $SLIDE_COMPOSE_V3_1_CONCAT_PATH" >&2 ;;
    *)         echo "  slide_compose:   $SLIDE_COMPOSE_V3_CONCAT_PATH" >&2 ;;
  esac
  case "$PROMPTS_VERSION" in
    v3.3) echo "  substory_design: $SUBSTORY_DESIGN_V3_3_CONCAT_PATH" >&2 ;;
    v3.2) echo "  substory_design: $SUBSTORY_DESIGN_V3_2_CONCAT_PATH" >&2 ;;
    *)    echo "  substory_design: $SUBSTORY_DESIGN_V3_CONCAT_PATH" >&2 ;;
  esac
}

# v0.4 M3: bounded-concurrency worker-pool for parallel slide_compose
# (tools/worker_pool.sh — defines functions only, no side effects).
if [[ ! -f "$TOOLS_DIR/worker_pool.sh" ]]; then
  echo "Error: worker_pool.sh missing at $TOOLS_DIR/worker_pool.sh" >&2
  exit 1
fi
# shellcheck source=worker_pool.sh
source "$TOOLS_DIR/worker_pool.sh"

# --- Discover the pipx venv's Python interpreter ---
# 2026-04-27 fix #67: bare `python3` in bash resolves differently than
# in zsh on macOS (Anaconda vs Homebrew Python 3.14 — different
# site-packages). Pin to whatever Python the user installed
# `beril-presentation-maker` into via pipx. The console script's
# shebang points at the pipx venv's interpreter; reading it gives us
# a deploy-portable Python that has python-pptx + Pillow + nbformat
# pre-installed. Pattern adapted from beril-paper-writer's
# paper_writer.sh discover_python_bin helper.
discover_python_bin() {
  local cli_path
  cli_path="$(command -v beril-presentation-maker 2>/dev/null || true)"
  if [[ -z "$cli_path" ]]; then
    return 1
  fi
  local shebang
  shebang="$(head -n 1 "$cli_path" | sed 's|^#!||')"
  if [[ -z "$shebang" || ! -x "$shebang" ]]; then
    return 1
  fi
  echo "$shebang"
}

PYTHON_BIN="$(discover_python_bin)" || PYTHON_BIN=""
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Error: cannot discover the package's Python interpreter." >&2
  echo "       The orchestrator needs a deploy-portable Python that has" >&2
  echo "       python-pptx, Pillow, and nbformat installed. Install via:" >&2
  echo "" >&2
  echo "         cd $(dirname "$(dirname "$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")")")" >&2
  echo "         pipx install --force -e ." >&2
  echo "" >&2
  echo "       Then re-run this script. \`beril-presentation-maker\` should" >&2
  echo "       be on PATH; this script reads its shebang to find the right" >&2
  echo "       python." >&2
  exit 1
fi

echo "[orchestrator] using python: $PYTHON_BIN" >&2

# --- Pre-flight: verify python deps in the discovered interpreter ---
# Burned ~\$6 across two smoke runs (2026-04-26) discovering python-pptx
# wasn't on the python3 the orchestrator resolves to — assembly failed
# at the LAST stage after \$3 of LLM costs. This pre-flight catches the
# missing-dep case at second 0, before stage 1 fires.
echo "[pre-flight] verifying python deps..." >&2
if ! "$PYTHON_BIN" -c "
import sys
missing = []
for mod, install_name in [
    ('pptx', 'python-pptx'),
    ('PIL', 'Pillow'),
    ('nbformat', 'nbformat'),
]:
    try:
        __import__(mod)
    except ImportError:
        missing.append((mod, install_name))
if missing:
    sys.stderr.write('FAIL: missing python deps in ' + sys.executable + ':\n')
    for mod, name in missing:
        sys.stderr.write(f'  - {name} (import {mod})\n')
    sys.stderr.write('\nThis is unexpected — these are pyproject.toml deps.\n')
    sys.stderr.write('Re-run the pipx install:\n')
    sys.stderr.write('  pipx install --force -e .\n')
    sys.exit(1)
" 2>&1; then
  echo "" >&2
  echo "Error: pre-flight check failed. Fix the missing deps above before running smoke." >&2
  echo "       The smoke makes ~6 LLM calls totaling ~\$3.00 — failing at the final" >&2
  echo "       assembly step wastes that. Install deps first." >&2
  exit 1
fi
echo "[pre-flight] OK" >&2

# --- v0.3.3 + M5b image-gen: resolve provider API keys ---
# Mirrors image_gen_calibration.py's _resolve_api_key precedence: shell
# env wins; otherwise read from BERIL_ROOT/.env (the standard BERIL
# secret location, matches what atlas + adversarial use). Never echoes
# the value. Per memory feedback_secret_file_handling.md, we extract
# the specific variables we need rather than `source`-ing the whole file.
#
# M5b/D-062: we now resolve BOTH CBORG_API_KEY and
# GOOGLE_AI_STUDIO_API_KEY in one pass. Provider precedence is
# computed below (after both keys are resolved).
if [[ -f "$BERIL_ROOT/.env" ]]; then
  if [[ -z "${CBORG_API_KEY:-}" ]] || [[ -z "${GOOGLE_AI_STUDIO_API_KEY:-}" ]]; then
    _env_dump=$("$PYTHON_BIN" -c "
import re, sys
from pathlib import Path
WANTED = ('CBORG_API_KEY', 'GOOGLE_AI_STUDIO_API_KEY')
env_file = Path('$BERIL_ROOT/.env')
for line in env_file.read_text(encoding='utf-8').splitlines():
    for name in WANTED:
        m = re.match(rf'^{name}=(.*)\$', line.strip())
        if m:
            v = m.group(1).strip()
            if (v.startswith('\"') and v.endswith('\"')) or (v.startswith(\"'\") and v.endswith(\"'\")):
                v = v[1:-1]
            # Output as NAME=value lines; consumer parses.
            sys.stdout.write(f'{name}={v}\n')
            break
" 2>/dev/null) || true
    while IFS='=' read -r _k _v; do
      case "$_k" in
        CBORG_API_KEY)
          if [[ -z "${CBORG_API_KEY:-}" ]] && [[ -n "$_v" ]]; then
            CBORG_API_KEY="$_v"
            export CBORG_API_KEY
            echo "[orchestrator] CBORG_API_KEY loaded from BERIL_ROOT/.env" >&2
          fi
          ;;
        GOOGLE_AI_STUDIO_API_KEY)
          if [[ -z "${GOOGLE_AI_STUDIO_API_KEY:-}" ]] && [[ -n "$_v" ]]; then
            GOOGLE_AI_STUDIO_API_KEY="$_v"
            export GOOGLE_AI_STUDIO_API_KEY
            echo "[orchestrator] GOOGLE_AI_STUDIO_API_KEY loaded from BERIL_ROOT/.env" >&2
          fi
          ;;
      esac
    done <<< "$_env_dump"
    unset _env_dump _k _v
  fi
fi

# --- M5b/D-062: image-gen provider precedence ---
# Explicit --image-provider arg wins. Otherwise: GOOGLE_AI_STUDIO_API_KEY
# present → AI Studio (matches Adam's stated intent: "use the user's
# Gemini Studio license if available" — §14.1). Else CBORG_API_KEY →
# CBORG. Else leave IMAGE_PROVIDER empty; the image-gen stage will
# disable itself with a clear diagnostic (image_gen_decision.py /
# stage_image_gen handle the no-provider case as if --no-images was set).
if [[ -z "$IMAGE_PROVIDER" ]]; then
  if [[ -n "${GOOGLE_AI_STUDIO_API_KEY:-}" ]]; then
    IMAGE_PROVIDER="google_ai_studio"
    echo "[orchestrator] image-gen provider: google_ai_studio (GOOGLE_AI_STUDIO_API_KEY present)" >&2
  elif [[ -n "${CBORG_API_KEY:-}" ]]; then
    IMAGE_PROVIDER="cborg"
    echo "[orchestrator] image-gen provider: cborg (CBORG_API_KEY present)" >&2
  fi
else
  # --image-provider explicit: validate the corresponding env var
  case "$IMAGE_PROVIDER" in
    cborg)
      if [[ -z "${CBORG_API_KEY:-}" ]]; then
        echo "[orchestrator] WARNING: --image-provider cborg but CBORG_API_KEY not set" >&2
      fi
      ;;
    google_ai_studio)
      if [[ -z "${GOOGLE_AI_STUDIO_API_KEY:-}" ]]; then
        echo "[orchestrator] WARNING: --image-provider google_ai_studio but GOOGLE_AI_STUDIO_API_KEY not set" >&2
      fi
      ;;
    *)
      echo "[orchestrator] ERROR: --image-provider must be 'cborg' or 'google_ai_studio', got: $IMAGE_PROVIDER" >&2
      exit 2
      ;;
  esac
  echo "[orchestrator] image-gen provider: $IMAGE_PROVIDER (via --image-provider)" >&2
fi
export IMAGE_PROVIDER

# --- Output dir setup ---
DRAFTS_DIR="$PROJECT_DIR/talks"
mkdir -p "$DRAFTS_DIR"

if [[ -n "$DRAFT_DIR_OVERRIDE" ]]; then
  # Resume mode: reuse the existing draft directory
  OUTDIR="$(cd "$DRAFT_DIR_OVERRIDE" && pwd -P)"
else
  # Fresh-run mode: pick next draft_N atomically
  DRAFT_N=1
  while [[ -d "$DRAFTS_DIR/draft_$DRAFT_N" ]]; do
    DRAFT_N=$((DRAFT_N + 1))
    if [[ $DRAFT_N -gt 9999 ]]; then
      echo "Error: cannot allocate draft directory under $DRAFTS_DIR" >&2
      exit 1
    fi
  done
  OUTDIR="$DRAFTS_DIR/draft_$DRAFT_N"
fi

# --- v0.3.1 4-zone layout setup ---
# Mirror of draft_paths.py DraftPaths. Test
# tests/unit/test_draft_paths.py asserts shell + Python agree on schema.
init_draft_layout() {
  local outdir="$1"
  mkdir -p \
    "$outdir/deliverable" \
    "$outdir/narrative" \
    "$outdir/working" \
    "$outdir/working/00_phase0" \
    "$outdir/working/03_slides" \
    "$outdir/working/04_speaker_notes" \
    "$outdir/working/05_image_requests" \
    "$outdir/working/05_images" \
    "$outdir/audit" \
    "$outdir/audit/stage-logs" \
    "$outdir/audit/snapshots" \
    "$outdir/audit/manual-edits" \
    "$outdir/audit/runs"
}

set_draft_paths() {
  local outdir="$1"
  # Top-level zones
  DELIVERABLE_DIR="$outdir/deliverable"
  NARRATIVE_DIR="$outdir/narrative"
  WORKING_DIR="$outdir/working"
  AUDIT_DIR="$outdir/audit"
  # deliverable/
  DECK_PPTX="$DELIVERABLE_DIR/draft.pptx"
  DECK_PDF="$DELIVERABLE_DIR/draft.pdf"
  # narrative/
  THROUGHLINE_PATH="$NARRATIVE_DIR/00_throughline.md"
  SUBSTORIES_PATH="$NARRATIVE_DIR/02_substories.md"
  REFERENCES_MD="$NARRATIVE_DIR/references.md"
  BIBLIOGRAPHY="$NARRATIVE_DIR/bibliography.bib"
  CITATION_MAP="$NARRATIVE_DIR/citation_map.md"
  # working/
  PLAN_PATH="$WORKING_DIR/00_plan.md"
  THROUGHLINE_CANDIDATES="$WORKING_DIR/00_throughline_candidates.md"
  SLIDES_DIR="$WORKING_DIR/03_slides"
  SPEAKER_NOTES_DIR="$WORKING_DIR/04_speaker_notes"
  IMAGE_REQUESTS_DIR="$WORKING_DIR/05_image_requests"
  IMAGES_DIR="$WORKING_DIR/05_images"
  CITATION_POOL_PATH="$WORKING_DIR/citation_pool.json"
  CROSS_TENANT_MD="$WORKING_DIR/cross_tenant_signal.md"
  CROSS_TENANT_JSON="$WORKING_DIR/cross_tenant_signal.json"
  # v0.7/D-086 Tier C: deck_close curator signal + composer fragment.
  DECK_CLOSE_SIGNAL_JSON="$WORKING_DIR/deck_close_signal.json"
  CURATED_FIGURES="$WORKING_DIR/curated_figures.md"
  FIGURES_INVENTORY="$WORKING_DIR/figures_inventory.md"
  # v0.4 M1/M3: Phase-0 reuse/originate staging (phase0_reuse.py output).
  # Mirrors draft_paths.py DraftPaths.phase0_dir / *_phase0.
  PHASE0_DIR="$WORKING_DIR/00_phase0"
  METHODS_PROVENANCE_PHASE0="$PHASE0_DIR/methods_provenance.md"
  CLAIM_INVENTORY_PHASE0="$PHASE0_DIR/claim_inventory.tsv"
  DIAGRAM_REPAIR="$WORKING_DIR/diagram_repair_report.md"
  NEXT_ACTIONS="$WORKING_DIR/next_actions.md"
  SLIDE_SPEC="$WORKING_DIR/slide_spec.json"
  # v0.3.3 image-gen working-zone artifacts (mirrors draft_paths.py)
  IMAGE_DECISIONS_JSON="$WORKING_DIR/05_image_decisions.json"
  IMAGE_MANIFEST_JSON="$IMAGES_DIR/manifest.json"
  # audit/
  STATE_JSON="$AUDIT_DIR/state.json"
  COST_LOG="$AUDIT_DIR/cost-log.jsonl"
  STAGE_METADATA="$AUDIT_DIR/stage-metadata.json"
  STAGE_LOGS_DIR="$AUDIT_DIR/stage-logs"
  SNAPSHOTS_DIR="$AUDIT_DIR/snapshots"
  MANUAL_EDITS_DIR="$AUDIT_DIR/manual-edits"
  RUNS_DIR="$AUDIT_DIR/runs"
  ADVERSARIAL_REVIEW_JSON="$AUDIT_DIR/adversarial_review.json"
  ADVERSARIAL_REVIEW_MD="$AUDIT_DIR/adversarial_review.md"
  QUANT_GROUNDING_JSON="$AUDIT_DIR/quantitative_grounding.json"
  QUANT_GROUNDING_MD="$AUDIT_DIR/quantitative_grounding.md"
  REVISE_LOOP_METADATA="$AUDIT_DIR/revise_loop_metadata.json"
  # v0.3.3 image-gen audit-zone artifacts
  IMAGE_PROVENANCE_JSON="$AUDIT_DIR/image_provenance.json"
  PRE_IMAGE_GEN_SNAPSHOTS_DIR="$SNAPSHOTS_DIR/03_slides_pre_image_gen"
  LAST_RENDER_HASH="$AUDIT_DIR/last-render.json"
  LAST_RENDER_PPTX="$SNAPSHOTS_DIR/last-render.pptx"
}

init_draft_layout "$OUTDIR"
set_draft_paths "$OUTDIR"
# v0.5.1/D-075: build the v3 concat-prompt files now that $AUDIT_DIR is
# populated. No-op for v1/v2 paths.
build_v3_concat_prompts

# --- v0.3.4.2 finalize-on-exit hook ---
# Run finalize_run.py at the end of every orchestrator invocation
# (success, failure, Ctrl-C). Consolidates per-stage .metadata.json
# sidecars into audit/stage-metadata.json + writes
# audit/runs/run-N/summary.json. The hook captures the exit code
# and the start time; finalize_run does the rest.
#
# trap order: EXIT fires after the script exits (any reason). It
# runs in the same shell so OUTDIR + RUN_STARTED_AT are visible.
# Errors from finalize_run.py are tolerated — it shouldn't change
# the orchestrator's reported exit code.
RUN_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
finalize_run_on_exit() {
  local rc=$?
  if [[ -d "$OUTDIR/audit" ]]; then
    "$PYTHON_BIN" "$TOOLS_DIR/finalize_run.py" write \
      --draft-dir "$OUTDIR" \
      --exit-code "$rc" \
      --started-at "$RUN_STARTED_AT" \
      2>/dev/null || true
  fi
  return $rc
}
trap finalize_run_on_exit EXIT

# --- Resume validation: verify required files exist for the resume point ---
# Each stage has prerequisites that must already be on disk; fail fast if
# they're missing rather than running the LLM and then crashing in merge.
validate_resume_prereqs() {
  local stage="$1"
  local missing=()
  case "$stage" in
    throughline)
      [[ -f "$PLAN_PATH" ]] || missing+=("$PLAN_PATH") ;;
    phase0_tooling)
      # v0.4 M3: phase0_tooling runs after the throughline gate; its own
      # inputs (REPORT.md / notebooks) are project-level and always present.
      [[ -f "$THROUGHLINE_PATH" ]] || missing+=("$THROUGHLINE_PATH") ;;
    substory_design)
      [[ -f "$PLAN_PATH" ]] || missing+=("$PLAN_PATH")
      [[ -f "$THROUGHLINE_PATH" ]] || missing+=("$THROUGHLINE_PATH") ;;
    intro)
      [[ -f "$PLAN_PATH" ]] || missing+=("$PLAN_PATH")
      [[ -f "$THROUGHLINE_PATH" ]] || missing+=("$THROUGHLINE_PATH")
      [[ -f "$SUBSTORIES_PATH" ]] || missing+=("$SUBSTORIES_PATH") ;;
    slide_compose)
      [[ -f "$PLAN_PATH" ]] || missing+=("$PLAN_PATH")
      [[ -f "$THROUGHLINE_PATH" ]] || missing+=("$THROUGHLINE_PATH")
      [[ -f "$SUBSTORIES_PATH" ]] || missing+=("$SUBSTORIES_PATH")
      [[ -f "$SLIDES_DIR/intro.json" ]] || missing+=("$SLIDES_DIR/intro.json") ;;
    image_gen)
      # v0.3.3: image_gen needs slide_compose fragments AND throughline +
      # substory paths (fed to ai_image_prompt.v1 as context).
      [[ -f "$THROUGHLINE_PATH" ]] || missing+=("$THROUGHLINE_PATH")
      [[ -f "$SUBSTORIES_PATH" ]] || missing+=("$SUBSTORIES_PATH")
      [[ -d "$SLIDES_DIR" ]] || missing+=("$SLIDES_DIR (no fragments)")
      ;;
    merge)
      [[ -f "$PLAN_PATH" ]] || missing+=("$PLAN_PATH")
      [[ -f "$THROUGHLINE_PATH" ]] || missing+=("$THROUGHLINE_PATH")
      [[ -f "$SUBSTORIES_PATH" ]] || missing+=("$SUBSTORIES_PATH")
      [[ -f "$SLIDES_DIR/intro.json" ]] || missing+=("$SLIDES_DIR/intro.json")
      # Per-substory fragments validated dynamically in stage_merge_and_assemble
      ;;
  esac
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: --resume-from $stage requires the following files in --draft-dir," >&2
    echo "       but they are missing:" >&2
    for f in "${missing[@]}"; do echo "         - $f" >&2; done
    echo "       Pick an earlier --resume-from stage or use a different draft." >&2
    echo "" >&2
    echo "       Note: v0.3.1 changed the per-draft layout. If --draft-dir was" >&2
    echo "       created by v0.3.0 or earlier, the old layout is incompatible —" >&2
    echo "       start a fresh draft." >&2
    exit 1
  fi
}
if [[ -n "$RESUME_FROM" && "$RESUME_FROM" != "plan" ]]; then
  validate_resume_prereqs "$RESUME_FROM"
fi

echo "==================================================================" >&2
echo "BERIL Presentation Maker — Smoke Run" >&2
echo "==================================================================" >&2
echo "  project:      $PROJECT_ID" >&2
echo "  mode:         $MODE" >&2
echo "  tier:         $TIER" >&2
echo "  draft dir:    $OUTDIR" >&2
echo "  auto-advance: $AUTO_ADVANCE" >&2
echo "  model:        $MODEL" >&2
if [[ -n "$RESUME_FROM" ]]; then
  echo "  resume from:  $RESUME_FROM (skipping all earlier stages)" >&2
fi
echo "==================================================================" >&2

# ==============================================================================
# Helpers
# ==============================================================================

# Stamp a placeholder at path so the parser has a target to verify against.
claim_file() {
  local path="$1"
  local label="$2"
  local ext="${path##*.}"
  if [[ "$ext" == "json" ]]; then
    echo "{\"status\": \"in_progress\", \"label\": \"$label\"}" > "$path"
  else
    echo "<!-- Stage in progress: $label — started $(date -u +%Y-%m-%dT%H:%M:%SZ) -->" > "$path"
  fi
}

# Invoke claude with the standard adversarial pattern, piped through the
# stream parser for Write verification + cost summary.
invoke_claude() {
  local sys_prompt_file="$1"
  local user_prompt="$2"
  local expected_path="$3"
  local label="$4"

  if ! command -v claude &>/dev/null; then
    echo "Error: 'claude' CLI not on PATH" >&2
    return 1
  fi

  local sys_prompt
  sys_prompt="$(cat "$sys_prompt_file")"

  local use_parser=1
  if [[ "$NO_STREAM" == "1" ]]; then use_parser=0; fi
  if ! command -v python3 &>/dev/null; then use_parser=0; fi
  if [[ ! -f "$TOOLS_DIR/stream_progress.py" ]]; then use_parser=0; fi

  if [[ "$use_parser" == "1" ]]; then
    local log_file="${expected_path}.stream.log"
    local meta_file="${expected_path}.metadata.json"
    set -o pipefail
    CLAUDECODE= claude -p \
      --model "$MODEL" \
      --system-prompt "$sys_prompt" \
      --allowedTools "$CLAUDE_TOOLS" \
      --dangerously-skip-permissions \
      --output-format stream-json \
      --verbose \
      "$user_prompt" \
      < /dev/null \
      | "$PYTHON_BIN" "$TOOLS_DIR/stream_progress.py" \
          --expected-write-path "$expected_path" \
          --log "$log_file" \
          --model "$MODEL" \
          --metadata-out "$meta_file" \
          --label "$label" \
          > /dev/null
    local rc=$?
    [[ $rc -eq 0 ]] && rm -f "$log_file"
    return $rc
  else
    CLAUDECODE= claude -p \
      --model "$MODEL" \
      --system-prompt "$sys_prompt" \
      --allowedTools "$CLAUDE_TOOLS" \
      --dangerously-skip-permissions \
      "$user_prompt" \
      < /dev/null
  fi
}

# Retry-on-silent-failure wrapper: rc=2 from parser means Write was never
# invoked (the prompt produced a chat response instead). Retry up to
# 3 times with escalation messaging.
invoke_claude_with_retry() {
  local sys_prompt_file="$1"
  local base_user_prompt="$2"
  local expected_path="$3"
  local label="$4"

  local MAX=3
  local attempt=1
  local prompt rc

  while [[ $attempt -le $MAX ]]; do
    if [[ $attempt -gt 1 ]]; then
      echo "  Retry $attempt/$MAX for $label (Write was not invoked)" >&2
      prompt="ATTEMPT $attempt OF $MAX — the previous attempt produced output \
but did not call the Write tool. The artifact was lost. THIS ATTEMPT \
MUST CALL THE Write TOOL with the absolute path. Do not produce the \
artifact as a chat response under any circumstance.

${base_user_prompt}"
    else
      prompt="$base_user_prompt"
    fi

    claim_file "$expected_path" "$label"
    invoke_claude "$sys_prompt_file" "$prompt" "$expected_path" "$label"
    rc=$?

    if [[ $rc -eq 0 ]]; then return 0; fi
    if [[ $rc -eq 2 ]]; then
      rm -f "$expected_path"
      attempt=$((attempt + 1))
      continue
    fi
    if [[ $rc -eq 3 ]]; then
      echo "Error: $label invoked Write on the wrong path (not retryable)" >&2
      return 1
    fi
    if [[ $rc -eq 4 ]]; then
      # 2026-04-27 #71: Anthropic API transient error
      # (overloaded_error / rate_limit / 503). Backoff + retry.
      local backoff=$(( 5 * attempt ))   # 5s, 10s, 15s
      echo "  API transient error — sleeping ${backoff}s before retry $((attempt + 1))/$MAX" >&2
      sleep "$backoff"
      rm -f "$expected_path"
      attempt=$((attempt + 1))
      continue
    fi
    echo "Error: $label failed (exit $rc)" >&2
    return 1
  done

  echo "Error: $label failed across $MAX attempts" >&2
  echo "  Stream log preserved at: ${expected_path}.stream.log" >&2
  return 1
}

# ==============================================================================
# Stages
# ==============================================================================

stage_plan() {
  local out="$PLAN_PATH"
  echo "" >&2
  echo "[Stage 1/4] plan" >&2
  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
MODE=$MODE
TIER_HINT=$TIER
AUDIENCE=$AUDIENCE

Run the plan stage as defined in the system prompt. Read the project's \
REPORT.md, RESEARCH_PLAN.md, notebooks, and any pre-existing review files. \
Build the critical-analysis inventory and seed 2-3 throughline candidates. \
Write the result to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/plan.v1.md" "$user_prompt" "$out" "plan"
}

stage_throughline() {
  local out="$THROUGHLINE_CANDIDATES"
  echo "" >&2
  echo "[Stage 2/4] throughline (candidates)" >&2
  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
PLAN_PATH=$PLAN_PATH
MODE=$MODE
TIER=$TIER

Run the throughline stage. Read the plan's critical-analysis inventory \
and seed candidates. Produce 2-3 throughline candidates with evidence \
maps. Write the result to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/throughline.v1.md" "$user_prompt" "$out" "throughline"
}

# Throughline pick gate. v0.3.6 (2026-05-05): replaced TTY-blocking
# `read -r pick </dev/tty` with halt-and-handoff (paper-writer
# pattern). When --auto-advance is set: auto-pick TL1 (legacy CI/
# unattended-smoke behavior, unchanged). Otherwise: write
# <draft_dir>/.handoff.json describing the gate state, print a clear
# "what to do next" message to stderr, and exit 0 cleanly. The
# `beril-presentation-maker continue <draft_dir> --pick TLN` Python
# command (or the /beril-presentation-maker slash command's two-stage
# flow) reads the handoff, picks, and resumes from substory_design.
#
# Live failure 2026-05-05 on KBERDL JupyterHub (ibd_phage_targeting,
# Claude Code background Bash tool): the previous `read </dev/tty`
# fails 100% in TTY-less contexts. Hub auto-backgrounds Claude Code's
# bash invocations; every hub participant hits this gate. The
# halt-and-handoff pattern matches paper-writer (which never had this
# bug because it was designed asynchronously from day one).
#
# Full state.json + Phase enum (paper-writer's complete pattern) is
# v0.4.0 work post-event; this v0.3.6 ships a single-purpose handoff
# at the one gate that 100% of participants hit.
gate_throughline_pick() {
  local candidates="$THROUGHLINE_CANDIDATES"
  local out="$THROUGHLINE_PATH"

  if [[ ! -f "$candidates" ]]; then
    echo "Error: throughline candidates not found at $candidates" >&2
    return 1
  fi

  if [[ $AUTO_ADVANCE -eq 1 ]]; then
    local pick="TL1"
    echo "  [auto-advance] picking $pick" >&2
    "$PYTHON_BIN" "$TOOLS_DIR/parse_throughline_candidates.py" \
      --candidates "$candidates" \
      --pick "$pick" \
      --out "$out"
    return $?
  fi

  # Halt-and-handoff: write .handoff.json, print message, exit 0.
  emit_throughline_handoff "$candidates" || {
    echo "Error: failed to emit throughline handoff" >&2
    return 1
  }

  echo "" >&2
  echo "==================================================================" >&2
  echo "  HALT: throughline-pick gate (v0.3.6 halt-and-handoff)" >&2
  echo "==================================================================" >&2
  echo "  Stages 1-2 complete. Throughline candidates written to:" >&2
  echo "    $candidates" >&2
  echo "" >&2
  echo "  Pick a candidate (TL1, TL2, ...) and run:" >&2
  echo "    beril-presentation-maker continue $OUTDIR --pick TLN" >&2
  echo "" >&2
  echo "  For unattended/CI runs, re-invoke with --auto-advance to" >&2
  echo "  auto-pick TL1 and run end-to-end without halting." >&2
  echo "==================================================================" >&2

  # Exit 0: clean halt, NOT failure. Slash command reads .handoff.json
  # to disambiguate "halted at gate" from "pipeline complete." Paper-
  # writer uses rc=0 for both states + state.json's `phase` field.
  exit 0
}

# v0.3.6: emit narrative/.handoff.json describing the throughline-pick
# gate state. Slash command reads this to present candidates via
# AskUserQuestion. continue --pick TLN validates against this file.
#
# Wait — actually puts handoff at draft root (<draft>/.handoff.json),
# matching paper-writer's location. Outside the 4-zone layout
# (deliverable/narrative/working/audit) deliberately — it's
# coordination state, not deliverable/narrative/working/audit content.
emit_throughline_handoff() {
  local candidates="$1"
  local handoff="$OUTDIR/.handoff.json"

  "$PYTHON_BIN" - "$candidates" "$handoff" "$OUTDIR" <<'PYEOF'
import json, os, re, sys

candidates_path, handoff_path, draft_dir = sys.argv[1], sys.argv[2], sys.argv[3]

with open(candidates_path, encoding="utf-8") as f:
    text = f.read()

# Match all four observed header variants: `## TL1 —`, `## TL1:`,
# `## Candidate TL1 —`, `## Candidate TL1:` (live throughline.v1
# produced the last shape on 2026-04-26; consistent with the grep
# pattern this gate used in the pre-v0.3.6 read-from-TTY codepath).
candidates = []
for m in re.finditer(
    r"^##\s+(Candidate\s+)?(TL\d+)[\s:—–-]+(.+?)$",
    text,
    re.MULTILINE,
):
    cid = m.group(2)
    label = m.group(3).strip()
    if len(label) > 120:
        label = label[:117] + "..."
    candidates.append({"id": cid, "label": label})

if not candidates:
    print(
        f"  ERROR: no `## Candidate TLN: ...` headers found in {candidates_path}",
        file=sys.stderr,
    )
    sys.exit(1)

with open(handoff_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "phase": "throughline_pick",
            "draft_dir": draft_dir,
            "candidates": candidates,
            "candidates_md": candidates_path,
            "next_command": (
                f"beril-presentation-maker continue {draft_dir} --pick TLN"
            ),
        },
        f,
        ensure_ascii=False,
        indent=2,
    )

print(
    f"  wrote {len(candidates)} candidates to {handoff_path}",
    file=sys.stderr,
)
PYEOF
}

stage_substory_design() {
  local out="$SUBSTORIES_PATH"
  echo "" >&2
  echo "[Stage 3/5] substory_design" >&2
  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
PLAN_PATH=$PLAN_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
MODE=$MODE
TIER=$TIER

Run the substory_design stage. Read the chosen throughline and the plan's \
critical-analysis inventory. Cluster analyses into substories. Compute \
mode-capacity verdict. If overflow, surface the three options and halt. \
Write the result to OUT_PATH."

  invoke_claude_with_retry "$(_substory_design_prompt_path)" "$user_prompt" "$out" "substory_design"
}

# v0.4 M3 (V0_4_ARCHITECTURE.md §16 M3 / §20.8; M3_PUNCH_LIST.md Tier A;
# closes M1 Tier F1). Phase-0 tooling: invokes the M1 helper
# phase0_reuse.py to reuse-or-originate the two v0.4 Phase-0 artifacts
# (claim_inventory.tsv + methods_provenance.md) under working/00_phase0/.
# Runs only on the v0.4 path, before deck_outline. Reuse from a sibling
# papers/draft_*/ is the default; originate (via the vendored
# extract_methods.py / extract_claims.py) is the no-paper fallback and is
# the only path that spends LLM tokens (~$0.05-0.10). An unchanged-input
# re-run is a no-op (hash cache in audit/phase0.jsonl). Fail-loud: a
# non-zero exit fails the stage — claim_inventory feeds deck_outline's
# grounded headline-slot assignment, the load-bearing v0.4 quality lever.
stage_phase0_tooling() {
  echo "" >&2
  echo "[Stage 2.5/5] phase0_tooling (claim_inventory + methods_provenance)" >&2

  local log="$STAGE_LOGS_DIR/phase0_tooling.log"
  if "$PYTHON_BIN" "$TOOLS_DIR/phase0_reuse.py" \
      --project-dir "$PROJECT_DIR" \
      --talk-draft-dir "$OUTDIR" \
      --artifact all \
      > "$log" 2>&1; then
    sed 's/^/    /' "$log" >&2
    echo "  -> Phase-0 artifacts ready under $PHASE0_DIR" >&2
    return 0
  else
    local rc=$?
    sed 's/^/    /' "$log" >&2
    echo "  ERROR: phase0_reuse.py exited $rc — Phase-0 artifacts not ready." >&2
    echo "         claim_inventory.tsv / methods_provenance.md feed deck_outline;" >&2
    echo "         full log: $log" >&2
    return 1
  fi
}

# v0.4 M2 (M2-lite — V0_4_ARCHITECTURE.md §20 / D-042). The deck-outline
# call: substory clustering PLUS the cross-section coordination
# prescriptions (per-section headline slot, transition-in/out, scoped
# figures; deck-level register / arc / image budget). Engaged by
# --architecture-pipeline v0_4; the v0.3.x default runs
# stage_substory_design at this slot instead. Writes the same
# 02_substories.md path (enriched, backward-compatible skeleton).
stage_deck_outline() {
  local out="$SUBSTORIES_PATH"
  echo "" >&2
  echo "[Stage 3/5] deck_outline (v0.4 — M2-lite)" >&2

  # Phase-0 artifacts (v0.4 M3: produced upstream by stage_phase0_tooling,
  # stage_curate_figures, stage_citation_pool, stage_cross_tenant — the
  # v0.4 dispatch runs all four before deck_outline). deck_outline.v1.md
  # keeps escape hatches for any that are absent.
  local claim_inv="$CLAIM_INVENTORY_PHASE0"
  local methods_prov="$METHODS_PROVENANCE_PHASE0"
  local cross_tenant="$CROSS_TENANT_MD"

  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
PLAN_PATH=$PLAN_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
CLAIM_INVENTORY_PATH=$claim_inv
CURATED_FIGURES_PATH=$CURATED_FIGURES
CITATION_POOL_PATH=$CITATION_POOL_PATH
CROSS_TENANT_PATH=$cross_tenant
METHODS_PROVENANCE_PATH=$methods_prov
MODE=$MODE
TIER=$TIER

Run the deck_outline stage. Read the chosen throughline, the plan's \
critical-analysis inventory, and the Phase-0 artifacts. Cluster analyses \
into substories; for each section prescribe the slide budget, headline \
slot, transition-in/out, and scoped figures; write the deck-level \
register, arc, and image budget. Compute the mode-capacity verdict — if \
overflow, surface the options and halt (D-027). Write the result to \
OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/deck_outline.v1.md" "$user_prompt" "$out" "deck_outline"
}

# Audit divider punchline lengths against the soft 14-word cap.
# Surfaces a warning at run time so the user sees discipline drift
# without a validator-blocking failure (per Adam's "budgets are
# guidelines" framing). 2026-04-27 #79: live failures draft_5 +
# draft_7 produced 18-19 word punchlines.
audit_punchline_lengths() {
  local substories="$SUBSTORIES_PATH"
  local audit_out
  audit_out=$("$PYTHON_BIN" -c "
import sys
sys.path.insert(0, '$TOOLS_DIR')
import parse_substories as ps
content = open('$substories').read()
over = ps.audit_punchline_lengths(content, recommended_max_words=14)
if not over:
    print('  ✓ all divider punchlines within 14-word recommendation')
else:
    print(f'  ⚠ {len(over)} divider punchline(s) exceed 14-word recommendation:')
    for sid, pl, wc in over:
        preview = pl[:80] + ('…' if len(pl) > 80 else '')
        print(f'    {sid}: {wc} words — {preview!r}')
")
  echo "$audit_out" >&2
}

# Conditional gate: only halt if capacity_verdict == overflow.
gate_substory_overflow() {
  local substories="$SUBSTORIES_PATH"
  local verdict
  verdict="$("$PYTHON_BIN" "$TOOLS_DIR/parse_substories.py" \
    --path "$substories" --field capacity_verdict)"

  echo "  capacity verdict: $verdict" >&2

  if [[ "$verdict" == "overflow" ]]; then
    if [[ $AUTO_ADVANCE -eq 1 ]]; then
      echo "  [auto-advance] overflow detected; halt for user pick" >&2
      echo "  In smoke v1, --auto-advance does NOT auto-pick on overflow." >&2
      echo "  Re-run without --auto-advance and pick drop|escalate|merge." >&2
      return 1
    fi
    echo "" >&2
    echo "==== Mode-capacity overflow — pick an option ====" >&2
    echo "  (a) drop substories — re-run substory_design with picks" >&2
    echo "  (b) escalate mode (talk-15 → talk-30, etc.) — re-run from throughline" >&2
    echo "  (c) merge substories — re-run substory_design with merge directive" >&2
    echo "  (d) PROCEED ANYWAY — accept overrun; budgets are guidelines (2026-04-26)" >&2
    echo -n "Choice (a/b/c/d) [or 'abort']: " >&2
    local choice
    read -r choice </dev/tty
    case "$choice" in
      d|proceed|proceed-anyway)
        echo "  [proceed-anyway] continuing despite mode overflow." >&2
        echo "  The deck will run longer than the mode's typical window." >&2
        return 0 ;;
      a|drop|b|escalate|c|merge)
        echo "  Smoke v1 does not implement re-routing for drop/escalate/merge." >&2
        echo "  The substory_design output stands; subsequent stages will" >&2
        echo "  surface the overflow gap. To proceed cleanly, choose (d)" >&2
        echo "  proceed-anyway, OR re-run from scratch with a larger --mode." >&2
        return 1 ;;
      *)
        echo "  Aborting on overflow." >&2
        return 1 ;;
    esac
  fi
  return 0
}

stage_curate_figures() {
  # 2026-04-27 #68 (Phase 2A.1): scan REPORT.md + notebooks for figure
  # references, produce curated_figures.md with mode-bounded shortlist.
  # Runs between substory_design and intro so slide_compose can pick
  # data_figure layouts from real figure paths instead of skipping
  # them per the escape hatch.
  #
  # Pure Python — no LLM cost. The figure inventory is deterministic
  # from REPORT.md / notebook scans.
  echo "" >&2
  echo "[Stage 3.5/5] curate_figures (no LLM)" >&2

  # v0.8/D-093: if 02_substories.md exists, pass it to curate so the
  # per-substory floor kicks in. The curator will guarantee ≥1 figure
  # per substory when the inventory contains a candidate (matched by
  # NB-id on the substory's analyses). May exceed mode budget by up
  # to N_substories; per-substory coverage wins per D-093.
  local _substories_arg=()
  if [[ -f "$NARRATIVE_DIR/02_substories.md" ]]; then
    _substories_arg=(--substories-path "$NARRATIVE_DIR/02_substories.md")
  fi

  # NB: --no-md is a store_true flag (no value); omitting it = produce
  # markdown output, which is what we want.
  if "$PYTHON_BIN" "$TOOLS_DIR/curate_figures.py" curate \
      "$PROJECT_DIR" \
      --mode "$MODE" \
      --output-dir "$WORKING_DIR" \
      "${_substories_arg[@]}" \
      >/dev/null 2>"$STAGE_LOGS_DIR/curate_figures.stderr"; then
    # v0.3.1: curate_figures.py writes directly to working/curated_figures.md
    # via --output-dir pointing at the working/ zone. The legacy
    # figures_curated.md duplicate is killed.
    if [[ -f "$CURATED_FIGURES" ]]; then
      local n_curated
      n_curated="$(grep -c '^### [0-9]\+\.' "$CURATED_FIGURES" 2>/dev/null || echo 0)"
      echo "  -> wrote $CURATED_FIGURES ($n_curated figure(s) curated)" >&2
    else
      echo "  warning: curate_figures.py produced no curated_figures.md" >&2
      # Don't fail — slide_compose's escape hatch handles missing figures
    fi

    # v0.8/D-093 Tier A: run check_curator_figure_floor.py to emit
    # audit/curator_figure_floor.json with per-substory coverage
    # findings. The validator is the suspenders to curate_for_mode's
    # belt — catches drift when the per-substory floor heuristic
    # misses a candidate. Advisory P1; never blocks the pipeline.
    # Requires 02_substories.md (already present at this stage) +
    # curated_figures.md (just written above).
    if [[ -f "$NARRATIVE_DIR/02_substories.md" && -f "$CURATED_FIGURES" ]]; then
      local _ffloor_inv=""
      if [[ -f "$WORKING_DIR/figures_inventory.md" ]]; then
        _ffloor_inv="--inventory $WORKING_DIR/figures_inventory.md"
      fi
      if "$PYTHON_BIN" "$TOOLS_DIR/check_curator_figure_floor.py" \
          --project-dir "$PROJECT_DIR" \
          --substories "$NARRATIVE_DIR/02_substories.md" \
          --curated-figures "$CURATED_FIGURES" \
          $_ffloor_inv \
          --draft-dir "$OUTDIR" \
          >/dev/null 2>"$STAGE_LOGS_DIR/check_curator_figure_floor.stderr"; then
        if [[ -f "$AUDIT_DIR/curator_figure_floor.json" ]]; then
          local _n_uncovered
          _n_uncovered="$("$PYTHON_BIN" -c "import json,sys; d=json.load(open('$AUDIT_DIR/curator_figure_floor.json')); print(d.get('summary',{}).get('n_substories_uncovered',0))" 2>/dev/null || echo "?")"
          echo "  -> figure-floor check: $_n_uncovered substory/ies uncovered (advisory)" >&2
        fi
      else
        echo "  warning: check_curator_figure_floor.py exited non-zero — see $STAGE_LOGS_DIR/check_curator_figure_floor.stderr" >&2
        cat "$STAGE_LOGS_DIR/check_curator_figure_floor.stderr" >&2 || true
      fi
    fi
    return 0
  else
    echo "  warning: curate_figures.py exited non-zero — see $STAGE_LOGS_DIR/curate_figures.stderr" >&2
    cat "$STAGE_LOGS_DIR/curate_figures.stderr" >&2 || true
    # Don't fail the run; figures are an enrichment, not a blocker
    return 0
  fi
}

stage_citation_pool() {
  # 2026-04-27 #72 (Phase 2B.1): build a verified citation pool for
  # the deck. Runs after substory_design / parallel to curate_figures.
  # If PROJECT_DIR has a sibling papers/draft_*/ with an existing
  # citation_pool.json, reuse it (saves verify-by-resolution cost).
  # Otherwise, run citation_pool.v1.md to verify-by-resolution every
  # claim's source per its 9-field schema. Output:
  # {OUTDIR}/citation_pool.json. slide_compose's CITATION_POOL_PATH
  # points here; merge populates the references slide from it.
  echo "" >&2
  echo "[Stage 3.7/5] citation_pool" >&2

  local pool_path="$CITATION_POOL_PATH"

  # Check for sibling paper draft to reuse from
  local paper_dir=""
  if [[ -d "$PROJECT_DIR/papers" ]]; then
    # Find latest paper draft with a citation_pool.json or pool.json
    local latest_paper
    latest_paper=$(ls -1d "$PROJECT_DIR/papers/draft_"* 2>/dev/null | sort -V | tail -1)
    if [[ -n "$latest_paper" ]] && \
       { [[ -f "$latest_paper/citation_pool.json" ]] || [[ -f "$latest_paper/pool.json" ]]; }; then
      paper_dir="$latest_paper"
      echo "  -> found sibling paper draft: $latest_paper (reuse-from-paper enabled)" >&2
      "$PYTHON_BIN" "$TOOLS_DIR/citation_pool.py" reuse-from-paper \
        "$paper_dir" "$OUTDIR" 2>&1 | sed 's/^/    /' >&2 || \
        echo "    warning: reuse-from-paper failed; will start fresh" >&2
    fi
  fi

  local user_prompt="PROJECT_ROOT=$PROJECT_DIR
DRAFT_DIR=$OUTDIR
POOL_JSON_PATH=$pool_path
MODE=paper
TIER=$TIER
THROUGHLINE_PATH=$THROUGHLINE_PATH
EXISTING_POOL_PATH=$pool_path

Run the citation_pool stage. Build a verify-by-resolution pool of \
citations supporting the throughline + critical-analysis inventory. \
Cap at 80 entries (D-009). If EXISTING_POOL_PATH already exists \
(reuse-from-paper landed), trust those entries verbatim and ADD only \
talk-needed entries with notes='added by talk'. Write the result as \
JSON to POOL_JSON_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/citation_pool.v1.md" \
    "$user_prompt" "$pool_path" "citation_pool"
}

stage_cross_tenant() {
  # 2026-04-27 #73 (Phase 2B.2): two-step.
  # (a) Run extract_cross_tenant.py to detect signal — pure Python.
  #     If no signal, skip the LLM call entirely (saves ~\$0.30).
  # (b) If signal present, run cross_tenant.v1.md to compose a single
  #     cross_tenant_integration slide (deck-level; spliced between
  #     last substory and acknowledgments at merge time).
  echo "" >&2
  echo "[Stage 3.8/5] cross_tenant" >&2

  local signal_md="$CROSS_TENANT_MD"
  local signal_json="$CROSS_TENANT_JSON"
  local fragment_path="$SLIDES_DIR/cross_tenant.json"

  # Step (a): detect signal
  "$PYTHON_BIN" "$TOOLS_DIR/extract_cross_tenant.py" \
    "$PROJECT_DIR" \
    --out "$signal_md" \
    --json "$signal_json" \
    --quiet 2>&1 | sed 's/^/    /' >&2

  # Step (b): check if we have signal
  local has_signal
  has_signal=$("$PYTHON_BIN" -c "
import json, sys
try:
    d = json.load(open('$signal_json'))
    print('false' if d.get('no_signal_fallback') else 'true')
except Exception as e:
    print('false', file=sys.stderr)  # if extract fails, skip
    print('false')
")

  if [[ "$has_signal" != "true" ]]; then
    echo "  no cross-tenant signal detected — skipping LLM call" >&2
    return 0
  fi

  echo "  cross-tenant signal detected — composing slide" >&2

  local user_prompt="OUT_PATH=$fragment_path
PROJECT_DIR=$PROJECT_DIR
SIGNAL_PATH=$signal_md
PLAN_PATH=$PLAN_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
SUBSTORY_PATH=$SUBSTORIES_PATH
CITATION_POOL_PATH=$CITATION_POOL_PATH
MODE=$MODE
TIER=$TIER

Run the cross_tenant stage. The signal file lists detected K-BERDL \
tenants, databases, sibling-project references, and KBase URLs. \
Compose a SINGLE cross_tenant_integration slide presenting honestly \
what cross-tenant integration the project leverages. Write the result \
as a JSON fragment with kind='cross_tenant_set' to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/cross_tenant.v1.md" \
    "$user_prompt" "$fragment_path" "cross_tenant"
}

stage_deck_close() {
  # v0.7/D-086 Tier C.3: deck-spanning closing-synthesis slide.
  # Two-step (mirrors stage_cross_tenant per D-086 + Adam Tier-0 DQ
  # "Separate stage emits deck_close.json fragment"):
  # (a) Run extract_deck_close.py to pull the structured signal from
  #     narrative/02_substories.md (per-substory Conclusion-for-next)
  #     + narrative/00_throughline.md (unified_point) + REPORT.md
  #     (forward_call from Future-directions / Next-steps sections).
  # (b) If signal present, run deck_close.v1.md to compose a single
  #     deck_close slide. Composer reads structured fields VERBATIM
  #     per D-086; if no signal (curator-stage failure), skip the
  #     LLM call and emit an empty-slides fragment so the merger
  #     splices nothing — Tier C.0's mode-gated soft-warning will
  #     surface the absence on talk-30 STRONG runs.
  #
  # Mode-gating per Adam Tier-0 DQ2: only fire on talk-30 STRONG;
  # talk-45 / talk-15 / lightning-5 skip silently. The skip is
  # SILENT (not "skipped advisory") because deck_close is optional
  # by design on sub-STRONG modes; the per-substory C-slots
  # provide sufficient closure at those talk lengths.
  echo "" >&2
  echo "[Stage 4.5/5] deck_close" >&2

  if [[ "$MODE" != "talk-30" ]]; then
    echo "  mode=$MODE — deck_close is optional below talk-30 STRONG (D-086); skipping" >&2
    return 0
  fi

  local signal_json="$DECK_CLOSE_SIGNAL_JSON"
  local fragment_path="$SLIDES_DIR/deck_close.json"

  # Step (a): extract signal
  "$PYTHON_BIN" "$TOOLS_DIR/extract_deck_close.py" \
    "$OUTDIR" \
    --out "$signal_json" \
    --quiet 2>&1 | sed 's/^/    /' >&2

  # Step (b): check signal + decide whether to compose
  local has_signal
  has_signal=$("$PYTHON_BIN" -c "
import json, sys
try:
    d = json.load(open('$signal_json'))
    print('false' if d.get('no_signal_fallback') else 'true')
except Exception:
    print('false', file=sys.stderr)
    print('false')
")

  if [[ "$has_signal" != "true" ]]; then
    echo "  no deck_close signal detected (curator-stage extraction" >&2
    echo "  could not pull per-substory takeaways) — emitting empty" >&2
    echo "  fragment so the merger splices nothing. The Tier C.0" >&2
    echo "  mode-gated soft-warning will surface the absent slide" >&2
    echo "  on talk-30 for Tier-F review." >&2
    # Emit an empty-slides fragment so merge_compose_fragments
    # doesn't crash on a missing file when the user passes
    # --deck-close-fragment-path; the merger's "splice if non-empty"
    # logic handles the empty case.
    cat > "$fragment_path" <<EOF
{
  "schema_version": "compose-fragment.v1",
  "kind": "deck_close_set",
  "mode": "$MODE",
  "tier": "$TIER",
  "slides": []
}
EOF
    return 0
  fi

  echo "  deck_close signal extracted — composing slide" >&2

  local user_prompt="OUT_PATH=$fragment_path
PROJECT_DIR=$PROJECT_DIR
SIGNAL_PATH=$signal_json
PLAN_PATH=$PLAN_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
SUBSTORY_PATH=$SUBSTORIES_PATH
MODE=$MODE
TIER=$TIER

Run the deck_close stage. The signal file (SIGNAL_PATH, produced \
by extract_deck_close.py) contains the curator-approved structured \
fields (unified_point + key_takeaways + forward_call + data_source) \
extracted from the throughline + per-substory Conclusion-for-next \
fields + REPORT.md Future-directions section. Per D-086, compose \
the slide content VERBATIM from the signal (light typography polish \
allowed; no synthesis drift). Write a SINGLE deck_close slide as a \
JSON fragment with kind='deck_close_set' to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/deck_close.v1.md" \
    "$user_prompt" "$fragment_path" "deck_close"
}

stage_intro() {
  local out="$SLIDES_DIR/intro.json"
  echo "" >&2
  echo "[Stage 4/5] intro" >&2

  # Mode-aware short-circuit: lightning-5 and posters skip intro entirely.
  # Still emit a fragment with empty slides[] so the merge step has a
  # consistent input. The prompt itself handles this case, but emitting
  # the fragment from the orchestrator side avoids paying for an LLM
  # call when we know the answer (lightning/poster modes always emit 0
  # intro slides per intro.v1.md's mode-aware framing).
  if [[ "$MODE" == "lightning-5" || "$MODE" == "poster-h" || "$MODE" == "poster-v" ]]; then
    echo "  mode=$MODE has zero intro slide budget — emitting empty fragment" >&2
    cat > "$out" <<EOF
{
  "schema_version": "compose-fragment.v1",
  "kind": "intro",
  "mode": "$MODE",
  "tier": "$TIER",
  "n_intro_slides_target": 0,
  "slides": []
}
EOF
    return 0
  fi

  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
PLAN_PATH=$PLAN_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
SUBSTORY_PATH=$SUBSTORIES_PATH
MODE=$MODE
TIER=$TIER

Run the intro stage. Read THROUGHLINE, SUBSTORIES, PLAN, and the \
project's REPORT.md + RESEARCH_PLAN.md. Produce mode-aware intro \
slides covering background/significance, goal, and approach overview. \
For talk-30/45 emit 3-4 slides; for talk-15 emit 1-2. Goal must be \
derivable from RESEARCH_PLAN; numbers verbatim from REPORT. No \
marketing voice. Write the result to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/intro.v1.md" "$user_prompt" "$out" "intro"
}

# v0.4 M3 helpers — per-section composer brief extraction.
# _m3_outline_field echoes a parse_deck_outline.py field (a per-section
# "S{N}<TAB>value" block, or a deck-level single value); empty on any
# parse failure — the brief is advisory, so a missing field is non-fatal.
_m3_outline_field() {
  "$PYTHON_BIN" "$TOOLS_DIR/parse_deck_outline.py" \
    --path "$1" --field "$2" 2>/dev/null || true
}

# _m3_section_line pulls substory <sid>'s value out of a per-section
# field block (tab-separated "S{N}<TAB>value" lines).
_m3_section_line() {
  printf '%s\n' "$1" | awk -F'\t' -v s="$2" '$1 == s {print $2; exit}'
}

# Runner for ONE v0.4 substory composer — invoked by wp_run_pool in a
# backgrounded subshell that inherits these globals. Its last command is
# invoke_claude_with_retry, so the subshell exits with that rc (rc=2
# Write-not-invoked / rc=4 API-transient are handled inside the wrapper).
_compose_one_substory() {
  local sid="$1"
  local out="$SLIDES_DIR/${sid}_slides.json"
  local ti to budget headline figs
  ti=$(_m3_section_line "$_M3_BRIEF_TRANSITIONS_IN" "$sid")
  to=$(_m3_section_line "$_M3_BRIEF_TRANSITIONS_OUT" "$sid")
  budget=$(_m3_section_line "$_M3_BRIEF_BUDGETS" "$sid")
  headline=$(_m3_section_line "$_M3_BRIEF_HEADLINE_SLOTS" "$sid")
  figs=$(_m3_section_line "$_M3_BRIEF_SCOPED_FIGURES" "$sid")

  # v0.5/D-071: per-substory Question + Conclusion (v3 prompts only).
  local sub_question="" sub_conclusion=""
  if [[ "$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
    sub_question=$(_m3_section_line "$_M3_BRIEF_QUESTIONS" "$sid")
    sub_conclusion=$(_m3_section_line "$_M3_BRIEF_CONCLUSIONS" "$sid")
  fi

  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
SUBSTORY_PATH=$_M3_SUBSTORIES_PATH
SUBSTORY_ID=$sid
THROUGHLINE_PATH=$THROUGHLINE_PATH
PLAN_PATH=$PLAN_PATH
CURATED_FIGURES_PATH=$CURATED_FIGURES
CITATION_POOL_PATH=$CITATION_POOL_PATH
MODE=$MODE
TIER=$TIER
TRANSITION_IN=$ti
TRANSITION_OUT=$to
SECTION_BUDGET=$budget
HEADLINE_SLOT=$headline
SCOPED_FIGURES=$figs
DECK_REGISTER=$_M3_BRIEF_REGISTER
DECK_ARC=$_M3_BRIEF_ARC"

  # v0.5/D-071 + D-072: append v3-only inputs. v1/v2 prompts don't
  # reference these fields, so injecting them would just bloat the
  # user prompt without effect; gate on PROMPTS_VERSION=v3.
  if [[ "$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
    user_prompt="${user_prompt}
SUBSTORY_QUESTION=$sub_question
SUBSTORY_CONCLUSION=$sub_conclusion
ALLOWLIST_TERMS=$_M3_ALLOWLIST_TERMS"
  fi

  user_prompt="${user_prompt}

Run the slide_compose stage for substory $sid. SUBSTORY_PATH is the \
enriched whole-deck outline; compose ONLY substory $sid's section. The \
per-section brief above (TRANSITION_IN / TRANSITION_OUT, SECTION_BUDGET, \
HEADLINE_SLOT, SCOPED_FIGURES) and the deck-level DECK_REGISTER / \
DECK_ARC are advisory cross-section coordination context — not a rigid \
contract. Read REPORT.md sections cited by the analyses; verify any \
quantitative claim before placing it on a slide. CURATED_FIGURES_PATH / \
CITATION_POOL_PATH may not exist — emit slides without figures and \
without citations[] entries in that case (the prompt's escape hatches \
cover this). Write the result to OUT_PATH."

  invoke_claude_with_retry "$(_slide_compose_prompt_path)" \
    "$user_prompt" "$out" "slide_compose-$sid"
}

# v0.3.x slide_compose: sequential per-substory composition with
# PRIOR_SUBSTORY_OUTPUTS chaining — each composer sees the prior
# substories' composed fragments. Unchanged from pre-M3.
_slide_compose_v0_3() {
  local substories="$1"; shift
  local prior_outputs="" sid

  # v0.5/D-071 + D-072: pre-extract Q/Conclusion + allowlist once for
  # the whole loop (v3 prompts only); reused per-substory below.
  local _v3_questions="" _v3_conclusions="" _v3_allowlist=""
  if [[ "$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
    _v3_questions="$(_m3_outline_field "$substories" questions)"
    _v3_conclusions="$(_m3_outline_field "$substories" conclusions)"
    local _allowlist_path="$PROJECT_DIR/references/register_allowlist.md"
    if [[ -f "$_allowlist_path" ]]; then
      _v3_allowlist="$(grep -vE '^\s*(#|$)' "$_allowlist_path" \
        2>/dev/null | tr '\n' ',' | sed 's/,$//' || true)"
    fi
  fi

  for sid in "$@"; do
    echo "" >&2
    echo "  -> composing $sid" >&2
    local out="$SLIDES_DIR/${sid}_slides.json"

    # v0.5/D-071: per-substory Question + Conclusion (v3 prompts only).
    local sub_question="" sub_conclusion=""
    if [[ "$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
      sub_question=$(_m3_section_line "$_v3_questions" "$sid")
      sub_conclusion=$(_m3_section_line "$_v3_conclusions" "$sid")
    fi

    local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
SUBSTORY_PATH=$substories
SUBSTORY_ID=$sid
THROUGHLINE_PATH=$THROUGHLINE_PATH
PLAN_PATH=$PLAN_PATH
CURATED_FIGURES_PATH=$CURATED_FIGURES
CITATION_POOL_PATH=$CITATION_POOL_PATH
MODE=$MODE
TIER=$TIER
PRIOR_SUBSTORY_OUTPUTS=$prior_outputs"

    # v0.5/D-071 + D-072: append v3-only inputs (gate on
    # PROMPTS_VERSION=v3; v1/v2 prompts don't reference these).
    if [[ "$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
      user_prompt="${user_prompt}
SUBSTORY_QUESTION=$sub_question
SUBSTORY_CONCLUSION=$sub_conclusion
ALLOWLIST_TERMS=$_v3_allowlist"
    fi

    user_prompt="${user_prompt}

Run the slide_compose stage for substory $sid. The substory's punchline \
and covered analyses are in $substories. Read REPORT.md sections cited \
by the analyses; verify any quantitative claim before placing it on a \
slide. Note: in this smoke run, CURATED_FIGURES_PATH and \
CITATION_POOL_PATH may not exist — emit slides without figures and \
without citations[] entries in that case (the prompt's escape hatches \
cover this). Write the result to OUT_PATH."

    invoke_claude_with_retry "$(_slide_compose_prompt_path)" "$user_prompt" "$out" "slide_compose-$sid"

    # Append to prior_outputs for the next substory's PRIOR context
    if [[ -z "$prior_outputs" ]]; then
      prior_outputs="$out"
    else
      prior_outputs="${prior_outputs},${out}"
    fi
  done

  return 0
}

# v0.4 slide_compose: parallel per-substory composition against the
# shared deck outline. Composers run concurrently (bounded by
# SLIDE_COMPOSE_MAX_PARALLEL, default 5); the enriched 02_substories.md
# outline replaces the v0.3.x PRIOR_SUBSTORY_OUTPUTS chaining as the
# cross-section coordination layer (V0_4_ARCHITECTURE.md §20.3;
# M3_PUNCH_LIST.md Tier B). The per-section brief injected below is
# advisory — the composer-prompt narrowing that consumes it is Tier D.
_slide_compose_v0_4() {
  local substories="$1"; shift
  local max="${SLIDE_COMPOSE_MAX_PARALLEL:-5}"
  echo "  v0.4 parallel composition — $# substory composer(s), max $max concurrent" >&2

  # Per-section coordination brief, extracted ONCE from the enriched
  # 02_substories.md. A field that fails to parse yields an empty block;
  # the brief is advisory, so empty is non-fatal. These globals are read
  # by _compose_one_substory inside each worker subshell.
  _M3_SUBSTORIES_PATH="$substories"
  _M3_BRIEF_TRANSITIONS_IN="$(_m3_outline_field "$substories" transitions_in)"
  _M3_BRIEF_TRANSITIONS_OUT="$(_m3_outline_field "$substories" transitions_out)"
  _M3_BRIEF_BUDGETS="$(_m3_outline_field "$substories" budgets)"
  _M3_BRIEF_HEADLINE_SLOTS="$(_m3_outline_field "$substories" headline_slots)"
  _M3_BRIEF_SCOPED_FIGURES="$(_m3_outline_field "$substories" scoped_figures)"
  _M3_BRIEF_REGISTER="$(_m3_outline_field "$substories" register)"
  _M3_BRIEF_ARC="$(_m3_outline_field "$substories" arc)"
  # v0.5/D-071 + D-072: Q/A/R/C contract fields + register-discipline
  # allowlist. Only populated when --prompts-version v3 to avoid
  # parsing cost on v1/v2 paths where slide_compose ignores them.
  _M3_BRIEF_QUESTIONS=""
  _M3_BRIEF_CONCLUSIONS=""
  _M3_ALLOWLIST_TERMS=""
  if [[ "$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" || "$PROMPTS_VERSION" == "v3.2" || "$PROMPTS_VERSION" == "v3.3" ]]; then
    _M3_BRIEF_QUESTIONS="$(_m3_outline_field "$substories" questions)"
    _M3_BRIEF_CONCLUSIONS="$(_m3_outline_field "$substories" conclusions)"
    # Load per-project register allowlist (D-072) if present.
    local _allowlist_path="$PROJECT_DIR/references/register_allowlist.md"
    if [[ -f "$_allowlist_path" ]]; then
      _M3_ALLOWLIST_TERMS="$(grep -vE '^\s*(#|$)' "$_allowlist_path" \
        2>/dev/null | tr '\n' ',' | sed 's/,$//' || true)"
    fi
  fi

  local _t0
  _t0="$(date +%s)"

  wp_run_pool "$max" "$STAGE_LOGS_DIR" "slide_compose" \
    _compose_one_substory "$@" || {
    echo "Error: one or more parallel slide_compose workers failed" >&2
    return 1
  }

  # v0.4 M3 (E-2): surface the parallel-composition telemetry. Each
  # composer's stream_progress banner went to its worker log (removed
  # on success by wp_run_pool), so the stage was otherwise silent on
  # cost/time — yet the wall-clock here IS the M3 parallelism win, the
  # milestone's primary metric. Read the per-composer .metadata.json
  # sidecars stream_progress wrote (these persist) and print the stage
  # wall-clock + cumulative LLM cost/time. Telemetry only — never fails
  # the stage.
  local _wall=$(( $(date +%s) - _t0 ))
  "$PYTHON_BIN" - "$SLIDES_DIR" "$_wall" "$@" <<'PYEOF' >&2 || true
import json, sys
slides_dir, wall, sids = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
tot_cost, tot_llm = 0.0, 0
for sid in sids:
    try:
        m = json.load(open(f"{slides_dir}/{sid}_slides.json.metadata.json"))
    except Exception:
        print(f"    {sid}: (no metadata sidecar)")
        continue
    c, e = m.get("estimated_cost_usd"), m.get("elapsed_seconds")
    if isinstance(c, (int, float)):
        tot_cost += c
    if isinstance(e, int):
        tot_llm += e
    cs = f"~${c:.3f}" if isinstance(c, (int, float)) else "~$?"
    es = f"{e // 60}:{e % 60:02d}" if isinstance(e, int) else "?"
    print(f"    {sid}: {es}  ·  {cs}")
def fmt(s):
    return f"{s // 60}:{s % 60:02d}"
print(f"  slide_compose (parallel): wall-clock {fmt(wall)}  ·  "
      f"cumulative LLM {fmt(tot_llm)}  ·  ~${tot_cost:.3f}  ·  "
      f"{len(sids)} composers")
PYEOF
  return 0
}

stage_slide_compose() {
  local substories="$SUBSTORIES_PATH"
  echo "" >&2
  echo "[Stage 5/5] slide_compose (per substory)" >&2

  # Enumerate substory IDs from the clustering output (substory_design
  # for v0.3.x; the enriched deck_outline for v0.4 — both keep the
  # backward-compatible `### S{N} —` skeleton parse_substories.py reads).
  local substory_ids
  substory_ids=$("$PYTHON_BIN" "$TOOLS_DIR/parse_substories.py" \
    --path "$substories" --field substory_ids)

  if [[ -z "$substory_ids" ]]; then
    echo "Error: no substory IDs parsed from $substories" >&2
    return 1
  fi

  if [[ "$ARCH_PIPELINE" == "v0_4" ]]; then
    _slide_compose_v0_4 "$substories" $substory_ids
  else
    _slide_compose_v0_3 "$substories" $substory_ids
  fi
}

stage_qa_prep() {
  # 2026-04-27 #74 (Phase 2B.3): whole-deck pass after slide_compose × N.
  # Reads all substory fragments + plan + throughline + substory_design;
  # picks 2-4 hardest audience questions ranked by priority
  # (generalizability > methodology > limitation > consistency >
  # practical) per qa_prep.v1.md. Output is one fragment with
  # kind='qa_anticipated_set'; spliced at deck end before acks.
  echo "" >&2
  echo "[Stage 5.7/7] qa_prep" >&2

  # Mode-aware QA budget: skip for posters (qa makes no sense in poster)
  if [[ "$MODE" == "poster-h" || "$MODE" == "poster-v" ]]; then
    echo "  mode=$MODE — skipping qa_prep (posters don't have Q&A)" >&2
    return 0
  fi

  # Mode-default budget per qa_prep.v1.md
  local qa_budget
  case "$MODE" in
    talk-30)        qa_budget=3 ;;
    talk-15)        qa_budget=2 ;;
    talk-45)        qa_budget=4 ;;
    lightning-5)    qa_budget=1 ;;
    *)              qa_budget=3 ;;
  esac

  local fragment_path="$SLIDES_DIR/qa_anticipated.json"

  # Build comma-separated FRAGMENT_PATHS list (all substory composes)
  local fragment_paths=""
  for f in "$SLIDES_DIR/"S?_slides.json; do
    if [[ -f "$f" ]]; then
      fragment_paths="${fragment_paths}${f},"
    fi
  done
  fragment_paths="${fragment_paths%,}"  # strip trailing comma

  local user_prompt="OUT_PATH=$fragment_path
PROJECT_DIR=$PROJECT_DIR
SUBSTORY_PATH=$SUBSTORIES_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
PLAN_PATH=$PLAN_PATH
FRAGMENT_PATHS=$fragment_paths
CITATION_POOL_PATH=$CITATION_POOL_PATH
MODE=$MODE
TIER=$TIER
QA_SLIDE_BUDGET=$qa_budget

Run the qa_prep stage. Build a weakness inventory from all substory \
fragments + plan inventory's ⚠/✗ glyphs + throughline scope-gap list. \
Pick the top $qa_budget hardest audience questions, weighted toward \
generalizability + methodology + limitation. Each anticipated question \
gets answer_summary (slide body) + answer_detail (speaker reference) + \
specific evidence_pointer. Write the result as a JSON fragment with \
kind='qa_anticipated_set' to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/qa_prep.v1.md" \
    "$user_prompt" "$fragment_path" "qa_prep"
}

stage_speaker_notes() {
  # 2026-04-27 #70: invoke speaker_notes.v1.md per substory after
  # slide_compose runs. The prompt produces markdown with strict H2
  # headers (`## position N — layout — `title``); parse_speaker_notes.py
  # converts to JSON keyed by position; merge_compose_fragments injects
  # into slide_spec.json's per-slide speaker_notes field.
  echo "" >&2
  echo "[Stage 5.5/7] speaker_notes (per substory)" >&2

  local notes_dir="$SPEAKER_NOTES_DIR"
  mkdir -p "$notes_dir"

  local substory_ids
  substory_ids=$("$PYTHON_BIN" "$TOOLS_DIR/parse_substories.py" \
    --path "$SUBSTORIES_PATH" --field substory_ids)
  if [[ -z "$substory_ids" ]]; then
    echo "Error: no substory IDs parsed from $SUBSTORIES_PATH" >&2
    return 1
  fi

  for sid in $substory_ids; do
    echo "" >&2
    echo "  -> notes for $sid" >&2
    local notes_md="$notes_dir/${sid}_speaker_notes.md"
    local notes_json="$notes_dir/${sid}_notes.json"
    local fragment_path="$SLIDES_DIR/${sid}_slides.json"

    # Build prior-notes path list for voice consistency (read-only)
    local prior_notes=""
    for prior in "$notes_dir"/S*_speaker_notes.md; do
      if [[ -f "$prior" && "$prior" != "$notes_md" ]]; then
        prior_notes="${prior_notes}${prior},"
      fi
    done
    prior_notes="${prior_notes%,}"  # strip trailing comma

    local user_prompt="OUT_PATH=$notes_md
PROJECT_DIR=$PROJECT_DIR
FRAGMENT_PATH=$fragment_path
SUBSTORY_PATH=$SUBSTORIES_PATH
THROUGHLINE_PATH=$THROUGHLINE_PATH
PLAN_PATH=$PLAN_PATH
CITATION_POOL_PATH=$CITATION_POOL_PATH
MODE=$MODE
TIER=$TIER
PRIOR_NOTES=$prior_notes

Run the speaker_notes stage for substory $sid. Read the slide_compose \
fragment at FRAGMENT_PATH; for each slide in fragment.slides[], author \
200-400 words of speaker notes using the 5-step scaffold (opening, \
grounding, supporting, caveat, transition). Quantitative claims must \
be REPORT-verbatim. Caveats from plan inventory ⚠/✗ glyphs surface in \
notes. Output as markdown with strict H2 headers per the prompt's \
schema. Write the result to OUT_PATH."

    invoke_claude_with_retry "$PROMPTS_DIR/speaker_notes.v1.md" \
      "$user_prompt" "$notes_md" "speaker_notes-$sid"

    # Parse the markdown to JSON for merge-step injection
    if [[ -f "$notes_md" ]]; then
      "$PYTHON_BIN" "$TOOLS_DIR/parse_speaker_notes.py" \
        --notes "$notes_md" --out "$notes_json" 2>&1 | sed 's/^/    /' >&2 || {
          echo "    warning: parse_speaker_notes failed for $sid; notes won't inject" >&2
      }
    else
      echo "    warning: no notes file written for $sid" >&2
    fi
  done

  return 0
}

stage_image_gen() {
  # v0.3.3: per-slide AI image generation pipeline.
  # Decision (deterministic Python) → ai_image_prompt.v1 (LLM) → user
  # approval gate → image_client.py generate → manifest update +
  # fragment mutation. Architecture: V0_3_3_ARCHITECTURE.md.
  echo "" >&2
  echo "──────────────────────────────────────────────────" >&2
  echo "[Stage 11/14] image_gen (concept_illustration → AI image)" >&2
  echo "──────────────────────────────────────────────────" >&2

  # M5b Tier C / D-064: AI Studio model probe + hybrid fallback.
  # Runs once per draft when IMAGE_PROVIDER=google_ai_studio. If the
  # probe finds no usable model:
  #   - CBORG_API_KEY set → silent fallback: override IMAGE_PROVIDER=cborg
  #     for the rest of this draft (D-064 hybrid).
  #   - else → loud-warning diagnostic to stderr; disable image-gen for
  #     this run (treat as --no-images).
  # Cache lives at $AUDIT_DIR/ai_image_gen_probe.json (D-063 sidecar);
  # repeat invocations on the same draft are essentially free.
  if [[ "${IMAGE_PROVIDER:-}" == "google_ai_studio" ]]; then
    local cborg_flag=""
    if [[ -n "${CBORG_API_KEY:-}" ]]; then
      cborg_flag="--cborg-available"
    fi
    local resolved_model probe_rc
    set +e
    resolved_model=$("$PYTHON_BIN" "$TOOLS_DIR/image_client.py" probe \
        --audit-dir "$AUDIT_DIR" \
        $cborg_flag)
    probe_rc=$?
    set -e
    if [[ $probe_rc -eq 0 ]]; then
      export GOOGLE_AI_STUDIO_RESOLVED_MODEL="$resolved_model"
      echo "  [image-gen probe] AI Studio model: $resolved_model" >&2
    elif [[ $probe_rc -eq 5 ]]; then
      # D-064 hybrid fallback
      if [[ -n "${CBORG_API_KEY:-}" ]]; then
        echo "  [image-gen probe] AI Studio probe found no usable model; "\
"falling back to CBORG (silent fallback per D-064; CBORG_API_KEY is set)" >&2
        IMAGE_PROVIDER="cborg"
        export IMAGE_PROVIDER
      else
        echo "  [image-gen probe] AI Studio probe failed AND no CBORG_API_KEY; "\
"disabling image-gen for this run (D-064 loud-warning branch)." >&2
        return 0
      fi
    else
      echo "  [image-gen probe] image_client.py probe failed (rc=$probe_rc); "\
"see stderr above. Disabling image-gen for this run." >&2
      return 0
    fi
  fi

  # 1. Run the decision layer. v0.3.7+: this includes the LLM-judgment
  # layer for deferred-layout slides (claim_evidence, big_idea, big_number,
  # workflow_diagram, two_column_compare, implications). The CLI default
  # auto-enables judgment when `claude` is on PATH and falls back to the
  # pre-v0.3.7 conservative "no AI image" behavior otherwise. Adds
  # ~$0.10-0.20/draft cost for ~15 deferred slides at $0.005-0.01 each.
  # To disable judgment explicitly, pass --no-llm-judge here (or use
  # --no-images at the orchestrator level to skip the stage entirely).
  local exploratory_flag=""
  if [[ $IMAGE_ALLOW_EXPLORATORY -eq 1 ]]; then
    exploratory_flag="--allow-exploratory"
  fi
  if ! "$PYTHON_BIN" "$TOOLS_DIR/image_gen_decision.py" emit-decisions \
      --slides-dir "$SLIDES_DIR" \
      --tier "$TIER" --mode "$MODE" \
      $exploratory_flag \
      --out "$IMAGE_DECISIONS_JSON"; then
    echo "  image_gen_decision failed; skipping image-gen stage" >&2
    return 0
  fi

  # 2. Enumerate emit=true slide_ids. Empty list → nothing to do.
  local yes_list
  yes_list="$("$PYTHON_BIN" "$TOOLS_DIR/image_gen_decision.py" \
    list-yes "$IMAGE_DECISIONS_JSON")"
  if [[ -z "$yes_list" ]]; then
    echo "  no slides flagged for image-gen (decision layer)" >&2
    return 0
  fi
  local n_yes
  n_yes=$(echo "$yes_list" | wc -l | tr -d ' ')
  echo "  decision layer flagged $n_yes slide(s) for image-gen" >&2

  # Per-slide loop. bulk_mode is set when user picks [A]/[R]; subsequent
  # slides short-circuit through the gate.
  local bulk_mode=""
  local n_approved=0 n_rejected=0 n_skipped=0
  local slide_id

  while IFS= read -r slide_id; do
    [[ -z "$slide_id" ]] && continue
    echo "" >&2
    echo "  ── $slide_id ──" >&2

    # 3a. Snapshot fragment (idempotent across multiple slides per fragment).
    "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" snapshot-fragment \
      --draft-dir "$OUTDIR" --slide-id "$slide_id" >/dev/null || {
      echo "    failed to snapshot fragment for $slide_id; skipping" >&2
      continue
    }

    # 3b. Budget pre-flight. Worst-case for one image is ~$0.04 per
    # gemini-3-pro-image; if remaining < that, record skip + continue.
    local budget_remaining
    budget_remaining=$("$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" \
      budget-remaining --draft-dir "$OUTDIR" --cap-usd "$MAX_IMAGE_COST_USD")
    # Compare with awk (bash doesn't do floats natively).
    local under_budget
    under_budget=$(awk -v b="$budget_remaining" 'BEGIN{print (b > 0.04) ? "yes" : "no"}')
    if [[ "$under_budget" == "no" ]]; then
      echo "    budget exhausted (remaining \$$budget_remaining); skipping" >&2
      "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-skipped \
        --draft-dir "$OUTDIR" --slide-id "$slide_id" \
        --reason "budget cap \$${MAX_IMAGE_COST_USD} exhausted (remaining \$${budget_remaining})" \
        >/dev/null
      n_skipped=$((n_skipped + 1))
      continue
    fi

    # 3b-bis. v0.7/D-088 Tier D.2: approval-count cap. D-088 widens
    # eligibility to claim_evidence with ≥3 bullets, so a count cap
    # bounds visual density independently of the dollar cap. The
    # check is per-deck (MAX_IMAGE_APPROVALS, default 4); MAX=0
    # disables. Once the cap trips, break out of the per-slide
    # loop entirely — no point evaluating further candidates we
    # know we won't approve. Per-slide skip-records get written
    # for the slides we never reached so the manifest stays
    # complete.
    if [[ "$MAX_IMAGE_APPROVALS" -gt 0
          && "$n_approved" -ge "$MAX_IMAGE_APPROVALS" ]]; then
      echo "    approval cap ($MAX_IMAGE_APPROVALS) reached;" >&2
      echo "    recording skip for $slide_id + remaining flagged slides" >&2
      "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-skipped \
        --draft-dir "$OUTDIR" --slide-id "$slide_id" \
        --reason "approval count cap (${MAX_IMAGE_APPROVALS}) reached per D-088 Tier D.2" \
        >/dev/null
      n_skipped=$((n_skipped + 1))
      # Drain remaining slide_ids from the loop input so they each
      # get a skip record. The loop's `while IFS= read -r` consumes
      # the rest one-by-one; we record-skipped each before
      # `continue` so the manifest reflects every flagged slide.
      while IFS= read -r remaining_slide_id; do
        [[ -z "$remaining_slide_id" ]] && continue
        "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-skipped \
          --draft-dir "$OUTDIR" --slide-id "$remaining_slide_id" \
          --reason "approval count cap (${MAX_IMAGE_APPROVALS}) reached per D-088 Tier D.2" \
          >/dev/null
        n_skipped=$((n_skipped + 1))
      done
      break
    fi

    # 3c. Resolve the slide's stub path (the fragment is the stub for v0.3.3).
    local stub_path
    stub_path=$("$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" \
      find-fragment --draft-dir "$OUTDIR" --slide-id "$slide_id")
    if [[ -z "$stub_path" || ! -f "$stub_path" ]]; then
      echo "    fragment not found for $slide_id; skipping" >&2
      continue
    fi

    # 3d. Author the image request via ai_image_prompt.v1.md, OR reuse
    # a cached request from a prior run if one exists and is valid.
    # v0.3.3.2 (#63): cache-reuse saves ~$0.14/slide on every retry.
    # The check-reuse subcommand exits 0 when reusable, 1 when not;
    # always prints the reason to stderr.
    local request_path="$IMAGE_REQUESTS_DIR/${slide_id}_request.json"
    if "$PYTHON_BIN" "$TOOLS_DIR/image_gen_approval.py" check-reuse \
        "$request_path" "$slide_id" \
        --expected-style "$IMAGE_STYLE" 2>/dev/null; then
      echo "    reusing cached request: $request_path" >&2
    else
      local style_directive=""
      if [[ -n "$IMAGE_STYLE" ]]; then
        style_directive="STYLE_HINT=$IMAGE_STYLE"$'\n'
      fi

      # v0.8/D-097: compute DECK_POSITION from slide_id format.
      # ai_image_prompt.v1 uses this to enforce intro-slide spoiler
      # rule (no result-level statistics on intro images). Slide-id
      # conventions per _build_slide_id() in image_gen_decision.py:
      #   "pos{N}"          → intro slides (no substory_id)
      #   "S{N}-pos{M}"     → body slides (substory-attributed)
      #   closer slides (deck_close, acks, refs, qa_anticipated)
      #     are in _STRUCTURAL_NO_IMAGE — never reach this stage.
      # If a future closer-class slide becomes image-eligible, the
      # SUBSTORY_ID-prefix detector here needs extending; for now
      # binary intro|body covers everything that gets here.
      local deck_position="body"
      if [[ "$slide_id" =~ ^pos[0-9]+$ ]]; then
        deck_position="intro"
      fi

      local user_prompt="OUT_PATH=$request_path
CHANNEL=A
SLIDE_ID_TARGET=$slide_id
DECK_POSITION=$deck_position
STUB_PATH=$stub_path
USER_PROMPT_TEXT=
${style_directive}THROUGHLINE_PATH=$THROUGHLINE_PATH
SUBSTORY_PATH=$SUBSTORIES_PATH
MODE=$MODE
TIER=$TIER
BUDGET_USD_REMAINING=$budget_remaining

Run ai_image_prompt.v1 for slide $slide_id (Channel A — LLM-initiated).
Read STUB_PATH for slide content; read THROUGHLINE_PATH and SUBSTORY_PATH
for context; emit a model-ready image-request.v1 JSON to OUT_PATH.
slide_id_target MUST exactly equal $slide_id; the orchestrator verifies
this on write.

DECK_POSITION=$deck_position — see ai_image_prompt.v1 §'Inputs the
user prompt will pass' + §'Anti-pattern PA-9' (v0.8/D-097): when
DECK_POSITION=\"intro\", the image MUST NOT include result-level
statistics from later substories (percentages, p-values, effect
sizes, named outcome metrics). Intro images frame the question;
they don't state the answer."

      if ! invoke_claude_with_retry "$PROMPTS_DIR/ai_image_prompt.v1.md" \
          "$user_prompt" "$request_path" "ai_image_prompt-$slide_id"; then
        echo "    ai_image_prompt failed; recording rejection" >&2
        "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-rejected \
          --draft-dir "$OUTDIR" --slide-id "$slide_id" \
          --reason "ai_image_prompt invocation failed (LLM error)" \
          >/dev/null
        n_rejected=$((n_rejected + 1))
        continue
      fi
    fi

    # 3e. Trust-but-verify: confirm slide_id_target matches what we
    # passed in. LLMs occasionally drop or rewrite the field.
    if ! "$PYTHON_BIN" "$TOOLS_DIR/image_gen_approval.py" verify \
        "$request_path" "$slide_id" >&2; then
      echo "    request verification failed; recording rejection" >&2
      "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-rejected \
        --draft-dir "$OUTDIR" --slide-id "$slide_id" \
        --reason "ai_image_prompt produced malformed request (slide_id_target mismatch)" \
        --request-path "$request_path" \
        >/dev/null
      n_rejected=$((n_rejected + 1))
      continue
    fi

    # 3f. Approval gate. --auto-approve-images or a prior bulk choice
    # short-circuits the prompt.
    local verdict_rc
    if [[ $AUTO_APPROVE_IMAGES -eq 1 ]]; then
      verdict_rc=0  # treat as APPROVE
    else
      local bulk_arg=""
      if [[ -n "$bulk_mode" ]]; then
        bulk_arg="--bulk-mode $bulk_mode"
      fi
      "$PYTHON_BIN" "$TOOLS_DIR/image_gen_approval.py" prompt \
        "$request_path" \
        --budget-remaining-usd "$budget_remaining" \
        $bulk_arg
      verdict_rc=$?
    fi

    case "$verdict_rc" in
      0)  # APPROVE
        _generate_and_record_image "$slide_id" "$request_path" \
          && n_approved=$((n_approved + 1)) \
          || n_rejected=$((n_rejected + 1))
        ;;
      1)  # REJECT
        echo "    user rejected $slide_id" >&2
        "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-rejected \
          --draft-dir "$OUTDIR" --slide-id "$slide_id" \
          --reason "user-rejected via approval gate" \
          --request-path "$request_path" \
          >/dev/null
        n_rejected=$((n_rejected + 1))
        ;;
      10) # APPROVE_ALL
        bulk_mode="approve_all"
        echo "    bulk approve enabled for remaining slides" >&2
        _generate_and_record_image "$slide_id" "$request_path" \
          && n_approved=$((n_approved + 1)) \
          || n_rejected=$((n_rejected + 1))
        ;;
      11) # REJECT_ALL
        bulk_mode="reject_all"
        echo "    bulk reject enabled for remaining slides" >&2
        "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-rejected \
          --draft-dir "$OUTDIR" --slide-id "$slide_id" \
          --reason "user-rejected via approval gate (bulk reject)" \
          --request-path "$request_path" \
          >/dev/null
        n_rejected=$((n_rejected + 1))
        ;;
      20) # QUIT
        echo "    user quit image-gen stage" >&2
        break
        ;;
      *)
        echo "    unexpected approval gate exit $verdict_rc; recording rejection" >&2
        "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-rejected \
          --draft-dir "$OUTDIR" --slide-id "$slide_id" \
          --reason "approval gate returned unexpected exit code $verdict_rc" \
          --request-path "$request_path" \
          >/dev/null
        n_rejected=$((n_rejected + 1))
        ;;
    esac
  done <<< "$yes_list"

  echo "" >&2
  echo "  image_gen summary: $n_approved approved, $n_rejected rejected, $n_skipped skipped" >&2
  return 0
}

# Helper for stage_image_gen: invoke image_client.py, on success
# update manifest + bind image into the fragment. Returns 0 on
# success, 1 on failure (caller increments rejected counter).
_generate_and_record_image() {
  local slide_id="$1"
  local request_path="$2"
  local image_path="$IMAGES_DIR/${slide_id}.png"

  local image_prompt cost_ceil
  image_prompt=$("$PYTHON_BIN" -c "
import json
with open('$request_path') as f:
    print(json.load(f)['image_prompt'])
")
  cost_ceil=$("$PYTHON_BIN" -c "
import json
with open('$request_path') as f:
    print(json.load(f)['worst_case_cost_usd'])
")

  local budget_remaining
  budget_remaining=$("$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" \
    budget-remaining --draft-dir "$OUTDIR" --cap-usd "$MAX_IMAGE_COST_USD")

  echo "    generating image (worst-case \$$cost_ceil; remaining \$$budget_remaining)" >&2
  # M5b/D-062: pass resolved --provider. Empty IMAGE_PROVIDER (no key
  # resolved) defaults to cborg downstream, which then exits 3 with
  # "CBORG_API_KEY not set" — surfaces the misconfiguration loudly.
  local provider_arg="${IMAGE_PROVIDER:-cborg}"
  # M5b Tier C: for google_ai_studio, pass the probe-resolved model so
  # we use what the user actually has access to (3-pro-preview if
  # available, else 3.1-flash-preview, etc.). CBORG path uses its
  # default; no probe needed there.
  local model_arg=()
  if [[ "$provider_arg" == "google_ai_studio" ]] \
      && [[ -n "${GOOGLE_AI_STUDIO_RESOLVED_MODEL:-}" ]]; then
    model_arg=(--model "$GOOGLE_AI_STUDIO_RESOLVED_MODEL")
  fi
  if ! "$PYTHON_BIN" "$TOOLS_DIR/image_client.py" generate \
      --provider "$provider_arg" \
      "${model_arg[@]}" \
      --prompt "$image_prompt" \
      --out "$image_path" \
      --budget "$budget_remaining" \
      --channel A \
      --provenance "$IMAGE_PROVENANCE_JSON"; then
    echo "    image_client.py failed for $slide_id" >&2
    "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-rejected \
      --draft-dir "$OUTDIR" --slide-id "$slide_id" \
      --reason "image_client.py generation failed" \
      --request-path "$request_path" \
      >/dev/null
    return 1
  fi

  # image_client appended to image_provenance.json. Pull the entry it
  # just wrote to get the actual cost + timestamp.
  local approved_at cost_usd model
  approved_at=$("$PYTHON_BIN" -c "
import json
with open('$IMAGE_PROVENANCE_JSON') as f:
    entries = json.load(f)['entries']
print(entries[-1]['approved_at'])
")
  cost_usd=$("$PYTHON_BIN" -c "
import json
with open('$IMAGE_PROVENANCE_JSON') as f:
    entries = json.load(f)['entries']
print(entries[-1]['cost_usd'])
")
  model=$("$PYTHON_BIN" -c "
import json
with open('$IMAGE_PROVENANCE_JSON') as f:
    entries = json.load(f)['entries']
print(entries[-1]['model'])
")

  # Manifest entry.
  "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" record-approved \
    --draft-dir "$OUTDIR" --slide-id "$slide_id" \
    --image-path "$image_path" \
    --request-path "$request_path" \
    --channel A \
    --model "$model" \
    --cost-usd "$cost_usd" \
    --approved-at "$approved_at" \
    >/dev/null

  # Bind into the fragment so merge picks it up via the manifest;
  # also writes back the placeholder fields in the fragment so a
  # spec-validator-only run (e.g. --resume-from merge) sees real data.
  "$PYTHON_BIN" "$TOOLS_DIR/image_gen_orchestrate.py" mutate-fragment-bind \
    --draft-dir "$OUTDIR" --slide-id "$slide_id" \
    --image-path "$image_path" \
    --model "$model" \
    --cost-usd "$cost_usd" \
    --channel A \
    --approved-at "$approved_at" \
    >/dev/null

  echo "    -> $image_path (\$$cost_usd)" >&2
  return 0
}

stage_merge_and_assemble() {
  echo "" >&2
  echo "[Final] merge fragments + validate + assemble" >&2

  # v0.3.1: spec snapshots live in audit/snapshots/, not at top level.
  local spec_raw="$SNAPSHOTS_DIR/slide_spec.raw.json"
  local spec="$SLIDE_SPEC"
  local repair_report="$DIAGRAM_REPAIR"

  # v0.3.3: optionally pass --image-manifest-path so merge binds
  # approved image_path + provenance and drops rejected/skipped slides.
  # If the manifest is absent (NO_IMAGES, image_gen skipped, or
  # image_gen failed), merge_compose_fragments treats it as a no-op.
  #
  # 2026-05-03 fix: under `set -u`, expanding "${manifest_arg[@]}"
  # on an empty array fails with "unbound variable". The
  # `${name[@]+"${name[@]}"}` form expands to the inner only when set,
  # so an empty array safely expands to nothing. Verified against bash
  # 4.x and 5.x — both honor this idiom.
  local manifest_arg=()
  if [[ -f "$IMAGE_MANIFEST_JSON" ]]; then
    manifest_arg=(--image-manifest-path "$IMAGE_MANIFEST_JSON")
  fi

  "$PYTHON_BIN" "$TOOLS_DIR/merge_compose_fragments.py" \
    --outdir "$OUTDIR" \
    --project-id "$PROJECT_ID" \
    --mode "$MODE" \
    --tier "$TIER" \
    --audience "$AUDIENCE" \
    --throughline-path "$THROUGHLINE_PATH" \
    --substory-path "$SUBSTORIES_PATH" \
    --fragments-dir "$SLIDES_DIR" \
    --intro-fragment-path "$SLIDES_DIR/intro.json" \
    --speaker-notes-dir "$SPEAKER_NOTES_DIR" \
    --citation-pool-path "$CITATION_POOL_PATH" \
    --cross-tenant-fragment-path "$SLIDES_DIR/cross_tenant.json" \
    --qa-fragment-path "$SLIDES_DIR/qa_anticipated.json" \
    --deck-close-fragment-path "$SLIDES_DIR/deck_close.json" \
    ${manifest_arg[@]+"${manifest_arg[@]}"} \
    --out "$spec_raw"

  echo "  repairing diagram stubs..." >&2
  "$PYTHON_BIN" "$TOOLS_DIR/repair_diagram_stubs.py" \
    --in "$spec_raw" \
    --out "$spec" \
    --report "$repair_report"

  echo "  validating slide_spec.json..." >&2
  # v0.6 / D-083: redirect validator stderr to a file to avoid the
  # tee/pipefail/BlockingIOError that surfaced live in v0.5.1 Tier D
  # (validator soft-warnings overflow pipe buffer → Python crashes
  # mid-print → spurious non-zero rc → orchestrator bails). The file
  # gets cat'd to orchestrator stderr after, in one all-at-once write
  # that doesn't suffer pipe back-pressure.
  local _validate_stderr="$AUDIT_DIR/validate.stderr"
  if ! "$PYTHON_BIN" "$TOOLS_DIR/slide_spec.py" validate "$spec" \
        2> "$_validate_stderr"; then
    echo "  validation FAILED — see $spec" >&2
    [[ -s "$_validate_stderr" ]] && cat "$_validate_stderr" >&2
    echo "  stderr saved to: $_validate_stderr" >&2
    echo "  repair report: $repair_report" >&2
    return 1
  fi
  # Validation succeeded; cat the soft-warnings to orchestrator stderr.
  [[ -s "$_validate_stderr" ]] && cat "$_validate_stderr" >&2

  if [[ $SKIP_ASSEMBLY -eq 1 ]]; then
    echo "  [--skip-assembly] stopping before assemble_pptx.py" >&2
    return 0
  fi

  # v0.3.1 manual-edit detection: before clobbering deliverable/draft.pptx,
  # check whether the user has manually edited it since the last render.
  # If so, archive their edited copy to audit/manual-edits/ before
  # proceeding so they don't lose work.
  if [[ -f "$DECK_PPTX" ]] && [[ -f "$LAST_RENDER_HASH" ]]; then
    "$PYTHON_BIN" "$TOOLS_DIR/draft_paths.py" detect-manual-edit "$OUTDIR" 2>/dev/null || true
  fi

  local pptx="$DECK_PPTX"
  "$PYTHON_BIN" "$TOOLS_DIR/assemble_pptx.py" \
    "$spec" \
    --out "$pptx" \
    --master "$SKILL_DIR/references/templates/kbase-presentation-master.pptx" || {
    echo "  assemble_pptx FAILED" >&2
    return 1
  }

  # v0.3.1: record the rendered deck's hash for next-run manual-edit
  # detection. Also copies the deck to audit/snapshots/last-render.pptx
  # as the diff baseline.
  "$PYTHON_BIN" "$TOOLS_DIR/draft_paths.py" record-render-hash "$OUTDIR" \
    >/dev/null 2>&1 || \
    echo "  warning: failed to record render hash for manual-edit detection" >&2

  # 2026-04-28 (v0.2.1): mechanical post-checker — every number on a slide
  # must appear verbatim (or in a normalized form) in REPORT.md. Advisory
  # only (exit 1 doesn't halt); writes audit/quantitative_grounding.{md,json}
  # for the user / next stage to consult. The deeper semantic checks
  # (register drift, caveat omission, narrative arc) are handled by
  # beril-adversarial --type presentation (v0.4.0+).
  echo "  running quantitative-grounding check..." >&2
  "$PYTHON_BIN" "$TOOLS_DIR/check_quantitative_grounding.py" \
    "$OUTDIR" --severity-floor low 2>&1 | sed 's/^/    /' >&2 || true

  # v0.3.8 (2026-05-06): mechanical post-checker for process-detail bleed.
  # Flags internal-artifact references (notebook IDs, file paths,
  # REPORT.md sections, analysis-layer codes) on slides — patterns that
  # consistently slip past the slide_compose / revise_slide prompts and
  # leave the deck unreadable to peer audiences. Advisory only (rc=0
  # by design); writes audit/no_artifact_refs.{md,json} for the user
  # to consult during the hand-edit pass. Surfaced by 2026-05-06
  # ibd_phage_targeting talk-45 review (~11 of 37 slides flagged by
  # memoryless reviewer).
  echo "  running process-detail-bleed check..." >&2
  "$PYTHON_BIN" "$TOOLS_DIR/check_no_artifact_refs.py" \
    "$OUTDIR" 2>&1 | sed 's/^/    /' >&2 || true

  # v0.4 M3 (V0_4_ARCHITECTURE.md §20.4): post-merge reconciliation —
  # flag residual cross-section conflicts (a curated figure reused on
  # two slides, the same big_number headline twice, AI-image count over
  # the deck outline's image budget) that the parallel composers cannot
  # detect alone. Advisory (rc=0 by design); writes
  # audit/deck_reconciliation.{md,json}. Runs for both pipelines — the
  # image-budget class no-ops on a v0.3.x draft (no Image-budget line).
  echo "  running deck reconciliation check..." >&2
  "$PYTHON_BIN" "$TOOLS_DIR/reconcile_deck.py" \
    "$OUTDIR" 2>&1 | sed 's/^/    /' >&2 || true

  # v0.4 M4a Tier C (DQ1 — opt-in): visual-QA pass. Renders the deck to
  # per-slide PNGs and runs a vision-capable claude -p over them to flag
  # render-quality defects (overflow, overlap, footer collision,
  # illegible scale, headline↔body mismatch). Opt-in via --visual-qa
  # because the vision-LLM + LibreOffice render adds non-trivial cost
  # per run; always advisory (rc=0). Writes audit/visual_qa.{md,json}.
  if [[ "$VISUAL_QA" -eq 1 ]]; then
    echo "  running visual-QA pass (--visual-qa)..." >&2
    "$PYTHON_BIN" "$TOOLS_DIR/visual_qa.py" \
      "$OUTDIR" 2>&1 | sed 's/^/    /' >&2 || true
  fi

  echo "" >&2
  echo "==================================================================" >&2
  echo "ASSEMBLE COMPLETE" >&2
  echo "==================================================================" >&2
  echo "  spec:  $spec" >&2
  echo "  deck:  $pptx" >&2
  echo "==================================================================" >&2
}

# ==============================================================================
# v0.4 M4b — review cascade orchestrator (Tier A scaffolding)
# ==============================================================================

stage_review_cascade() {
  # v0.4 M4b Tier A (Adam 2026-05-24 — DQ1 auto-run): run the tiered
  # review cascade. Tier A ships scaffolding only — per-tier dispatchers
  # return 'not-implemented' until Tiers B/C/D fill them in. Tier-A
  # cascade is therefore advisory: writes audit/review_cascade.{md,json}
  # with all three tiers marked 'not-implemented', total cost $0.
  # Always rc=0 (advisory; matches reconcile_deck.py + visual_qa.py).
  #
  # v0.7/D-090 (C1 from v0.6 fdm interruption diagnostic): write
  # `audit/cascade-started.json` BEFORE the cascade runs and
  # `audit/cascade-completed.json` AFTER it finishes. The "started
  # without completed" delta is the interruption signature operators
  # can use to distinguish "cascade never ran" from "cascade
  # interrupted mid-flight" post-mortem. Both files capture
  # timestamp + the git sha of the skill repo for traceability.
  echo "" >&2
  echo "──────────────────────────────────────────────────" >&2
  echo "[Stage 11.5/13] review_cascade (M4b Tier A scaffolding)" >&2
  echo "──────────────────────────────────────────────────" >&2

  # Pre-cascade checkpoint marker (D-090).
  local _started_marker="$AUDIT_DIR/cascade-started.json"
  local _started_ts; _started_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local _skill_sha; _skill_sha="$(cd "$SKILL_DIR" && \
    git rev-parse --short HEAD 2>/dev/null || echo "unknown")"
  mkdir -p "$AUDIT_DIR"
  cat > "$_started_marker" <<EOF
{
  "schema_version": "cascade-checkpoint.v1",
  "phase": "started",
  "started_at_utc": "$_started_ts",
  "skill_git_sha": "$_skill_sha",
  "draft_dir": "$OUTDIR",
  "stages": ["review_cascade.py"]
}
EOF

  # Run the cascade. Advisory rc=0; never gates the orchestrator.
  "$PYTHON_BIN" "$TOOLS_DIR/review_cascade.py" \
    "$OUTDIR" 2>&1 | sed 's/^/  /' >&2 || true

  # Post-cascade checkpoint marker (D-090).
  local _completed_marker="$AUDIT_DIR/cascade-completed.json"
  local _completed_ts; _completed_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$_completed_marker" <<EOF
{
  "schema_version": "cascade-checkpoint.v1",
  "phase": "completed",
  "started_at_utc": "$_started_ts",
  "completed_at_utc": "$_completed_ts",
  "skill_git_sha": "$_skill_sha",
  "draft_dir": "$OUTDIR",
  "stages": ["review_cascade.py"]
}
EOF
}

# ==============================================================================
# 2026-04-29 v0.3.0 — review-rewrite loop stages
# ==============================================================================

stage_adversarial_review() {
  echo "" >&2
  echo "──────────────────────────────────────────────────" >&2
  echo "[Stage 12/13] adversarial_review (--type presentation)" >&2
  echo "──────────────────────────────────────────────────" >&2

  # v0.3.2.5: prefer the v0.6.0+ Python CLI subcommand
  # `beril-adversarial review --type presentation <draft_dir>`. Cleaner
  # than the prior sibling-shell-script invocation; doesn't depend on
  # filesystem-path discovery to find adversarial_review.sh.
  if ! command -v beril-adversarial >/dev/null 2>&1; then
    echo "  beril-adversarial not on PATH; skipping adversarial review." >&2
    echo "  Install: pipx install --pip-args=\"--no-cache-dir\" \\" >&2
    echo "           git+ssh://git@github.com/ArkinLaboratory/beril-adversarial-skill.git@v0.6.3" >&2
    echo "  Or pass --no-adversarial to skip this warning." >&2
    return 0
  fi

  local review_path="$ADVERSARIAL_REVIEW_JSON"
  local review_md="$ADVERSARIAL_REVIEW_MD"

  # Detect whether the Python CLI has the `review` subcommand (v0.6.0+).
  # On older installs, fall back to the sibling shell script. We probe
  # by calling --help once and grep'ing for the subcommand name; cheap
  # and avoids hard pinning a min-version requirement here.
  local has_review_subcmd=0
  if beril-adversarial --help 2>&1 | grep -qE "^[[:space:]]*review[[:space:]]"; then
    has_review_subcmd=1
  fi

  if [[ $has_review_subcmd -eq 1 ]]; then
    # v0.6.0+ path — clean Python CLI dispatch.
    # M6 Tier B.1: pass --beril-root explicitly (mirrors the cascade
    # Tier-3 fix from M4b Tier E round 2 / D-058 — without it,
    # beril-adversarial resolves BERIL_ROOT from its own pipx install
    # path and fails with "does not contain .claude/skills/").
    #
    # M6 Tier B.2 (v0.7.0.7+v0.7.0.8 exit-code contract; adversarial
    # team correction 2026-05-25): explicit rc branching is REQUIRED
    # for correctness, not just messaging. v0.7.0.8's rc=4 means
    # "schema-invalid JSON; do not consume." A schema-invalid file
    # PARSES — so a downstream `if [[ -f $JSON ]]; then load_it`
    # gate sees it as present and revise_loop.py iterates on broken
    # findings. paper-writer hit exactly this; ship-the-fix per their
    # v1.0.1 pattern: quarantine the .json (rename) so the cross-
    # phase file-existence check sees absent. The .md is always
    # intact regardless of rc; never quarantine the .md.
    set +e
    beril-adversarial review --type presentation \
        --beril-root "$BERIL_ROOT" \
        "$OUTDIR"
    local rc=$?
    set -e
    case "$rc" in
      0)
        # JSON parses cleanly + schema-valid; safe to consume.
        :
        ;;
      2)
        # Per CONTRACT.md (v0.7.0.7): auto-repaired but still safe.
        echo "  beril-adversarial review: auto-repaired JSON (rc=2; .json consumer-safe)" >&2
        ;;
      4)
        # CONTRACT.md (v0.7.0.7+v0.7.0.8): JSON is NOT consumer-safe.
        # Quarantine to prevent the downstream file-existence gate
        # from loading it (revise_loop would iterate on broken
        # findings). .md is intact; operator inspects that.
        echo "  beril-adversarial review: rc=4 — JSON is NOT consumer-safe" >&2
        echo "    (either unparseable after failed auto-repair, or schema-invalid)" >&2
        if [[ -f "$review_path" ]]; then
          local quarantine="${review_path}.quarantined-rc4"
          mv "$review_path" "$quarantine"
          echo "  quarantined: $review_path → $(basename "$quarantine")" >&2
          echo "  .md intact: $review_md (inspect this for the review content)" >&2
        fi
        echo "  revise loop will halt (no consumer-safe adversarial_review.json)" >&2
        return 1
        ;;
      3)
        echo "  beril-adversarial review: rc=3 — config error (check --beril-root, install-skill, etc.)" >&2
        return 1
        ;;
      *)
        echo "  beril-adversarial review failed (rc=$rc); revise loop will halt" >&2
        return 1
        ;;
    esac
  else
    # Legacy fallback — find the sibling shell script and invoke it.
    # This path is for beril-adversarial v0.5.x installs that predate
    # the `review` Python subcommand.
    local adversarial_sh
    adversarial_sh="$(dirname "$(dirname "$TOOLS_DIR")")/beril-adversarial/tools/adversarial_review.sh"
    if [[ ! -f "$adversarial_sh" ]]; then
      echo "  beril-adversarial v0.5.x detected but sibling adversarial_review.sh not found at:" >&2
      echo "    $adversarial_sh" >&2
      echo "  Upgrade to v0.6.0+ (which exposes 'beril-adversarial review' subcommand) OR" >&2
      echo "  re-run 'beril-adversarial install-skill <BERIL_ROOT>' to deploy the script." >&2
      return 1
    fi
    bash "$adversarial_sh" "$OUTDIR" --type presentation || {
      echo "  adversarial_review.sh failed (rc=$?); revise loop will halt" >&2
      return 1
    }
  fi

  if [[ ! -f "$review_path" ]]; then
    echo "  adversarial review did not produce $review_path; revise loop will halt" >&2
    return 1
  fi

  # Surface a quick summary to stdout
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    "$PYTHON_BIN" -c "
import json
with open('$review_path') as f:
    review = json.load(f)
s = review.get('summary', {})
print(f'  total findings: {s.get(\"total_findings\", \"?\")}', end='')
sev = s.get('by_severity', {})
print(f' (P0={sev.get(\"P0\", 0)} P1={sev.get(\"P1\", 0)} P2={sev.get(\"P2\", 0)} info={sev.get(\"info\", 0)})')
" 2>&1 | sed 's/^/    /' >&2
  fi
}

stage_revise_slides() {
  echo "" >&2
  echo "──────────────────────────────────────────────────" >&2
  echo "[Stage 13/13] revise_slides (review-rewrite loop)" >&2
  echo "──────────────────────────────────────────────────" >&2

  local review_path="$ADVERSARIAL_REVIEW_JSON"
  if [[ ! -f "$review_path" ]]; then
    echo "  no adversarial_review.json found; skipping revise loop" >&2
    return 0
  fi

  local stream_flag=""
  if [[ $NO_STREAM -eq 1 ]]; then stream_flag="--no-stream"; fi

  echo "  invoking revise_loop.py (max-revisions=$MAX_REVISIONS, max-cost-usd=$MAX_REVISE_COST_USD)" >&2
  "$PYTHON_BIN" "$TOOLS_DIR/revise_loop.py" \
    "$OUTDIR" \
    --severity-floor P0 \
    --max-revisions "$MAX_REVISIONS" \
    --max-cost-usd "$MAX_REVISE_COST_USD" \
    --model "$MODEL" \
    $stream_flag 2>&1 | sed 's/^/    /' >&2

  local rc=$?
  if [[ $rc -ne 0 && $rc -ne 1 ]]; then
    echo "  revise_loop.py crashed (rc=$rc); spec may be corrupt — pre-revise backup at $SNAPSHOTS_DIR/slide_spec.pre_revise.json" >&2
    return 1
  fi

  # If the loop made any changes, re-run validate + assemble against the
  # revised spec.
  local meta="$REVISE_LOOP_METADATA"
  if [[ -f "$meta" ]]; then
    local n_changed
    n_changed=$("$PYTHON_BIN" -c "
import json
with open('$meta') as f:
    m = json.load(f)
print(len(m.get('findings_revised', [])) + len(m.get('findings_added', [])))
" 2>/dev/null || echo "0")
    if [[ "$n_changed" -gt 0 ]]; then
      echo "  revise loop applied $n_changed change(s); re-assembling deck..." >&2
      local spec="$SLIDE_SPEC"
      local pptx="$DECK_PPTX"
      # v0.6 / D-083: same stderr-to-file redirect as Tier B
      # stage_merge_and_assemble validation site.
      local _revise_validate_stderr="$AUDIT_DIR/validate.post_revise.stderr"
      if ! "$PYTHON_BIN" "$TOOLS_DIR/slide_spec.py" validate "$spec" \
            2> "$_revise_validate_stderr"; then
        echo "  post-revise validation FAILED — spec at $spec" >&2
        [[ -s "$_revise_validate_stderr" ]] && cat "$_revise_validate_stderr" >&2
        echo "  stderr saved to: $_revise_validate_stderr" >&2
        return 1
      fi
      [[ -s "$_revise_validate_stderr" ]] && cat "$_revise_validate_stderr" >&2
      "$PYTHON_BIN" "$TOOLS_DIR/assemble_pptx.py" \
        "$spec" \
        --out "$pptx" \
        --master "$SKILL_DIR/references/templates/kbase-presentation-master.pptx" || {
        echo "  post-revise assemble_pptx FAILED" >&2
        return 1
      }
      # Re-record render hash after the post-revise re-assemble.
      "$PYTHON_BIN" "$TOOLS_DIR/draft_paths.py" record-render-hash "$OUTDIR" \
        >/dev/null 2>&1 || true
      echo "  re-assembled deck: $pptx" >&2
    else
      echo "  revise loop made no changes (all findings were surface-only or skipped)" >&2
    fi
  fi

  if [[ -f "$NEXT_ACTIONS" ]]; then
    echo "  next_actions.md written: $NEXT_ACTIONS" >&2
  fi
}

# ==============================================================================
# Main flow
# ==============================================================================

# --- Resume-aware stage execution ---
# Each stage runs unless RESUME_FROM names a later stage. Gates that
# follow a skipped stage are also skipped (the user's prior choice
# already wrote the canonical file). Order:
#   v0.3.x:  plan → throughline → (gate) → substory_design → (gate)
#            → curate_figures → citation_pool → cross_tenant
#            → intro → slide_compose → merge
#   v0.4:    plan → throughline → (gate) → phase0_tooling
#            → curate_figures → citation_pool → cross_tenant
#            → deck_outline → (gate) → intro → slide_compose → merge

# Compute "should we run stage X" for each stage.
should_run() {
  local stage="$1"
  if [[ -z "$RESUME_FROM" ]]; then return 0; fi
  # Stage ordinals. v0.3.3: image_gen inserted at 11 (between
  # speaker_notes and merge per V0_3_3_ARCHITECTURE.md §3); merge,
  # adversarial_review, revise_slides shift by 1.
  #
  # v0.3.5.1 (2026-05-05): explicit "" initialization required under
  # bash `set -u`. Without it, the `[[ -z "$order_resume" ]]` check
  # after the loop can trip "unbound variable" on bash 5.2+ when
  # neither case-arm matched any iteration. Live failure on KBERDL
  # JupyterHub during ibd_phage_targeting smoke run (Claude Code
  # agent's first `continue --resume-from throughline` invocation hit
  # this codepath, hidden until then because most prior tests ran
  # without --resume-from and short-circuited out at the early check).
  local order_resume="" order_stage=""
  # v0.4 M3: the v0_4 pipeline reorders the Phase-0 producers ahead of
  # deck_outline, so its stage ordinals differ from the v0.3.x map. Pick
  # the ordinal map by --architecture-pipeline.
  local ordinals
  # v0.7/D-086 Tier C.3: deck_close inserted after qa_prep (both
  # are deck-level closers consumed at merge time; deck_close has
  # to come after slide_compose so substory C-slot conclusions are
  # readable). Stages from speaker_notes onward shift by 1.
  if [[ "$ARCH_PIPELINE" == "v0_4" ]]; then
    ordinals="plan:1 throughline:2 phase0_tooling:3 curate_figures:4 citation_pool:5 cross_tenant:6 deck_outline:7 intro:8 slide_compose:9 qa_prep:10 deck_close:11 speaker_notes:12 image_gen:13 merge:14 adversarial_review:15 revise_slides:16"
  else
    ordinals="plan:1 throughline:2 substory_design:3 curate_figures:4 citation_pool:5 cross_tenant:6 intro:7 slide_compose:8 qa_prep:9 deck_close:10 speaker_notes:11 image_gen:12 merge:13 adversarial_review:14 revise_slides:15"
  fi
  for o in $ordinals; do
    case "$o" in
      "$RESUME_FROM":*) order_resume="${o#*:}" ;;
      "$stage":*)       order_stage="${o#*:}" ;;
    esac
  done
  if [[ -z "$order_resume" || -z "$order_stage" ]]; then return 0; fi
  [[ $order_stage -ge $order_resume ]]
}

if should_run plan;             then stage_plan            || { echo "FAIL at plan" >&2; exit 1; }
                                else echo "[skip] plan (resume from $RESUME_FROM)" >&2; fi

if should_run throughline;      then stage_throughline     || { echo "FAIL at throughline" >&2; exit 1; }
                                     gate_throughline_pick || { echo "FAIL at throughline pick gate" >&2; exit 1; }
                                else echo "[skip] throughline + pick (resume from $RESUME_FROM)" >&2; fi

# v0.4 M3: the deck-clustering region is pipeline-conditional. v0.4 runs
# phase0_tooling + the Phase-0 producers (curate_figures / citation_pool /
# cross_tenant) BEFORE deck_outline, so the outline call sees its inputs.
# v0.3.x is byte-unchanged: substory_design first, then the same three
# enrichment stages. `intro` onward is common to both paths.
if [[ "$ARCH_PIPELINE" == "v0_4" ]]; then
  if should_run phase0_tooling; then stage_phase0_tooling  || { echo "FAIL at phase0_tooling" >&2; exit 1; }
                                else echo "[skip] phase0_tooling (resume from $RESUME_FROM)" >&2; fi

  if should_run curate_figures; then stage_curate_figures  || { echo "FAIL at curate_figures" >&2; exit 1; }
                                else echo "[skip] curate_figures (resume from $RESUME_FROM)" >&2; fi

  if should_run citation_pool;  then stage_citation_pool   || { echo "FAIL at citation_pool" >&2; exit 1; }
                                else echo "[skip] citation_pool (resume from $RESUME_FROM)" >&2; fi

  if should_run cross_tenant;   then stage_cross_tenant    || { echo "FAIL at cross_tenant" >&2; exit 1; }
                                else echo "[skip] cross_tenant (resume from $RESUME_FROM)" >&2; fi

  if should_run deck_outline;   then stage_deck_outline    || { echo "FAIL at deck_outline" >&2; exit 1; }
                                     audit_punchline_lengths
                                     gate_substory_overflow || { echo "FAIL at substory overflow gate" >&2; exit 1; }
                                else echo "[skip] deck_outline + overflow gate (resume from $RESUME_FROM)" >&2; fi
else
  if should_run substory_design; then stage_substory_design || { echo "FAIL at substory_design" >&2; exit 1; }
                                      audit_punchline_lengths
                                      gate_substory_overflow || { echo "FAIL at substory overflow gate" >&2; exit 1; }
                                 else echo "[skip] substory clustering + overflow gate (resume from $RESUME_FROM)" >&2; fi

  if should_run curate_figures;  then stage_curate_figures || { echo "FAIL at curate_figures" >&2; exit 1; }
                                 else echo "[skip] curate_figures (resume from $RESUME_FROM)" >&2; fi

  if should_run citation_pool;   then stage_citation_pool  || { echo "FAIL at citation_pool" >&2; exit 1; }
                                 else echo "[skip] citation_pool (resume from $RESUME_FROM)" >&2; fi

  if should_run cross_tenant;    then stage_cross_tenant   || { echo "FAIL at cross_tenant" >&2; exit 1; }
                                 else echo "[skip] cross_tenant (resume from $RESUME_FROM)" >&2; fi
fi

if should_run intro;            then stage_intro           || { echo "FAIL at intro" >&2; exit 1; }
                                else echo "[skip] intro (resume from $RESUME_FROM)" >&2; fi

if should_run slide_compose;    then stage_slide_compose   || { echo "FAIL at slide_compose" >&2; exit 1; }
                                else echo "[skip] slide_compose (resume from $RESUME_FROM)" >&2; fi

if should_run qa_prep;          then stage_qa_prep         || { echo "FAIL at qa_prep" >&2; exit 1; }
                                else echo "[skip] qa_prep (resume from $RESUME_FROM)" >&2; fi

# v0.7/D-086 Tier C.3: deck-spanning closing-synthesis slide.
# Mode-gated to talk-30 STRONG inside stage_deck_close itself
# (silent skip on sub-STRONG modes). Reads substory C-slots +
# throughline + REPORT.md to produce the deck_close.json fragment
# the merger splices between the final substory and cross_tenant.
if should_run deck_close;       then stage_deck_close      || { echo "FAIL at deck_close" >&2; exit 1; }
                                else echo "[skip] deck_close (resume from $RESUME_FROM)" >&2; fi

# v0.4 M3 (D-033): the v0.4 composer (slide_compose.v2.md) authors
# speaker notes inline — the separate speaker_notes stage is retired
# on the v0.4 path. v0.3.x still runs it.
if [[ "$ARCH_PIPELINE" == "v0_4" ]]; then
  echo "[skip] speaker_notes (v0.4 — fused into slide_compose.v2; D-033)" >&2
elif should_run speaker_notes;  then stage_speaker_notes   || { echo "FAIL at speaker_notes" >&2; exit 1; }
                                else echo "[skip] speaker_notes (resume from $RESUME_FROM)" >&2; fi

# v0.3.3: image_gen between speaker_notes and merge. Stage owns its own
# error handling; failures are recorded as rejections in the manifest
# rather than halting the pipeline.
if [[ $NO_IMAGES -eq 0 ]]; then
  if should_run image_gen;      then stage_image_gen        || { echo "FAIL at image_gen" >&2; exit 1; }
                                else echo "[skip] image_gen (resume from $RESUME_FROM)" >&2; fi
else
  echo "[skip] image_gen (--no-images)" >&2
fi

# merge always runs (it's the final assembly step; cheap)
stage_merge_and_assemble    || { echo "FAIL at merge/assemble" >&2; exit 1; }

# v0.4 M4b: review cascade orchestrator. Auto-runs by default (DQ1);
# opt out with --no-review-cascade. Tier B aggregates the deterministic
# checks + opt-in visual-QA; Tier C runs Haiku narrative-light; Tier D
# runs the canonical adversarial review. Always advisory rc=0.
if [[ $NO_REVIEW_CASCADE -eq 0 && $SKIP_ASSEMBLY -eq 0 ]]; then
  stage_review_cascade
else
  if [[ $NO_REVIEW_CASCADE -eq 1 ]]; then
    echo "[skip] review_cascade (--no-review-cascade)" >&2
  fi
fi

# v0.4 M4b Tier D: when the cascade ran its Tier 3 (canonical
# adversarial), the standalone stage_adversarial_review elides — both
# call `beril-adversarial review --type presentation` and write the
# same audit/adversarial_review.json; running both is double-spend.
# Read cascade's tier3.status: 'pass'/'advisory'/'fail' → cascade ran
# Tier 3 (skip standalone); 'skipped'/'error'/'not-implemented' →
# cascade did NOT produce adversarial output (standalone runs).
CASCADE_RAN_TIER3=0
CASCADE_JSON="$OUTDIR/audit/review_cascade.json"
if [[ -f "$CASCADE_JSON" ]]; then
  # Read tiers[2].status via a tiny python one-liner (jq isn't a
  # guaranteed runtime dep on the hub; python is).
  TIER3_STATUS="$("$PYTHON_BIN" -c "
import json, sys
try:
    d = json.load(open('$CASCADE_JSON'))
    tiers = d.get('tiers') or []
    print(tiers[2].get('status', '') if len(tiers) >= 3 else '')
except Exception:
    print('')
" 2>/dev/null)"
  case "$TIER3_STATUS" in
    pass|advisory|fail)
      CASCADE_RAN_TIER3=1 ;;
  esac
fi

# v0.3.0: adversarial review-rewrite loop (after assembly, before final summary).
# Skip when --no-adversarial OR when --skip-assembly (no spec to review)
# OR when the cascade already ran Tier 3 (M4b Tier D de-dup).
#
# v0.3.2.7: control-flow restructure. Previously, the revise_slides
# dispatch was nested INSIDE the should_run adversarial_review branch —
# which meant `--resume-from revise_slides` skipped adversarial_review
# (correctly) but ALSO skipped revise_slides (incorrectly, because the
# whole enclosing block was bypassed). Each stage now has its own
# top-level should_run gate.
if [[ $NO_ADVERSARIAL -eq 0 && $SKIP_ASSEMBLY -eq 0 ]]; then
  # Adversarial review stage
  if [[ $CASCADE_RAN_TIER3 -eq 1 ]]; then
    echo "[skip] adversarial_review (cascade Tier 3 already ran; audit/adversarial_review.json populated)" >&2
  elif should_run adversarial_review; then
    stage_adversarial_review || {
      # M6 Tier B.2: stage_adversarial_review already handled exit-code
      # branching including v0.7.0.8 rc=4 quarantine. The contract is
      # now: if $ADVERSARIAL_REVIEW_JSON exists at the file-check below,
      # it's consumer-safe. The .md is always preserved (rc=4 path
      # only quarantines the .json + keeps the .md).
      echo "[warn] adversarial_review stage returned non-zero — revise loop will skip" >&2
      echo "       (any .json was quarantined or absent; .md preserved if produced)" >&2
      echo "       Inspect: $ADVERSARIAL_REVIEW_MD" >&2
    }
  else
    echo "[skip] adversarial_review (resume from $RESUME_FROM)" >&2
  fi

  # Revise loop stage — dispatched independently, contingent on
  # the review JSON being present (whether produced by this run or
  # a prior one in the same draft_dir).
  if should_run revise_slides; then
    if [[ -f "$ADVERSARIAL_REVIEW_JSON" ]]; then
      stage_revise_slides || {
        echo "[warn] revise_slides loop failed — slide_spec may be at backup" >&2
      }
    else
      echo "[skip] revise_slides — no $ADVERSARIAL_REVIEW_JSON present" >&2
      echo "       Run adversarial review first, or pass --resume-from adversarial_review" >&2
    fi
  else
    echo "[skip] revise_slides (resume from $RESUME_FROM)" >&2
  fi
else
  if [[ $NO_ADVERSARIAL -eq 1 ]]; then
    echo "[skip] adversarial_review + revise loop (--no-adversarial)" >&2
  fi
fi

# Final summary banner
echo "" >&2
echo "==================================================================" >&2
echo "PIPELINE COMPLETE" >&2
echo "==================================================================" >&2
echo "  draft_dir:   $OUTDIR" >&2
if [[ -f "$DECK_PPTX" ]]; then
  echo "  deliverable: $DECK_PPTX" >&2
fi
if [[ -f "$THROUGHLINE_PATH" ]]; then
  echo "  narrative:   $NARRATIVE_DIR/" >&2
fi
if [[ -f "$NEXT_ACTIONS" ]]; then
  echo "  next:        $NEXT_ACTIONS" >&2
fi
echo "==================================================================" >&2

exit 0
