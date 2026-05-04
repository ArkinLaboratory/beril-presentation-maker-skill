---
name: beril-presentation-maker
description: |
  Draft evidence-grounded scientific presentations (talks + posters) from
  BERDL analysis projects, in KBase brand. Pipeline: plan → throughline →
  substory_design → curate_figures → citation_pool → cross_tenant → intro →
  slide_compose → qa_prep → speaker_notes → image_gen → merge → adversarial
  review → revise loop. Generates AI illustrations for concept_illustration
  slides via CBORG (Channel A, calibrated). Reuses project figures verbatim;
  validates every claim against REPORT.md. Produces speaker notes,
  anticipated Q&A, citation pool, and a full audit trail. Use when a BERDL
  project (REPORT.md + notebooks + RESEARCH_PLAN) needs a talk or poster
  derived from the project's evidence.
allowed-tools: Bash, Read, Write, AskUserQuestion
user-invocable: true
---

# BERIL Presentation Maker

Drafts a scientific presentation from a BERDL analysis project. Reads
the project's `REPORT.md`, `RESEARCH_PLAN.md`, notebooks, and figures;
produces a complete .pptx (or poster .pptx) plus speaker notes, Q&A
prep, citation pool, an adversarial review with revise-loop integration,
and AI-generated illustrations for `concept_illustration` slides.

The skill ships as a pip-installable Python package
(`beril-presentation-maker-skill`) plus a Claude Code skill installed at
`<BERIL>/.claude/skills/beril-presentation-maker/`. The Python layer
handles install + configuration. The drafting itself runs through a
shell orchestrator (`tools/presentation_maker.sh`) that invokes
per-stage prompts as `claude -p` subagents and writes a validated
`slide_spec.json` that `assemble_pptx.py` renders to .pptx.

**Status: v0.3.4.4 — production-ready, hub-deployable.** v0.3.4.x
trajectory: docs (v0.3.4) → prune CLI subcommand (v0.3.4.1) →
audit/runs + stage-metadata.json consolidation (v0.3.4.2) →
CONTRACT.md cross-skill interop pinning (v0.3.4.3) → README +
RELEASE_NOTES rollup (v0.3.4.4). Production stack: 14-stage
pipeline including image_gen (Channel A, CBORG-calibrated
$0.014/image) + adversarial v0.7.0.1 review-rewrite loop with
`central_objection` + `citation_reality` class routing.
KBase-branded master + slide_spec validator (16 layouts) + 4-zone
draft layout + manual-edit hash guard + request-cache reuse +
prune subcommand + per-run audit summaries via trap-EXIT hook.
726 unit tests + 1 marker-gated live integration test. See
`RELEASE_NOTES.md` for the v0.3.x trajectory and `CONTRACT.md`
for cross-skill interop.

## Two ways to invoke a draft

The skill exposes the same drafting functionality via two surfaces.
Pick the right one for your context:

| Surface | When to use | How it's called | Where it lives |
|---|---|---|---|
| **`/beril-presentation-maker` slash command** | Interactive use inside Claude Code from a BERIL deployment. User-driven draft of a talk or poster. | `/beril-presentation-maker [<project_id>] [--mode ...]` (Claude Code agent then runs the orchestrator per the workflow below). | `commands/beril-presentation-maker.md` (this skill). |
| **`beril-presentation-maker draft` CLI subcommand** | Programmatic invocation from another orchestrator, scripted workflows, CI/CD, or direct shell use. | `beril-presentation-maker draft <project_id> [--mode ...]` (Python wrapper that delegates to `tools/presentation_maker.sh`). | `src/beril_presentation_maker/commands/draft.py`; installed alongside `install-skill`, `configure`, `continue`, `assemble`. |

Both surfaces dispatch to the same `tools/presentation_maker.sh`
under the hood — single source of truth. Same exit codes, same
output paths, same `slide_spec.json` schema. The slash command adds
Claude-Code agent procedural steps (resolve project, pick draft,
surface output); the CLI subcommand is a thin wrapper that
propagates exit codes for downstream scripts to act on.

