# M4b Punch List — Tiered review cascade

**Filed:** 2026-05-24. **Status: PROPOSED — awaiting Adam's sign-off on
DQ1–DQ4 at the start of the M4b build session.**
**Milestone:** M4b of the v0.4 pivot. M4 was split (Adam, 2026-05-23)
into **M4a — visual-QA + content discipline** (shipped 2026-05-24,
commit `7ff16d0`) and **M4b — tiered review cascade** (this).
**Predecessor:** M4a (renderer mechanism + content caps + visual-QA pass
available as opt-in `--visual-qa`); commit `7ff16d0`.
**Successor:** M5 — image-gen multi-provider + revise-invariance
(`V0_4_ARCHITECTURE.md` §16 M5).
**Design source:** `V0_4_ARCHITECTURE.md` §8 (Phase 4 — Tiered review
cascade, fail-fast) + §16 M4b sketch + D-049 (Tier-2 detection-class
calibration deferred here) + D-050 (visual-QA opt-in; revisit as M4b
Tier-1 candidate).

## Status

| Tier | Scope | Status |
|---|---|---|
| A — `review_cascade.py` orchestrator scaffolding | new `tools/review_cascade.py` + `presentation_maker.sh` wiring | ✅ committed 2026-05-24 (cascade contract `review-cascade.v1`; per-tier dispatchers return `not-implemented` until B/C/D fill in; orchestrator auto-runs cascade per DQ1 with `--no-review-cascade` opt-out; suite 1127 passed) |
| B — Tier 1 (deterministic + visual-QA aggregation) | `review_cascade.py`'s Tier-1 dispatcher; reuses existing checkers | ✅ committed 2026-05-24 (aggregates 5 sources: P1-P10 + quantitative_grounding + no_artifact_refs + deck_reconciliation + opt-in visual_qa per DQ2; P0/P1/P2 classification per DQ4 — only P3/P4/P5 fail short-circuits; writes `audit/presentation_validation.json` side-effect; suite 1139 passed) |
| C — Tier 2 (Haiku narrative-light) + empirical detection-class calibration (D-049) | new `tools/review_tier2.py` + prompt; calibration probe | ✅ committed 2026-05-24 (`prompts/review_tier2.v1.md` + `tools/review_tier2.py` ship the 4 detection classes per §8.1; claude-haiku-4-5 pinned per DQ3 ship-as-v1; cascade `_invoke_review_tier2` + DQ4 invariant pin (rogue P0 demoted to P1); 16 Tier-2 tests + 3 cascade-dispatcher tests; suite 1158 passed. C3 calibration probe deferred to Tier E + post-ship per DQ3.) |
| D — Tier 3 (wrap canonical adversarial under the cascade contract) | `review_cascade.py` integrates `stage_adversarial_review` | ✅ committed 2026-05-24 (cascade `run_tier3` invokes `beril-adversarial review --type presentation` directly; parses v3 schema into cascade findings (P1 advisory; `central_objection` lifted as its own finding); orchestrator de-dup: standalone `stage_adversarial_review` elides when cascade's Tier 3 status in (`pass`, `advisory`, `fail`); revise loop unchanged (still consumes `audit/adversarial_review.json`); suite 1162 passed) |
| E — end-to-end cascade smoke on `ibd_phage_targeting` | live | ✅ committed 2026-05-24 (3 live rounds + 4 integration tests). r1 revealed P3 v0.3-era contract → D-058 demotes P3 on v0.4. r2 revealed missing `--beril-root` → `_invoke_beril_adversarial` resolves via explicit arg → env → walk-up-4-parents. r3 revealed Tier 3 v3 schema uses `class`/`issue` (not `kind`/`summary`) and `central_objection` is a regular finding (not top-level); cascade-Tier-3 lifter fixed to use real v3 shape + preserve v3 severities (P0/P1/info → cascade P0/P1/P2). r3 produced: T1 advisory 586 findings, T2 advisory 6 findings (all 4 classes; ~$0.05; 121.7s), T3 advisory 14 findings (8 classes, 5 P0, 1 central_objection; 9.3 min). Calibration capture at `audit/review_tier2_calibration.md` (DQ3 ship-then-iterate ratified; v2 prompt-iteration candidates listed). Suite 1174 passed. |
| F — closeout | paperwork | ⬜ not started |

## Why M4b exists — the gap M4a doesn't close

M4a gave us the *mechanism* (renderer shrink-to-fit) and *upstream
discipline* (content caps + soft-warning channel) and a *visual* detector
(opt-in `--visual-qa`). What's still missing: a single **review orchestrator**
that runs the existing mechanical checks (P1–P10 + advisory + visual-QA)
+ a cheap LLM pass + the canonical adversarial review in **fail-fast
order**, so a deck with a P3 numeric-provenance violation never pays the
~$1.50 adversarial review cost.

The components mostly exist; M4b *integrates* them and *adds* the
missing Tier 2 (cheap LLM with 4 detection classes empirically chosen
from the adversarial v3 schema). The integration matters because today
the orchestrator runs:

- `stage_merge_and_assemble`'s end-of-stage checks (quant-grounding +
  process-detail-bleed + deck reconciliation + opt-in visual-QA) —
  advisory only, never short-circuit
