# beril-presentation-maker-skill v0.3.x — punch list

**Last updated:** 2026-05-01.
**Goal:** From the v0.3.0 ship through to v1.0 candidacy. Tables and
images both operational, drop-in tested on KBERDL JupyterHub.

This document supersedes the original v0.3.1-only scope (2026-04-30
draft, retained in section history below). The cycle splits into
four tagged releases plus a v1.0 gate.

## Release sequence

```
v0.3.0 (SHIPPED 2026-04-30 c39f9aa)
  └── v0.3.1 — Layout cleanup + Stream A wrinkles
        ~2 days. PRECONDITION for tables/images. Reduces future drag.
        └── v0.3.2 — data_table layout
              ~2 days. Smoke on LIGHT BERDL project.
              └── v0.3.3 — image-gen orchestrator stage
                    ~3 days. Smoke on MEDIUM BERDL project.
                    └── v0.3.4 — cross-feature smoke + KBERDL hub install
                          ~1 day build + iteration. Multi-project gate.
                          └── v1.0 — gate (audit + tag)
```

Total to first cross-feature smoke: ~7 working days. KBERDL drop-in
follows immediately.

---

## v0.3.1 — Layout cleanup + Stream A wrinkles (precondition)

**Why first.** The `projects/<id>/talks/draft_N/` directory currently
has 30+ files at top level mixing deliverables, stage outputs, audit
debris, and test residue. Adding tables (small) and images (10-30
new files per draft) on top of this chaos compounds the mess. v0.3.1
introduces a clean 4-zone layout (`deliverable/`, `narrative/`,
`working/`, `audit/`) that scales to v0.3.3+ without further reorg.

Adam-only-tester scope: clean break, no migration of historical
drafts, no backwards-compat in `assemble`. v0.3.0-shape drafts get a
clear error message; users either run a new draft or delete the old.

### T0. 4-zone directory layout

**Schema:**

```
projects/<id>/talks/draft_N/
├── deliverable/
│   ├── draft.pptx
│   ├── draft.pdf
│   └── speaker-notes.pdf      (if assembled)
├── narrative/
│   ├── 00_throughline.md       (CHOSEN throughline)
│   ├── 02_substories.md
│   ├── references.md
│   ├── bibliography.bib
│   └── citation_map.md
├── working/
│   ├── 00_plan.md
│   ├── 00_throughline_candidates.md
│   ├── 03_slides/
│   ├── 04_speaker_notes/
│   ├── 05_image_requests/      (v0.3.3)
│   ├── 05_images/              (v0.3.3 generated PNGs)
│   ├── citation_pool.json
│   ├── cross_tenant_signal.{json,md}
│   ├── curated_figures.md      (CANONICAL — figures_curated.md killed)
│   ├── figures_inventory.md
│   ├── diagram_repair_report.md
│   ├── next_actions.md
│   └── slide_spec.json         (LIVE spec)
└── audit/
    ├── state.json
    ├── cost-log.jsonl
    ├── stage-metadata.json     (CONSOLIDATED — replaces 13 scattered .metadata.json)
    ├── stage-logs/
    │   ├── 00_plan.{stdout,stderr}
    │   └── ...
    ├── snapshots/
    │   ├── slide_spec.raw.json
    │   ├── slide_spec.pre_revise.json
    │   ├── slide_spec.post_assemble.json
    │   └── last-render.pptx    (manual-edit detection baseline)
    ├── manual-edits/           (if user touched deliverable/draft.pptx)
    │   └── <UTC-timestamp>.pptx
    ├── runs/                   (replaces audit-fail-N/)
    │   ├── run-1/
    │   └── run-2/
    ├── adversarial_review.{json,md,original-summary.json}
    ├── quantitative_grounding.{json,md}
    └── revise_loop_metadata.json
```

**Acceptance:** a freshly-run draft has 4 top-level entries
(`deliverable/`, `narrative/`, `working/`, `audit/`). Zero leaked
test residue. Zero `*.stderr` at top. No `figures_curated.md`.

### T1. Tool path updates

Every tool that reads or writes a per-draft file needs path updates.

