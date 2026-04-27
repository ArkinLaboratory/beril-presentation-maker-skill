#!/usr/bin/env bash
# presentation_maker_smoke.sh — minimal orchestrator for v0.1.0 mid-phase
# live testing of the drafting prompts (plan → throughline → substory →
# slide_compose) against a real BERDL project.
#
# This is NOT the production orchestrator. Production behavior (citation
# pool, cross_tenant, curate_figures, speaker_notes, qa_prep,
# diagram_design, ai_image_prompt, review-rewrite loops, slash command
# integration) is deferred to a later cycle. The smoke harness exists
# to surface real LLM behavior on the four load-bearing drafting prompts
# before we invest in the heavier production wiring.
#
# Forked structurally from beril-adversarial v0.1.x adversarial_review.sh
# (claude -p invocation pattern, stream_progress.py piping, retry on
# rc=2). Adapts to a 4-stage sequential flow with two interactive gates.
#
# Usage:
#   presentation_maker_smoke.sh <project_id> [options]
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
#                              intro | slide_compose | merge
#                            Cost savings on prompt-iteration:
#                              from intro:         ~$1.50 (saves plan+throughline+substory)
#                              from slide_compose: ~$1.20 (saves plan+throughline+substory+intro)
#                              from merge:         FREE (no LLM; assembly only)
#                            Requires --draft-dir.
#   --draft-dir <path>       Existing draft_N directory to resume into.
#                            Required when --resume-from is set.
#   --help                   Show this message

set -euo pipefail

# --- Defaults ---
PROJECT_ID=""
BERIL_ROOT_OVERRIDE=""
MODE="talk-30"
TIER="STRONG"
AUDIENCE="peer"
AUTO_ADVANCE=0
SKIP_ASSEMBLY=0
MODEL="claude-sonnet-4-20250514"
NO_STREAM=0
RESUME_FROM=""        # 2026-04-26 #58: skip earlier stages on prompt iteration
DRAFT_DIR_OVERRIDE="" # required when RESUME_FROM is set

CLAUDE_TOOLS="Read,Write,Bash,Grep,Glob,WebSearch,Agent,ToolSearch"

# --- Usage ---
usage() {
  local exit_code="${1:-0}"
  sed -n '4,38p' "$0"
  exit "$exit_code"
}

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
    --draft-dir)         DRAFT_DIR_OVERRIDE="$2"; shift 2 ;;
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

# Validate --resume-from + --draft-dir pairing
case "$RESUME_FROM" in
  ""|plan|throughline|substory_design|curate_figures|intro|slide_compose|speaker_notes|merge) ;;
  *)
    echo "Error: invalid --resume-from '$RESUME_FROM'" >&2
    echo "       valid stages: plan|throughline|substory_design|curate_figures|intro|slide_compose|speaker_notes|merge" >&2
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

for f in plan.v1.md throughline.v1.md substory_design.v1.md slide_compose.v1.md intro.v1.md; do
  if [[ ! -f "$PROMPTS_DIR/$f" ]]; then
    echo "Error: prompt missing at $PROMPTS_DIR/$f" >&2
    exit 1
  fi
done

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

# --- Output dir setup ---
DRAFTS_DIR="$PROJECT_DIR/talks"
mkdir -p "$DRAFTS_DIR"

if [[ -n "$DRAFT_DIR_OVERRIDE" ]]; then
  # Resume mode: reuse the existing draft directory
  OUTDIR="$(cd "$DRAFT_DIR_OVERRIDE" && pwd -P)"
  mkdir -p "$OUTDIR/03_slides"
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
  mkdir -p "$OUTDIR/03_slides"
fi