- `stage_adversarial_review` → `stage_revise_slides` — full canonical
  Tier 3 with no fail-fast guard

A P3 fail on assemble currently still pays the full ~$1.50 adversarial
review. Fail-fast cascade gating fixes that.

## Scope

M4b ships an opt-in **cascade orchestrator** (`review_cascade.py`) that
runs after `stage_merge_and_assemble` and before `stage_adversarial_review`,
short-circuits when a tier emits a P0 finding, and surfaces a structured
cascade report at `audit/review_cascade.{md,json}`. Tier 3 still calls
`beril-adversarial`; Tier 2 is the new Haiku pass; Tier 1 wraps the
existing mechanical checks.

**What M4b is NOT:** image-gen multi-provider (M5); revise-invariance
post-check (M5); the A/B cut-over (M6); the visual-QA prompt iteration
deferred from M4a (separate prompt-edit task, NOT cascade scope).

**Cost discipline (`feedback_cost_record_dont_gate`):** per-tier cost
is recorded in the cascade diagnostic; no `--max-cost-usd` cap on the
cascade itself. Tier 3 inherits the existing `MAX_REVISE_COST_USD` cap.
Tier 2 cost (~$0.05/run on Haiku) is well below caps that would change
behaviour.

## Open design questions — need Adam's sign-off before the affected tier

> **RESOLVED 2026-05-24 (build session open).** All four signed off by Adam.
> DQ1 → **auto-run** (cascade auto-runs by default; opt out via `--no-review-cascade`).
> DQ2 → **(b) — cascade reads `audit/visual_qa.json` if present, ignores otherwise** (preserves M4a `--visual-qa` opt-in posture); Adam emphasized: **the `--visual-qa` option needs prominent documentation** in HUB_INSTALL + README + SKILL.md so operators discover when/why to opt in. Tier F docs work is load-bearing.
> DQ3 → **(c) — ship §8.1 candidate-four classes as v1**, one calibration probe against re-run Tier-3 adversarial for validation; fine-grained calibration deferred to post-ship.
> DQ4 → **operator-gated** — Tier-1 P0 short-circuits later tiers; Tier-2 always advisory (never gates Tier 3); Tier 3 runs unless `--no-adversarial`.
> Land as D-054..D-057 in Tier F.