| File | Read changes | Write changes |
|---|---|---|
| `tools/presentation_maker.sh` | `OUTDIR=<draft_dir>`; computes paths to subdirs; ensures dir layout exists pre-stage 0 | Each stage routes to its zone |
| `tools/revise_loop.py` | `working/slide_spec.json` | `audit/snapshots/slide_spec.pre_revise.json` (snapshot); mutates `working/slide_spec.json`; metadata to `audit/revise_loop_metadata.json` |
| `tools/assemble_pptx.py` | `working/slide_spec.json` | `deliverable/draft.pptx`; post-write hash → `audit/last-render.json`; copy to `audit/snapshots/last-render.pptx` |
| `tools/build_master.py` | (orchestrator passes spec via stdin) | (orchestrator routes outputs) |
| `tools/check_quantitative_grounding.py` | `working/slide_spec.json` | `audit/quantitative_grounding.{json,md}` |
| `tools/curate_figures.py` | project-level paths unchanged | `working/curated_figures.md`, `working/figures_inventory.md`; stderr → `audit/stage-logs/curate_figures.stderr` |
| `tools/citation_pool.py` | project-level paths unchanged | `working/citation_pool.json` + `narrative/citation_map.md` |
| `tools/parse_substories.py` | working/03_slides as needed | `narrative/02_substories.md` |
| `tools/parse_throughline_candidates.py` | working stage outputs | `working/00_throughline_candidates.md`; chosen throughline → `narrative/00_throughline.md` |
| `tools/parse_speaker_notes.py` | per-slide notes | `working/04_speaker_notes/` |
| `tools/merge_compose_fragments.py` | `working/03_slides/*` | `working/slide_spec.json`; snapshot to `audit/snapshots/slide_spec.raw.json` |
| `tools/repair_diagram_stubs.py` | `working/slide_spec.json` | `working/diagram_repair_report.md` |
| `tools/diagram_render.py` | mermaid stubs from slide_spec | (renders inline; mermaid-cli stderr to audit/stage-logs/) |
| `tools/poster_fill.py` | `working/slide_spec.json` | `deliverable/poster.pptx` |
| `tools/extract_cross_tenant.py` | project-level paths unchanged | `working/cross_tenant_signal.{json,md}` |
| `tools/stream_progress.py` | (consumed by orchestrator) | per-stage logs to `audit/stage-logs/<stage>.{stdout,stderr}` |
| `commands/continue_run.py` | `audit/state.json` | `audit/state.json` |
| `commands/assemble.py` | `working/slide_spec.json` | invokes assemble_pptx |
| `commands/draft.py` | (initial dir creation) | initializes 4-zone skeleton |

### T2. Hygiene

- **Kill `figures_curated.md` duplicate.** Audit which tools write
  it and which read it; standardize on `working/curated_figures.md`.
  Remove the alias.
- **Stop `*.stderr` leakage at top level.** Every helper that emits
  stderr routes to `audit/stage-logs/<stage>.stderr` via the
  orchestrator wrapper.
- **Stop smoke-residue accumulation.** No file named
  `slide_spec.v0XX_smoke.json` or similar at top level. Smoke runs
  during dev should write to a separate dir, not the same draft.

### T3. Manual-edit safety

User concern: pipeline regenerates `deliverable/draft.pptx` and
clobbers manual PowerPoint edits. Solution: snapshot-then-warn (NO
blocking, no flag gymnastics).

**Mechanism:**

```
After assemble:
  - sha256(deliverable/draft.pptx) → audit/last-render.json
  - copy deliverable/draft.pptx → audit/snapshots/last-render.pptx

Before next assemble:
  - if hash(deliverable/draft.pptx) != stored hash:
      copy current draft.pptx → audit/manual-edits/<UTC-timestamp>.pptx
      WARN to stderr:
        "deliverable/draft.pptx was modified since last render.
         Your edited copy has been saved to audit/manual-edits/...
         before regeneration. See SKILL.md §manual-edits."
      proceed with regeneration
  - else: proceed silently
```

No blocking, no `--force` flag needed, no `--absorb-manual-edits`
round-trip. User always gets a fresh deck after assemble; previous
manual edits are always preserved (in audit/); they always know it
happened.

**SKILL.md §manual-edits** documents:
- Pipeline-owned (`deliverable/draft.pptx`) vs user-owned (anywhere
  else the user saves it) files.
- Recommended workflow: run pipeline to convergence → copy
  `deliverable/draft.pptx` somewhere outside the project → polish
  that copy.
- What the audit/manual-edits/ snapshot is for (preserved edits;
  diff with audit/snapshots/last-render.pptx to identify deltas).
