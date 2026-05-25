# M6 Punch List — A/B test + cut-over decision

**Status:** drafted 2026-05-24 (post-M5b). Authoritative scope:
`V0_4_ARCHITECTURE.md` §15 + §16 M6. DQ resolutions inlined below
(Adam's calls 2026-05-24).

**Posture.** M6 is the cut-over gate — the ship/no-ship decision
for v0.4 as the default pipeline. No new code paths beyond a
scoring script + a state-schema investigation. Live spend
dominates the milestone (~$32–48 across 4 talk runs).

## Per-tier status

| Tier | Scope | Status |
|---|---|---|
| 0 — investigate paper-writer state model + decide v0.4 state-schema posture (DQ1) | research + DECISION | ✅ committed 2026-05-24 (D-067 lands option (a) — DROP the state-schema deliverable from M6; D-038 OBSOLETED. Three findings drove the call: (1) no v0.3 schema exists to migrate FROM (zero `state.json` files across all `talks/` projects); (2) M6 A/B scoring data is already on disk — `audit/runs/run-N/summary.json` (schema `run-summary.v1`, written by `finalize_run.py` EXIT trap) has wall-clock + cost + tokens + stages_run, `stage-metadata.json` has per-stage breakdown; (3) no operational request for resume-with-state-restore (zero memory entries, file-presence-based resume works today). Paper-writer's 687-line state.py is reference value (hash-diff source-change detection, user-edit detection) but rejected for M6 — adopt-at-scale = v0.5+; lightweight state.json would duplicate `runs/run-N/summary.json`. Tier-A scoring script (next) consumes existing audit files, no state.json needed) |
| A — scoring script (`tools/m6_score.py`) | new tool + tests | ✅ ready to commit 2026-05-24 (new `tools/m6_score.py` ~530 lines: `aggregate_runs` (sums cost+elapsed across `runs/run-N/summary.json` per D-067 — no state.json needed), `count_adversarial_findings` (adversarial_review.json primary; cascade tiers[2] fallback), `count_validator_failures` (count of fail-status validators), `aggregate_image_budget` (image_provenance.json entries); `compare_lower_is_better` with ±5% tie band + n/a handling + zero-baseline edge case; `compare_subjective_higher_is_better` for metric 5; `score_project` orchestrates 6-metric extraction; `evaluate_decision` applies D-065 (≥4/6 on target) + wall-clock ≥40% gate; `render_report` emits Markdown with Adam-veto checkboxes per D-066. CLI accepts `--v0_3-target/--v0_4-target` (required) + optional sanity pair + `--subjective-scores` + `--out` + `--tie-band-pct`; 30 new tests pin extraction logic + comparison math + decision rule + report shape + CLI arg pairing; suite 1309 passed) |
| B — A/B run on `ibd_phage_targeting` (target; talk-30 STRONG) | live (~$16–24) | ⬜ not started |
| C — A/B run on `functional_dark_matter` (sanity; talk-30 STRONG) | live (~$16–24) | ⬜ not started |
| D — Adam reads both decks + subjective scoring (metric 5) + veto decision (D-066) | review + DECISION | ⬜ not started |
| E — SPEC + DECISIONS + LAYOUT + RELEASE_NOTES (cut-over outcome) | docs | ⬜ not started |
| F — closeout (V0_4_ARCHITECTURE §16 M6 → SHIPPED; auto-memory; v0.4.0 tag if pass) | paperwork + tag | ⬜ not started |

## DQ resolutions (Adam 2026-05-24)

- **DQ1: State-schema migration scope** — **(investigate first, then
  decide).** §16 M6's "state-schema v0.3 → v0.4 migration" is moot as
  literally written (no presentation-maker state.json exists; the
  orchestrator's line 19 comment names itself as canonical). But
  paper-writer has a serious 687-line `state.py` with `DraftState`,
  `compute_artifact_hashes`, `diff_artifacts`, `STATE_SCHEMA_VERSION`,
  Phase enum — built for **restartability with source-change
  detection** (re-run `continue`, paper-writer reports which source
  artifacts changed since last build). Tier 0 examines paper-writer's
  model and decides whether presentation-maker should adopt it (lands
  as a new DECISION, candidate D-N TBD). The "v0.3 → v0.4 migration
  script" deliverable from §16 is **dropped** regardless (no v0.3
  schema to migrate FROM); only the question of "should we have a
  centralized state.json at all" remains.

- **DQ2: Metric 7 (paper-review skill quality)** — **DROP.** Lands as
  **D-065**. There is no skill named `paper-review` in the workspace;
  the §15 reference is a phantom dependency. Adjusted decision rule:
  v0.4 must dominate v0.3.8 on **≥4 of 6** metrics (was ≥5 of 7);
  primary metric (wall-clock ≥40% reduction) remains mandatory.

- **DQ3: A/B harness implementation** — **(a) Manual: 4 separate
  orchestrator runs + 1 scoring script.** Lowest-magic; matches how
  M4b Tier E was run. Each run gets its own audit dir; `tools/m6_score.py`
  reads all 4 audit dirs + emits a comparison Markdown. ~3h scoring
  script + manual coordination of the runs. No new harness CLI; the
  orchestrator's existing `--architecture-pipeline {v0_3|v0_4}` flag
  is the toggle.

- **DQ4: Decision-rule edge case** — **Adam-veto explicit.** Lands as
  **D-066**. The ≥4/6 rule is **advisory**; the human reviewer is
  final. Adam can call "this isn't good enough to ship" after reading
  both decks regardless of the metric count, OR can call "ship it"
  despite missing a metric if the failure is non-substantive (e.g.,
  token cost up 10% but adversarial findings significantly better).
  Per the panel-of-one project posture.

## Tier 0 — state-schema investigation (DQ1)

Read-only research; no code. Result is a one-page decision artifact
+ new DECISION entry.

**0.1 Read paper-writer state.py end-to-end** (687 lines):
- Catalog every field in `DraftState` (probably ~15–25 fields).
- Catalog every method (`load_state`, `save_state`, `is_user_edited`,
  `compute_artifact_hashes`, `diff_artifacts`, etc.).
- Note the resume-from-pause flow that consumes `state.json`.

**0.2 Read presentation-maker orchestrator for shell-canonical state**:
- Inventory what the orchestrator tracks via shell variables across
  stages (PROJECT_ID, MODE, TIER, AUDIENCE, OUTDIR, DRAFT_N,
  ARCH_PIPELINE, IMAGE_PROVIDER, …).
- Identify which would meaningfully change behaviour if re-loaded
  on resume (vs which are just per-stage inputs).
- Inventory the per-stage `audit/*.json` files we already emit —
  they may already cover "what stage am I at" via presence.

**0.3 Compare against actual operational pain**:
- Do we have user-reported issues that a centralized state.json
  would fix? (e.g., resume-from-stage UX bugs; "what did I run
  last?" confusion; source-change-detection requests.)
- Check `.auto-memory/MEMORY.md` for any
  feedback_presentation_state_* entries.
- Check the carry list from M3-M5b for any items that imply state-
  schema would help.

**0.4 Draft DECISION + recommendation**. Lands as candidate D-N
(numbering TBD; depends on what's used by other Tier-E/F entries).

Three sub-options the DECISION may land on:
- **(a) Drop the deliverable**: D-038 obsoleted; per-stage audit
  JSONs are sufficient; orchestrator-canonical state is fine.
  Smallest M6 scope.
- **(b) Adopt the paper-writer pattern at scale**: build
  presentation-maker `state.py`, port DraftState/load_state/save_state,
  add hash-diff source-change detection. ~3–5 days of work; would
  push M6 substantially. **Likely too big for M6** — should become
  v0.5.
- **(c) Lightweight state.json with no migration**: add the minimal
  `state.json` capturing phase + cost + draft_n + last_stage; no
  hash-diff. Fits in M6 (~1 day). Useful for resume UX
  improvements; doesn't change correctness.

**AC for Tier 0:** decision artifact written + a DECISION entry
added. Tier 0 doesn't itself ship state.json work; if (b) or (c)
is picked, a follow-up tier (or a separate milestone) handles
implementation.

## Tier A — scoring script

**A.1 New `tools/m6_score.py`** — reads 4 audit dirs (2 projects ×
2 pipelines) and emits a comparison Markdown.

Per-run inputs (from each audit dir):
- `<audit>/state.json` (if Tier 0 picks option c) OR the orchestrator
  emits a summary line at end-of-run via a new
  `cmd_emit_run_summary` helper.
- `<audit>/review_cascade.json` — finding counts by tier + severity.
- `<audit>/presentation_validation.json` — P1–P10 validator
  results (metric 4).
- `<audit>/quantitative_grounding.json` — for cross-reference.
- `<audit>/adversarial_review.json` — Tier-3 findings count
  (metric 3).
- `<audit>/image_provenance.json` — image count + cumulative cost
  (metric 6).
- Wall-clock + token-cost: harvested from per-stage stream logs OR
  from the orchestrator emitting a summary file. **Decision point**:
  if `state.json` doesn't exist (Tier 0 option a/c without
  cumulative-cost), wall-clock + token-cost have to come from the
  orchestrator's stream logs. May need a small orchestrator
  patch to emit `audit/run_summary.json` per run.

Metric mapping:
| # | Metric | Source |
|---|---|---|
| 1 | Wall-clock (start → end) | `audit/run_summary.json::wall_clock_seconds` |
| 2 | Token cost | `audit/run_summary.json::cumulative_cost_usd` |
| 3 | Adversarial findings count | `audit/adversarial_review.json::findings_count` (or `audit/review_cascade.json::tiers[2].n_findings` if cascade ran) |
| 4 | Validator failure rate at Tier 1 | `audit/presentation_validation.json::violations.length` (post-first-composition only — pre-revise) |
| 5 | Cross-substory arc coherence | Adam-subjective (Tier D); scoring script just shows placeholder |
| 6 | Image-budget adherence | `audit/image_provenance.json::entries[].cost_usd.sum()` vs `--max-image-cost-usd` |
| ~~7~~ | ~~Paper-review~~ | **DROPPED per D-065** |

**A.2 Comparison logic** — for each metric:
- Compute v0.4 − v0.3 delta (absolute + percent).
- Score: v0.4 wins (lower-is-better metrics: 1, 2, 3, 4, 6) or
  loses; tie (within 5%) counts as no-decision.
- Emit per-project sub-totals + overall (2 projects × 6 metrics =
  12 metric-instances).

**A.3 Output format** — `audit/m6_score_report.md`:
```
# M6 A/B comparison
## ibd_phage_targeting
| Metric | v0.3 | v0.4 | Δ | v0.4 wins? |
|---|---|---|---|---|
| 1. wall-clock | 32m12s | 14m38s | -55% | ✓ |
| 2. token cost | $8.45 | $6.92 | -18% | ✓ |
...
**Sub-total**: 4/6 in v0.4's favour
**Wall-clock primary**: ✓ ≥40% reduction met

## functional_dark_matter
[similar table]

## Aggregate
**Decision rule (D-065 + D-066 adjusted)**: v0.4 wins ≥4 of 6 metrics
on at least the target project (ibd_phage_targeting) AND wall-clock
≥40% reduction on at least one project.

**Score**: [auto-computed]
**Adam-veto** (D-066): [REVIEW REQUIRED — fill at Tier D]
```

**A.4 Tests**:
- Unit: scoring math on synthetic audit JSONs (each metric's source
  format pinned).
- Unit: decision-rule application on fixed score combinations
  (wins, losses, ties, missing-data).
- Unit: report rendering pin (output Markdown matches expected
  shape).

**AC for A:** `m6_score.py --audit-dirs <4>` produces a valid
report; tests pin scoring math + decision rule against synthetic
inputs.

## Tier B — A/B on `ibd_phage_targeting`

Two orchestrator runs on the same project, same talk-30 STRONG.

**B.1 v0.3 run**:
```
presentation_maker.sh \
    --project-id ibd_phage_targeting \
    --mode talk-30 --tier STRONG \
    --beril-root <BERDL_FORK> \
    --architecture-pipeline v0_3 \
    --max-image-cost-usd 0.50 \
    --image-provider cborg  # CBORG image-gen non-functional on Adam's
                            # tenant per M5b Tier E — image-gen will
                            # disable gracefully; doesn't block run
```
- Lands at `<BERDL_FORK>/projects/ibd_phage_targeting/talks/draft_N1`.
- Expected wall-clock ~25–35 min; expected cost ~$8–12 (M4b Tier E
  observed range, v0.3-side).

**B.2 v0.4 run**:
```
presentation_maker.sh \
    --project-id ibd_phage_targeting \
    --mode talk-30 --tier STRONG \
    --beril-root <BERDL_FORK> \
    --architecture-pipeline v0_4 \
    --max-image-cost-usd 0.50 \
    --image-provider cborg
```
- Lands at `<BERDL_FORK>/projects/ibd_phage_targeting/talks/draft_N2`.
- Expected wall-clock ~12–18 min (parallel-compose); expected cost
  ~$8–12 (same per-token rate, fewer wall-clock minutes).

**Pre-flight checklist**:
- Confirm `<BERDL_FORK>/projects/ibd_phage_targeting/REPORT.md`
  unchanged since the M4b/M5a runs (or document the change).
- Confirm both pipelines see the same `claim_inventory.tsv`
  (M1 Phase-0 output; reused via `--resume-from` shortcut if
  applicable, OR fresh-run to keep timing comparable).
- Pre-stage adversarial-skill is available + working
  (`beril-adversarial --version` from PATH).
- AI Studio billing enabled if `--image-provider google_ai_studio`
  is wanted (per M5b Tier E findings).

**B.3 Capture**:
- Both audit dirs preserved in-place; do NOT delete after.
- Stream logs captured (orchestrator's existing `stream_progress.py`
  output redirected to file).
- Emit a `audit/run_summary.json` per run (may require a small
  orchestrator patch; tracked under Tier A as a dependency).

**AC for B:** both runs complete (or fail with a clear diagnostic);
audit dirs intact; run_summary.json present.

**B-budget cap**: hard-stop at $30 cumulative; if either run exceeds
that, halt + escalate to Adam.

## Tier C — A/B on `functional_dark_matter`

Same as Tier B but on the second project. Same model arguments;
same image-provider; same talk-30 STRONG. Adds a sanity-check
data point so the decision isn't based on a single project.

**Pre-flight**: confirm `functional_dark_matter` has a current REPORT.md
+ notebooks; v0.3.x has run on it before (draft_4 exists), so
infrastructure should work.

**Output**: 2 more audit dirs (1 v0.3, 1 v0.4); same capture as Tier B.

**C-budget cap**: hard-stop at $30 cumulative for this tier
(combined with Tier B, M6 spend cap = ~$60).

## Tier D — Adam reads + scores metric 5 + veto decision

**D.1 Adam reads both pairs of decks back-to-back**:
- ibd v0.3 → ibd v0.4 (compare arc coherence)
- fdm v0.3 → fdm v0.4 (same)
- 5-point Likert rating per pair on cross-substory transitions
  (per §15 metric 5 wording).

**D.2 Inputs to Tier-A scoring script**:
- Adam enters the metric-5 scores into a small JSON file
  (`audit/m6_subjective_scores.json` or similar) that
  `m6_score.py` reads alongside the audit JSONs.

**D.3 Adam-veto** (D-066): explicit "ship / don't ship / ship-but-
flag" decision recorded in DECISIONS.md regardless of what the
score script outputs.

Three veto outcomes:
- **Ship**: v0.4 becomes default; v0.3 prompts move to archive.
- **Don't ship**: v0.4 stays opt-in via `--architecture-pipeline
  v0_4`; v0.3 remains default; file follow-ups on the gaps.
- **Ship-but-flag**: v0.4 becomes default but a stderr warning
  prints "v0.4 pipeline (experimental — known regressions: X, Y)"
  for one release.

**AC for D:** decision artifact written + DECISION D-N entry.

## Tier E — docs

**E.1 SPEC.md** update to reflect cut-over outcome (whichever
default).

**E.2 LAYOUT.md** — if Tier 0 ships a state.py, document it; if not,
no changes here.

**E.3 DECISIONS.md** — Tier-0 outcome DECISION, D-065 (drop metric 7),
D-066 (Adam-veto), Tier-D decision DECISION.

**E.4 V0_4_ARCHITECTURE.md** §15 + §16 M6 → SHIPPED block.

**E.5 RELEASE_NOTES.md** — v0.4.0 release notes (or whatever the
final ship version is); high-level summary of the v0.4 architecture
+ links to per-milestone retrospectives in auto-memory.

**AC for E:** docs reflect the actual shipped state; DECISIONS
chronological order maintained; cross-references intact.

## Tier F — closeout + tag

**F.1 V0_4_ARCHITECTURE §16 M6 → SHIPPED** block (full ledger).

**F.2 auto-memory** `project_presentation_maker_v0_4_m6.md` (final
v0.4 retrospective: what shipped, what carry, lessons learned
from the cut-over experience).

**F.3 MEMORY.md index** — promote M6 to top; demote M5b/M5a.

**F.4 Git tag** if Tier-D outcome was "ship":
```
git tag -a v0.4.0 -m "v0.4.0 — architect-then-parallel-compose default"
git push --tags
```

If "don't ship" or "ship-but-flag": tag as `v0.4.0-rc1` or
`v0.4.0-experimental` per outcome.

**AC for F:** retrospective written; MEMORY.md index updated;
tag pushed (if applicable).

## Dep edges

```
0 ──┬──> A (scoring script may depend on state-schema outcome)
    └──> E (docs need Tier-0 DECISION)
A ──> B (scoring script ready before any live run)
B ──> C (sequential — keep harness simple; could be parallelized
                       but adds cost-tracking complexity)
B + C ──> D (Adam reads both pairs)
D ──> E (Tier-D DECISION lands in docs)
E ──> F
```

Tier 0 + Tier A can run in parallel. Tier B and C are sequential
(serializes spend; halt mid-flight if v0.3 runs are blowing
budget). Tier D blocks on Tier C. Tier E + F are paperwork.

## Smoke gates

- **Tier 0 gate**: DECISION entry drafted + Adam signoff before
  any further M6 work.
- **Tier A gate**: scoring script tests green; renders an example
  report against synthetic audit JSONs.
- **Tier B gate**: both ibd runs complete; audit dirs present;
  cumulative spend ≤ $30.
- **Tier C gate**: same for fdm; cumulative M6 spend ≤ $60.
- **Tier D gate**: Adam-veto decision recorded; metric-5 scores
  entered.
- **Tier E gate**: doc cross-references pass a manual review.

## What M6 does NOT do (→ post-cut-over)

- **Centralized state.py for presentation-maker** (unless Tier 0
  picks option c-small; option b-paper-writer-clone is v0.5).
- **A `--resume-from` UX improvement** (depends on state.json
  existing).
- **The M3–M5b carry items** (4 deferred items). Track separately
  for a v0.4.1 tidy release post-M6.
- **CBORG image-gen restoration** (separate CBORG-admin issue).
- **Bimodal AI Studio wall-clock investigation** (M5b carry).
- **OpenAI gpt-image-1 third-provider** (not requested).

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — state-schema investigation | 1–2 h research + DECISION |
| A — scoring script | 3–4 h coding + tests |
| B — ibd_phage_targeting A/B | ~50 min wall-clock + ~$20 spend |
| C — functional_dark_matter A/B | ~50 min wall-clock + ~$20 spend |
| D — Adam reads + veto | 30–60 min Adam-time |
| E — docs | 1–2 h |
| F — closeout + tag | 30 min |
| **Total** | ~10–14 h coding/docs; ~$32–48 live spend; ~2 h Adam-attention |

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| v0.3 pipeline has regressed (no run since M3) | Tier B does a v0.3 run cold; if it fails, that's the answer — v0.3 is dead, ship v0.4 by default |
| Wall-clock primary gate fails (v0.4 ≥40% reduction not met) | M3 had reconciliation slipping; if it's the slow path causing this, M3 work continues post-M6 as v0.4.1 |
| Image-gen path adds noise (CBORG broken, AI Studio variable timeout) | Both runs disable image-gen via `--no-images` if necessary; metric 6 becomes N/A |
| Adversarial schema drift since M4b | Run `beril-adversarial --version` pre-flight; pin to the M4b-known version if needed |
| Spend exceeds cap mid-run | Hard halt at $30/tier; escalate to Adam |
| `functional_dark_matter` REPORT.md is stale or missing | Tier C runs depend on the project being live; if not, M6 can ship on ibd_phage_targeting alone with documented sanity-check skip |

## Ref

- `V0_4_ARCHITECTURE.md` §15 (cut-over gate criteria) + §16 M6 +
  D-038 (state-schema decision being revisited) + D-041 (A/B in
  both projects).
- `M5b_PUNCH_LIST.md` (mirror format).
- `tools/presentation_maker.sh` — `--architecture-pipeline {v0_3|v0_4}`
  flag (the toggle); auth-discovery + provider precedence (M5b/D-062);
  cascade auto-run (M4b/D-054).
- Paper-writer `src/beril_paper_writer/state.py` — 687-line state
  model reference for DQ1 / Tier-0 investigation.
- Carry list (4 items: portable visual-QA, Tier-2 prompt v2, Tier-2
  cost-in-JSON, dead `_extract_numeric_claims`) deferred to v0.4.1.