**DQ1 (gates Tier A) — opt-in or auto-run?** M4a's visual-QA is opt-in
via `--visual-qa` (D-050) because vision-LLM cost was unknown. **The
cascade is different**: Tier 1 is ~free, Tier 2 is ~$0.05, Tier 3 is
already running by default (only `--no-adversarial` skips it). Making
the cascade auto-run gives the fail-fast value (skip Tier 2/3 when
Tier 1 flags P0); making it opt-in defeats the point.
**Recommendation: auto-run by default**, off via `--no-review-cascade`
(matching the `--no-adversarial` / `--no-images` opt-out pattern). The
existing `stage_adversarial_review` becomes the cascade's Tier 3, gated
by the same `NO_ADVERSARIAL=0` check; the cascade ONLY changes the
control flow, not the per-tier cost discipline.

**DQ2 (gates Tier B) — does `--visual-qa` become a Tier-1 component?**
Per D-050 the answer was "revisit when M4b ships." Two options:
(a) Tier 1 always includes visual-QA (changes the default cost model —
auto-running adds ~$0.6–0.8/draft of vision-LLM); (b) visual-QA stays
opt-in via `--visual-qa` AND is consumed by Tier 1 *only when the flag
is set* (cascade reads `audit/visual_qa.json` if present, ignores
otherwise). **Recommendation: (b)** — preserves M4a's portability
posture (skill ships without LibreOffice/Poppler hard dep), avoids
auto-spending vision-LLM, and the cascade still gets the value when
the operator opts in. If we want auto-run later, that's a flag flip,
not a contract change.

**DQ3 (gates Tier C) — Tier-2 detection-class calibration: how + on
what data?** D-049 deferred empirical calibration to M4b. §8.1 names
four candidate classes (`register_drift`, `qa_softball`,
`unbacked_quantitative`, `substory_arc`). Calibration needs ground
truth: the adversarial Tier-3 v3 schema output on a real deck tells us
which classes are most useful to catch cheaply at Tier 2 vs which only
Tier 3 sees. Three options:
- **(a) Calibrate on `ibd_phage_targeting` round-1 adversarial output** —
  we have a fresh Tier-3 review from this past session (well, would
  have if we ran `--adversarial` on the M4a-closed deck; we deliberately
  passed `--no-adversarial` in Tier E to stay scoped). One real
  reference + cheap to add: re-run adversarial on the current deck,
  use the v3 findings to calibrate Tier-2 prompt scope. Cost: ~$0.50–$1.50.
- **(b) Calibrate by inspection of paper-writer's calibration data** —
  paper-writer has a Stage-2-like detection-class probe per `SPEC_v0_8.md`
  §7.5; borrow the calibration approach (the empirical-precision/recall
  per class) without running new spend.
- **(c) Ship Tier 2 with the §8.1 candidate-four as a v1 starting
  point + a follow-on calibration task** — accept that calibration is
  best done after Tier-2 has been used in anger and we have multiple
  drafts' worth of finding data. The empirical work becomes "M4b round 2"
  or M6 pre-cutover.
**Recommendation: (c) for the M4b ship**, with (a) as the validation
gate (one calibration pass against the ibd_phage_targeting Tier-3 output
to confirm the §8.1 four classes catch a non-trivial fraction of what
Tier-3 catches). Defer fine-grained calibration to post-ship. This
matches M4a's posture (ship the mechanism; iterate the parameters with
real data).

**DQ4 (gates Tier D) — fail-fast semantics: what is a P0?** The cascade
short-circuits on P0 findings. Three definitions in play:
- **Strict P0**: only validator-emitted P0s (P3 numeric-provenance
  fail, P4 citation-pool drift, P5 brand-color violation) short-circuit.
  Tier 2 + Tier 3 always run unless one of these mechanical P0s fires.
- **Inclusive P0**: any Tier-1 or Tier-2 high-severity finding (P0 +
  adversarial v3 `central_objection` + visual-QA `confidence=high`
  container_breach) short-circuits later tiers.
- **Operator-gated**: Tier 1 P0 short-circuits Tier 2/3 by default;
  Tier 2 findings are advisory (never gate Tier 3); Tier 3 is
  unconditional.
