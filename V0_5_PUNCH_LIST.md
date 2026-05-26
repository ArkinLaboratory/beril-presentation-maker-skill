# V0.5 Punch List — Content-discipline milestone

**Status:** drafted 2026-05-25 (post-M6). Authoritative scope opening:
`DECISIONS.md` D-070. Framing per Adam's M6 Tier D read 2026-05-25:
*"Overall arc and stories are obscure. Substory division is OK but
could be sharper, but in no case is the question → clear analysis →
results → conclusions clear. We get walls of text poisoned by
specialist reference to, for example, specific notebooks rather than
a general analytical discussion. The stories don't build and/or
aren't brought together to make an overall point."*

**Posture.** v0.5 is a **content-discipline** milestone, NOT another
architectural pivot. Sequential vs parallel-compose dispatch (v0.3
default; v0.4 opt-in via `--architecture-pipeline v0_4`) is settled
per D-069. v0.5 rewrites the per-substory + cross-substory CONTRACTS
the dispatch operates over. Both pipelines feed identical v0.5
prompts; v0.5's wins should appear regardless of which dispatch the
user runs.

**Scope (2 workstreams ship per Adam 2026-05-25; the other 2 carry to v0.6):**

Per Adam: ship the **highest-leverage two** first; assess whether the
other two resolve as side-effects or need separate work.

1. **Substory Q/A/R/C contract** (load-bearing; the analytical-arc
   weakness Adam named) → `substory_design.v3.md` +
   `tools/check_substory_shape.py`.
