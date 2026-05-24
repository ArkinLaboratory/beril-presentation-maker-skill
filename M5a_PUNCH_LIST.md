# M5a Punch List — P3 retirement + revise_invariance post-check

**Filed:** 2026-05-24. **Status: PROPOSED — awaiting Adam's sign-off on
DQ1–DQ4 at the start of the M5a build session.**
**Milestone:** M5a of the v0.4 pivot. M5 was reordered (Adam,
2026-05-24) into **M5a — P3 retirement + revise_invariance** (this)
+ **M5b — AI Studio image-gen multi-provider** (deferred; biggest
spend / least urgent per Adam). M6 — A/B cut-over decision still
gated on M5b shipping.
**Predecessor:** M4b — tiered review cascade (commit `88658b8`,
pushed 2026-05-24); M4b D-058 scheduled the P3 retirement here.
**Successor:** M5b (AI Studio image-gen) → M6 (A/B cut-over).
**Design source:** `V0_4_ARCHITECTURE.md` §13 (revise-verb
semantic-invariance post-check — 5 hard invariants) + §16 M5
sketch + D-058 (P3 demote → retirement) + Q5/D-034 (revise-verb
invariance contract, M0-era sign-off).

## Status

| Tier | Scope | Status |
|---|---|---|
| A — `revise_invariance.py` + 5-invariant impl | new `tools/revise_invariance.py` | ✅ committed 2026-05-24 (5 invariants per §13: claim_id cross-walk via DQ1 heuristic, citation preservation, numeric preservation via reused `check_quantitative_grounding.extract_numbers`, hedge level per DQ2 per-slide aggregation, layout preservation; CLI rc=0/1 per DQ3; suite 1203 passed) |
| B — wire invariance into `revise_loop.py` (per-finding gate) | `revise_loop.py` edit | ✅ committed 2026-05-24 (`_check_revise_invariance` helper invokes `revise_invariance.py` via subprocess between LLM post-edit and in-spec merge; threads claim_inventory.tsv from M1 standard location; new `LoopState.findings_invariance_violated` distinct from `findings_failed`; `next_actions.md` surfaces invariance violations as a distinct line; new return value `"revise_invariance_violated"`; suite 1209 passed) |
| C — P3 retirement (rewrite as wrapper around `check_quantitative_grounding`) | `validate_presentation.py` + cascade `_P0_VALIDATORS` re-add P3 | ✅ committed 2026-05-24 (`validate_p3_numeric_provenance(spec, draft_dir)` wraps `check_grounding`; HIGH-severity ungrounded → Violation(error); medium/low intentionally NOT lifted to prevent double-lifting with cascade `_read_quantitative_grounding`; cascade `_P0_VALIDATORS` re-added P3 (D-058 obsolete); `validate_presentation` threads draft_dir to P3; 3 v0.3 tests replaced with 5 v0.4 tests; suite 1212 passed) |
| D — SPEC.md §13.1 docs update + DECISIONS update | `SPEC.md`, `DECISIONS.md` D-059..D-061 | ⬜ not started |
| E — end-to-end smoke on `ibd_phage_targeting` | live | ⬜ not started |
| F — closeout | paperwork | ⬜ not started |

## Why M5a exists — two cheap-wins before M5b's bigger spend

**Why P3 retirement (load-bearing for cascade fail-fast):**
D-058 demoted P3 from cascade P0 to P1 because v0.3-era
`speaker_notes_provenance` contract is dead on the v0.4 fused-notes
composer. The cascade's fail-fast value-prop is currently degraded:
the `_P0_VALIDATORS` set is just `{P4, P5}` (no numeric-provenance
short-circuit). Retiring P3 cleanly (replace with wrapper around
the v0.4-native `check_quantitative_grounding.py`) restores
fail-fast on numeric defects AND clears D-058's debt.

