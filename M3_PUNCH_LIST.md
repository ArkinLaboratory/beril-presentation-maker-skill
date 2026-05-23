# M3 Punch List — Per-substory parallel composition

**Filed:** 2026-05-23. **Status (2026-05-23): M3 STRUCTURALLY COMPLETE.** Tiers A–E done
— the v0.4 path runs end-to-end on `ibd_phage_targeting` (phase0 reuse → deck_outline →
4 parallel composers → fused notes → reconcile → valid 27-slide deck). Tier E surfaced
patches E-1…E-7. The remaining render-quality debt — diagram containment, fixed-box text
overflow, Slide-13 headline — is **routed to M4** (Adam, 2026-05-23): it is one root
cause (fixed-size boxes vs variable composer content), an assembler/content concern, not
M3's blast radius. **Tier F closeout complete 2026-05-23 — M3 COMPLETE; awaiting Adam's
M3-closeout commit. Next milestone: M4 (M4a visual-QA + content discipline, then M4b
review cascade).**
**Milestone:** M3 of the v0.4 architectural pivot (`V0_4_ARCHITECTURE.md` §16 + §20).
**Predecessor:** M2 — M2-lite deck-outline call (shipped 2026-05-23; `M2_PUNCH_LIST.md`).
**Successor:** M4 — tiered review cascade.
**Design source:** `V0_4_ARCHITECTURE.md` §16 (M3), §20.3 (per-section composer brief), §20.4 (post-merge reconciliation), §20.8 (the M3-carried dependency); `M1_PUNCH_LIST.md` Tier F1; decisions D-033 (speaker-notes fusion), D-044 (advisory composer contract). Composer-brief prototype: `experiments/m2-outline-probe/` condition C.

## Status

| Tier | Scope | Status |
|---|---|---|
| A — `phase0_tooling` stage + v0.4 stage re-sequencing | orchestrator | ✅ shipped 2026-05-23 |
| B — parallel worker-pool + per-section composer brief | orchestrator | ✅ shipped 2026-05-23 |
| C — post-merge reconciliation check | Python tool | ✅ shipped 2026-05-23 |
| D — composer prompt: narrow + fuse speaker-notes + consume brief | prompt + Python | 🔶 code-complete 2026-05-23 — `slide_compose.v2.md` awaiting review |
| E — end-to-end v0.4 smoke on `ibd_phage_targeting` | live | ✅ structural gate passed 2026-05-23 — v0.4 path runs end-to-end; render debt → M4 |
| F — closeout | paperwork | ✅ done 2026-05-23 |

## Key finding — the v0.4 path does not run end-to-end today

M2-lite shipped `stage_deck_outline` and the `--architecture-pipeline v0_4` flag, but
**the v0.4 path is wired in an order that starves `deck_outline` of its inputs.** Current
dispatch (`presentation_maker.sh` lines 1937–1985, `should_run` ordinals line 1927):

```
plan → throughline → [deck_outline | substory_design] → curate_figures
     → citation_pool → cross_tenant → intro → slide_compose → …
```

`stage_deck_outline` (lines 858–870) reads `working/00_phase0/claim_inventory.tsv`,
`working/00_phase0/methods_provenance.md`, `CURATED_FIGURES`, `CITATION_POOL_PATH`, and
`working/cross_tenant_signal.md`. The two Phase-0 artifacts have **no producer stage at
all** (`phase0_reuse.py` is unwired — M1 Tier F1); `curated_figures` / `citation_pool` /
`cross_tenant_signal` are produced by stages that currently run **after** `deck_outline`.
`deck_outline.v1.md`'s escape hatches keep the run from crashing, but the call silently
degrades to roughly `substory_design`-equivalent behaviour — no grounded headline slots,
no scoped figures. M2's Tier D smoke sidestepped this by running `deck_outline` standalone
with the inputs hand-passed.

So M3's "`phase0_tooling` wiring" (the punch-list F1 framing) is not one new stage — it is
**a re-sequencing of the v0.4 pipeline** so that all four Phase-0 producers run before
`deck_outline`. That is Tier A and it is the milestone unblock: nothing downstream of
`deck_outline` is testably correct on the v0.4 path until Tier A lands.

## Scope

M3 makes the v0.4 path **run end-to-end and in parallel**: Phase-0 inputs materialise
before `deck_outline`; the N per-substory composers run concurrently against the shared
outline; speaker-notes drafting is fused into the composer call (D-033); a post-merge
checker flags residual cross-section conflicts (§20.4). The wall-clock win
(`V0_4_0_PUNCH_LIST.md` C1) is banked here.

**What M3 is NOT:** the tiered review cascade (M4), image-gen multi-provider + revise
invariance (M5), the A/B cut-over (M6). The `--architecture-pipeline v0_4` path stays
opt-in; the v0.3.x default is unchanged (additive discipline, as M1/M2).

**Cost discipline:** every LLM call records cost from its `--output-format json` / stream
envelope (`stream_progress.py` already writes `.metadata.json`). No `--max-cost-usd` cap in
any tier or runbook — `feedback_cost_record_dont_gate`.

