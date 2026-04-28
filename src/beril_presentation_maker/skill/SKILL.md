---
name: beril-presentation-maker
description: |
  Draft evidence-grounded scientific presentations (talks + posters) from
  BERDL analysis projects, in KBase brand. Pipeline: plan → throughline →
  substory_design → curate_figures → citation_pool → cross_tenant → intro →
  slide_compose → qa_prep → speaker_notes → merge_and_assemble. Reuses
  project figures verbatim; generates illustrative diagrams procedurally.
  Produces speaker notes, anticipated Q&A, citation pool, and an audit trail
  of every claim. Use when a BERDL project (REPORT.md + notebooks +
  RESEARCH_PLAN) needs a talk or poster derived from the project's evidence.
allowed-tools: Bash, Read, Write, AskUserQuestion
user-invocable: true
---

# BERIL Presentation Maker

Drafts a scientific presentation from a BERDL analysis project. Reads
the project's `REPORT.md`, `RESEARCH_PLAN.md`, notebooks, and figures;
produces a complete .pptx (or poster .pptx) plus speaker notes, Q&A
prep, and a citation pool with verified DOI/PMID provenance.

The skill ships as a pip-installable Python package
(`beril-presentation-maker-skill`) plus a Claude Code skill installed at
`<BERIL>/.claude/skills/beril-presentation-maker/`. The Python layer
handles install + configuration. The drafting itself runs through a
shell orchestrator (`tools/presentation_maker.sh`) that invokes
per-stage prompts as `claude -p` subagents and writes a validated
`slide_spec.json` that `assemble_pptx.py` renders to .pptx.

**Status: v0.2.0 — first install-shippable release.** Full 11-stage
drafting pipeline + KBase-branded master + slide_spec validator
(15 layouts) + assemble_pptx + poster_fill. Adversarial
review-rewrite loop and `ai_image_prompt` staging are deferred to
v0.3.

## Slash commands

### `/beril-presentation-maker` — start a new draft

```
/beril-presentation-maker [<project_id>]
                          [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v]
                          [--tier STRONG|THIN|EXPLORATORY]
                          [--auto-advance] [--skip-assembly]
                          [--model <model_id>] [--no-stream]
```

**Arguments:**

- `<project_id>` — project directory under `projects/`. Optional if cwd is
  inside `projects/<id>/`.
- `--mode` — presentation format. Default `talk-30`. talk-15 / talk-45 /
  lightning-5 vary slide-budget + figure-budget. poster-h / poster-v
  dispatch to the poster_fill renderer.
- `--tier` — evidence tier. Default `STRONG`. Affects language register
  (declarative vs. hedged) and citation-floor discipline.
- `--auto-advance` — skip interactive gates: pick TL1 throughline,
  escalate-mode on overflow. Use for unattended runs against
  known-shape projects.
- `--skip-assembly` — stop after fragment merge; do not invoke
  `assemble_pptx.py`. Useful for spec-only iteration.
- `--model <model_id>` — override default model (Sonnet).
- `--no-stream` — disable `stream_progress.py` wrapper. Loses cost
  summary + Write verification.

### `/beril-presentation-maker-continue` — re-run from a named stage

```
/beril-presentation-maker-continue <draft_dir> --resume-from <stage>
                                   [--auto-advance] [--no-stream]
                                   [--model <model_id>]
```

**Arguments:**

- `<draft_dir>` — path to the existing draft directory (e.g.,
  `projects/<id>/talks/draft_3/`).
- `--resume-from <stage>` — required. One of: plan, throughline,
  substory_design, curate_figures, citation_pool, cross_tenant, intro,
  slide_compose, qa_prep, speaker_notes, merge.
- Earlier-stage artifacts on disk are reused; later stages re-run.

Cost savings on prompt-iteration:
- from `intro`: ~$1.50 (saves plan + throughline + substory)
- from `slide_compose`: ~$1.20 (saves through intro)
- from `merge`: free (no LLM; assembly only)

## Workflow

The orchestrator runs the 11-stage pipeline in one shot:

1. **plan.v1** — triage tier + scope; emit `00_plan.md`. ~$0.20.
2. **throughline.v1** — produce 2-3 throughline candidates. With
   `--auto-advance`, picks TL1; otherwise pauses inside the
   orchestrator for user pick via AskUserQuestion.