**Why revise_invariance now (load-bearing for revise loop trust):**
Today's revise loop accepts whatever the LLM emits for the post-
edit slide — it validates structural shape (P-validators) but doesn't
catch the silent semantic drifts the v0.3 critique memo flagged:
citation token lost mid-prose, "suggests" flipped to "demonstrates,"
a numeric assertion that wasn't on the prior slide, a layout change
that should have required re-architecting. Per V0_4_ARCHITECTURE
§13 (and Q5/D-034 sign-off), the revise verb needs the 5-invariant
post-check. Without it, M5b's `revise_invariance` deferral leaves a
real correctness gap that M4b's cascade exposes (Tier 3 finds these
silently broken; revise can't be trusted to fix without re-introducing).

**Why deferred AI Studio image-gen (per Adam):**
Biggest surface change (new provider; auth; calibration re-run; the
model-availability probe adds a network dep at startup). M4b cleared
the review-loop blocker; the image-gen work doesn't unblock anything
downstream of M5a. Defer to M5b; M6 cut-over can either include or
exclude it depending on M5b timing.

## Scope

**In scope:**
- `tools/revise_invariance.py` (~250 LOC): 5 invariant checks per §13.
- `revise_loop.py` wiring: invariance gate between post-edit LLM
  output and the in-spec merge. On invariance fail, reject the
  revision wholesale; emit `audit/revise_invariance/<finding.id>.json`
  + bump state's `findings_failed`.
- `validate_p3_numeric_provenance` rewrite: wrap
  `check_quantitative_grounding.check_grounding(draft_dir)` and
  map findings to ValidatorResult violations.
- Cascade `_P0_VALIDATORS` re-adds P3 (the new P3 is the v0.4-native
  check; D-058 demote no longer needed).
- SPEC.md §13.1 doc update.
- DECISIONS.md D-059 (P3 retirement closeout) + D-060/D-061 for the
  4 DQs below.

**What M5a is NOT:**
- AI Studio image-gen provider (M5b).
- `revise_loop.py` redesign (the 5-invariant gate plugs into the
  existing per-finding loop; no architectural change).
- New revise prompt iteration (the invariance check is content-only;
  prompt stays the same — if invariance fails, the LLM is signaled
  to retry, same as today's validator-fail retry).
- M6's v0.3→v0.4 state migration script.

## Open design questions — need Adam's sign-off before the affected tier

> **RESOLVED 2026-05-24 (build session open).** All four signed off by Adam.
> DQ1 → **(b) heuristic claim_id cross-walk** (ship all 5 invariants from §13 in M5a; the heuristic reads `claim_inventory.tsv` and extracts claim_id mentions from slide content + speaker notes — pre vs post set equality per slide; misses claims referenced without quoting the id but catches the common case where composer reuses the id string in `evidence_pointer` fields).
> DQ2 → **(a) per-slide hedge aggregation + §13 5-marker dict as constant** in `revise_invariance.py`.
> DQ3 → **(a) hard reject on invariance fail** per §13 contract; no retry counter increment; per-finding audit file.
> DQ4 → **(a) replace `validate_p3_numeric_provenance` in-place** with the `check_quantitative_grounding` wrapper; same P3 id; cascade `_P0_VALIDATORS` re-adds P3 (D-058 demote becomes obsolete).
> Land as D-059..D-061 in Tier D.

**DQ1 (gates Tier A) — `claim_id` cross-walk shape.** Invariant (1)
from §13: "Every `claim_id` in pre-edit slide content + speaker
notes MUST appear in post-edit at the same slide." But: claim_ids
don't appear in slide content today as a discoverable token (the
M3 fused composer doesn't emit `claim_id` in `speaker_notes`
inline). Two options:
- **(a) Skip invariant (1) until the composer emits inline
  `[claim_id]` tokens** (deferred to a future Tier B follow-on /
  next composer iteration). Invariants (2)–(5) ship in M5a.
- **(b) Heuristic claim_id cross-walk** — read the
  `claim_inventory.tsv` (Phase-0 output; M1) and extract every
  claim_id string mention from slide content + speaker notes. Pre
  vs post must have the same set of claim_id mentions per slide.
  Misses content that references a claim without quoting its id;
  catches the common case (composer reuses claim_id strings in
  `evidence_pointer` fields).