## Open design questions — need Adam sign-off; each is tagged with the tier it gates

**DQ1 (gates Tier A) — where does `phase0_tooling` sit in the v0.4 order?**
`V0_4_ARCHITECTURE.md` §10.1 puts `phase0_tooling` *before* `throughline_pick`.
**Recommendation: cluster all four Phase-0 producers contiguously, after the throughline
gate, immediately before `deck_outline`:** `throughline → (gate) → phase0_tooling →
curate_figures → citation_pool → cross_tenant → deck_outline`. Rationale: `citation_pool`
and `cross_tenant` already need the approved throughline; one contiguous reorder is
lower-risk than scattering; Phase-0 spend ($0.50–$1.50) lands only on gate-approved runs.
The §10.1 ordering is immaterial to correctness — `phase0_reuse.py` depends only on the
project, not the throughline. Cost of the recommendation: none material.

**DQ2 (gates Tier B) — worker-pool: bash `&`/`wait` or Python `concurrent.futures`?**
`V0_4_ARCHITECTURE.md` §7.3 leaves this open. **Recommendation: bash `&`/`wait`, reusing
`invoke_claude_with_retry` verbatim.** That function (lines 595–655) already encodes the
load-bearing retry semantics — rc=2 (Write never invoked) and rc=4 (API transient →
exponential backoff). A Python pool would reimplement them. The real risk is not the
LLM-call machinery (which we reuse, not reinvent — `V0_4_0_PUNCH_LIST.md` C1's "fragile
bash pools" warning was about that machinery) but the concurrency plumbing under
`set -euo pipefail` (line 73): `wait "$pid"` returning non-zero must be caught
(`|| rc=$?`), and N workers' stderr interleaves. Mitigation: per-worker stderr → a file,
tail-on-failure. If Adam would rather isolate concurrency in Python, that is the fork.

**DQ3 (gates Tier D) — speaker-notes fusion + the cross-skill contract — RESOLVED 2026-05-23.**
D-033 + the §12 migration matrix retire `speaker_notes.v1.md` and have the composer emit
notes. **Decision: full fusion** — `slide_compose.v2.md` emits complete 200–400-word notes
per slide (the `speaker_notes.v1.md` 5-step scaffold); `stage_speaker_notes` is dropped from
the v0.4 path. **Verified this does not break beril-adversarial** (`adversarial_review.sh`
lines 322–354 / 416–422 + `adversarial_presentation.v3.md` lines 100–121 / 1945–1961, read
2026-05-23):
(1) the reviewer's *primary* speaker-notes source is the per-slide `speaker_notes` field in
`slide_spec.json` — its **required** input #1 — and the v0_4 merge still injects notes into
`slide_spec.json` from the fused fragment, so that field is populated exactly as today;
(2) `working/04_speaker_notes/` is an **optional** input — `adversarial_review.sh` requires
only throughline / substories / qa_anticipated (lines 348–354) and gates the notes dir on
`[[ -d ]]` (line 419); an absent dir yields a clean review, not an error. The reviewer
globs `04_speaker_notes/S*_notes.json` (prompt line 1961).
**Tier D therefore derives `working/04_speaker_notes/{sid}_notes.json`** (the
`parse_speaker_notes.py` `notes_by_position` shape) from the fused fragment — belt-and-
suspenders byte-parity so the reviewer sees zero change. The hard dependency is
`slide_spec.json`'s `speaker_notes` field, preserved regardless of the dir.

**DQ4 (scope) — Tier-2 detection-class calibration: M3 or M4?**
`V0_4_ARCHITECTURE.md` §16 assigns "empirical Tier-2 detection-class calibration" to
M3-start. The user's stated M3 scope omits it. **Recommendation: defer to M4.** Tier 2 is
M4's review cascade; calibrating detection classes for a cascade that does not exist yet is
premature, and §16's assignment predates the M2-lite reshape. If Adam wants the calibration
probe banked early, it is a standalone ~$2–4 experiment, not orchestrator work — it should
not block M3's parallelism.

---

## Tier A — `phase0_tooling` stage + v0.4 stage re-sequencing

Orchestrator-only. No prompt edits, no new LLM call beyond what `phase0_reuse.py` already
does on originate. This is the unblock (see Key finding).

**Status — SHIPPED 2026-05-23.** All four sub-items landed in `presentation_maker.sh`:
A1 `stage_phase0_tooling()` (invokes `phase0_reuse.py --artifact all`, reuse-or-originate,
fail-loud on non-zero exit); A2 the pipeline-conditional dispatch block (v0_4:
`phase0_tooling → curate_figures → citation_pool → cross_tenant → deck_outline`; v0_3
branch behaviour-identical to the prior code); A3 the v0.4 `should_run` ordinal map +
`phase0_tooling` added to the `--resume-from` valid list and a `validate_resume_prereqs`
case — **`state.py` verified NOT to enumerate phases (58 LOC, no phase enum), so no state
change was needed**; A4 `PHASE0_DIR` / `METHODS_PROVENANCE_PHASE0` / `CLAIM_INVENTORY_PHASE0`
added to `set_draft_paths()` + `working/00_phase0/` to `init_draft_layout()`, and
`stage_deck_outline`'s hand-rolled paths converged onto those vars + `CROSS_TENANT_MD`.
Validation: `bash -n` clean; full `tests/` suite **1014 passed, 1 skipped, 2 errors** —
identical to the M2 baseline (the 2 errors are the pre-existing stale-upload-path fixture;
the 1 skip is "beril-adversarial CLI not installed"). No regressions. Awaiting Adam's
commit (no git run from the sandbox).

**A1. New `stage_phase0_tooling()`.** Invokes `phase0_reuse.py` (M1 helper, 656 LOC) with
`--project-dir "$PROJECT_DIR" --talk-draft-dir "$OUTDIR" --artifact all`. Reuse-or-originate
is the default — do not pass `--force-originate`. The helper calls `DraftPaths.init_layout()`
(idempotent) so `working/00_phase0/` is created. Records reuse-vs-originate + cost into
`audit/phase0.jsonl` (already its behaviour). Pure-ish: $0 on reuse, ~$0.05–$0.10 on
originate (the `extract_claims.py` `claude -p` leg).

**A2. v0.4 dispatch order.** Per DQ1, when `ARCH_PIPELINE == v0_4` the post-gate sequence
becomes `phase0_tooling → curate_figures → citation_pool → cross_tenant → deck_outline →
audit_punchline_lengths → gate_substory_overflow → intro → …`. The v0_3 path is byte-unchanged.
Implement as a conditional dispatch branch, not by editing the shared linear block.

**A3. `should_run` ordinals + `--resume-from`.** `should_run` (line 1911) carries one
ordinal table (line 1927). v0.4 reorders `curate_figures` / `citation_pool` / `cross_tenant`
relative to `deck_outline`, so `should_run` needs a v0.4 ordinal map selected on
`$ARCH_PIPELINE`. Add `phase0_tooling` to the `--resume-from` valid list (lines 177–181)
and to both ordinal maps. Add a `phase0_tooling` phase constant to `state.py` if it
enumerates phases (no schema bump — D-038 puts the v0.4 schema bump at M6).

**A4. Layout-var check.** `draft_paths.shell_exports()` already emits `PHASE0_DIR` /
`METHODS_PROVENANCE_PHASE0` / `CLAIM_INVENTORY_PHASE0` (M1 C1.a). Confirm `stage_deck_outline`'s
hand-rolled `working/00_phase0/...` paths (lines 858–859) match those exports; converge on
the exported vars.

**AC for A:** `bash -n presentation_maker.sh` clean; full unit suite green; `phase0_tooling`
accepted by `--resume-from`; a code-walk of the v0_4 dispatch confirms the order in A2; the
v0_3 default path is unchanged. Full order is validated live at Tier E (no dry-run mode
exists; honest about that).

## Tier B — parallel worker-pool + per-section composer brief

Adds a **v0.4 branch** to `stage_slide_compose` (lines 1146–1197). **The v0_3 path stays
sequential + `PRIOR_SUBSTORY_OUTPUTS`-chained, byte-unchanged** — only the v0_4 branch
parallelises. (Parallelising v0_3 would regress it to the probe's condition B — cold-opening
composers, no transition coordination — because v0_3 has no shared outline; that violates
the v0.3.x-default-unchanged discipline.) Prompt-independent at this tier: the v0_4 branch
invokes the current `slide_compose.v1.md` (new brief vars injected but ignored until Tier D
introduces the v2 prompt); `stage_speaker_notes` is left intact for both paths here (retired
for v0_4 in Tier D).

**Status — SHIPPED 2026-05-23.** The worker-pool was extracted to a new sourceable bash
library — `tools/worker_pool.sh`, `wp_run_pool MAX LOGDIR LABEL RUNNER ID...` — rather than
left inline in the orchestrator, so the concurrency logic (the DQ2 risk) is unit-testable
in isolation. It is bash-3.2-compatible (indexed arrays + `${!arr[@]}`, no `wait -n`):
launches IDs in batches of MAX, captures each job's stdout+stderr to a per-job log, drains
each batch with `wait "$pid" || rc=$?`, returns non-zero if any job failed (failed logs
preserved + echoed; passing logs removed). Each worker subshell clears the inherited EXIT
trap so it cannot re-fire the orchestrator's finalize hook. `presentation_maker.sh` sources
it and splits `stage_slide_compose` into `_slide_compose_v0_3` (sequential +
`PRIOR_SUBSTORY_OUTPUTS` chaining — byte-identical behaviour to pre-M3) and
`_slide_compose_v0_4` (extracts the per-section brief once via `parse_deck_outline.py`,
sets `_M3_BRIEF_*` globals, runs `_compose_one_substory` through `wp_run_pool`; concurrency
bounded by `SLIDE_COMPOSE_MAX_PARALLEL`, default 5). Unlike v0_3, a v0_4 worker failure
fails the stage loud (`wp_run_pool || return 1`). Validation: `bash -n` clean on both
files; `tests/unit/test_worker_pool.py` — 9 tests (concurrency overlap, batching-cap
enforcement, rc collection, log preserve/remove, usage errors) all pass; full `tests/`
suite **1023 passed** (1014 + 9 new), 1 skipped, no regressions. Awaiting Adam's commit.

**B1. Per-section brief assembly (v0_4 branch).** For each substory, the orchestrator
extracts its boundaries from the enriched `02_substories.md` via `parse_deck_outline.py`
(`--field transitions_in|transitions_out|budgets|headline_slots|scoped_figures`, each
returns `S{N}\t<value>` lines) and the deck-level `--field register|arc|image_budget`.
Inject as explicit user-prompt vars (`TRANSITION_IN`, `TRANSITION_OUT`, `SECTION_BUDGET`,
`HEADLINE_SLOT`, `SCOPED_FIGURES`, `DECK_REGISTER`, `DECK_ARC`). The whole outline stays
available via `SUBSTORY_PATH` for arc context (§20.3 element 1). In the v0_4 branch, drop
the `PRIOR_SUBSTORY_OUTPUTS` chaining (lines 1188–1193) — the shared outline replaces it;
the probe (condition C) confirmed the outline carries the transition coordination without
prior fragments. The v0_3 branch keeps the chaining.

**B2. Worker-pool.** Launch each `invoke_claude_with_retry` (one per substory) as a
background job; capture per-worker stderr to `audit/stage_logs/slide_compose-$sid.worker.log`.
`wait` for all; collect each pid's rc with `wait "$pid" || rc=$?` (required under
`set -e`). Any non-zero rc → print that worker's log, return 1. Per-substory output paths
(`S{N}_slides.json`) and `stream_progress.py` log/metadata paths are already disjoint — no
write collision. Concurrency cap: N is typically 3–5; fire all at once for N ≤ 5, batch
above that (rc=4 backoff handles any rate-limit spillover regardless).