**For end users in Claude Code:** use the slash command.
**For skill-to-skill integration or scripted workflows:** use the
CLI subcommand. See `CONTRACT.md` (post-v0.4) for the full
programmatic interop surface.

### Surface syntax — DO NOT conflate the two

The two surfaces have **functionally equivalent behavior** but
**slightly different syntax**. When the user types a command,
identify which surface they used and respond using that surface's
exact shape; do not describe one surface as if it were the other.

| | Slash command | Python CLI subcommand |
|---|---|---|
| Invocation prefix | `/beril-presentation-maker` | `beril-presentation-maker` |
| Subcommand keyword | NONE — project_id follows directly | **`draft`** required (other subcommands: `install-skill`, `configure`, `continue`, `assemble`) |
| Full shape | `/beril-presentation-maker <project_id> --mode talk-30` | `beril-presentation-maker draft <project_id> --mode talk-30` |
| Where it runs | Claude Code agent inside a BERIL deployment | Shell (any environment with the pipx install) |
| Behind-the-scenes | Agent runs `tools/presentation_maker.sh` directly | Python wrapper invokes the same shell script |

A second slash command exists for resuming paused or partially-failed
drafts:

| Surface | Slash | CLI |
|---|---|---|
| Continue from a named stage | `/beril-presentation-maker-continue <draft_dir> --resume-from <stage>` | `beril-presentation-maker continue <draft_dir> --resume-from <stage>` |

## Mode selection — one matrix, six modes

The `--mode` flag picks the presentation format. Each mode has a
different slide budget, figure budget, and assembly path. **This
table is the single source of truth for per-mode behavior;** the
slash command, the CLI subcommand, and the orchestrator all
reference it rather than re-stating per-mode details.

| Mode | Use case | Wall clock | Cost (Sonnet) | Slide budget | Renderer |
|---|---|---|---|---|---|
| **`talk-30`** (default) | Standard 30-min talk | ~15-25 min | ~$1.50-3.00 | 18-24 | `assemble_pptx.py` |
| **`talk-15`** | Short talk / lab meeting | ~10-15 min | ~$1.00-2.00 | 10-14 | `assemble_pptx.py` |
| **`talk-45`** | Full seminar | ~20-30 min | ~$2.00-4.00 | 28-36 | `assemble_pptx.py` |
| **`lightning-5`** | 5-min lightning talk | ~5-8 min | ~$0.50-1.00 | 4-6 | `assemble_pptx.py` (skips intro stage) |
| **`poster-h`** | Horizontal scientific poster | ~10-15 min | ~$1.00-2.00 | (poster zones) | `poster_fill.py` |
| **`poster-v`** | Vertical scientific poster | ~10-15 min | ~$1.00-2.00 | (poster zones) | `poster_fill.py` |

The `--tier` flag is orthogonal to mode and shapes language
register: `STRONG` (declarative; default), `THIN` (scoped/hedged),
`EXPLORATORY` (preliminary; requires opt-in for AI images via
`--image-allow-exploratory`).

## Workflow (run a draft)

When the user invokes `/beril-presentation-maker`:

### Step 1 — Resolve project context

This is the agent's most load-bearing inference step. On the BERIL
hub, users may invoke the slash command from many starting points
(just opened Claude Code, in the middle of a research workflow,
after `/berdl_start`, etc.) and they often stay at BERIL_ROOT in
cwd rather than `cd`-ing into a specific project. Walk this
resolution tree IN ORDER and stop at the first match:

**1a. Explicit argument.** If the user typed a project_id after
the slash command (e.g., `/beril-presentation-maker my_project_id
--mode talk-30`), use it as-is. Validate `projects/<id>/` exists;
ask the user to clarify if it doesn't.