# --- Resume validation: verify required files exist for the resume point ---
# Each stage has prerequisites that must already be on disk; fail fast if
# they're missing rather than running the LLM and then crashing in merge.
validate_resume_prereqs() {
  local stage="$1"
  local missing=()
  case "$stage" in
    throughline)
      [[ -f "$OUTDIR/00_plan.md" ]] || missing+=("00_plan.md") ;;
    substory_design)
      [[ -f "$OUTDIR/00_plan.md" ]] || missing+=("00_plan.md")
      [[ -f "$OUTDIR/00_throughline.md" ]] || missing+=("00_throughline.md") ;;
    intro)
      [[ -f "$OUTDIR/00_plan.md" ]] || missing+=("00_plan.md")
      [[ -f "$OUTDIR/00_throughline.md" ]] || missing+=("00_throughline.md")
      [[ -f "$OUTDIR/02_substories.md" ]] || missing+=("02_substories.md") ;;
    slide_compose)
      [[ -f "$OUTDIR/00_plan.md" ]] || missing+=("00_plan.md")
      [[ -f "$OUTDIR/00_throughline.md" ]] || missing+=("00_throughline.md")
      [[ -f "$OUTDIR/02_substories.md" ]] || missing+=("02_substories.md")
      [[ -f "$OUTDIR/03_slides/intro.json" ]] || missing+=("03_slides/intro.json") ;;
    merge)
      [[ -f "$OUTDIR/00_plan.md" ]] || missing+=("00_plan.md")
      [[ -f "$OUTDIR/00_throughline.md" ]] || missing+=("00_throughline.md")
      [[ -f "$OUTDIR/02_substories.md" ]] || missing+=("02_substories.md")
      [[ -f "$OUTDIR/03_slides/intro.json" ]] || missing+=("03_slides/intro.json")
      # Per-substory fragments validated dynamically in stage_merge_and_assemble
      ;;
  esac
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: --resume-from $stage requires the following files in --draft-dir," >&2
    echo "       but they are missing:" >&2
    for f in "${missing[@]}"; do echo "         - $OUTDIR/$f" >&2; done
    echo "       Pick an earlier --resume-from stage or use a different draft." >&2
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
  local out="$OUTDIR/00_plan.md"
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
  local out="$OUTDIR/00_throughline_candidates.md"
  echo "" >&2
  echo "[Stage 2/4] throughline (candidates)" >&2
  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
PLAN_PATH=$OUTDIR/00_plan.md
MODE=$MODE
TIER=$TIER

Run the throughline stage. Read the plan's critical-analysis inventory \
and seed candidates. Produce 2-3 throughline candidates with evidence \
maps. Write the result to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/throughline.v1.md" "$user_prompt" "$out" "throughline"
}

# Throughline pick gate. Either prompts the user or auto-picks TL1 in
# auto-advance mode. Writes the chosen candidate to 00_throughline.md.
gate_throughline_pick() {
  local candidates="$OUTDIR/00_throughline_candidates.md"
  local out="$OUTDIR/00_throughline.md"

  if [[ ! -f "$candidates" ]]; then
    echo "Error: throughline candidates not found at $candidates" >&2
    return 1
  fi

  local pick
  if [[ $AUTO_ADVANCE -eq 1 ]]; then
    pick="TL1"
    echo "  [auto-advance] picking $pick" >&2
  else
    echo "" >&2
    echo "==== Throughline candidates (open $candidates to review) ====" >&2
    # Match all four observed header variants: `## TL1 —`, `## TL1:`,
    # `## Candidate TL1 —`, `## Candidate TL1:` (live throughline.v1
    # produced the last shape on 2026-04-26).
    grep -E "^## (Candidate +)?TL[0-9]+[ :—–-]" "$candidates" >&2 || true
    echo "" >&2
    echo -n "Pick a throughline (TL1 / TL2 / TL3): " >&2
    read -r pick </dev/tty
  fi

  "$PYTHON_BIN" "$TOOLS_DIR/parse_throughline_candidates.py" \
    --candidates "$candidates" \
    --pick "$pick" \
    --out "$out"
}

stage_substory_design() {
  local out="$OUTDIR/02_substories.md"
  echo "" >&2
  echo "[Stage 3/5] substory_design" >&2
  local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
PLAN_PATH=$OUTDIR/00_plan.md
THROUGHLINE_PATH=$OUTDIR/00_throughline.md
MODE=$MODE
TIER=$TIER

Run the substory_design stage. Read the chosen throughline and the plan's \
critical-analysis inventory. Cluster analyses into substories. Compute \
mode-capacity verdict. If overflow, surface the three options and halt. \
Write the result to OUT_PATH."

  invoke_claude_with_retry "$PROMPTS_DIR/substory_design.v1.md" "$user_prompt" "$out" "substory_design"
}