- How to make edits stick across re-runs: edit
  `narrative/02_substories.md` for content (re-run from slide_compose),
  or `working/slide_spec.json` directly for surgical fixes (re-run
  from assemble). slide_spec.json is JSON; common edit patterns
  documented inline.

### T4. Stream A wrinkles

These were flagged during the v0.3.0 draft_10 live test that landed
F001 + F003 cleanly. Co-located in v0.3.1 because A1 will conflict
with the path reorg anyway, and A2 is a small prompt edit.

**A1. `_insert_slide_into_spec` position fallback.** When the
adversarial review's `add_slide.v1` produces a finding with
`position=N` but existing slides lack `position` fields, the insert
function falls through to "append at end" instead of computing the
right insertion index. In v0.3.0 live test, F003's new slide was
supposed to land after slide 9 but ended up at end-of-deck.

Fix: in `tools/revise_loop.py::_insert_slide_into_spec` (or wherever
the logic lives), fallback chain:
1. Use `substory_id` to identify the substory's last slide and
   insert immediately after it.
2. Index by slide-array order matching the finding's `fix_hint`
   text ("between current slides 8 and 9").
3. Append-at-end (current behavior) WITH a stderr warning surfacing
   the position drift.

Acceptance: synthetic test where spec has no position fields + new
slide with `position=9` lands at array-index 9, not end-of-deck.

**A2. Register discipline propagation in `add_slide.v1.md`.** F003's
new slide title contained "high-confidence" — same overclaim F001
fixed elsewhere. `add_slide.v1.md` doesn't read the deck-level tier
register, so it can introduce drift even when adjacent slides have
been corrected.

Fix: add anti-pattern section + per-tier register cheat-sheet
(mirror from `revise_slide.v1.md`). Self-review checklist item:
"Does any title or bullet contain a tier-forbidden verb?"

Acceptance: re-run F003 against updated prompt; new slide title no
longer contains "high-confidence". Unit test mocking an
EXPLORATORY-tier finding with high-confidence-leaning data shape;
assert LLM output does not contain forbidden verbs.

### T5. Tests + ship

- Layout schema test: post-init dir has 4 zones present.
- Hash-guard test: synthetic mismatch → snapshot + warning.
- A1 unit test: position-fallback chain.
- A2 unit test: tier-violating verb absent from add_slide output.
- Full suite green (current 402 + ~10 new).
- Wheel rebuild + install-skill round-trip (your shell, not sandbox).
- Smoke: fresh draft on a small project; verify layout + manual-edit
  warning works.
- RELEASE_NOTES.md flagged BREAKING (layout changed).
- `.commit-message-v0_3_1.txt`.

### Out of v0.3.1 scope

- Migration tool (`reorg <draft_dir>`). Adam will delete old drafts
  manually.
- Backwards-compat detection in assemble. v0.3.0-shape drafts error
  with clear "old layout" message; user re-runs from scratch.

---

## v0.3.2 — `data_table` layout

**BLOCKED-BY:** v0.3.1 ships.

**Why.** `add_slide.v1.md` already references `data_table` as a
target for "Top-N ranking with multiple columns" but the layout
doesn't exist in `slide_spec.py` or `assemble_pptx.py`. Current
fallback is `claim_evidence` with bullets-as-rows, capped at 3.
For real top-N findings, this loses the bottom rows.

**Reference:** `beril-paper-writer` ships table rendering via
python-docx. Adapt for python-pptx (different API:
`slide.shapes.add_table(rows, cols, left, top, width, height)`).

**Design.**

- **Spec schema:**

  ```json
  {
    "layout": "data_table",
    "content": {
      "title": "Top 10 dark-matter candidates",
      "columns": ["Gene", "Organism", "Score", "Evidence"],
      "rows": [
        ["AO356_11255", "P. putida", "0.92", "ML+conservation"],
        ...
      ],
      "caption": "Top 10 candidates ranked by ensemble score (REPORT.md §4.2).",
      "footnote": "Full ranking in REPORT.md §4.2 (n=347).",
      "highlight_rows": [0, 2]
    }
  }
  ```

- **Caps (validator-blocking):** rows ≤ 12, cols ≤ 6, all cells are
  strings (caller stringifies with desired precision).
- **Master template:** new `data_table` layout in `build_master.py`
  with title placeholder + body region for the table.
