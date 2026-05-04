---
description: Re-run the presentation-maker orchestrator from a named stage, reusing earlier-stage artifacts on disk. Useful for prompt iteration on a single stage, recovery after a mid-pipeline failure, re-rolling AI images, or re-running adversarial review.
argument-hint: "<draft_dir> --resume-from <stage> [--auto-advance] [--no-adversarial] [--no-images] [--auto-approve-images] [--max-image-cost-usd <n>] [--image-style <style>] [--max-revise-cost-usd <n>] [--max-revisions <n>] [--skip-assembly] [--no-stream] [--model <model_id>]"
allowed-tools: Bash, Read, Write
---

# /beril-presentation-maker-continue

Resume an existing presentation draft from a named stage. The
orchestrator reuses on-disk artifacts of earlier stages and re-runs
later ones. Useful for:

- **Prompt iteration** — changed `slide_compose.v1.md` and want to
  re-run `slide_compose → qa_prep → speaker_notes → image_gen →
  merge` without redoing plan / throughline / substory_design /
  citation_pool / cross_tenant / intro.
- **Mid-pipeline failure recovery** — rerun from the failed stage
  onward. The 14-stage pipeline is idempotent at each stage
  boundary.
- **Re-rolling AI images** — `--resume-from image_gen` with a
  cleared manifest re-authors images. Cached request.json reused
  unless `--image-style` differs.
- **Re-running adversarial review** — `--resume-from
  adversarial_review` after a deck edit. Or
  `--resume-from revise_slides` if review JSON is fresh.
- **Spec-only iteration** — pass `--skip-assembly` to stop at the
  merged spec without rendering .pptx.

For the full pipeline + workflow + 4-signal project resolution
tree, see `SKILL.md` and `/beril-presentation-maker`.

## Step 1 — Verify the package is installed

Run in a Bash block:

    beril-presentation-maker --version

If the command is not found, refer the user to
`/beril-presentation-maker` Step 1 or `HUB_INSTALL.md`.

## Step 2 — Resolve project + draft

If the user passed `<draft_dir>` explicitly (e.g.,
`projects/<id>/talks/draft_3/`), validate it exists and proceed to
Step 3.

If `<draft_dir>` not specified, walk the 4-signal tree from
`/beril-presentation-maker` Step 2 to resolve the project, then:

```bash
ls $BERIL_ROOT/projects/<project_id>/talks/
```

Pick the highest-numbered `draft_N` as the proposed default and
confirm: "Found drafts `draft_1` through `draft_3`. Resume from
`draft_3`, or pick another? [Y/n/N=specific number]".

The orchestrator's `<draft_dir>` argument needs the absolute path:
`$BERIL_ROOT/projects/<project_id>/talks/draft_<N>/`. The Python
wrapper auto-derives `--beril-root` from the draft_dir's
`parents[3]` (the path layout is
BERIL_ROOT/projects/<id>/talks/draft_N), so users don't need to
pass `--beril-root` explicitly when the layout is standard.

## Step 3 — Pick the resume stage

The 14 stages, in order:

| Resume stage | Pipeline runs from this stage onward | Cost (Sonnet, talk-30) |
|---|---|---|
| `plan` | full pipeline (re-runs from scratch) | ~$2-4 |
| `throughline` | throughline → ... | ~$1.80-3.80 |
| `substory_design` | substory → ... | ~$1.55-3.55 |
| `curate_figures` | curate (Python) → ... | ~$1.35-3.35 |
| `citation_pool` | citation pool → ... | ~$1.35-3.35 |
| `cross_tenant` | cross_tenant → ... | ~$1.05-3.05 |
| `intro` | intro → ... | ~$1.00-3.00 |
| `slide_compose` | slide_compose → ... | ~$0.85-2.85 |
| `qa_prep` | qa_prep → ... | ~$0.40-2.40 |
| `speaker_notes` | speaker_notes → ... | ~$0.20-2.20 |
| `image_gen` | image_gen → ... (NEW v0.3.3) | ~$0-0.50 |
| `merge` | merge + assemble (no LLM) | $0 |
| `adversarial_review` | adversarial → revise loop | ~$1-5 |
| `revise_slides` | revise loop only (uses prior review JSON) | ~$0.30-5 |

## Step 4 — Validate prereqs

The orchestrator runs `validate_resume_prereqs` before invoking the
stage. Each stage requires earlier-stage artifacts on disk:

| `--resume-from` | Required artifacts (under `<draft_dir>/`) |
|---|---|
| `plan` | (none — re-runs plan) |
| `throughline` | `working/00_plan.md` |
| `substory_design` | `working/00_plan.md`, `narrative/00_throughline.md` |
| `intro` | as above + `narrative/02_substories.md` |
| `slide_compose` | as above + `working/03_slides/intro.json` |
| `image_gen` | as above + `working/03_slides/S*_slides.json` + `narrative/00_throughline.md`, `narrative/02_substories.md` |
| `merge` | all of the above + `working/03_slides/qa_anticipated.json` (when qa_prep ran) |
| `adversarial_review` | merge complete + `working/slide_spec.json` |
| `revise_slides` | `audit/adversarial_review.json` (v3 schema) |

If artifacts are missing, the orchestrator halts with a clear
diagnostic naming the missing files. v0.3.0 drafts (pre-zone
layout) are **not** compatible — start a fresh draft.

## Step 5 — Run the resume

**Run the bash command in the FOREGROUND.** Cost depends on the
resume stage; see the table above.

    beril-presentation-maker continue <draft_dir> \
        --resume-from <stage> \
        [--auto-advance] \
        [--no-adversarial] \
        [--no-images] \
        [--auto-approve-images] \
        [--max-image-cost-usd <n>] \
        [--image-style <style>] \
        [--max-revise-cost-usd <n>] \
        [--max-revisions <n>] \
        [--skip-assembly] \
        [--no-stream] \
        [--model <model_id>]

Common resume scenarios:

- **Re-roll AI images:** delete or hand-edit
  `<draft_dir>/working/05_images/manifest.json` to remove the
  rejected entries, then:

      beril-presentation-maker continue <draft_dir> \
          --resume-from image_gen --auto-approve-images \
          --max-image-cost-usd 0.20

- **Re-run adversarial after deck edit:**

      beril-presentation-maker continue <draft_dir> \
          --resume-from adversarial_review

- **Re-run revise loop with existing review JSON:**

      beril-presentation-maker continue <draft_dir> \
          --resume-from revise_slides --max-revisions 3

- **Re-render after editing slide_spec.json:**

      beril-presentation-maker continue <draft_dir> \
          --resume-from merge

  (this is the FREE option — no LLM cost; pure Python re-assembly.)

## Step 6 — Surface the output

If the resume completed merge_and_assemble, the deck is at
`<draft_dir>/deliverable/draft.pptx`. Otherwise, surface the
artifacts produced by the resumed stage and any later ones the
orchestrator ran. See `/beril-presentation-maker` Step 5 for the
full output-handling protocol.

## Failure modes

Same table as `/beril-presentation-maker` Failure modes. Most
common on resume:

- **`slide_id S<N>-pos<P> already in manifest`** during image_gen
  resume. The previous run recorded an attempt; clear the manifest
  entry (or `rm working/05_images/manifest.json` for a clean
  re-roll).
- **Schema-validation rejection at `merge`** when slide_compose
  fragments contain a malformed `figure` path. Fix the fragment by
  hand and re-run with `--resume-from merge`.
- **`v0.3.0-shape draft is incompatible`** — old layout, no
  migration. Start a fresh draft via `/beril-presentation-maker`.