**1b. Git branch convention.** Run `git -C $BERIL_ROOT branch
--show-current`. The hub uses a `projects/<id>` branch-naming
convention — branch `projects/gene_function_ecological_agora` means
the active research project is `gene_function_ecological_agora`.
Strip the `projects/` prefix; that's the project_id. **Confirm
with the user before acting:** "I see you're on branch
`projects/<id>`. Draft a presentation for that project? [Y/n]".
This is the strongest signal on the hub because users typically
stay at BERIL_ROOT.

**1c. cwd.** Run `pwd`. If the path is inside `projects/<id>/`,
that `<id>` is the project_id. Common when the user `cd`'d into a
project manually.

**1d. Ask the user.** If 1a–1c didn't resolve, present the project
list and ask:

```bash
ls $BERIL_ROOT/projects/        # all available project_ids
```

For projects that have a `beril.yaml` manifest, surface the
project's status alongside the id. If the user just ran
`/berdl_start`, reference the project list it already displayed
rather than re-listing.

After resolving project_id, validate `projects/<project_id>/`
exists before proceeding. Confirm the project has the inputs
presentation-maker requires:

- `REPORT.md` (canonical findings)
- `RESEARCH_PLAN.md` (design intent)
- `figures/` (or `figs/`, `plots/`, `output/figures/`,
  `results/figures/`) — at least one .png
- `notebooks/` with at least one `*.ipynb`

If any are missing, halt and tell the user. The orchestrator will
also halt at curation/citation stages with worse diagnostics, so
catching it at Step 1 saves time.

### Step 2 — Resolve draft (continue mode only)

For a fresh draft, the orchestrator allocates the next available
`talks/draft_N/` and writes there. Skip to Step 3.

For `/beril-presentation-maker-continue`:

- If the user passed an absolute or relative path to a specific
  `talks/draft_N/` directory in Step 1a, use that.
- Else: list talk drafts under the resolved project and pick a
  default:

  ```bash
  ls $BERIL_ROOT/projects/<project_id>/talks/
  ```

  Pick the highest-numbered `draft_N` as the proposed default.
  Confirm with the user before invoking: "Found drafts `draft_1`
  through `draft_3`. Resume from `draft_3`, or pick another?
  [Y/n/N=specific number]".

The orchestrator's `<draft_dir>` argument needs the absolute path:
`$BERIL_ROOT/projects/<project_id>/talks/draft_<N>/`.

### Step 3 — Invoke the orchestrator

Run the shipped CLI:

```bash
beril-presentation-maker draft <project_id> [options]
# OR for resume:
beril-presentation-maker continue <draft_dir> --resume-from <stage> [options]
```

The CLI:

- Auto-detects BERIL_ROOT, validates the project layout, allocates
  the next `talks/draft_N/` (fresh runs).
- Loads CBORG_API_KEY from BERIL_ROOT/.env (for image_gen stage)
  if not already in env.
- Initializes the 4-zone layout (`deliverable/`, `narrative/`,
  `working/`, `audit/`).
