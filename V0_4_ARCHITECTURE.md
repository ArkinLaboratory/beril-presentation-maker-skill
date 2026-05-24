# beril-presentation-maker — v0.4 Architecture Memo

**Status:** SIGNED OFF — M0 complete 2026-05-12. **M1 shipped 2026-05-21. v0.4.1 revision 2026-05-23 — M2 reshaped to "M2-lite" (shared-outline call): see §20, which supersedes §6, §7.2, the §10.1 phase enum, and decisions D-031 / D-032. M2-lite shipped 2026-05-23 (`deck_outline.v1` + `parse_deck_outline.py` + orchestrator wiring); M3 next.**
**Scope:** architectural pivot from per-substory drafting to
deck-architect-then-parallel-compose. Not a punch list; not code.
**Relationship to existing docs:**
- Extends `SPEC.md` (v0.1 design rationale) for the pipeline layer.
  SPEC.md §§1–3 (purpose, design premises, inputs), §6 (slide-shape
  vocabulary), §8 (figure handling), §13 (validators P1–P10), §14
  (assembly), §15 (posters), §18 (adversarial coupling) remain
  authoritative. v0.4 changes the *drafting pipeline* and *review
  cascade*, not the product mission or output format.
- Distinct from `V0_4_0_PUNCH_LIST.md`, which tracks v0.3.x trailing
  work (image-gen calibration, prompt anti-patterns, worker-pool
  parallelization, state.json refactor). The punch list's C1
  (worker-pool parallelization, ~6–8h, "biggest wall-clock win")
  and C2 (state.json + phase enum refactor, ~1.5–2 days,
  "architectural") are *enabled and load-bearing* for v0.4 — the
  punch list framed them as standalone wins; v0.4 reframes them as
  consequences of the deck-architecture pivot.
- Sister-skill reference: paper-writer `SPEC_v0_8.md` (currently at
  M1 §A1). v0.4 borrows the subtraction-over-addition frame and the
  fail-fast tiered cascade pattern from there, but the architectural
  pivot is presentation-specific (architect-then-compose, not single
  holistic call).

This document is *what* v0.4 does and *why*. The *how* (package layout
deltas, file paths, state schema details, CLI surface changes) is
captured per-milestone in `LAYOUT_v0_4.md` (M1 deliverable) and pinned
in `DECISIONS.md` as v0.4 entries (D-030+) land.

---

## 1. Why v0.4 — three converging signals

### 1.1 Per-substory sprawl is now measurable

Every v0.3.x release patched a per-substory symptom: register drift
between substories (v0.3.1 layout reorg), figure-resolution path drift
(v0.3.2.1 backwards-compat shim), image-gen budget overshoot
(v0.3.7 image-gen LLM-judgment layer), process-detail bleed in speaker
notes (v0.3.8 post-checker). The pattern matches paper-writer's
v0.4→v0.7.x cycle exactly (`SPEC_v0_8.md` §1.1) — each patch closes
one symptom of the same upstream weakness: per-substory composition
runs without seeing what the rest of the deck is doing.

The diagnosis transferred from paper-writer is now backed by a
quantitative finding on a real talk (`V0_4_0_PUNCH_LIST.md` gap
analysis from `audit/runs/run-3/summary.json` on `ibd_phage_targeting`):
**per-substory fan-out (stages 3–10) is 80% of wall-clock and 86% of
cost.** Six independent LLM calls (`slide_compose-S{1,2,3}` +
`speaker_notes-S{1,2,3}`) run sequentially today, and each one operates
on a slice of the project without the others' context. That's both
the largest engineering opportunity (parallelism) and the largest
quality opportunity (coordination via shared artifact).

### 1.2 Paper-writer v0.8's frame — but adapted

`SPEC_v0_8.md` collapses per-section drafting into one holistic Opus
4.6 call. The IBD one-shot exercise (paper-writer §1.3) showed an LLM
seeing the whole project at once produces better integrative biology
than per-section prompts knitting localized claims together.

The presentation-maker analogue does **not** copy that move directly.
Slide decks are deliberately atomic — each slide must hold up on its
own visual surface, and the cross-slide arc rides on `section_divider`
+ `big_idea` punchlines, not on paragraph-level connective tissue
between sequential prose blocks. The case for a single holistic
deck-compose call is structurally weaker than the case for a single
holistic paper-pass.

What transfers is the *architectural insight* one level higher: lift
the cross-cutting decisions to an agent that sees the whole, and let
the localized composition agents work in parallel against that
shared artifact. The cross-cutting decisions in a deck are: slide
sequence, layout dispatch, image and diagram intent, transition
placement, claim and citation assignment to slide. Composition
(bullet wording, exact punchline phrasing, figure path resolution,
speaker-notes drafting) stays where it is — but with the architecture
as input rather than as emergent coordination.

### 1.3 V0_4_0_PUNCH_LIST C1+C2 want this anyway

Two items from the trailing punch list pointed at this pivot without
naming it:

- **C1 — Per-substory worker-pool for `slide_compose` + `speaker_notes`.**
  Estimated 60–90 min wall-clock saved per draft. The punch list
  flagged "bash worker-pool patterns are fragile under concurrent LLM
  calls; needs careful test design" — but the deeper friction is
  *coordination*, not *concurrency*. Concurrent per-substory composers
  that each invent their own punchline cadence, image budget, and
  transition slots produce a less coherent deck. The deck-architecture
  artifact is the coordination layer that makes parallelism safe.
- **C2 — state.json + phase enum refactor.** Today's state machine
  has `plan → throughline_pick → substory_approval → drafting →
  review → assembled` (`LAYOUT.md` §6 + `SPEC.md` §16.1). v0.4's
  pipeline introduces a deck-architecture phase between
  `substory_approval` (subsumed) and parallel composition. The
  state.json refactor is no longer a parity-with-paper-writer
  cleanup item; it's the v0.4 phase-enum implementation.

C1 and C2 are subordinate items inside the v0.4 work, not standalone
wins to schedule independently. Reframing them as such avoids the
trap of paying the parallelism cost (concurrency complexity, test
design) without paying the architecture cost (the coordination
artifact) — the two halves of the answer.

---

## 2. Design premises (delta from SPEC §2)

The six SPEC §2 premises (honesty, auditability, visual coherence,
user judgment over LLM judgment, bounded cost, reuse over generation)
carry forward unchanged. v0.4 adds two:

7. **Subtraction over addition.** v0.3.x complexity is patching
   downstream symptoms of upstream coordination failure. The v0.4
   simplification mostly removes prompts; the only net-new prompt
   is `deck_architect.v1.md`. Tooling investment (`claim_inventory.py`
   port from paper-writer; light additions to `state.py`) is the
   only net-new engineering on the Python side. The bash orchestrator
   shrinks (parallel composition reduces serialization bookkeeping).
8. **Architecture-as-coordination.** Per-substory composition runs
   in parallel against a fixed deck-architecture contract. The
   architect agent is the single source of cross-cutting truth
   (slide sequence, layout dispatch, image budget, transitions);
   composers cannot deviate without a defined contract path. This
   trades flexibility for coherence — accepted because today's
   pipeline already pays in coherence to gain flexibility we don't
   exercise.

