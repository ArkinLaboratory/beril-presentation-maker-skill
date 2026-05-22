# v0.4.x Punch List

**Last updated:** 2026-05-06 (post Tier-A ship + diagnostic data review)
**Current shipped state:** v0.3.8.
**Status:** active — opportunistic pre-May-7 ship; v0.3.8 is the safe Thursday floor.

## What v0.3.8 ships

Three coordinated capabilities now live in main:

- **v0.3.6 halt-and-handoff** at the throughline-pick gate (paper-writer pattern). Fixes 100% TTY-block failure for hub participants.
- **v0.3.7 image_gen_decision LLM-judgment layer.** Closes the silent "deferred to v0.3.4" bug; figure-rich projects now produce 5-12 AI illustrations instead of 0. Per-call cost ~$0.005-0.01; net per-draft +$0.10-0.20.
- **v0.3.8 process-detail-bleed post-checker.** Mechanical scan over slide content + speaker_notes for internal-artifact references; advisory output to `<draft_dir>/audit/no_artifact_refs.md`. On the live `ibd_phage_targeting` deck: 30/37 slides flagged with 496 hits across all 6 pattern categories — actionable hand-edit checklist.

861 unit tests passing. Wall-clock per `talk-45 STRONG` end-to-end: ~3.7h on the hub (verified). Cost: $16-20 per draft.

## Gap analysis from May 5-6 live data

Two diagnostic findings reshape what's worth doing next:

1. **Per-substory fan-out is 80% of wall-clock and 86% of cost.** Verified from `audit/runs/run-3/summary.json` on ibd_phage_targeting: stages 3-10 (citation_pool through speaker_notes) ran 158 minutes for $14.23. Within that segment, `slide_compose-S{1,2,3}` and `speaker_notes-S{1,2,3}` are six independent LLM calls that operate on independent substory data and currently run sequentially. Worker-pool parallelization is the single biggest available wall-clock win — estimated 60-90 min saved per draft.

2. **Process-detail bleed lives mostly in speaker notes (50%) and qa_anticipated answers (24%).** Of 497 hits flagged on the live deck, 247 are in speaker_notes and 122 are in qa_anticipated answer fields. Original task #88 (revise-loop bias) was filed at the wrong layer — the bleed is upstream in `qa_prep.v1.md` and `speaker_notes.v1.md` prompts, not in revise. Prompt-rule edits to those two prompts would address ~75% of the remaining post-checker hits.

## Sequencing — go/no-go decision tree

```
v0.3.8 (SHIPPED 2026-05-06)
  │
  ├─ Tier B (pre-May-7 IF time allows; small surface, low risk)
  │   │
  │   ├─ B1  Docs update — wall-clock from real data            [DONE 2026-05-06]
  │   ├─ B2  Live-test image-gen LLM-judgment on a fresh project [pending Adam's run]
  │   ├─ B3  qa_prep.v1.md anti-pattern rule + worked example   [~2-3h, taste-level]
  │   └─ B4  speaker_notes.v1.md anti-pattern rule + example    [~2-3h, taste-level]
  │
  ├─ Tier C (post-May-7, larger surface or architectural)
  │   │
  │   ├─ C1  Per-substory worker-pool for slide_compose +       [~6-8h, biggest wall-clock win]
  │   │     speaker_notes (#89 fix)
  │   ├─ C2  state.json + Phase enum (#85, paper-writer parity, [~1.5-2 days, architectural]
  │   │     replaces single-purpose .handoff.json)
  │   ├─ C3  Vocabulary-shaped-codes refinement to              [~1-2h, post-checker noise reduction]
  │   │     check_no_artifact_refs (E\d, S\d in vocab-defined
  │   │     mode rolled into single deck-level note)
  │   ├─ C4  finalize_run.py no-op detection (#91)              [~30min, data hygiene]
  │   ├─ C5  Plan stage refactor (parallelize internal sub-     [~1 day, profile-driven]
  │   │     tasks; second-biggest wall-clock target)
  │   └─ C6  Layout cosmetic fixes (#74-77)                     [hand-fixable for May 7;
  │                                                              v0.4.x cleanup]
  │
  └─ Tier D (Adam's call — possibly merge or defer)
      │
      ├─ D1  revise_slide.v1 caveat-handling rewrite (original  [taste-level; defer until C3
      │     #88 scope before re-targeting)                       lands and we have data]
      └─ D2  citation_pool stage validator: filename-only        [related to v0.3.8 post-checker;
            citations flagged                                    integrate post-event]
```

## Pre-event recommendation (next 24h)

**Sequence A — minimal additional ship (recommended).**

