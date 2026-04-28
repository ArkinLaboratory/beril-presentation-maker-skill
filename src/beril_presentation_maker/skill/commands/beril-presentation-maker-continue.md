---
description: Re-run the presentation-maker orchestrator from a named stage, reusing earlier-stage artifacts on disk. Useful for prompt iteration on a single stage or recovery after a mid-pipeline failure.
argument-hint: "<draft_dir> --resume-from <stage> [--auto-advance] [--no-stream] [--model <model_id>]"
allowed-tools: Bash, Read, Write
---

# /beril-presentation-maker-continue

Resume an existing presentation draft from a named stage. The
orchestrator reuses on-disk artifacts of earlier stages and re-runs
later ones. Useful for:

- Prompt iteration: changed `slide_compose.v1.md` and want to re-run
  just `slide_compose → qa_prep → speaker_notes → merge` without
  re-doing plan / throughline / substory.
- Mid-pipeline failure recovery: rerun from the failed stage onward.
- Spec-only iteration: pass `--skip-assembly` to stop at the merged
  spec without rendering .pptx.

## Step 1 — Verify the package is installed

Run in a Bash block:

    beril-presentation-maker --version

If the command is not found, refer the user to
`/beril-presentation-maker` Step 1.

## Step 2 — Validate the draft_dir

The user must pass `<draft_dir>` (e.g.,
`projects/<project_id>/talks/draft_3/`). Confirm it exists and
contains the artifacts required for the chosen `--resume-from`
stage:

| `--resume-from` | Required artifacts on disk |
|---|---|
| `plan` | (none — re-runs plan) |
| `throughline` | `00_plan.md` |
| `substory_design` | `00_plan.md`, `00_throughline.md` |
| `curate_figures` | `00_plan.md`, `00_throughline.md`, `02_substories.md` |
| `citation_pool` | as above + `figures_curated.md` |
| `cross_tenant` | as above + `citation_pool.json` |
| `intro` | as above + `cross_tenant_signal.md` (optional) |
| `slide_compose` | as above + `03_slides/intro.json` |
| `qa_prep` | as above + `03_slides/S*_slides.json` |
| `speaker_notes` | as above + `03_slides/qa_anticipated.json` |
| `merge` | all of the above |

If artifacts are missing, the orchestrator will halt with a clear
diagnostic naming the missing files.

## Step 3 — Run the resume

**Run the bash command in the FOREGROUND.** Cost depends on the
resume stage; see the table in `/beril-presentation-maker` for
ballpark figures.

    beril-presentation-maker continue <draft_dir> \
        --resume-from <stage> \
        [--auto-advance] \
        [--no-stream] \
        [--model <model_id>]

## Step 4 — Surface the output

If the resume completed merge_and_assemble, the draft.pptx is at
`<draft_dir>/draft.pptx`. Otherwise, surface the produced artifacts
for the resumed stage and any later ones the orchestrator ran.

## Failure modes

Same table as `/beril-presentation-maker`. Most common on resume:
schema-validation rejection at `merge` stage when slide_compose
fragments contain a malformed `figure` path. Fix the fragment by
hand and re-run with `--resume-from merge`.