- Runs the 14-stage pipeline (see [Pipeline](#pipeline) below).
  Each stage's stderr streams live; per-stage cost + token usage
  printed inline via `stream_progress.py`.
- Auto-retries on silent LLM failures (Write not invoked) up to 3
  attempts.
- Writes the deck to `deliverable/draft.pptx`.
- Optionally invokes adversarial review + revise loop (unless
  `--no-adversarial`).

Run from `BERIL_ROOT` (the directory containing `projects/` and
`.claude/`). The script auto-resolves BERIL_ROOT from its install
path if needed; pass `--beril-root <path>` to override.

### Step 4 — Verify completion

After the orchestrator returns:

1. Check `<draft_dir>/deliverable/draft.pptx` exists and is
   non-empty.
2. If adversarial review ran: check
   `<draft_dir>/audit/adversarial_review.json` is valid v3 schema.
3. Check `<draft_dir>/audit/quantitative_grounding.md` for any
   ungrounded numbers (advisory; doesn't block ship).
4. Print a brief summary: total cost, slide count, image count
   (if image_gen ran), revise-loop outcomes if any.

### Step 5 — Guidance

Based on the run outcome:

- **Clean run (no adversarial findings, no quantitative-grounding
  warnings):** point user at `deliverable/draft.pptx`. Suggest
  manual polish in PowerPoint (the polishing-workflow rules below
  apply).
- **Adversarial findings revised in-loop:** surface the count of
  P0 findings revised + any rejected (in `next_actions.md`).
  Suggest a re-render via `--resume-from assemble` if the user
  wants to re-eyeball.
- **citation_reality findings (v3 only):** these are surfaced
  rather than auto-revised. Direct the user to
  `working/next_actions.md` for the list of citations needing
  human verification — provide the citation_id + slide for each.
- **Quantitative-grounding warnings:** surface ungrounded numbers
  to the user with slide-id locations. Recommend manual fix or
  re-running upstream stages with corrected REPORT.md.

## Pipeline

The orchestrator runs 14 stages. Each stage's output is on disk;
intermediate state under `working/`, audit history under `audit/`.

```
Stage 1.  plan.v1                  triage tier + scope        ~$0.20
Stage 2.  throughline.v1           2-3 candidates → pick      ~$0.25
Stage 3.  substory_design.v1       partition into substories  ~$0.20
Stage 4.  curate_figures           inventory + shortlist      ~$0  (Python)
Stage 5.  citation_pool.v1         verify-by-resolution pool  ~$0.30
Stage 6.  cross_tenant.v1          K-BERDL signal (optional)  ~$0  - $0.10
Stage 7.  intro.v1                 opening framing slides     ~$0.15
Stage 8.  slide_compose.v1         per-substory composition   ~$0.30-0.50
Stage 9.  qa_prep.v1               anticipated Q&A slides     ~$0.20
Stage 10. speaker_notes.v1         per-slide speaker notes    ~$0.20-0.40
Stage 11. image_gen                concept_illustration → AI  ~$0  - $0.50
Stage 12. merge_and_assemble       slide_spec + .pptx render  ~$0  (Python)
Stage 13. adversarial_review       v0.7.0.1 v3 review         ~$0.50 (skip with --no-adversarial)
Stage 14. revise_slides            review-rewrite loop        ~$0.30 - $5 (capped)
```

Total on `talk-30 STRONG`: ~$2-4 typical, $5-7 if revise loop fires
heavily.

## Output artifacts

v0.3.1 introduced a 4-zone layout. Top level of every draft directory
has exactly four entries.

```
projects/<project_id>/talks/draft_N/
├── deliverable/                     ← what you open / present
│   ├── draft.pptx                   ← assembled deck
│   ├── draft.pdf                    ← (optional)
│   └── speaker-notes.pdf            ← (optional)
├── narrative/                       ← human-readable story artifacts
│   ├── 00_throughline.md            ← chosen throughline + evidence map
│   ├── 02_substories.md             ← substory partition with punchlines
│   ├── references.md                ← human-readable citations
│   ├── bibliography.bib             ← machine-readable (BibTeX)
│   └── citation_map.md              ← claim → reference index
├── working/                         ← intermediate pipeline state
│   ├── 00_plan.md                   ← triage + scope from plan.v1
│   ├── 00_throughline_candidates.md ← rejected alternatives
│   ├── 03_slides/                   ← per-substory compose fragments
│   ├── 04_speaker_notes/            ← per-substory speaker notes
│   ├── 05_image_decisions.json      ← v0.3.3 per-slide image-gen decisions
│   ├── 05_image_requests/           ← v0.3.3 image-gen request JSONs
│   ├── 05_images/                   ← v0.3.3 generated PNGs (draft-local)
│   │   └── manifest.json            ← image-manifest.v1 (slide_id → image_path)
│   ├── citation_pool.json           ← verified literature pool
│   ├── cross_tenant_signal.{json,md}
│   ├── curated_figures.md           ← mode-bounded figure shortlist
│   ├── figures_inventory.md
│   ├── diagram_repair_report.md
│   ├── next_actions.md              ← P1/P2 findings + citation_reality items
│   └── slide_spec.json              ← LIVE merged + validated slide spec
└── audit/                           ← provenance + debug history
    ├── state.json                   ← orchestrator state
    ├── cost-log.jsonl               ← per-stage LLM cost
    ├── stage-metadata.json          ← consolidated per-stage metadata
    ├── stage-logs/                  ← per-stage stdout/stderr
    ├── snapshots/                   ← immutable spec snapshots
    │   ├── slide_spec.raw.json      ← pre-repair merge
    │   ├── slide_spec.pre_revise.json
    │   ├── 03_slides_pre_image_gen/ ← v0.3.3 pre-mutation fragment snapshots
    │   ├── last-render.pptx         ← deck baseline for manual-edit detection
    │   └── ...
    ├── manual-edits/                ← preserved user edits to draft.pptx
    ├── runs/                        ← per-orchestrator-invocation summaries
    │   └── run-N/
    ├── adversarial_review.{json,md} ← v3 schema (v0.3.3.1+)
    ├── adversarial_review.original-summary.json ← v0.4.1 sidecar
    ├── quantitative_grounding.{json,md}
    ├── image_provenance.json        ← v0.3.3 image_client append-log
    └── revise_loop_metadata.json
```

**Reading the layout:**
- Open `deliverable/draft.pptx` to see the talk.
- Read `narrative/` to review the story (throughline + substories +
  references). User-editable; pipeline absorbs edits via
  `--resume-from <stage>`.
- Look in `working/` only when debugging or hand-tweaking the spec.
- Check `audit/` for per-run history, snapshots, and provenance.

## Manual edits to the deck

The pipeline owns `deliverable/draft.pptx` — it gets regenerated from
`working/slide_spec.json` on every assemble. If you open the deck in
PowerPoint and edit it directly, the next pipeline run **regenerates
the deck and your manual edits are preserved (but not absorbed)** in
`audit/manual-edits/<UTC-timestamp>.pptx`.

The orchestrator detects manual edits via sha256 of the deck before
assemble. If the hash differs from `audit/last-render.json`, your
edited copy is archived to `audit/manual-edits/` before regeneration.
You'll see a prominent stderr warning when this happens.

**Recommended polishing workflow:**

1. Run the pipeline to convergence (or until adversarial review passes).
2. Copy `deliverable/draft.pptx` to a location of your choice (e.g.,
   `~/Desktop/talk-2026-05-15.pptx`).
3. Polish that copy in PowerPoint. The pipeline-owned
   `deliverable/draft.pptx` is now considered "stale"; re-running
   the pipeline will regenerate it from `slide_spec.json`, but your
   polished copy is safe.

**To make edits stick across re-runs:**

- For content changes (revised substory, new claim): edit
  `narrative/02_substories.md`, then run
  `beril-presentation-maker continue <draft_dir> --resume-from slide_compose`.
  The pipeline reads from `narrative/`, regenerates `working/03_slides/`,
  re-merges `slide_spec.json`, re-renders the deck.
- For surgical fixes (tweak a slide's title or bullet): edit
  `working/slide_spec.json` directly (it's JSON), then run
  `beril-presentation-maker assemble <draft_dir>`. The validator
  catches schema violations; clean edits round-trip cleanly.
- For re-rolling an AI image: delete the corresponding entry in
  `working/05_images/manifest.json` (or the entire manifest), then
  run `beril-presentation-maker continue <draft_dir> --resume-from image_gen`.
  Cached request.json is reused unless `--image-style` differs;
  the LLM authoring is skipped (~$0.14 saved per slide).
- For full restart: delete the draft directory and re-run from
  scratch.

**What the pipeline cannot absorb:**

Manual PowerPoint edits to `deliverable/draft.pptx` (text reorder,
shape moves, image swaps, slide insertion) are **not** parsed back
into `slide_spec.json`. A future round-trip command (v0.4+) may
support a subset of these, but for now: edit upstream
(narrative/working) or accept that polish lives in YOUR copy of the
deck, not the pipeline's.

## Cost-control flags

| Flag | Default | Effect |
|---|---|---|
| `--no-adversarial` | (off) | Skip stages 13-14. Saves $1-5 on a typical run. |
| `--max-revise-cost-usd <n>` | `5.00` | Cumulative cap on revise-loop LLM spend. |
| `--max-revisions <n>` | `6` | Max P0 findings the revise loop processes. |
| `--no-images` | (off) | Skip stage 11 entirely. Saves $0-0.50. |
| `--auto-approve-images` | (off) | Bypass per-slide approval gate. CI / power-user; cost cap still enforced. |
| `--max-image-cost-usd <n>` | `0.50` | Cumulative image-gen cap. ~30 images at calibrated $0.014/each. |
| `--image-allow-exploratory` | (off) | Allow concept_illustration on EXPLORATORY tier. |
| `--image-style <style>` | (none) | Force style override across all images this run. |
| `--no-stream` | (off) | Disable cost-summary streaming. Useful only for debugging the parser. |

## When to use this skill vs. alternatives

| Scenario | Use |
|---|---|
| BERDL project → talk or poster | `/beril-presentation-maker` |
| BERDL project → manuscript | `/beril-paper-writer` (sibling skill) |
| Existing slide deck → adversarial review | `/beril-adversarial --type presentation` |
| Cold-scan BERIL deployment | `/beril-atlas` (sibling skill) |

## Notes

- The system prompts (`prompts/*.v1.md`) are the locus of composition
  intelligence. They iterate via `.v{N}.md` versioning.
- The KBase-branded master template lives at
  `references/templates/kbase-presentation-master.pptx`. The 16-layout
  vocabulary is defined by this master + `slide_spec.py` enums.
- Figure paths in `slide_spec.json` come verbatim from
  `curated_figures.md` (typically `figures/<name>.png`, relative to
  `project_dir`). The validator hard-rejects the deprecated
  `figures/curated/` path convention (changelog 2026-04-27).
- Image generation uses CBORG (Lawrence Berkeley API gateway) for
  Gemini-3-pro-image. Calibrated at $0.014/image (13 trials,
  v0.3.0). The orchestrator auto-loads `CBORG_API_KEY` from
  `BERIL_ROOT/.env` if not in shell env; never echoes the value.
- Adversarial review consumes the v3 schema
  (`adversarial-review-presentation.v3`). v2 audit files are still
  readable for forensic compatibility but new reviews emit v3.
- This skill never modifies project source files (no edits to
  `REPORT.md`, `RESEARCH_PLAN.md`, notebooks). All output is scoped
  to `talks/draft_N/`.
- For provider/model configuration: the `claude` CLI carries its own
  config. This skill does not edit `.env` directly (only reads
  CBORG_API_KEY).

## Pitfall detection

When you encounter errors, unexpected results, or surprising drafting
outcomes during invocation of this skill, the recovery path is:

1. Check `audit/stage-logs/<stage>.stderr` for the failed stage's
   live output. Most pipeline errors include enough context here to
   diagnose without re-running.
2. Check `audit/runs/run-N/summary.json` for the run-level totals
   (cost, stages_run, exit_code) to confirm whether the issue was
   pre-LLM (cheap to recover from) or mid-pipeline (re-run from a
   later `--resume-from` to save cost).
3. Cross-reference `HUB_INSTALL.md` "Troubleshooting" for the 8
   recipe-shaped recoveries covering common failures (CBORG_API_KEY
   missing, image-gen worst-case rejection, adversarial CLI version
   mismatch, v0.3.0-shape draft incompatibility, etc.).

If you encounter a pitfall that isn't covered there, surface it to
the user with the audit log paths and recommend they file an issue
on the GitHub repo. The maintainer will fold it into HUB_INSTALL.md
on the next docs release.

If a sibling `pitfall-capture` skill is installed at
`.claude/skills/pitfall-capture/SKILL.md`, follow its protocol
instead — it supersedes this section when present.
