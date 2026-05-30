# V0.7 Punch List — Per-arc figure placement + arc-transitions + closing synthesis + technical image-gen + structured methods

**Status:** drafted 2026-05-28 (post-v0.6 D-084 veto).
Authoritative scope opening: this file + `DECISIONS.md` D-084 (the
v0.6 veto + five v0.7 inputs); pin from
[[project-presentation-maker-v0-6]] §"v0.7 inputs."

**Posture:** v0.7 picks up the five qualitative findings from
Adam's Tier-F read of the v0.6 (v3.1) decks. Same pattern as the
D-079 → v0.6 transition (mechanical-pass + Adam-veto + carries
become next-version scope). Five workstreams clustered into three
themes: **arc-cohesion + per-arc placement** (findings 1-3),
**image-gen scope expansion** (finding 4), **structured methods
slot** (finding 5). Plus three carries from v0.5.1/v0.6 lessons
(retraction filter, FDM cascade incompleteness diagnostic, per-slot
template sweep).

**Scope (5 workstreams + 3 carry items):**

1. **Per-arc figure placement** (refines D-080/D-081; D-084-A).
   → `prompts/slide_compose.v3.2_overlay.md` adds per-arc rule:
     "if N curated figures available for the deck, distribute
     them across arcs — at most ⌈N/arcs⌉ figures per arc unless
     no alternative." Plus distribution-aware counting in
     `check_figure_provenance.py`.
2. **Arc transitions** (D-084-B).
   → `slide_compose.v3.2_overlay.md` adds arc-transition guidance:
     each substory's intro slot references the prior arc's
     conclusion. Optional transition layout (`arc_bridge`?) — DQ.
3. **Closing synthesis** (D-084-C).
   → New layout `deck_close` (or `synthesis` / `unified_point` —
     DQ on naming). slide_compose's final-substory C-slot OR a
     post-substory append stage produces a deck-spanning slide
     that brings the arcs together.
4. **Image-gen scope expansion to claim_evidence** (D-084-D).
   → `image_gen_decision.py` LLM-judge prompt expanded to consider
     claim_evidence slides with technical-amenable bullet
     structure (≥3 distinct mechanisms / phases / categories).
     Image-gen prompt template extended to pull from substory
     analyses (methods text, statistics, mechanism vocabulary).
     New "technical-specificity" criterion in the judge.
5. **Structured methods-slot composition** (D-084-E).
   → New curator output extension: `methods_provenance.md`
     gains tiered structured fields (primary_databases,
     reference_databases, external_cohorts, notebook_count).
     New layout `methods_summary` (or extend existing) reads
     structured fields. slide_compose template for methods slot
     becomes data-driven, not free-text-templated.

**Deferred to v0.8+** (still real; not in v0.7 scope):

- **Retraction-aware composer / `discarded_results.md` filter** —
  no recurrence in v0.6. Deferral remains acceptable. If v0.7
  Tier-D/E surfaces retraction leakage in the read, moves to
  guaranteed v0.8 (no further deferral).
- **Compression / mode-budget heuristics** — ibd dropped 34→32 in
  v0.6; fdm 29→27. Closer to mode-budget compliance. Tune with
  v0.7 arc-transitions/synthesis data (more slides may shift
  compression behavior).

**Carry items in v0.7 (do alongside main workstreams):**

- **C1: FDM cascade-interruption diagnostic** (Lesson 5 from
  v0.6 retrospective) — root-cause why fdm draft_6 missing
  `review_cascade.json`/`adversarial_review.*`/`presentation_
  validation.json` while ibd has all three. Likely a Tier-0
  task: run cascade against the existing fdm draft_6
  slide_spec.json + reproduce the interruption.
- **C2: Per-slot template under-specification sweep** (Lesson 4
  from v0.6 retrospective) — audit `data_table`,
  `workflow_diagram`, `section_divider`, and any new layouts
  added in v0.7 for the slide-27-class bug (deck-spanning
  template slot composed from free text instead of structured
  upstream data). Likely a Tier-A audit; document findings
  even if no fix lands in v0.7.
- **C3: Per-arc distribution metric design** (part of W1 but
  worth flagging as its own design surface) — what counts as
  "per-arc distribution well-balanced"? Variance? Chi-squared
  vs uniform? Max-per-arc cap? Likely DQ at Tier 0.

