---
description: Draft an evidence-grounded scientific presentation (talk or poster) from a BERDL analysis project. Runs the full 14-stage pipeline including image_gen + adversarial review-rewrite loop and emits a KBase-branded .pptx.
argument-hint: "[<project_id>] [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v] [--tier STRONG|THIN|EXPLORATORY] [--auto-advance] [--no-adversarial] [--no-images] [--auto-approve-images] [--max-image-cost-usd <n>] [--image-style <style>] [--max-revise-cost-usd <n>] [--max-revisions <n>] [--skip-assembly] [--model <model_id>] [--no-stream]"
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# /beril-presentation-maker

Draft a presentation from a BERDL analysis project. The pipeline runs
14 stages (plan → throughline → substory_design → curate_figures →
citation_pool → cross_tenant → intro → slide_compose → qa_prep →
speaker_notes → image_gen → merge → adversarial_review →
revise_slides) and writes the deck to
`<draft_dir>/deliverable/draft.pptx`.

Without `--auto-advance`, the orchestrator pauses inside the
throughline stage for the user to pick from candidates. Pass
`--auto-advance` for unattended runs (picks TL1, escalates on
overflow).

For full reference docs (mode matrix, output artifacts catalog,
cost-control flags, manual-edit workflow), see `SKILL.md`.

## Step 1 — Verify the package is installed

Run in a Bash block:

    beril-presentation-maker --version

If the command is not found, tell the user:

> The `beril-presentation-maker` package isn't on your PATH. Install it with:
>
>     pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git
>
> If you have an SSH key registered with GitHub you can also use the
> SSH URL — note the explicit `git@`, which is required:
>
>     pipx install --force git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git
>
> Then run `beril-presentation-maker install-skill .` from your BERIL
> root, followed by `beril-presentation-maker configure`. See
> `HUB_INSTALL.md` for the full hub deployment runbook.

Stop here if the command is missing.

## Step 2 — Resolve project context

Walk this 4-signal resolution tree IN ORDER and stop at the first
match. This mirrors `/beril-adversarial`'s tree so users have a
consistent experience across the BERIL skill family.

**2a. Explicit argument.** If the user typed a project_id after the
slash command (e.g., `/beril-presentation-maker my_project_id`),
use it as-is. Validate `projects/<id>/` exists; ask the user to
clarify if not.

**2b. Git branch convention.** Run `git -C $BERIL_ROOT branch
--show-current`. The hub uses a `projects/<id>` branch-naming
convention. Branch `projects/gene_function_ecological_agora` means
the active project is `gene_function_ecological_agora`. Strip the
`projects/` prefix; that's the project_id. **Confirm with the user
before acting:** "I see you're on branch `projects/<id>`. Draft a
presentation for that project? [Y/n]". This is the strongest
signal on the hub.

**2c. cwd.** Run `pwd`. If the path is inside `projects/<id>/`,
that `<id>` is the project_id. Common when the user `cd`'d into a
project manually.

**2d. Ask the user.** If 2a–2c didn't resolve, present the project
list and ask:

```bash
ls $BERIL_ROOT/projects/
```

Validate that `projects/<project_id>/` exists. If not, stop with
an error. Confirm the project has the inputs presentation-maker
requires:

- `REPORT.md` (canonical findings)
- `RESEARCH_PLAN.md` (design intent)
- `figures/` (or `figs/`, `plots/`, `output/figures/`,
  `results/figures/`) — at least one .png; figure curation degrades
  gracefully but the deck has no figures with none.
- `notebooks/` with at least one `*.ipynb` (used for figure
  savefig-context captions).

If any are missing, stop and tell the user. The pipeline will halt
at curation/citation stages with worse diagnostics anyway, so
catching it at Step 2 saves time + cost.

## Step 3 — Pick mode + tier (optional)

Default is `--mode talk-30 --tier STRONG`. Other modes per the
SKILL.md mode matrix: `talk-15` / `talk-45` / `lightning-5` /
`poster-h` / `poster-v`. Tier defaults to STRONG; override with
`--tier THIN|EXPLORATORY` for hedged language register.

If the user didn't specify, ask only when ambiguous (e.g., they
said "make a poster" — ask `poster-h` vs. `poster-v`).

## Step 4 — Start the draft

**Run the bash command in the FOREGROUND.** Plan + throughline
typically take 3-5 minutes on Sonnet; the full pipeline runs
15-25 minutes for `talk-30 STRONG`. If the bash tool warns about a
long-running command, wait for it.