# Conditional gate: only halt if capacity_verdict == overflow.
gate_substory_overflow() {
  local substories="$OUTDIR/02_substories.md"
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

  if "$PYTHON_BIN" "$TOOLS_DIR/curate_figures.py" curate \
      "$PROJECT_DIR" \
      --mode "$MODE" \
      --output-dir "$OUTDIR" \
      --no-md=false >/dev/null 2>"$OUTDIR/curate_figures.stderr"; then
    # The script writes figures_curated.md AND figures_inventory.md to
    # --output-dir. slide_compose's CURATED_FIGURES_PATH input expects
    # a single file; point it at figures_curated.md.
    if [[ -f "$OUTDIR/figures_curated.md" ]]; then
      cp "$OUTDIR/figures_curated.md" "$OUTDIR/curated_figures.md"
      local n_curated
      n_curated="$(grep -c '^### [0-9]\+\.' "$OUTDIR/curated_figures.md" 2>/dev/null || echo 0)"
      echo "  -> wrote $OUTDIR/curated_figures.md ($n_curated figure(s) curated)" >&2
    else
      echo "  warning: curate_figures.py produced no figures_curated.md" >&2
      # Don't fail — slide_compose's escape hatch handles missing figures
    fi
    return 0
  else
    echo "  warning: curate_figures.py exited non-zero — see $OUTDIR/curate_figures.stderr" >&2
    cat "$OUTDIR/curate_figures.stderr" >&2 || true
    # Don't fail the run; figures are an enrichment, not a blocker
    return 0
  fi
}

stage_intro() {
  local out="$OUTDIR/03_slides/intro.json"
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
PLAN_PATH=$OUTDIR/00_plan.md
THROUGHLINE_PATH=$OUTDIR/00_throughline.md
SUBSTORY_PATH=$OUTDIR/02_substories.md
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

stage_slide_compose() {
  local substories="$OUTDIR/02_substories.md"
  echo "" >&2
  echo "[Stage 5/5] slide_compose (per substory)" >&2

  # Enumerate substory IDs from substory_design output
  local substory_ids
  substory_ids=$("$PYTHON_BIN" "$TOOLS_DIR/parse_substories.py" \
    --path "$substories" --field substory_ids)

  if [[ -z "$substory_ids" ]]; then
    echo "Error: no substory IDs parsed from $substories" >&2
    return 1
  fi

  local prior_outputs=""
  for sid in $substory_ids; do
    echo "" >&2
    echo "  -> composing $sid" >&2
    local out="$OUTDIR/03_slides/${sid}_slides.json"
    local user_prompt="OUT_PATH=$out
PROJECT_DIR=$PROJECT_DIR
SUBSTORY_PATH=$substories
SUBSTORY_ID=$sid
THROUGHLINE_PATH=$OUTDIR/00_throughline.md
PLAN_PATH=$OUTDIR/00_plan.md
CURATED_FIGURES_PATH=$OUTDIR/curated_figures.md
CITATION_POOL_PATH=$OUTDIR/citation_pool.json
MODE=$MODE
TIER=$TIER
PRIOR_SUBSTORY_OUTPUTS=$prior_outputs

Run the slide_compose stage for substory $sid. The substory's punchline \
and covered analyses are in $substories. Read REPORT.md sections cited \
by the analyses; verify any quantitative claim before placing it on a \
slide. Note: in this smoke run, CURATED_FIGURES_PATH and \
CITATION_POOL_PATH may not exist — emit slides without figures and \
without citations[] entries in that case (the prompt's escape hatches \
cover this). Write the result to OUT_PATH."

    invoke_claude_with_retry "$PROMPTS_DIR/slide_compose.v1.md" "$user_prompt" "$out" "slide_compose-$sid"

    # Append to prior_outputs for the next substory's PRIOR context
    if [[ -z "$prior_outputs" ]]; then
      prior_outputs="$out"
    else
      prior_outputs="${prior_outputs},${out}"
    fi
  done

  return 0
}