- **Assembler:** `_fill_data_table(slide, content)` in
  `assemble_pptx.py`. KBase-branded styling: header row background
  `#007DC3` (blue), white header text, alternating row bands
  (white / `#F2F2F2`), `#F78E1E` (orange) row highlight when index
  ∈ `highlight_rows`. Caption box below table. Footnote at
  slide-bottom.
- **Validator:** row/col caps + all-string cell verification.
- **Update `add_slide.v1.md`:** remove the "fall back to
  claim_evidence with bullets-as-rows" workaround; reference the
  v0.3.2 layout directly.

**Acceptance.** Live test where a `missing_slide` finding requesting
"top-10 candidates" produces a clean table (10 rows, 4 cols, header
row blue, no overflow into bottom logos). Master re-render passes
the existing layout walker. 402+ tests green plus new schema +
render tests.

**Smoke target:** LIGHT BERDL project (likely `core_gene_tradeoffs`
based on current state, pending upstream pull).

**Effort:** ~2 days.

---

## v0.3.3 — image-gen orchestrator stage

**BLOCKED-BY:** v0.3.2 ships (so tables exist as a "never use image"
exemption case in the decision layer).

**Why.** v0.3.0 shipped the calibrated client + the calibrated
prompt template, but the orchestrator does not automatically flag
`concept_illustration` slides for image generation. Channel A
(LLM-initiated) has prompt-spec but no production stage invokes it.

**Design.** Three-layer pipeline inserted between `slide_compose`
and `merge_compose_fragments`:

1. **Decision layer** — `ai_image_decision.v1.md`. Per-slide gate:
   does this slide actually benefit from an image? Inputs: slide
   layout, substory shape, tier register, deck mode. Outputs:
   `image_helps: bool` + rationale. Hard rules:
   - NEVER on `data_figure` (already has a figure)
   - NEVER on `data_table` (table IS the content)
   - NEVER on `acknowledgments`, `references`, `qa_anticipated`,
     `methods_summary`, `section_divider`, `title`
   - PROBABLY on `concept_illustration` (it's literally what the
     layout is for)
   - SOMETIMES on `claim_evidence` if the substory needs visual
     grounding the existing figures don't provide
   - NEVER on EXPLORATORY tier without explicit user opt-in

2. **Spec layer** — `ai_image_brief.v1.md`. When decision=true,
   generate the image brief: what concept to depict, what aspect
   ratio, what region of the slide, what to AVOID. Calibrated style
   defaults from v0.3.0:
   - Style: `scientific_illustration` (T2 winner)
   - Palette: KBase brand hex `#007DC3` / `#5E9732` / `#F78E1E`
   - In-image text permitted when explicitly named (T3 verdict)
   - For genome-coverage opener slides: genome-ring pattern (T4)

3. **Prompt layer** — `ai_image_prompt.v1.md` (already in v0.3.0).
   Takes the brief → composes the model-ready prompt → stages the
   request JSON in `working/05_image_requests/<slide_id>_request.json`.

**Orchestrator stage** (Stage 6.5, between slide_compose=06 and
merge=07):

```bash
stage_image_gen() {
  for each slide in working/03_slides/*:
    decision = invoke ai_image_decision.v1
    if decision.image_helps:
      brief = invoke ai_image_brief.v1
      request = invoke ai_image_prompt.v1
      # gate user approval per D-029
      if user_approves(request):
        png_path = invoke image_client.py with request
        update curated_figures.md to include png_path as candidate
        update slide content to reference png_path
}
```

**Cost cap:** `--max-image-cost-usd` (default $0.50, ~30 images at
T0-calibrated $0.014/image). User approval gate per slide; bulk
approve flag (`--auto-approve-images`) for power users.

**Integration with curated_figures.md:** generated PNGs land at
`working/05_images/<slide_id>.png`; appended to `curated_figures.md`
as candidates with provenance metadata (model, prompt hash, cost).
Slide_compose reads curated_figures to bind the image to a slide.

**Acceptance.** Live test on chosen MEDIUM project where ~3-8 slides
get flagged for images, all gated through user approval, ~$0.10-0.15
budget for the run, generated images land in `working/05_images/`
and integrate into `curated_figures.md` as candidates. No regression
on existing pipeline; `--no-images` flag disables the stage cleanly.

