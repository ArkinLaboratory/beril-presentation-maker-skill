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

**v0.3.6: halt-and-handoff at the throughline-pick gate (paper-writer
pattern).** Without `--auto-advance`, the orchestrator runs stages 1-2
(plan + throughline candidates), writes `<draft_dir>/.handoff.json`
describing the gate state, prints a "what to do next" message, and
exits 0 cleanly. This works in TTY-less contexts (Claude Code's
backgrounded bash on the hub, CI, daemons) where the prior
`read </dev/tty` blocking model failed 100% of the time. The slash
command (Steps 4-5 below) reads the handoff, presents candidates via
`AskUserQuestion`, and re-invokes `continue --pick TLN` to resume from
substory_design through to the .pptx. Pass `--auto-advance` for
unattended runs (auto-picks TL1, no halt).

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

## Step 4 — Start the draft (runs to throughline-pick gate)

**Run the bash command in the FOREGROUND.** Stages 1-2 (plan +
throughline candidates) typically take 3-5 minutes on Sonnet for STRONG
tier; longer for THIN/EXPLORATORY. If the bash tool warns about a
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
  Bash halts at the throughline-pick gate (writes `.handoff.json`,
  exits 0); proceed to Step 5 to read the handoff and ask the user.
- **Unattended smoke run:** `--auto-advance --auto-approve-images
  --max-image-cost-usd 0.20`. Auto-picks TL1, runs end-to-end without
  halting, bulk-approves images, caps image-gen spend at $0.20. Skip
  Steps 5-6 entirely; the .pptx will be at `deliverable/draft.pptx`
  when bash returns.
- **Iterating on prompts (skip adversarial):** `--no-adversarial`.
  Saves $1-5 by skipping stages 13-14.
- **Spec-only iteration (no .pptx):** `--skip-assembly`. Stops after
  merge; useful when iterating on prompts where you don't need the
  visual every time.
- **Cost-bounded smoke:** `--max-revise-cost-usd 1.00 --max-revisions 3
  --max-image-cost-usd 0.10`. Tighter cost ceiling for budget-
  conscious testing.

See SKILL.md "Cost-control flags" for the full table.

When the bash returns, check whether it halted at the gate (exit 0
with `.handoff.json` written) or completed (exit 0 with a .pptx in
`deliverable/`). If `--auto-advance` was set, you should see the .pptx
and can skip to Step 6. Otherwise, proceed to Step 5.

## Step 5 — Read the throughline-pick handoff and ask the user

After the bash returns from Step 4 without `--auto-advance`, the gate
should have written `<draft_dir>/.handoff.json` describing the
throughline-pick state. The draft_dir path was printed near the top
of the bash output ("draft dir: ...") and is also the path under
`projects/<project_id>/talks/draft_N/`.

Read the handoff JSON in a Bash block:

    cat <draft_dir>/.handoff.json

The expected fields:

- `phase` — should be `"throughline_pick"`
- `candidates` — an array of `{id, label}` objects (TL1, TL2, ...)
- `candidates_md` — absolute path to the full candidates markdown with
  per-candidate evidence maps
- `next_command` — the canonical command shape to invoke next

If `phase` is anything other than `"throughline_pick"`, something
upstream went wrong; tell the user and stop. If the handoff doesn't
exist at all, the bash either completed (look for the .pptx) or
errored (re-read the bash output for the failure mode).

**Before invoking AskUserQuestion**, in a Bash block tell the user
the absolute path to the candidates markdown so they can open it in
a separate terminal or scrollback for the full evidence map per
candidate. The AskUserQuestion widget truncates descriptions, and
the evidence map is the substantive material:

    echo "Open this for the full evidence map:"
    echo "  $(cat <draft_dir>/.handoff.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["candidates_md"])')"

**Then invoke AskUserQuestion** with one option per candidate:

- `label`: the candidate id (e.g. `"TL1"`, `"TL2"`)
- `description`: use the `label` field from the handoff JSON; trim to
  one line if the LLM produced a long label

Question framing:

> Pick a throughline candidate. Open the candidates markdown above for
> the full evidence map per candidate.

After the user selects, **immediately re-invoke the bash** to run
`continue --pick TLN` and resume the pipeline from substory_design.
This is a foreground run; the remaining 12 stages take 12-20 minutes.

    beril-presentation-maker continue <draft_dir> --pick TL2 \
        [--mode <mode>] \
        [--auto-approve-images] \
        [--max-image-cost-usd <n>] \
        [--no-adversarial] \
        [--max-revise-cost-usd <n>]

Forward whatever flags from Step 4 are still relevant. The `--mode`
should match the original draft's mode; the orchestrator validates
this. If image-gen is enabled and you're running unattended, set
`--auto-approve-images --max-image-cost-usd <cap>`.

## Step 6 — Surface the output

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

## Step 7 — Guidance

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
| Bash returns rc=0 after stages 1-2 with no .pptx; `<draft_dir>/.handoff.json` exists with `phase=throughline_pick` | Working as designed (v0.3.6 halt-and-handoff). The bash halted at the throughline-pick gate awaiting user input. | Proceed to Step 5 (read handoff, ask user via AskUserQuestion, run `continue --pick TLN`). For unattended runs, re-invoke `draft` with `--auto-advance` to skip the gate. |
| Old `(Pick a throughline (TL1 / TL2 / TL3):` prompt waits forever / errors with `read: ambiguous redirect` | Pre-v0.3.6 bash with TTY-block gate, running in TTY-less context | Upgrade to v0.3.6+ (`pipx install --force git+...@v0.3.6`); the TTY block is gone in v0.3.6. |
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