**Recommendation: operator-gated** — Tier 1 P0 short-circuits later
tiers (fail-fast value); Tier 2 is light + advisory (one prompt,
findings logged but never block Tier 3); Tier 3 runs always (unless
explicitly `--no-adversarial`). Keeps the cascade's value (Tier 1 catches
mechanical fail cheap), keeps Tier 3's authority (the canonical reviewer
sees everything Tier 1+2 didn't catch), and avoids Tier 2 becoming a new
gate before the calibration data is in.

---

## Tier A — `review_cascade.py` orchestrator scaffolding

New file `tools/review_cascade.py` modeled on `reconcile_deck.py`
(advisory CLI shape, rc=0). Standalone tool; calls per-tier helpers;
writes `audit/review_cascade.{md,json}` with structured per-tier
results.

**A1. Cascade contract.** Schema for `review_cascade.v1`:

```json
{
  "schema_version": "review-cascade.v1",
  "draft_dir": "<absolute path>",
  "tiers": [
    {"name": "tier1", "status": "pass|fail|short-circuit-blocked",
     "findings": [...], "cost_usd": 0.0, "duration_sec": ...},
    {"name": "tier2", "status": "...", "findings": [...], "cost_usd": 0.05, ...},
    {"name": "tier3", "status": "...", "findings": [...], "cost_usd": 0.85, ...}
  ],
  "short_circuited_at": "tier1|tier2|null",
  "total_cost_usd": 0.85,
  "total_duration_sec": 12.3
}
```

**A2. `review_cascade.py` CLI.** `python3 review_cascade.py <draft_dir>
[--no-tier2] [--no-tier3] [--quiet]`. Always rc=0 (advisory; like
`reconcile_deck.py`). Reads `working/slide_spec.json`; calls Tier 1
dispatcher → Tier 2 (if Tier 1 cleared OR `--keep-going`) → Tier 3 (if
Tiers 1+2 cleared OR `--keep-going`).

**A3. Orchestrator wiring** (`presentation_maker.sh`). Cascade runs
between `stage_merge_and_assemble` and `stage_adversarial_review`:
- Add `--no-review-cascade` flag (default off; cascade auto-runs per DQ1).
- New `stage_review_cascade` invokes `review_cascade.py`; on
  short-circuit, the existing `stage_adversarial_review` is skipped (the
  cascade ran it as Tier 3 OR Tier 1 short-circuited it).
- Cost note: when cascade is on, the standalone `stage_adversarial_review`
  is the *cascade's* Tier 3 (one adversarial run, not two).

**AC for A:** unit tests cover the cascade contract (schema, status
transitions, short-circuit detection); `bash -n` clean; orchestrator
wiring on the v0.3 + v0.4 paths (both pipelines call cascade the same
way). No live spend.

## Tier B — Tier 1 (deterministic + visual-QA aggregation)

Tier 1 reuses every existing mechanical checker; the new code is
aggregation logic + a structured P0/P1/P2 classification.

**B1. Aggregate the existing checks** into a single `tier1_run()`
function in `review_cascade.py`. Checks in fail-fast order (cheapest first):
- `validate_presentation.py` P1–P10 mechanical validators
- `check_quantitative_grounding.py` (advisory severity)
- `check_no_artifact_refs.py` (advisory severity)
- `reconcile_deck.py` (cross-section conflict checker; advisory)
- `audit/visual_qa.json` (if present — see DQ2; cascade reads but does
  NOT invoke visual_qa.py; opt-in `--visual-qa` is the only way to
  populate)

**B2. P0/P1/P2 classification.** Per SPEC §13's tier-classification:
- **P0** (short-circuits): P3 numeric-provenance fail, P4 citation-pool
  fail, P5 brand-color fail (per validate_presentation.py).
- **P1** (advisory, no short-circuit): every other validator fail, every
  advisory checker finding, every visual-QA finding with
  `confidence="high"`.
- **P2** (informational, no short-circuit): visual-QA findings with
  `confidence="medium"|"low"`, soft-warnings from the assembler.