**Smoke target:** MEDIUM BERDL project (likely `fitness_modules` or
similar, pending upstream pull).

**Effort:** ~3 days. 2 new prompts + orchestrator stage + tests +
smoke.

---

## v0.3.4 — cross-feature smoke + KBERDL hub install

**BLOCKED-BY:** v0.3.3 ships.

**Why.** Multi-project gate before v1.0 (Adam: "test on 3 projects
then v1.0"). KBERDL/KBase 2.0 JupyterHub is the final user-facing
deployment target. Atlas + adversarial reviewer already work on the
hub via the same pipx + install-skill pattern; presentation-maker
should slot in identically IF separability + artifact organization
hold.

**Local smoke (~1 day):**

- Pull beril-extended from upstream.
- Pick 3 BERDL projects of increasing complexity from refreshed
  list. Suggested triage:
  - LIGHT (~1 notebook, <200 line REPORT) — full pipeline + tables,
    no images expected
  - MEDIUM (~5-7 notebooks, 200-400 line REPORT) — full pipeline +
    tables + 3-5 images
  - HEAVY (~10+ notebooks, >400 line REPORT) — full pipeline + tables
    + 5-10 images. Probably `functional_dark_matter` updated, or
    fresh comparable
- For each: run `beril-presentation-maker draft <project_dir>` to
  completion. Verify deliverable, narrative, working, audit zones
  populate correctly. Verify tables render where applicable. Verify
  images integrate where flagged.
- For each: re-run pipeline after a manual PPTX edit. Verify the
  warning + audit/manual-edits/ snapshot.
- For each: run a revision via `--resume-from substory_design`.
  Verify clean re-rendering.

**KBERDL hub deployment (~1 day + iteration):**

- Confirm CBORG_API_KEY availability in user venv (Adam confirms
  this works for atlas + adversarial; presentation-maker should
  inherit). Document fallback if not present (--no-images skips
  cleanly).
- Confirm Claude Code presence on hub. Document install path if
  missing.
- Confirm pipx + install-skill works in user venv (per Adam: same
  pattern as atlas + adversarial which are operational).
- Smoke a draft on a hub project via slash command:
  - `/beril-presentation-maker <project_id>`
  - `/beril-presentation-maker-continue <draft_dir>`
- Verify deliverable lands in expected location (per-user file
  storage on JupyterHub).
- Write **HUB_INSTALL.md** runbook (or extend SKILL.md) covering:
  - pipx install command for hub users
  - install-skill placement
  - CBORG_API_KEY setup
  - slash-command usage
  - troubleshooting per failure mode

**Acceptance.** Three full pipelines pass on local beril-extended.
At least one full pipeline runs successfully on KBERDL via slash
command, producing a viewable deck. Install runbook reviewed by
someone other than Adam.

---

## v1.0 — gate

**BLOCKED-BY:** v0.3.4 ships.

Not a build cycle; an audit + tag.

- All test suite green (~450+ tests by this point).
- Cross-feature smoke clean on 3+ projects.
- KBERDL drop-in verified.
- Documentation complete (SKILL.md, HUB_INSTALL.md, RELEASE_NOTES).
- Tag v1.0 on ArkinLaboratory/beril-presentation-maker-skill main.
- Update augmentation-stream-plan.md with the v1.0 ship.

---

## Out of v0.3.x scope

- KBase Co-Scientist orchestrator integration (separate stream).
- Manual-edit round-trip (`import-edits` PPTX → slide_spec.json).
  Research-grade hard; v0.4+ if at all.
- `reorg` migration command for v0.3.0-shape drafts. Adam will
  delete manually.

---

## History

The original v0.3.1 punch list (2026-04-30) covered three tiers:
Stream A wrinkles (A1, A2), image-gen orchestrator stage (B1), and
data_table (C1). The 2026-05-01 revision splits this into four
tagged releases (v0.3.1 layout cleanup + Stream A wrinkles, v0.3.2
data_table, v0.3.3 image-gen orchestrator, v0.3.4 cross-feature
smoke + hub) following Adam's "skills must be cleanly packaged to be
separable + artifacts in projects should be well organized" framing.
The cleanup was added as a precondition because adding tables (small)
and images (10-30 new files per draft) on top of the v0.3.0 chaos
would compound the mess. Adam-only-tester scope means clean break,
no migration, no backwards-compat.
