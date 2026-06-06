# beril-presentation-maker — cross-skill interop contract

This document pins the **interop surface** that other skills and
external orchestrators consume from beril-presentation-maker, and the
schemas/artifacts presentation-maker reads from sibling skills (paper-
writer, adversarial). It is the durable reference for skill-to-skill
integration; if you're maintaining another BERIL skill that reads or
writes presentation-maker artifacts, this is the load-bearing
document.

For end-user docs (slash commands, mode selection, polishing
workflow), see `src/beril_presentation_maker/skill/SKILL.md`.

For operator install + first-run + troubleshooting, see
`HUB_INSTALL.md`.

For internal design rationale and decision history, see `SPEC.md` /
`LAYOUT.md` / `DECISIONS.md`.

**Status:** v0.8.0 — canonical CONTRACT.md, current as of the
v0.8.0 release. Mirrors the adversarial v0.7.0.8 CONTRACT.md
pattern. Consumer-schema dependency: beril-adversarial-skill
v0.7.0.8 (`adversarial-review-presentation.v3` schema; v3
`central_objection` rename + `citation_reality` routing). Subject
to schema-version bumps as v0.8.x → v0.9.x → v1.0 lands.

v0.8.0 contract additions over v0.3.4.3:

- New audit artifact `audit/layout_overlaps.json`
  (`layout-overlaps.v1`) — emitted by the Tier G.10-A
  deterministic overlap detector.
- New audit artifact `audit/content_overflow.json`
  (`content-overflow.v1`) — emitted by the renderer's geometry-
  aware fitter on floor-clamp.
- New audit artifact `audit/visual_qa_final.{json,md}` — visual-
  QA's post-revise pass (separate from the cascade's pre-revise
  `audit/visual_qa.{json,md}`).
- New audit artifact `audit/adversarial_review_vq_only.json` —
  standalone VQ findings for the 2nd revise pass per Tier G.8.
- New CLI flags forwardable through the `draft` Python wrapper:
  `--prompts-version`, `--force-v3-smoke-stale`,
  `--architecture-pipeline`, `--resume-from`, `--draft-dir`,
  `--revise-severity-floor`, `--visual-qa`, `--no-visual-qa`,
  `--image-provider`, `--max-image-approvals`.

Backwards compatibility: all v0.3.x audit artifacts remain
stable. New artifacts ship as additive (read-if-present); no
existing consumer breaks.

---

## 1. Purpose & scope

### What this contract pins

- **Producer schemas:** every JSON file presentation-maker writes that
  another skill might read. Each has a stable `schema_version` field
  and a canonical Python source-of-truth module.
- **Consumer schemas:** every JSON file presentation-maker reads from
  another skill (adversarial, paper-writer, BERIL itself). The
  expected shape, version-acceptance policy, and dispatch rules.
- **CLI surface:** the 6 subcommands, the bash orchestrator's flag
  set, and the `--resume-from` stage list. These are stable APIs
  external scripts can rely on.
- **Versioning policy:** what's allowed to break at minor vs. major
  bumps; how transition releases work.

### What this contract does NOT cover