**B3. Tier-1 output**: the cascade JSON's `tiers[0]` entry carries the
short-circuit decision + the structured finding list.

**AC for B:** unit tests assert the short-circuit triggers on a
synthetic spec that fails P3; clears on a clean spec. Integration smoke
on `ibd_phage_targeting/draft_1` (which we KNOW passes P3 + everything
else from the M4a Tier E rounds) — cascade Tier 1 clears, Tier 2 runs.

## Tier C — Tier 2 (Haiku narrative-light) + calibration probe

New `tools/review_tier2.py` + `prompts/review_tier2.v1.md`. Single
Haiku call (~$0.05). Inputs: `working/slide_spec.json` +
`narrative/00_throughline.md` + `narrative/02_substories.md` +
`audit/quantitative_grounding.json` (for the unbacked_quantitative
cross-walk).

**C1. `tools/review_tier2.py`** — same shape as `tools/visual_qa.py`:
probe Haiku availability, build user prompt with absolute paths,
invoke `claude -p` with model pinned to Haiku 4.5
(`claude-haiku-4-5-20251001`), allowed tools `Read,Write`, output
format JSON for cost envelope. Writes
`audit/review_tier2.{md,json}` with the structured finding list.

**C2. `prompts/review_tier2.v1.md`** — vision-prompt-shaped (mirrors
`visual_qa.v1.md`) with 4 detection classes per §8.1:
- `register_drift` — fast pattern detection
- `qa_softball` — question-mark / low-novelty heuristic on
  qa_anticipated slides
- `unbacked_quantitative` — cross-walk against
  `quantitative_grounding.json`'s ungrounded list
- `substory_arc` — cross-slide arc coherence (the M2-lite outline gives
  a deterministic frame: each substory has a punchline; the slides
  assigned to that substory should land it)

Structured JSON output; advisory severity always (per DQ4 — Tier 2
findings never gate Tier 3).

