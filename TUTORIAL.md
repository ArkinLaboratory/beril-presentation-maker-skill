# BERIL Presentation Maker — Tutorial

A skill-specific guide for reading, iterating on, and hand-editing presentation drafts produced by `beril-presentation-maker`. Assumes you've already installed the four BERIL plug-in skills and have a project in BERIL ready to draft from.

> **For install + configure + first-time setup**, start with the cross-skill **[PARTICIPANT-RUNBOOK.md](https://github.com/ArkinLaboratory/beril-presentation-maker-skill/blob/main/docs/cross-skill/PARTICIPANT-RUNBOOK.md)** (covers all 4 plug-in skills end-to-end). This tutorial is the presentation-maker-specific layer that sits on top.

> **For operator hub deployment**, see [HUB_INSTALL.md](HUB_INSTALL.md). For consumer integration with the adversarial reviewer, see [CONTRACT.md](CONTRACT.md).

**Audience:** Researchers using `/beril-presentation-maker` in Claude Code on the BERIL hub who have already run a draft and want to make the most of it (read the output, iterate cheaply, hand-edit the `.pptx`, troubleshoot).

**Time:** 5 minutes to read; 45-60 minutes for a typical draft run; 5-15 minutes per revise-loop iteration.

**Cost:** $5-20 per draft (talk-30, STRONG, with image-gen + adversarial); $2-5 without image-gen and adversarial. Per-image cost ~$0.014 (CBORG-Gemini). Per-revise-loop iteration $0.50-2.

---

## The output tree at a glance

After `beril-presentation-maker draft <project_id>` finishes, your project has a new `talks/draft_N/` directory with a four-zone layout:

```
talks/draft_N/
├── deliverable/           # what you actually share with humans
│   ├── draft.pptx         #   ← the slide deck (open in PowerPoint / Keynote / LibreOffice)
│   └── speaker-notes.md   #   ← speaker notes as readable markdown
├── narrative/             # the *decisions* the writer made, before slides
│   ├── REPORT-skim.md     #   ← which parts of REPORT.md the writer read
│   ├── throughline.md     #   ← the chosen scientific throughline (1 of N candidates)
│   └── substory-design.md #   ← partition into substories (acts of the talk)
├── working/               # machine-readable internals (you'll mostly skip)
│   ├── slide_spec.json    #   ← THE structured slide spec — useful for hand-edits
│   ├── citation_pool.md   #   ← references the writer found
│   └── stage_metadata.json#   ← per-stage cost + timing
└── audit/                 # everything the writer did and why
    ├── stages/            #   ← per-stage logs (one dir per of 14 stages)
    ├── runs/              #   ← per-run summaries, cost, adversarial review output
    └── manual-edits/      #   ← (only created after you hand-edit the .pptx)
```

Two files are worth opening; the rest is for debugging.

The `deliverable/draft.pptx` is the obvious one. The non-obvious one is **`working/slide_spec.json`** — read on.

## Reading `slide_spec.json`

The slide_spec is the single source of truth for what's on each slide *before* it gets rendered into PowerPoint XML. Useful when:

- A slide is structurally wrong and you want to understand what the writer was trying to do.
- You want to revise one slide cheaply (`/beril-presentation-maker-continue` reads slide_spec, edits one slide, re-assembles).
- You want to hand-edit slide_spec.json directly and re-run `assemble` (advanced; see "Iteration" below).

Top-level shape:

```json
{
  "schema_version": "1.0",
  "project_id": "my_phylo_study",
  "mode": "talk-30",
  "tier": "STRONG",
  "throughline": { "id": "TL2", "punchline": "...", "tier_evidence": "STRONG" },
  "substories": [ { "id": "S1", "punchline": "...", "slide_ids": [3,4,5] }, ... ],
  "slides": [ ... ]
}
```

Each slide has a `layout` (one of 16 — see below), an `id`, an optional `substory_id` mapping it to a substory, and a layout-specific `content` block. The `validator_status` field on each slide records whether the post-checkers (quantitative grounding, figure manifest, etc.) flagged anything during the pipeline.

The slide_spec validator (`tools/slide_spec.py`) is hand-rolled and authoritative. If you edit slide_spec.json by hand, run `python3 src/beril_presentation_maker/skill/tools/slide_spec.py validate <path>` first — broken specs fail loud at assemble time and you'll waste a $5-20 re-run.

## The 16 layouts

The presentation maker speaks a vocabulary of 16 slide layouts. Each layout has its own content schema, its own master-template geometry, and its own author rules (in `prompts/slide_compose.v1.md`).

| Layout | When the writer chooses it | Key content fields |
|---|---|---|
| `title` | Slide 1 (always) | title, presenter, date, optional subtitle/affiliation/venue |
| `section_divider` | Substory transitions | punchline, optional substory_number |
| `big_idea` | Opening claim or key transition; pull-quote feel | title; optional supporting_graphic for banner+image mode |
| `big_number` | Headline statistic (27M genomes, 90% accuracy) | headline, subtitle, optional sub_pointer / source_footer |
| `claim_evidence` | The workhorse data slide | title, 1-3 bullets, optional figure + figure_caption + citations |
| `two_column_compare` | Before/after, control/treatment | left_col_{title,content}, right_col_{title,content} |
| `data_figure` | One figure dominates the slide | title, figure path, caption (≤280 chars), optional data_source |
| `data_table` | Ranked top-N or comparison matrix | title, columns (2-6), rows (1-12), optional caption/footnote/highlight_rows |
| `workflow_diagram` | Methods walkthrough as boxes-and-arrows | title, diagram (nodes + edges), 3 step_captions |
| `methods_summary` | Parameters/tools list | title, 5-10 bullets, optional tools_versions |
| `concept_illustration` | AI-generated illustration as a slide | title, image_path, image_prompt, style, provenance |
| `cross_tenant_integration` | Pulling data from multiple BERDL tenants | title, optional tenant_list / kberdl_db_list / data_flow_diagram |
| `implications` | "What changes if this is true" | title, 1-3 bullets ({claim, evidence_pointer}) |
| `acknowledgments` | Last-but-one slide | contributors list, optional funder_logos / tenant_attribution |
| `references` | Final slide | refs_short (≤8 entries), optional ai_disclosure |
| `qa_anticipated` | Anticipated Q&A | question, answer_summary, evidence_pointer, optional answer_detail |

Layout selection happens in `slide_compose.v1.md` based on the substory plan + figure inventory + tier. The writer rarely makes blatant mis-fits but does have known biases — see "Troubleshooting" below.

## Image-gen approval flow

`concept_illustration` slides use AI-generated illustrations (CBORG-Gemini, ~$0.014/image). The pipeline's `image_gen` stage:

1. **Decides** which slides need illustrations (deterministic Python; per-slide).
2. **Authors** an image prompt for each (LLM call against `ai_image_prompt.v1.md`).
3. **Approves** each image with you, one at a time — by default, interactively.
4. **Generates** approved images and binds them into the slide_spec via the merge stage.

The per-image approval prompt shows you the slide context, the prompt the writer wrote, the estimated cost, and your options:

```
Slide 7: concept_illustration — "Genome ring opener for Substory 1"
Prompt: "scientific illustration in KBase brand palette, ..."
Style: scientific_illustration | Channel: A | Cost estimate: $0.014
[A]pprove and generate / [R]e-roll prompt / [E]dit prompt / [S]kip slide / [D]efer slide
```

For non-interactive runs (auto-advance + auto-approve), pass `--auto-approve-images --max-image-cost-usd 0.20`. The cap is per-image; pipeline halts gracefully if any single image exceeds the cap. Without `--auto-approve-images`, you'll be prompted; with it but without `--max-image-cost-usd`, the pipeline assumes infinite budget. Use both for hands-off runs; use neither for full control.

If a generated image looks wrong post-hoc, run `/beril-presentation-maker-continue` against the draft and use the revise loop to re-roll specific slides — much cheaper than re-running the whole pipeline.

## Iteration: revise vs re-run

After a draft completes, you have three iteration paths in increasing cost order:

| Path | Cost | When |
|---|---|---|
| Hand-edit `.pptx` in PowerPoint | $0 | Cosmetic / formatting / typo fixes. Manual edits preserved under `audit/manual-edits/` on subsequent revise passes (see below). |
| Revise specific slides (`/beril-presentation-maker-continue` with adversarial review) | $0.50-2 per pass | Slide content is structurally wrong (weak punchline, missing claim, fabricated quantitative). The revise loop runs adversarial review, picks the worst N findings, re-authors only the affected slides. |
| Full re-run from scratch (`beril-presentation-maker draft`) | $5-20 | Throughline was wrong (most expensive failure mode). Substory partition is fundamentally off. Tier was mis-detected. Use sparingly; the throughline-pick stage halts for you to confirm before any deep cost is paid. |

The revise loop is the right tool for most "this slide is bad" cases. The full re-run is the right tool only when the *story* is wrong, not when individual slides are.

## Hand-editing `draft.pptx`

The `.pptx` is yours. Open it, edit freely. Preserve and ship semantics:

- **Manual edits are detected via hash-guard.** On the next `/beril-presentation-maker-continue` or revise pass, the assembler diffs the on-disk `.pptx` against what it would render from `slide_spec.json`. Diverging slides are preserved — copied to `audit/manual-edits/draft_N/` and the revise loop skips them. You won't lose work.
- **The slide_spec.json does NOT update from your edits.** If you want the structured spec to reflect your hand-edit (e.g., you fixed a punchline by hand and want the next draft to inherit it), you'll need to update slide_spec.json manually. The hand-edit detection is one-way — `.pptx` wins, but only for that draft.
- **Best practice for the May 7 event:** finish the pipeline first, then hand-edit only the deliverable `.pptx`. Don't try to edit slide_spec.json + re-assemble unless you know what you're doing — it's a faster cycle but easier to break.

## Known cosmetic issues — hand-fix list

The following layout issues are tracked for post-event releases. If your draft hits any of them, hand-fix in PowerPoint:

- **Title slide** — long throughline punchlines (>200 chars) may render visually cramped. Adjust font size or shorten in the title slide directly.
- **References slide** — `refs_short` is currently capped at 8; longer bibliographies are truncated upstream. To show more references, copy from `working/citation_pool.md` and split into a second references slide manually.
- **`qa_anticipated` slide** — long synthesis-style questions may overflow the question region. Shorten the question or split across two slides.
- **`cross_tenant_integration` slide** — currently renders as a flat list when no `data_flow_diagram` is provided. If that's how yours looks, consider adding a hand-drawn diagram in PowerPoint to convey the integration pattern.

These are tracked in the workspace task list as #74-77 and slated for v0.4. Until then, hand-edits are the workaround.

## Presentation-maker-specific troubleshooting

For cross-skill troubleshooting (pipx install, configure, BERIL_ROOT detection, schema mismatch errors), see PARTICIPANT-RUNBOOK §Appendix A. The items below are presentation-maker-specific.

**Pipeline halts at "Pick a throughline (TL1 / TL2 / TL3):" with exit code 1 in a Claude Code background task.** The throughline-pick gate uses `read -r pick </dev/tty` to prompt interactively, which fails in TTY-less contexts (Claude Code's Bash background tool, CI, headless daemons). For TTY-less use, **always pass `--auto-advance`** — the pipeline will auto-pick TL1 (the first throughline candidate, ordered by the writer's confidence) and run end-to-end without prompting. If you specifically want a non-TL1 candidate, run interactively in a real terminal, or run with `--auto-advance` first and then iterate via the revise loop. State-driven gate-resume with explicit `--pick TLN` is planned for v0.4.0 (paper-writer pattern); until then, `--auto-advance` is the right tool for hub agents and CI.

**Image-gen approval prompts you don't want.** You're running interactively but each slide's image-gen approval is breaking your flow. Pass `--auto-approve-images --max-image-cost-usd 0.20` to make image-gen non-interactive while still capping cost.

**Image-gen budget exceeded mid-pipeline.** The pipeline halts gracefully at the next image-gen call after the cap. Resume options: (a) raise the cap and `continue`, (b) skip remaining concept_illustration slides (they fall back to image-free `big_idea` layouts), (c) accept the partial draft (the deliverable from a partial pipeline is usable).

**`concept_illustration` selection seems too eager / too sparse.** Known bias in the writer's layout selection (tracked as #65). For too-eager: the revise loop can downgrade specific concept_illustration slides to `big_idea` or `claim_evidence`. For too-sparse: the writer is conservative on illustrations by design when the project's REPORT.md is figure-rich; consider hand-adding a slide if you really want one.

**Caption for a `data_figure` slide is rejected as too long.** Validator caps at 280 chars (v0.3.5+). The error message tells you the actual length; trim the caption, move citations to `data_source`, or split insight across multiple slides. The `revise_slide.v1` prompt knows this rule.

**Adversarial review finds the same issue across 3+ slides.** That's a deck-level pattern, not a per-slide fix. Run the revise loop once; if the pattern persists across iterations, the throughline or substory partition is the actual root cause — consider a full re-run with `--no-adversarial` first to get a clean draft, then iterate.

**Wall-clock wildly exceeds 60 minutes.** Image-gen retries on rate-limit are the most common cause; check `audit/stages/image_gen/` logs. Adversarial review on a long deck (35+ slides for `talk-45`) can also push 90+ minutes. Both are normal under load; not an error condition.

## Where to read more

- **Cross-skill setup, BERIL workflow, cohort cheat-sheets, recovery patterns** → [PARTICIPANT-RUNBOOK.md](https://github.com/ArkinLaboratory/beril-presentation-maker-skill/blob/main/docs/cross-skill/PARTICIPANT-RUNBOOK.md).
- **Hub deployment for operators** → [HUB_INSTALL.md](HUB_INSTALL.md).
- **The 14 pipeline stages in detail (with prompts)** → [SPEC.md](SPEC.md) §5.
- **Runtime contracts (file paths, draft layout, exit codes)** → [LAYOUT.md](LAYOUT.md).
- **Cross-skill interop pinning (presentation-maker as adversarial consumer)** → [CONTRACT.md](CONTRACT.md).
- **Version history** → [RELEASE_NOTES.md](RELEASE_NOTES.md).
- **Adversarial reviewer for presentations (the v3 schema this skill consumes)** → [github.com/ArkinLaboratory/beril-adversarial-skill/blob/main/TUTORIAL.md](https://github.com/ArkinLaboratory/beril-adversarial-skill/blob/main/TUTORIAL.md).
