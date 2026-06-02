# v0.5 Tier C + D Runbook — Live A/B Morning Start

**Prepared:** 2026-05-25 evening. **Run:** 2026-05-26 morning.

Code-complete state on disk (commit `f10aa9c`, pushed to origin/main).
This runbook is the morning-of step-by-step for kicking off the live A/B.

---

## Pre-flight (5 min) — verify state

```bash
cd /Users/aparkin/Documents/Claude/Projects/research-coscientist-dev/spike/beril-presentation-maker-skill-draft

# 1. Confirm clean state + at f10aa9c
git status              # expect: clean
git log --oneline -1    # expect: f10aa9c v0.5 Tier A.2 ...

# 2. Confirm BERIL_ROOT is set (or export it)
echo "$BERIL_ROOT"
# If empty, set it:
export BERIL_ROOT=/Users/aparkin/Documents/Claude/Projects/research-coscientist-dev/spike/beril-extended

# 3. Confirm provider keys are present in BERIL_ROOT/.env
#    (the orchestrator auto-loads from there; do NOT echo the file)
test -f "$BERIL_ROOT/.env" && echo "env file present" || echo "MISSING .env"

# 4. Sanity: orchestrator --help shows --prompts-version flag
bash src/beril_presentation_maker/skill/tools/presentation_maker.sh --help 2>&1 \
  | grep -A2 "prompts-version"
```

**Expected baselines on disk** (do NOT delete; we reuse them):

```
$BERIL_ROOT/projects/ibd_phage_targeting/talks/
  draft_4   ← v0.3 baseline (M6 Tier B)
  draft_5   ← v0.4 baseline (M6 Tier B, the v0.4.0-experimental candidate)

$BERIL_ROOT/projects/functional_dark_matter/talks/
  draft_2   ← v0.3 baseline (M6 Tier C)
  draft_5   ← v0.4 baseline (M6 Tier C)
```

If any are missing, **stop** — Tier C/D depends on reusing these (saves ~$50).

---

## Tier C — `ibd_phage_targeting` v0.5 run (~$13, ~50 min wall)

The v0.5 run uses **default architecture (v0_3) + v3 prompts**. Lands at
`draft_6`.

```bash
# From skill repo root.
# Architecture flag omitted → defaults to v0_3 per D-069.
bash src/beril_presentation_maker/skill/tools/presentation_maker.sh \
    ibd_phage_targeting \
    --beril-root "$BERIL_ROOT" \
    --prompts-version v3 \
    --auto-advance \
    2>&1 | tee /tmp/v0_5_tier_c_ibd.log
```

**Monitor for:**
- `[orchestrator] CBORG_API_KEY loaded from BERIL_ROOT/.env` (or
  GOOGLE_AI_STUDIO_API_KEY) early — confirms auth picked up.
- `composing S1 ... composing S2 ...` — sequential per-substory
  (default v0_3 pipeline; not parallel).
- Watch for **rc=4 quarantine** in cascade Tier-3 output. Per
  v0.7.0.8 contract, that's NOT-consumer-safe; the orchestrator
  moves it to `.quarantined-rc4` and continues. If you see this,
  note it for Tier E — could be a v3-prompt-induced JSON-shape
  regression worth investigating.
- Final `.pptx` written to
  `$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_6/`.

**Cost cap:** orchestrator's per-stage cost cap is ~$0.08/image
(M5b calibration). Total run estimated ~$13 (similar to v0.3 M6
baseline cost).

**Failure modes to watch:**
- **Empty allowlist is correct.** `register_allowlist.md` doesn't
  exist in either project; the orchestrator fail-softs to empty
  `ALLOWLIST_TERMS=`. Per `check_register_discipline.py`, 6 of 7
  patterns are unambiguous specialist-ref flags (don't need
  allowlist) and the 7th (tool versions) defaults to `allowed`.
  So empty allowlist = safe default; if Tier-E read surfaces
  legitimate audience-relevant terms being flagged, write a
  per-project allowlist mid-run as a v0.5.1 carry.
- **P11 produces 50-100 soft-warnings.** Expected — matches the
  ibd v0.4 draft_5 baseline (59 soft-warnings on M6 verification).
  These don't lift into cascade fail-fast (P11 is soft-warning;
  matches P10 behavior). They're for the Tier-E read to assess
  "did v3 reduce vs v2?"
- **Substory-shape findings (kind=substory_arc) appear in cascade
  Tier-2.** This is the v3 contract working — v3 prompts MUST
  emit Question/Conclusion fields per D-071; substory_shape.py
  flags missing ones at P1.

---

## Tier D — `functional_dark_matter` v0.5 run (~$13, ~50 min wall)

Same command, different project. Lands at `draft_6` for fdm.

```bash
bash src/beril_presentation_maker/skill/tools/presentation_maker.sh \
    functional_dark_matter \
    --beril-root "$BERIL_ROOT" \
    --prompts-version v3 \
    --auto-advance \
    2>&1 | tee /tmp/v0_5_tier_d_fdm.log
```

**Can run in parallel with Tier C** (different project dirs; no
shared state) if you want to halve wall-clock. Costs the same;
just doubles peak token-burn rate. Recommended unless you want to
watch each in isolation.

---

## Scoring (after both runs complete; ~5 min)

`m6_score.py`'s flag names predate v0.5 — they say `v0_3` / `v0_4`
but actually mean "baseline" / "candidate" in our case. Treat v0.5
as the "candidate" (the `--v0_4-*` slot) and v0.3 baseline as the
"baseline" (the `--v0_3-*` slot). Target = ibd (per D-041), sanity
= fdm.