**C3. Calibration probe.** ONE pass: run Tier 2 on the
`ibd_phage_targeting/draft_1` deck (M4a-closed state), compare the
4-class findings to the existing Tier 3 adversarial v3 output (re-run
adversarial on the M4a deck — required spend, ~$0.50–$1.50). Record:
- How many Tier-3 findings would Tier-2 have caught (recall)?
- How many Tier-2 findings are NOT real (precision; i.e., Tier 3
  doesn't ratify them)?
- Per-class breakdown.
Result lands as a one-page calibration note + a Tier C task close —
NOT a parameter tune of the prompt yet (per DQ3-(c): ship + iterate
with real data).

**AC for C:** prompt diffs reviewed by Adam before any live spend
(mirrors M4a Tier B). `review_tier2.py` test suite mocks the
subprocess (same pattern as `test_visual_qa.py`). Calibration probe
output captured in `audit/review_tier2_calibration.md`.

## Tier D — Tier 3 (wrap adversarial under cascade contract)

The existing `stage_adversarial_review` already invokes
`beril-adversarial review --type presentation`. M4b's contribution:
make Tier 3 a cascade member, not a parallel-but-uncoordinated stage.

**D1. Cascade-aware Tier 3 wrapper.** New function in
`review_cascade.py` that calls `beril-adversarial review` the same way
`stage_adversarial_review` does (or shells to that stage) and parses
the v3 output into the cascade JSON schema. NO change to the
adversarial CLI; M4b just routes its output through the cascade
report.

**D2. Short-circuit semantics.** If Tiers 1+2 cleared, Tier 3 runs.
If Tier 1 short-circuited, Tier 3 skips (per DQ4 — Tier-1 P0 means we
have a known mechanical fail; running adversarial on a known-broken
deck is wasted spend). If Tier 2 fired only advisory findings (the DQ4
recommendation), Tier 3 runs anyway.

**D3. revise loop coupling.** `stage_revise_slides` still consumes
`adversarial_review.json` as today; no change. The cascade's Tier-3
findings ARE the adversarial_review.json (cascade re-uses the existing
filename + schema; doesn't re-invent it).

**AC for D:** unit tests on the wrapper (mocked subprocess); integration
on the M4a-closed `ibd_phage_targeting/draft_1` deck — cascade runs
Tier 1 (clear) → Tier 2 (some advisory findings) → Tier 3 (full
adversarial). Total cost recorded.

## Tier E — end-to-end cascade smoke on `ibd_phage_targeting`

Run the cascade on the M4a-closed deck (the same `draft_1` Tier E
exercised). Expect Tier 1 clear, Tier 2 emits findings, Tier 3 runs.
Also: a synthetic-defect smoke — inject a P3 numeric violation into a
test spec and confirm Tier 1 short-circuits.

**AC for E:** cascade produces `audit/review_cascade.{md,json}` with
all three tiers populated; total spend recorded; short-circuit case
confirmed on a synthetic-defect spec. Expect 1 round (no per-tier
iteration; the components all exist).

## Tier F — closeout

`V0_4_ARCHITECTURE.md` §16 M4b → SHIPPED; `LAYOUT.md`
(`review_cascade.py`, `review_tier2.py`, `review_tier2.v1.md`);
this punch list's status table; `DECISIONS.md` (DQ1–DQ4 → D-054..D-057);
auto-memory `project_presentation_maker_v0_4_m4b.md` + MEMORY.md.

## Dep edges

```
A ──┬──> B ──> E ──> F
    └──> C ──┬──> D ──> E
             └──> calibration probe (one-off, after C1+C2 ship)
```

A (orchestrator scaffold) unblocks B (Tier 1) and C (Tier 2). D (Tier 3
wrapper) depends on C's contract (so Tier 3 reads what Tier 2 wrote).
E integrates all three. The C3 calibration probe is a one-off after
C1+C2 land; doesn't block E.

## Smoke gates

- **A gate:** cascade contract test green; bash -n clean; orchestrator
  wiring code-walk + a `--resume-from` smoke that runs cascade without
  any tier spend.
- **B gate:** synthetic P3-fail spec triggers Tier 1 short-circuit;
  clean spec clears.
- **C gate:** prompt diffs signed off by Adam; mocked subprocess tests
  green; calibration probe output reviewed.
- **D gate:** wrapper contract test green; cascade JSON validates against
  the v1 schema after Tier 3 runs.
- **E gate:** cascade end-to-end on `ibd_phage_targeting/draft_1`
  produces a valid report with all three tiers; synthetic-defect smoke
  confirms short-circuit.

## What M4b does NOT do (→ M5 / M6)

- Image-gen multi-provider (AI Studio) + revise-verb semantic-
  invariance post-check (M5).
- State-schema v0.3 → v0.4 migration + the A/B cut-over decision (M6).
- The visual-QA prompt iteration deferred from M4a (separate prompt-edit
  task; not in the cascade's blast radius).

## Estimated effort

| Tier | Estimate |
|---|---|
| A — cascade scaffolding + orchestrator wire | 3–5 h |
| B — Tier 1 aggregation | 2–3 h |
| C — Tier 2 + calibration probe | 6–10 h (the largest tier; mirrors M4a Tier C) |
| D — Tier 3 wrapper | 2–3 h |
| E — end-to-end smoke | 2–4 h (includes the calibration adversarial run) |
| F — closeout | 1–2 h |

Total ~16–27 h over 3–5 working days. Lower bound than M4a because the
components mostly exist; the new code is integration + Tier 2.

## First action (M4b build session)

Read `CLAUDE.md` → `augmentation-stream-plan.md` → this file → auto-memory
`project_presentation_maker_v0_4_m4a.md` (the M4a retrospective; the
severity-aware ValidatorIssue + the assembler warnings channel are the
substrate the cascade builds on). Then Adam resolves DQ1–DQ4. Then
Tier A — the cascade scaffolding is the keystone; Tier 1/2/3 hang off
its contract.
