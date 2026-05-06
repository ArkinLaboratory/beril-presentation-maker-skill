# PARTICIPANT-RUNBOOK.md

A walkthrough for researchers and event participants using the **KBase Co-Scientist** augmentation skills inside the [BERIL Research Observatory](https://github.com/kbaseincubator/BERIL-research-observatory).

This runbook is durable — it's the reference for any BERIL user who wants to turn finished analysis projects into manuscripts, presentations, and adversarial reviews. The **Quick start** below gives May 7 event participants the minimum path; the rest of the document fills in everything else.

> **STATUS:** v0.2 — all four skill flows filled, cohort cheat-sheets ready, troubleshooting populated from observed failure modes. Will continue to grow as dry-runs and the May 7 event surface new issues. Last edited 2026-05-05.

---

## Quick start (for May 7 event participants)

You should already have done this before the event:

1. **Account on the KBERDL JupyterHub** (admin gives you this).
2. **Open a terminal** in your hub session.
3. **Install the four skills via pipx:**
   ```bash
   pipx install --force git+https://github.com/ArkinLaboratory/beril-paper-writer-skill.git@<TAG>
   pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git@<TAG>
   pipx install --force git+https://github.com/ArkinLaboratory/beril-adversarial-skill.git@<TAG>
   pipx install --force git+https://github.com/ArkinLaboratory/beril-atlas-skill.git@<TAG>
   ```
   (Pinned tags will be supplied in your event-day email — pin them, don't use `@main`.)
4. **Install each skill into your BERIL checkout:**
   ```bash
   cd ~/BERIL-research-observatory
   beril-paper-writer install-skill .
   beril-presentation-maker install-skill .
   beril-adversarial install-skill .
   beril-atlas install-skill .
   ```
5. **Configure each:**
   ```bash
   beril-paper-writer configure
   beril-presentation-maker configure
   beril-adversarial configure
   beril-atlas configure
   ```

On event day:

1. **Open a Claude Code session** inside `~/BERIL-research-observatory`.
2. **Run `/berdl_start`** in Claude — orientation + project pick.
3. **Do your research** (analysis, queries, notebooks, REPORT.md) using BERIL's native tools, in Claude.
4. **Optional `/submit`** for BERIL's automated review.
5. **Generate your deliverable** based on your assigned cohort — see the cheat-sheet for your track in [Part 8](#part-8-cohort-cheat-sheets).
6. **Find your output** under `projects/<project_id>/{papers,talks}/draft_N/deliverable/`.

If something fails, see the [Recovery](#part-6-recovery--hand-editing) section.

---

## Overview

This runbook covers two distinct contexts:

- **The terminal** — where you `pipx install`, run `beril-X configure`, and can invoke any skill's CLI directly (e.g., `beril-presentation-maker draft <project_id>`).
- **Claude Code, opened inside the BERIL repo** — where you operate BERIL's research pipeline (`/berdl_start`, analysis, `/submit`) and can also invoke our augmentation skills as slash commands (`/beril-presentation-maker`, `/beril-paper-writer`, `/beril-adversarial`, `/beril-atlas`) or via natural language ("Generate a presentation for this project at the STRONG tier"). Each skill ships a single top-level slash command plus a few task-specific ones (`/beril-presentation-maker-continue`, `/beril-paper-writer-continue`, `/beril-adversarial-configure`).

Both paths produce the same outputs. Most participants will live mostly in Claude Code; the terminal is for installation, configuration, and crash recovery.

**Audience assumptions:**

- You have basic command-line literacy.
- You have a JupyterHub account on the KBERDL hub (or equivalent BERIL deployment).
- You don't need to know how the skills are implemented — only how to use them.

**Out of scope:**

- Setting up the JupyterHub itself (admin task; not covered).
- Writing your own skill (see each skill's `SPEC.md` if you want this).
- Modifying BERIL upstream (see BERIL's own contributor guide).

---

## Part 1: Setup

### 1.1 Prerequisites

Before installing anything:

- **Python 3.10+** on the hub. Verify with `python3 --version`. The skills use modern type hints and won't run on 3.9.
- **pipx**. Verify with `pipx --version`. If missing: `python3 -m pip install --user pipx && python3 -m pipx ensurepath`. Reload your shell.
- **A BERIL checkout** at `~/BERIL-research-observatory` (or wherever your BERIL deployment lives). The hub usually mounts one at `~/BERIL-research-observatory`.
- **Claude Code** installed and authenticated. Most hub configurations preinstall this.
- **(Optional, for presentation-maker)** A CBORG API key, used for AI-image generation on `concept_illustration` slides. The key lives in `BERIL_ROOT/.env` as `CBORG_API_KEY=...` — your hub admin should already have provisioned this. Without it, presentation-maker still runs; it just falls back to image-free `big_idea` layouts for slides that would otherwise have used AI illustrations.

### 1.2 Install the four skills

The repos are public, so no GitHub authentication is needed.

```bash
pipx install --force git+https://github.com/ArkinLaboratory/beril-paper-writer-skill.git@<TAG>
pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git@<TAG>
pipx install --force git+https://github.com/ArkinLaboratory/beril-adversarial-skill.git@<TAG>
pipx install --force git+https://github.com/ArkinLaboratory/beril-atlas-skill.git@<TAG>
```

Replace `<TAG>` with the pinned version your event-day email specifies. Do **not** use `@main` for production runs — pinned tags ensure all participants are using identical versions.

Verify:

```bash
beril-paper-writer --version
beril-presentation-maker --version
beril-adversarial --version
beril-atlas --version
```

You should see four version strings without errors. If `command not found`, run `pipx ensurepath` and restart your shell.

### 1.3 Install each skill into your BERIL checkout

This step copies the skill's `SKILL.md`, slash commands, prompts, and tools into your BERIL deployment's `.claude/skills/` tree, so Claude Code (running inside the BERIL repo) can find and invoke them.

```bash
cd ~/BERIL-research-observatory
beril-paper-writer install-skill .
beril-presentation-maker install-skill .
beril-adversarial install-skill .
beril-atlas install-skill .
```

The dot (`.`) is the BERIL root. Each command will report what it copied and where. Re-running the command updates in place; the skill version installed must match the pipx version installed (otherwise upgrade with `pipx install --force ...`, then re-run `install-skill`).

### 1.4 Configure each skill

```bash
beril-paper-writer configure
beril-presentation-maker configure
beril-adversarial configure
beril-atlas configure
```

Each skill's configure step:

- Detects whether you have `claude` and/or `codex` CLIs available (most participants will have `claude`).
- For presentation-maker: verifies that `CBORG_API_KEY` is reachable (either as a shell env var or in `BERIL_ROOT/.env`).
- For adversarial-using producers (paper-writer, presentation-maker): verifies that `beril-adversarial` is installed and accessible.
- Writes a small per-user state file under your BERIL checkout's `.claude/` tree.

**Common gotchas:**

- *"adversarial: [absent]"* in configure output → run `pipx install ... beril-adversarial-skill...` and re-run `configure`. Cause: you skipped step 1.2 for adversarial, or your `pipx` venv path isn't on `$PATH`.
- *"CBORG_API_KEY: missing"* → confirm with hub admin that `BERIL_ROOT/.env` contains `CBORG_API_KEY=...`. Do **not** paste the key into the chat — secrets stay in `.env`.
- *"BERIL_ROOT must be set"* when running `draft` later → don't `BERIL_ROOT=...` in your shell without `export`. Either `export BERIL_ROOT=...`, or just `cd` into your BERIL tree and let auto-detection find it (works since presentation-maker v0.3.4.6, paper-writer recent versions).

---

## Part 2: The BERIL workflow (briefly)

Once setup is done, your day-to-day loop is in **Claude Code**, opened inside `~/BERIL-research-observatory`. The augmentation skills slot into BERIL's existing pipeline; they don't replace it.

A typical end-to-end research session looks like:

1. **`/berdl_start`** — BERIL's orientation skill. Tells you what databases are available, helps you pick or create a project, surfaces relevant tenants. New users should always start here. **As part of project creation, BERIL puts you on the `projects/<your_project_id>` git branch automatically** — that's how all the augmentation skills' slash commands later figure out which project you mean (see §2.1). You don't have to set or remember anything about git.
2. **Research and analysis** — query BERDL via Spark SQL, run notebooks, compute statistics, generate figures. Claude (with BERIL skills loaded) can drive these directly. This phase produces the project's `REPORT.md`, `RESEARCH_PLAN.md`, executed notebooks under `notebooks/`, and figures under `figures/`.
3. **(Optional) `/submit`** — BERIL's lightweight automated reviewer runs against your project and produces `REVIEW.md`. This is *not* the same as our adversarial review; `/submit` is fast and broad, our adversarial is slow and deep.
4. **Generate a deliverable** — paper-writer or presentation-maker (or both), optionally with our adversarial review (Part 5).

**What our skills expect from your project:**

For paper-writer or presentation-maker to produce a useful draft, your project should have:

- `REPORT.md` — narrative results write-up (the "what we found" document).
- `RESEARCH_PLAN.md` — the original research question + methodology (the "what we set out to do" document).
- `figures/<name>.png` — figure assets, referenced from REPORT.md or notebooks.
- `notebooks/*.ipynb` — analysis notebooks, ideally executed (output cells populated).
- A clear **evidence tier**: STRONG, THIN, or EXPLORATORY. The skills tier-aware their output (a STRONG-tier project gets confident claims; an EXPLORATORY-tier project gets explicit caveats and "this is preliminary" framing).

If your project is missing pieces — say `figures/` is empty or `REPORT.md` is one paragraph — the draft will be thin. The skills will still run and tell you what's missing in their output (`next_actions.md`, `audit/` logs).

**What "tier" means:**

- **STRONG** — multi-line evidence, replicated, statistically robust. Default when unspecified for established projects.
- **THIN** — one or two evidence lines; some support but inferential leaps remain. Use for early-stage projects.
- **EXPLORATORY** — preliminary signals, hypothesis-generating. Use for first-pass projects; the skills will frame all claims as exploratory.

For full BERIL usage, see BERIL's own documentation. This runbook only covers the augmentation skills.

### 2.1 How the skills know which project you mean — the branch convention

You'll be working on your own project, not one we provide. **You don't need to think about how the skills find it.** When you create or pick a project via BERIL's `/berdl_start` flow, BERIL automatically puts you on a `projects/<project_id>` git branch — that branch is what every augmentation skill's slash command reads to figure out which project the current command targets.

For completeness — the slash commands walk a four-signal resolution tree, in order, and stop at the first match:

1. **Explicit argument** — if you typed a project after the slash command (`/beril-presentation-maker my_phylo_study`), it wins.
2. **Git branch** — `git -C $BERIL_ROOT branch --show-current` returns `projects/<id>`; the agent strips the prefix and confirms with you. **This is the path the BERIL flow puts you on by default; you don't have to set it manually.**
3. **cwd** — if `pwd` returns a path under `projects/<id>/`, that's the project. Used when you `cd` into a project manually.
4. **Ask** — the agent lists `projects/` and asks you to pick. Fallback only.

The four-signal tree is implemented in `beril-adversarial` (v0.7.0.1+) and `beril-presentation-maker` (v0.3.4+). Paper-writer's slash command currently uses only the cwd + explicit-argument signals (no branch detection); for paper-writer, the slash command will fall back to asking you which project you mean if you're at BERIL_ROOT — answer with the project_id BERIL gave you when you created the project. We're tracking the cross-skill consistency gap; future versions of paper-writer will adopt the same four-signal tree.

**Practical implication:** in the normal hub flow — `/berdl_start` → research → augmentation skills — there's no step where you type or remember your project_id. BERIL set it, BERIL put you on the branch, our slash commands read the branch. From the terminal (not Claude), you still pass `<project_id>` as a positional, but most participants will live in Claude.

---

## Part 3: Generate a manuscript with `beril-paper-writer`

### 3.1 When to use this skill

You want a peer-grade manuscript drafted from a finished BERDL analysis project. The skill produces an ICMJE-conformant draft (Methods → Results → Discussion → Introduction → Abstract), with explicit handling of evidence gaps, a citation pool grounded in the project's bibliography, and (optionally) a revise-loop driven by adversarial review.

The skill auto-detects your project's evidence tier from `RESEARCH_PLAN.md` (you don't pass it on the command line, unlike presentation-maker). The tier drives several authoring decisions:

- **STRONG / THIN** → output mode is `paper` (full manuscript).
- **EXPLORATORY** → output mode is `report` (preliminary-claim framing; not a publishable manuscript).

You can override mode explicitly with `--mode paper|report` if the auto-detected tier produces the wrong shape for your goal.

### 3.2 Pick a depth

| Depth | What it does | Use for |
|---|---|---|
| `quick` | Fewer revise iterations, tighter scope | Rough drafts, internal review |
| `standard` | Default. Balanced cost/quality | Most participants. |
| `deep` | More revise iterations, broader literature checks | Final pre-submission drafts |

If you don't pass `--depth`, you get `standard`.

### 3.3 Run the draft

**From Claude Code** (recommended):

Paper-writer's slash command currently auto-detects only from cwd, not from the git branch. If you're inside `projects/<your_project_id>/`, the slash command resolves it; if you're at BERIL_ROOT, you'll need to either `cd` into your project first or pass the project_id explicitly:

> *"Draft a paper at standard depth with adversarial review for `my_phylo_study`."*

**From the terminal:**

```bash
cd ~/BERIL-research-observatory
beril-paper-writer draft <project_id> \
    --depth standard \
    --max-cost-usd 25
```

Terminal invocation requires the positional `<project_id>`.

Flags worth knowing:

- `--depth quick|standard|deep` — depth tier (default: standard).
- `--mode paper|report` — output shape override (default: tier-driven; STRONG/THIN → paper, EXPLORATORY → report).
- `--no-adversarial` — skips the canonical adversarial reviewer; uses the lighter inline fallback reviewer instead. **Note:** this does *not* skip review entirely (unlike presentation-maker's `--no-adversarial`). To run with no review at all, you'd need to pass this and ignore the fallback's output. For the May 7 cohort assignments, "without adversarial review" means with `--no-adversarial`.
- `--max-cost-usd <N>` — cumulative LLM-spend cap. Pipeline halts gracefully with a handoff if it would exceed N USD on the next call.
- `--no-stream` — disables stage-by-stage output streaming. Useful if your terminal is choking on output volume.
- `--recaption` — re-runs only the caption-generation stage on an existing draft. Use this if the figures are right but captions came out boilerplate-heavy or shallow.

The pipeline is multi-stage (plan → tier-detect → throughline-pick → analysis-request gap surfacing → IMRAD section drafting → caption authoring → assemble docx → review → revise). Wall-clock is typically 15-30 min; cost is typically $5-15 depending on depth and revise iterations.

### 3.4 Where outputs land

```
projects/<project_id>/papers/draft_N/
├── deliverable/
│   ├── manuscript.docx                ← your manuscript
│   ├── manuscript.md                  ← markdown source (also consumable by presentation-maker)
│   └── next_actions.md                ← reviewer-flagged items the user should address
├── narrative/
│   ├── throughline.md                 ← chosen scientific throughline
│   └── analysis_requests.md           ← evidence gaps the writer detected
├── working/
│   ├── citations.json                 ← citation pool
│   ├── stage_metadata.json            ← per-stage cost + timing
│   └── ...
└── audit/
    ├── stages/                        ← per-stage logs
    └── runs/                          ← per-run logs (incl. adversarial)
```

The `deliverable/manuscript.docx` is the primary output. Open it in Word, Google Docs (after upload), or LibreOffice. If the writer flagged evidence gaps, see `narrative/analysis_requests.md` — these are paste-ready BERIL analysis requests you can run to fill the gaps before re-drafting.

### 3.5 What to do if something fails

```bash
beril-paper-writer continue papers/draft_N
```

Same checkpointing pattern as presentation-maker. Resumes from the last completed stage.

If the manuscript came out structurally correct but with weak captions, run `beril-paper-writer draft <project_id> --recaption` against the existing draft — re-authors only the caption stage, much cheaper than a full re-run.

---

## Part 4: Generate a presentation with `beril-presentation-maker` (worked example)

This is the worked end-to-end example for structure review. The other skill flows (paper-writer, atlas) follow the same pattern.

### 4.1 When to use this skill

You want a peer-grade slide deck (talk or poster) drafted from a BERDL analysis project. The skill produces:

- A `.pptx` file in KBase brand, with 16 layout types (title, big_idea, claim_evidence, data_figure, data_table, workflow_diagram, methods_summary, concept_illustration, cross_tenant_integration, implications, references, qa_anticipated, etc.).
- Speaker notes per slide.
- An anticipated Q&A slide.
- A citation pool grounded in the project's REPORT.md and bibliography.
- Optionally, AI-generated illustrations on `concept_illustration` slides (via CBORG-Gemini, ~$0.014/image).

### 4.2 Pick a presentation mode

| Mode | Duration | Slide count | Use for |
|---|---|---|---|
| `talk-30` | 30-min talk | ~25-30 slides | Most peer-presentations. Default. |
| `talk-15` | 15-min talk | ~12-15 slides | Conference lightning + standard short talks. |
| `talk-45` | 45-min talk | ~35-40 slides | Invited / departmental seminars. |
| `lightning-5` | 5-min talk | ~5-6 slides | Lab meetings, lightning rounds. |
| `poster-h` | poster, horizontal | 1 large slide | Conference poster. |
| `poster-v` | poster, vertical | 1 large slide | Conference poster. |

### 4.3 Run the draft

**From Claude Code** (recommended for participants):

You don't need to type your project_id — BERIL has already put you on the right branch (§2.1):

> *"Draft a 30-minute talk at the STRONG tier, auto-advance, auto-approved images at 0.20 USD max."*

The slash command reads your branch, confirms the resolved project with you, and composes the equivalent CLI call.

**From the terminal:**

```bash
cd ~/BERIL-research-observatory/projects/<project_id>
beril-presentation-maker draft <project_id> \
    --tier STRONG \
    --mode talk-30 \
    --auto-advance \
    --auto-approve-images --max-image-cost-usd 0.20
```

Terminal invocation requires the positional `<project_id>` — no branch detection at the CLI layer.

Notes on the flags:

- `--auto-advance` — skips per-stage prompts; the pipeline runs end-to-end without waiting on you. Without this flag, you'll be asked to approve each of 14 stages.
- `--auto-approve-images` — skips per-image approval prompts. Without this flag, you'll see each AI illustration before it's generated and can re-roll, change the prompt, or skip it.
- `--max-image-cost-usd 0.20` — caps per-image cost. Default behavior without this flag is to prompt; this flag is the way to make image-gen non-interactive.
- `--no-adversarial` — skips the adversarial revise-loop (Part 5) entirely. Default behavior includes adversarial review when `beril-adversarial` is installed.

The pipeline runs 14 stages (`plan` → `throughline` → `substory_design` → `curate_figures` → `citation_pool` → `cross_tenant` → `intro` → `slide_compose` → `qa_prep` → `speaker_notes` → `image_gen` → `merge` → `adversarial_review` → `revise_slides`). Each stage's outputs land in `talks/draft_N/working/`, and the final `.pptx` lands in `talks/draft_N/deliverable/draft.pptx`. Wall-clock is typically 45-60 min on a real STRONG-tier project; cost is typically $5-20 depending on slide count, image-gen, and revise iterations.

### 4.4 Where outputs land

After the pipeline completes:

```
projects/<project_id>/talks/draft_N/
├── deliverable/
│   ├── draft.pptx                     ← your slide deck
│   └── speaker-notes.md               ← speaker notes as readable markdown
├── narrative/
│   ├── REPORT-skim.md                 ← the report-skim used as input
│   ├── throughline.md                 ← the chosen throughline
│   └── substory-design.md             ← substory plan
├── working/
│   ├── slide_spec.json                ← the structured slide spec (machine-readable)
│   ├── citation_pool.md               ← references used
│   ├── stage_metadata.json            ← per-stage cost + timing
│   └── ...
└── audit/
    ├── stages/                        ← per-stage logs
    ├── runs/                          ← per-run logs (incl. adversarial)
    └── manual-edits/                  ← (only created if you hand-edit)
```

The `deliverable/draft.pptx` is the primary output. Open it in PowerPoint, Keynote, or LibreOffice. Hand-editing is supported; see [Part 6](#part-6-recovery--hand-editing).

### 4.5 What to do if something fails

If the pipeline crashes mid-flight (network blip, malformed LLM JSON, CBORG rate limit), you don't lose work — every completed stage is checkpointed. Resume with:

```bash
beril-presentation-maker continue talks/draft_N
```

This re-reads the stage state and picks up at the failed stage. If you're unsure which draft was in flight, run `beril-presentation-maker prune talks/` to see the list.

If the pipeline succeeds but the output is unsatisfactory (wrong throughline, weak punchlines, missing slide), the **revise loop** (Part 5) is the right tool — not a re-run from scratch. A re-run costs another $5-20; a revise pass on specific slides costs $0.50-2.

---

## Part 5: Adversarial review with `beril-adversarial`

### 5.1 What it produces

`beril-adversarial review --type <paper|presentation|project|plan>` is a single-pass adversarial reviewer. It produces:

- **`<type>-review.md`** — human-readable findings, one section per finding, with severity and citations.
- **`<type>-review.json`** — machine-readable findings, consumed by paper-writer's and presentation-maker's revise loops.

Findings include detection classes like `register_drift`, `claim_evidence` mismatch, `qa_softball`, `unbacked_quantitative`, `central_objection` (synthesis-level objection), `citation_reality` (fabricated/drifting citations), and several others. Each finding has a severity (P0 / Critical, P1 / Important, P2 / Suggested) and a quoted text snippet anchoring it to the deliverable.

### 5.2 Two ways to use it

**As part of a revise loop** (default for paper-writer + presentation-maker when `beril-adversarial` is installed):

When you run `beril-paper-writer draft` or `beril-presentation-maker draft` with adversarial enabled (the default), the producer skill automatically invokes `beril-adversarial review` after the initial draft and feeds findings back into the producer's revise stage. The output is a revised draft with a `revision_log` in each affected slide / section showing what changed and why.

**Standalone**, on an existing draft. Note that the input shape differs by `--type`:

```bash
# For --type paper or --type presentation: pass the draft_dir as the positional.
beril-adversarial review projects/<project_id>/talks/draft_N --type presentation
beril-adversarial review projects/<project_id>/papers/draft_N --type paper

# For --type plan or --type project: pass the project_id (under projects/).
beril-adversarial review <project_id> --type plan
beril-adversarial review <project_id> --type project
```

Optional flags: `--depth quick|standard|deep` (default: standard) and `--output <path>` to override where the review files land. Use standalone review when you want to read findings before deciding which to act on, or to review a project / plan that no producer skill has drafted from yet.

### 5.3 Cohort note

If your assigned cohort runs **without** adversarial review, pass `--no-adversarial` to the producer skill (`beril-presentation-maker draft ... --no-adversarial`). This skips both the adversarial-review stage and the subsequent revise stage; the initial draft is your final deliverable.

---

## Part 6: Recovery + hand-editing

### 6.1 Crashed pipeline

```bash
beril-presentation-maker continue talks/draft_N
beril-paper-writer continue papers/draft_N
```

Resume from the last successful stage. Both skills checkpoint per-stage; you don't lose completed work.

### 6.2 Old or junk drafts

```bash
beril-presentation-maker prune talks/
```

Lists drafts under `talks/`, shows their state, and lets you delete failed or superseded ones. Use this when your `talks/` directory is full of `draft_N/` directories from earlier attempts.

### 6.3 Audit and logs

Per-stage logs live under `<draft_N>/audit/stages/`. Per-run logs (including adversarial reviewer output and cost summaries) live under `<draft_N>/audit/runs/`. If you need to file a bug report, attach the relevant `audit/` directory.

### 6.4 Hand-editing the output

The `deliverable/draft.pptx` (or `manuscript.docx`) is yours. Open it in PowerPoint, Keynote, or LibreOffice, edit freely. The skills will detect manual edits on the next `continue` or revise pass and preserve them under `audit/manual-edits/`.

**Known cosmetic issues you may want to hand-fix in PowerPoint** (these are deferred to post-event releases):

- Title slide throughline punchline appearing truncated → adjust font size / move text.
- References slide overflowing for >8 references → split into two slides.
- `qa_anticipated` slide with a long synthesis-style question → reformat.
- `cross_tenant_integration` slide rendering as a flat bibliography → reformat.

### 6.5 Cost tracking

After a run, see `<draft_N>/working/stage_metadata.json` for per-stage cost + timing. The `cost_log.jsonl` at `talks/cost-log.jsonl` aggregates across drafts. Use this to budget if running multiple drafts.

---

## Part 7: Atlas (observability, after-the-fact)

Atlas sits **outside** the production loop. It's a read-only retrofit analyzer that scans an entire BERIL deployment — the skill pack, every project under `projects/`, and the workspace memory — and produces tabular exports, an interactive HTML dashboard, drift-review markdown, and a recommendations writeup grounded in the warehouse it builds.

For event participants, atlas is the tool the event organizers use *afterwards* to compute aggregate metrics across all participants' work (cost per draft, time-to-draft, sophistication scores, drift between cohorts). You generally don't run it during your own session.

If you do want to run atlas on a BERIL deployment for diagnostics, the bootstrap pattern is three commands (the order matters):

```bash
cd ~/BERIL-research-observatory
OUT=~/.beril-atlas/latest

beril-atlas scan --projects-root projects --outputs-root "$OUT" --extract
beril-atlas metrics --warehouse "$OUT/atlas.duckdb" --outputs "$OUT"
beril-atlas render \
    --warehouse "$OUT/atlas.duckdb" \
    --metrics-dir "$OUT/metrics" \
    --output "$OUT/dashboard.html"

open "$OUT/dashboard.html"   # macOS; xdg-open on Linux; or upload from the hub
```

`scan --extract` is the expensive step (~5M tokens / ~45 min on a 50-project corpus on a fresh deployment). The same `$OUT` directory acts as a hot cache on re-runs — only new or changed content pays LLM cost.

Atlas does not write into any project; it only reads. Running it during the event will not interfere with participants' drafts.

For the full reference (slash commands, drift-review workflow, periodic-rescan loop, cache invalidation), see [github.com/ArkinLaboratory/beril-atlas-skill](https://github.com/ArkinLaboratory/beril-atlas-skill).

---

## Part 8: Cohort cheat-sheets

Each cohort below has a one-page recipe. Pick yours and run it. The terminal commands below show `<project_id>` as the explicit positional argument; if you'd rather use Claude Code's slash commands instead of the terminal, you don't need the project_id at all — `/berdl_start` already put you on the `projects/<your_project_id>` branch and the slash commands read it (see §2.1). The exception is paper-writer, whose slash command currently doesn't read the branch — for paper-writer in Claude Code, just say "draft a paper for `<project_id>`" or first `cd` into the project directory.

### Track A: Manuscript with canonical adversarial review

```bash
cd ~/BERIL-research-observatory
beril-paper-writer draft <project_id> \
    --depth standard \
    --max-cost-usd 25
```

(Canonical adversarial reviewer is on by default when `beril-adversarial` is installed.) Wall-clock: 20-35 min. Cost: $5-15. Output: `papers/draft_N/deliverable/manuscript.docx`.

If the writer flagged evidence gaps in `narrative/analysis_requests.md`, address them in BERIL (re-run analysis, regenerate figures, update REPORT.md), then re-run the draft for a tighter manuscript.

### Track B: Manuscript with fallback inline reviewer

```bash
cd ~/BERIL-research-observatory
beril-paper-writer draft <project_id> \
    --depth standard --no-adversarial \
    --max-cost-usd 20
```

`--no-adversarial` switches from the canonical `beril-adversarial` reviewer to paper-writer's lighter inline fallback reviewer. The pipeline still reviews and revises; it just uses a less rigorous review pass. Wall-clock: 15-25 min. Cost: $4-10. Output: same path as Track A.

Cohort note: for the experimental design, "without adversarial review" in your assigned-cohort instructions means *with* `--no-adversarial`. The fallback reviewer is paper-writer's no-cross-skill-dependency degraded mode, not a true "no review" mode.

### Track C: Presentation with adversarial review

```bash
cd ~/BERIL-research-observatory/projects/<project_id>
beril-presentation-maker draft <project_id> \
    --tier STRONG --mode talk-30 \
    --auto-advance \
    --auto-approve-images --max-image-cost-usd 0.20
```

(Adversarial review is on by default.) Wall-clock: 45-60 min. Cost: $5-20. Output: `talks/draft_N/deliverable/draft.pptx`.

### Track D: Presentation without adversarial review

```bash
cd ~/BERIL-research-observatory/projects/<project_id>
beril-presentation-maker draft <project_id> \
    --tier STRONG --mode talk-30 \
    --auto-advance --no-adversarial \
    --auto-approve-images --max-image-cost-usd 0.20
```

Wall-clock: 30-45 min (no review/revise stages). Cost: $4-15. Output: `talks/draft_N/deliverable/draft.pptx`.

---

## Appendix A: Troubleshooting

Failure modes seen in install + first-use of the four skills, with fixes. This appendix will grow as new failure modes surface during dry-runs and the event.

**`pipx install` fails with "Python 3.10 or higher required"**
The hub's default Python is older than 3.10. Verify with `python3 --version`. Ask your hub admin to install Python 3.10+ or to set up pipx against a newer Python. Workaround: `pipx install --python python3.11 git+https://...` if 3.11 is available under another name.

**`pipx install` succeeds but `beril-X` is `command not found`**
pipx installed to a directory that isn't on `$PATH`. Run `pipx ensurepath`, then close and reopen your terminal. If that doesn't fix it, check `pipx environment` for the bin directory and add it to your shell's `PATH` manually.

**`beril-X configure` reports `adversarial: [absent]` but you installed it**
Cause is usually the wrapper-naming gap that bit us in v0.3.4.5: configure is looking for the wrong binary name. Run `which beril-adversarial` to confirm it's on `$PATH`. If it is and configure still says `[absent]`, your skill versions may be out of sync — re-run `pipx install --force` for both the adversarial skill and the producer skill (paper-writer / presentation-maker).

**`beril-X configure` reports `CBORG_API_KEY: missing`**
The presentation-maker configure step looks for `CBORG_API_KEY` in two places, in order: shell environment variables, then `BERIL_ROOT/.env`. If it reports missing, neither has it. Fix: confirm with your hub admin that `BERIL_ROOT/.env` contains a line `CBORG_API_KEY=...` (no quotes, no spaces around `=`). Do **not** echo the key in chat or paste it into the runbook.

**`beril-X draft` fails with `--beril-root or $BERIL_ROOT must be set`**
Two common causes:

- You typed `BERIL_ROOT=...` without `export`. Bash sets a shell variable but does NOT export it to subprocesses; the Python CLI sees a missing env var. Fix: use `export BERIL_ROOT=~/BERIL-research-observatory`, then re-run.
- You're not inside a BERIL checkout. The auto-detection walks up from your current directory looking for the BERIL markers (`.env`, `.claude/skills/`). Fix: `cd ~/BERIL-research-observatory` before running, or pass `--beril-root <path>` explicitly.

**Pipeline halts at "Pick a throughline (TL1 / TL2 / TL3):" with exit code 1 (Claude Code background task / TTY-less context)**
The presentation-maker pipeline currently uses an interactive prompt at stage 2 (throughline pick). In TTY-less contexts (Claude Code's Bash background tool, CI, headless daemons) the prompt's `read </dev/tty` fails. **Always pass `--auto-advance` for TTY-less runs** — auto-picks the first throughline candidate and runs end-to-end without prompting. State-driven gate-resume with explicit `--pick TLN` (the paper-writer pattern) is planned for presentation-maker v0.4.0 post-event; until then, `--auto-advance` is the right tool. Paper-writer is unaffected — its continue command already takes `--pick TLN` and does not depend on TTY for the throughline pick.

**Pipeline crashes mid-stage (network blip, malformed LLM JSON, CBORG rate limit)**
Don't re-run from scratch — you'll lose work and pay the full cost again. Instead:

```bash
beril-presentation-maker continue talks/draft_N
beril-paper-writer continue papers/draft_N
```

Both skills checkpoint per-stage. `continue` re-reads the stage state and picks up at the failed stage. Logs are under `<draft_N>/audit/stages/`.

**Schema mismatch error from `beril-adversarial review`** ("invalid schema_version" or "field X required")
All four skills must be at the pinned event-day versions; cross-skill contract drift between, say, paper-writer v0.6.x and adversarial v0.7.x will produce schema mismatches. Check versions: `beril-paper-writer --version`, `beril-presentation-maker --version`, `beril-adversarial --version`. Re-pipx-install the skill that's behind.

**"Old draft" clutter in `talks/` or `papers/`**
After several dry-runs, you'll have multiple `draft_N/` directories. Run `beril-presentation-maker prune talks/` (or `beril-paper-writer prune papers/`) to list and clean up old drafts.

**Output PowerPoint has visual issues (truncated title, overflowing references, weird Q&A layout)**
Known cosmetic issues, deferred to post-event releases. Open the `.pptx` in PowerPoint or LibreOffice and edit by hand. The skills will preserve manual edits under `audit/manual-edits/` on subsequent revise passes. See "Hand-editing the output" in [Part 6](#part-6-recovery--hand-editing).

**Adversarial review JSON parse error ("malformed JSON delimiter")**
LLMs occasionally emit JSON with unescaped quotes inside string values. The validator now catches and reports these with a diagnostic hint pointing at the likely cause (paragraph_quote field with embedded quotation). If you see this, the fix is to re-run the review (`beril-adversarial review ...`) — it's usually a one-off LLM mistake on retry. If it recurs on the same draft three times, file a bug with the failing JSON attached.

**Cost exceeded `--max-cost-usd` mid-run**
Pipeline halts gracefully at the next LLM call after the cap is reached. Resume options:

- Raise the cap and `continue`: `beril-X continue <draft_N> --max-cost-usd <higher>`.
- Accept the partial draft: the stages already completed are usable; `assemble` can build a deliverable from a partial pipeline state.
- Investigate why cost is high: `<draft_N>/working/stage_metadata.json` shows per-stage cost.

---

## Appendix B: Cost expectations and caps

| Skill / mode | Typical cost | Notes |
|---|---|---|
| `presentation-maker draft` (talk-30, STRONG, with image-gen + adversarial) | $5-20 | Image-gen and revise iterations are the swing. |
| `presentation-maker draft` (without image-gen, without adversarial) | $2-5 | Cheapest mode. |
| `paper-writer draft` (depth=standard, with canonical adversarial) | $5-15 | Verified against shipped v0.7.x trajectory. |
| `paper-writer draft` (depth=standard, `--no-adversarial`, fallback reviewer) | $4-10 | Cheaper; lighter review pass. |
| `paper-writer draft` (depth=deep, with canonical adversarial) | $10-25 | More revise iterations + broader literature checks. |
| `adversarial review` (standalone) | $0.50-2 | Single-pass review. |
| `atlas scan` (on a fresh corpus) | $5-10 | Cold-scan; only run once per major BERIL update. |

Caps you can opt into:

- `--max-image-cost-usd <N>` (presentation-maker) — hard cap per image. Default: prompt per image.
- `--auto-approve-images` (presentation-maker) — skips the per-image approval prompt. Combine with `--max-image-cost-usd` for non-interactive runs.
- `--max-cost-usd <N>` (paper-writer) — cumulative LLM-spend cap; pipeline halts gracefully on next LLM call after the cap is reached. Verified.

If you hit a cap, the pipeline halts gracefully and tells you which stage stopped. Resume with `continue` after raising the cap.

For event participants: the event organizer is not enforcing default caps. You can run unlimited; participants who want guardrails set them via the flags above.

---

## Appendix C: Where to go for more

For per-skill internals (architecture, prompts, runtime contracts, version history), each public skill repo has its own `SPEC.md`, `LAYOUT.md`, `CONTRACT.md`, `RELEASE_NOTES.md`, and `README.md`:

- [github.com/ArkinLaboratory/beril-paper-writer-skill](https://github.com/ArkinLaboratory/beril-paper-writer-skill)
- [github.com/ArkinLaboratory/beril-presentation-maker-skill](https://github.com/ArkinLaboratory/beril-presentation-maker-skill)
- [github.com/ArkinLaboratory/beril-adversarial-skill](https://github.com/ArkinLaboratory/beril-adversarial-skill)
- [github.com/ArkinLaboratory/beril-atlas-skill](https://github.com/ArkinLaboratory/beril-atlas-skill)

For BERIL itself:

- BERIL upstream: [github.com/kbaseincubator/BERIL-research-observatory](https://github.com/kbaseincubator/BERIL-research-observatory).
- KBERDL docs: [berdatalakehouse.github.io/kberdl-docs/](https://berdatalakehouse.github.io/kberdl-docs/).

This document currently lives at `docs/cross-skill/PARTICIPANT-RUNBOOK.md` in the `beril-presentation-maker-skill` repo as a pragmatic event-timing choice (no cross-skill umbrella repo exists yet). It will be relocated to a more neutral cross-skill location after May 7, 2026; the URL above will be updated to redirect.