- User-facing docs (SKILL.md, HUB_INSTALL.md, README.md).
- Internal-only fields not consumed by other skills (e.g.,
  `working/03_slides/<sid>_slides.json` is private to merge; if you
  read it from another skill you've voided your warranty).
- Prompt content (`prompts/*.v1.md`) — those are implementation
  details of the LLM stages, versioned per file but not part of the
  cross-skill contract.

### When this document changes

Any change to a producer schema, consumer schema, or CLI surface that
another skill could observe MUST update this document in the same
commit. The producer-side principle (v0.3.3.1 onward, per
`feedback_cross_skill_contract_drift.md`): when changing a thing
others depend on, list the consumers, file consumer-update tasks
BEFORE tagging the producer, and update CONTRACT.md as part of the
producer commit.

---

## 2. Producer surface — schemas presentation-maker emits

Every file in this section has a stable schema with a `schema_version`
field. Consumers should match on that field, not on the file path.

### 2.1 `slide_spec.json` (slide_spec.v1)

**Location:** `<draft_dir>/working/slide_spec.json`

**Source of truth:** `src/beril_presentation_maker/skill/tools/slide_spec.py`
(LAYOUTS enum, content schemas, validator) +
`src/beril_presentation_maker/skill/references/slide_spec.schema.json`
(JSON Schema, regenerated from the Python source).

**Schema version:** the JSON file's own `schema_version` field is
`"1.0"` (predates the strict schema-version naming convention; treat
as `slide_spec.v1`).

**Required top-level fields:**

```json
{
  "schema_version": "1.0",
  "project_id": "<id>",
  "mode": "talk-30",
  "audience": "peer",
  "tier": "STRONG",
  "throughline": {
    "id": "TL1",
    "punchline": "...",
    "tier_evidence": "STRONG"
  },
  "substories": [
    {"id": "S1", "punchline": "...", "slide_ids": [2, 3, 4]}
  ],
  "slides": [
    {"id": 1, "position": 0, "substory_id": null, "layout": "title",
     "content": {...}}
  ]
}
```

**Layout vocabulary** (closed enum at `slide_spec.LAYOUTS`):

```
title, section_divider, big_idea, big_number, claim_evidence,
two_column_compare, data_figure, data_table, workflow_diagram,
methods_summary, concept_illustration, cross_tenant_integration,
implications, acknowledgments, references, qa_anticipated
```

Per-layout content schemas defined by `_check_<layout>` functions in
`slide_spec.py`. Schema regression test:
`tests/unit/test_slide_spec.py::test_schema_json_on_disk_matches_dump`.

**Image-bearing layouts:**
- `data_figure` — `content.figure` is a relative path (typically
  `figures/<name>.png` resolving against `project_dir`); the
  validator hard-rejects the deprecated `figures/curated/<name>.png`
  segment.
- `concept_illustration` — `content.image_path` is a relative path
  to a generated AI image (`working/05_images/<slide_id>.png`).
  `content.style` MUST be one of CONCEPT_STYLES (7 values; see §2.4).
  `content.provenance` is required (model, cost_usd, channel,
  approved_at).

**Mutation lifecycle:**
- merge_compose_fragments.py emits the initial spec at
  `audit/snapshots/slide_spec.raw.json`.
- repair_diagram_stubs.py reads raw, writes
  `working/slide_spec.json`.
- assemble_pptx.py reads working spec; never mutates it.
- revise_loop.py snapshots to
  `audit/snapshots/slide_spec.pre_revise.json`, mutates working spec
  in place per finding, re-validates after each revision.

**Stability:** `slide_spec.v1` (via `schema_version: "1.0"`) stable
across v0.3.x. Schema additions (new optional layout content fields)
are non-breaking. Layout removals or required-field additions are
BREAKING and would bump to `slide_spec.v2`.

### 2.2 `image-manifest.v1`

**Location:** `<draft_dir>/working/05_images/manifest.json`

**Source of truth:** `src/beril_presentation_maker/skill/tools/image_gen_manifest.py`

**Schema:**

```json
{
  "schema_version": "image-manifest.v1",
  "draft_dir": "<absolute path>",
  "entries": [
    {
      "slide_id": "S2-pos4",
      "approved": true,
      "image_path": "working/05_images/S2-pos4.png",
      "request_path": "working/05_image_requests/S2-pos4_request.json",
      "channel": "A",
      "model": "gemini-3-pro-image",
      "cost_usd": 0.014,
      "approved_at": "2026-05-03T14:32:11Z"
    },
    {
      "slide_id": "S2-pos7",
      "approved": false,
      "rejected_at": "2026-05-03T14:32:35Z",
      "reason": "user-rejected: prompt drift from substory"
    },
    {
      "slide_id": "S2-pos9",
      "approved": false,
      "skipped": true,
      "rejected_at": "2026-05-03T14:33:02Z",
      "reason": "budget cap exhausted ($0.50)"
    }
  ]
}
```

**slide_id format** (frozen across image_gen_decision, manifest,
merge): `S{N}-pos{P}` for substory slides (substory_id +
0-indexed fragment_position) or `intro-pos{P}` for intro slides.

**Consumer expectations:**
- merge_compose_fragments.py reads when `--image-manifest-path`
  passed; binds `image_path` + provenance to matching
  concept_illustration slides; drops slides with `approved: false`
  (R6 Option A). Backwards-compat: missing manifest is a no-op
  (legacy v0.3.2 behavior).
- revise_loop.py (future v0.4+) may inspect rejected entries to
  avoid re-introducing dropped slides during adversarial revisions.

**Validator:** `image_gen_manifest.Manifest.validate()` returns a
list of error strings. Empty list = valid. Catches duplicate
slide_ids, missing required fields, invalid channel.

**Stability:** `image-manifest.v1` stable through v0.3.x.

### 2.3 `image-decisions.v1`

**Location:** `<draft_dir>/working/05_image_decisions.json`

**Source of truth:** `src/beril_presentation_maker/skill/tools/image_gen_decision.py`

**Schema:**

```json
{
  "schema_version": "image-decisions.v1",
  "tier": "STRONG",
  "mode": "talk-30",
  "user_opt_in_exploratory": false,
  "decisions": [
    {"slide_id": "S2-pos4", "substory_id": "S2", "position": 4,
     "layout": "concept_illustration",
     "emit": true, "reason": "concept_illustration layout is the AI-image vehicle"},
    {"slide_id": "S2-pos5", "substory_id": "S2", "position": 5,
     "layout": "claim_evidence",
     "emit": false, "reason": "supplemental image deferred to v0.3.4 LLM-judgment layer"}
  ]
}
```

**Decision rules** (closed-set partition over the 16-layout vocabulary;
see image_gen_decision.py `_AI_IMAGE_VEHICLE` /
`_STRUCTURAL_NO_IMAGE` / `_HAS_OWN_FIGURE` / `_DEFERRED_LLM_DECISION`
tuples). Drift between these tuples and slide_spec.LAYOUTS surfaces
at module-load time as a `RuntimeError` per
`_validate_partition()`.

**Consumer expectations:** the bash orchestrator's `stage_image_gen`
reads via `image_gen_decision.py list-yes` to enumerate emit=true
slide_ids. External consumers should treat as read-only.

**Stability:** `image-decisions.v1` stable through v0.3.x. Adding
new layouts to slide_spec.LAYOUTS forces a corresponding
categorization in image_gen_decision.py (closed-set assertion);
adding new layouts is therefore semi-BREAKING (adds work to image-gen
maintainers).

### 2.4 `image-request.v1`

**Location:** `<draft_dir>/working/05_image_requests/<slide_id>_request.json`

**Source of truth:**
`src/beril_presentation_maker/skill/prompts/ai_image_prompt.v1.md`
(prompt + schema rules); `image_gen_approval.verify_request_slide_id`
+ `image_gen_approval.can_reuse_cached_request` (validator).

**Schema:**

```json
{
  "schema_version": "image-request.v1",
  "slide_id_target": "S2-pos4",
  "channel": "A",
  "originator": "slide_compose flagged concept_illustration",
  "style": "scientific_illustration",
  "image_prompt": "...",
  "negative_prompt": "...",
  "placement": {
    "region": "body",
    "aspect_ratio": "16:9",
    "max_width_in": 8.5,
    "max_height_in": 4.0
  },
  "model_preference": "gemini-3-pro-image",
  "worst_case_cost_usd": 0.04,
  "user_supplied_prompt": null,
  "user_overrides": {"style": null, "additional_directives": null},
  "approval_required": true
}
```

**Style enum** (mirrors `slide_spec.CONCEPT_STYLES`):

```
scientific_illustration  (T2-winning default per v0.3.0 calibration)
metaphor
infographic
conceptual_diagram
watercolor
minimalist
abstract
```

Adding/removing a style here REQUIRES a matching update to
`slide_spec.CONCEPT_STYLES` + `slide_spec.schema.json`. Drift fails
the `test_concept_styles_match_ai_image_prompt` regression test.
This was the v0.3.3 ship-validation incident captured in
`feedback_cross_skill_contract_drift.md` (4th strike).

**Channel:** `"A"` = LLM-initiated (slide_compose flagged
concept_illustration); `"B"` = user-initiated (deferred to v0.4+).

**`approval_required: true`** is invariant in v1 — every generation
is gated by user approval (or `--auto-approve-images` for CI).
Tightening to `false` is BREAKING; would require D-029 revision.

**Consumer expectations:**
- `image_gen_approval.verify_request_slide_id(path, expected)`
  validates schema_version, slide_id_target match, approval_required,
  channel. Returns list of error strings; orchestrator rejects if
  non-empty.
- `image_client.py generate --prompt ... --budget ...` consumes the
  `image_prompt` + writes the PNG. Worst-case-cost preflight at
  `_WORST_CASE_COST_USD = 0.05` (v0.3.3.2 recalibration; pinned
  in `[0.03, 0.10]` band by `test_worst_case_cost_recalibrated_against_v0_3_0_data`).

**Cache reuse semantics** (v0.3.3.2 #63): the orchestrator may reuse
a cached request.json from a prior run if (a) verifier passes, (b)
no `--image-style` override differs from cached style. Skip-the-LLM
path is safe because the request schema is fully deterministic at
that point.

**Stability:** `image-request.v1` stable through v0.3.x.

### 2.5 `image_provenance.json`

**Location:** `<draft_dir>/audit/image_provenance.json`

**Source of truth:**
`image_client.append_provenance` + `image_client.ImageResult.to_provenance_dict`.

**Schema:**

```json
{
  "version": "1.0",
  "entries": [
    {
      "image_path": "<draft>/working/05_images/S1-pos5.png",
      "model": "gemini-3-pro-image",
      "prompt": "<full prompt verbatim>",
      "cost_usd": 0.014178,
      "elapsed_seconds": 34.9,
      "channel": "A",
      "approved_at": "2026-05-03T03:15:22Z",
      "quant_content_score": null
    }
  ]
}
```

**Append-only.** Every successful `image_client.py generate` call
appends one entry. Survives re-runs and `--resume-from image_gen`
re-rolls (entries from prior attempts are preserved).

`quant_content_score` is currently `null` (v1 stub; vision-LLM
integration deferred to v0.4+). Consumers should accept `null`.

**Stability:** stable. Append-only schema; new optional fields are
non-breaking.

### 2.6 `stage-metadata.v1` + `run-summary.v1` (v0.3.4.2 NEW)

**Locations:**
- `<draft_dir>/audit/stage-metadata.json` (consolidated stages)
- `<draft_dir>/audit/runs/run-<N>/summary.json` (per-invocation)

**Source of truth:** `src/beril_presentation_maker/skill/tools/finalize_run.py`

**stage-metadata.v1 schema:**

```json
{
  "schema_version": "stage-metadata.v1",
  "draft_dir": "<absolute path>",
  "stages": {
    "plan": {
      "elapsed_seconds": 120,
      "input_tokens": 50000, "output_tokens": 1500,
      "estimated_cost_usd": 0.20,
      "model": "<tier-pinned model id>",
      "_source_path": "00_plan.md.metadata.json"
    },
    "slide_compose-S1": {...},
    ...
  }
}
```

Keys are stage labels per the `_STAGE_LABEL_RE_BY_NAME` map +
`_STAGE_LABEL_PATTERNS` regex set in finalize_run.py. Per-substory
fan-out gets `<stage>-<sid>` labels (e.g., `slide_compose-S2`,
`speaker_notes-S3`, `ai_image_prompt-S2-pos5`).

**run-summary.v1 schema:**

```json
{
  "schema_version": "run-summary.v1",
  "run_n": 3,
  "draft_dir": "<absolute path>",
  "started_at": "2026-05-04T03:00:00Z",
  "finished_at": "2026-05-04T03:18:42Z",
  "exit_code": 0,
  "stages_run": ["plan", "throughline_candidates", ...],
  "total_cost_usd": 2.347,
  "total_input_tokens": 4523890,
  "total_output_tokens": 89234,
  "total_cache_read_tokens": 0,
  "total_cache_creation_tokens": 0,
  "total_elapsed_seconds": 1122,
  "models_used": ["<tier-pinned model id>"]
}
```

**Allocation:** per-invocation. Each `presentation_maker.sh` run
allocates the next sequential `run-N` directory atomically (scans
existing). Prior summaries are preserved; the directory is
append-only at the run-N level.

**Bash hook:** `trap finalize_run_on_exit EXIT` registered in
`presentation_maker.sh` after layout init + before any stage runs.
Fires on success, failure, Ctrl-C, or any other exit. Errors from
finalize_run itself are tolerated (don't change the orchestrator's
exit code).

**Stability:** new in v0.3.4.2. `stage-metadata.v1` /
`run-summary.v1` stable through v0.3.x.

### 2.7 4-zone draft layout

**Source of truth:**
`src/beril_presentation_maker/skill/tools/draft_paths.py`
(`DraftPaths` dataclass; `LAYOUT_SUBDIRS` tuple).

**Top-level invariant:** every draft directory has exactly four
entries:

```
draft_N/
├── deliverable/    # what you open / present
├── narrative/      # human-readable story artifacts (user-editable)
├── working/        # intermediate pipeline state
└── audit/          # provenance + debug history
```

The full sub-tree is documented in SKILL.md "Output artifacts"
section. The `DraftPaths` class is the canonical Python resolver;
the bash orchestrator's `set_draft_paths` function is its mirror.
A regression test (`tests/unit/test_draft_paths.py::test_shell_exports_paths_match_python_paths`)
asserts the two sources stay in sync.

**Manual-edit hash guard contract:**

After every assemble, sha256 of `deliverable/draft.pptx` is
recorded at `audit/last-render.json` and the deck snapshotted at
`audit/snapshots/last-render.pptx`. Before the next assemble, hash
mismatch → archive the user-edited copy at
`audit/manual-edits/<UTC-timestamp>.pptx` with a stderr warning.
Documented in SKILL.md "Manual edits to the deck."

**Stability:** v0.3.1 BREAKING change from v0.3.0's flat layout.
Stable through v0.3.x. v0.3.0-shape drafts are explicitly
non-migratable; the orchestrator hard-fails with a clear error.

---

## 3. Consumer surface — schemas presentation-maker reads

### 3.1 `adversarial-review-presentation.v3` (v0.7.0.1+)

**Location:** `<draft_dir>/audit/adversarial_review.{md,json}`
(produced by `beril-adversarial review --type presentation`).

**Source of truth (producer side):** `beril-adversarial v0.7.0.1`
CONTRACT.md + `src/beril_adversarial/skill/prompts/adversarial_presentation.v3.md`
+ `src/beril_adversarial/skill/tools/validate_presentation_review.py`.

**Class enum (v3):**

| Class | Severity range | Dispatch |
|---|---|---|
| `register_drift` | P0/P1 | REVISE → revise_slide.v1 |
| `claim_evidence` | P0/P1 | REVISE → revise_slide.v1 |
| `qa_softball` | P1/P2 | REVISE → revise_slide.v1 |
| `substory_arc` | P0/P1 | REVISE → revise_slide.v1 |
| `missing_slide` | P0/P1 | ADD → add_slide.v1 |
| `throughline` | info | SURFACE_ONLY (next_actions.md) |
| `central_objection` (v3 NEW; renamed from narrative_weakness) | info | SURFACE_ONLY |
| `citation_reality` (v3 NEW) | P1/P2 | SURFACE_ONLY (human verification needed) |
| `unbacked_quantitative` | P0/P1 | SURFACE_ONLY (handled by check_quantitative_grounding) |

The dispatch tuples in `revise_loop.py` (`REVISE_CLASSES`,
`ADD_CLASSES`, `SURFACE_ONLY_CLASSES`, `DECK_WIDE_OBJECTION_CLASSES`)
are the canonical consumer-side mapping. Adding a new class to
adversarial v3 requires a corresponding decision in revise_loop's
dispatch table; failure to update routes the new class to the
fallback "unknown class → surface-only" path (safe default).

**v2 backwards-compat:**
`narrative_weakness` (v2 audit files) is still accepted by
`revise_loop.SURFACE_ONLY_CLASSES` for forensic compatibility.
Maps to the same role as v3's `central_objection`. Will be removed
when both teams confirm v3 adoption (per adversarial team's
event-driven deprecation policy).

**Required field per finding:**
- All findings: `id`, `class`, `severity`, `issue`
- Slide-level findings: `slide_id` (int) for spec-bound classes
- `citation_reality` only: `citation_id` (string; bibtex key | DOI |
  REPORT.md section reference)
- `register_drift` / `claim_evidence` / `qa_softball`: `title_quote`
  required per validator D-conditional rule

**Validator behavior** (presentation-maker side):
- `revise_loop.py` reads `audit/adversarial_review.json`, dispatches
  per class.
- Surface-only findings are consolidated into
  `working/next_actions.md` with the class-specific section heading
  ("The deck's central objection" for central_objection /
  narrative_weakness; "Citation verification needed" for
  citation_reality).
- Cost-bounded: `--max-revise-cost-usd 5.00` default; revise loop
  halts when cumulative cost exceeds.

**Smoke test:**
`tests/integration/test_adversarial_interop.py` —
`@pytest.mark.integration`, gated. Asserts (a) exits 0, (b) output
file exists, (c) JSON parses, (d) `schema_version ==
"adversarial-review-presentation.v3"`. Live LLM cost ~$0.50/run.

### 3.2 `citation_pool.json` reuse-from-paper

**Location:** `<project>/papers/draft_*/citation_pool.json` (or
`pool.json`) emitted by `beril-paper-writer`'s pipeline.

**Source of truth (producer side):** beril-paper-writer
`tools/citation_pool.py` (9-field schema).

**Reuse mechanism:** presentation-maker's `stage_citation_pool`
detects `<project>/papers/draft_*/{citation_pool,pool}.json` and
runs:

```bash
citation_pool.py reuse-from-paper <paper_draft_dir> <talk_draft_dir>
```

The paper's pool entries are copied verbatim into the talk's
`working/citation_pool.json`; the LLM-driven citation_pool stage
then ADDS only talk-needed entries with `notes='added by talk'`.
Saves ~$1.00 in verify-by-resolution cost when a sibling paper
draft exists.

**Schema invariant:** the 9-field schema (key, title, authors,
year, venue, type, doi/pmid/url, source, notes) is shared between
paper and talk drafts. Schema changes coordinate with the
paper-writer team.

### 3.3 Project inputs

presentation-maker reads from the BERDL project directory:

| Input | Required? | Used by stage |
|---|---|---|
| `REPORT.md` | YES (at minimum the canonical findings) | plan, throughline, slide_compose, citation_pool, check_quantitative_grounding |
| `RESEARCH_PLAN.md` | YES (design intent) | plan, throughline |
| `figures/` (or `figs/`, `plots/`, `output/figures/`, `results/figures/`) | At least one .png | curate_figures, slide_compose |
| `notebooks/*.ipynb` | At least one notebook | curate_figures (savefig context for captions) |
| `references.md` (optional) | NO | citation_pool (seed bibliography if present) |
| `papers/draft_*/citation_pool.json` (optional) | NO | citation_pool (reuse-from-paper if present) |

**Path resolution:** figure paths in `slide_spec.json` resolve
relative to `<project_dir>` (e.g., `figures/burden_by_function.png`).
The validator hard-rejects the deprecated `figures/curated/<name>`
segment (changelog 2026-04-27).

**Project source files are NEVER modified.** All writes scope to
`talks/draft_N/`. This is invariant.

---

## 4. CLI surface — interop guarantees

### 4.1 Subcommands

The Python CLI exposes 6 subcommands (in cli.py registration order):

| Subcommand | Purpose | Stable? |
|---|---|---|
| `install-skill <BERIL_ROOT>` | Copy skill files into BERIL/.claude/skills/ | Stable |
| `configure` | Verify claude CLI + python deps + CBORG_API_KEY status | Stable |
| `draft <project_id>` | Run the full 14-stage pipeline | Stable |
| `continue <draft_dir> --resume-from <stage>` | Re-run from a named stage | Stable |
| `assemble <draft_dir>` | Re-render .pptx from existing slide_spec.json (no LLM) | Stable |
| `prune <project_id>` | Clean up old drafts (v0.3.4.1) | Stable |

External scripts may rely on these names + flag sets. Removing or
renaming a subcommand is BREAKING. Adding new subcommands is
non-breaking.

### 4.2 Flag pass-through invariant

The bash orchestrator (`tools/presentation_maker.sh`) is the
canonical flag set. The Python CLI wrappers (`commands/draft.py`,
`commands/continue_run.py`) MUST forward every bash flag.

Pre-v0.3.3.2, the Python wrappers were missing v0.3.0 flags
(`--no-adversarial`, `--max-revise-cost-usd`, `--max-revisions`)
and v0.3.3 image-gen flags (`--no-images`, `--auto-approve-images`,
`--image-allow-exploratory`, `--max-image-cost-usd`,
`--image-style`). v0.3.3.2 closed this gap. Memory:
`feedback_verify_cli_before_recommending.md` documents the
recurrence pattern.

**Maintainer rule:** any new bash flag added to
presentation_maker.sh MUST also land in `commands/draft.py` and
`commands/continue_run.py` in the same commit, or it's unreachable
through the production CLI. Same convention applies to
beril-adversarial's `review` subcommand.

### 4.3 `--resume-from` valid stages

The stable resume-API contract. Adding/removing stages from this
list is BREAKING for any consumer that scripts `--resume-from`:

```
plan, throughline, substory_design, curate_figures, citation_pool,
cross_tenant, intro, slide_compose, qa_prep, speaker_notes,
image_gen, merge, adversarial_review, revise_slides
```

`image_gen` was added in v0.3.3, `adversarial_review` + `revise_slides`
in v0.3.0. `merge` is stage 12 in v0.3.3+ (was 11 pre-v0.3.3 image-gen
insertion).

The case statement in `presentation_maker.sh` and `_VALID_STAGES`
in `commands/continue_run.py` MUST stay in sync. Drift surfaces as
an `invalid --resume-from` error from one or the other.

### 4.4 Exit code semantics

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | User error (bad args, missing draft_dir, missing input file the user should fix) |
| 2 | Runtime error (subprocess failed, package data missing) |
| 3 | Config error (claude not installed; tools unavailable) |

Stable across v0.3.x. Scripts may rely on these distinctions.

---

## 5. Versioning policy

### 5.1 Schema-version stability

Producer schemas (§2) carry an explicit `schema_version` field.
**Within v0.3.x, all schemas are stable.** Consumers that match on
`schema_version == "..."` will keep working through every v0.3.x
point release.

### 5.2 Backwards compatibility expectations

Minor bumps (v0.3.x → v0.3.x+1):
- Adding optional fields to a producer schema: NON-BREAKING.
- Adding new layouts to slide_spec: semi-BREAKING (forces image-gen
  decision-layer update + slide-compose / merge / assemble support).
- Renaming an existing field: BREAKING; coordinated via dual-mode
  transition release.
- Removing a class or layout: BREAKING; coordinated via deprecation
  timeline.

Major bumps (v0.4 → v1.0 → v2.0):
- May break any schema with explicit migration messaging.
- Producer ships dual-mode for at least one transition release
  before removing old support.
- Mirrors the adversarial team's "event-driven, not calendar-driven"
  policy: removal happens AFTER both producer and consumer teams
  confirm new-version adoption in production.

### 5.3 Worked example: adversarial v2 → v3 migration

The v0.7.0.1 adversarial migration is the reference pattern:

1. **v0.7.0 produces v3 reviews exclusively.** v3 hard-rejects the
   dead class name `narrative_weakness` (D1 in adversarial CONTRACT).
2. **v3 validator still accepts v2 audit files** for forensic
   compatibility (reading prior audit history doesn't break).
3. **presentation-maker v0.3.3.1 ships consumer-side migration:**
   `revise_loop.SURFACE_ONLY_CLASSES` lists BOTH `central_objection`
   (v3) and `narrative_weakness` (v2). Both names route to
   surface-only.
4. **Removal milestone:** when both teams confirm v3 adoption in
   production (event-driven), adversarial drops v2 acceptance and
   presentation-maker drops `narrative_weakness` from its dispatch
   tuple.

This is the template for any future schema rename.

---

## 6. Known interop quirks

### Slash command vs. CLI subcommand syntax

The slash command (`/beril-presentation-maker <project_id>`) and the
Python CLI (`beril-presentation-maker draft <project_id>`) are
functionally equivalent but syntactically different. Mirror the
user's chosen surface in agent responses; do NOT describe one as if
it were the other. SKILL.md §"Surface syntax — DO NOT conflate the
two" has the side-by-side comparison.

This convention mirrors the adversarial team's identical lesson
learned during their v0.7.0 hub test (their SKILL.md L60-87).

### Manifest wipe before re-roll

If a prior image_gen attempt recorded a rejection in the manifest
(slide_id-keyed entries are unique), re-running with
`--resume-from image_gen` against the same draft_dir will fail with
`slide_id <X> already in manifest`. To force a re-roll, either:

- `rm <draft>/working/05_images/manifest.json` (clean re-roll;
  image_provenance.json preserved), or
- Hand-edit the manifest to remove the offending entry.

The orchestrator does NOT auto-wipe the manifest because rejection
history is intentional audit data.

### `--image-style` override forces re-author past cache

The v0.3.4.1 cache-reuse decision skips the LLM authoring when
`<slide>_request.json` exists + slide_id verifier passes + cached
style matches `--image-style`. If `--image-style` differs from the
cached request's style, the cache is invalidated and a fresh LLM
authoring runs. This is intentional: a style override is a content
change.

### v0.3.0-shape drafts are non-migratable

Pre-v0.3.1 drafts used a flat layout (`talks/draft_N/<files>` at top
level). v0.3.1+ uses 4-zone (deliverable/narrative/working/audit/).
There is NO migration tool. The orchestrator detects v0.3.0-shape
drafts and hard-fails with a clear error. Users on the hub: start
fresh.

---

## 7. Cross-skill smoke tests in this repo

Producer-side tests cannot enforce that consumers call us correctly.
This repo carries consumer-side smoke tests for the producers we
read from:

### `tests/integration/test_adversarial_interop.py`

Marker-gated (`@pytest.mark.integration`), runs only with `pytest -m
integration`. Three layers:

1. **Unit-level shape checks** (always run, no LLM cost):
   - Orchestrator invokes `beril-adversarial review --type
     presentation "$OUTDIR"`.
   - `--help`-based subcommand probe for graceful pre-v0.6.0 fallback.
   - `command -v beril-adversarial` skip-guard for not-installed case.

2. **Live integration** (gated; ~$0.50/run on Sonnet):
   - Resolves BERIL_ROOT (env var → workspace fallback → skip).
   - Auto-discovers a real complete v0.3.1+ draft (latest by N) under
     `<BERIL_ROOT>/projects/*/talks/`.
   - Snapshots existing `audit/adversarial_review.{md,json}` first;
     restores in `finally:` whether test passes or fails.
   - Invokes real `beril-adversarial review --type presentation
     <draft> --beril-root <root>`.
   - Asserts (a) exit 0, (b) output exists, (c) JSON parses, (d)
     schema_version is v3 exactly.

3. **Operator override:** `TEST_DRAFT_DIR=<path>` env var pins a
   specific draft for the live test.

This test caught the v0.7.0.1 schema-version drift early. Pattern
generalizes — when a future producer ships a schema bump, add (or
extend) a similar consumer-side smoke before the consumer
integrates the change.

### Hypothetical extensions

When paper-writer ships v0.6+ citation_pool reuse-from-paper as a
public API, add `tests/integration/test_paper_writer_interop.py`
mirroring the adversarial pattern: 3 unit-level shape checks +
1 marker-gated live test that asserts pool reuse works against a
real paper draft.

---

## 8. Document maintenance

### When to update CONTRACT.md

- Producer-side schema change (any field added / renamed / removed).
- Consumer-side schema migration (e.g., adversarial v3 → v4).
- CLI surface change (subcommand added, flag added/renamed/removed,
  exit code semantics changed).
- Stage list change (`--resume-from` valid stages).
- Cross-skill smoke test added or substantially revised.

### Test surface

A future regression test could grep this document for every
declared `schema_version` and assert the matching Python source
file declares the same string. Not implemented in v0.3.4.3; track as
backlog if drift becomes a problem.

### Reference docs

- `SKILL.md` — agent-facing skill instructions (slash commands,
  workflow, output artifacts).
- `HUB_INSTALL.md` — operator install runbook (pipx, install-skill,
  configure, troubleshooting).
- `SPEC.md` — internal design rationale (load-bearing).
- `LAYOUT.md` — runtime contracts for the per-draft layout.
- `DECISIONS.md` — design-decision log (D-001 through D-029+).
- `RELEASE_NOTES.md` — per-version changelog.
- `V0_3_3_ARCHITECTURE.md` — v0.3.3 image-gen architecture (informs
  §2.2-2.4).
- `V0_3_1_PUNCH_LIST.md` — v0.3.x release tracking (mostly historical
  by v0.3.4.3).

---

## Appendix: contract-version table

For quick reference, every schema in this contract:

| Schema | Producer / Consumer | Version | Path |
|---|---|---|---|
| slide_spec.v1 | producer | `1.0` | `working/slide_spec.json` |
| image-manifest.v1 | producer | `image-manifest.v1` | `working/05_images/manifest.json` |
| image-decisions.v1 | producer | `image-decisions.v1` | `working/05_image_decisions.json` |
| image-request.v1 | producer | `image-request.v1` | `working/05_image_requests/<slide_id>_request.json` |
| image_provenance | producer | `1.0` | `audit/image_provenance.json` |
| stage-metadata.v1 | producer (v0.3.4.2 NEW) | `stage-metadata.v1` | `audit/stage-metadata.json` |
| run-summary.v1 | producer (v0.3.4.2 NEW) | `run-summary.v1` | `audit/runs/run-N/summary.json` |
| adversarial-review-presentation.v3 | consumer | `adversarial-review-presentation.v3` | `audit/adversarial_review.json` |
| citation_pool 9-field | consumer | (paper-writer canonical) | reused from `<project>/papers/draft_*/citation_pool.json` |