The "user judgment over LLM judgment" premise (SPEC §2 premise 4)
gets a new locus: the user reviews the deck-architecture artifact at
the deck-architecture-approval gate (§5 below), and that becomes the
second load-bearing gate (after throughline pick). The substory-
approval gate (today's second gate, D-002 rev1) is absorbed.

---

## 3. Pipeline overview — the 6-phase architecture

```
Project artifacts (REPORT, RESEARCH_PLAN, notebooks, figures, references.md)
   │
   ▼
[Phase 0]   Deterministic + LLM-only tooling (run-once per project, idempotent)
   │       ├── citation_pool/pool.json      (existing; reuse from paper-writer if present)
   │       ├── figures shortlist            (existing: curate_figures.py)
   │       ├── cross_tenant_signal.md       (existing: extract_cross_tenant.py)
   │       ├── claim_inventory.tsv          (NEW via extract_claims.py adapter:
   │       │                                  claude -p extract_claims.v1.md
   │       │                                  → validate_claim_inventory.py)
   │       └── methods_provenance.md        (NEW: vendored extract_methods.py)
   ▼
[Phase 1]   Throughline pick (INTERACTIVE — load-bearing user gate, unchanged)
   │       Output: 00_throughline.md per existing throughline.v1 prompt.
   ▼
[Phase 2]   Deck architect (NEW — INTERACTIVE — load-bearing user gate)
   │       One LLM call; emits 01_deck_architecture.json.
   │       Absorbs plan.v1 + substory_design.v1 roles.
   │       User reviews and approves; on amend, re-emit until approval.
   ▼
[Phase 3]   Per-substory composition (PARALLEL)
   │       N independent slide_compose.v1 calls (one per substory),
   │       reading the deck-architecture artifact + their assigned
   │       slide slots. Output: per-substory compose-fragment.v1 JSONs.
   │       Speaker-notes drafting runs in the same per-substory worker
   │       (one Claude call per substory writes compose + notes seeds).
   ▼
[Phase 4]   Tiered review cascade (fail-fast)
   │       ├── Tier 1: deterministic post-checkers + validators (~$0.01).
   │       │           Cap 1 pass; failures route to targeted re-compose.
   │       ├── Tier 2: Haiku light reviewer (~$0.05). Cap 1 pass.
   │       └── Tier 3: canonical beril-adversarial --type presentation
   │                   (~$0.50–$1.50). Cap 1 pass; retries P0 only.
   ▼
[Phase 5]   Assembly (existing)
   │       slide_spec.json → pptx → optional pdf via python-pptx +
   │       LibreOffice (existing assemble_pptx.py path).
   ▼
[Optional] revise verb (post-assembled, existing)
            Per-slide / per-substory revision with semantic-invariance
            post-check (NEW; modeled on paper-writer SPEC §11.2).
```

Each phase has: an idempotent contract, a `state.json` checkpoint, an
`audit/` artifact, and a halt-to-handoff failure path that preserves
the v0.3.6+ parser-facing `.handoff.json` shape.

---

## 4. Phase 0 — Deterministic tooling

Phase 0 is the load-bearing competitive advantage shared with
paper-writer. v0.4 inherits four artifacts from existing v0.3.x
tooling and adds two new dependencies (claim_inventory.py +
extract_methods.py, both ported from paper-writer).

### 4.0 Two work modes — paper exists vs. no paper

Per SPEC §3.2 (paper-writer output reuse via `--ignore-paper` opt-out)
and D-009: presentation-maker has two work modes. Adam confirmed
2026-05-12 that the no-paper case is *not* a fallback — it's an
equal-standing primary workflow (originally the only one). The v0.4
architecture must serve both.

**Artifact-by-artifact provenance:**

| Artifact | Paper exists | No paper | Cost delta no-paper |
|---|---|---|---|
| `citation_pool.json` | Reuse `papers/draft_N/citation_pool.json` | Originate via `citation_pool.py` + `citation_pool.v1.md` literature scan | +$0.80–$2.50, +3–8 min |
| `00_throughline.md` | Optionally seed from `papers/draft_N/00_throughline.md` (`--throughline auto-from-paper`); user gate still runs | Originate via `throughline.v1` from REPORT + PLAN + notebooks (today's default) | ~$0 (same Sonnet pass) |
| `claim_inventory.tsv` | Reuse `papers/draft_N/claim_inventory.tsv` if exists and REPORT.md hash matches | Originate via `extract_claims.py` adapter: `claude -p extract_claims.v1.md` → `validate_claim_inventory.py` (M1 active-path vendor per D-040-rev1) | +$0.05–$0.10 (LLM call only; validator is deterministic) |
| `methods_provenance.md` | Reuse `papers/draft_N/methods_provenance.md` | Originate via vendored `extract_methods.py` (M1 port) | $0 (deterministic AST), +1–2 min |
| `curated_figures.md` | Reuse paper-writer's curated subset as seed; talk-mode trims further | Originate via `curate_figures.py` (standalone today) | ~$0 (same Sonnet pass) |
| `cross_tenant_signal.md` | Always originate via `extract_cross_tenant.py` (no paper-writer equivalent) | Same — always originate | ~$0 (same) |

**Storage layout — per-draft directories, one-way read for reuse.**
paper-writer writes to `projects/<id>/papers/draft_N/` (per
paper-writer `SPEC_v0_8.md §4.7`: "All Phase-0 artifacts live in
`papers/draft_N/`, not at the project root. Different drafts may
want different inventories"). presentation-maker writes to
`projects/<id>/talks/draft_N/` (per `LAYOUT.md §5`). The cross-skill
reuse pattern at D-009 is *one-way read* — presentation-maker reads
`papers/draft_*/<artifact>` if present; never writes there. Neither
skill writes to a shared location. No concurrency lock concern;
panel-of-one team makes concurrent invocation unrealistic in
practice.

**Repo-fusion / shared-cache as v0.5+ consideration (not v0.4 work).**
Some artifacts in the §4.0 table are *project-data-level*, not
draft-level — `claim_inventory.tsv` and `methods_provenance.md`
depend on REPORT.md and notebooks, not on draft-tier or audience
choices. These are candidates for migrating upward to
`projects/<id>/<artifact>` for true cross-skill sharing without
duplication. The design decision needs cross-skill alignment with
paper-writer (whose §4.7 explicitly defends the per-draft pattern
on the grounds that different drafts may pick different claim_id
subsets). v0.4 preserves the per-draft pattern unchanged; the
shared-cache question is deferred to v0.5 or to a joint paper-writer
v0.9 / presentation-maker v0.5 design pass.




### 4.1 citation_pool.json (KEPT — existing)

Reuse-from-paper-writer if `papers/draft_*/citation_pool.json`
exists (D-009). Otherwise built from scratch by `citation_pool.py` +
`citation_pool.v1.md`. No change.

### 4.2 Figure shortlist (KEPT — `curate_figures.py`)

Curated figure list with caption candidates. Output goes to
`curated_figures.md`. No change. The architect consumes this as input;
composition consumes it for figure path resolution.

### 4.3 cross_tenant_signal.md (KEPT — `extract_cross_tenant.py`)

Regex+LLM scan for tenant/DB/sibling-project signal. No change.
Surfaces in the architecture's `cross_tenant` slide intent.

### 4.4 claim_inventory.tsv (NEW — paper-writer active-path vendor per D-040-rev1)

Every numeric assertion in `REPORT.md`, demarcated and tied to its
notebook source (NB#:cell) and its supporting figure if any, with
`effect_size_present` / `ci_present` / `pvalue_present` boolean flags.

**Production path (M1 shipped 2026-05-12):** `extract_claims.py` adapter
invokes `claude -p` with system prompt `extract_claims.v1.md` (40-line
LLM prompt) reading `REPORT.md` + `methods_provenance.md`, emitting the
TSV. Then chains `validate_claim_inventory.py` (Stage 1 Tier C validator
from paper-writer, ~241 LOC) which clears LLM-fabricated `source_notebook`
paths (~10% fabrication rate observed in paper-writer draft_3). The
validator step is NOT optional in production.

**Why LLM-only extraction, not regex+demarcation:** paper-writer's M1
§B1 originally shipped a regex+LLM-demarcation tool (`claim_inventory.py`,
~2400 LOC). Their `STAGED_IMPROVEMENT_PLAN.md` Stage 1 (closed
2026-05-11, one day before our v0.4 M0) deferred this tool from the
active pipeline in favor of LLM-only extraction: *"the agent-built
Python orchestrator + holistic-draft prompt + LLM-only Phase-0
extraction is the right shape. The M1 regex-catalog work (B1.b–B1.h)
was over-engineered for this scope."* Presentation-maker M1 vendors
the simpler active path per D-040-rev1. The deferred tool is NOT
vendored at v0.4; if LLM-extraction quality issues surface in
presentation-maker (the same risk paper-writer's `claim_inventory.py`
was originally built to address), re-vendor at v0.5.

This is the single largest Phase-0 quality lever the v0.8 paper-writer
work surfaced.

**Why it transfers.** Today the `big_number` and `claim_evidence`
layouts pick their headline statistic from REPORT.md prose with no
programmatic guarantee that the chosen number has a CI or p-value
attached. P3 (numeric provenance, `SPEC.md` §13) runs post-composition.
The architect can do better: assign `claim_id`s to slide slots
*before* composition, and constrain `big_number` slots to claim_ids
where `effect_size_present == yes` OR `ci_present == yes`. That's a
constructive constraint at architecture time, not a post-hoc validator.

**Implementation strategy.** Vendor `claim_inventory.py` and the
`claim_demarcate.v1.md` prompt from
`spike/beril-paper-writer-skill-draft/`. The artifact is project-data-
level, not paper-genre-specific, so the demarcator's batched-retry
machinery (D-038/039/040 in paper-writer) ports without change. Skip
the discrepancy_register.py port — that's paper-Methods-and-Limitations
specific (per the v0.3 critique memo, §"What does not transfer").

**Cost.** $0.50–$1.50 per project (deterministic Python + Haiku
batched demarcation pass for multi-numeric sentences). Idempotent; if
the upstream artifact at `projects/<id>/claim_inventory.tsv` exists
and REPORT.md is unchanged, skip.

**M1 deliverable.** Vendored, tests pass against
`ibd_phage_targeting`, smoke against `functional_dark_matter`. ~400
LOC new in presentation-maker's `tools/` plus a thin Python wrapper to
share the demarcator artifact between sibling skills.

### 4.5 methods_provenance.md (NEW — port `extract_methods.py` from paper-writer)

**Why this changed from "reuse only" to "vendor + reuse" between
memo v1 and v2.** Memo v1 said: if paper exists, reuse;
otherwise architect does ad-hoc notebook grep+read. Adam's 2026-05-12
question on no-paper mode surfaced this gap: "grep+read at architect
runtime" is exactly the kind of ad-hoc grounding paper-writer's Phase 0
deterministic tooling exists to prevent. The `methods_summary` slide
is one of the 15 named layouts (SPEC §6) and is required at every
talk mode; the architect should pre-allocate methods bullets from a
structured artifact, not invent them from raw notebook reading.

**Implementation strategy.** Vendor `extract_methods.py` from
`spike/beril-paper-writer-skill-draft/`. The AST-based notebook
scanner is ~300 LOC; tests port without change. Add to M1 scope
alongside `claim_inventory.py` (M1 becomes a two-tool port).

**Idempotent reuse.** If `projects/<id>/methods_provenance.md`
exists and the notebook set hashes match the artifact's recorded
hashes, skip; otherwise run.

**Cost.** ~$0.10 + 1–2 min per project in no-paper mode (Haiku +
AST extraction). $0 in paper-exists mode (reuse).

**M1 deliverable (extended).** Both `claim_inventory.py` AND
`extract_methods.py` vendored, tested against `ibd_phage_targeting`
in no-paper mode, smoke against `functional_dark_matter`.
~700 LOC total + ~60 tests across both tools.

### 4.6 Phase-0 idempotency contract

> **Path correction (2026-05-14, M1 Tier C ship).** This section's
> M0 draft put Phase-0 artifacts at `talks/draft_N/00_phase0/` —
> draft-root level. That broke `draft_paths.py`'s 4-zone discipline
> (top of `draft_N/` has exactly four entries: `deliverable/`
> `narrative/` `working/` `audit/`). Adam signed off `working/00_phase0/`
> on 2026-05-12; M1 Tier C shipped it there. The list below is
> corrected. Also corrected: M1 Tier C's `phase0_reuse.py` routes only
> the **two new v0.4 artifacts** (`methods_provenance.md`,
> `claim_inventory.tsv`); the other three Phase-0 artifacts keep their
> existing v0.3.x `working/` locations and their own writers — the
> M0 draft over-claimed by lumping all five into `00_phase0/`.
> Five-artifact unification under one helper is deferred to v0.5
> (M1_PUNCH_LIST.md Tier F).

Phase-0 artifacts live under `projects/<id>/talks/draft_N/` per the
v0.3.1+ 4-zone per-draft layout (`LAYOUT.md §5`; canonical source
`tools/draft_paths.py`). The reuse-from-paper-writer pattern at D-009
reads from `projects/<id>/papers/draft_*/` but never writes there.

Within a talk draft, Phase-0 artifacts written:

*Routed by `phase0_reuse.py` (M1 Tier C) — reuse-or-originate:*
- `working/00_phase0/methods_provenance.md` (copied from `papers/draft_M/` on reuse, or originated via `extract_methods.py`)
- `working/00_phase0/claim_inventory.tsv` (copied on reuse, or originated via `extract_claims.py`)

*Pre-existing v0.3.x artifacts — own writers, own `working/` locations (NOT routed through `phase0_reuse.py` at v0.4):*
- `working/citation_pool.json` (`citation_pool.py`; reuse logic via `state.json.paper_writer_reuse`)
- `working/curated_figures.md` (`curate_figures.py`)
- `working/cross_tenant_signal.{md,json}` (`extract_cross_tenant.py`)

*Invocation record:*
- `audit/phase0.jsonl` (per-tool record; `phase0_reuse.py` + `extract_claims.py` both append; `tool` field distinguishes)

Hash-cache: rerun Phase 0 with unchanged input hashes is a no-op
(`phase0_reuse.py` stamps current input hashes into `audit/phase0.jsonl`
and compares against the most-recent stamp on re-invocation; matched +
artifact present → no-op). The cache is per-draft; cross-draft sharing
within a project is explicitly *not* done in v0.4 (deferred per §4.0
closing paragraph).

---

## 5. Phase 1 — Throughline pick (unchanged)

The throughline-pick gate (D-002, SPEC §4) is the first load-bearing
user gate and stays as-is. `throughline.v1.md` produces 2–3 candidate
meta-arcs with evidence maps; user picks via the slash-command halt
pattern (v0.3.6). `00_throughline.md` is written; `state.phase`
advances to `deck_architect`.

`--throughline auto` continues to opt into the highest-evidence-
density candidate.

---

## 6. Phase 2 — Deck architect (NEW)

> **SUPERSEDED 2026-05-23 (v0.4.1 revision — see §20).** The
> heavyweight "deck architect" in this section — the rigid
> `01_deck_architecture.json` contract, the `deck_architecture.py`
> schema validator, `check_architecture_drift.py`, the six
> architecture-time validators (§8.3), the Opus model (D-031), and the
> `deck_architecture_pick` user gate (§6.7) — is replaced by the
> lighter **M2-lite "deck-outline call"** defined in §20. The
> 2026-05-23 outline probe (`experiments/m2-outline-probe/`) showed
> the coordination gains come from terse explicit *prescriptions*, not
> from a rigid per-slide contract. §6 is retained as the M0 design
> record; §20 is authoritative for M2.

### 6.1 What this phase does

One LLM call. Input: all Phase-0 artifacts + the approved
`00_throughline.md` + mode + tier. Output: a single
`01_deck_architecture.json` that fixes the deck skeleton — slide
sequence, layout per slide, substory assignment, image/diagram intent,
claim assignments, citation pre-allocations, transition slot
placements.

This phase absorbs the roles of `plan.v1` (triage + mode-tier match)
and `substory_design.v1` (substory clustering). It does NOT absorb
`throughline.v1` (the load-bearing user gate stays where it is).

### 6.2 Why one call, not the per-substory loop

The cross-cutting decisions an architect must make — where transitions
help, what AI-illustration budget to allocate across the deck, which
substory gets the `big_number` headline slot — require seeing the
whole deck at once. Per-substory composition cannot make these calls
because it doesn't see what happens before or after its own substory.
Today's pipeline pushes these decisions onto the orchestrator's
mechanical heuristics (one section_divider per substory, AI-illustration
flagging inside slide_compose with no deck-level budget awareness),
which is why AI-illustration count varies wildly between drafts
(v0.3.7's image-gen LLM-judgment patch addressed half of this problem
at the slide layer; the other half is deck-level budgeting).

### 6.3 System prompt budget

≤400 lines (~12K tokens). Replaces the cumulative budget of
`plan.v1.md` + `substory_design.v1.md` (~250 + ~300 = ~550 lines).
Architect is a more sophisticated agent than either; the prompt
should grow but not by 5×.

### 6.4 Inputs the architect consumes

| Artifact | Role |
|---|---|
| `00_throughline.md` | The narrative skeleton; central claim and evidence map |
| `claim_inventory.tsv` | Every numeric claim available with flags; constrains big_number / claim_evidence slot assignments |
| `curated_figures.md` | Available figures with caption candidates; constrains data_figure / claim_evidence slot assignments |
| `cross_tenant_signal.md` | Cross-tenant slide content (mandatory per SPEC §7) |
| `citation_pool.json` | Available citations; pre-allocated to slide slots in the architecture |
| `methods_provenance.md` | Constrains methods_summary slot content |
| Mode + tier | Slide budget caps + register expectations |

### 6.5 Output contract: 01_deck_architecture.json

```json
{
  "schema_version": "deck-architecture.v1",
  "throughline_id": "TL2",
  "throughline_punchline": "...",
  "mode": "talk-30",
  "tier": "STRONG",
  "substories": [
    {
      "id": "S1",
      "punchline": "...",
      "slide_position_range": [2, 8],
      "claim_id_pool": ["C001", "C002", "C003", "C004"]
    },
    {"id": "S2", "...": "..."}
  ],
  "slide_sequence": [
    {
      "global_position": 0,
      "layout": "title",
      "substory_id": null,
      "deck_role": "opener",
      "intended_punchline_seed": "{seed; composer may refine}",
      "image_intent": null,
      "claim_assignments": [],
      "citation_assignments": []
    },
    {
      "global_position": 1,
      "layout": "section_divider",
      "substory_id": "S1",
      "deck_role": "substory_divider",
      "intended_punchline_seed": "Substory 1 punchline (= S1.punchline)",
      "image_intent": null,
      "claim_assignments": [],
      "citation_assignments": []
    },
    {
      "global_position": 2,
      "layout": "claim_evidence",
      "substory_id": "S1",
      "deck_role": "evidence",
      "intended_punchline_seed": "First key finding — {claim_id seed}",
      "image_intent": {"kind": "figure_reuse", "figure_id": "fig_03", "caption_hint": "..."},
      "claim_assignments": ["C001"],
      "citation_assignments": ["Lloyd-Price2019"]
    },
    {
      "global_position": 8,
      "layout": "big_idea",
      "substory_id": null,
      "deck_role": "inter_substory_transition",
      "intended_punchline_seed": "Pivot from method to implication",
      "image_intent": {"kind": "concept_illustration", "metaphor_hint": "bridge from method to claim"},
      "transition_hook": {"from_substory": "S1", "to_substory": "S2"},
      "claim_assignments": [],
      "citation_assignments": []
    }
  ],
  "image_budget": {
    "ai_generated_count": 2,
    "diagram_count": 1,
    "figure_reuse_count": 7,
    "estimated_cost_usd": 0.08
  },
  "validation": {
    "claim_assignment_resolution": "pending|pass|fail",
    "citation_assignment_resolution": "pending|pass|fail",
    "image_budget_within_cap": "pending|pass|fail",
    "substory_coverage": "pending|pass|fail"
  }
}
```

### 6.6 What the architect is forbidden from doing

- Inventing claim_ids not in `claim_inventory.tsv`.
- Inventing citation keys not in `citation_pool.json`.
- Inventing figure_ids not in `curated_figures.md`.
- Assigning `image_intent.kind == "concept_illustration"` to more
  slots than `image_budget.ai_generated_count` allows.
- Assigning a transition slot inside a substory (transitions live at
  substory boundaries only).
- Dropping a critical analysis from REPORT (per D-027; the
  mode-capacity overflow protocol still applies and now halts at the
  deck-architecture-approval gate instead of the substory-approval
  gate).

### 6.7 User gate — deck-architecture-approval

The skill halts with `phase=deck_architecture_pick` handoff. The user
reviews `01_deck_architecture.json` (presented through a human-
readable renderer; raw JSON is the audit artifact) and either:

1. **Approve.** `/beril-presentation-maker-continue --approve-architecture`
2. **Amend.** `--amend-architecture "make S2 longer; drop the AI illustration on slide 14"`. Architect re-runs with amendment as input; emits revised architecture.
3. **Pick alternative.** Architect may emit 2–3 candidates via `--candidates 3`; `--pick ARCH{N}` selects.

**Hard cap:** 3 amendment cycles. After 3, halt with
`phase=architecture_blocked` (user manually edits the JSON and runs
`--approve-architecture` to bypass).

**Mode-capacity overflow handling (D-027 inheritance).** If
`sum(substory.slide_position_ranges)` exceeds mode capacity, the
architect emits with overflow flags and the gate offers the three
existing options: pick substories, escalate mode, merge substories.
The overflow protocol is unchanged from substory_design.v1's behavior
— the gate just moves up a phase.

### 6.8 Cost target + model choice

**Decided 2026-05-12 (Q2; D-031):** default model is **Opus 4.6**
(`claude-opus-4-6`). The architect is the load-bearing cross-cutting
planning agent; arc quality at this layer determines whether the
whole deck holds together or whether the parallel composers produce
locally-good slides that miss the through-arc. The paper-writer
v0.8 precedent (D-034 Q4) chose Opus for analogous reasons on its
holistic-write phase. Cost: $3.00–$5.00 per architect call (~3× the
Sonnet alternative considered and rejected).

Compare to today's `plan.v1` ($0.10) + `substory_design.v1` ($0.20)
≈ $0.30; net +$2.70–$4.70 per draft at the architect locus.
Partially offset by reduced rewrite cycles after Tier 1 review
fails less often.

`--architect-model claude-sonnet-4-6` is the explicit cost-sensitive
override for projects where bulk-draft economics matter more than
arc-quality margin.

---

## 7. Phase 3 — Per-substory composition (narrowed scope)

### 7.1 Contract with the architecture artifact

`slide_compose.v1.md` is retained but its scope shrinks. Today it
reads substory + throughline + figure shortlist + citation pool and
*invents* slide layouts, transitions, image flags, figure choices,
citation choices. v0.4 it reads the architecture artifact plus its
assigned slide slots, and composes *only the bullet-level content*:

| Today (v0.3.x) | v0.4 |
|---|---|
| Decides layout per slide | Reads `slide.layout` from architecture |
| Decides image_intent per slide | Reads `slide.image_intent` from architecture |
| Decides which figures appear | Reads `slide.image_intent.figure_id` |
| Decides which citations appear | Reads `slide.citation_assignments` |
| Decides punchline (no upstream constraint) | Refines from `intended_punchline_seed` |
| Decides bullet content | Decides bullet content (preserved) |
| Decides speaker-notes seed | Decides speaker-notes seed (preserved) |

Composer authority is preserved over: exact punchline wording (may
refine the seed), bullet content, figure caption refinement, exact
citation token wording in prose, speaker-notes seed.

### 7.2 Deviation contract — rigid for v0.4 pilot

> **SUPERSEDED 2026-05-23 (v0.4.1 — see §20, D-044).** The rigid
> halt-and-re-architect contract below is dropped. The M2-lite outline
> is advisory context, not a contract: composers free-hand local
> composition and there is no `architecture_conflict` halt.

If a composer finds the architecture's plan doesn't fit the evidence
(e.g., the assigned claim_id and figure don't actually support the
intended punchline), the contract is: **halt with `phase=architecture_conflict`,
log the specific deviation in `audit/architecture_conflicts.jsonl`,
and re-run the architect with the composer's complaint as
amendment input.** Two-pass advisory mode is deferred to v0.5 if
empirically the rigid contract proves too brittle.

Rationale: rigid blame attribution + simpler implementation are worth
more in v0.4 than the operational flexibility of advisory mode. If
the architect is making bad calls often enough to trigger
re-architecting, that's a signal the architect prompt needs
improvement — fix the cause, not the workaround.

### 7.3 Parallel execution

Per-substory composers run concurrently. Implementation: bash
worker-pool (C1 from `V0_4_0_PUNCH_LIST.md`) or Python `concurrent.futures`
wrapper around the `claude -p` subprocess calls — pick whichever
ports cleanest to the existing `presentation_maker.sh` orchestrator.

Per-substory worker scope: one Claude call writes both
`compose-fragment.v1` and `speaker_notes_seed.v1` JSON for the
substory's slide range. Today these are two separate calls per
substory; v0.4 fuses them because they share the same context (architecture
+ throughline + assigned claims/citations/figures) and the LLM's
context-loading cost dominates.

**Expected wall-clock saving.** From `V0_4_0_PUNCH_LIST.md` gap analysis:
60–90 min per draft on `ibd_phage_targeting` (talk-45 STRONG).
Confirmed pre-pivot wall-clock: 158 min for stages 3–10 sequential.
Post-pivot estimate: ~50–80 min (3-substory parallel + the architecture
call + Tier 1 review at the new locus). Adam confirms on M5 A/B.

### 7.4 What happens to the substory-approval gate (D-002 rev1)

Absorbed into the deck-architecture-approval gate (§6.7). The user
sees substory clusters as part of the deck architecture; approving
the architecture approves the substory list. This is a minor change
to D-002 rev1 (the gate moves up one phase); the load-bearing
property (user gets to split/merge/drop substories before composition
starts) is preserved.

`--no-substory-pause` becomes `--no-architecture-pause`. Legacy flag
kept as alias for one release.

---

## 8. Phase 4 — Tiered review cascade (fail-fast)

### 8.1 Three tiers, fail-fast

Direct port of `SPEC_v0_8.md` §7. Each tier reads `slide_spec.json`
(post-composition merge) + the architecture + the Phase-0 artifacts.

**Tier 1 — deterministic + minimal LLM (~$0.01).**
- All P1–P10 validators (per SPEC §13) run mechanically.
- Plus the v0.3.8 process-detail-bleed post-checker (advisory).
- Plus the new `check_architecture_drift.py`: every composed slide's
  layout, image_intent, claim_assignments, citation_assignments
  matches the architecture artifact's pre-allocated values.

Cap: 1 pass. Failures route to targeted re-compose (per-substory
worker re-runs for the affected substory only) or to
`phase=tier1_blocked` handoff if the failure is architectural
(architect prompted to amend).

**Tier 2 — Haiku narrative-light (~$0.05).**
- Subset of `beril-adversarial` v3 presentation detection classes
  empirically chosen at M3 (per paper-writer §7.5 pattern; empirical
  calibration before this tier ships):
  - `register_drift` — fast pattern detection
  - `qa_softball` — question-mark / low-novelty heuristic
  - `unbacked_quantitative` — cross-walk against claim_inventory
  - `substory_arc` — cross-slide arc coherence (newly tractable
    because the architect's substory_id assignment gives a
    deterministic frame)

Cap: 1 pass. Findings dispatch to per-substory targeted re-compose.

**Tier 3 — canonical adversarial (~$0.50–$1.50).**
- `beril-adversarial review --type presentation --auto-number <draft_dir>`
  (per `CONTRACT.md` from beril-adversarial v0.6.0+).
- Full v3 paper schema with `central_objection`, `citation_reality`,
  etc.

Cap: 1 pass; one retry on P0 only. Fallback to inline
`fallback_reviewer.v1.md` if `beril-adversarial` CLI absent.

### 8.2 Fail-fast saving

Tier 1 P0s short-circuit Tier 2/3. If mechanical checks fail (e.g.,
P3 numeric-provenance fails because composition invented a number),
don't pay Tier 2/3 LLM costs until Tier 1 clears. On
`ibd_phage_targeting` historical data (P3 escalation rate ~15% on
first pass), this saves ~$0.50 per failed-tier-1 draft.

### 8.3 Validators-at-architecture-time (NEW)

A subset of P-validators run *against the architecture artifact*
before composition starts:

- `claim_inventory` cross-walk: every `claim_assignments` entry
  resolves to a real `claim_id` in `claim_inventory.tsv`.
- `citation_pool` cross-walk: every `citation_assignments` entry
  resolves to a `pool.json` key.
- `figure_inventory` cross-walk: every `image_intent.figure_id`
  resolves to `curated_figures.md`.
- `image_budget` arithmetic: `ai_generated_count` ≤ `--ai-diagram-budget` / `_WORST_CASE_COST_USD`.
- `substory_coverage`: every critical analysis from REPORT (per claim_inventory) is assigned to at least one slide.
- `transition_placement`: every `inter_substory_transition` slide sits at a substory boundary.

If any architecture-time validator fails, the architect re-runs with
the failure as amendment input. No composition cost is paid; this is
the cheapest possible failure path and the cleanest blame attribution.

---

## 9. Phase 5 — Assembly (unchanged)

`slide_spec.json` → `slides.pptx` via `assemble_pptx.py` is unchanged
from v0.3.x. `slide_spec` schema is unchanged from v0.3.2's data_table
addition — the architecture artifact is upstream of `slide_spec`, not
a replacement for it.

---

## 10. State machine + handoff contract

### 10.1 New phase enum

```
plan → phase0_tooling → throughline_pick → deck_outline
     → composition (parallel) → review_tier1
     → review_tier2 → review_tier3 → assembled
```

> **Revised 2026-05-23 (v0.4.1 — §20).** The enum above is the M2-lite
> form: `deck_architect` → `deck_outline`, and the
> `deck_architecture_pick` gate is removed (throughline-pick is the
> single human gate; the outline flows straight through). The M0 form
> was `deck_architect → deck_architecture_pick → composition`.

Halt states: `tier{1,2,3}_blocked`, `compliance_blocked`, plus the
existing v0.3.x states preserved (`throughline_pick_blocked`, etc.).
`architecture_blocked` and `architecture_conflict` are dropped with
the rigid contract (D-044).

State schema bumps to `"version": "0.4"`. Migration script from v0.3.x
state.json is M6 deliverable; v0.4 runs don't back-migrate v0.3.x
state.

**Cross-skill path-detection — verified no drift (M1 Tier E1, 2026-05-21).**
M1 introduces `working/00_phase0/` (Phase-0 staging) and
`audit/phase0.jsonl`. beril-adversarial's `--type presentation`
reviewer was checked against this layout: `adversarial_review.sh`'s
v0.5.2 detection block probes the exact path `working/slide_spec.json`
and reads fixed paths (`working/03_slides/qa_anticipated.json`,
`working/04_speaker_notes/`, `narrative/00_throughline.md`,
`narrative/02_substories.md`) — it never zone-globs or counts
draft-root entries. `working/00_phase0/` is a sub-subdir of the
`working/` zone, so it is invisible to the reviewer; `audit/phase0.jsonl`
does not collide with the reviewer's `audit/adversarial_review.{md,json}`.
No consumer-update task is needed. The original watchpoint
(`project_presentation_maker_v0_4_m0.md`) assumed Phase-0 artifacts at
draft-root `00_phase0/` — a 5th top-level entry; Tier C's correction to
`working/00_phase0/` dissolved that concern. Reviewer awareness of
`01_deck_architecture.json` is a genuine M2+ cross-skill item, tracked
with the architect work.

### 10.2 Handoff JSON contract preserved

The v0.3.6+ `.handoff.json` shape with `phase`, `prompt_to_user`,
`resume_command` carries forward unchanged. The slash-command parser
keeps its "always read .handoff.json" rule (`commands/beril-presentation-maker-continue.md`
parser; SKILL.md halt-and-handoff section).

---

## 11. Cost + latency targets

Both work modes (paper exists vs. no paper) are first-class. The
cost delta concentrates in Phase 0; downstream phases are identical.

### 11.1 Per-phase table (paper-exists mode)

| Phase | Tokens (in/out) | Model | Cost | Wall-clock |
|---|---|---|---|---|
| 0 — tooling | ~25K/10K | mixed (cache reuse + Haiku batched demarcation if cache stale) | $0.50–$1.50 | 1–3 min |
| 1 — throughline pick | ~40K/8K | Sonnet | $0.40–$0.80 | 2–4 min |
| 2 — deck architect | ~40K/10K | **Opus 4.6** (Sonnet opt-in via `--architect-model`) | $3.00–$5.00 | 2–4 min |
| 3 — composition (parallel) | ~100K/15K total across N substories | Sonnet | $2.00–$4.00 | **5–10 min wall-clock (parallel)**; ~15–25 min cumulative LLM time |
| 4 — tier 1 deterministic | <2K/<1K | Haiku (ambiguity-only) | $0.02–$0.05 | <30 s |
| 4 — tier 2 narrative | ~12K/5K | Haiku | $0.05–$0.10 | 1 min |
| 4 — tier 3 canonical | ~80K/15K | Sonnet (canonical adversarial) | $0.50–$1.50 | 3–6 min |
| 5 — assembly | 0 | — | $0 | <30 s |
| **Total (talk-30 default, local, paper exists)** | — | — | **$6.50–$13.00** | **20–35 min** |

### 11.2 No-paper-mode delta

Phase 0 absorbs the cost of originating citation_pool from scratch
(literature scan, $0.80–$2.50, +3–8 min) and originating
methods_provenance + claim_inventory from scratch (already counted
in §11.1's Phase 0 range when cache stale, but the no-paper case
guarantees they run). All other phases identical to §11.1.

| Phase | Delta vs paper-exists | Notes |
|---|---|---|
| 0 — tooling | **+$0.80–$2.50, +3–8 min** | citation_pool literature scan; methods_provenance + claim_inventory cost already counted in §11.1's range |
| 1–5 | $0 / 0 min | Architect and downstream identical |
| **Total (talk-30 default, local, no paper)** | **$7.30–$15.50 / 25–45 min** | ~+12–19% cost; ~+25–40% wall-clock vs paper-exists |

The no-paper case is the harder draft to land cheaply because
literature-scan citation_pool building is the single largest
non-architect cost in Phase 0. This is unchanged from v0.3.x; the
v0.4 architecture doesn't make the no-paper case worse. The
reuse-from-paper-writer optimization (D-009) remains the practical
fast path when a paper draft exists.

### 11.3 Hub wall-clock baseline

Compare to v0.3.8 (per `V0_4_0_PUNCH_LIST.md`): talk-45 STRONG ran
~3.7h (~222 min) wall-clock at $16–$20 per draft on the hub. The
punch list's C1-alone estimate was 60–90 min saved from per-substory
parallelism. v0.4 adds further savings from cascade fail-fast
(~5–15 min, when Tier 1 P0 short-circuits Tier 2/3) and from reduced
rewrite cycles (~10–30 min, when architecture-time validators catch
issues before composition spends). Combined estimated post-pivot
hub wall-clock on talk-45 STRONG: **100–150 min** (a 30–50%
reduction, not a 60–80% reduction — be honest). Local runs scale
proportionally; expect ~45–75 min on talk-30 local. The wall-clock
primary-metric target at the cut-over gate (§15) is set at the
conservative end of this range to leave headroom for variance.

The cost increase at the architect call (+$0.70–$1.70 over today's
plan + substory_design) is offset by:
- Fewer rewrite cycles after Tier 1 fails less often.
- Tier 2/3 short-circuiting on Tier 1 P0 failures.
- Image-budget allocated once at architecture time, not per-substory.

Net cost expected: ±$0 to +$1 per draft vs v0.3.8.

---

## 12. v0.3.x → v0.4 migration matrix

| Component | v0.3.x state | v0.4 disposition | Notes |
|---|---|---|---|
| `prompts/plan.v1.md` | triage + mode-tier match | RETIRED → `prompts/archive/v0_3/` | Architect absorbs |
| `prompts/throughline.v1.md` | throughline candidates | KEPT | Load-bearing user gate unchanged |
| `prompts/substory_design.v1.md` | substory clustering | RETIRED → archive | Architect absorbs |
| `prompts/slide_compose.v1.md` | per-substory composer | KEPT but NARROWED | Reads architecture; composes bullets+notes-seed only |
| `prompts/speaker_notes.v1.md` | per-slide notes | FUSED into slide_compose | One LLM call per substory writes both |
| `prompts/qa_prep.v1.md` | Q&A generation | KEPT | Reads architecture for substory list |
| `prompts/cross_tenant.v1.md` | cross-tenant extraction | KEPT | Phase 0 |
| `prompts/citation_pool.v1.md` | citation lit-scan | KEPT | Phase 0 |
| `prompts/diagram_design.v1.md` | procedural diagram spec | KEPT | Runs per-slide flagged for diagram |
| `prompts/ai_image_prompt.v1.md` | image prompt author | KEPT | Reads architecture's `image_intent` |
| `prompts/intro.v1.md` | (legacy, lightly used?) | TBD at M1 | Audit current invocation rate |
| `prompts/add_slide.v1.md` | revise verb's add-slide path | KEPT | Reads architecture for placement |
| `prompts/revise_slide.v1.md` | revise verb's edit path | KEPT | New semantic-invariance post-check added (see §13) |
| `tools/curate_figures.py` | figure shortlist | KEPT | Phase 0 |
| `tools/extract_cross_tenant.py` | cross-tenant signal | KEPT | Phase 0 |
| `tools/citation_pool.py` | pool builder | KEPT | Phase 0 |
| `tools/claim_inventory.py` | — | **NEW** (port from paper-writer M1) | Phase 0 |
| `tools/claim_demarcate.v1.md` | — | **NEW** (port from paper-writer) | Phase 0 |
| `tools/validate_presentation.py` | P1–P10 | EXTENDED | Tier 1 cascade; adds `check_architecture_drift.py` |
| `tools/check_no_artifact_refs.py` | v0.3.8 post-checker | KEPT → Tier 1 | Mechanical |
| `tools/diagram_render.py` | procedural diagram renderer | KEPT | Phase 5 |
| `tools/image_client.py` | CBORG-default image client | EXTENDED | Multi-provider (§14) |
| `tools/assemble_pptx.py` | slide_spec → pptx | KEPT | Phase 5 |
| `tools/presentation_maker.sh` | orchestrator (~3000 LOC) | REWRITTEN | New phase enum; worker-pool; smaller (~1800 LOC) |
| `state.py` | state.json schema | EXTENDED | Phase enum; v0.3→v0.4 migration script (M6) |

New prompt: `prompts/deck_architect.v1.md` (~400-line system prompt;
Sonnet by default).

New tool: `tools/check_architecture_drift.py` (Tier 1 mechanical
check: composed slide_spec values match architecture pre-allocations).

New artifact: `01_deck_architecture.json` (per-draft).

---

## 13. Revise verb — semantic-invariance post-check (NEW)

Per the v0.3 critique memo recommendation #4: `revise` today re-runs
slide_compose for the affected scope and re-runs P3–P10, but has no
programmatic check that revising slide N didn't silently change a
citation token still cross-referenced from slide N+2's speaker notes,
didn't flip a "suggests" to "demonstrates," or didn't introduce a
numeric assertion that wasn't on the prior slide.

`tools/revise_invariance.py` runs after every `revise` invocation
with the pattern from `SPEC_v0_8.md` §11.2:

1. **Claim_id cross-walk.** Every `claim_id` in pre-edit slide content + speaker notes MUST appear in post-edit at the same slide.
2. **Citation cross-walk.** Every `[citation_key]` in pre-edit MUST appear in post-edit (insertions and deletions both forbidden; revise should only edit *prose around* citations).
3. **Numeric token preservation.** Every numeric literal in pre-edit appears in post-edit at least as often (allows removal in service of de-duplication; forbids invention).
4. **Hedge-marker level.** Each claim's hedge-marker count (`may`, `suggests`, `appears`, `candidate`, `preliminary`, etc.) is computed pre and post; per-claim level may decrease by ≤1 but not increase or flip a scoped claim to declarative.
5. **Layout preservation.** Slide layout MUST NOT change via revise (layout changes require re-architecting; user must run `--re-evaluate-architecture` instead).

If any check (1)–(5) fails, the revise is rejected wholesale; halt
with `phase=revise_invariance_violated`, validation output JSON
written to `audit/revise_invariance.json`, user accepts manually or
skips.

---

## 14. Image-gen — AI Studio API key + multi-provider

### 14.1 Why now

Adam confirmed: the intent is "use the user's Gemini Studio license if
available." Today's `image_client.py` (line 75–93) defaults to CBORG
with `gemini-3-pro-image`; only the `cborg` provider is implemented.
`gemini-3-pro-image` is reportedly being deprecated (Adam's
observation); the AI Studio image-gen model line as of May 2026 is
`gemini-2.5-flash-image` (Imagen 4 lineage on Studio's surface).

### 14.2 Implementation plan

**Provider abstraction extension** in `tools/image_client.py`:
- `ImageClient.__init__` extends provider dispatch to handle `"google_ai_studio"` alongside `"cborg"`.
- New `_call_google_ai_studio()` matching `_call_cborg()` shape:
  - Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`
  - Auth: `x-goog-api-key: <api_key>` header
  - Request body shape differs from CBORG's OpenAI-compat shape (Google's native API is `{"contents":[{"parts":[{"text": prompt}]}], "generationConfig":{...}}`).
  - Response: image bytes in `candidates[0].content.parts[N].inline_data.data` (base64).

**Auth discovery** in `commands/configure.py`:
- Precedence: `GOOGLE_AI_STUDIO_API_KEY` env var present → AI Studio default; else `CBORG_API_KEY` → CBORG; else fail with both env-var names in the error.
- `--image-provider {cborg|google-ai-studio}` CLI override.

**Model-availability probe** at startup:
- One `GET https://generativelanguage.googleapis.com/v1beta/models` call (AI Studio path only); filter for image-capable models.
- Pick `gemini-3-pro-image` if present (Adam: "use it if we see it"), else `gemini-2.5-flash-image`, else fail with a clear message naming available models.
- Cache the choice in `state.json` per draft (`ai_image_gen.resolved_model`); don't re-probe on every invocation.

**Rate-card update** at `_MODEL_RATES_USD_PER_M` (lines 85–93):
- Add `gemini-2.5-flash-image` entry with AI Studio's published rate (~$30/M output tokens, verify before shipping).
- Cost-cap recalibration: `_WORST_CASE_COST_USD = 0.05` was calibrated against CBORG-proxied `gemini-3-pro-image`. AI Studio's `gemini-2.5-flash-image` has different per-image token economics; re-run `image_gen_calibration.py` against AI Studio before that default is treated as load-bearing. Until re-calibration, conservative default `_WORST_CASE_COST_USD = 0.08` for the AI Studio path.

**Rate-limit handling**:
- AI Studio free-tier rate-limits aggressively. `_call_google_ai_studio()` detects 429 and surfaces a clear error (don't retry blindly). Per-image approval gate naturally spaces calls; should be sufficient at default usage.

### 14.3 v0.4 ship criteria

- All four wired (provider abstraction, auth discovery, model probe, rate-card update).
- Calibration harness re-run against AI Studio path; calibrated constant updated.
- Smoke test: 1 image generated via each path (CBORG + AI Studio) on `ibd_phage_targeting` talk-30 draft.

---

## 15. Cut-over gate (M6 A/B)

Mirrors `SPEC_v0_8.md` §16 pattern. A/B run on `ibd_phage_targeting`
(target) and `functional_dark_matter` (sanity-check) through:
- **A:** v0.3.8 (current default) — sequential, per-substory.
- **B:** v0.4.0 (M0–M5 deliverable) — architect-then-parallel-compose.

Score on 7 metrics:

1. **Wall-clock time.** First-byte to last-byte. Objective. Primary metric.
2. **Token cost.** Sum of all LLM-call input + output tokens. Objective.
3. **Adversarial findings count after one Tier-3 pass.** Run `beril-adversarial --type presentation` against both decks with identical settings. Objective.
4. **Validator failure rate at Tier 1.** P1–P10 failure rate on first composition pass. Objective.
5. **Cross-substory arc coherence (subjective).** Adam reads both decks back-to-back; rates substory-to-substory transitions on a 5-point scale. Subjective but reproducible across one reviewer.
6. **Image-budget adherence.** AI illustration count and cost vs target. Objective.
7. **Paper-review skill quality assessment of the deck's narrative arc.** Run `paper-review` skill against both decks (or against speaker-notes export); take the qualitative summary. Subjective but reproducible.

**Decision rule.** v0.4 must dominate v0.3.8 on **≥5 of 7** metrics
OR have a documented accepted-trade-off reason for ties/regressions.

**Primary metric (1, wall-clock) is mandatory** — if v0.4 doesn't
materially reduce wall-clock (target: ≥40% reduction on talk-45
STRONG), the parallelism investment didn't pay off and the gate
fails regardless of the other 6 scores.

**If gate fails:** keep v0.3.x as default; ship v0.4.0 as
experimental flag (`--architecture-pipeline v0_4`); file follow-up
tasks for the failed metrics.

**Reviewer pool:** Adam-only for v0.4.0 (matches paper-writer Q8 deferral).

---

## 16. Milestones M0–M6

**M0 — Spec sign-off (this document).** ~500–700 lines of
`V0_4_ARCHITECTURE.md` plus a `DECISIONS.md` v0.4.0 entry capturing
the decision frame. NO code. End of milestone is Adam's sign-off on
the v0.4 questions in §17.

**M1 — Phase 0 vendor ports (REVISED per D-040-rev1).** Vendor active-path
artifacts from paper-writer: `extract_methods.py` + `extract_claims.v1.md`
(LLM prompt) + `validate_claim_inventory.py`. Author `extract_claims.py`
adapter (~340 LOC; standalone CLI wrapping the `claude -p` invocation
that paper-writer inlines in orchestrator.py). Adapt tests to
presentation-maker's package layout. Smoke against `ibd_phage_targeting`
in *both work modes* (paper-exists reuse path + no-paper origination
path). ~1400 LOC vendored + ~340 LOC new + ~65 tests.

**M1 — SHIPPED 2026-05-21.** All five tiers complete: Tier A + Tier B
(vendor copies + adapter + unit tests, 2026-05-12), Tier C
(`phase0_reuse.py` helper + `DraftPaths` extension, 2026-05-14), the B6
model-pin, the post-Tier-C `validate_claim_inventory.py` re-vendor to
`0.2.0-stage3-tierI` + D-052 numeric-grounding port, the Tier D Step 0
`extract_claims.v1.md` re-vendor, Tier D (dual-mode smoke — all three
gates pass: reuse $0 / byte-identical, originate clean on both projects
with 0 validator repairs), and Tier E (this paperwork). Full suite 991
passed on Adam's Mac. Per-tier ship tables in `M1_PUNCH_LIST.md`; M1
retrospective + M2 watchpoints in auto-memory
`project_presentation_maker_v0_4_m1.md`.

**M2 unblocked** (reshaped to M2-lite 2026-05-23 — see §20): the
`deck_outline.v1` call (enrich `substory_design.v1`) + per-section
composer briefing + a post-merge reconciliation check.

**M1 dependency note (resolved 2026-05-12):** paper-writer M1 §B1 had
shipped `claim_inventory.py` (per memory `project_paper_writer_v0_8_m1_a1.md`),
but their Stage 1 (closed 2026-05-11, per `STAGED_IMPROVEMENT_PLAN.md`)
deferred it from active pipeline. The active path is `extract_claims.v1.md`
+ `validate_claim_inventory.py`, both shipped in paper-writer's tree
and vendored byte-portable here. See `feedback_vendor_port_verify_active_path.md`
for the cross-cutting lesson.

**M2 — deck-outline call (M2-lite) — SHIPPED 2026-05-23 (see §20 + §20.8).**
Enrich `substory_design.v1` into a `deck_outline.v1` call that emits a
terse, prescriptive whole-deck outline (per-section punchline + budget
+ headline-slot assignment + explicit transition-in/out sentences +
scoped figures/claims + deck register spec). Sonnet, not Opus. The
outline is advisory context fed to the parallel composers — NOT a
rigid `01_deck_architecture.json` contract. Dropped vs the M0 §6
design: `deck_architecture.py`, `check_architecture_drift.py`, the six
architecture-time validators, the `deck_architecture_pick` gate.
Validated by the 2026-05-23 outline probe (§20.7). Opt-in
`--architecture-pipeline v0_4`; v0.3.x default unchanged. Est. ~12–18h.

**M3 — Per-substory parallel composition — STRUCTURALLY COMPLETE 2026-05-23.**
`tools/worker_pool.sh` (sourceable bounded-concurrency batch runner) +
a parallel `_slide_compose_v0_4` branch; the v0.4 dispatch re-sequenced
so the Phase-0 producers run before `deck_outline` (closed M1 Tier F1);
`tools/reconcile_deck.py` post-merge conflict checker; `slide_compose.v2.md`
(advisory deck-outline brief + fused speaker notes, D-033 / D-044; emits
`compose-fragment.v2`); `merge_compose_fragments.py` dual-mode. Tier E
live smoke on `ibd_phage_targeting` ran the v0.4 path end-to-end; patches
E-1…E-7 logged in `M3_PUNCH_LIST.md`. The deck's render-quality debt —
fixed-size assembler boxes vs variable composer content — is **routed to
M4** (Adam 2026-05-23), not M3's blast radius. Empirical Tier-2
detection-class calibration moved to M4b (D-049). Detail: `M3_PUNCH_LIST.md`.

**M4 — Render-quality + review cascade.** Two halves, M4a before M4b
(Adam 2026-05-23):

- **M4a — visual-QA + content discipline — SHIPPED 2026-05-24.**
  Six tiers, five Tier-E rounds, suite 1107 passed, VQA cost across
  rounds: $2.84 (one-time M4a-build spend). Per-tier ship table in
  `M4_PUNCH_LIST.md`; DQ1–DQ4 resolutions land as D-050..D-053 in
  `DECISIONS.md`; M4a retrospective in auto-memory
  `project_presentation_maker_v0_4_m4a.md`.
  - **Renderer** (Tier A, commit `fa42880`): `_fit_textbox` helper
    writes explicit `<a:normAutofit fontScale="…">` on overflow-prone
    freeform textboxes (big_number subtitle/sub_pointer/source_footer,
    workflow step_captions + tool_version_footer, data_table caption +
    footnote, methods_summary tools_versions); `_apply_fontscale_to_shape`
    on diagram node labels (replaces the LibreOffice-ignored
    `auto_size=TEXT_TO_FIT_SHAPE`); 60% fontScale floor (D-052) with a
    clamp-warning surfaced via `AssemblyResult.warnings`. `_render_edge`
    split into `_render_edge_line` + `_render_edge_label`; third
    render-diagram pass paints labels on top of nodes (M3-deferred
    z-order fix).
  - **Content** (Tier B, commit `f7581af`): four advisory caps pinned
    in `slide_spec.py` (`BIG_NUMBER_SUBTITLE_MAX_CHARS=80`,
    `WORKFLOW_STEP_CAPTION_MAX_CHARS=70`, `QA_ANSWER_SUMMARY_MAX_CHARS=600`,
    `DIAGRAM_NODE_LABEL_MAX_CHARS=40`); `ValidatorIssue.severity`
    splits hard-error from advisory soft-warning (D-053); three prompt
    edits (`diagram_design.v1.md` node label cap, `slide_compose.v2.md`
    big_number subtitle + workflow step_caption guidance, `qa_prep.v1.md`
    answer_summary cap); soft-warnings flow through the assembler
    warnings channel (not `AssemblyError`).
  - **Visual-QA** (Tier C, commit `e9e4e82`): new `tools/visual_qa.py`
    + `prompts/visual_qa.v1.md` + opt-in orchestrator `--visual-qa`
    flag (D-050). Six-step pipeline (probe toolchain → load spec →
    assemble → soffice pptx→pdf → pdftoppm pdf→pngs → claude -p vision
    pass) with stub-report fallback on every failure path. Sonnet 4.6
    vision (~$0.6–0.8 per 28-slide deck); LibreOffice + Poppler are
    host-only runtime deps (skill ships portable; absent deps → stub
    report + rc=0). Toolchain choice per D-051: `soffice --headless
    --convert-to pdf` then `pdftoppm` (both confirmed on Adam's Mac).
  - **Tier D — test hygiene** (commit `0d3a07b`): the live
    adversarial-interop integration test is now gated behind BOTH
    `BERIL_PRESENTATION_MAKER_RUN_LIVE=1` AND `TEST_DRAFT_DIR`; the
    pre-D auto-discovery walk that fired a live ~$0.50 LLM call on
    routine `pytest tests/` was removed.
  - **Tier E — live render smoke** (5 rounds, commits `53dfaf5`,
    `64d35f1`, `1a7e9c7`, `a234acf`, `de4a7f1`): convergence gate on
    `ibd_phage_targeting` draft_1. Round 1 hotpatched a CLI severity
    bug (soft-warnings halted the orchestrator); round 2 stripped the
    full-slide watermark from 12 layouts via `build_master.py` +
    darkened `GRAPHITE_GRAY_RGB` (157,146,135)→(80,75,70) + the
    `claim_evidence` figure_caption autofit; round 3 introduced
    gap-based edge-label geometry + acronym-aware title fix-up;
    round 4 raised the in-gap threshold (0.4→1.0in) + word_wrap=False
    after round-3 produced char-by-char wrap, and moved the acronym
    fix to `merge_compose_fragments.py` so the spec-on-disk matches
    the render; round 5 anchored edge-label `y` to `node_top - h - 0.05`
    (the round-4 `mid_y - 0.40` was INSIDE the node-row vertical extent)
    + added the missing `_enable_normautofit` to `_fill_claim_evidence`'s
    with-figure branch.
  - **Tier F — closeout**: this section; `LAYOUT.md` updated for
    `visual_qa.py` + `visual_qa.v1.md`; `DECISIONS.md` D-050..D-053;
    `M4_PUNCH_LIST.md` status table closed; auto-memory updated.
  - **Carried out of M4a:** composer prompt iteration for node-label
    cap respect (slides 5/9/18 carry 50–70-char node labels — Tier-A
    renderer absorbs; tightening lives with the next slide_compose
    prompt iteration); `visual_qa.v1.md` prompt iteration to require
    fontScale-grounded illegible_scale claims (7 false positives in
    Tier-E round-4 VQA where the model reported "extremely small font"
    on text rendered at 80–100% scale); portable visual-QA path for
    end-user revise loops (auto-memory task; revisit during M4b
    cascade design).
- **M4b — tiered review cascade — SHIPPED 2026-05-24.**
  Six tiers, three live Tier-E rounds, suite 1174 passed. Per-tier
  ship table in `M4b_PUNCH_LIST.md`; DQ1–DQ4 resolutions land as
  D-054..D-057 in `DECISIONS.md`; live P3 contract-mismatch fix
  lands as D-058; M4b retrospective in auto-memory
  `project_presentation_maker_v0_4_m4b.md`.
  - **Tier A — orchestrator scaffolding** (commit `80139a5`):
    `tools/review_cascade.py` ships the cascade contract
    (`review-cascade.v1`); `TierResult` / `CascadeFinding` /
    `CascadeReport` dataclasses; `run_cascade` with DQ4
    operator-gated short-circuit (Tier-1 P0 → skip Tier 2+3; Tier 2
    advisory only; Tier 3 unconditional unless `--no-tier3`); CLI
    + orchestrator `--no-review-cascade` opt-out (D-054 auto-run
    default).
  - **Tier B — Tier 1 aggregation** (commit `60795b1`): five sources
    in fail-fast cost order — `validate_presentation` P1–P10
    (Tier B runs it directly + persists
    `audit/presentation_validation.json` as side-effect; pre-flighted
    via `slide_spec.validate_slide_spec` to skip cleanly on
    structurally-invalid specs), `quantitative_grounding.json`,
    `no_artifact_refs.json`, `deck_reconciliation.json`, and
    `audit/visual_qa.json` (DQ2 / D-055: read-if-present; never
    invoke `visual_qa.py`). DQ4 / D-057 P0 set: `_P0_VALIDATORS =
    {"P3", "P4", "P5"}` (D-058 later removes P3).
  - **Tier C — Tier 2 narrative-light** (commit `1812813`): new
    `tools/review_tier2.py` + `prompts/review_tier2.v1.md` (D-056
    ship-as-v1 with the §8.1 candidate-four classes —
    `register_drift`, `qa_softball`, `unbacked_quantitative`,
    `substory_arc`). Pinned `claude-haiku-4-5-20251001` (~$0.05/run
    target). Cascade dispatcher with DQ4 invariant: even a rogue
    Tier-2 P0 is demoted to P1 (cascade short-circuit reads
    `TierResult.has_p0`; Tier 2 must never trigger).
  - **Tier D — Tier 3 wrapper** (commit `5bfea4b`): cascade `run_tier3`
    invokes `beril-adversarial review --type presentation` directly
    + lifts v3 findings into cascade findings. Orchestrator de-dup:
    reads `audit/review_cascade.json`'s `tiers[2].status`; if in
    {pass, advisory, fail}, standalone `stage_adversarial_review`
    skips (no double-spend on adversarial; revise loop still
    consumes the cascade-produced `audit/adversarial_review.json`).
  - **Tier E — live cascade smoke** (3 rounds, commits `8fab2fa`,
    `da3112e`, `b774e66`; plus offline integration tests `b2ae7f5`):
    convergence gate on `ibd_phage_targeting/draft_1`. Round 1 hit
    P3 v0.3-era contract mismatch (282 P0s on numbers; v0.4
    composer doesn't emit `speaker_notes_provenance`) — fixed via
    D-058 P3 demote + M5 schedule. Round 2 hit missing
    `--beril-root` in cascade Tier-3 subprocess (orchestrator
    preamble sets `BERIL_ROOT` env; standalone cascade doesn't) —
    fixed with explicit-arg → env-var → walk-up-4-parents
    resolution. Round 3 hit real v3 schema (`class`/`issue`/
    central_objection-as-finding, not `kind`/`summary`/top-level) —
    fixed lifter. Final round 3: T1 advisory 586 findings, T2
    advisory 6 findings (all 4 classes; 121.7s; ~$0.05), T3
    advisory 14 findings (8 classes; 5 P0; 9.3 min). Calibration
    captured at `audit/review_tier2_calibration.md` (DQ3
    ship-then-iterate ratified; v2 expansion candidates documented:
    `claim_evidence`, `throughline_drift`, `unbacked_citation`,
    tighten `qa_softball`).
  - **Tier F — closeout**: this section; `LAYOUT.md` updated for
    `review_cascade.py` + `review_tier2.py` + `review_tier2.v1.md`;
    `DECISIONS.md` D-054..D-058; `M4b_PUNCH_LIST.md` status table
    closed; auto-memory updated.
  - **Carried out of M4b** (deferred per the M4b posture):
    - P3 retirement (replace `validate_p3_numeric_provenance` with
      a wrapper around `check_quantitative_grounding.py`) — scheduled
      for M5 per D-058.
    - Tier 2 prompt v2 expansion (add `claim_evidence`,
      `throughline_drift`, `unbacked_citation` classes; tighten
      `qa_softball`) — captured in
      `audit/review_tier2_calibration.md`; ship-then-iterate per
      DQ3 / D-056.
    - Persist Tier-2 cost into `audit/review_tier2.json`
      (currently goes to stderr via the diagnostic envelope; future
      consumers want it in the JSON).

**M5 — Image-gen multi-provider + revise invariance + P3 retirement.**
Split into two halves; M5a (cheap-wins; offline correctness) shipped
first per Adam's reorder 2026-05-24.

- **M5a — P3 retirement + revise_invariance — SHIPPED 2026-05-24.**
  Six tiers; per-tier ship table in `M5a_PUNCH_LIST.md`; DQ1–DQ4
  resolutions land as D-059..D-061 in `DECISIONS.md`; M5a
  retrospective in auto-memory `project_presentation_maker_v0_4_m5a.md`.
  - **Tier A — `revise_invariance.py` + 5 invariants** (commit
    `cf8c0bd` and follow-ups): new `tools/revise_invariance.py`
    ships the contract (`revise-invariance.v1`); five §13 invariants
    — claim_id cross-walk (DQ1 heuristic per D-060: substring match
    against `claim_inventory.tsv` column 1; skipped+advisory when
    inventory missing), citation preservation (`[Author20YY]` set
    equality, insertions AND deletions forbidden), numeric
    preservation (multiset via reused
    `check_quantitative_grounding.extract_numbers`), hedge level
    (per-slide aggregation per DQ2 / D-060; ≤1 decrease OK, increase
    or >1 decrease fail; 5-marker dict as constant), layout
    preservation (`slide["layout"]` equality). CLI rc=0 pass / rc=1
    fail per DQ3 / D-061 hard-reject. 29 unit tests; suite 1203
    passed.
  - **Tier B — wire into `revise_loop.py`** (commit `e84efc4`):
    `_check_revise_invariance` helper invokes `revise_invariance.py`
    via subprocess between LLM post-edit and `_replace_slide_in_spec`
    (gate placement guarantees spec-not-mutated on violation); threads
    `claim_inventory.tsv` from M1 standard location
    (`<draft_dir>/working/00_phase0/claim_inventory.tsv`); new
    `LoopState.findings_invariance_violated` distinct from
    `findings_failed` (DQ3 hard-reject: no retry-counter increment);
    `next_actions.md` surfaces invariance violations as a distinct
    line; new `_process_finding` return value
    `"revise_invariance_violated"`. 6 new unit tests; suite 1209
    passed.
  - **Tier C — P3 retirement** (commit `79e863a`): rewrite-in-place
    per DQ4 / D-061 — `validate_p3_numeric_provenance(spec, draft_dir)`
    wraps `check_quantitative_grounding.check_grounding(draft_dir)`
    (the v0.4 REPORT-walking authority); HIGH-severity ungrounded →
    `Violation(severity="error")`; medium/low intentionally NOT
    lifted (D-061 anti-double-lift split: cascade Tier-1
    `_read_quantitative_grounding` aggregator already lifts those as
    P1/P2 advisory). Cascade `_P0_VALIDATORS` re-added P3 →
    `{"P3", "P4", "P5"}` (D-058 obsolete). v0.3
    `speaker_notes_provenance` contract retired (no fallback;
    legacy `draft_dir=None` callers get `status="skipped"`). 3 v0.3
    P3 tests replaced with 5 v0.4 P3 tests; suite 1212 passed.
  - **Tier D — docs** (commit `5babab8`): `SPEC.md` §13.1 + §13.2
    updated with v0.4 P3 mechanism + severity mapping;
    `DECISIONS.md` D-059 (P3 retirement closes D-058), D-060
    (DQ1 heuristic + DQ2 per-slide hedge), D-061 (DQ3 hard-reject
    + DQ4 split).
  - **Tier E — live + synthetic smoke** (commit `807dbe6`): E1
    re-ran cascade on `ibd_phage_targeting/draft_1` — 586 → 306
    findings (282 v0.3-style P3 false-positives gone), P0 went
    0 → 2 (the two real high-severity ratios on slides 8 and 24),
    `short_circuited_at: tier1` ✓ — fail-fast restored on real
    numeric defects, the cascade-saves-Tier-3-spend property
    promised by D-058 now operational. E2 synthetic
    `revise_invariance` CLI: citation-deletion → `rc=1`
    `verdict=fail`; clean prose tightening → `rc=0` `verdict=pass`.
    All at $0.0000 (E1 was cascade `--no-tier2 --no-tier3`; E2 was
    offline CLI).
  - **Tier F — closeout**: this section; `LAYOUT.md` updated for
    `revise_invariance.py`; `DECISIONS.md` D-059..D-061;
    `M5a_PUNCH_LIST.md` status table closed; auto-memory updated.
  - **Carried out of M5a** (deferred):
    - `_extract_numeric_claims` helper in `validate_presentation.py`
      is now dead code (the v0.3 P3 walker); only referenced by its
      own unit tests. Could be removed in a future cleanup. Defer.
    - Tier 2 prompt v2 expansion (carried from M4b).
    - Persist Tier-2 cost into `audit/review_tier2.json` (carried
      from M4b).
    - Portable visual-QA path for end-user revise loops (carried
      from M4a).

- **M5b — AI Studio image-gen multi-provider.** AI Studio provider
  in `image_client.py`; auth discovery; model-availability probe
  (`gemini-3-pro-image` → `gemini-2.5-flash-image` → fail per D-035);
  calibration re-run. Pure provider extension; no architectural
  change. Deferred from M5a per Adam's reorder (ship cheap-wins
  first).

**M6 — A/B test + cut-over decision.** Score sheet on
`ibd_phage_targeting`; sanity check on `functional_dark_matter`;
explicit go/no-go decision recorded in DECISIONS.md. State-schema
v0.3 → v0.4 migration script. Make `--architecture-pipeline v0_4`
the default on M6 pass; deprecate v0.3.x prompts (move to
`prompts/archive/v0_3/`).

---

## 17. Decisions captured (2026-05-12)

All twelve sign-off items resolved. They land as D-030 through D-041
in `DECISIONS.md`.

| Q | Decision | Where it lives | D-N |
|---|---|---|---|
| Q1 | Discrepancy_register port: **NO** — paper-Methods-specific | §4.0 + §19 | D-030 |
| Q2 | Architect default model: **Opus 4.6** (Sonnet opt-in via `--architect-model`) | §6.8 | D-031 |
| Q3 | Composer-architect deviation contract: **RIGID** (halt + re-architect) for v0.4 pilot | §7.2 | D-032 |
| Q4 | Speaker notes fusion into slide_compose: **YES** (per-substory worker writes both) | §7.3 | D-033 |
| Q5 | Revise-verb invariance post-check: **5 hard invariants** per §13; layout-change forbidden via revise | §13 | D-034 |
| Q6 | AI Studio model-probe fallback chain: gemini-3-pro-image → gemini-2.5-flash-image → fail | §14.2 | D-035 |
| Q7 | Cut-over gate threshold: **≥5 of 7 metrics**; wall-clock mandatory primary metric | §15 | D-036 |
| Q8 | M6 reviewer pool: **Adam-only** for v0.4.0 (matches paper-writer Q8) | §15 | D-037 |
| Q9 | Phase enum + state.json migration: **hard schema bump to "0.4"**; migration script at M6 | §10 | D-038 |
| Q10 | Wall-clock primary-metric target: **≥30% reduction** on talk-45 STRONG vs v0.3.8 (hub) | §11 + §15 | D-039 |
| Q11 | Vendor `extract_methods.py` from paper-writer at M1: **YES** | §4.5 + §16 M1 | D-040 |
| Q12 | Cut-over A/B in both work modes: **YES** — must dominate v0.3.8 on `ibd_phage_targeting` (paper-exists) AND `functional_dark_matter` (no-paper) | §15 | D-041 |

M0 is complete on these decisions.

### v0.4.1 revision decisions (2026-05-23)

Layered on top of M0 after the outline probe; see §20 for the full
rationale. Also mirrored in `DECISIONS.md`.

| Decision | Where | D-N |
|---|---|---|
| M2 reshaped: heavyweight "deck architect" → lightweight **M2-lite "deck-outline call"** (enrich `substory_design.v1`; terse prescriptive outline; no rigid JSON contract, no `check_architecture_drift.py`, no architecture-time validators) | §20 | D-042 |
| Outline-call model: **Sonnet 4.6**, not Opus 4.6 — supersedes **D-031** (it emits an outline, not a frozen contract) | §20 | D-043 |
| Composer–outline contract: **advisory**, not rigid — supersedes **D-032** (drop the halt-and-re-architect loop, `architecture_conflict`, `architecture_blocked`) | §20 / §7.2 | D-044 |
| `deck_architecture_pick` user gate **removed** — throughline-pick is the single human gate; the outline flows through — supersedes **§6.7** | §20 / §10.1 | D-045 |

---

## 18. Pointers

- **Architecture decision frame:** this document.
- **Sister-skill reference:** `spike/beril-paper-writer-skill-draft/SPEC_v0_8.md`
  for the subtraction-over-addition frame, the tiered-cascade pattern,
  and the semantic-invariance post-check pattern.
- **Quantitative motivation:** `V0_4_0_PUNCH_LIST.md` gap analysis
  (per-substory fan-out 80% of wall-clock, 86% of cost).
- **Reference projects:** `ibd_phage_targeting` (M6 A/B target);
  `functional_dark_matter` (sanity-check, STRONG-tier).
- **v0.3.x state:** `RELEASE_NOTES.md`, `LAYOUT.md`, `DECISIONS.md`
  D-001 through D-029.
- **Per-milestone discipline reference:**
  `feedback_punch_list_release_pattern.md`,
  `feedback_cross_skill_contract_drift.md`,
  `feedback_sandbox_bash_vs_intermediate_checks.md` from auto-memory.

---

## 19. What's intentionally NOT in this memo

- **`discrepancy_register` port.** Paper-Methods-specific; the deck
  doesn't carry the same plan-vs-execution surface. Deferred per the
  v0.3 critique recommendation #6.
- **`iterative citation rounds` (paper-writer §9).** Talks cite ≤8
  short-form citations; the 5–8-round adaptive-stop pattern doesn't
  scale down to that volume. Existing reuse-from-paper-writer +
  scope-down/citation-request/accept-as-limitation is right-sized.
- **`Phase 7 copy edit` (paper-writer §11).** Slides have no
  paragraph-level prose; the equivalent surface is bullet-density
  and arc consistency, which Tier 2 review already addresses.
  Speaker notes *do* have prose and *could* use a copy-edit pass —
  deferred to v0.5 unless empirically needed.
- **Holistic single-call deck composition.** Rejected per §1.2:
  the IBD evidence is paragraph-level, slides are atomic. Architect-
  then-parallel-compose is the answer that preserves the
  parallelism + per-slide depth properties.
- **Free-form architect deviation (advisory mode).** v0.4 ships
  rigid contract; advisory mode considered for v0.5 if empirically
  warranted (§7.2).
- **`--audience lay` axis.** Out of v1 scope per D-001; orthogonal
  to v0.4 architectural pivot.

---

## 20. v0.4.1 revision — M2-lite (2026-05-23)

This section is authoritative for Phase 2 (M2). It supersedes §6, the
§7.2 rigid deviation contract, and the §10.1 phase enum, and lands
decisions D-042–D-045 (§17). §6/§7.2 are retained as the M0 design
record.

> **M2-lite SHIPPED 2026-05-23.** `deck_outline.v1.md` (the prompt),
> `parse_deck_outline.py` (+ 15 tests), and the orchestrator wiring
> (`--architecture-pipeline v0_4` → `stage_deck_outline`) are in tree.
> Tier D smoke on `ibd_phage_targeting` produced a real enriched
> `02_substories.md` — transitions chain, headline slots clean,
> budgets within mode. Build log: `M2_PUNCH_LIST.md`; retrospective:
> auto-memory `project_presentation_maker_v0_4_m2.md`. §20.8 records
> the M3-carried dependency (`phase0_tooling` wiring).

### 20.1 What changed, and why

The M0 design made Phase 2 a heavyweight **deck architect**: one Opus
call emitting a rigid `01_deck_architecture.json` that pre-assigns
every slide field, policed by `check_architecture_drift.py` + six
architecture-time validators, behind a `deck_architecture_pick` user
gate. v0.4.1 replaces that with **M2-lite: a shared-outline call**.

Two findings drove the change:

1. **Parallelization and coordination are separable.** §1.3 bundled
   them ("don't pay the parallelism cost without paying the
   architecture cost"). Re-examination (2026-05-22) found the bundling
   has a hole: today's deck is *already* composed by uncoordinated
   per-substory composers — just sequentially. Running them in
   parallel is no *less* coherent than today's shipped output, just
   faster. So parallelization (M3) is the safe wall-clock win and can
   be banked independently; the architect is a *separate* bet on
   coherence.

2. **The coordination gain comes from prescriptions, not a contract.**
   The outline probe (§20.7) showed a composer given a shared outline
   beats one without — but the gain is driven by terse explicit
   *prescriptions* (headline-slot assignments, per-section transition
   sentences, budgets, register spec), not by a rigid per-slide
   contract and not by "seeing the whole" (the composer already sees
   the whole via `00_throughline.md` + `02_substories.md`). A rigid
   `01_deck_architecture.json` + drift-checker is over-engineering for
   the gain actually on offer.

### 20.2 M2-lite — the deck-outline call

Phase 2 is a single `deck_outline.v1` call that emits a **prescription
sheet**, not a contract. Implementation: enrich the existing
`substory_design.v1` (substory clustering) into `deck_outline.v1` — an
evolution of an existing prompt, not a new heavyweight agent. Sonnet
4.6 (D-043). Per section the outline carries: punchline, slide budget,
headline-number slot assignment, explicit transition-in / transition-
out sentences, scoped figures + claim_ids, and a deck-level register
spec. It pre-assigns only the **scarce / conflict-prone** resources
(figures, the headline `big_number` slots, the deck image budget,
transition placement) and leaves all local composition (bullet
wording, punchline phrasing, speaker-notes seed, which in-scope claim
to foreground) to the composer.

**Dropped vs §6:** `01_deck_architecture.json` as a rigid schema;
`deck_architecture.py` (the JSON-schema validator);
`check_architecture_drift.py`; the six §8.3 architecture-time
validators; the Opus model (D-031 → D-043); the §6.7
`deck_architecture_pick` user gate (D-045 — throughline-pick is the
single human gate; the outline flows straight to the composers).

### 20.3 Per-section composer brief

Each parallel composer (M3) receives: (1) the whole outline +
throughline, structured as a cacheable shared prefix so the N parallel
calls share prompt cache; (2) its boundaries — section punchline +
budget, what the prior section closes on (transition-in) and what the
next opens (hand-off); (3) its scoped content — the slice of
`claim_inventory.tsv` + the figures the outline assigns it (a scope
hint, not a forbidden-to-deviate contract); (4) its visual brief —
`diagram_design` for data/procedural diagrams, `ai_image_prompt` for
concept illustrations, plus this section's image budget. The §7.1
composer narrowing still applies; the §7.2 rigid deviation contract
does not (D-044).

### 20.4 Post-merge reconciliation

Parallel composers cannot see each other's in-flight output, so the
outline pre-assigns the scarce resources above AND a ~30-line
post-merge reconciliation checker flags residual conflicts (duplicate
figure use, two headline `big_number` slides, total image count vs the
deck budget). This replaces `check_architecture_drift.py`: it checks
for *conflicts*, not *contract adherence*.

### 20.5 Effort + sequencing

M2-lite is **~12–18h** — the low end of the original M2 estimate; the
dropped schema/validator/drift-checker machinery was the bulk of the
heavyweight cost. M3 (parallelization) is separable and may be banked
first as the wall-clock win. M4 / M6 are unchanged from §16. M5 is
unchanged but note its §14 AI Studio image-gen provider is **confirmed
not yet implemented** (verified 2026-05-22 — `image_client.py` is
CBORG-only) and remains real M5 work.

### 20.6 Risk note

The outline probe tested whether an *ideal* (hand-written) outline
helps the composer — Risk 1. It did not test whether the
`deck_outline.v1` LLM call can reliably *generate* a good outline —
Risk 2. Risk 2 looks manageable precisely because the load-bearing
elements are structured prescriptions (slot assignments, budgets,
one-sentence transitions), which an LLM emits reliably — far more so
than subtle prose coordination. If M2-lite composition quality
disappoints, the first place to look is outline-generation quality,
not the composer.

### 20.7 Probe evidence

The outline probe (`experiments/m2-outline-probe/` — README has the
full method) composed 3 `ibd_phage_targeting` substories with
`slide_compose.v1.md`, over two runs:

- **Run 1 (2026-05-23):** conditions **B** (naive parallel — no prior
  fragments, no outline) and **C** (with the hand-written outline).
  6 calls, $2.93.
- **Run 2 (2026-05-23):** conditions **A** (today's sequential
  pipeline — `PRIOR_SUBSTORY_OUTPUTS` chained), **B**, **C**. 9 calls,
  $3.96.

**Transitions — A ≈ C > B.** Both A and C produced explicit lead-in
bridges (run 2: `A_S2` and `C_S2` both open with a "Bridge from S1"
tee-up; `B_S2` opened cold on its own terms — consistent with run 1).
A bridges because today's *sequential* composer sees the prior
substory's actual composed fragment; C bridges because it has the
outline. B — naive parallel — has neither and loses the transition.

The decisive reading: **M2-lite does not regress vs today's pipeline,
and its real value is coordination-preservation under parallelism.**
A gets good transitions *only* by being sequential — it cannot be
parallelized without becoming B. C gets the same transition quality
*and* is parallelizable. M2-lite is the layer that lets M3 parallelize
without dropping to B-grade coordination — exactly the "coordination
layer that makes parallelism safe" §1.3 posited, now evidenced.

**Other dimensions.** C follows the outline's headline-slot
prescriptions where there is a real choice — only C made the 8,489
sample count S1's `big_number` (A used 73%, B none); the 88.2% S2
headline was picked by all three because it is the obvious choice. C
is consistently the most structurally uniform (uniform section-opening
layout in both runs). Hedge discipline is *not* a differentiator — all
three handle partial-evidence claims well.

**Corrected from the run-1 single-run read.** Run 1 suggested C beat B
on slide-budget discipline (B overran S3 to 6 slides). Run 2 did not
replicate this — all three conditions hit the 5-slide S3 budget. The
overrun was LLM non-determinism, not a systematic naive-parallel
defect; budget is *not* a reliable C-vs-B differentiator.

**Confidence.** n=2 runs; LLM non-determinism is real (the budget
finding is a live example of why n>1 matters). The findings that
*replicated* — `A ≈ C > B` on transitions, C the most structurally
uniform — are the load-bearing evidence for D-042. The verdict (build
M2-lite) holds: parallelization without M2-lite drops to B-grade
coordination; M2-lite restores A-grade coordination while keeping
parallelism.

### 20.8 M2-lite ship state (2026-05-23) and the M3-carried dependency

> **RESOLVED 2026-05-23.** The M3-carried dependency described below —
> wiring `phase0_reuse.py` into the orchestrator — shipped in M3 Tier A
> (`stage_phase0_tooling` + the v0.4 dispatch re-sequencing). M3 is
> structurally complete; see `M3_PUNCH_LIST.md` and §16 M3.

M2-lite shipped 2026-05-23. In tree: `deck_outline.v1.md` (the prompt,
an enrichment of `substory_design.v1`), `parse_deck_outline.py` (+ 15
tests; `parse_substories.py` left untouched and still parsing the
carried skeleton), and the orchestrator wiring — a `stage_deck_outline`
function plus a `--architecture-pipeline {v0_3|v0_4}` flag that selects
it over `stage_substory_design` at the clustering slot. The v0.3.x
default path is unchanged. The Tier D smoke on `ibd_phage_targeting`
produced a real enriched `02_substories.md` (transitions chain,
headline slots clean, budgets within mode); one D-phase prompt patch
landed — the headline-slot rule, corrected so a measured proportion is
a valid headline, not only a hypothesis-test statistic. Build log +
per-tier table: `M2_PUNCH_LIST.md`.

**M3-carried dependency.** `deck_outline` reads the Phase-0 artifacts
(`claim_inventory.tsv`, `methods_provenance.md`) from
`working/00_phase0/` — produced by `phase0_reuse.py`, the M1 helper.
`phase0_reuse.py` is not yet wired into `presentation_maker.sh` (M1
Tier F1), so the v0.4 orchestrator path cannot run end-to-end until M3
adds a `phase0_tooling` stage that invokes it. This did not block M2:
the Tier D smoke ran `deck_outline` standalone with the Phase-0 inputs
passed directly. M3 owns: `phase0_tooling` wiring, the per-section
composer brief, the parallel worker-pool, and the post-merge
reconciliation check.

---

**End of memo.** M0 deliverable (signed off 2026-05-12): Adam's
sign-off on Q1–Q12 in §17. **v0.4.1 revision (2026-05-23):** M2
reshaped to M2-lite per §20 + D-042–D-045, after the outline probe.
M1 shipped 2026-05-21; **M2-lite shipped 2026-05-23 — M3 (parallel
composition) is next.**