2. **Register-discipline validator** (load-bearing; the "walls of
   text poisoned by specialist reference" weakness) →
   `tools/check_register_discipline.py` + new heuristic per Tier A.1.

Deferred to v0.6 (or fold-in if the above two subsume the symptom):
- **Cross-substory throughline-bridge pass** (`prompts/throughline_bridge.v1.md`
  + `tools/bridge_substories.py`).
- **Figure-utilization contract** (`tools/check_figure_provenance.py`).

**Cut-over rule:** same as M6 per D-065 + D-066 — v0.5 must dominate
v0.4 (or v0.3 default; both A/B targets) on ≥4 of 6 metrics on the
target project + ≥40% wall-clock reduction on at least one project.
Adam-veto (D-066) is final. Reuses `tools/m6_score.py` unchanged
(provider-agnostic; runs against any 2-project A/B audit dir pair).

**Prompt-versioning posture (per Adam 2026-05-25):** clean break to
**v3 prompt set**, NOT in-place evolution of v2. Mirrors how v0.3→v0.4
introduced v1/v2 prompts in parallel. v0.5 ships:
- `substory_design.v3.md` (new — Q/A/R/C contract).
- `slide_compose.v3.md` (new — register-discipline-aware).
- (other prompts unchanged at v1/v2 unless touched by Tier-X live
  discovery).

`--prompts-version {v1,v2,v3}` flag added to orchestrator alongside
the existing `--architecture-pipeline {v0_3,v0_4}` flag (independent
axes). Default at v0.5 ship: prompts=v3 (the new default) +
architecture=v0_3 (per D-069 unchanged). Operators can mix-and-match
for ongoing benchmarking.

## Per-tier status

| Tier | Scope | Status |
|---|---|---|
| 0 — orientation read + v3 prompt design DQs sign-off | research + DQs | ✅ committed 2026-05-25 (read substory_design.v1.md + slide_compose.v1/v2.md end-to-end; verified contract has Punchline + Critical analyses + Cluster rationale but ZERO question/conclusion/handoff fields; audited 4 M6 drafts (ibd v0.3/v0.4 + fdm v0.3/v0.4) confirmed all 4 had 0 question fields, 0 conclusion fields, 0 handoff fields; inventoried register-discipline violations with field-class split — NB-refs in audience-facing fields: ibd-v0.3=8, ibd-v0.4=18, fdm-v0.3=9, fdm-v0.4=1 — wildly project+pipeline dependent; D-071 (Q/A/R/C slide-shape mapping per DQ1 (b) middle ground), D-072 (field-class-aware register heuristic + per-project allowlist + soft-warning per DQ2), D-073 (substory-shape via cascade Tier-2 substory_arc findings per DQ3 (c)), D-074 (--prompts-version default v2 until A/B passes per DQ4 (b)) all drafted) |
| A — `substory_design.v3.md` (Q/A/R/C contract) + `slide_compose.v3.md` (register-aware) + `--prompts-version` flag | prompts + orchestrator | ⬜ not started |
| A.1 — `tools/check_register_discipline.py` heuristic + design | new tool + tests | ✅ ready to commit 2026-05-25 (new `tools/check_register_discipline.py` ~330 lines: 7 patterns per D-072 (notebook_id, notebook_filename, section_marker, notebook_cell, figure_filename, schema_version, tool_version); field-class classifier (operator/audience/other) with `OPERATOR_FIELDS` + `AUDIENCE_FIELDS` frozensets covering v0.5 D-071 Q-arc fields; per-project allowlist loader from `references/register_allowlist.md` with comment+blank handling + substring match semantics; `scan_slide` walker yields (field_name, text) via immediate-parent-key traversal — handles `bullets[]`, `diagram.nodes[].label` etc.; `check_register_discipline` aggregates across slides + emits `RegisterReport` (schema_version `register-discipline.v1`); standalone CLI with text + JSON formats. `validate_p11_register_discipline` thin wrapper in `validate_presentation.py` (sibling-module load matches M5a Tier C P3 pattern); P11 wired into `validate_presentation()` with project_dir derived by walking up draft_dir; live verification: 59 soft-warnings on ibd v0.4 draft_5 (matches Tier-0 audit signal). 38 new tests (pattern matches, field-class classifier, severity rules, allowlist mechanism + substring matching, scan_slide orchestration, text report shape, CLI happy + sad paths) + 1 fixture update in test_validate_presentation.py (P-validator count 10→11); suite 1357 passed) |
| B — `tools/check_substory_shape.py` post-composer Q/A/R/C check | new tool + tests | ✅ ready to commit 2026-05-25 (new `tools/check_substory_shape.py` ~440 lines: `extract_substory_fields` (parses v1/v2-shape **Punchline:** + v3 **Question:** + **Conclusion for next substory:** with alt-name acceptance "Scientific question" / "Hands off to" / "Next substory"); `inventory_slides_per_substory` (maps substory_id → [(slide_id, layout)]); `check_substory` per-substory validator with 8 finding kinds (missing_question / missing_conclusion / question_too_long / conclusion_too_long / missing_q_slide / missing_r_slide / missing_c_slide / substory_has_no_slides) — last-substory exempt from conclusion req; word caps 25 per D-071; Q_SLIDE_LAYOUTS = {section_divider, big_idea}, R_SLIDE_LAYOUTS = {data_figure, data_table, big_number, two_column_compare, workflow_diagram}, C_SLIDE_LAYOUTS = {claim_evidence, big_idea}; big_idea legitimately serves as both Q+C if used at substory open + close. `check_substory_shape` orchestration with defensive missing-input handling; standalone CLI writes `audit/substory_shape.json` (`substory-shape.v1` schema) by default. **Cascade integration**: new `_read_substory_shape` in `review_cascade.py` (read-if-present per visual_qa/DQ2 pattern; per-finding `kind=substory_arc:<sub-kind>` mapping; P0 demoted to P1 defensively per D-073); `run_tier1` gains 6th source; old `test_tier1_aggregates_all_five_sources` renamed + updated. Live verification on ibd v0.4 (draft_5): 12 findings (5 missing_question, 4 missing_conclusion, 3 missing_c_slide — S3/S4/S5 close on big_number/data_figure not claim_evidence/big_idea, a real M6-Adam-read concern surfaced empirically). 28 new tests (24 substory-shape + 4 cascade-reader); suite 1385 passed) |
| C — A/B run on `ibd_phage_targeting` (v0.5 vs v0.4-experimental AND vs v0.3 default) | live (~$30) | ⬜ not started |
| D — A/B run on `functional_dark_matter` (sanity) | live (~$25) | ⬜ not started |
| E — Adam reads decks + scores metric 5 + veto | review + DECISION | ⬜ not started |
| F — SPEC + DECISIONS + LAYOUT + RELEASE_NOTES + V0_4_ARCHITECTURE update | docs | ⬜ not started |
| G — closeout (V0_5 SHIPPED block; auto-memory; v0.5.0 / v0.5.0-experimental tag per Tier-E veto) | paperwork + tag | ⬜ not started |

## DQs to resolve at Tier 0 sign-off

### DQ1: Q/A/R/C contract shape

**Question:** What does "each substory must follow Q → A → R → C"
mean operationally in `substory_design.v3.md`?

**Options:**
- **(a) Substory-level fields**: each substory has explicit
  `question:` / `analysis:` / `results:` / `conclusions:` fields.
  The slide map is derived from filling those (Q on the
  section_divider; A on the methods slide; R on data slides; C on
  the closing slide). **Most opinionated.**
- **(b) Slide-shape mapping**: each substory has fixed slot
  positions for Q-slide / A-slide(s) / R-slide(s) / C-slide. The
  composer picks which slide layouts go in each slot from the
  existing 16-layout vocabulary. **Middle ground.**
- **(c) Soft framing in prompt**: substory_design.v3.md prompt
  asks the LLM to organize the slide map as a Q→A→R→C arc but
  doesn't enforce structural fields. Validator checks for it
  post-hoc. **Least opinionated; matches D-053 / soft-warning
  posture.**

**My read:** (b) for v0.5 ship — middle ground gives enforcement
teeth without forcing prompt-engineering of all 16 layouts. (c) is
a v0.5.1 fallback if (b) is too rigid. (a) is over-engineered.

**Resolves at Tier 0.**

### DQ2: register-discipline heuristic

**Question:** What counts as "specialist reference" in
audience-facing prose?

**Candidates** (from Adam's M6 read + adversarial findings):

| Pattern | Regex sketch | Example | Verdict |
|---|---|---|---|
| Notebook IDs | `\bNB\d+\b` | "NB10 §3" | clear flag |
| REPORT section markers | `§Finding \d+`, `§Step \d+` | "§Finding 7 hedges" | clear flag |
| Figure file names | `\bF\d{2,3}_\w+\.\w{3,4}\b` | "F03_recovery_by_method.png" | clear flag |
| Citation pool keys (in prose) | `\[[A-Za-z]+\d{4}\w*\]` outside of bullet end | "[Price2022] shows" → audience expects "Price (2022) shows" | clear flag |
| Tool names (Bakta, GapMind, RAST) | named whitelist | "Bakta v1.12.0 reclassified" | **NUANCED** — sometimes audience needs it; sometimes "annotation tool" suffices |
| Schema versions | `v\d+\.\d+(\.\d+)?` in prose | "slide_spec.v1" → never; "Gemini 3.1" → fine | **NUANCED** |
| Per-cell internal refs | `cell \d+`, `chunk \d+` | rare; flag if seen | clear flag |

**Open Qs:**
- Where does the validator live? Per-slide post-composer (matches
  M4a Tier B pattern), or pre-composer slide-spec validation
  (catches at validate_slide_spec time)?
- Severity? **soft-warning** matches D-053; **error** would force
  revise_loop iteration. **My read: soft-warning to start;
  promote to error if v0.5 A/B shows the soft warning isn't
  enough.**
- Allowlist mechanism for legitimate tool/version names? Per-slide
  prose hint? Per-talk allowlist file? Per-project allowlist in
  `slide_spec.json`?

**Resolves at Tier 0; implementation lands at Tier A.1.**

### DQ3: substory-shape post-composer check enforcement

**Question:** What happens when `check_substory_shape.py` finds a
substory missing Q/A/R/C structure?

**Options:**
- **(a) Hard error** (fail merge/assemble) → triggers revise_loop.
  Heaviest; risks pipeline halts.
- **(b) Soft-warning** (advisory) → assembler warns; deck still
  renders. Matches M4a Tier B / D-053 pattern.
- **(c) Tier-2 cascade finding** (review_cascade adds it as a P1
  with `kind=substory_arc`) → operator sees it in the cascade
  output; revise_loop may pick it up. Most graceful.

**My read:** (c) for v0.5 ship — leverages the cascade
infrastructure M4b shipped; matches the cascade's narrative-light
posture; revise_loop can act on it without halting the pipeline.

**Resolves at Tier 0; implementation lands at Tier B.**

### DQ4: `--prompts-version` flag default after v0.5 ships

**Question:** Once v0.5 ships, what's the default value of
`--prompts-version`?

**Options:**
- **(a) v3** — new default; v1/v2 remain available via flag.
  Matches "v0.5 IS the new contract" framing.
- **(b) v2** until v0.5 cut-over A/B passes; then flip to v3.
  Conservative; matches D-069 "v0.4 stays opt-in" posture.
- **(c) v3 only on architecture=v0_4** path (since v0.4 was already
  experimental); v0.3 default uses v2. Pins v3 to the experimental
  axis to start.

**My read:** (b). v0.5 ships v3 as opt-in; A/B runs at Tier C/D;
if A/B passes per Tier-E veto, future v0.5.1 release flips default
to v3.

**Resolves at Tier 0.**

## Tier 0 — orientation read + DQ sign-off

Read-only research; no code. Result is a one-page decision artifact
+ DQ1-DQ4 resolutions + new DECISION entries.

**0.1** Read substory_design.v1.md + slide_compose.v1.md + .v2.md
end-to-end. Cataloge what each prompt asks for + what each emits.
Identify where Q/A/R/C structure could land (top-level
substory fields? per-slide layout sequence?).

**0.2** Read 3-4 actual substories from the M6 A/B drafts
(ibd_phage_targeting + functional_dark_matter, both v0.3 and v0.4)
to inventory how substories actually shape today. Specifically:
which substories DO have an implicit Q/A/R/C arc + which don't.
Pattern-detect.

**0.3** Inventory register-discipline violations in M6 drafts.
Grep for the regex patterns named in DQ2 against the actual
slide_spec.json content fields (bullets, captions, subtitles,
answer_summary, etc.). Count + characterize.

**0.4** Draft DECISIONS for DQ1-DQ4 (likely D-071..D-074). Lock
in: Q/A/R/C contract shape; register heuristic + allowlist
mechanism; substory-shape enforcement severity; v3 prompt default
posture.

**AC for Tier 0:** Adam signs off on DQ1-DQ4 resolutions before
any Tier-A code lands.

## Tier A — `substory_design.v3.md` + `slide_compose.v3.md` + `--prompts-version` flag

Three sub-changes:

**A.1** New `prompts/substory_design.v3.md`. Adds the Q/A/R/C
contract per DQ1 resolution. Likely shape (per DQ1 (b) middle-
ground option):

```
For each substory, designate:
- Q-slide (section_divider OR opening big_idea): names the
  scientific question this substory answers.
- A-slide(s): methods OR analytical framework slides.
- R-slide(s): results slides (data_figure, data_table, big_number).
- C-slide: closing slide (claim_evidence OR big_idea) summarizing
  what's been established and explicitly handing the next
  question forward to the next substory.

Substory-level metadata:
  question: "<the one scientific question this substory answers>"
  conclusion_for_next_substory: "<one-sentence handoff to next>"
```

**A.2** New `prompts/slide_compose.v3.md`. Register-discipline-aware:
- Pre-flight reminder block: "Audience-facing prose. Avoid
  specialist references — say 'a robust statistical analysis'
  not '§Finding 7 binomial p=0.072'; say 'recovered 87/95 loci'
  not 'NB10 §3'; say 'fitness assay' not 'Price2022 fitness
  data'."
- Post-composition self-check: "Before emitting JSON, re-read each
  slide's prose. Replace any notebook IDs, REPORT section markers,
  figure file names, or specialist tool versions with general
  analytical language."

(The validator at Tier A.1 catches the soft-warning case; the
prompt provides the discipline upstream.)

**A.3** Orchestrator `--prompts-version {v1,v2,v3}` flag wired
through `presentation_maker.sh`. Default: v2 per DQ4 (b). Dispatch
in `stage_substory_design` + `stage_slide_compose` picks the right
prompt file by version. Per-version prompts coexist in `prompts/`
(no archive moves).

**AC for A:** orchestrator accepts `--prompts-version v3`; runs
through `substory_design` + `slide_compose` stages without breaking
existing v1/v2 paths; new v3 prompts render valid `slide_spec.json`
+ valid `slide_compose-S*.json` fragments.

## Tier A.1 — `tools/check_register_discipline.py`

New post-composer validator. Soft-warning severity by default per
DQ2.

**A.1.1** Heuristic implementation (per DQ2 resolution):
- Regex set for clear-flag patterns (NB IDs, §Finding/§Step
  markers, figure file names, in-prose citation keys).
- Allowlist for ambiguous patterns (tool names, software versions
  when audience-relevant; pulled from per-talk allowlist or
  default whitelist).
- Per-slide scan over `content.bullets`, `content.subtitle`,
  `content.caption`, `content.answer_summary`, `content.step_caption`,
  `content.notes` (speaker notes get a separate, looser allowlist).
- Audience-aware: title slides + acknowledgments + references get
  a much looser allowlist than data_figure captions.

**A.1.2** Output: extends `audit/presentation_validation.json`
with a `P11` validator entry (next P-validator slot after P10);
soft-warning severity by default; promotes to error only if Tier
0 DQ2 resolution lands "error" (currently TBD — recommended
"soft-warning").

**A.1.3** Tests: synthetic-prose fixtures for each pattern;
allowlist mechanism (per-project + default); audience-aware
severity scaling.

**A.1.4** Optional CLI: standalone invocation against a single
slide JSON for operator inspection (`python check_register_discipline.py
<slide_spec.json>`).

**AC for A.1:** P11 entry appears in `audit/presentation_validation.json`;
soft-warning per slide that contains specialist refs; doesn't
break the cascade Tier-1; clean output on a well-disciplined deck.

## Tier B — `tools/check_substory_shape.py`

Post-composer / post-merge check that each substory has Q/A/R/C
shape per the v3 contract. Per DQ3 resolution, emits cascade
Tier-2 findings (`kind=substory_arc`); doesn't hard-fail.

**B.1** Read merged `slide_spec.json` + substory metadata from
`substories.md`. For each substory:
- Locate the substory's Q-slide (section_divider OR opening
  big_idea with `question:` field in v3).
- Locate at least one R-slide (data_figure, data_table,
  big_number).
- Locate the C-slide (closing claim_evidence OR big_idea with
  `conclusion_for_next_substory:` field).
- Validate the handoff: does the next substory's Q match the
  previous substory's `conclusion_for_next_substory`?

**B.2** Emit a `substory_shape.json` audit artifact + integrate
with `review_cascade.py::run_tier1` (or as a new cascade
augmentation). Findings appear as `kind=substory_arc` (same as
M5b adversarial findings), severity P1.

**B.3** Tests: synthetic substory fixtures (well-shaped + each
failure mode: missing Q, missing R, missing C, broken handoff).

**AC for B:** new findings appear in cascade Tier-1 audit when
substory-shape rules are violated; cascade short-circuit
unaffected (only P0 short-circuits); existing tests pass.

## Tier C + D — A/B runs

Mirror M6 Tier B + C exactly. Re-use `tools/m6_score.py` unchanged.

**Tier C** (`ibd_phage_targeting`, target per D-041):
- v0.3 + v0.4 baselines already on disk from M6 (`draft_4`,
  `draft_5`) — REUSE them; no need to re-run.
- New: v0.5 run with `--prompts-version v3` (architecture default
  v0_3). Lands at `draft_6`.
- Score: `m6_score.py --v0_3-target=draft_4 --v0_4-target=draft_6`
  (treats v0.5 as "the new v0.4 candidate") — surfaces the v0.5
  vs v0.3 delta.
- Optional secondary score: `--v0_3-target=draft_5 --v0_4-target=draft_6`
  (v0.5 vs v0.4-experimental).

**Tier D** (`functional_dark_matter`, sanity):
- v0.3 + v0.4 baselines on disk from M6 (`draft_2`, `draft_5`) —
  REUSE.
- v0.5 run at `draft_6` or `draft_7`.
- Same scoring against `m6_score.py`.

**Estimated cost:** ~$13 (ibd v0.5 run; similar to v0.3) + ~$13
(fdm v0.5 run; same shape) = **~$26 total live spend**. Saves
~$50 vs M6 because v0.3/v0.4 baselines are reused.

**AC for C + D:** both v0.5 runs complete + .pptx delivered +
audit JSONs populated; `m6_score.py` produces final report.

## Tier E — Adam reads decks + scores metric 5 + veto

Per D-066. Adam reads:
- ibd v0.3 (draft_4) vs ibd v0.5 (draft_6)
- fdm v0.3 (draft_2) vs fdm v0.5 (draft_6 or _7)

Optionally also reads v0.5 vs v0.4-experimental (if Adam wants
the four-way comparison; punch-list-optional).

Casts veto: ship / don't-ship / ship-but-flag. Per D-066 the
final call is Adam's regardless of mechanical result.

**Veto-question to keep in mind during the read:** *did v0.5 fix
the upstream content-shape weakness Adam named in M6?*
Specifically:
- Are substory transitions tighter?
- Did the "walls of text poisoned by specialist reference" diminish?
- Is the Q → A → R → C arc visible in each substory?
- Do substories build into a unifying point?

If YES → ship v0.5 as default; v0.3/v0.4 prompts archive at v0.5.1.
If NO → v0.5 stays opt-in via `--prompts-version v3` (mirror v0.4's
opt-in pattern); next milestone (v0.6) picks up the remaining 2
deferred workstreams (throughline-bridge + figure-utilization).
If MIXED → ship-but-flag; v0.5.0-experimental tag.

## Tier F — docs

**F.1** `SPEC.md` updates — v3 prompt set documented; P11 validator
documented in §13 P-validator table; Q/A/R/C contract documented
in §4.2 (substory list).

**F.2** `V0_4_ARCHITECTURE.md` — v0.5 stub fleshed out into SHIPPED
block (or experimental block per veto outcome) at §16.

**F.3** `LAYOUT.md` — `check_register_discipline.py` +
`check_substory_shape.py` entries; v3 prompt set entries.

**F.4** `DECISIONS.md` — Tier-0 DECISIONs (D-071..D-074 for DQ1-DQ4);
Tier-E veto outcome (D-075-ish, depending on D-N usage).

**F.5** `RELEASE_NOTES.md` — v0.5.0 or v0.5.0-experimental entry
per veto.

## Tier G — closeout + tag

Mirror M6 Tier F. `V0_5_PUNCH_LIST.md` status table closed;
auto-memory `project_presentation_maker_v0_5.md` written; MEMORY.md
index promoted; git tag `v0.5.0` or `v0.5.0-experimental` per
Tier-E veto.

## Dep edges

```
Tier 0 (DQ sign-off) → unlocks A + A.1 + B in parallel
Tier A → Tier C/D (need v3 prompts to run v0.5)
Tier A.1 → Tier C/D (P11 validator influences scoring)
Tier B → Tier C/D (substory_arc findings influence scoring)
Tier C + D → Tier E (Adam read needs both project pairs)
Tier E → Tier F + G (paperwork)
```

## Smoke gates

- **Tier 0 gate:** Adam signoff on DQ1-DQ4 resolutions + DECISIONS
  drafted.
- **Tier A gate:** orchestrator `--prompts-version v3` runs end-to-
  end on a small project (existing M6 fixture if quick); fragments
  validate.
- **Tier A.1 gate:** unit tests green on each regex pattern +
  allowlist; P11 entry appears in `audit/presentation_validation.json`.
- **Tier B gate:** unit tests on Q/A/R/C structural checks +
  handoff detection; cascade Tier-1 absorbs the new findings
  without breaking short-circuit behaviour.
- **Tier C/D gate:** v0.5 runs complete; `m6_score.py` produces
  report.
- **Tier E gate:** Adam-veto outcome + metric-5 Likert.

## What v0.5 does NOT do

- **No architectural changes.** Sequential vs parallel-compose
  dispatch is settled per D-069. `--architecture-pipeline {v0_3,
  v0_4}` flag stays; v0.4 stays opt-in.
- **No new image-gen providers.** M5b shipped the multi-provider
  layer; v0.5 doesn't touch image_client.py beyond bug fixes if any.
- **No state.json introduction.** D-067 settled this; v0.5 still
  uses per-stage audit JSONs.
- **No throughline-bridge pass.** Deferred to v0.6 unless v0.5 A/B
  shows the Q/A/R/C contract didn't subsume the cross-substory
  bridging weakness.
- **No figure-utilization contract.** Deferred to v0.6 unless
  ditto.
- **No new adversarial finding classes.** v0.5 extends the
  cascade with `substory_arc` (matches the existing class), not a
  new schema.

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — orientation read + DQ sign-off | 2-3h research + DECISIONS |
| A — v3 prompts + flag wiring | 3-4h prompts + orchestrator + tests |
| A.1 — register-discipline validator | 4-6h heuristic + allowlist + tests |
| B — substory-shape post-check | 3-4h tool + cascade integration + tests |
| C — ibd v0.5 run | ~50min wall + ~$13 spend |
| D — fdm v0.5 run | ~50min wall + ~$13 spend |
| E — Adam read + veto | 30-60min Adam-time |
| F — docs | 1-2h |
| G — closeout + tag | 30min |
| **Total** | ~15-20h coding/docs; ~$26 live spend; ~1h Adam-attention |

Note: live spend is HALF of M6 because the v0.3/v0.4 baselines are
already on disk (re-use M6's draft_2/draft_4/draft_5).

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| v0.5 doesn't actually move the needle on Adam's read (Q/A/R/C contract too rigid OR too loose) | Tier E veto catches this; v0.5 stays opt-in; v0.5.1 iterates on prompt content (cheaper than re-architecting) |
| Register-discipline allowlist is wrong (too aggressive flags legitimate audience-relevant tool names) | Soft-warning default per DQ2 = operator can ignore; allowlist tunable per-project |
| Q/A/R/C contract forces uniform substory shape that doesn't fit some scientific narratives | DQ1 (b) middle-ground preserves flexibility; soft enforcement via cascade Tier-2 (DQ3 (c)) not hard-fail |
| v0.5 prompts produce more tokens (Q/A/R/C scaffolding costs prose) | Token cost metric in m6_score will catch this; veto can accept cost regression if quality wins |
| `--prompts-version` flag interacts unexpectedly with `--architecture-pipeline` (4-way matrix) | Tier A includes a smoke covering each combination; tests pin each combination |

## Ref

- `DECISIONS.md` D-070 (v0.5 scope opening; this punch list
  delivers on it).
- M6 Tier D Adam read (the content-shape findings driving v0.5).
- `tools/m6_score.py` (reused for v0.5 cut-over A/B).
- `tools/finalize_run.py` + `audit/runs/run-N/summary.json` (data
  infrastructure unchanged).
- `prompts/substory_design.v1.md` + `slide_compose.v1.md` + `.v2.md`
  (existing prompts v0.5 supersedes via new v3 files).
- M4a Tier B / D-053 (soft-warning posture for length caps; v0.5's
  register-discipline validator follows the same posture).
- M4b `review_cascade.py` (the infrastructure substory-shape
  findings integrate into per DQ3).
- M5a `revise_invariance.py` (the semantic-invariance pattern v0.5
  may extend if substory-shape needs revise-loop integration).
