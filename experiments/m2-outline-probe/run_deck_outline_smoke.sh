#!/usr/bin/env bash
# run_deck_outline_smoke.sh — M2 Tier D smoke.
#
# Runs deck_outline.v1.md once (standalone `claude -p`, the probe
# pattern — no orchestrator, so no composition) on ibd_phage_targeting,
# producing a real enriched 02_substories.md. Then parses it with BOTH
# parse_substories.py (carried skeleton) and parse_deck_outline.py (the
# v0.4 fields) to confirm it is well-formed.
#
# Inputs are reused from the outline probe (inputs/) plus paper-writer's
# real Phase-0 artifacts (claim_inventory.tsv + methods_provenance.md)
# under papers/draft_2/. Run on a machine with an authenticated `claude`
# CLI (your Mac).
#
# Usage:  ./run_deck_outline_smoke.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(cd "$HERE/../.." && pwd)"
PROMPT="$SKILL/src/beril_presentation_maker/skill/prompts/deck_outline.v1.md"
TOOLS="$SKILL/src/beril_presentation_maker/skill/tools"
PROJECT="$(cd "$SKILL/../beril-extended/projects/ibd_phage_targeting" 2>/dev/null && pwd || true)"
INPUTS="$HERE/inputs"
OUT="$HERE/out"
MODEL="claude-sonnet-4-6"
ALLOWED="Read,Write,Edit,Bash,Grep,Glob"

fail() { echo "FATAL: $*" >&2; exit 1; }
command -v claude  >/dev/null || fail "claude CLI not on PATH"
command -v python3 >/dev/null || fail "python3 not on PATH"
[[ -f "$PROMPT" ]] || fail "deck_outline.v1.md not found: $PROMPT"
[[ -n "$PROJECT" ]] || fail "ibd_phage_targeting project not found"
PHASE0="$PROJECT/papers/draft_2"   # paper-writer's real claim_inventory + methods_provenance
for f in "$INPUTS/00_throughline.md" "$INPUTS/00_plan.md" \
         "$INPUTS/curated_figures.md" "$INPUTS/citation_pool.json" \
         "$PHASE0/claim_inventory.tsv" "$PHASE0/methods_provenance.md"; do
  [[ -f "$f" ]] || fail "missing input: $f"
done

mkdir -p "$OUT"
OUTFILE="$OUT/deck_outline_smoke_02_substories.md"
rm -f "$OUTFILE"

USER_PROMPT="OUT_PATH=$OUTFILE
PROJECT_DIR=$PROJECT
PLAN_PATH=$INPUTS/00_plan.md
THROUGHLINE_PATH=$INPUTS/00_throughline.md
CLAIM_INVENTORY_PATH=$PHASE0/claim_inventory.tsv
CURATED_FIGURES_PATH=$INPUTS/curated_figures.md
CITATION_POOL_PATH=$INPUTS/citation_pool.json
CROSS_TENANT_PATH=$PROJECT/cross_tenant_signal.md
METHODS_PROVENANCE_PATH=$PHASE0/methods_provenance.md
MODE=talk-30
TIER=STRONG

Run the deck_outline stage. Read the chosen throughline, the plan's critical-analysis inventory, and the Phase-0 artifacts. Cluster the analyses into substories; for each section prescribe the slide budget, headline slot, transition-in/out, and scoped figures; write the deck-level register, arc, and image budget. CURATED_FIGURES_PATH and CITATION_POOL_PATH are intentionally empty for this smoke, and CROSS_TENANT_PATH may be absent (the prompt's escape hatches cover all three — scoped figures will be '(none)'). Compute the mode-capacity verdict; if overflow, surface the options and halt. Write the result to OUT_PATH."

echo ">> running deck_outline (Sonnet) ..." >&2
ENV="$(claude -p --model "$MODEL" --system-prompt "$(cat "$PROMPT")" \
  --allowedTools "$ALLOWED" --output-format json \
  --dangerously-skip-permissions "$USER_PROMPT" 2>"$OUT/deck_outline_smoke.stderr")"
RC=$?
printf '%s\n' "$ENV" > "$OUT/deck_outline_smoke.envelope.json"
COST="$(printf '%s' "$ENV" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("total_cost_usd","?"))
except Exception: print("?")' 2>/dev/null)"
echo "   exit=$RC  cost=\$$COST" >&2

[[ -s "$OUTFILE" ]] || fail "deck_outline produced no output file (see $OUT/deck_outline_smoke.stderr)"

echo "" >&2
echo "=== parse_substories.py — carried skeleton (must still work) ===" >&2
python3 "$TOOLS/parse_substories.py" --path "$OUTFILE" --field substory_ids       | sed 's/^/  substory_ids:     /' >&2
python3 "$TOOLS/parse_substories.py" --path "$OUTFILE" --field capacity_verdict   | sed 's/^/  capacity_verdict: /' >&2

echo "" >&2
echo "=== parse_deck_outline.py — v0.4 fields ===" >&2
for fld in register arc image_budget budgets headline_slots transitions_in transitions_out scoped_figures; do
  echo "  --- $fld ---" >&2
  python3 "$TOOLS/parse_deck_outline.py" --path "$OUTFILE" --field "$fld" 2>&1 | sed 's/^/    /' >&2
done

echo "" >&2
echo "=== DONE — enriched outline at $OUTFILE (cost \$$COST) ===" >&2