```bash
# Primary score: v0.5 candidate vs v0.3 baseline (the "did v0.5 fix
# what M6 surfaced?" question).
python src/beril_presentation_maker/skill/tools/m6_score.py \
    --v0_3-target "$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_4" \
    --v0_4-target "$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_6" \
    --v0_3-sanity "$BERIL_ROOT/projects/functional_dark_matter/talks/draft_2" \
    --v0_4-sanity "$BERIL_ROOT/projects/functional_dark_matter/talks/draft_6" \
    --target-label "ibd_phage_targeting v0.5-vs-v0.3" \
    --sanity-label "functional_dark_matter v0.5-vs-v0.3" \
    --out /tmp/v0_5_score_vs_v0_3.md \
    2>&1 | tee /tmp/v0_5_score_vs_v0_3.log

# Optional secondary score: v0.5 candidate vs v0.4-experimental
# baseline (the 4-way comparison). Skip unless you want it.
python src/beril_presentation_maker/skill/tools/m6_score.py \
    --v0_3-target "$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_5" \
    --v0_4-target "$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_6" \
    --v0_3-sanity "$BERIL_ROOT/projects/functional_dark_matter/talks/draft_5" \
    --v0_4-sanity "$BERIL_ROOT/projects/functional_dark_matter/talks/draft_6" \
    --target-label "ibd_phage_targeting v0.5-vs-v0.4exp" \
    --sanity-label "functional_dark_matter v0.5-vs-v0.4exp" \
    --out /tmp/v0_5_score_vs_v0_4.md
```

(Output is Markdown via `--out`, not JSON — that's m6_score.py's
contract. The .md is what feeds into Tier E + Tier F paperwork.)

**Cut-over rule (D-065 + D-066 inherited):** v0.5 wins ≥4 of 6
metrics on ibd (target) + ≥40% wall-clock reduction on at least
one project → mechanical PASS. Adam-veto (D-066) is final
regardless.

---

## Tier E — Adam read + veto (~30-60 min Adam-time)

Read these four decks in this order:

1. `ibd_phage_targeting/talks/draft_4` (v0.3 baseline)
2. `ibd_phage_targeting/talks/draft_6` (v0.5 candidate) **← target compare**
3. `functional_dark_matter/talks/draft_2` (v0.3 baseline)
4. `functional_dark_matter/talks/draft_6` (v0.5 candidate)

**Veto questions** (per V0_5_PUNCH_LIST.md Tier E):
- Are substory transitions tighter? (Q → A → R → C arc visible?)
- Did "walls of text poisoned by specialist reference" diminish?
- Do substories build into a unifying point?
- Score metric 5 (the qualitative one m6_score can't measure).

**Veto outcomes:**
- **SHIP** → tag `v0.5.0`; v3 becomes new default; archive v1/v2
  prompts at v0.5.1.
- **DON'T SHIP** → tag `v0.5.0-experimental`; v3 stays opt-in via
  `--prompts-version v3`; v0.6 picks up throughline-bridge +
  figure-utilization (deferred per D-070).
- **MIXED** → ship-but-flag; `v0.5.0-experimental` with operator
  guidance in RELEASE_NOTES.

---

## Tier F + G — paperwork + tag (after Tier E veto)

After the veto, drive me back to update:

- `V0_5_PUNCH_LIST.md` Tier C/D/E rows → SHIPPED with results.
- `V0_4_ARCHITECTURE.md` §16 v0.5 stub → SHIPPED block.
- `RELEASE_NOTES.md` v0.5.0 (or `.0-experimental`) entry.
- `DECISIONS.md` D-075-ish for the veto outcome.
- `SPEC.md` §13 (P11 validator) + §4.2 (Q/A/R/C contract).
- `LAYOUT.md` (check_register_discipline + check_substory_shape
  entries; v3 prompt files).
- Auto-memory `project_presentation_maker_v0_5.md` retrospective +
  promote in MEMORY.md.
- `git tag v0.5.0` (or `v0.5.0-experimental`); `git push --tags`.

---

## What's already in place (no morning prep needed)

- v3 prompts: `prompts/substory_design.v3.md` +
  `prompts/slide_compose.v3.md`.
- Orchestrator: `--prompts-version {v1,v2,v3}` flag (default v2);
  v3-gated injection of SUBSTORY_QUESTION/CONCLUSION/ALLOWLIST_TERMS
  in both v0_3 + v0_4 paths.
- Validators: P11 register-discipline (soft-warning, 38 tests);
  substory_shape Tier-2 cascade reader (24 tests).
- Scoring: `tools/m6_score.py` (unchanged from M6; reused as-is).
- Test suite: 1404 passed.

## What's NOT in place (intentional)

- **No `references/register_allowlist.md`** in either project.
  Per analysis above this is the correct default — 6/7 patterns
  don't need it; the 7th (tool versions) defaults to `allowed`.
  Only create one if Tier-E read surfaces a specific
  audience-relevant term getting flagged.
- **No v0.5 baselines pre-generated.** This is the whole point of
  Tier C/D; the live runs ARE the baseline generation.

---

## Total morning-of estimate

- Pre-flight: 5 min
- Tier C + D (parallel): ~50 min wall-clock + ~$26 spend
- Scoring: 5 min
- Tier E Adam read: 30-60 min
- Tier F/G paperwork (post-veto): 1-2h

**~3-4 hours from start to tag.**