**AC for B:** a concurrency test (a stub `claude` that sleeps then writes the expected
file) confirms N workers overlap (wall-clock ≈ 1×, not N×) and that per-worker rc is
collected — one worker failing fails the stage while the others' fragments are preserved;
per-worker stderr is captured. `bash -n` clean; suite green.

## Tier C — post-merge reconciliation check

Independent of B and D; needs A only for the integrated Tier-E smoke. Deterministic Python.

**Status — SHIPPED 2026-05-23.** `tools/reconcile_deck.py` (stdlib-only, ~250 LOC incl.
docstring) detects three conflict classes against the merged `slide_spec.json`:
`duplicate_figure` (a reused asset — `content.figure` or `content.supporting_graphic` —
on >1 slide; `concept_illustration.image_path` is excluded, since AI images are
slide-unique and the `{TBD}` placeholder would otherwise read as a deck-wide duplicate),
`duplicate_headline` (the same `big_number` `content.headline` value on >1 slide), and
`image_budget` (count of `concept_illustration` slides over the outline's `**Image
budget:**` integer cap). Two grounding decisions vs the C1 sketch: (1) the headline check
keys on the **headline value**, not a `claim_id` — the merged `slide_spec.json` carries no
`claim_id` on slides (verified against `slide_spec.py`); (2) the checker is wired to run
**unconditionally** for both pipelines in `stage_merge_and_assemble` (after
`check_no_artifact_refs.py`), matching the existing advisory post-checkers — the
image-budget class simply no-ops on a v0.3.x draft (no `Image budget` line). Advisory:
always exits 0; writes `audit/deck_reconciliation.{md,json}`. Validation: `bash -n` clean;
`tests/unit/test_reconcile_deck.py` — 18 tests (each conflict class, the cap parser, the
`reconcile()` integration, main()'s always-0 contract incl. missing-slide_spec no-op) all
pass; full `tests/` suite **1041 passed** (1023 + 18 new), no regressions. Awaiting Adam's
commit.

**C1. `tools/reconcile_deck.py`** (~40–60 LOC + ~10 tests). Reads the merged
`slide_spec.json` + the outline's `image_budget` (via `parse_deck_outline.py`). Flags the
three §20.4 conflict classes: (a) the same `figure:` path used on more than one slide;
(b) more than one `big_number` headline slide, or one `claim_id` headlining twice;
(c) total image-gen slide count over the deck `image_budget`. Advisory only (rc=0, mirrors
`check_quantitative_grounding.py` / `check_no_artifact_refs.py`); writes
`audit/deck_reconciliation.{md,json}`.

**C2. Wire into `stage_merge_and_assemble`** after the existing post-checkers (after
`check_no_artifact_refs.py`, ~line 1740).

**AC for C:** on a fixture `slide_spec.json` carrying a duplicated figure / two
`big_number` headlines / an over-budget image count, `reconcile_deck.py` flags each; a
clean spec produces zero flags; rc=0 always; the merge stage calls it; suite green.

## Tier D — composer prompt: narrow + fuse speaker-notes + consume the brief

Prompt edits deferred to here per `feedback_punch_list_release_pattern` — prompt smokes are
expensive; wiring (A/B/C) is stabilised first. Couples a prompt change with its consumer
(`merge_compose_fragments.py`) — pinned by a contract test (the intra-skill drift lesson).

**Status — CODE-COMPLETE 2026-05-23; `slide_compose.v2.md` awaiting Adam's review before
Tier E.** What landed: `slide_compose.v2.md` (1249 lines — built by `cp v1 v2` then a
targeted delta so the ~900 lines of live-failure-earned discipline stay byte-identical;
adds the advisory deck-outline brief section, fuses speaker-notes authoring as a
200–400-word `speaker_notes` string per slide, emits `compose-fragment.v2`, drops
`PRIOR_SUBSTORY_OUTPUTS` + the seed discipline; PA-15–PA-18 + self-review items 16–17 are
the new notes checks). `merge_compose_fragments.py` is dual-mode — `strip_orchestrator_metadata`
already keeps an inline `speaker_notes`, so a v2 fragment's notes survive into
`slide_spec.json` untouched; the new `derive_speaker_notes_files()` writes
`working/04_speaker_notes/{sid}_notes.json` in the `parse_speaker_notes.py`
`notes_by_position` shape (the beril-adversarial contract, DQ3). `presentation_maker.sh`:
`_compose_one_substory` repointed v1→v2, `slide_compose.v2.md` added to the startup
prompt-existence check, `stage_speaker_notes` retired on the v0_4 dispatch path (v0_3
keeps it). **`slide_spec.py` needed no change** — it already accepts an optional
slide-level `speaker_notes` string; `compose-fragment.v2` is a prompt↔merge contract, not
a validated schema file, so it is pinned by the test, not a schema doc. Reframe vs the D1
sketch below: v2 is **not a narrowing** — under D-044 the composer still owns layout /
headline / figure selection, so v2 is v1 + the brief + fused notes ≈ 1249 lines (bigger
than v1). Validation: `bash -n` clean; `tests/unit/test_merge_fused_notes.py` — 8 contract
tests (inline-notes survival, `derive_speaker_notes_files` v2-writes / v1-noop / dir-None,
loader round-trip, empty-notes skip) all pass; full `tests/` suite **1049 passed**
(1041 + 8 new), no regressions. **The notes-quality off-ramp (DQ3):** if Tier E shows
fused notes underperform a dedicated pass, un-fuse — `speaker_notes` returns as its own
stage parallelized through `wp_run_pool`. The Tier-E AC carries an explicit notes-quality
check.

**D1. New `slide_compose.v2.md` — the narrowed composer (advisory, D-044).** A versioned
prompt bump, **not** an in-place edit of v1: `slide_compose.v1.md` stays as the v0_3
composer (M6 archives v1 at cut-over, exactly as it will `substory_design.v1.md`). This
deviates from the §12 migration-matrix "KEPT but NARROWED" wording — that line predates the
M1/M2 dual-pipeline additive pattern, where the v0_4 variant is a sibling file, not an
in-place mutation. v2's input contract adds the per-section brief vars (B1); v2 honours —
*advisorily* — its section's `TRANSITION_IN/OUT`, `SECTION_BUDGET`, `HEADLINE_SLOT`,
`SCOPED_FIGURES` and the deck `REGISTER`/`ARC`, while free-handing layout, bullet content,
and punchline wording (§7.1 / §20.2). **No `architecture_conflict` halt** — D-044 dropped
the rigid contract. The v0_4 composer branch (Tier B) is repointed from v1 to v2.

**D2. Fuse speaker-notes into v2 (D-033).** `slide_compose.v2.md` emits full per-slide
speaker notes (200–400 words, the `speaker_notes.v1.md` 5-step scaffold) inside the
compose-fragment, replacing the `speaker_notes_seed`. `speaker_notes.v1.md` is not invoked
on the v0.4 path (left in-tree for the v0_3 path until M6 archives v0.3.x prompts, as M2
did with `substory_design.v1.md`).

**D3. `compose-fragment.v1` schema + merge.** Add the per-slide `speaker_notes` field;
update `slide_spec.schema.json` / `slide_spec.py` accepted shapes. `merge_compose_fragments.py`
goes dual-mode: v0_4 fragments carry notes inline; v0_3 fragments keep the separate
`working/04_speaker_notes/` dir. For v0_4, merge injects the embedded notes into
`slide_spec.json`'s per-slide `speaker_notes` field (the reviewer's primary, required
source) **and derives `working/04_speaker_notes/{sid}_notes.json`** — the
`parse_speaker_notes.py` `notes_by_position` JSON shape, which is what beril-adversarial
globs (`S*_notes.json`, `adversarial_presentation.v3.md` line 1961) — from the fused
fragment. The `.md` intermediate is not reproduced (no consumer reads it). (DQ3 /
`feedback_cross_skill_contract_drift`.)

**D4. Retire `stage_speaker_notes` on the v0.4 path.** v0_3 keeps it; v0_4 skips it (notes
arrive fused). Branch on `$ARCH_PIPELINE` in the dispatch, as the clustering slot already does.

**D5. Contract test.** Pin the v2 fused-fragment shape ↔ `merge_compose_fragments.py`
parser — if `slide_compose.v2.md` changes the notes field, the test fails until the merge
consumer is updated (the intra-skill drift lesson — `feedback_cross_skill_contract_drift`'s
fourth strike).

**AC for D:** `slide_compose.v2.md` emits `compose-fragment.v1` with embedded full speaker
notes + advisory brief-honouring instructions, no halt path; merge reads embedded notes for
v0_4 and derives `working/04_speaker_notes/`; v0_3's `slide_compose.v1.md` + separate-notes
flow untouched; contract test green; suite green. **Reviewed by Adam before any Tier-E token spend** (mirrors M2
Tier A — no live run until the prompt is signed off).

## Tier E — end-to-end v0.4 smoke on `ibd_phage_targeting`

Propose a runbook first; surface the commands as copy-paste blocks in chat for Adam to run
on his Mac (`feedback_sandbox_bash_vs_intermediate_checks` — explicit `.venv/bin/python`
form; Adam runs all git). Full v0.4 path: `plan → throughline → phase0_tooling →
curate_figures → citation_pool → cross_tenant → deck_outline → intro →
slide_compose (parallel) → qa_prep → merge → reconcile`.

**AC for E:** the v0.4 path runs end-to-end and produces a valid `slide_spec.json` + `pptx`;
`deck_outline` consumes real Phase-0 inputs (grounded headline slots, scoped figures); the
parallel composers measurably overlap (stage wall-clock < sum of per-substory times);
speaker notes are present in the deck and in `working/04_speaker_notes/`; `reconcile_deck.py`
runs and writes its audit; cost recorded from envelopes; beril-adversarial
`--type presentation` resolves `narrative/02_substories.md` + `working/04_speaker_notes/`
against the v0_4 draft. Expect 1–3 patches in this phase
(`feedback_punch_list_release_pattern`).

**Notes-quality gate (DQ3 — "make sure we check").** Tier E explicitly assesses the fused
speaker notes: Adam reads a sample against the v2 notes anti-patterns (PA-15 marketing
voice, PA-16 caveat erosion, PA-17 number paraphrase, PA-18 teleprompter) and confirms
every ⚠/✗ caveat surfaced. The fusion bet (D-033) was made under the M0 "narrowed
composer" premise that M2-lite did not deliver — so if fused notes show a clear quality
drop vs a dedicated `speaker_notes` pass, the **un-fuse off-ramp** fires: `speaker_notes`
returns as its own stage, parallelized through `wp_run_pool` (the worker-pool already
supports it). A documented, low-regret reversal — not a Tier-E blocker.

### Runbook (proposed 2026-05-23)

Preconditions: `beril-presentation-maker` pipx-installed (the orchestrator reads its
console-script shebang to find a Python with python-pptx / Pillow / nbformat);
`ibd_phage_targeting` present under the BERIL fork with `papers/draft_2/` (phase0 +
citation reuse make the run cheap); authenticated `claude` CLI. Runs on Adam's Mac —
live LLM spend.

Step 1 — the v0_4 pipeline (talk-30, est. ~$5–9 paper-exists; no `--max-cost-usd`):

    cd ~/Documents/Claude/Projects/research-coscientist-dev/spike/beril-presentation-maker-skill-draft
    bash src/beril_presentation_maker/skill/tools/presentation_maker.sh \
      ibd_phage_targeting \
      --beril-root ~/Documents/Claude/Projects/research-coscientist-dev/spike/beril-extended \
      --architecture-pipeline v0_4 --mode talk-30 --tier STRONG \
      --auto-advance --no-images --no-adversarial \
      2>&1 | tee /tmp/m3-tier-e-smoke.log

`--no-images` (image-gen is M5, orthogonal) and `--no-adversarial` (the adversarial
cross-skill check is Step 2) keep the smoke on the M3 path.

Step 2 — cross-skill check (DRAFT_DIR from Step 1's final banner):

    beril-adversarial review --type presentation <DRAFT_DIR>

Checks: (1) stage banners appear in v0_4 order — phase0_tooling → curate_figures →
citation_pool → cross_tenant → deck_outline → intro → slide_compose ("v0.4 parallel
composition") → qa_prep → `[skip] speaker_notes (v0.4 — fused…)` → merge → deck
reconciliation; (2) `working/00_phase0/{claim_inventory.tsv,methods_provenance.md}` exist;
(3) the `[worker-pool]` lines show N concurrent composers, slide_compose wall-clock < sum
of per-composer times; (4) every content slide in `working/slide_spec.json` carries a
`speaker_notes` string and `working/04_speaker_notes/{sid}_notes.json` were derived;
(5) `audit/deck_reconciliation.{md,json}` written; (6) `deliverable/draft.pptx` produced;
(7) Step 2 yields a real review, not "required input missing"; (8) the notes-quality
gate above.

### Patch log (E-phase)

- **E-1 (2026-05-23) — `phase0_reuse.py` import context.** The first v0_4 run failed at
  `phase0_tooling`: `phase0_reuse.py` used package-style imports
  (`from beril_presentation_maker.skill.tools import extract_claims, …`) — the lone
  orchestrator-run tool to do so. That resolves under `PYTHONPATH=src` (the test env —
  which is why the suite was green) but not when the orchestrator runs the file as a
  script under the pipx venv, where `beril_presentation_maker` is not an importable
  package. Fixed: try the package import, fall back to a `__file__`-resolved bare sibling
  import (the `merge_compose_fragments.py` pattern). Both contexts verified in the sandbox;
  full suite still **1049 passed**. Re-run Step 1.
- **E-2 (2026-05-23) — `slide_compose` parallel-stage telemetry.** The first full v0_4 run
  produced a valid 27-slide deck ($9.74 all-in, talk-30; phase0/citation reused), but the
  `slide_compose` stage printed no cost/timing banner — each parallel composer's
  `stream_progress` output goes to its worker log, which `wp_run_pool` removes on success.
  The data was captured (per-composer `.metadata.json` sidecars persist) but invisible on
  the console — and the slide_compose wall-clock IS the M3 primary metric. Fixed:
  `_slide_compose_v0_4` times the pool and prints a banner — per-composer cost/time read
  from the sidecars + stage wall-clock vs cumulative LLM time (the parallelism win, side by
  side). Telemetry-only, never fails the stage. `bash -n` clean; suite **1049 passed**.
- **E-3 (2026-05-23) — `data_figure` title discipline (`slide_compose.v2.md`).** Smoke
  deck Slide 13 carried a compound section-synthesis headline ("bile-acid dehydroxylation,
  multi-omics synthesis, and partial serology corroboration…") on a `data_figure` slide
  whose figure shows only the serology heatmap — a headline/body mismatch. The v2
  `data_figure` rule already said "title states what the figure shows" but wasn't strong
  enough. Strengthened: it now explicitly forbids a section-summary / compound-claim title
  on a `data_figure` (those belong on a `section_divider` / `big_idea`), incl. a
  substory's closing `data_figure` slide. Prompt-only; takes effect on the next
  `slide_compose` run.
- **E-4 (2026-05-23) — `qa_anticipated` render hotfix (`assemble_pptx.py`).** Smoke deck
  slides 23–25 (the Q&A slides) rendered with the question overflowing the title band and
  the answer tiny over a half-empty body. Root cause in `_fill_qa_anticipated`: the
  question (an audience question, naturally long) went into the 1.3in title with no
  autofit; the answer used a FIXED 60% fontScale (v0.2.2, sized for a worst-case
  ~2000-char answer) applied unconditionally, so moderate answers rendered tiny. Fixed:
  title autofit on the question (the `big_idea` long-claim treatment) + body fontScale now
  **adaptive by content length** (≤700 chars → 100%, scaling to the 60% floor). General —
  a function of length, not deck-specific. A pre-existing v0.3.x assembler bug surfaced by
  the M3 smoke (assembly is outside M3's blast radius), fixed here at Adam's direction.
  Suite **1049 passed**; focused check confirms short→100% / long→60% + title autofit.
  Visual confirmation needs a re-render.
- **E-5 (2026-05-23) — `qa_anticipated`: `answer_detail` off the slide face.** The E-4
  re-render showed slides 23–25 still broken: E-4's adaptive autofit was necessary but
  insufficient — each Q&A slide carried ~3.8K characters, ~2.2K of it `answer_detail`,
  which `_fill_qa_anticipated` rendered on the slide *face*. But `answer_detail` is the
  *speaker reference* by qa_prep's own contract (qa_prep stage prompt, line 1455:
  "answer_summary (slide body) + answer_detail (speaker reference)") — rendering it on the
  face was renderer/contract drift. Fixed: the slide face now carries `answer_summary` +
  the evidence pointer only (~1.5K chars → 80% autofit, legible); `answer_detail` is routed
  to the slide's notes pane via `_set_speaker_notes`. Companion robustness fix: the
  assembly loop's `if "speaker_notes" in slide_data` → `if slide_data.get("speaker_notes")`
  so a present-but-empty value can't clobber handler-set notes. Suite **1049 passed**;
  focused check confirms face 3.8K→1.5K, `answer_detail` off the face + in the notes pane.
  Residual: `answer_summary` is itself ~1.1K chars — a `qa_prep.v1.md` length cap would
  make the slides genuinely tight (recommended follow-on, not done here — v0.3.x prompt,
  needs a qa_prep re-run to verify).
- **E-6 (2026-05-23) — assembler footer-safety + containment geometry fix.** A full
  visual pass on the smoke deck (Adam, slides 6–21) found ~8 slides with gray secondary
  text rendered into the bottom logo strip. Root cause: the slide is 10.0×5.62in, the
  DOE/KBase logo strip occupies y≈5.00–5.55, and the band constants + ~6 layout fillers in
  `assemble_pptx.py` placed secondary text at y≈5.0–5.5 — inside the strip. One coherent
  fix: a documented `FOOTER_SAFE_BOTTOM = 4.92`; `CAPTION_BAND`/`CITATION_BAND`/
  `AI_DISCLOSURE_BAND` moved above it; big_number's title placeholder shrunk (it was
  3.59in tall, leaving only 0.40in for three sub-elements) so subtitle/sub_pointer/
  source_footer fit above 4.92; methods_summary / claim_evidence(no-figure) /
  qa_anticipated body placeholders trimmed clear of the strip (claim_evidence's no-figure
  branch also gained the autofit it was missing — slide 8); workflow_diagram region
  shrunk + step-caption/tool-footer raised; data_table bounded + caption/footnote moved
  to fixed safe y's (the caption was placed off an *underestimated* table height —
  python-pptx `add_table` height is a hint, rows grow to content). `diagram_render.py`:
  node labels gained `word_wrap` + shrink-to-fit (slides 6/10/19 node-text overrun).
  Also `revise_loop.py`: `f.get("slide_id","n/a")` → `... or "n/a"` (the present-but-null
  `.get` bug — rendered "slide None"; flagged by the adversarial team). Validation: full
  suite **1049 passed**; a synthetic 7-layout deck assembles clean and every text/table
  shape ends ≤4.95in. Visual confirmation needs Adam's re-render. Deferred: the
  workflow_diagram inter-box transition-label position (behind boxes on 10/19) — needs a
  render to position precisely; next round. Note: E-6 is a pre-existing v0.3.x assembler
  defect surfaced by the M3 smoke — not M3's blast radius — fixed here at Adam's direction.
- **E-7 (2026-05-23) — regression fix: zero-width placeholders.** E-6's four placeholder
  resizes set only `.top`/`.height`. On a placeholder that *inherits* its geometry from
  the layout, python-pptx then writes a slide-level `xfrm` with `.left`/`.width` left at
  0 — collapsing the body to a zero-width column (text rendered one character per line;
  the big number stacked vertically at the left edge). Caught on Adam's `pngs3`
  re-render. Fixed: all four resizes (big_number title; methods_summary /
  claim_evidence-no-figure / qa_anticipated body) now set **all four** dims — `.left`,
  `.top`, `.width`, `.height`. The E-6 geometry check measured only the bottom edge, so
  it passed a zero-width box; the check now also asserts width. Suite **1049 passed**;
  the widened scan is all-clear (text shapes full-width + above the footer).

## Tier F — closeout

`V0_4_ARCHITECTURE.md` §16 M3 → SHIPPED + §20.8 dependency marked resolved;
`M1_PUNCH_LIST.md` Tier F1 → closed; `LAYOUT.md` §1 (`reconcile_deck.py` under `tools/`,
`slide_compose.v2.md` under `prompts/`); this punch list's status table; `DECISIONS.md`
(DQ1–DQ4 resolutions land as D-046+);
auto-memory `project_presentation_maker_v0_4_m3.md` + `MEMORY.md` index line.

## Dep edges

```
A ──┬──> B ──> D ──> E ──> F
    └──> C ───────────────> E
```

A unblocks B and C. B → D (D's prompt consumes the brief vars B injects; D retires the
`stage_speaker_notes` that B leaves intact). C is independent after A — `reconcile_deck.py`
is unit-testable on a fixture; only its integrated smoke needs the v0.4 path. D → E, C → E.
F ships after E's gate.

## Smoke gates

- **A gate:** `bash -n` clean, suite green, v0.4 dispatch order correct by code-walk + a
  `--resume-from` smoke. Failure stops B/C.
- **B gate:** the concurrency test — N workers overlap, per-worker rc collected, one
  failure fails the stage cleanly.
- **C gate:** `reconcile_deck.py` flags all three conflict classes on a fixture; clean spec
  stays clean.
- **D gate:** contract test green; Adam sign-off on the prompt before E.
- **E gate:** v0.4 end-to-end produces a valid deck on `ibd_phage_targeting`. Failure stops
  Tier F until the gate passes.

## What M3 does NOT do (carried into M4+)

- The tiered review cascade — Tier 1 deterministic / Tier 2 Haiku / Tier 3 canonical
  adversarial (M4).
- Tier-2 detection-class calibration (M4 per DQ4, unless Adam pulls it forward).
- Image-gen multi-provider (AI Studio) + revise-verb semantic-invariance post-check (M5).
- State-schema v0.3 → v0.4 migration + the A/B cut-over decision (M6).

## Estimated effort

| Tier | Estimate |
|---|---|
| A — `phase0_tooling` + re-sequencing | 4–6 h |
| B — worker-pool + composer brief | 6–9 h (concurrency under `set -e` is the fragile bit) |
| C — `reconcile_deck.py` | 2–3 h |
| D — prompt narrow + fuse + merge | 5–8 h (two coupled prompt edits) |
| E — live smoke | 3–5 h (+ 1–3 patches) |
| F — closeout | 1–2 h |

Total ~21–33 h over 3–5 working days, assuming no smoke-gate failure forcing rework.
Punch-list expected to absorb 1–3 patches in the Tier-E phase.

## First action

Adam resolves DQ1–DQ4. Then Tier A: author `stage_phase0_tooling`, add the v0.4 dispatch
branch + the v0.4 `should_run` ordinal map, extend `--resume-from`. Tier A is the unblock —
nothing on the v0.4 path is testably correct until it lands.