1. **Docs update (DONE)** — corrected wall-clock + cost in TUTORIAL.md + PARTICIPANT-RUNBOOK.md per the live `ibd_phage_targeting` data.
2. **Adam runs a fresh-project draft on the hub** to live-test the v0.3.7 image-gen LLM-judgment calibration. Output:
   - `<draft_dir>/working/05_image_decisions.json` — confirm `llm_judgment_used: true` and 3-12 emit=true entries on a typical talk-30 STRONG.
   - Inspect 1-2 generated illustrations for quality.
3. **If calibration looks right:** stop here. v0.3.8 is the May 7 floor.
4. **If calibration is off (>50% emit=true on talk-30, or <3 emit=true on talk-45 STRONG):** prompt-iterate `_build_judge_prompt()` and ship as v0.3.9 by Wednesday EOD. Otherwise the docs are honest and the floor is solid.

**Sequence B — opportunistic prompt fixes (if time allows after sequence A).**

5. **B3 + B4: qa_prep + speaker_notes anti-pattern rules.** Two small prompt-rule edits modeled after slide_compose's existing structure. Per-prompt change is well-scoped (worked example showing artifact-citation → peer-citation substitution). Ship as v0.3.9 docs+prompt patch. Risk: prompt regressions are hard to pre-test; if it ships and underperforms, the post-checker still catches the issue advisory-only.

If Sequence A reveals image-gen needs prompt iteration, fold B3/B4 into the same v0.3.9 ship to amortize the testing-and-tagging cost.

**What I'd NOT do pre-event:**

- Per-substory parallelization (C1). Bash worker-pool patterns are fragile under concurrent LLM calls; needs careful test design. 6-8h focused work + smoke testing. Wrong project to land in <24 hours.
- state.json refactor (C2). 1.5-2 days. Same reasoning.
- Plan stage refactor (C5). Profile-driven; we don't have per-stage breakdown data yet to know what to parallelize within plan. Need C1 done first to demonstrate the pattern.

## Post-event development plan (May 8-21)

**Week 1 (May 8-14): impact-ordered.**

- **Day 1 (May 8):** C1 — per-substory worker pool. Highest-impact single change. Target: 60-90 min off `talk-45 STRONG` wall-clock. Ship as v0.4.0.
  - Approach: bash background jobs with `wait`; per-substory `claude -p` invocations parallelize. Stream output via per-substory log files; merge in finalize_run.
  - Testing: smoke on `ibd_phage_targeting` (re-run from substory_design); verify total wall-clock cuts from ~158 min to ~60 min for the per-substory segment.
  - Risk: rate limits at 3-5 concurrent Sonnet calls. May need to throttle to 2-3.

- **Day 2-3 (May 9-10):** C2 — state.json + Phase enum (paper-writer parity).
  - Replace single-purpose `.handoff.json` with full state machine.
  - Migrates substory_overflow gate too (the second TTY block we left in v0.3.6).
  - Ship as v0.4.1 (or roll into v0.4.0 if C1 is small enough — judge by Day 1 EOD).

- **Day 4 (May 11):** C3 + C4 — post-checker noise reduction + finalize_run no-op detection. Both small. Ship as v0.4.2.

- **Day 5-7 (May 12-14):** D1 + D2 — revise_slide caveat handling + citation_pool validator. Iterative prompt work; multiple cycles with Adam's project tests.

**Week 2 (May 15-21): cosmetic + atlas integration.**

- **C6** layout cosmetic fixes (#74-77).
- **C5** plan stage refactor (post-C1; we'll have parallelization patterns to copy).
- Cross-skill cleanup pass per the doc-consistency thread.

## Continuation philosophy

The rhythm that's been working for v0.3.5 → v0.3.8 is **single-ish-issue patches with explicit ship gates**:

- Each version addresses one identified failure mode (TTY block; deferred-to-NO; process-detail-bleed).
- Each ships with: source change + tests + smoke against real data + docs update + commit-message file.
- Each ship has an explicit go/no-go gate (don't tag if test suite drops; don't push if smoke fails).
- Live test on hub, observe, iterate.

This is producing measurable per-version improvements with no rollbacks. Continue this rhythm post-event. The temptation will be to bundle multiple Tier-C items into a single v0.4.0 — resist; the smaller versions are easier to bisect when something goes wrong.

## Decision points

- **End of Wed work session (2026-05-06 EOD):** if Adam's fresh-project hub run validates image-gen calibration, stop development. v0.3.8 is the floor.
- **Thursday morning pre-event:** participant runbook URL pinned to v0.3.8 (or v0.3.9 if Sequence B shipped).
- **Mon May 11:** start C1 (per-substory parallelization).
- **Mid-May:** all of Tier C landed.

## What's out of scope

- Cross-skill items (paper-writer's HUB_INSTALL.md, atlas's CONTRACT.md if a real consumer emerges) — those teams own their cycles.
- BERIL upstream changes — never push.
- Per-cohort event handouts — Adam owns.
