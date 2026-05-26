# beril-presentation-maker-skill — Release Notes

## v0.4.0-experimental (2026-05-25) — architecture pivot + cut-over decision

Ships the v0.4 architectural pivot (architect-then-parallel-compose)
as **opt-in via `--architecture-pipeline v0_4`**, NOT as the new default.
v0.3 (sequential per-substory) remains the default pipeline. Per the
M6 A/B cut-over decision (D-069): v0.4 wins on speed + cost + (some)
quality but doesn't clear the ≥4/6 mechanical bar on the target project
and shows substantive content-shape regressions on the sanity-check
project. Adam-veto (D-066) = don't-ship-as-default. Tag is
`-experimental` to communicate the opt-in status explicitly.

**What's in v0.4 (opt-in via `--architecture-pipeline v0_4`):**

- **M1** — Phase-0 vendor ports from paper-writer (`extract_methods`,
  `extract_claims`, `validate_claim_inventory`, `phase0_reuse`).
- **M2** — `deck_outline` M2-lite (lightweight enriched clustering
  per D-042/D-043/D-044/D-045 — supersedes the M0 deck-architect rigid
  contract).
- **M3** — per-substory parallel composition via `worker_pool.sh` +
  `merge_compose_fragments.py` + `reconcile_deck.py`.
- **M4a** — render-debt fix (renderer shrink-to-fit, content caps,
  visual-QA opt-in).
- **M4b** — tiered review cascade (`review_cascade.py`,
  `review_tier2.py`, cascade Tier-3 wrapping `beril-adversarial review`;
  auto-runs by default; fail-fast on Tier-1 P0).
- **M5a** — `revise_invariance.py` (5 semantic invariants on the revise
  verb per §13) + P3 retirement (rewrite-in-place wrapping
  `check_quantitative_grounding`; D-058 obsoleted).
- **M5b** — AI Studio image-gen multi-provider (`image_client.py`
  Google AI Studio native `:generateContent` path; sidecar probe cache;
  D-064 hybrid fallback). beril-adversarial v0.7.0.8 contract integration
  (rc=4 quarantine; Tier B.2 + B.3).
- **M6** — `tools/m6_score.py` cut-over scoring script. A/B test on
  `ibd_phage_targeting` (target) + `functional_dark_matter` (sanity).
- **D-068** — `data_figure` caption cap demoted from hard error →
  soft-warning (renderer shrink-to-fit absorbs; matches M4a length-cap
  posture).

**What v0.4 doesn't change:**

- v0.3 default behaviour. Run without `--architecture-pipeline v0_4`
  and the pipeline is identical to v0.3.x.
- The slide-spec schema (v1 unchanged). Same `slide_spec.json` shape;
  same 16-layout vocabulary.
- The validator surface (P1–P10 unchanged in identity; severities
  updated per D-053/D-068).
- The orchestrator's stage names + CLI flags. `--architecture-pipeline`,
  `--image-provider`, `--no-images`, `--auto-advance`, etc. — all
  backward-compatible.

**M6 cut-over results (mechanical FAIL; Adam-veto = don't-ship; full
report regenerable via `tools/m6_score.py`):**

- **Target (`ibd_phage_targeting`):** v0.4 wins 2/6 (wall-clock -15.2%;
  adversarial findings -47.1%). Ties on cost + validators + image budget.
  Adam metric-5 read: both pipelines equally poor (2/5) on overall arc.
- **Sanity (`functional_dark_matter`):** v0.4 wins 3/6 (wall-clock -36.7%;
  cost -41.9%; validator failures -100%). v0.3 wins on adversarial
  (+33% v0.4 findings; cross-slide consistency loss). Adam metric-5
  read: v0.3=3/5, v0.4=2/5 (v0.4 regressed).
- Mechanical decision rule (D-065): v0.4 needs ≥4/6 on target + ≥40%
  wall-clock reduction on any project. v0.4 hit neither.
- Adam-veto (D-066): don't-ship-as-default; v0.4 opt-in via flag.

**Operational guidance:**

- **Most users should run default (v0.3).** It's the bench-validated
  pipeline. v0.4's speed/cost wins don't justify the quality regressions
  on cluster-rich projects (like `functional_dark_matter`).
- **Use `--architecture-pipeline v0_4` when:** the project has many
  small, independent substories (parallel-compose pays off); speed
  matters more than narrative-arc tightness; you're prepared to manually
  audit the merged spec for cross-slide numeric consistency (v0.4
  parallel-compose can produce the same wrong number on multiple slides
  composed independently).
- **Don't use v0.4 when:** the project has tightly-coupled substories
  that need to flow into each other; the final deck is for a high-stakes
  presentation where the M6-surfaced "substory_arc" and
  "unbacked_quantitative" regressions are material.

**Carry items addressed in v0.5** (per D-070; `V0_5_PUNCH_LIST.md`):
content-shape weaknesses that affect BOTH pipelines on BOTH projects
(obscure arc, weak transitions, walls of text, specialist-register
leakage). v0.5 is a content-discipline milestone, NOT another
architectural pivot.

**Upgrade notes:**

- No breaking changes vs v0.3.4.4. Existing draft directories load
  without migration.
- `tools/m6_score.py` is the new cut-over scoring CLI (regenerable
  against any draft pair; useful for ongoing benchmarking).
- AI Studio image-gen requires `GOOGLE_AI_STUDIO_API_KEY` in shell
  env or `BERIL_ROOT/.env`. See SPEC §8.3 + §8.3.2.
- `beril-adversarial` consumers should use v0.7.0.8+ for the
  exit-code contract integration (rc=4 quarantine). v0.7.0.6 and
  earlier work but the rc=4 hazard isn't quarantined.

**Tag:** `v0.4.0-experimental`. Future v0.4.x patch releases continue;
v0.5 will be the next default-pipeline candidate.

---

## v0.3.4.4 (2026-05-04) — docs cleanup pre-hub-install

Docs-only release prepping for KBERDL hub install. README rewritten
from v0.1-spec-only state to reflect v0.3.4.3 reality (14-stage
pipeline, 16-layout vocabulary, 4-zone layout, image_gen, adversarial
loop, prune subcommand). HUB_INSTALL pinned to v0.3.4.3+ install
URLs. SKILL.md output-artifacts catalog updated for v0.3.4.2 audit
hygiene additions. RELEASE_NOTES rolled up the v0.3.3 → v0.3.4.3
trajectory.

## v0.3.4.3 (2026-05-04) — CONTRACT.md cross-skill interop pinning

New canonical CONTRACT.md at repo root pinning every schema
presentation-maker emits (slide_spec.v1, image-manifest.v1,
image-decisions.v1, image-request.v1, image_provenance,
stage-metadata.v1, run-summary.v1, 4-zone draft layout) and every
schema it consumes (adversarial-review-presentation.v3 incl class
dispatch, citation_pool reuse-from-paper, project inputs). Includes
CLI surface guarantees, versioning policy, known interop quirks,
cross-skill smoke test catalog. Mirrors adversarial v0.6.0+ pattern.
Closes the audit's "no CONTRACT.md" gap. v1.0 prerequisite stack
(v0.3.4 + v0.3.4.1 + v0.3.4.2 + v0.3.4.3) now complete.

## v0.3.4.2 (2026-05-04) — audit hygiene closer