stage_speaker_notes() {
  # 2026-04-27 #70: invoke speaker_notes.v1.md per substory after
  # slide_compose runs. The prompt produces markdown with strict H2
  # headers (`## position N — layout — `title``); parse_speaker_notes.py
  # converts to JSON keyed by position; merge_compose_fragments injects
  # into slide_spec.json's per-slide speaker_notes field.
  echo "" >&2
  echo "[Stage 5.5/7] speaker_notes (per substory)" >&2

  local notes_dir="$OUTDIR/04_speaker_notes"
  mkdir -p "$notes_dir"

  local substory_ids
  substory_ids=$("$PYTHON_BIN" "$TOOLS_DIR/parse_substories.py" \
    --path "$OUTDIR/02_substories.md" --field substory_ids)
  if [[ -z "$substory_ids" ]]; then
    echo "Error: no substory IDs parsed from $OUTDIR/02_substories.md" >&2
    return 1
  fi

  for sid in $substory_ids; do
    echo "" >&2
    echo "  -> notes for $sid" >&2
    local notes_md="$notes_dir/${sid}_speaker_notes.md"
    local notes_json="$notes_dir/${sid}_notes.json"
    local fragment_path="$OUTDIR/03_slides/${sid}_slides.json"

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
SUBSTORY_PATH=$OUTDIR/02_substories.md
THROUGHLINE_PATH=$OUTDIR/00_throughline.md
PLAN_PATH=$OUTDIR/00_plan.md
CITATION_POOL_PATH=$OUTDIR/citation_pool.json
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

stage_merge_and_assemble() {
  echo "" >&2
  echo "[Final] merge fragments + validate + assemble" >&2

  local spec_raw="$OUTDIR/slide_spec.raw.json"
  local spec="$OUTDIR/slide_spec.json"
  local repair_report="$OUTDIR/diagram_repair_report.md"

  "$PYTHON_BIN" "$TOOLS_DIR/merge_compose_fragments.py" \
    --outdir "$OUTDIR" \
    --project-id "$PROJECT_ID" \
    --mode "$MODE" \
    --tier "$TIER" \
    --audience "$AUDIENCE" \
    --throughline-path "$OUTDIR/00_throughline.md" \
    --substory-path "$OUTDIR/02_substories.md" \
    --fragments-dir "$OUTDIR/03_slides" \
    --intro-fragment-path "$OUTDIR/03_slides/intro.json" \
    --speaker-notes-dir "$OUTDIR/04_speaker_notes" \
    --out "$spec_raw"

  echo "  repairing diagram stubs..." >&2
  "$PYTHON_BIN" "$TOOLS_DIR/repair_diagram_stubs.py" \
    --in "$spec_raw" \
    --out "$spec" \
    --report "$repair_report"

  echo "  validating slide_spec.json..." >&2
  "$PYTHON_BIN" "$TOOLS_DIR/slide_spec.py" validate "$spec" || {
    echo "  validation FAILED — see $spec" >&2
    echo "  repair report: $repair_report" >&2
    return 1
  }

  if [[ $SKIP_ASSEMBLY -eq 1 ]]; then
    echo "  [--skip-assembly] stopping before assemble_pptx.py" >&2
    return 0
  fi

  local pptx="$OUTDIR/draft.pptx"
  "$PYTHON_BIN" "$TOOLS_DIR/assemble_pptx.py" \
    "$spec" \
    --out "$pptx" \
    --master "$SKILL_DIR/references/templates/kbase-presentation-master.pptx" || {
    echo "  assemble_pptx FAILED" >&2
    return 1
  }

  echo "" >&2
  echo "==================================================================" >&2
  echo "SMOKE COMPLETE" >&2
  echo "==================================================================" >&2
  echo "  spec:  $spec" >&2
  echo "  deck:  $pptx" >&2
  echo "==================================================================" >&2
}

# ==============================================================================
# Main flow
# ==============================================================================

# --- Resume-aware stage execution ---
# Each stage runs unless RESUME_FROM names a later stage. Gates that
# follow a skipped stage are also skipped (the user's prior choice
# already wrote the canonical file). Order:
#   plan → throughline → (gate) → substory_design → (gate)
#         → intro → slide_compose → merge

# Compute "should we run stage X" for each stage.
should_run() {
  local stage="$1"
  if [[ -z "$RESUME_FROM" ]]; then return 0; fi
  # Map stages to integer ordinals (curate_figures inserted at 4;
  # later stages shifted by 1).
  local order_resume order_stage
  for o in plan:1 throughline:2 substory_design:3 curate_figures:4 intro:5 slide_compose:6 speaker_notes:7 merge:8; do
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

if should_run substory_design;  then stage_substory_design  || { echo "FAIL at substory_design" >&2; exit 1; }
                                     gate_substory_overflow || { echo "FAIL at substory overflow gate" >&2; exit 1; }
                                else echo "[skip] substory_design + overflow gate (resume from $RESUME_FROM)" >&2; fi

if should_run curate_figures;   then stage_curate_figures  || { echo "FAIL at curate_figures" >&2; exit 1; }
                                else echo "[skip] curate_figures (resume from $RESUME_FROM)" >&2; fi

if should_run intro;            then stage_intro           || { echo "FAIL at intro" >&2; exit 1; }
                                else echo "[skip] intro (resume from $RESUME_FROM)" >&2; fi

if should_run slide_compose;    then stage_slide_compose   || { echo "FAIL at slide_compose" >&2; exit 1; }
                                else echo "[skip] slide_compose (resume from $RESUME_FROM)" >&2; fi

if should_run speaker_notes;    then stage_speaker_notes   || { echo "FAIL at speaker_notes" >&2; exit 1; }
                                else echo "[skip] speaker_notes (resume from $RESUME_FROM)" >&2; fi

# merge always runs (it's the final assembly step; cheap)
stage_merge_and_assemble    || { echo "FAIL at merge/assemble" >&2; exit 1; }

exit 0
