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

**Scope (5 workstreams + 3 carry items — Tier 0 resolved 2026-05-28; see DECISIONS D-085..D-091):**

1. **Per-arc figure-relevance rule + validator** (refines D-080;
   D-084-A → D-085). NOT budgeting. Per Adam Tier-0 DQ1: figures
   are paid-for at curator time, so use every relevant one; no
   budget caps.
   → `prompts/slide_compose.v3.2_overlay.md` adds the rule:
     *"if a curated figure is relevant to this arc's claim, USE
     IT (data_figure slide); do not relegate to bullets."* +
     anti-pattern "figure-as-bullet-citation."
   → `tools/check_figure_provenance.py` adds
     `relevant_figure_not_used` finding (P1 soft-warning): per
     substory, list curated figures whose NB-id matches the
     substory's analyses; for each, check if it appears as a
     data_figure slide. No distribution math; no per-arc caps.
   → D-080/D-081 utilization-rate retained as regression check.
2. **Arc transitions via substory_design** (D-084-B → D-087).
   Per Adam Tier-0 DQ3: substory_design owns cross-substory
   relationships, not slide_compose.
   → `prompts/substory_design.v3.2_overlay.md` (new — overlay
     on v1+v3 substory_design concat) instructs the LLM to emit
     `transition_from_prior: Optional[str]` per substory (null
     for substory 1). Free-text 1-2 sentence summary of what
     prior-arc claim this substory builds on.
   → `prompts/slide_compose.v3.2_overlay.md` instructs composer
     to use `transition_from_prior` when authoring the first
     non-Q slot of non-first substories. Soft preference, not
     inviolable.
   → Schema change: substory_design output adds optional
     `transition_from_prior` field; backward-compatible.
3. **Closing synthesis: new `deck_close` layout** (D-084-C →
   D-086). Per Adam Tier-0 DQ2: explicit new layout, not a
   variant or implicit final-C-slot.
   → New `deck_close` layout: `unified_point` (1-2 sentences),
     `key_takeaways` (3-5 bullets tying to each arc),
     `forward_call` (implication/next-step/open-question),
     `data_source` (cited substories/REPORT sections).
   → Curator stage produces `working/deck_close_signal.json`
     (or extends existing artifact) with structured fields
     drawn from substories + REPORT synthesis.
   → `slide_compose.v3.2_overlay.md` carries the authoring rule.
   → Renderer adds `_fill_deck_close` filler. Validator adds
     presence + field-shape checks. Position: final slide after
     final substory's C-slot + references/acknowledgments.
   → Gate: presence-required iff mode ≥ STRONG (lightning-5
     skips). Resolved at Tier C implementation.
4. **Image-gen scope expansion to claim_evidence with ≥3
   bullets** (D-084-D → D-088).
   → `image_gen_decision.py` LLM-judge eligibility gate expanded:
     `claim_evidence` slides with ≥3 distinct bullets ALSO
     eligible. Existing `big_idea` eligibility preserved. Other
     layouts remain ineligible.
   → Image-gen prompt-generator extended to pull substory
     analysis text (methods, statistics, mechanism vocabulary)
     when composing prompts for claim_evidence slides. New
     input contract: pass `02_substories.md` analysis text to
     prompt-generator.
   → Judge approval prompt gains "technical-specificity"
     criterion: reject generic/abstract; approve only on
     identifiable technical elements (labeled diagram panels,
     schematic mechanism illustration).
   → Cost cap: ≤4 approvals/deck (~$1.60 worst case).
5. **Narrow fix: `cross_tenant_integration` speaker_notes +
   title** (D-084-E → D-089). Per Adam Tier-0 DQ5: the bug is
   localized to this one layout's free-text fields, not a missing
   methods slot. C2 audit (D-091) confirmed no other vulnerable
   slots.
   → Signal extractor (`tools/extract_cross_tenant.py`) extends
     `cross_tenant_signal.json` with three new structured
     fields: `reference_databases: list[str]` (MIBiG, MetaCyc,
     GTDB, BRENDA detected via README/REPORT scan),
     `external_cohorts: list[str]` (HMP2 etc.), `notebook_count:
     int` (from `methods_provenance.md` / `02_substories.md`).
   → Composer agent (`cross_tenant.v1.md`) updated to read
     extended signal + produce title + speaker_notes that
     enumerate all four tiers (primary K-BERDL + reference +
     cohorts + notebook count). NO free-text invention.
   → New validator `tools/check_cross_tenant_grounding.py` (or
     extend existing) compares composed title/notes against
     structured signal; flags hallucinations + omissions as P1.
   → Broader `methods_summary` layout deferred to v0.8+ pending
     v0.7 Tier-F outcome.