**Prompt versioning:** v3.2 overlay on v3.1 stack (D-075 pattern
extends again). v0.7 ships:
- `slide_compose.v3.2_overlay.md` (new — per-arc figure rule + arc
  transitions + closing-synthesis guidance).
- `substory_design.v3.2_overlay.md` (new IF arc-transition
  cross-substory awareness needs substory-design changes — DQ).
- Concat: `cat slide_compose.v2.md slide_compose.v3_overlay.md
  slide_compose.v3.1_overlay.md slide_compose.v3.2_overlay.md >
  audit/_prompts/slide_compose.v3.2.concat.md` (D-075 attention
  rule extends; v3.2 wins over v3.1 on conflicts).
- `--prompts-version {v1,v2,v3,v3.1,v3.2}` flag adds v3.2.
- Smoke gate (D-076) extends: v3.2 requires fresh v3.2-smoke-pass.

**Cut-over rule:** same as v0.5/v0.5.1/v0.6 (D-066, D-079, D-084
lineage). Adam-veto is final regardless of mechanical result.
Metric targets for v0.7:

- **Per-arc figure-placement uniformity** (new metric): variance
  of data_figure count per arc; or max-per-arc / min-per-arc
  ratio ≤ 2. Definition TBD at DQ. v0.6 baseline was strongly
  clustered (Adam's qualitative read).
- **Arc-transition presence** (new metric): % of arcs after the
  first that reference the prior arc's conclusion. Target ≥75%.
  v0.6 baseline = 0% (no arc transitions composed).
- **Closing-synthesis present** (new metric, binary): does the
  deck have a deck_close / synthesis slide? Target = yes. v0.6
  baseline = no.
- **Image-gen approval rate on claim_evidence** (new metric):
  count of approved AI illustrations on claim_evidence slides.
  Target ≥1 per substory where technically-amenable. v0.6
  baseline = 0 (concept_illustration policy ruled out all
  claim_evidence approvals).
- **Methods-slot factual accuracy** (qualitative; checked at
  Tier-F): slide 27-class slide enumerates primary + reference
  + cohorts + correct notebook count. v0.6 baseline = wrong on
  ibd.
- **Figure-utilization regression check** (must hold from v0.6):
  ≥70% rate (v0.6 was 100% on both).
- **Schema errors regression check** (must hold): 0 on both
  decks.
- **Cascade-completion regression check** (must hold): all six
  cascade artifacts present on BOTH decks (FDM-incomplete bug
  from C1 must be fixed).

## DQs to resolve at Tier 0 sign-off

### DQ1: per-arc distribution metric definition

**Question:** How does the per-arc figure-placement metric count?

**Options:**
- **(a) Max-per-arc count ≤ ⌈N_figures/N_arcs⌉ + 1**: hard cap
  per arc with one slot for unevenness. Simple, deterministic.
- **(b) Variance / standard deviation across arcs ≤ threshold**:
  smoother metric; tolerates one outlier arc with more figures.
  Threshold TBD.
- **(c) Max-arc count / min-arc count ratio ≤ 2**: ratio-based;
  forgiving of arcs with no figures available.
- **(d) Per-arc utilization rate (analogous to D-081 per-deck
  rate)**: fraction of arcs with ≥1 data_figure when figures
  available. Misses "uses 4 figures in one arc" pattern.

**My read:** (a). Mirrors D-081's strict counting; deterministic
+ explicable; aligns with Adam-rubric "every arc should back a
claim or finding by relevant figure." (b)/(c) introduce variance
math that's harder to reason about; (d) doesn't catch clustering.

**Resolves at Tier 0.**

### DQ2: closing-synthesis layout — new layout or extend existing?

**Question:** How does the closing-synthesis slide land in the deck?

**Options:**
- **(a) New `deck_close` layout** with explicit fields
  (`unified_point` / `key_takeaways` / `forward_call`). Curator
  + slide_compose produce it from all substories' C-slots +
  the deck's overall arc.
- **(b) Extend existing `claim_evidence` or `big_idea` to a
  `closing` variant** with a flag. Less schema churn but
  semantically muddier.
- **(c) Final substory's C-slot becomes implicitly the deck
  closer** — no new layout; just composer guidance in v3.2
  overlay to make the final C-slot bring all arcs together.

**My read:** (a). The closing synthesis is structurally a
different slide-kind than per-substory C-slots — it's deck-
spanning, not substory-bounded. New layout makes the difference
explicit, which the renderer + validator + audit pipeline can
all reason about cleanly. (c) is appealing for simplicity but
puts a deck-spanning concern inside a per-substory unit; (b)
is half-measures.

**Resolves at Tier 0.**

### DQ3: arc-transition mechanism — substory_design or slide_compose?

**Question:** Where does cross-arc awareness live in the pipeline?

**Options:**
- **(a) `slide_compose.v3.2_overlay`** adds prompt guidance:
  "the first non-Q slot of each substory after the first
  should reference the prior substory's conclusion." Composer
  sees all substories in context (they already are in the
  v3 stack); just gets new guidance.
- **(b) `substory_design.v3.2_overlay`** adds explicit
  `transition_from_prior` field per substory; slide_compose
  reads the field to compose the transition. Cleaner data flow;
  more schema churn.
- **(c) New `arc_bridge` layout between substories** —
  dedicated transition slides between arcs. Most visible
  structurally; biggest scope.

**My read:** (a) for v0.7; reassess at v0.7 retrospective
whether (b) or (c) is needed. (a) is the smallest change with
the most leverage — composer already has full deck context;
just needs the guidance. (b) adds a substory-design schema
change; (c) adds slide-count which conflicts with v0.6
compression carry.

**Resolves at Tier 0.**

### DQ4: image-gen scope — claim_evidence-with-bullets only, or broader?

**Question:** Which slides become eligible for AI illustration
beyond big_idea?

**Options:**
- **(a) claim_evidence with ≥3 distinct bullets only** — strict
  cap; only slides where bullets clearly map to a multi-panel
  diagram. Conservative expansion.
- **(b) claim_evidence + any R-slide (data_figure or
  claim_evidence)** — broader; covers more substory bodies.
  Higher recall, lower precision.
- **(c) All non-Q layouts except data_figure** — broadest;
  reserves data_figure for curated REPORT figures, AI is
  allowed everywhere else.

**My read:** (a). Smallest expansion that addresses Adam's
"technical detail would be nice" feedback without opening the
floodgates. The judge's current strictness (rejects 29/30 on
ibd) is correct; the constraint is the *eligible slot set*, not
the judge bar. (b)/(c) risk flooding judges with too many
candidates and losing the per-slide quality.

