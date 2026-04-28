---
description: Draft an evidence-grounded scientific presentation (talk or poster) from a BERDL analysis project. Runs the full 11-stage pipeline and emits a KBase-branded .pptx.
argument-hint: "[<project_id>] [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v] [--tier STRONG|THIN|EXPLORATORY] [--auto-advance] [--skip-assembly] [--model <model_id>] [--no-stream]"
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# /beril-presentation-maker

Draft a presentation for the analysis project at
`projects/<project_id>/`. The pipeline runs the 11-stage drafting
flow (plan → throughline → substory_design → curate_figures →
citation_pool → cross_tenant → intro → slide_compose → qa_prep →
speaker_notes → merge_and_assemble) and writes a validated
`slide_spec.json` rendered to `draft.pptx`.

Without `--auto-advance`, the orchestrator pauses inside the
throughline stage for the user to pick from candidates. Pass
`--auto-advance` for unattended runs (picks TL1, escalates on
overflow).

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
> root, followed by `beril-presentation-maker configure`.

Stop here if the command is missing.

## Step 2 — Resolve the project

If the user passed `<project_id>` explicitly, use it.

Otherwise, check if cwd is inside `projects/<id>/` and auto-detect.
If neither, ask the user via AskUserQuestion which project to draft
for.

Validate that `projects/<project_id>/` exists. If not, stop with an
error.

Confirm the project has the inputs presentation-maker requires:

- `REPORT.md` (canonical findings)
- `RESEARCH_PLAN.md` (design intent)
- `figures/` (or `figs/`, `plots/`, `output/figures/`,
  `results/figures/`) — at least one .png; figure curation degrades
  gracefully but the deck has no figures with none.
- `notebooks/` with at least one `*.ipynb` (used for figure
  savefig-context captions).

If any are missing, stop and tell the user. The pipeline will halt
at the curation step anyway with worse diagnostics.

## Step 3 — Start the draft

**Run the bash command in the FOREGROUND.** Plan + throughline
typically take 3-5 minutes on Sonnet; the full pipeline runs
10-25 minutes. If the bash tool warns about a long-running command,
wait for it.

From BERIL_ROOT:

    beril-presentation-maker draft <project_id> \
        [--mode <mode>] \
        [--tier <tier>] \
        [--auto-advance] \
        [--skip-assembly] \
        [--model <model_id>] \
        [--no-stream]

- Omit `--mode` for default `talk-30`.
- Omit `--tier` for default `STRONG`.
- `--auto-advance` skips interactive gates: picks TL1; escalates on
  overflow. Use for unattended smoke runs.
- `--skip-assembly` stops after fragment merge (no .pptx). Useful for
  spec-only iteration.
- Omit `--model` for Sonnet (default; substantially cheaper than Opus
  on this pipeline).

## Step 4 — Surface the output

After the bash command completes, the draft directory will be at
`projects/<project_id>/talks/draft_N/`. Tell the user:

- The deck path: `projects/<project_id>/talks/draft_N/draft.pptx`
- The slide spec: `projects/<project_id>/talks/draft_N/slide_spec.json`
- The audit log: `projects/<project_id>/talks/draft_N/audit/`
- If `--skip-assembly` was passed: only `slide_spec.json` exists;
  user can run `/beril-presentation-maker-continue <draft_dir>
  --resume-from merge` to assemble.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `slide_spec.json failed schema validation: deprecated 'curated/' segment` | slide_compose emitted a `figures/curated/<name>.png` path | Inspect the failed fragment; either bump `slide_compose.v1.md` or fix the spec by hand and retry with `--resume-from merge` |
| `asset not found` warnings + draft.pptx with missing pictures | figure path doesn't resolve under draft_dir or project_dir | Check `figures_curated.md` for the canonical paths; cross-reference against the spec |
| pipeline halt at `curate_figures` | no figures in any candidate dir | The project needs notebooks that emit savefig calls or REPORT.md with image refs |
| pipeline halt at `citation_pool` with `pool_exhaustion` | seed bibliography too small + WebSearch returning few results | Manually add references to a project-level `references.md` and retry with `--resume-from citation_pool` |

## Re-running

Re-iterating on a single stage:

    beril-presentation-maker continue <draft_dir> --resume-from <stage>

See `/beril-presentation-maker-continue` for details.