**Recommendation: (a) — defer invariant (1)** for M5a; ship
invariants (2)–(5) which are well-defined on current composer
output. Invariant (1) returns in a future iteration once the
composer emits inline `[claim_id]` tokens. Avoids shipping a
heuristic that's mostly false-negative (option b) and forces the
composer-prompt iteration to be a proper decision rather than a
retrofit.

**DQ2 (gates Tier A) — hedge-marker counting & per-claim
attribution.** Invariant (4) from §13: "Each claim's hedge-marker
count … may decrease by ≤1 but not increase or flip a scoped claim
to declarative." Two things to settle:
- **Hedge dictionary**: §13 names `may / suggests / appears /
  candidate / preliminary`. Need to decide whether to expand
  (e.g., `consistent with / might / possibly / hint / indicate`)
  and where the list lives (constant in `revise_invariance.py` vs
  external YAML/JSON).
- **Per-claim vs per-slide**: §13 says "per-claim" but slides
  don't emit a per-claim hedge index. Two readings:
  - **(a) Per-slide aggregation**: total hedge-marker count on the
    slide (title + bullets + figure_caption + speaker_notes).
    Permits one hedge swap per slide; rejects a slide whose total
    hedge count increases.
  - **(b) Per-bullet attribution**: each bullet is a claim; count
    per bullet. More granular; catches "moved hedge from bullet 1
    to bullet 2" as a 0-net-change which is actually a claim
    re-attribution.
**Recommendation: (a) per-slide aggregation + the §13-listed
five-marker dictionary as v1 + a constant in `revise_invariance.py`
(no external file)**. Simpler; matches the "ship the mechanism,
iterate the parameters" posture from M4a/M4b. Per-claim
attribution is an empirical refinement after we have revise-failure
data.

**DQ3 (gates Tier B) — invariance failure: hard-reject or
auto-retry?** §13 says "the revise is rejected wholesale; halt with
`phase=revise_invariance_violated`." The existing revise loop
already retries failing findings up to 2 times (per
`retries_per_slide`). Two options:
- **(a) Hard reject** (per §13): invariance fail → finding marked
  failed; finding's retry counter NOT incremented (the LLM
  produced something well-formed but semantically wrong; another
  attempt is unlikely to help on its own). Emit
  `audit/revise_invariance/<finding.id>.json` with the failing
  invariants. Operator manually addresses.
- **(b) Retry with invariance-fail as a finding annotation** —
  re-invoke `revise_slide.v1` with the failing invariants prepended
  to the user prompt as "DO NOT change X, Y, Z." Burns LLM cost
  but might fix on retry.
**Recommendation: (a) hard reject + per-finding audit file** for
M5a v1. Matches §13's contract; defers prompt-aware retry
(option b) to a future iteration once we see how often invariance
failures happen in practice. The retry-count integration is
asymmetric: today's validator-fail retry assumes the LLM might
fix on a second try (it's structural; usually does), but
invariance failure is semantic and retry success rate is unknown.

**DQ4 (gates Tier C) — P3 retirement: replace in-place or new
validator + retire P3?** Two paths:
- **(a) Replace `validate_p3_numeric_provenance` in-place** with
  the new `check_quantitative_grounding`-wrapping body. P3 keeps
  its id ("P3"); cascade `_P0_VALIDATORS` re-adds it; existing
  callers see no contract change.
- **(b) New validator `validate_p3_grounded_numbers` (new id, e.g.,
  P3b or rename existing); deprecate the old `validate_p3_numeric_provenance`** (move
  to `validate_presentation.py` archive or just delete on the v0.4
  cut-over).
**Recommendation: (a) replace in-place**. Same id, same severity
position, same SPEC reference. Lower-churn; doesn't break the
DECISIONS / SPEC narrative; the v0.4 fused-notes composer's
content goes through the new `check_quantitative_grounding` path
that's already in tree (Tier B aggregation reads its output).
Option (b) adds id churn for no semantic gain.

---

## Tier A — `tools/revise_invariance.py` + 5-invariant impl

New file `tools/revise_invariance.py`. Modeled on
`tools/visual_qa.py`'s shape minus the LLM invocation (this is a
pure-Python static analysis tool).