**Resolves at Tier 0.**

### DQ5: structured methods-slot — curator output extension shape

**Question:** Where do the structured fields live?

**Options:**
- **(a) Extend `methods_provenance.md` with a YAML frontmatter
  block** containing `primary_databases`, `reference_databases`,
  `external_cohorts`, `notebook_count`. Body stays markdown.
- **(b) New sibling file `methods_structured.yaml`** alongside
  `methods_provenance.md` for the tiered fields; body stays
  in the .md.
- **(c) Extend `02_substories.md`** with a methods header section
  containing the tiered fields. Single source of truth for
  curator outputs.

**My read:** (a). Frontmatter is the lightest extension; existing
.md body remains human-readable; slide_compose reads frontmatter
for the methods slot composition. (b) adds a file to the curator
contract; (c) overloads substories with deck-level metadata.

**Resolves at Tier 0.**

## Per-tier scope

| Tier | Scope | Status |
|---|---|---|
| 0 — DQ1-DQ5 sign-off + C1 FDM diagnostic + C2 per-slot sweep audit | research + DECISIONS | ⬜ not started |
| A — `slide_compose.v3.2_overlay.md` per-arc rule (D-084-A) + dispatcher + `--prompts-version v3.2` | prompts + orchestrator | ⬜ not started |
| A.1 — `check_figure_provenance.py` per-arc distribution counter per DQ1 (D-084-A) | tool extension + tests | ⬜ not started |
| B — `slide_compose.v3.2_overlay.md` arc-transition guidance (D-084-B) per DQ3 | prompts | ⬜ folded into Tier A (same overlay file) |
| C — `deck_close` layout + composer + renderer + validator (D-084-C) per DQ2 | new layout end-to-end | ⬜ not started |
| D — `image_gen_decision.py` LLM-judge scope expansion to claim_evidence per DQ4 + prompt template technical-detail pull (D-084-D) | image-gen pipeline | ⬜ not started |
| E — Curator extension: `methods_provenance.md` frontmatter per DQ5 (D-084-E) + composer reads structured fields + new `methods_summary` layout (or extend existing) | curator + composer + renderer | ⬜ not started |
| F — smoke harness extends for v3.2 (`smoke_v3_prompt.py --version v3.2`) | smoke tool | ⬜ not started |
| G — live A/B re-run on ibd_phage_targeting | live (~$13) | ⬜ not started |
| H — live A/B re-run on functional_dark_matter | live (~$13) | ⬜ not started |
| I — Adam reads decks + scores metrics + casts veto | review + DECISION | ⬜ not started |
| J — docs (DECISIONS + RELEASE_NOTES + LAYOUT + SPEC per veto) | docs | ⬜ not started |
| K — closeout + auto-memory + tag (per veto) | paperwork + tag | ⬜ not started |