**Deferred to v0.8+** (still real; not in v0.7 scope):

- **Retraction-aware composer / `discarded_results.md` filter** —
  no recurrence in v0.6. Deferral remains acceptable. If v0.7
  Tier-D/E surfaces retraction leakage in the read, moves to
  guaranteed v0.8 (no further deferral).
- **Compression / mode-budget heuristics** — ibd dropped 34→32 in
  v0.6; fdm 29→27. Closer to mode-budget compliance. Tune with
  v0.7 arc-transitions/synthesis data (more slides may shift
  compression behavior).

**Carry items in v0.7 (resolved at Tier 0 2026-05-28; see DECISIONS):**

- **C1: FDM cascade-interruption diagnostic → resumable cascade
  + checkpoint marker** (Lesson 5 from v0.6 retrospective; D-090).
  Tier-0 diagnostic (Explore subagent 2026-05-28): operator-side
  interruption HIGH CONFIDENCE. FDM `run-summary.json` has
  `exit_code: 1` (vs ibd's `0`); orchestrator killed
  (Ctrl-C/shell-close/signal) after merge/assemble but before
  cascade wrote artifacts. Cascade is "advisory rc=0 always" so
  it would write a stub on internal failure; complete absence =
  never finished or never started.
  → **v0.7 fix (D-090)**: (a) `stage_review_cascade` becomes
    idempotent — invokable standalone against an existing draft
    directory; (b) pre-cascade `audit/cascade-started.json`
    checkpoint + post-cascade `audit/cascade-completed.json`;
    (c) new CLI subcommand `presentation_maker.sh resume-cascade
    <draft-dir>`.
  → **Verification at Tier 0**: invoke `resume-cascade` against
    existing v0.6 fdm draft_6 directory; expect it to produce
    the three missing artifacts without re-running merge/assemble.
    Retroactively heals the v0.6 audit gap.
- **C2: Per-slot template under-specification sweep — DONE; bug
  localized** (Lesson 4 from v0.6 retrospective; D-091).
  Tier-0 audit (Explore subagent 2026-05-28): no other vulnerable
  slots beyond `cross_tenant_integration` speaker_notes + title.
  All other deck-spanning slots are placeholder-only (`title`,
  `acknowledgments`), structured-sourced (`references` from
  `citation_pool.json`, `methods_summary` from
  `methods_provenance.md`), or per-substory + Q/A/R/C-protected.
  → **No additional v0.7 fix needed beyond D-089 (cross_tenant
    narrow fix).** Lesson 4 stands as a design principle but the
    "structural class" framing was too broad — empirical sweep
    found one instance.
  → **Codified preventive pattern**: any NEW deck-spanning layout
    (including v0.7's `deck_close` per D-086) MUST source its
    factual fields from a structured signal artifact (`*_signal.json`)
    rather than free-text composition. D-086 already follows this
    pattern.
- **C3: Per-arc distribution metric design — OBSOLETE per D-085.**
  Adam Tier-0 DQ1: no figure budgeting; the v0.7-A rule is
  "use figure when relevant" with per-arc-relevance audit. No
  distribution math, no caps, no variance threshold. C3
  dissolved into D-085.

**Prompt versioning:** v3.2 overlay on v3.1 stack (D-075 pattern
extends again). v0.7 ships:
- `slide_compose.v3.2_overlay.md` (new — figure-relevance rule
  per D-085 + closing-synthesis guidance per D-086 + arc-transition
  usage per D-087).
- `substory_design.v3.2_overlay.md` (new — `transition_from_prior`
  emission per D-087; this is the cleaner-data-flow path Adam
  chose over slide_compose-only).
- Concat: `cat slide_compose.v2.md slide_compose.v3_overlay.md
  slide_compose.v3.1_overlay.md slide_compose.v3.2_overlay.md >
  audit/_prompts/slide_compose.v3.2.concat.md` (D-075 attention
  rule extends; v3.2 wins over v3.1 on conflicts). Same pattern
  for substory_design (`cat substory_design.v1.md
  substory_design.v3_overlay.md substory_design.v3.2_overlay.md`).
- `--prompts-version {v1,v2,v3,v3.1,v3.2}` flag adds v3.2.
- Smoke gate (D-076) extends: v3.2 requires fresh v3.2-smoke-pass
  (sha covers v2 + v3 overlay + v3.1 overlay + v3.2 overlay +
  substory_design v3.2 overlay — any change invalidates).

**Cut-over rule:** same as v0.5/v0.5.1/v0.6 (D-066, D-079, D-084
lineage). Adam-veto is final regardless of mechanical result.
Metric targets for v0.7 (revised per Tier-0 DQ resolutions):

- **`relevant_figure_not_used` finding count** (new metric per
  D-085): per substory, count curated figures whose NB-id
  matches the substory's analyses but which don't appear as
  data_figure slides. Target: 0 on both decks. v0.6 baseline:
  ibd had clustering (Adam's qualitative read; mechanically
  100% utilization counted breadth not depth).
- **Arc-transition presence** (new metric per D-087): % of
  non-first substories that have non-null `transition_from_prior`
  in substory_design output AND whose first non-Q slot
  references it in slide composition. Target ≥75% structural
  (presence of `transition_from_prior`); qualitative check
  at Tier-F on whether the composer used it meaningfully.
  v0.6 baseline = 0%.
- **Closing-synthesis present** (new metric per D-086, binary):
  deck has a `deck_close` slide when mode ≥ STRONG. Target =
  yes on both decks (talk-30 STRONG). v0.6 baseline = no.
- **Image-gen approvals on claim_evidence** (new metric per
  D-088): count of approved AI illustrations on
  claim_evidence-with-≥3-bullets slides. Target ≥1 on at least
  one substory where bullets are technically-amenable; cap at
  ≤4 approvals total per deck. v0.6 baseline = 0 (only big_idea
  approvals).
- **`cross_tenant_integration` factual accuracy** (qualitative
  + grounded; checked by `tools/check_cross_tenant_grounding.py`
  per D-089): slide enumerates primary K-BERDL + reference DBs
  (MIBiG/MetaCyc/GTDB/BRENDA when present) + external cohorts
  (HMP2 etc.) + correct notebook count; all four tiers match
  structured signal. Target: 0 hallucination + 0 omission
  findings. v0.6 baseline: title + speaker_notes wrong on ibd.
- **Cascade completion** (new metric per D-090): both decks
  produce all six cascade artifacts (review_cascade.json/.md,
  adversarial_review.json/.md, presentation_validation.json,
  no_artifact_refs.json/.md, deck_reconciliation.json/.md,
  quantitative_grounding.json/.md). Both decks have
  `cascade-completed.json` checkpoint. Target = 100% on both.
  v0.6 baseline = ibd complete; fdm missing 3 of 6.
- **Figure-utilization regression check** (must hold from
  v0.6): ≥70% rate on D-081's strict counting (v0.6 was 100%
  on both).
- **Schema errors regression check** (must hold): 0 on both
  decks.

## DQs resolved at Tier 0 sign-off (2026-05-28)

All seven DQs resolved 2026-05-28. See DECISIONS.md D-085..D-091
for the full rationale + alternatives considered. Summary:

| DQ | Decision | Anchor |
|---|---|---|
| DQ1 (figure rule) | NO budgeting. Rule "use figure when relevant" + per-arc-relevance audit (P1 soft-warning on `relevant_figure_not_used`). Adam-redirect: figures paid for at curator time, no scarcity. | D-085 |
| DQ2 (closing synthesis) | New `deck_close` layout with explicit fields (unified_point / key_takeaways / forward_call / data_source). Curator emits structured signal; composer reads it. | D-086 |
| DQ3 (arc transitions) | `substory_design.v3.2` overlay adds `transition_from_prior` field per substory. slide_compose uses it for first non-Q slot of non-first substories. | D-087 |
| DQ4 (image-gen scope) | `claim_evidence` with ≥3 distinct bullets becomes eligible; prompt-generator pulls technical detail from substory analyses; judge gets "technical-specificity" criterion. Cap ≤4 approvals/deck. | D-088 |
| DQ5 (methods slot) | Narrow: extend `cross_tenant_signal.json` with reference_databases + external_cohorts + notebook_count; composer reads structured fields for title + speaker_notes; new validator. Broader `methods_summary` layout deferred to v0.8+. | D-089 |
| C1 (cascade resumability) | Re-runnable `stage_review_cascade` + pre-cascade `cascade-started.json` checkpoint + `resume-cascade <draft-dir>` CLI subcommand. Tier-0 verification: invoke against existing v0.6 fdm draft_6 to heal the audit gap. | D-090 |
| C2 (per-slot sweep) | Audit found bug localized to `cross_tenant_integration`; no other vulnerable slots. D-089 fully covers v0.7 scope. Codified preventive pattern for future layouts (must source from structured signal artifact). | D-091 |

<details>
<summary>Original DQ language (kept for historical reference)</summary>

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

</details>

## Per-tier scope

| Tier | Scope | Status |
|---|---|---|
| 0 — DQ1-DQ5 + C1 + C2 sign-off | research + DECISIONS | ✅ done 2026-05-28 (D-085..D-091 in DECISIONS.md; 4 DQs answered + 1 redirected by Adam; 2 carries diagnosed via Explore subagents — C1 root-caused as operator-side interruption, fix is D-090 resumable cascade + checkpoint; C2 audit found bug localized to cross_tenant_integration, no other vulnerable slots — D-091; methods scope narrowed to D-089). Pending: verification step at C1 (invoke `resume-cascade` against v0.6 fdm draft_6 once D-090 ships in Tier A.2). |
| A — `slide_compose.v3.2_overlay.md` figure-relevance rule (D-085) + dispatcher + `--prompts-version v3.2` | prompts + orchestrator | ⬜ not started |
| A.1 — `check_figure_provenance.py` extends with `relevant_figure_not_used` finding per D-085 | tool extension + tests | ⬜ not started |
| A.2 — `stage_review_cascade` idempotent + checkpoint marker + `resume-cascade` CLI per D-090 | orchestrator + tool | ⬜ not started |
| B — `substory_design.v3.2_overlay.md` + `transition_from_prior` schema extension + slide_compose v3.2 usage per D-087 | prompts + schema | ⬜ not started |
| C — `deck_close` layout end-to-end per D-086: curator emits `deck_close_signal.json` + new layout in SPEC/LAYOUT + composer + renderer `_fill_deck_close` + validator presence-check (gate: mode ≥ STRONG) | new layout end-to-end | ⬜ not started |
| D — `image_gen_decision.py` eligibility expansion to claim_evidence ≥3 bullets per D-088 + prompt-generator pulls substory analysis text + judge "technical-specificity" criterion + cost-cap ≤4/deck | image-gen pipeline | ⬜ not started |
| E — `extract_cross_tenant.py` signal extension (reference_databases + external_cohorts + notebook_count) + `cross_tenant.v1.md` composer agent reads extended signal + new `tools/check_cross_tenant_grounding.py` validator per D-089 | extractor + composer + validator | ⬜ not started |
| F — smoke harness extends for v3.2 per existing D-080/D-076 pattern (`smoke_v3_prompt.py --version v3.2`) | smoke tool | ⬜ not started |
| G — live A/B re-run on ibd_phage_targeting | live (~$13) | ⬜ not started |
| H — live A/B re-run on functional_dark_matter (and verify resume-cascade healed the v0.6 audit gap retroactively) | live (~$13) | ⬜ not started |
| I — Adam reads decks + scores metrics + casts veto | review + DECISION | ⬜ not started |
| J — docs (DECISIONS + RELEASE_NOTES + LAYOUT + SPEC per veto) | docs | ⬜ not started |
| K — closeout + auto-memory + tag (per veto) | paperwork + tag | ⬜ not started |

## Dep edges

```
Tier 0 → ✅ unlocks A + A.1 + A.2 + B + C + D + E + F
Tier A (overlay) → Tier F (smoke needs v3.2 overlay)
Tier B (substory_design v3.2 + schema change) → Tier C (deck_close composer may reference transition fields)
Tier A.2 (resumable cascade) → can verify against existing v0.6 fdm draft_6 anytime (heals audit gap retroactively)
Tier A + A.1 + A.2 + B + C + D + E + F → Tier G/H (live runs need everything stable)
Tier G + H → Tier I (Adam read)
Tier I → Tier J + K (paperwork)
```

## Smoke gates

- **Tier 0 gate:** ✅ DQ1-DQ5 + C1 + C2 resolved (D-085..D-091).
- **Tier A gate:** orchestrator accepts `--prompts-version v3.2`;
  v3.2 concat built at startup (stack: v2 + v3 + v3.1 + v3.2);
  smoke harness extended (Tier F) validates v3.2 fragment.
- **Tier A.1 gate:** `relevant_figure_not_used` finding emitted on
  a synthetic fixture where a curated figure's NB-id matches a
  substory's analyses but the substory composes only bullets for
  that figure's content. Passes on a synthetic fixture where the
  substory composes a data_figure slide for the matched figure.
- **Tier A.2 gate:** `presentation_maker.sh resume-cascade` against
  the existing v0.6 fdm `draft_6/` directory produces the three
  missing artifacts (review_cascade.json, adversarial_review.*,
  presentation_validation.json) without re-running merge/assemble.
  `cascade-started.json` + `cascade-completed.json` both written.
- **Tier B gate:** substory_design v3.2 emits `transition_from_prior`
  field on a synthetic multi-substory fixture; backward-compatible
  on older specs without the field (renders as before).
- **Tier C gate:** `deck_close` layout validates with the new
  fields; renderer produces a valid slide; validator detects
  missing `deck_close` on talks ≥18 slides (STRONG-mode threshold);
  skips presence-check on lightning-5.
- **Tier D gate:** image-gen judge approves ≥1 claim_evidence on
  a synthetic deck with technically-amenable bullets (≥3 distinct);
  rejects on a synthetic deck with vague/abstract bullets. Cost-
  cap enforced (≤4 approvals/deck max).
- **Tier E gate:** `extract_cross_tenant.py` emits
  reference_databases + external_cohorts + notebook_count on the
  ibd project README/REPORT/methods_provenance.md (expect to find
  MIBiG, MetaCyc, GTDB, BRENDA in reference_databases; HMP2 in
  external_cohorts; 32 notebooks). Composer reads extended signal;
  validator catches a synthetic hallucination (DB named in title
  not in signal) and a synthetic omission (DB in signal not in
  title).
- **Tier F gate:** `smoke_v3_prompt.py --version v3.2` composes
  the v3.2 stack + validates against v2 schema requirements.
- **Tier G/H gate:** both runs end-to-end with all six cascade
  artifacts produced on BOTH decks (no recurrence of v0.6 fdm
  interruption class); 0 `relevant_figure_not_used` findings;
  ≥1 image-gen approval on a claim_evidence slide on at least
  one deck; `deck_close` present on both decks (talk-30 STRONG);
  0 `cross_tenant_grounding` findings on both decks.

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — DQ sign-off + C1 diagnostic + C2 audit | ✅ done (~1.5h, lower than estimated thanks to parallel Explore subagents) |
| A — v3.2 overlay (figure-relevance rule) + dispatcher + `--prompts-version v3.2` | 2-3h |
| A.1 — `relevant_figure_not_used` finding in `check_figure_provenance.py` + tests | 2-3h |
| A.2 — Resumable cascade + checkpoint marker + `resume-cascade` CLI per D-090 | 2-3h |
| B — substory_design v3.2 overlay + `transition_from_prior` schema + slide_compose usage | 3-4h |
| C — `deck_close` layout end-to-end (curator signal + SPEC/LAYOUT + composer + renderer + validator) | 4-6h |
| D — image-gen judge scope expansion + prompt-generator substory-text pull + technical-specificity criterion + cost-cap | 3-5h |
| E — `extract_cross_tenant.py` extension + composer agent update + `check_cross_tenant_grounding.py` validator (narrower scope than original D-084-E framing) | 2-3h |
| F — smoke extension for v3.2 | 1h |
| G — ibd v3.2 run | ~50min wall + ~$13 spend |
| H — fdm v3.2 run | ~50min wall + ~$13 spend |
| I — Adam read + veto | 30-60min Adam-time |
| J — docs (only if shipping) | 1-2h |
| K — closeout + tag (only if shipping) | 30min |
| **Total** | ~20-30h coding + ~$26 live + ~1h Adam-attention |

Coding total roughly matches the original estimate. Tier E
narrowed (~2-3h vs original 4-6h) offset by adding Tier A.2 (~2-3h
for resumable cascade) — net wash. Tier 0 actuals (~1.5h) came in
under estimate via parallel subagent diagnostics.

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