**A1. Invariance contract** — schema for
`revise-invariance.v1`:

```json
{
  "schema_version": "revise-invariance.v1",
  "draft_dir": "<absolute path>",
  "finding_id": "F042",
  "slide_id": 13,
  "pre_edit_slide_path": "<absolute path>",
  "post_edit_slide_path": "<absolute path>",
  "checked_invariants": ["citation_cross_walk", "numeric_preservation",
                         "hedge_level", "layout_preservation"],
  "skipped_invariants": ["claim_id_cross_walk"],
  "violations": [
    {"invariant": "citation_preservation",
     "severity": "fail",
     "detail": "citation [Smith2024] in pre-edit bullets[2] missing from post-edit",
     "pre_value": "[Smith2024]", "post_value": null}
  ],
  "verdict": "fail",
  "note": "claim_id cross-walk skipped — composer doesn't emit inline tokens (DQ1)"
}
```

**A2. Five-invariant implementations.** Per DQ1, ship 4 of 5:
- **`_check_citation_preservation`** (invariant 2): regex-extract
  `[citation_key]` tokens from pre + post text (title + bullets +
  figure_caption + speaker_notes); set equality check; insertion OR
  deletion = fail.
- **`_check_numeric_preservation`** (invariant 3): extract numeric
  literals (re-use a tightened version of
  `check_quantitative_grounding.py`'s `_extract_numbers` helper);
  post-multi-set count of each token ≥ pre-multi-set count (allows
  removal for de-dup; forbids invention).
- **`_check_hedge_level`** (invariant 4): per-slide aggregation per
  DQ2 recommendation; sum hedge-marker counts across the 5
  marker words from §13; post-count ≤ pre-count + 0 increase, with
  the §13-allowed ≤1-decrease tolerance.
- **`_check_layout_preservation`** (invariant 5): single-field
  comparison `pre_slide["layout"] == post_slide["layout"]`; any
  delta = fail.
- **Skip `_check_claim_id_cross_walk`** (invariant 1) per DQ1; the
  output records "skipped" in `skipped_invariants` for forensic
  trace.

**A3. CLI.** `python3 revise_invariance.py
<pre_slide.json> <post_slide.json> [--finding-id ID] [--out PATH]
[--quiet]`. rc=0 if all checked invariants pass; rc=1 if any fail.
Mirrors the `slide_spec.py validate` CLI severity contract.

**AC for A:** unit tests cover each of the 4 invariants (citation,
numeric, hedge, layout) on synthetic pre/post slide pairs;
contract test pins the JSON schema; CLI smoke (rc=0 on pass, rc=1
on fail); `bash -n` N/A (Python-only).

## Tier B — wire invariance into `revise_loop.py`

The invariance gate plugs in between the LLM post-edit output and
the in-spec merge in `_process_finding`.

**B1. Gate location.** In `_process_finding` (around line 640
of `revise_loop.py`, where `_replace_slide_in_spec(spec, slide_id,
new_slide)` runs):

```python
# CURRENT (M4b state):
new_slide = json.loads(out_path.read_text(encoding="utf-8"))
if not _replace_slide_in_spec(spec, slide_id, new_slide):
    state.findings_failed.append(finding.id)
    return "failed"
state.findings_revised.append(finding.id)

# AFTER M5a Tier B:
new_slide = json.loads(out_path.read_text(encoding="utf-8"))
# Invariance gate (M5a Tier B)
ok, invariance_path = _check_revise_invariance(
    slide_path,        # pre-edit (already on disk per line 605-607)
    out_path,          # post-edit (just-written by LLM)
    finding_id=finding.id,
    audit_dir=paths["audit_dir"],
)
if not ok:
    # Per DQ3 (a) — hard reject; no retry; finding marked failed
    state.findings_failed.append(finding.id)
    return "revise_invariance_violated"
if not _replace_slide_in_spec(spec, slide_id, new_slide):
    ...
```

**B2. New `_process_finding` return value** — `"revise_invariance_violated"`
joins `revised | added | skipped | failed | retried_failed`. The
caller (`run_revise_loop`) treats it as terminal (not retry-eligible)
and surfaces in `next_actions.md`.

**B3. Audit dir** — new `audit/revise_invariance/` directory holds
per-finding invariance JSONs (analogous to
`audit/revisions/{finding.id}.{finding,slide,revised_slide,metadata,stream}.json`).

**AC for B:** unit test on a synthetic finding that triggers a
citation-deletion invariance fail → `_process_finding` returns
"revise_invariance_violated" + writes the audit file + does NOT
mutate the spec. Existing revise-loop tests stay green (the gate
is additive).

## Tier C — P3 retirement (rewrite, not delete)

Per DQ4 recommendation (a): replace
`validate_p3_numeric_provenance` in-place with a wrapper around
`check_quantitative_grounding.check_grounding(draft_dir)`. Keeps the
`P3` id, severity position, and SPEC reference.

**C1. Rewrite `validate_p3_numeric_provenance`** to:
1. Resolve `draft_dir` from caller (already passed to
   `validate_presentation` as kwarg).
2. Invoke `check_grounding(draft_dir)` (already in tree;
   produces a `GroundingReport`).
3. Map `GroundingReport.findings` (severity high/medium/low) →
   ValidatorResult violations:
   - high → `Violation(severity="error", escalation_path="manual")`
   - medium/low → `Violation(severity="warning", escalation_path="manual")`
4. If any high-severity findings exist → `status="fail"`; else
   `status="pass"`. Matches the v0.3 P3 contract (fail when any
   load-bearing numeric is ungrounded).

**C2. Cascade `_P0_VALIDATORS` re-add P3.** Once P3 is the
v0.4-native check, the D-058 demote is obsolete; cascade
`_P0_VALIDATORS = {"P3", "P4", "P5"}` (the original M4b Tier B
posture). Update the existing test
`test_tier1_p0_validators_pinned_to_p4_p5` →
`test_tier1_p0_validators_pinned_to_p3_p4_p5`.

**C3. Tier-1 `_validate_p1_p10`** — already passes `draft_dir` to
`validate_presentation`; no change.

**C4. Tier-1 `_read_quantitative_grounding`** — this aggregator
currently lifts findings as P1/P2 advisory (M4b Tier B). With the
new P3 emitting violations from the same source, we have
double-lifting risk. Resolution: keep
`_read_quantitative_grounding` (it lifts the medium/low
findings); the new P3 lifts only the high-severity findings as
P0. Test that no medium finding is lifted twice (once by P3, once
by `_read_quantitative_grounding`).

**AC for C:** new unit tests pin P3 rewrite (synthetic spec +
synthetic REPORT-grounded check fixture → P3 passes; ungrounded
fixture → P3 fails with the high-severity violation count); cascade
`_P0_VALIDATORS` test updated; double-lifting test added.

## Tier D — SPEC.md §13.1 update + DECISIONS

**D1. SPEC.md §13.1 update** — replace the v0.3-era
`speaker_notes_provenance` description with the v0.4 wrapper-
around-grounding-check semantic. Note: P3's id is preserved;
severity is preserved; the source-of-truth is now REPORT.md
(walking) rather than per-slide structured index.

**D2. DECISIONS.md** — three new entries:
- D-059: M5a P3 retirement complete (closes D-058's M5 schedule).
- D-060: revise_invariance DQ1 resolution (claim_id cross-walk
  deferred).
- D-061: revise_invariance DQ2/DQ3 resolutions (per-slide hedge
  aggregation; hard-reject on fail).

**D3. V0_4_ARCHITECTURE.md §16 M5 update** — split into M5a
(SHIPPED) + M5b (AI Studio image-gen; deferred). M5a closeout note
mirrors M4a/M4b's SHIPPED block.

**AC for D:** docs render cleanly; cross-references intact;
DECISIONS chronological order maintained.

## Tier E — end-to-end smoke on `ibd_phage_targeting`

Two probes:

**E1. P3 retirement probe.** Re-run cascade on
`ibd_phage_targeting/draft_1` (M4b-closed state). Expected:
- Tier 1 status: now FAIL (the deck's 3 ungrounded numbers from
  `quantitative_grounding.json` lift as P3 P0; **previously P1
  advisory from `_read_quantitative_grounding`**, so the cascade
  short-circuit will fire). Confirms P3 retirement restores
  fail-fast.
- The 3 high-severity ungrounded numbers are exactly what P3
  catches; the 282 v0.3-style P3 fails (the D-058 root cause) are
  GONE because the new P3 doesn't walk `speaker_notes_provenance`
  at all.

**E2. revise_invariance probe** — synthetic-defect smoke on a
revise-loop run. Inject a finding that should trigger a
citation-deletion (e.g., a finding whose revise output the LLM
would naively edit away a citation token). Confirm:
- Invariance check fires; `audit/revise_invariance/<finding.id>.json`
  written with the failing invariant.
- Spec NOT mutated.
- Revise loop's state surfaces the violation in `next_actions.md`.

Both probes are bounded spend: E1 is ~$0.05 + ~$0.50–$1.50
(cascade re-run; same as M4b Tier E). E2 is ~$0.02 (single
revise call). Total ~$0.55–$1.55.

**AC for E:** cascade re-run produces P3 P0 on slide(s) with
ungrounded numbers per `quantitative_grounding.json`; cascade
correctly short-circuits Tier 2+3. revise_invariance probe
catches the synthetic violation.

## Tier F — closeout

`V0_4_ARCHITECTURE.md` §16 M5 split into M5a/b; M5a → SHIPPED;
`LAYOUT.md` (`revise_invariance.py`); this punch list's status
table; `DECISIONS.md` D-059..D-061; SPEC.md §13.1; auto-memory
`project_presentation_maker_v0_4_m5a.md` + MEMORY.md index line.

## Dep edges

```
A ──┬──> B ──> E ──> F
    └──> (DQ1/DQ2/DQ3 resolutions land here)
C ──┬──> E (P3 probe)
    └──> (DQ4 resolution lands here)
D — runs anytime after A+C land (paperwork)
```

A (invariance impl) and C (P3 rewrite) are independent. B (wire into
revise_loop) blocks on A. E integrates both. D + F are paperwork.

## Smoke gates

- **A gate:** unit tests on each of the 4 invariants; contract test
  green; CLI smoke (rc=0 / rc=1 on pass / fail).
- **B gate:** revise-loop tests stay green; new test pins the
  invariance-gate's hard-reject path.
- **C gate:** P3 rewrite unit tests green; cascade _P0_VALIDATORS
  re-add tested; double-lifting absence test green.
- **E gate:** P3 probe shows fail-fast restored (cascade short-
  circuits at Tier 1 P0 on the 3 ungrounded numbers); revise
  invariance probe catches a synthetic violation.

## What M5a does NOT do (→ M5b / M6)

- AI Studio image-gen provider (`image_client.py` provider
  extension; auth discovery; model-availability probe) — M5b.
- State-schema v0.3 → v0.4 migration script — M6.
- A/B test + cut-over decision — M6.

## Estimated effort

| Tier | Estimate |
|---|---|
| A — revise_invariance.py | 4–6 h (4 invariants + tests + CLI) |
| B — wire into revise_loop | 2–3 h (gate + audit-dir + test) |
| C — P3 retirement | 2–3 h (rewrite + cascade test + double-lift test) |
| D — SPEC + DECISIONS | 1–2 h |
| E — end-to-end smoke | 2–3 h (P3 probe + revise_invariance probe) |
| F — closeout | 1–2 h |

Total ~12–19 h. Lower bound than M4a/M4b because no new LLM
infrastructure; both components reuse existing patterns
(revise_invariance is pure Python; P3 wraps existing
quantitative_grounding code).

## First action (M5a build session)

Read `CLAUDE.md` → `augmentation-stream-plan.md` → this file →
auto-memory `project_presentation_maker_v0_4_m4b.md` (the cascade
substrate that M5a's P3 work fits into) + `project_presentation_maker_v0_4_m4a.md`
(the renderer + validator-severity foundations). Then Adam
resolves DQ1–DQ4. Then Tier A — `revise_invariance.py` is the
keystone for B; C is independent and can land in parallel.