## Dep edges

```
Tier 0 → unlocks A + A.1 + C + D + E + F
Tier A (overlay) → Tier F (smoke needs v3.2 overlay)
Tier A + A.1 + C + D + E + F → Tier G/H (live runs need everything stable)
Tier G + H → Tier I (Adam read)
Tier I → Tier J + K (paperwork)
```

## Smoke gates

- **Tier 0 gate:** DQ1-DQ5 resolutions; C1 FDM root-cause
  documented; C2 per-slot audit findings logged (fix-or-defer
  per slot).
- **Tier A gate:** orchestrator accepts `--prompts-version v3.2`;
  v3.2 concat built at startup; smoke harness extended (Tier F)
  validates v3.2 fragment.
- **Tier A.1 gate:** per-arc distribution counter emits findings
  on a synthetic clustered fixture; passes on a synthetic
  well-distributed fixture.
- **Tier C gate:** `deck_close` layout validates; renderer
  produces a valid slide; validator detects missing/malformed
  deck_close on talks ≥18 slides (the STRONG-mode talk-30
  threshold; below that may not need synthesis).
- **Tier D gate:** image-gen judge approves ≥1 claim_evidence on
  a synthetic deck with technically-amenable bullets; rejects
  on a synthetic deck with vague/abstract bullets.
- **Tier E gate:** curator emits frontmatter on a synthetic
  project; composer reads structured fields; the synthetic
  methods slide enumerates the tiered fields correctly.
- **Tier F gate:** `smoke_v3_prompt.py --version v3.2` composes
  and validates against the v3.2 stack.
- **Tier G/H gate:** both runs end-to-end with all artifacts
  produced (FDM cascade incompleteness from v0.6 not recurring);
  per-arc placement metric meets DQ1 threshold on both decks.

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — DQ sign-off + C1 + C2 audit | 2-3h research + DECISIONS |
| A — v3.2 overlay + dispatcher + arc-transition guidance | 3-4h |
| A.1 — per-arc distribution counter + tests | 2-3h |
| C — deck_close layout end-to-end | 4-6h |
| D — image-gen judge scope expansion + prompt nudge | 3-5h |
| E — curator extension + composer + methods_summary layout | 4-6h |
| F — smoke extension for v3.2 | 1h |
| G — ibd v3.2 run | ~50min wall + ~$13 spend |
| H — fdm v3.2 run | ~50min wall + ~$13 spend |
| I — Adam read + veto | 30-60min Adam-time |
| J — docs | 1-2h (only if shipping) |
| K — closeout + tag | 30min (only if shipping) |
| **Total** | ~20-30h coding + ~$26 live + ~1h Adam-attention |