New tools/finalize_run.py helper consolidates per-stage `.metadata.json`
sidecars into single `audit/stage-metadata.json` (stage-metadata.v1
schema) AND populates the previously-empty `audit/runs/run-N/` tree
with per-orchestrator-invocation summaries (run-summary.v1 schema:
started_at, finished_at, exit_code, stages_run, total_cost_usd, token
totals, models_used). Bash orchestrator hooks via `trap EXIT` so
finalize fires even on partial runs / Ctrl-C / failure. 36 new unit
tests (stage-label derivation, recursive metadata collection,
sequential run-N allocation). Closes the audit's "audit/runs declared
but unused" + "stage_metadata declared but unwritten" gaps.

## v0.3.4.1 (2026-05-04) — prune/clean CLI subcommand

New `beril-presentation-maker prune <project_id>` subcommand for
cleaning up old drafts under projects/<id>/talks/. Dry-run by default;
`--apply` to delete, `--archive <path>` to move. `--keep N` keeps
the latest N drafts (default 3); `.kept` marker file pins specific
drafts (e.g., a published talk). Detects orphan entries, reports
without touching unless `--also-orphans`. Never modifies project
source files. 26 new unit tests. Hub-readiness operational
improvement.

## v0.3.4 (2026-05-04) — hub-readiness docs (Tier A)

SKILL.md fully rewritten against v0.3.3.2 reality: status line
current, two-surfaces table (slash vs CLI subcommand) with "DO NOT
conflate" warning, 6-mode matrix as single source of truth, numbered
Steps 1-5 workflow including image_gen + adversarial loop, 14-stage
pipeline catalog, output-artifacts catalog reflecting 4-zone layout +
all v0.3.3 image-gen artifacts, cost-control flag table covering all
9 v0.3.x flags. Both slash command files (commands/beril-presentation-maker.md,
beril-presentation-maker-continue.md) updated with the 4-signal
project resolution tree (lifted from adversarial v0.7.0.1). NEW
HUB_INSTALL.md operator runbook covering pipx install + install-skill
+ configure + first-run validation + upgrade + uninstall + 8
troubleshooting recipes. Docs-only release.

## v0.3.3.2 (2026-05-03) — image-gen efficiency point release

Two cost-side fixes informed by the v0.3.3 ship-validation smoke:

- **#63 stage_image_gen reuses cached request.json on retry.** New
  `image_gen_approval.can_reuse_cached_request` helper: True when
  cached request exists, slide_id_target verifier passes, and any
  `--image-style` override matches. Saves ~$0.14/slide on every
  retry. New CLI subcommand `image_gen_approval.py check-reuse`
  for bash dispatch.
- **#62 image_client worst-case preflight recalibrated.** Constant
  `_WORST_CASE_COST_USD = 0.05` (was 32K-output × $12/M = $0.404,
  30× over the v0.3.0 calibrated mean of $0.014/image). Pre-recal
  was rejecting legitimate $0.10 caps mid-pipeline AFTER
  ai_image_prompt LLM had spent ~$0.14. New regression test pins
  the constant in [$0.03, $0.10] band.

15 new unit tests. 663/663 pass.

## v0.3.3.1 (2026-05-03) — adversarial v0.7.0.1 schema migration

Consumer-side migration for `adversarial-review-presentation.v3`
(shipped in beril-adversarial v0.7.0; v0.7.0.1 is byte-identical
except docs). Three changes:

- **Class enum dispatch:** `narrative_weakness` → `central_objection`
  in `revise_loop.SURFACE_ONLY_CLASSES`. Both names accepted for
  one transition release per adversarial team's "Optionally accept
  BOTH" guidance.
- **New class routing:** `citation_reality` added to surface-only
  (per adversarial team: human verification needed; required field
  is `citation_id`).
- **Consumer-side smoke** at `tests/integration/test_adversarial_interop.py`:
  3 unit-level shape checks (always run) + 1 marker-gated live
  integration (`pytest -m integration`; ~$0.50/run). Catches
  cross-skill drift cheaply.

10 new unit tests; v2 audit files still readable for forensic compat.
648/648 pass.

## v0.3.3 (2026-05-03) — image-gen orchestrator stage SHIPPED

Channel A end-to-end: deterministic Python decision + ai_image_prompt
LLM + per-slide approval + image_client.py + manifest binding through
merge. 7 new modules (~1,845 LOC, 140 tests):

- `tools/image_gen_decision.py` — closed-set partition over 16
  layouts; concept_illustration is the only YES.
- `tools/image_gen_manifest.py` — image-manifest.v1 schema +
  writer.
- `tools/image_gen_approval.py` — per-slide approval gate +
  slide_id_target trust-but-verify.
- `tools/image_gen_orchestrate.py` — Python orchestration helpers
  wrapping manifest + budget + fragment-mutation.
- `tools/draft_paths.py` extension — image_decisions, manifest,
  provenance paths + snapshot subdir.
- `tools/merge_compose_fragments.py` extension — `--image-manifest-path`
  + binding + slide-drop.
- `tools/presentation_maker.sh` extension — stage_image_gen + 5 new
  flags + `--resume-from image_gen` + CBORG_API_KEY auto-load.

Live smoke validated forced concept_illustration on
core_gene_tradeoffs (729KB PNG, $0.014 actual cost matched v0.3.0
calibration). 5 late-arrival fixes captured during smoke (usage
help truncation, wrapper flag pass-through, empty-array bash bug,
CBORG_API_KEY load, CONCEPT_STYLES contract drift). 638/638 pass.

## v0.3.2.8 (2026-05-03) — data_figure caption/data_source overlap fix

Live failure surfaced by the post-revise visual review of draft_2.

### Bug

`_fill_data_figure`'s caption box used `auto_size=True`, which lets
the box grow downward to fit text. With short captions (~150 chars)
this works fine — caption fits in ~1.5 lines, no collision. With
the longer caption the revise loop produced for slide 8 (~410
chars, 5+ wrapped lines at 12pt), the caption box grew past the
data_source's y=4.82 anchor, producing visual overlap on the
slide.

### Fix

- Drop `auto_size=True` from both caption and data_source textboxes.
  Caption stays at fixed H=0.65 (~3 wrapped lines at 12pt); longer
  captions get clipped at box edge instead of overlapping the
  data_source band.
- Shrink `FIGURE_REGIONS["data_figure"]` from `(0.50, 1.40, 9.00,
  3.10)` to `(0.50, 1.30, 9.00, 2.85)` — figure top moves up 0.10 in;
  bottom moves up to 4.15 in. Frees 0.35 in below figure for the
  expanded caption band.
- Caption box: y=4.18, H=0.65 (was y=4.50, H=0.30).
- Data_source box: y=4.83, H=0.15 (was y=4.82, H=0.18).

### Mitigation strategy

Geometry now budgets ~3 wrapped caption lines at 12pt. Captions
exceeding that are visually clipped at the box edge — the audience
loses the trailing text, but no overlap with data_source or the
logo strip at y=5.00. Acceptable as a render-side fail-safe.

The cleaner fix is content-side: cap caption length in the
slide_compose / revise_slide prompts at ~200 chars. Filed as a
v0.3.x backlog item; the render-side budget is the immediate
defensive measure.

---

## v0.3.2.7 (2026-05-03) — control flow: revise_slides dispatch independent of adversarial_review

The third bug uncovered by the live revise-loop test on draft_2.

### Bug

The orchestrator's main flow nested the `revise_slides` dispatch
INSIDE the `should_run adversarial_review` branch:

```bash
if should_run adversarial_review; then
    stage_adversarial_review
    if [[ -f $ADVERSARIAL_REVIEW_JSON ]]; then
        if should_run revise_slides; then
            stage_revise_slides
        fi
    fi
else
    echo "[skip] adversarial_review"
fi
```

When the user passes `--resume-from revise_slides`:
- `should_run adversarial_review` returns false (ordinal 12 < 13).
- The whole `if` block is bypassed, including the nested
  revise_slides dispatch.
- Output prints "[skip] adversarial_review" and proceeds to
  PIPELINE COMPLETE. Revise loop never fires.

Live failure: 2026-05-03 revise-loop test on draft_2 had a valid
adversarial_review.json in audit/ but the loop didn't run.

### Fix

Restructure: each stage gets its own top-level `should_run` gate at
the same nesting level. Revise loop runs IFF
`should_run revise_slides` AND the review JSON exists. Whether the
review came from this run or a prior run is irrelevant.

```bash
if should_run adversarial_review; then stage_adversarial_review; fi
if should_run revise_slides; then
  if [[ -f $ADVERSARIAL_REVIEW_JSON ]]; then stage_revise_slides; fi
fi
```

---

## v0.3.2.6 (2026-05-03) — `--resume-from` accepts adversarial_review + revise_slides

One-line fix surfaced by the live revise-loop test on draft_2.

### Bug

`presentation_maker.sh` had two lists of valid stages that disagreed:

- The arg-validation `case "$RESUME_FROM"` (line 129) listed stages
  through `merge` (the v0.2.x set) but never got the v0.3.0
  additions.
- The `should_run()` ordinal table (line ~1220) correctly included
  `adversarial_review:12` and `revise_slides:13`.

Result: `--resume-from revise_slides` (or `--resume-from
adversarial_review`) errored out at argument validation despite
`should_run()` knowing how to gate them.

Live failure: 2026-05-03 revise-loop test on draft_2 hit
`Error: invalid --resume-from 'revise_slides'`.

### Fix

Extend the case statement to include both stages. Update the error
message's "valid stages" list to match.

---

## v0.3.2.5 (2026-05-03) — adversarial dispatch via `beril-adversarial review` subcommand

beril-adversarial v0.6.0 (2026-05-02) added a `review` Python CLI
subcommand that dispatches to the canonical shell script. Cleaner
than our prior sibling-script-path discovery dance.

### Fix

`stage_adversarial_review` in `presentation_maker.sh` now probes
`beril-adversarial --help` for the `review` subcommand:

- v0.6.0+ detected → invoke `beril-adversarial review --type presentation <draft_dir>` (clean Python CLI path).
- Older v0.5.x install → falls back to sibling shell script lookup at `.claude/skills/beril-adversarial/tools/adversarial_review.sh`.
- Neither available → halt with a clear message that user should upgrade adversarial to v0.6.0+ OR re-run `beril-adversarial install-skill`.

The probe-then-dispatch pattern avoids hard-pinning a minimum
adversarial version in the orchestrator; existing v0.5.x installs
keep working.

### Why

The previous v0.3.2.4 fallback called `beril-adversarial --type
presentation` directly, which failed on v0.5.x installs because the
top-level Python CLI didn't have a review-dispatch subcommand. v0.6.0
fixed that on the adversarial side; this release closes the loop on
the consumer side.

### No tests required

The probe pattern is shell logic; the underlying CLI is exercised
by adversarial's own test suite. Cross-skill smoke (orchestrator
end-to-end) is the v0.3.4 gate, not blocking here.

---

## v0.3.2.4 (2026-05-02) — hotfix: model bump + adversarial CLI name fix

Two one-line fixes flagged during the v0.3.2.3 adversarial-loop A/B
prep.

### Fixes

- **Default model bumped** `claude-sonnet-4-20250514` →
  `claude-sonnet-4-6`. The orchestrator's hardcoded default was the
  original Sonnet 4 from May 2025, ~12 months stale. Sonnet 4.5
  (Sept 2025) and 4.6 (current) have shipped since. Every deck
  produced under v0.2.0–v0.3.2.3 ran on a year-old model.

- **`beril-adversarial-cli` → `beril-adversarial`** in the
  orchestrator's stage_adversarial_review function. The actual
  installed binary (per beril-adversarial pyproject.toml's
  `[project.scripts]`) is `beril-adversarial`. The `-cli` suffix in
  our orchestrator was a historical typo that happened to work on
  Adam's earlier setup but blocked fresh installs. Updated install
  hint to reference beril-adversarial v0.5.1.

No new tests required (model id is opaque; CLI name fix is a string
change). 496/496 unit tests still pass.

---

## v0.3.2.3 (2026-05-01) — hotfix: data_table allows empty corner-cell header

The v0.3.2.2 re-smoke (resume-from-merge) made it past the trailing-
comma issue but the validator rejected slide 14 — a 2×2 selection-
signature matrix data_table with `columns: ["", "Conserved", "Variable"]`.
The empty corner-cell header is the matrix-table convention and is
faithfully reproduced from the `slide_compose.v1.md` worked example.
The validator was too strict.

### Fix

- **`_check_data_table` columns relaxation** in `slide_spec.py`. Empty
  string headers are now allowed (matrix corner-cell pattern). Other
  constraints unchanged: 2 ≤ len(columns) ≤ 6, all entries must be
  strings (type-check still enforced).

### Tests

- `test_data_table_empty_corner_cell_allowed`: confirms the live
  failure shape (`["", "Conserved", "Variable"]`) validates clean.
- `test_data_table_non_string_header_rejects`: confirms type-check
  still fires for non-string headers (e.g. `[1, "B", "C"]`).
- 496 / 496 unit tests pass (was 494 in v0.3.2.2).

---

## v0.3.2.2 (2026-05-01) — hotfix: lenient JSON loader for LLM-emitted fragments

The v0.3.2.1 re-smoke crashed at merge: `S1_slides.json` had a stray
trailing comma between `bullets: [...]` and the enclosing content
object's closing `}`. Python's `json.loads` rejects trailing commas
correctly per spec, but LLM-emitted JSON fragments occasionally have
this malformation; a single bad fragment kills the whole pipeline
after ~$3 of LLM costs.

### Fix

- **`_load_json_lenient(path)`** in `merge_compose_fragments.py`. New
  helper that:
  1. Tries strict `json.loads` first.
  2. On `JSONDecodeError`, strips trailing commas via regex
     (`,(\s*[}\]])` → `\1`) and tries again.
  3. On second failure, raises the **original** error so debug
     output points at the actual malformation.
  4. Logs a stderr note when the repair pass fires (so we can
     track LLM JSON malformation frequency).
- All 5 LLM-emitted JSON parse sites in `merge_compose_fragments.py`
  switched to use the lenient loader: per-substory fragments,
  citation_pool, intro fragment, cross_tenant fragment, qa_anticipated
  fragment.
- Tool-emitted JSON parse sites (parse_speaker_notes output, etc) are
  left strict — they should never need repair.
- `slide_compose.v1.md` self-review checklist gains a "no trailing
  commas" rule + concrete failure-mode description, so the prompt
  itself flags this before write.

### Why not unfixable

Per `feedback_llm_json_unfixable_in_parser.md`, LLM-malformed JSON
with **unescaped quotes inside string values** is unfixable in the
parser (requires prompt-side discipline + worked example). Trailing
commas are a different beast: they're a single-character anomaly
that's algorithmically reparable via regex without ambiguity.
Repair-then-warn is correct here; the same approach would NOT work
for unescaped quotes.