3. **substory_design.v1** — partition the throughline into
   2-4 substories with punchlines. Includes word-cap audit.
4. **curate_figures** (Python) — inventory + mode-bounded shortlist
   of figures from `<project>/figures/` and notebooks. Writes
   `figures_inventory.md` and `figures_curated.md`.
5. **citation_pool.v1** — literature scan with 9-field DOI/PMID
   verification. Pool reuse across projects keyed on canonical refs.
6. **cross_tenant.v1** (optional) — extracts cross-tenant signal from
   K-BERDL when the project spans multiple tenants.
7. **intro.v1** — opening slides + framing fragment.
8. **slide_compose.v1** — per-substory slide composition. Picks
   layout from the 15-layout vocabulary; emits validated fragments.
9. **qa_prep.v1** — anticipated Q&A slides for the back of the deck.
10. **speaker_notes.v1** — per-slide speaker notes.
11. **merge_and_assemble** — merges fragments into `slide_spec.json`,
    runs the validator (P1-P10), invokes `assemble_pptx.py` →
    `draft.pptx`.

Wall clock: ~10-25 min on Sonnet for STRONG-tier `talk-30`. Cost
~$1.50-3.00 depending on `--mode` and project tier.

## Output artifacts

```
projects/<project_id>/talks/draft_N/
├── 00_plan.md                       ← triage + scope from plan.v1
├── 00_throughline.md                ← chosen throughline + evidence map
├── 00_throughline_candidates.md     ← rejected alternatives (audit)
├── 02_substories.md                 ← substory partition with punchlines
├── 03_slides/                       ← per-substory + intro/qa/cross_tenant fragments
│   ├── intro.json
│   ├── S1_slides.json
│   ├── ...
│   ├── qa_anticipated.json
│   └── cross_tenant.json (optional)
├── 04_speaker_notes/                ← per-substory speaker notes
├── slide_spec.json                  ← merged + validated slide spec
├── slide_spec.raw.json              ← pre-repair fragment merge
├── citation_pool.json               ← verified literature pool
├── citation_map.md                  ← claim → reference index
├── references.md                    ← human-readable
├── bibliography.bib                 ← machine-readable (BibTeX)
├── figures_inventory.md             ← from curate_figures.py
├── curated_figures.md               ← mode-bounded shortlist
├── cross_tenant_signal.md           ← optional, when applicable
├── diagram_repair_report.md         ← post-compose diagram coercion log
├── draft.pptx                       ← assembled deck
└── audit/                           ← per-stage LLM call metadata
```

## When to use this skill vs. alternatives

| Scenario | Use |
|---|---|
| BERDL project → talk or poster | `/beril-presentation-maker` |
| BERDL project → manuscript | `/beril-paper-writer` (sibling skill) |
| Existing slide deck → review | `/beril-adversarial --type presentation` (planned v0.3) |
| Cold-scan BERIL deployment | `/beril-atlas` (sibling skill) |

## Notes

- The system prompts (`prompts/*.v1.md`) are the locus of composition
  intelligence. They iterate via `.v{N}.md` versioning.
- The KBase-branded master template lives at
  `references/templates/kbase-presentation-master.pptx`. The 15-layout
  vocabulary is defined by this master + `slide_spec.py` enums.
- Figure paths in `slide_spec.json` come verbatim from
  `curated_figures.md` (typically `figures/<name>.png`, relative to
  `project_dir`). The validator hard-rejects the deprecated
  `figures/curated/` path convention (changelog 2026-04-27).
- This skill never modifies project source files (no edits to
  `REPORT.md`, `RESEARCH_PLAN.md`, notebooks). All output is scoped
  to `talks/draft_N/`.
- For provider/model configuration: the `claude` CLI carries its own
  config. This skill does not edit `.env` or hold API keys.

## Pitfall detection

When you encounter errors, unexpected results, or surprising drafting
outcomes during invocation of this skill, follow the pitfall-capture
protocol. Read `.claude/skills/pitfall-capture/SKILL.md` and follow
its instructions to determine whether the issue belongs in
`docs/pitfalls.md`.