This is roughly 2× v0.6's coding estimate because v0.7 opens five
new design surfaces (vs v0.6's two main workstreams + infra
bundle). Consider scope-cutting if it grows beyond ~30h.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Per-arc rule over-constrains the composer — forces awkward figure placement when one arc legitimately has more figure-evidence than others | DQ1 (a) caps with "+1 unevenness slot" — strict but not rigid. If v0.7 live A/B surfaces over-constraint, relax to (b) variance-based at v0.8. |
| Arc-transition guidance in v3.2 overlay (DQ3 (a)) doesn't move LLM behavior — composer ignores it | Same belt-and-suspenders pattern from D-080 (prompt + validator): add a `tools/check_arc_transitions.py` cascade-integrated validator if Tier A smoke shows the overlay alone doesn't move metrics. |
| `deck_close` layout collides with existing final-substory C-slot conventions — composer produces two closers | Composer prompt rule: "if deck has a `deck_close` slide, final-substory C-slot is *advisory*, not summative." Validator: detects double-closure. |
| Image-gen claim_evidence scope expansion produces too many approvals → token spend grows | DQ4 (a) keeps strictness (≥3 distinct bullets only); judge's technical-specificity criterion is additional, not subtractive. Worst case: cap approved-per-deck at 4 (matches v0.6 max of 2 + new claim_evidence quota of 2). |
| Curator frontmatter extension (DQ5 (a)) breaks parsing for older projects without frontmatter | Read with graceful fallback: if frontmatter absent, composer falls back to v0.6 template behavior. Migration path: tools/migrate_methods_provenance.py to backfill frontmatter on existing projects. |
| FDM cascade-incompleteness (C1) recurs in v0.7 — diagnostic insufficient | C1 Tier-0 includes a *reproducer* requirement: must trigger the failure on a non-fdm project deliberately to confirm root cause. Bug is the v3.2-blocker if unfixed. |
| v0.6's per-slot template bug class (Lesson 4 / C2) hides another factual error in v0.7's new layouts | C2 audit happens at Tier 0 + every new layout in v0.7 (deck_close, methods_summary) gets a "factual-grounding test" — fixture with known ground truth + composer produces a slide; test pins expected content. |
| Scope creep — five workstreams + three carries is too much for one cycle | Tier 0 DQ resolution makes scope explicit. If Tier 0 reveals one workstream is bigger than estimated, drop a carry (C2 the most droppable) or push one workstream to v0.8. Don't ship a half-implemented v0.7. |

## What v0.7 does NOT do

- **No retraction-aware composer** (deferred to v0.8+).
- **No compression / mode-budget heuristics tuning** (still
  deferred; reassess with v0.7 data).
- **No new architectural pivots.** v3.2 is an overlay extension,
  not a redesign. The concat-overlay pattern (D-075) extends; no
  new prompt-pipeline surgery.
- **No new image-gen providers.** D-D extends judge scope, not
  the multi-provider layer.
- **No SPEC-wide schema rewrites.** The `deck_close` layout adds
  to the schema; curator frontmatter extends; everything else
  piggybacks.

## What ships at v0.7 closeout (conditional on veto)

If Adam-veto = SHIP:
- v0.7.0 tag.
- v3.2 prompts become opt-in via `--prompts-version v3.2`.
- Default `--prompts-version` may move to v3.1 (carrying v0.6's
  shipping-but-untagged state forward) or stay v2; v3.2 is the
  ship candidate Adam evaluates.
- DECISIONS D-085..D-08x for the v0.7 decisions.
- `tools/check_figure_provenance.py` extended; `tools/check_arc_
  transitions.py` blessed as a new P-validator (if Tier A
  needed it).
- RELEASE_NOTES + LAYOUT + SPEC updates.

If Adam-veto = DON'T SHIP:
- Same pattern as v0.5.1 D-079 + v0.6 D-084: work stays on main;
  no tag; v0.8 inputs captured.

## Ref

- `DECISIONS.md` D-084 (the v0.6 veto opening v0.7 scope).
- D-080 / D-081 (the figure-utilization contract v0.7 refines
  per-arc).
- D-075 / D-076 (the concat-overlay pattern v3.2 extends).
- D-066 / D-079 (Adam-veto-final pattern continuing at v0.7 cut-
  over).
- D-064 / D-008 (the image-gen slot semantics v0.7 expands).
- [[project-presentation-maker-v0-6]] (the v0.6 retrospective +
  v0.7 inputs).
- [[project-presentation-maker-v0-5-1]] (the v0.5.1 carries
  still relevant: retraction, compression).
- `prompts/slide_compose.v3.1_overlay.md` (the v0.6 overlay
  v3.2 stacks on).
- `tools/check_figure_provenance.py` (D-080 validator v0.7
  extends for per-arc).
- `image_gen_decision.py` (the M5b decision layer v0.7 expands).
- `merge_compose_fragments.py` (the curator-to-composer
  handoff v0.7 extends with frontmatter parsing).