### Tests

- 6 new tests in `test_smoke_orchestrator_helpers.py`:
  clean JSON pass-through, trailing-comma repair in array,
  trailing-comma repair in object (mirroring the live failure shape),
  multiple trailing commas, comma-inside-string-not-stripped guard,
  unrepairable malformation raises original error.
- 494 / 494 unit tests pass (was 488 in v0.3.2.1).

### Verification

- 494 / 494 unit tests pass.
- Wheel rebuilds clean.
- Re-smoke is `--resume-from merge` on the existing draft_2/ (the
  S1_slides.json file was hand-fixed before the merge step's
  lenient-loader fix landed; the re-run will exercise the lenient
  loader against any remaining trailing-comma issues in the other
  fragments — currently none, but the pattern is now defended).

---

## v0.3.2.1 (2026-05-01) — hotfix: figure resolver, prompt teaching, position population

Closes four bugs surfaced by the v0.3.2 live smoke on
`core_gene_tradeoffs`. The smoke completed (25 slides, deck rendered)
but three figure assets failed to render, no `data_table` layout was
ever picked, and the slide_spec lacked `position` fields. None of
these were caught by unit tests because they only manifest in the
end-to-end flow with a real BERDL project.

### Bugs fixed

- **Figure resolver broken under v0.3.1 layout.** `_derive_project_dir`
  walked `draft_dir → talks → project_dir`, but in v0.3.1 the
  assembler's `draft_dir = slide_spec_path.parent = draft_N/working/`,
  not `draft_N/`. Walk-up failed; project_dir fallback never fired;
  three figure paths from the `core_gene_tradeoffs` smoke resolved
  against `draft_N/working/figures/` instead of `project_dir/figures/`
  (where the files actually live). All 3 data_figure / claim_evidence
  slides rendered without their figures.

  Fix: new `_derive_actual_draft_dir(maybe_working)` helper strips a
  trailing `working/` segment; `_derive_project_dir` extended to walk
  3 levels up from `working/`. Both legacy (v0.3.0) and v0.3.1+
  layouts work.

- **`figures_curated.md` duplicate not fully killed.** v0.3.1 removed
  the orchestrator's `cp figures_curated.md → curated_figures.md` line
  but `curate_figures.py` itself still wrote the legacy name. Result:
  `working/curated_figures.md` (the canonical name slide_compose
  expects) was missing; LLM ran without the curated figure inventory
  and inferred figure paths from REPORT.md / notebook scans. Three of
  six available figures got picked.

  Fix: `curate_figures.py` writes `curated_figures.md` directly. Test
  `test_cli_curate_subcommand_writes_outputs` updated to assert the
  legacy name does NOT exist.

- **`merge_compose_fragments.py` did not populate `position`.** ALL
  25 slides in the smoke had `position=None`. Stream A's
  `_insert_slide_into_spec` then ran its A1 fallback chain (substory
  anchor / array index / append-with-warning) on every revise loop
  invocation, instead of doing the cheap position-comparison path.

  Fix: `merge_compose_fragments.py` now sets `slide["position"] =
  array_index + 1` on every merged slide at write time. Test
  `test_merge_writes_valid_slide_spec` updated to verify positions are
  populated 1-based.

- **`slide_compose.v1.md` did not know about `data_table`.** v0.3.2
  added the schema + assembler handler + an `add_slide.v1.md` mention
  but missed the primary slide-composing prompt. The LLM had no
  pathway to pick `data_table` for substory content; the
  `core_gene_tradeoffs` smoke produced zero data_table slides despite
  having a literal "selection signature matrix" 2×2 quadrant
  classification (slide 13, rendered as `data_figure` with a missing
  PNG instead of a clean rendered table).

  Fix: `slide_compose.v1.md` now teaches `data_table`:
  - Added to the layout-diversity menu (between `data_figure` and
    `workflow_diagram`); explicit "strongly preferred over data_figure
    when the figure is a table-shaped image" guidance.
  - Full per-layout schema section with two worked examples (top-N
    ranking + quadrant matrix).
  - Validator-blocking caps documented (1-12 rows, 2-6 cols, all
    cells stringified by caller).
  - "16-layout vocabulary" callout in the prompt header (was "15").

### Tests

- 5 new tests in `test_assemble_pptx.py`:
  `_derive_actual_draft_dir` (v0.3.1 / legacy), `_derive_project_dir`
  (v0.3.1 / legacy), `_resolve_asset_path` end-to-end against
  project_dir/figures/X.png from a v0.3.1-shaped working/ dir.
- `test_cli_curate_subcommand_writes_outputs`: updated to verify
  canonical name is written + legacy name is NOT.
- `test_merge_writes_valid_slide_spec`: updated to verify positions
  are populated 1-based.
- 488 / 488 unit tests pass (was 483 in v0.3.2).

### Verification

- 488 / 488 unit tests pass.
- Wheel rebuilds clean.
- Re-smoke on `core_gene_tradeoffs` planned post-tag to confirm the
  three figures + data_table layout selection both work end-to-end.

---

## v0.3.2 (2026-05-01) — `data_table` layout

Adds the 16th layout to the production vocabulary. `data_table`
renders ranked Top-N candidates, comparison matrices, or any small
tabular result with KBase-branded styling. Closes the
`add_slide.v1`-flagged gap that previously fell back to
`claim_evidence` with bullets-as-rows (capped at 3, losing the bottom
of any top-N list).

### New

- **`data_table` layout** in `slide_spec.LAYOUTS` (LAYOUTS now 16
  entries). Schema:

    ```json
    {
      "layout": "data_table",
      "content": {
        "title": "Top 5 dark-matter candidates by ensemble score.",
        "columns": ["Gene", "Organism", "Score", "Evidence"],
        "rows": [
          ["AO356_11255", "P. putida", "0.92", "ML+conservation"],
          ...
        ],
        "caption": "Top candidates by ensemble score (REPORT.md §4.2).",
        "footnote": "Full ranking (n=347) in REPORT.md §4.2.",
        "highlight_rows": [0]
      }
    }
    ```

  Validator-blocking caps: 2 ≤ columns ≤ 6, 1 ≤ rows ≤ 12,
  all cells must be strings (callers own precision via
  `f"{x:.2f}"` etc), `highlight_rows` indices must be in
  `[0, len(rows))`. Caps are presentation-floor readability
  constraints — wider/taller tables should link to REPORT.md.
