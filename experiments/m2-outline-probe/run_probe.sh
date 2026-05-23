#!/usr/bin/env bash
# run_probe.sh — M2-lite outline probe.
#
# Tests whether a per-section slide composer that ALSO sees a shared
# whole-deck outline produces better cross-section coordination
# (transitions / register / arc) than one that does not.
#
# Composes 3 ibd_phage_targeting substories under up to 3 conditions:
#   B  naive parallel    — no prior fragments, no outline   (default)
#   C  with outline      — shared outline injected          (default)
#   A  today's pipeline  — sequential, PRIOR_SUBSTORY_OUTPUTS chained
#                          (optional; add --with-today)
#
# The decision-critical comparison is C vs B (does the outline help,
# given we are parallelising anyway). A is an optional reference —
# "does parallel+outline regress vs today's sequential pipeline?"
#
# Each call is `claude -p` with slide_compose.v1.md as the system
# prompt and --output-format json so the envelope's total_cost_usd is
# captured. Fragments land in out/<cond>_<sid>_slides.json; cost ledger
# in out/cost.tsv. Run on a machine with an authenticated `claude` CLI
# (i.e. your Mac, not the sandbox).
#
# Usage:  ./run_probe.sh [--with-today]
set -uo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,28p' "$0"; exit 0
fi
WITH_TODAY=0
[[ "${1:-}" == "--with-today" ]] && WITH_TODAY=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(cd "$HERE/../.." && pwd)"
PROMPT="$SKILL/src/beril_presentation_maker/skill/prompts/slide_compose.v1.md"
PROJECT="$(cd "$SKILL/../beril-extended/projects/ibd_phage_targeting" 2>/dev/null && pwd || true)"
INPUTS="$HERE/inputs"
OUT="$HERE/out"
MODEL="claude-sonnet-4-6"
ALLOWED="Read,Write,Edit,Bash,Grep,Glob"
SUBS=( S1 S2 S3 )

# --- preflight ---------------------------------------------------------
fail() { echo "FATAL: $*" >&2; exit 1; }
command -v claude >/dev/null || fail "claude CLI not on PATH"
command -v python3 >/dev/null || fail "python3 not on PATH"
[[ -f "$PROMPT" ]] || fail "slide_compose prompt not found: $PROMPT"
[[ -n "$PROJECT" && -f "$PROJECT/REPORT.md" ]] || fail "project REPORT.md not found under $PROJECT"
for f in 00_throughline.md 00_plan.md 02_substories.md curated_figures.md citation_pool.json; do
  [[ -f "$INPUTS/$f" ]] || fail "missing input: $INPUTS/$f"
done
[[ -f "$HERE/outline.md" ]] || fail "missing outline.md"

mkdir -p "$OUT"
printf 'condition\tsubstory\tcost_usd\texit\tfragment_written\n' > "$OUT/cost.tsv"
SYS="$(cat "$PROMPT")"

# --- one composition call ---------------------------------------------
# args: condition  substory_id  prior_outputs  mid_block
compose () {
  local cond="$1" sid="$2" prior="$3" mid="$4"
  local frag="$OUT/${cond}_${sid}_slides.json"
  local envf="$OUT/${cond}_${sid}.envelope.json"
  rm -f "$frag"
  echo ">> $cond / $sid  composing ..." >&2

  local user_prompt="OUT_PATH=$frag
PROJECT_DIR=$PROJECT
SUBSTORY_PATH=$INPUTS/02_substories.md
SUBSTORY_ID=$sid
THROUGHLINE_PATH=$INPUTS/00_throughline.md
PLAN_PATH=$INPUTS/00_plan.md
CURATED_FIGURES_PATH=$INPUTS/curated_figures.md
CITATION_POOL_PATH=$INPUTS/citation_pool.json
MODE=talk-30
TIER=STRONG
PRIOR_SUBSTORY_OUTPUTS=$prior
${mid}
Run the slide_compose stage for substory $sid. The substory's punchline and covered analyses are in SUBSTORY_PATH; the critical-analysis inventory with strength glyphs is in PLAN_PATH. Read the REPORT.md sections cited by the analyses and verify any quantitative claim before placing it on a slide. CURATED_FIGURES_PATH and CITATION_POOL_PATH are intentionally empty for this probe — emit slides without figures and without citations[] entries (the prompt's escape hatches cover this). Write the result to OUT_PATH."

  local envelope rc
  envelope="$(claude -p --model "$MODEL" --system-prompt "$SYS" \
    --allowedTools "$ALLOWED" --output-format json \
    --dangerously-skip-permissions "$user_prompt" 2>"$OUT/${cond}_${sid}.stderr")"
  rc=$?
  printf '%s\n' "$envelope" > "$envf"

  local cost
  cost="$(printf '%s' "$envelope" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("total_cost_usd","?"))
except Exception: print("?")' 2>/dev/null)"
  local written="no"; [[ -s "$frag" ]] && written="yes"
  printf '%s\t%s\t%s\t%s\t%s\n' "$cond" "$sid" "$cost" "$rc" "$written" >> "$OUT/cost.tsv"
  echo "   $cond/$sid  exit=$rc  cost=\$$cost  fragment=$written" >&2
}

# --- condition A (optional): today's sequential pipeline ---------------
if [[ "$WITH_TODAY" == "1" ]]; then
  echo "" >&2
  echo "=== Condition A — today's sequential (PRIOR_SUBSTORY_OUTPUTS chained) ===" >&2
  prior=""
  for sid in "${SUBS[@]}"; do
    compose "A" "$sid" "$prior" ""
    frag="$OUT/A_${sid}_slides.json"
    [[ -s "$frag" ]] && prior="${prior:+$prior,}$frag"
  done
fi

# --- condition B: naive parallel — no prior, no outline ----------------
echo "" >&2
echo "=== Condition B — naive parallel (no prior outputs, no outline) ===" >&2
for sid in "${SUBS[@]}"; do
  compose "B" "$sid" "" ""
done

# --- condition C: with shared whole-deck outline -----------------------
echo "" >&2
echo "=== Condition C — with shared whole-deck outline ===" >&2
OUTLINE="$(cat "$HERE/outline.md")"
C_MID="WHOLE-DECK OUTLINE (shared context for cross-section coordination):
---
${OUTLINE}
---
You are composing ONE section of the deck outlined above. Use the outline: open your section's content by leading in from the prior section's close, and shape its final slide so it hands off to the next section as the outline describes. Keep register consistent with the deck-level register spec. Within your section, foreground the claims the outline scopes to it. The outline is shared context — it does NOT replace SUBSTORY_PATH / PLAN_PATH, which remain authoritative for this section's analyses and budget."
for sid in "${SUBS[@]}"; do
  compose "C" "$sid" "" "$C_MID"
done

# --- summary -----------------------------------------------------------
echo "" >&2
echo "=== DONE — cost ledger at $OUT/cost.tsv ===" >&2
python3 - "$OUT/cost.tsv" <<'EOF' >&2
import sys
tot, n, miss = 0.0, 0, 0
with open(sys.argv[1]) as f:
    next(f, None)
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) < 5:
            continue
        n += 1
        try: tot += float(p[2])
        except ValueError: pass
        if p[4] != "yes": miss += 1
print(f"  {n} calls, total ${tot:.4f}" + (f"  ({miss} produced no fragment — check *.stderr)" if miss else ""))
EOF
echo "  Fragments: $OUT/{B,C}_S{1,2,3}_slides.json" >&2