From BERIL_ROOT:

    beril-presentation-maker draft <project_id> \
        [--mode <mode>] \
        [--tier <tier>] \
        [--auto-advance] \
        [--no-adversarial] \
        [--no-images] \
        [--max-image-cost-usd <n>] \
        [--max-revise-cost-usd <n>] \
        [--skip-assembly] \
        [--model <model_id>] \
        [--no-stream]

Common flag combinations:

- **First-time fresh run, attended:** no flags beyond `<project_id>`.
  User picks throughline; image gate prompts per slide.
- **Unattended smoke run:** `--auto-advance --auto-approve-images
  --max-image-cost-usd 0.20`. Picks TL1, bulk-approves images, caps
  image-gen spend at $0.20.
- **Iterating on prompts (skip adversarial):** `--no-adversarial`.
  Saves $1-5 by skipping stages 13-14.
- **Spec-only iteration (no .pptx):** `--skip-assembly`. Stops
  after merge; useful when iterating on prompts where you don't
  need the visual every time.
- **Cost-bounded smoke:** `--max-revise-cost-usd 1.00 --max-revisions 3
  --max-image-cost-usd 0.10`. Tighter cost ceiling for budget-
  conscious testing.

See SKILL.md "Cost-control flags" for the full table.

## Step 5 — Surface the output

After the bash command completes, the draft directory will be at
`projects/<project_id>/talks/draft_N/`. The 4-zone layout means:

- **The deck:** `projects/<project_id>/talks/draft_N/deliverable/draft.pptx`
- **The story:** `projects/<project_id>/talks/draft_N/narrative/`
  (throughline + substories + references)
- **The spec:** `projects/<project_id>/talks/draft_N/working/slide_spec.json`
- **The audit log:** `projects/<project_id>/talks/draft_N/audit/`
  (per-stage cost, snapshots, adversarial review JSON if it ran)

Tell the user:

1. The deck path (the deliverable).
2. If adversarial review ran: total findings + what was revised
   in-loop (from `audit/revise_loop_metadata.json`).
3. If `citation_reality` findings (v3) surfaced: direct user to
   `working/next_actions.md` — these need human verification.
4. If `--skip-assembly` was passed: only `slide_spec.json` exists;
   run `/beril-presentation-maker-continue <draft_dir>
   --resume-from merge` to assemble.

## Step 6 — Guidance

Based on the run outcome:

- **Clean run:** point user at the deck. Suggest manual polish in
  PowerPoint (per the recommended workflow in SKILL.md "Manual
  edits to the deck").
- **Adversarial findings revised in-loop:** count of P0 findings
  revised + any rejected. Suggest `--resume-from assemble` if user
  wants to re-eyeball.
- **citation_reality findings (v3):** these are surfaced rather
  than auto-revised. List the citation_id + slide_id for each from
  `next_actions.md`. Recommend the user verify each citation
  against the project's `references.md` or original source before
  shipping.
- **Quantitative-grounding warnings:** ungrounded numbers in
  `audit/quantitative_grounding.md`. Surface with slide-id
  locations; recommend manual fix or re-running upstream stages.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `slide_spec.json failed schema validation: deprecated 'curated/' segment` | slide_compose emitted a `figures/curated/<name>.png` path | Inspect the failed fragment; either bump `slide_compose.v1.md` or fix the spec by hand and retry with `--resume-from merge` |
| `asset not found` warnings + draft.pptx with missing pictures | figure path doesn't resolve under draft_dir or project_dir | Check `working/curated_figures.md` for canonical paths; cross-reference against the spec |
| pipeline halt at `curate_figures` | no figures in any candidate dir | The project needs notebooks that emit savefig calls or REPORT.md with image refs |
| pipeline halt at `citation_pool` with `pool_exhaustion` | seed bibliography too small + WebSearch returning few results | Manually add references to a project-level `references.md` and retry with `--resume-from citation_pool` |
| `image-gen worst-case $X > remaining budget $Y` | `--max-image-cost-usd` lower than per-image bound | v0.3.3.2 set worst-case at $0.05; set `--max-image-cost-usd 0.10` or higher |
| `CBORG_API_KEY not set` | image_gen stage can't reach CBORG | Add `CBORG_API_KEY=...` to `BERIL_ROOT/.env`; the orchestrator auto-loads it |
| `beril-adversarial review failed (rc=...)` | adversarial CLI not on PATH or wrong version | `pipx install --force git+https://github.com/ArkinLaboratory/beril-adversarial-skill.git@v0.7.0.1` |

See SKILL.md "Pitfall detection" for the broader protocol.

## Re-running

Re-iterating on a single stage:

    beril-presentation-maker continue <draft_dir> --resume-from <stage>

See `/beril-presentation-maker-continue` for the resume-stage table
and required-artifact prerequisites per stage.
