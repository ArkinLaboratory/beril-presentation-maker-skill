# V0.6 Punch List — Figure-utilization + image/tee infra fixes

**Status:** drafted 2026-05-27 (post-v0.5.1 D-079 veto).
Authoritative scope opening: this file + `DECISIONS.md` D-079 (the
v0.5.1 veto + v0.6 inputs); pin from
[[project-presentation-maker-v0-5-1]] §"v0.6 inputs."

**Posture:** v0.6 picks up the highest-leverage two carries from
v0.5.1's Tier-E read + a small infrastructure bundle. Mirrors the
D-070 pattern Adam used at v0.5 ("ship the highest-leverage two
first; the others wait"). v0.6 is **content-quality + infra**, not
architectural — the D-075 concat-overlay pattern is settled; v0.6
extends it.

**Scope (2 workstreams + 1 infra bundle):**

1. **Figure-utilization contract** (load-bearing; the deferred
   D-070 carry; Adam-rubric pin from D-079: *"every arc should
   back a claim or finding by relevant figure if possible"*).
   → `prompts/slide_compose.v3.1_overlay.md` (figure-utilization
   guidance) + `tools/check_figure_provenance.py` (post-composer
   validator) + composer prompt nudge.
2. **Image-gen + orchestrator-tee infra bundle** (small
   reliability fixes that unblock end-to-end runs).
   → 2a: root-cause-then-fix the "0/31 images approved" mystery
     on ibd v0.5.1; either policy-flag or bug-fix depending on
     outcome.
   → 2b: fix the orchestrator's tee/BlockingIOError that caused
     the false "validation FAILED" on fdm v0.5.1 (real but
     separable from prompt-architecture work).

**Deferred to v0.7+** (still real issues; not in v0.6 batch):

- **Retraction-aware composer / `discarded_results.md` filter** —
  the NB04 leak Adam called out was a story bug. The composer
  reproduces retracted analyses as story beats. This is high
  content-correctness leverage but more design surface than v0.6
  can absorb. **Risk to v0.6:** if the v0.6 figure-utilization
  live A/B surfaces another NB04-class content bug, retraction
  moves to guaranteed v0.7 (don't defer further).
- **Compression / mode-budget heuristics** — both v0.5.1 decks
  slightly over mode budget. Investigate-and-tune work that
  benefits from having v0.6's figure-utilization data first
  (more figures may reshape compression behavior).

**Prompt versioning:** v3.1 overlay on v3 (per DQ choice 2026-05-27).
v0.6 ships:
- `slide_compose.v3.1_overlay.md` (new — figure-utilization
  additions).
- `substory_design.v3.md` unchanged at v3 (no substory-design
  changes in v0.6).
- Concat at runtime: `cat slide_compose.v2.md slide_compose.v3_overlay.md
  slide_compose.v3.1_overlay.md > audit/_prompts/slide_compose.v3.1.concat.md`
  (D-075 pattern extends; overlay-last attention rule preserved;
  v3.1 wins over v3 wins over v2 on conflicts).
- `--prompts-version {v1,v2,v3,v3.1}` flag added (D-074 pattern
  extends).
- Smoke gate (D-076) extends: a v3.1 invocation requires a fresh
  v3.1-smoke-pass record. The existing v3 record does NOT satisfy
  v3.1 (different prompt-body sha).

**Cut-over rule:** same as v0.5/v0.5.1 (D-066, D-079 lineage).
Adam-veto is final regardless of mechanical result. Metric targets
for v0.6:

- **Figure-utilization rate** (new metric): % of curated figures
  used in the final deck (target: ≥70% on talk-30 STRONG; v0.5.1
  baseline was 43% on ibd, ? on fdm).
- **Data-figure slide count** (new metric): count of `data_figure`-
  layout slides per deck (target: ≥1 per non-Q substory; v0.5.1
  baseline was 3 of 5 ibd substories had ≥1 data_figure).
- **Q/A/R/C presence** (regression check; must hold from v0.5.1):
  0 violations per project.
- **Audience-prose violations** (regression check; must hold):
  ≤ v0.5.1's numbers (ibd 17, fdm 3).

## DQs to resolve at Tier 0 sign-off

### DQ1: figure-utilization rule strictness

**Question:** How does the figure-utilization contract enforce?

**Options:**
- **(a) Hard rule, composer-prompt-only**: v3.1 overlay's
  inviolable-rules adds "every R-slide that COULD use a
  curated figure MUST use one." Composer judges; no
  post-validator. **Lightest.**
- **(b) Soft-warning, validator-only**: `tools/check_figure_provenance.py`
  emits a P-validator soft-warning when curated figures exist
  but a substory has 0 data_figure slides. No composer guidance
  change. **Decoupled but might not move LLM behavior.**
- **(c) Both**: v3.1 overlay nudges composer + validator
  catches violations post-hoc. **Belt + suspenders; matches
  D-072 register-discipline pattern.**

**My read:** (c) — the D-072 precedent (register-discipline used
both a prompt-side preamble AND a post-validator) is the right
pattern. The prompt guides; the validator catches. Single-layer
doesn't move behavior enough OR doesn't catch what gets through.

**Resolves at Tier 0.**

### DQ2: figure-utilization metric — what counts?

**Question:** How to count "figure used in the deck"?

**Options:**
- **(a) Any reference to figure-path on any slide** — too lenient;
  catches references-without-rendering.
- **(b) `data_figure` slide with `figure:` field pointing to a
  curated figure** — strict; the curated figure has its own slide.
- **(c) `data_figure` slide OR `concept_illustration` slide
  referencing a curated figure (or AI-image of similar subject)** —
  middle ground.

**My read:** (b). The Adam-rubric was *"every arc should back a
claim or finding by relevant figure"* — a slide with the figure
as its focal element. (a) is gameable; (c) gets us into "is an AI
illustration of the same topic the same figure?" semantics that
don't help.

**Resolves at Tier 0.**

### DQ3: no-image diagnostic — first pass before fix

**Question:** Do we know yet whether the 0/31 image-gen decisions
issue on ibd v0.5.1 is a policy issue or a bug?

**Options:**
- **(a) Operator-side inspection first** — Adam runs `cat
  $BERIL_ROOT/.../draft_6/working/05_image_decisions.json` locally
  (harness sandbox blocked it during v0.5.1); report the action
  distribution. Then we decide policy-vs-bug.
- **(b) Re-run image_gen_decision in isolation** — invoke
  `image_gen_decision.py` directly against the merged
  slide_spec.json + LLM judge; produces a new decisions.json we
  CAN read. ~5 min, no live cost (uses the merged spec on disk).

**My read:** (b). Faster + reproducible. Bypasses the
harness-sandbox issue + gives us an artifact to inspect.

**Resolves at Tier 0 inspection.**

### DQ4: orchestrator tee bug — redirect or stdbuf?

**Question:** How to fix the validator-stderr pipe-buffer issue?

**Options:**
- **(a) Redirect validator stderr to a file** in
  `stage_merge_and_assemble`: `slide_spec.py validate "$spec"
  2> "$AUDIT_DIR/validate.stderr"`. The stderr-then-tee path is
  the one that blocks; redirecting to file removes the tee
  hazard. **Smallest change.**
- **(b) Use `stdbuf` to line-buffer the validator's output** so
  it doesn't accumulate in pipe buffers. Requires `stdbuf` on
  PATH (Linux/macOS-coreutils; available in Homebrew).
- **(c) Wrap the whole orchestrator with `script(1)`** — heavier
  shellscript wrapper, but immune to pipe-buffer issues system-wide.

**My read:** (a). One-line fix; preserves orchestrator's existing
output shape; tee on the parent invocation can still capture
everything else. The validator's stderr is the only oversized
writer in the pipeline.

**Resolves at Tier 0.**

## Per-tier scope

| Tier | Scope | Status |
|---|---|---|
| 0 — DQ1-DQ4 sign-off + DQ3 image-gen-decision diagnostic | research + DECISIONS | ✅ ready to commit 2026-05-27 (DQ3 diagnostic revealed a RENDERER BUG, not a policy issue: `working/05_image_decisions.json` on ibd v0.5.1 shows 31 decisions / 2 emit=true / 29 correctly skipped per policy; `working/05_images/intro-pos*.png` both present + manifest binds them onto `slide_spec.json[image_path]`; but `assemble_pptx.py::_fill_big_idea` and `_fill_claim_evidence` ONLY read `supporting_graphic`/`figure` respectively, NOT `image_path` — so the 2 generated images get silently dropped. D-082 captures the bug + fix. All four DQs resolved with recommended options: D-080 (both prompt+validator), D-081 (strict counting on data_figure+curated-figure path), D-082 (renderer fix in Tier B.1, NOT a policy redesign), D-083 (redirect validator stderr to file)) |
| A — `slide_compose.v3.1_overlay.md` + `--prompts-version v3.1` flag + dispatcher extension | prompts + orchestrator | ✅ ready to commit 2026-05-27 (new `prompts/slide_compose.v3.1_overlay.md` ~180 lines per D-080: figure-utilization contract — per-substory rule "≥1 data_figure when curated figure exists for analysis"; Adam-rubric pin reproduced verbatim; v3.1 anti-patterns (figure-as-decoration, figure-orphaning, curated-figure-substitution); v3.1 inviolable rules 8+9 (data_figure for curated figures, prefer data_figure over claim_evidence). Orchestrator: `--prompts-version v3.1` validated; `_slide_compose_prompt_path` v3.1 case returns `$SLIDE_COMPOSE_V3_1_CONCAT_PATH`; `_substory_design_prompt_path` v3.1 case reuses v3 concat (substory_design unchanged in v3.1). `build_v3_concat_prompts` extended to write BOTH v3 (substrate) AND v3.1 (stacked) when PROMPTS_VERSION=v3.1; concat order `cat v2.md + v3_overlay.md + v3.1_overlay.md` per D-075 attention rationale. All 6 v3-only gates (`PROMPTS_VERSION == "v3"`) updated to OR with `v3.1` so v3.1 invocations still get the v3 user-prompt injection (SUBSTORY_QUESTION/CONCLUSION/ALLOWLIST_TERMS) — v3.1 stacks on the v3 user-prompt contract. Smoke harness: `compute_prompt_sha()` extended to include the v3.1 overlay file → any existing v3 pass record gets sha-invalidated → operator forced to re-run smoke before any v3 OR v3.1 invocation (Tier C will properly compose against the v3.1 stack; this is the smallest change that prevents the gate from passing erroneously). --help docstring updated. Tests +7: v3.1 overlay-present-on-disk, validation accepts v3.1, v3.1 dispatcher returns v3.1 concat, v3.1 dispatcher for substory reuses v3 concat, build creates v3.1 concat with stacked order, build doesn't create v3.1 concat when v3, 6+ OR-gates pin, pre-flight loop pin. Suite 1454 passed.) |
| A.1 — `tools/check_figure_provenance.py` per D-080 + D-081 | new tool + tests | ✅ ready to commit 2026-05-27 (new `tools/check_figure_provenance.py` ~430 lines: parses `working/curated_figures.md` for path inventory; parses `02_substories.md` for per-substory analysis notebooks; matches curated figures to substory analyses by NB-id prefix (strips trailing letter so NB04b/NB04h both → NB04). Two finding kinds per D-080: `missing_data_figure_for_curated_analysis` (substory cites a curated figure but has 0 data_figure slides using it) + `data_figure_path_not_in_curated_inventory` (data_figure cites a non-curated path — anti-pattern per v3.1 overlay). Per D-081 strict counting: only `data_figure` with `figure:` exactly matching a curated inventory path counts. Utilization-rate metric: n_substories_covered / n_substories_with_curated. Cascade integration: new `_read_figure_provenance` in `review_cascade.py` (read-if-present per visual_qa/D-073 pattern); cascade Tier-1 finding-kind `figure_provenance:<sub-kind>`; severity always P1 (soft-warning maps to P1; never P0). 18 new unit tests + cascade-reader pin (28 effective tests counting parametrize). Live verification: ibd v0.5.1 figure-utilization 66.67% (below 70% target — S3 has NB11 curated figure but used claim_evidence instead — exactly the D-079 carry symptom); fdm v0.5.1 100% (1 of 1 covered). Suite 1472 passed) |
| B — orchestrator tee fix per D-083 (`2> $AUDIT_DIR/validate.stderr`) | orchestrator | ✅ ready to commit 2026-05-27 (one-line redirect at both validate call sites in `presentation_maker.sh`: `stage_merge_and_assemble` main validate (line 2273) + revise-loop post-revise re-validate (line 2557). Both invocations now redirect stderr to `$AUDIT_DIR/validate.stderr` (or `.post_revise.stderr`) via `2> "$_validate_stderr"`; failure branch cats the file to orchestrator stderr (so operators still see the error context); success branch ALSO cats (so soft-warnings still surface — preserves pre-fix advisory output without the pipe back-pressure hazard). New test file `tests/unit/test_orchestrator_validator_stderr.py` with 4 tests pinning: (1) main validate redirect pattern, (2) post-revise validate redirect pattern, (3) failure-branch cats stderr file, (4) success-branch ALSO cats (parity with old behavior; minimum 2 `cat $_validate_stderr` occurrences in the function). Suite 1443 passed) |
| B.1 — RENDERER FIX per D-082: `_fill_big_idea` + `_fill_claim_evidence` honor `image_path` | renderer + tests | ✅ ready to commit 2026-05-27 (added `image_path` fallback to both fillers in `assemble_pptx.py`. `_fill_big_idea` Mode-2 path: `graphic_src = content.get("supporting_graphic") or content.get("image_path")` + field-name carries through to `_resolve_asset_path` warnings context. `_fill_claim_evidence` with-figure branch: same pattern for `figure_src = content.get("figure") or content.get("image_path")`; also gracefully handles missing `figure_caption` (AI illustrations don't have captions per M5b schema — direct `content["figure_caption"]` KeyError'd pre-fix). Re-rendered both v0.5.1 decks (no live cost): ibd 5 slides with pictures (was 3 — +2 AI intros now visible); fdm 3 (was 1 — +2). 3 new unit tests pin the fallback behavior: image_path renders for big_idea, image_path renders for claim_evidence without figure_caption, supporting_graphic wins over image_path when both present (legacy precedence). Suite 1446 passed) |
| C — extend smoke harness for v3.1 (`tools/smoke_v3_prompt.py` adds v3.1 concat-build + prompt sha bump) | smoke tool | ✅ ready to commit 2026-05-27 (`build_concat` made variadic — accepts N source files + `out=` kwarg-only; v3 = 2 sources, v3.1 = 3 sources. `run_smoke` takes `version` param ("v3" or "v3.1"); raises ValueError on invalid. v3.1 default per D-080 rationale: validates the full v0.6 stack; a v3.1 smoke implicitly covers v3 since v3.1 stacks on top. CLI: new `--version {v3,v3.1}` flag with default v3.1; --help documents both. Tmpdir prefix + record labels reference `args.version` for traceability (e.g., `[smoke_v3.1] PASS — wrote audit/v3_smoke_pass.json`). Pass record sha already covers all 5 source files including v3.1 overlay (added in Tier A). 5 new tests: variadic build_concat 2 + 3 sources order; run_smoke rejects invalid version with clear message; --help mentions --version + v3.1 + default; default-is-v3.1 source-pin. Suite 1477 passed) |
| D — live A/B re-run on ibd_phage_targeting (v3.1 vs v3 vs v0.3 baseline) | live (~$13) | ✅ ran 2026-05-27 11:10–11:22 (ibd v0.6 deck rendered, 32 slides, 2.27MB .pptx, figure-utilization 100% (4/4 substories covered, was 66.7%/3/7 at v0.5.1), 0 schema errors, cascade 0/0/0/0 (P0/P1/P2/P3); audit complete) |
| E — live A/B re-run on functional_dark_matter (sanity) | live (~$13) | ✅ ran 2026-05-27 11:12–11:38 (fdm v0.6 deck rendered, 27 slides, 1.92MB .pptx, figure-utilization 100% (held), 0 schema errors; audit INCOMPLETE — missing review_cascade.json + adversarial_review.* + presentation_validation.json; .pptx + slide_spec + figure_provenance valid; flagged for v0.7 Tier 0 diagnostic per Lesson 5) |
| F — Adam reads decks + scores metric 5 + casts veto | review + DECISION | ✅ Adam Tier-F veto 2026-05-28: DON'T SHIP per D-084. Mechanical targets all met (figure-utilization ≥70% on both decks — actually 100%; schema 0; cascade clean on ibd). Five qualitative findings: (1) per-arc figure clustering (metric coverage-breadth vs Adam-rubric per-arc-placement); (2) no arc transitions; (3) no closing synthesis; (4) AI images generic-by-construction (architectural — concept_illustration policy limits to big_idea metaphor slot only); (5) slide 27 methods slot factual error (templated wording vs ground truth: 8 primary + 4 reference DBs + HMP2 cohort + 32 notebooks). All five become v0.7 inputs as D-084-A through D-084-E per Adam-confirmed direction 2026-05-28 |
| G — docs (DECISIONS + V0_4_ARCH + RELEASE_NOTES + LAYOUT per veto) | docs | ⬛ CANCELLED per veto (D-084 = DON'T SHIP; no release notes / V0_4_ARCH / LAYOUT updates needed; DECISIONS.md updated with D-084 alone) |
| H — closeout + auto-memory + tag (per veto) | paperwork + tag | ✅ closeout-only per veto: D-084 landed in DECISIONS.md; v0.6 retrospective auto-memory entry at `project_presentation_maker_v0_6.md`; MEMORY.md index updated; V0_7_PUNCH_LIST.md drafted next. No `v0.6.0` tag (per veto) |

## Dep edges

```
Tier 0 → unlocks A + A.1 + B + B.1 + C
Tier A → Tier C (smoke needs v3.1 prompts)
Tier A + A.1 + B + B.1 + C → Tier D/E (live runs need everything stable)
Tier D + E → Tier F (Adam read)
Tier F → Tier G + H (paperwork)
```

## Smoke gates

- **Tier 0 gate:** DQ1-DQ4 resolutions; DQ3 diagnostic outcome
  (policy or bug) documented.
- **Tier A gate:** orchestrator accepts `--prompts-version v3.1`;
  v3.1 concat built at startup; smoke harness extended to validate
  v3.1 fragment.
- **Tier B gate:** orchestrator tee bug repro fixed; assemble_pptx
  invoked on a known-good slide_spec.json runs end-to-end.
- **Tier B.1 gate:** image-gen-decision behavior either matches
  policy-as-designed (DQ3=policy) OR matches expected-bug-free
  behavior (DQ3=bug-fix).
- **Tier C gate:** `smoke_v3_prompt.py` accepts a `--version v3.1`
  flag or auto-detects the concat; smoke pass record for v3.1
  sha gets written.
- **Tier D/E gate:** both runs end-to-end; figure-utilization rate
  meets ≥70% target on at least one project.

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — DQ sign-off + DQ3 diagnostic | 1-2h research + DECISIONS |
| A — v3.1 overlay + dispatcher | 2-3h |
| A.1 — check_figure_provenance.py + tests | 3-4h |
| B — orchestrator tee fix + test | 1-2h |
| B.1 — image-gen policy/bug per outcome | 1-3h depending on DQ3 |
| C — smoke extension for v3.1 | 1h |
| D — ibd v3.1 run | ~50min wall + ~$13 spend |
| E — fdm v3.1 run | ~50min wall + ~$13 spend |
| F — Adam read + veto | 30-60min Adam-time |
| G — docs | 1-2h (only if shipping) |
| H — closeout + tag | 30min (only if shipping) |
| **Total** | ~10-15h coding + ~$26 live + ~1h Adam-attention |

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| v3.1 overlay nudge doesn't actually move composer behavior (figures stay under-used) | The post-validator (DQ1 (c) belt-and-suspenders) catches and lifts to revise_loop. Worst case operator sees soft-warnings + has to manually intervene; metrics still reported for Tier-F read. |
| Figure-utilization metric over-fires on substories that legitimately don't have figures | Curated-figure inventory IS the gate — if no curated figure for a substory's analysis, no soft-warning. Empty inventory = empty rule. Tested with synthetic fixture. |
| Stacked v2 + v3 + v3.1 overlay overruns LLM attention (1267 + 243 + ~150 = ~1660 lines of system prompt) | v0.5.1 smoke validated v2+v3 concat at ~1510 lines; +150 more is marginal. Smoke harness for v3.1 will catch if anything regresses. |
| The "0 images approved" mystery turns out to be a major bug that blocks v0.6 ship | Tier 0 DQ3 diagnostic runs early so the scope is known before downstream work; if it's a P0 bug we either fix in v0.6 or de-scope and continue. |
| Retraction leakage (NB04-class) recurs in v0.6 figure-utilization run, blocking veto | Pre-commit gate: if v0.6 Tier-D/E surfaces retraction leakage in the audit, retraction-aware composer moves to guaranteed v0.7 (no further deferral). |

## What v0.6 does NOT do

- **No retraction-aware composer** (deferred to v0.7+).
- **No compression / mode-budget heuristics** (deferred; investigate
  with v0.6 data first).
- **No new architectural pivots.** v3.1 is an overlay extension,
  not a redesign.
- **No new image-gen providers.** v0.6 may fix the no-image
  diagnostic but doesn't add providers (M5b shipped the multi-
  provider layer).
- **No SPEC schema changes.** v0.6 metrics piggyback on existing
  audit artifacts.

## What ships at v0.6 closeout (conditional on veto)

If Adam-veto = SHIP:
- v0.6.0 tag.
- v3.1 prompts become opt-in via `--prompts-version v3.1`.
- Default `--prompts-version` stays at v2 OR moves to v3.1 per
  Adam's call.
- DECISIONS D-080..D-08x for the v0.6 decisions.
- `tools/check_figure_provenance.py` blessed as a P-validator
  (P12).
- RELEASE_NOTES + V0_4_ARCH + LAYOUT updates.

If Adam-veto = DON'T SHIP:
- Same pattern as v0.5.1 D-079: work stays on main; no tag; v0.7
  inputs captured.

## Ref

- `DECISIONS.md` D-079 (the v0.5.1 veto opening v0.6 scope).
- D-070 (v0.5 scope; figure-utilization is the deferred carry).
- D-075 / D-076 / D-077 / D-078 (the v3 architectural pattern v3.1
  extends).
- D-066 (Adam-veto-final pattern continuing at v0.6 cut-over).
- [[project-presentation-maker-v0-5-1]] (the retrospective +
  v0.6 inputs).
- `prompts/slide_compose.v3_overlay.md` (the v3 overlay v3.1
  stacks on).
- `tools/smoke_v3_prompt.py` (the smoke harness v3.1 extends).
- `tools/check_register_discipline.py` + `tools/check_substory_shape.py`
  (the D-072/D-073 validator precedents check_figure_provenance.py
  mirrors).