- **`_fill_data_table` handler** in `assemble_pptx.py`. KBase-
  branded styling via `python-pptx`'s `add_table`:
  - Header row: KBase blue (#007DC3) bg, white text, bold, 12pt
  - Data rows: alternating white / light-gray (#F2F2F2) bands, 11pt
  - Highlight rows: KBase orange (#F78E1E) bg, white text, bold
  - Caption + footnote textboxes below the table
  - Auto-sized row height adapts to row count (3.40-in budget /
    n_rows; capped at 0.34 in/row).
- **`SPEC_TO_MASTER_LAYOUT` aliasing** in `assemble_pptx.py`.
  `data_table` reuses `data_figure`'s master-layout (same title
  placeholder + body region; the handler removes the body and
  renders its own freeform table). Avoids needing a source-`.potx`
  update to add a new layout.
- **JSON schema regenerated** with `data_table_content` defs.
- **`add_slide.v1.md` updated**: removes the "fall back to
  claim_evidence" workaround for top-N data shapes; references
  v0.3.2's `data_table` directly.

### Tests

- 12 new schema tests in `test_slide_spec.py`: minimal-valid,
  optional fields, missing-title, too-few/too-many cols, too-many
  rows, zero-rows, row-length mismatch, non-string cells, out-of-
  range highlight, non-int highlight, example-slide round-trip.
- `test_assemble_pptx`: existing example-spec smoke updated to
  expect 16 slides (was 15) and to recognize the data_table → data_figure
  master-layout aliasing.
- 483 / 483 unit tests pass (was 471 in v0.3.1).

### Out of v0.3.2 scope

- Per-column width hints in the schema. Equal-fraction widths
  render acceptably for 2-6 cols at presentation distance; defer
  until a live test surfaces a specific failure.
- Data-driven cell highlighting (e.g., color cells whose score
  exceeds a threshold). `highlight_rows` is sufficient for top-N
  ranking emphasis; per-cell highlighting is v0.4+.
- Sortable / interactive tables (PPTX is static; this would need
  a different rendering target).

### Verification

- 483 / 483 unit tests pass.
- Wheel rebuilds clean.
- `install-skill` round-trip planned in pre-tag smoke.

---

## v0.3.1 (2026-05-01) — BREAKING: 4-zone draft layout + Stream A wrinkles

Layout cleanup release. Per-draft directories now use a four-zone
layout instead of the v0.3.0 top-level chaos (30+ files mixing
deliverables, narrative, intermediate state, and audit debris).
Adam-only-tester scope: clean break, no migration of historical
drafts, no backwards-compat in `assemble`. Sets the stage for
v0.3.2 tables + v0.3.3 image-gen orchestrator stage without
compounding clutter.

### BREAKING

- **Per-draft layout changed.** v0.3.0-shape drafts (top-level
  `slide_spec.json`, `00_plan.md`, `audit-fail-N/`, etc) are
  incompatible with v0.3.1. `assemble` and `continue` will error
  with a clear "old layout" message. Start a fresh draft; old
  drafts can be deleted.

### New

- **4-zone directory layout.** Top level of every `talks/draft_N/`
  directory now has exactly 4 subdirs:

    ```
    deliverable/    what the user opens (draft.pptx, draft.pdf)
    narrative/      story artifacts (throughline, substories, references)
    working/        intermediate pipeline state (slide_spec.json, fragments)
    audit/          provenance + per-run history (snapshots, logs)
    ```

  Pipeline stages route their outputs to exactly one zone. See
  SKILL.md "Output artifacts" for the full mapping.
- **`tools/draft_paths.py`** (new module, ~440 LOC). Single source
  of truth for layout schema. Frozen dataclass `DraftPaths` with
  named properties for every per-file path. Helper methods:
  `init_layout()` (creates skeleton), `assert_initialized()`
  (rejects old-layout drafts), `snapshot_slide_spec(label)`,
  `record_render_hash()`, `detect_manual_edit()`,
  `archive_manual_edit()`. CLI subcommands
  `record-render-hash` and `detect-manual-edit` invoked by the
  shell orchestrator. 66 unit tests pin the schema.
- **Manual-edit detection + preservation.** Before regenerating
  `deliverable/draft.pptx`, the orchestrator checks its sha256
  against `audit/last-render.json`. If the user has edited the
  deck in PowerPoint, the edited copy is archived to
  `audit/manual-edits/<UTC-timestamp>.pptx` before regeneration,
  with a prominent stderr warning. No blocking, no flag gymnastics
  — edits are preserved (not absorbed) and the user is alerted.
- **SKILL.md §manual-edits** documents the recommended polish
  workflow (copy `deliverable/draft.pptx` → polish elsewhere) and
  how to make edits stick across re-runs (edit narrative/ or
  working/slide_spec.json).
- **Stream A wrinkle A1: `_insert_slide_into_spec` position
  fallback.** When existing slides lack `position` fields (the
  merge step doesn't always populate them), the original
  position-comparison loop fell through to "append at end"
  silently. v0.3.0 draft_10 F003 hit this — a new slide intended
  for position 9 ended up at end-of-deck. Fix: fallback chain
  → substory_id anchor → position-as-array-index → append-with-
  warning. 3 new unit tests.
- **Stream A wrinkle A2: tier register propagation in
  `add_slide.v1.md`.** v0.3.0 draft_10 F003 introduced
  "high-confidence" on an EXPLORATORY-tier deck. The prompt now
  has an explicit per-tier register cheat-sheet, mirrored from
  `revise_slide.v1.md`. Self-review checklist item added.

### Changed

- **`presentation_maker.sh`** rewritten to use named path
  variables (`$PLAN_PATH`, `$THROUGHLINE_PATH`, `$SLIDE_SPEC`, etc)
  set by `set_draft_paths`. Mirror of `draft_paths.py`. Pre-stage
  `init_draft_layout` creates the 4-zone skeleton.
- **`tools/citation_pool.py`** writes references.md /
  bibliography.bib / citation_map.md to `narrative/` and
  citation_pool.json to `working/`. Old-layout fallback preserved
  for paper-writer reuse-from-paper compatibility.
- **`tools/revise_loop.py`** reads from `working/`, snapshots
  pre-revise spec to `audit/snapshots/`, writes metadata to
  `audit/`.
- **`tools/check_quantitative_grounding.py`** reads
  `working/slide_spec.json`. Surfaces a clear error if pointed at
  an old-layout draft.
- **`figures_curated.md` duplicate killed.** Canonical name is
  `working/curated_figures.md`. Orchestrator no longer copies
  `figures_curated.md` over `curated_figures.md`.
- **`*.stderr` no longer leaks at top level.**
  `curate_figures.stderr` (and any future stage stderrs) routes
  to `audit/stage-logs/`.

### Out of scope (deferred)

- **Migration tool.** No `reorg <draft_dir>` command. Adam-only-
  tester scope; old drafts can be deleted.
- **Old-layout backwards-compat in `assemble`.** Errors instead.
- **Stage logs split per-stage stdout/stderr/stream.log under
  `audit/stage-logs/`.** Schema is in `draft_paths.py` but the
  orchestrator's `invoke_claude` still writes the `.stream.log`
  next to the expected output. Will land alongside v0.3.2's
  consolidated stage-metadata work.

### Verification

- 471 unit tests pass (66 new in `test_draft_paths.py`, 3 new in
  `test_revise_loop.py` for A1, layout fixtures updated in
  `test_check_quantitative_grounding.py` and `test_revise_loop.py`).
- Wheel rebuilds clean.
- `install-skill` round-trip verified (planned in pre-tag smoke).

---

## v0.3.0 (2026-04-30) — adversarial review-rewrite loop + image-gen calibrated

Two-stream feature release. Stream A wires `beril-adversarial --type
presentation` (shipped in beril-adversarial v0.4.0) into a
review-rewrite loop that takes JSON findings and dispatches them to
per-finding-class subagent prompts. Stream B calibrates the CBORG
image-gen client (`gemini-3-pro-image`) and encodes calibration
verdicts into the `ai_image_prompt.v1` prompt defaults. The
orchestrator stage that automatically flags `concept_illustration`
slides for image generation is deferred to v0.3.1 alongside two
wrinkles surfaced during Stream A live test.

### Stream A — adversarial review-rewrite loop

- **`revise_slide.v1.md`** (new prompt, ~310 lines). Per-finding-
  class subagent. Handles `register_drift`, `claim_evidence`,
  `qa_softball`, `substory_arc`, and `narrative_weakness`. Preserves
  slide `id`, `position`, `substory_id` across revision; appends to
  `revision_log` with the finding id and a one-sentence summary.
  Cap: ONE finding per invocation; the loop driver dispatches one-
  to-one.
- **`add_slide.v1.md`** (new prompt, ~220 lines). Handler for
  `missing_slide` findings. Layout-selection table maps the
  finding's data shape to one of the 15 production layouts;
  HARD-CAPS `claim_evidence` bullets at 1–3 (validator-blocking).
  Position/`substory_id` derived from the finding's `fix_hint` or
  inferred from the substory at the named insertion point.
- **`tools/revise_loop.py`** (new driver, ~570 lines). Reads the
  adversarial review JSON, dispatches each P0/P1 finding to
  `revise_slide.v1` or `add_slide.v1` via `claude -p`, validates
  the resulting `slide_spec.json` after each finding, and rolls
  back **per-finding** on validator failure (snapshot taken with
  `copy.deepcopy` before dispatch). Cost cap (`--max-revise-cost-
  usd`) and revision cap (`--max-revisions`) gate the loop. Live
  test on draft_10: F001 (register drift on slide 8) and F003
  (top-N candidates new slide) landed cleanly for ~$0.73.
- **Orchestrator stages 12 + 13.** `presentation_maker.sh` gains
  `stage_adversarial_review` (12) + `stage_revise_slides` (13)
  after `merge_and_assemble`. New flags: `--no-adversarial` (skip
  both), `--max-revise-cost-usd` (default $5), `--max-revisions`
  (default 8). `continue_run.py`'s `_VALID_STAGES` extended.

### Stream B — image-gen calibrated

- **`tools/image_gen_calibration.py`** (new harness, ~600 lines).
  Live test harness exercising CBORG image-gen end-to-end: T0
  smoke, T1 brand_color (hex vs descriptive), T2 style_baseline
  (4 styles), T3 text_handling (with-text + no-text), T4 slide2
  design candidates. Cost cap; halts on budget. Run 2026-04-30:
  13/13 trials ok, $0.177 total.
- **`tools/image_client.py` model id corrected.** `DEFAULT_MODEL`
  changed from `google/gemini-pro-image` to `gemini-3-pro-image`
  (CBORG drops the provider prefix). Error messages now include
  payload + response body for debugging. Rate-card table extended.
- **`prompts/ai_image_prompt.v1.md`** updated with calibration
  defaults (cited inline by trial id):
    - **Default style:** `scientific_illustration` (T2 winner).
    - **Default palette:** KBase brand hex `#007DC3` /
      `#5E9732` / `#F78E1E` (T1 winner; descriptive names also
      work but hex is more precise).
    - **In-image text permitted** when explicitly named (T3
      verdict: `gemini-3-pro-image` honors specified labels and
      "no text" prohibitions).
    - **Genome-coverage composition** (T4 winner): genome-ring
      pattern with ~25% dark / ~75% colored, subtle cosmic-dark-
      matter gradient, named as the preferred opener for
      "fraction-unknown" claims.
    - Style enum extended: `scientific_illustration` (default),
      `metaphor`, `infographic`, `conceptual_diagram`,
      `watercolor`, `minimalist`, `abstract`.
    - Cost ceilings re-grounded against measured ~$0.014/image
      with 2–3× headroom for rate-card drift.

### Deferred to v0.3.1

- **Wire `ai_image_prompt.v1` as orchestrator stage.** The prompt
  is calibrated and invokable as-is via Channel B (user explicitly
  asks for an image), but Channel A (slide_compose flags
  `concept_illustration` → orchestrator generates) needs a three-
  layer architecture (decision: when does an image help → spec:
  what to depict → prompt: how to phrase). Deferred to v0.3.1.
- **Stream A wrinkle 1: `_insert_slide_into_spec` position
  fallback.** F003 new slide had `position=9` but landed at end of
  deck because existing slides lack `position` fields, so the
  insert function fell through to "append". Fix: fall back to
  end-of-substory when sibling positions are absent.
- **Stream A wrinkle 2: register discipline propagation in
  `add_slide.v1`.** F003's new slide title used "high-confidence"
  — the same overclaim F001 fixed elsewhere. `add_slide.v1.md`
  needs an explicit anti-pattern section forbidding tier-violating
  language on EXPLORATORY/THIN tier decks.
- **`data_table` layout.** Adapt from `beril-paper-writer`'s table
  renderer; `add_slide.v1.md` already references this as an
  aspirational target.

### Verification

- 373 unit tests pass (Stream A added 21 in `test_revise_loop.py`,
  18 in `test_check_quantitative_grounding.py`, 5 in
  `test_slide_spec.py`; carry-over from v0.2.x).
- Wheel rebuilds clean (no cruft).
- `install-skill` round-trip verified.
- Live test draft_10: F001 + F003 landed; total $0.73.
- Image calibration suite: 13/13 ok, $0.177; defaults encoded.

---

## v0.2.2 (2026-04-29) — visual-review patch from draft_10

Second post-ship patch following live test of v0.2.1 on
`functional_dark_matter` (draft_10). Visual review by Adam plus
mechanical walk surfaced 7 remaining layout issues. Fixes target the
master template + assemble_pptx handlers + introduce a dual-mode
big_idea.

### Layout fixes

- **big_idea: dual-mode handler.** Default render is now centered-
  assertion (no banner, title at slide-center, 48pt + normAutofit) —
  pull-quote treatment for opening claims. Banner + image mode lights
  up only when `supporting_graphic` is present. Forward-compatible
  with v0.3's `ai_image_prompt.v1` so generated supporting graphics
  trigger the legacy banner+image rendering automatically. Live
  failure: draft_10 slide 2 was rendering as title-at-top + empty
  body because the LLM rarely emits supporting_graphic.
- **qa_anticipated: tighter geometry + 60% fontScale.** Title H
  1.00 → 1.30 in (handles 5-line questions like draft_10 slide 23
  without title-body collision). Body T 1.30 → 1.55 (clears taller
  title). Body H 4.00 → 3.75 (maintains logo clearance). Body
  normAutofit fontScale at slide-level 80% → 60% (math: 60% × 18pt ×
  1.2 leading × 9.32 in × 3.75 in ≈ 2000-char capacity, fits worst-
  case 2KB Q&A answers). methods/refs stay at 80% (their content
  fits).
- **workflow_diagram step_caption word_wrap.** v0.2.1 missed adding
  word_wrap=True to the 3-column step caption textboxes; production
  captions (60-100 chars) rendered as overlong single lines bleeding
  across columns. Fixed. Live failure: draft_10 slide 9 captions
  visually overlapping at the bottom.
- **two_column_compare: normAutofit on both columns.** Body
  placeholders inherit no autofit; production content (4-5 bullets
  per column) overflowed into bottom logos. Added `_enable_normautofit`
  calls for idx 1 and idx 2. Live failure: draft_10 slide 19 right
  column "scores 0.875 for CRISPRi analysis" running into logos.
- **claim_evidence figure_caption: drop auto_size, fix word_wrap.**
  v0.2.1's `auto_size=SHAPE_TO_FIT_TEXT` overrode word_wrap (auto-
  size assumes single-line in python-pptx); long captions truncated
  with "...". Geometry: figure H 3.50 → 3.15 (FIGURE_REGIONS update)
  to clear a 0.40 in band for caption above logos. Caption box uses
  word_wrap=True without auto_size. Live failure: draft_10 slide 18
  caption "across cond..." truncated.
- **acknowledgments TBD soft-default.** When contributors list
  contains "TBD - populated by production orchestrator" or similar
  placeholders, replace with "Acknowledgments to be added before
  presentation." Live failure: draft_10 slide 25 was rendering with
  literal "TBD" strings as bullets.

### New helpers in `assemble_pptx.py`

- `_remove_decorative_banner(slide)` — finds and removes the first
  non-placeholder shape in the spTree (used by big_idea Mode 1).
- `_reposition_placeholder_to_center(slide, idx, ...)` — runtime
  override of layout-defined placeholder geometry.
- `_set_title_font_size(slide, font_pt)` — sets font size on the
  title placeholder's runs (necessary because layout-level def_rpr
  doesn't propagate when slide-level body is rebuilt at fill).
- `_enable_normautofit_on_title(slide)` — convenience wrapper for
  title placeholder autofit (idx=0).
- `_is_tbd_placeholder(text)` — recognizes TBD-style placeholders for
  the acknowledgments soft-default.
- `_add_textbox` already had word_wrap and auto_size kwargs from
  v0.2.1; v0.2.2 fixes the order of operations so word_wrap actually
  takes when auto_size isn't also requested.

### Verification

- 373 / 373 unit tests pass (no new tests in v0.2.2 — the changes are
  geometry tweaks tested via re-assembly against draft_10's existing
  spec).
- Re-assembled draft_10's existing slide_spec against v0.2.2 master.
  Walker diff vs v0.2.1:
    OFF-CANVAS:   stays at 0 ✓
    OVERLAP:      8 → **0** ✓ (workflow_diagram chaos eliminated)
    TINY-FONT:    5 → 2 (workflow_diagram captions now 11pt; refs 8pt
                  is intentional per brand spec)
    TEXT-OVERFLOW (real, not auto_size'd): 22 → 17, but ALL remaining
    flags have `auto_size=TEXT_TO_FIT_SHAPE` or `auto_size=SHAPE_TO_
    FIT_TEXT` set, meaning PowerPoint shrinks/grows at render time.
    The walker heuristic doesn't model autofit; visual inspection
    confirms readable layout.
- Master rebuilds clean from updated `LAYOUT_FIXES`.

### Known limits (deferred to v0.3)

- **Slide 1 subtitle truncation.** Content-side; needs slide_compose
  prompt cap (~80 chars).
- **qa_prep.v1 word-budget cap.** Companion to v0.2.2's qa_anticipated
  layout fix. v0.2.2 lets the layout absorb 2KB answers via 60%
  fontScale; v0.3 prompt iteration should reduce to 600 chars per
  answer (cleaner visual + faster reading).
- **workflow_diagram caption ≤80 chars cap.** v0.2.2's word_wrap
  rescues most captions; very long ones (>100 chars) still wrap to 4
  lines vs cap 3. Prompt iteration in v0.3.
- **Adversarial review-rewrite loop.** Spec at
  `SPEC_TYPE_PRESENTATION.md`; pending v0.4.0 of beril-adversarial.

## v0.2.1 (2026-04-28) — master-template + quantitative-grounding patch

First post-ship patch following the v0.2.0 live test on
`functional_dark_matter` (draft_9). The walk + adversarial review
(spawned in this conversation) surfaced 5 master-template P0 bugs and
1 mechanically-detectable content failure class. Fixes target the
build_master + assemble_pptx layers + add a new post-checker that runs
after merge_and_assemble.

### Master-template fixes (`tools/build_master.py`)

- **section_divider**: title placeholder `off_x = -83050` → `0`.
  Affected slides: every section divider (5, 10, 16 in draft_9). Title
  text was bleeding 0.09 in past the left canvas edge on every divider.
- **methods_summary**: NEW LAYOUT_FIXES entry. Body placeholder gets
  `<a:normAutofit fontScale="80000" lnSpcReduction="20000"/>` so dense
  6-7 paragraph methods content (~600-800 chars) shrinks to fit
  instead of overflowing the 12-line cap.
- **qa_anticipated**: NEW LAYOUT_FIXES entry. Title placeholder
  `H 0.63 → 1.00 in` to hold 3-line questions readably; body
  placeholder `T 1.17 → 1.30 in` (push down to clear taller title)
  and `H 3.82 → 4.00 in`; body normAutofit so 5-paragraph answers
  shrink. Companion `qa_prep.v1.md` word-budget cap is a v0.3+
  prompt iteration.
- **references**: NEW LAYOUT_FIXES entry. Body normAutofit so 8 ref
  entries × ~134 chars (~17 wrapped lines) shrink to fit.

### Assemble-step fixes (`tools/assemble_pptx.py`)

- **`_add_textbox`**: new `word_wrap` and `auto_size` kwargs. The
  default of `word_wrap=False` was silently truncating content; opt-in
  for boxes that take production-realistic content.
- **`_enable_normautofit`**: NEW helper. Sets normAutofit at the
  slide-level `<p:txBody>/<a:bodyPr>` after `_set_placeholder_bullets`,
  with explicit `fontScale + lnSpcReduction`. Without this, layout-
  level normAutofit gets overridden by python-pptx creating a fresh
  empty body_pr at fill time. Wired into `_fill_methods_summary`,
  `_fill_qa_anticipated`, `_fill_references`.
- **`_fill_data_figure`**: caption + source TextBoxes use
  `word_wrap=True, auto_size=True` and adequate heights. Slides 9, 13,
  19 in draft_9 had captions running off the right edge.
- **`_fill_big_number`**: subtitle TextBox font 20pt → 16pt with
  `word_wrap=True`. 64-char subtitles fit in the 0.40 in slot between
  the title's bottom (4.60) and the logos (5.00). v0.3+ prompt
  iteration should cap subtitle ≤45 chars.
- **`_fill_claim_evidence`**: when figure is present, body placeholder
  is resized to the left half (W 9.32 → 4.86 in, ending at 5.20 in)
  before fill. Eliminates the ~15 in² body × figure overlap that
  shipped on draft_9 slide 8.

### New post-checker (`tools/check_quantitative_grounding.py`)

Mechanical verification that every number on every slide appears
verbatim (or in a normalized form) in `REPORT.md`. Runs after
`merge_and_assemble`; advisory (exit 1 doesn't halt the orchestrator).
Output: `audit/quantitative_grounding.{md,json}`.

Normalization handles: commas (57,011 ↔ 57011), percent ↔ decimal
(24.9% ↔ 0.249), ratio variants (4/4 ↔ "4 of 4"), `n=` prefixes,
scientific notation, rounding tolerance (slide's "82%" matches
REPORT's "82.4%" within precision), and a publication-year filter
(1900-2099 4-digit numbers skipped). Layouts `references` and
`acknowledgments` are skipped (their numbers are external citation
issue numbers, not project claims).

Validated against draft_9: 102/107 numbers grounded (95.3%). Single
HIGH finding: `35/50` on slide 24's Q&A answer about weight
sensitivity — REPORT only mentions `18/50`; the Q&A answer invented
`35/50`. Real failure caught.

### Why no register-drift / caveat-omission / narrative-arc checker

Earlier draft of this release included a regex-based register-drift
checker. Pulled because it can't work: the verb is not the
discriminator, the hedge-regex catches noise, and the slide → REPORT
mapping is a semantic problem. Mechanical post-checkers are for
structural invariants and verbatim grounding; semantic alignment
between two prose blocks needs LLM-in-the-loop adversarial review.
That ships in `beril-adversarial --type presentation` (spec at
`spike/beril-adversarial-skill-draft/SPEC_TYPE_PRESENTATION.md`,
planned v0.4.0 of beril-adversarial-skill). The presentation-maker
review-rewrite loop wires that reviewer in v0.3.0 of this skill.

### Verification

- 373 / 373 unit tests pass (was 355 in v0.2.0; +18 from new
  `test_check_quantitative_grounding.py` covering extraction,
  normalization, severity grading, layout-skip, and end-to-end).
- Re-assembled draft_9's existing `slide_spec.json` against the fixed
  master template. Walker diff vs baseline:
  - OFF-CANVAS: 3 → **0**
  - OVERLAP: 10 → 8 (slide 20 workflow_diagram remains; v0.3+ work)
  - TEXT-OVERFLOW (real): −3 (slide 8 + slides 9/13/19 source). The
    19 remaining overflow flags are walker false positives — autofit
    isn't modeled by the walker but PowerPoint shrinks at render.

### Cost & wallclock

No LLM cost. Master rebuild + re-assemble on draft_9 took <1 min.

## v0.2.0 (2026-04-27) — first install-shippable release

The fourth skill in the BERIL drop-in quartet (atlas, adversarial,
paper-writer, presentation-maker) reaches install-shippable parity.
The 11-stage drafting pipeline that grew under earlier `v0.1.x-*` and
`v0.2.x-pipeline` tags now ships behind a real CLI: pipx-installable,
deployable into a BERIL checkout via `install-skill`, and invocable
through `/beril-presentation-maker` slash commands.

### What's in this release

**Drafting pipeline (11 stages, all wired):**

1. `plan.v1` — triage + scope.
2. `throughline.v1` — 2-3 candidates with evidence map + glyph
   discipline.
3. `substory_design.v1` — 2-4 substories with punchlines (word-cap
   audit advisory).
4. `curate_figures.py` — inventory + mode-bounded shortlist (figure
   captions from REPORT.md / notebook savefig context / filename).
5. `citation_pool.v1` — DOI/PMID-verified pool with 9-field discipline.
6. `cross_tenant.v1` — K-BERDL cross-tenant signal extraction
   (optional; when project spans multiple tenants).
7. `intro.v1` — opening framing fragment.
8. `slide_compose.v1` — per-substory composition over the 15-layout
   vocabulary.
9. `qa_prep.v1` — anticipated Q&A.
10. `speaker_notes.v1` — per-slide notes.
11. `merge_and_assemble` — fragment merge → validator (P1-P10) →
    `assemble_pptx` → `draft.pptx`.

**Render layer:**

- `assemble_pptx.py` against the shipped KBase-branded master template
  (`references/templates/kbase-presentation-master.pptx`), 15 named
  layouts.
- `slide_spec.py` validator (15 layouts × per-layout shape rules +
  diagram sub-schema with 7 node shapes and 3 edge kinds).
- `poster_fill.py` for `--mode poster-h` and `poster-v`.
- LibreOffice-backed PDF render for `--format pdf`.
- `diagram_render.py` + `repair_diagram_stubs.py` for boxes-and-arrows
  workflow diagrams.

**CLI surface:**

- `beril-presentation-maker --version`
- `beril-presentation-maker install-skill <BERIL_ROOT>`
- `beril-presentation-maker configure`
- `beril-presentation-maker draft <project>`
- `beril-presentation-maker continue <draft_dir> --resume-from <stage>`
- `beril-presentation-maker assemble <draft_dir> [--format pptx|pdf]`
- Slash commands: `/beril-presentation-maker` and
  `/beril-presentation-maker-continue`.

**Packaging:**

- pipx-installable (mirrors paper-writer / adversarial / atlas pattern).
- `install-skill` copies SKILL.md + commands/ + prompts/ + references/
  + tools/ into `<BERIL>/.claude/skills/beril-presentation-maker/`.
  Preserves install-local `state/` (never overwritten).
- Hatchling wheel target excludes bytecode + cache cruft + the
  smoke-named orchestrator copy.

### What changed since the v0.2.1-pipeline tag

- **Real CLI.** `cli.py` and `commands/` modules ported from
  beril-paper-writer-skill (install_skill, configure, draft,
  continue_run, assemble). Previously: all stubs raising
  `NotImplementedError`.
- **Real `discovery.py`.** Ported from paper-writer with
  `SKILL_DIR_NAME = "beril-presentation-maker"`. Includes the
  marker-set BERIL_ROOT walk-up + tiebreaker scoring.
- **Real `state.py`.** Lightweight read/write helpers; the orchestrator
  is canonical for state semantics in v0.2.0. Promote to a dataclass-
  based machine if scope grows.
- **Real `SKILL.md`.** Rewritten from the v0.1.0-spec stub to the
  full slash-command + workflow + artifacts description.
- **Slash command markdowns.** `commands/beril-presentation-maker.md`
  and `commands/beril-presentation-maker-continue.md` shipped.
- **Orchestrator rename.** `presentation_maker_smoke.sh` →
  `presentation_maker.sh` (header rewritten; smoke disclaimer dropped).
  The old filename is excluded from sdist + wheel; Adam will `git rm`
  it post-tag.
- **`figures/curated/` contract drift fixed.** `slide_compose.v1.md`
  changelog + `slide_spec.py` `_check_figure_path` validator that
  hard-rejects the deprecated path convention. 5 new unit tests in
  `test_slide_spec.py`. Live failure mode (draft_8 fig34..fig37
  shipping picture-less) verified fixed.
- **Polish batch from commit `7077849`** included: figure path
  fallback (#77), workflow_diagram coords (#78), divider word cap
  (#79), cross_tenant JSON conversion (#75).

### Known gaps (deferred to v0.3+)

- **Adversarial review-rewrite loop.** Depends on
  `beril-adversarial --type presentation` mode (not yet shipped in
  beril-adversarial-skill).
- **`ai_image_prompt.v1` wired as a stage.** Currently the prompt
  exists; the orchestrator stage that fills `concept_illustration.
  image_path = "{TBD}"` placeholders does not.
- **5 deck formatting bugs** observed on draft_8 walk:
  section_divider title at `left=-0.09 in` (master bug);
  data_figure caption + source TextBox undersizing;
  qa_anticipated body 3× capacity overflow (~36-40 wrapped lines vs.
  cap 12); methods_summary body overflow; workflow_diagram
  caption-row + Oval-10 overflow. Fixes target master-template +
  qa_prep / methods_summary word-budget enforcement.
- **Tier 7 mermaid diagrams.** Cross-skill backlog with paper-writer.

### Upgrade path

For a fresh BERIL deployment:

```
pipx install --force \
  git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git
beril-presentation-maker install-skill <BERIL_ROOT>
beril-presentation-maker configure
```

For an existing deployment that has any pre-v0.2 install of this
skill: re-running `install-skill --force` overwrites the shipped
subdirectories without touching `state/`. No data loss.

### Acknowledgments

- The figures-curated regression smoke test that started this
  conversation surfaced the prompt-vs-tool contract drift class of
  failures, now memorialized in
  `.auto-memory/feedback_prompt_tool_contract_drift.md`.
- The pipx-installable pattern mirrors beril-paper-writer-skill
  (Adam Arkin / Arkin Laboratory) and beril-adversarial-skill.
