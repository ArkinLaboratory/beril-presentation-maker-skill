# beril-presentation-maker — JupyterHub install runbook

This is the operator runbook for deploying `beril-presentation-maker`
on a KBERDL JupyterHub user environment. It assumes the hub already
has BERIL installed at `<BERIL_ROOT>` (with `.claude/skills/`,
`projects/`, and `.env` containing `CBORG_API_KEY`).

For local dev install, see README.md.

For end-user docs (slash command usage, mode selection, polishing
workflow), see `src/beril_presentation_maker/skill/SKILL.md`.

## Prerequisites

The hub user environment must have:

1. **`pipx`** — for isolated installs of the package CLI.
2. **`claude` CLI** — Anthropic's Claude Code on PATH. The
   orchestrator invokes `claude -p` per pipeline stage.
3. **`BERIL_ROOT/.env`** with `CBORG_API_KEY=...` — for the
   `image_gen` stage. The orchestrator auto-loads this; never
   echoes the value.
4. **Read access to BERIL_ROOT/projects/** — at least one project
   with `REPORT.md`, `RESEARCH_PLAN.md`, `figures/`, `notebooks/`.
5. **Optional but recommended: `beril-adversarial`** v0.7.0.1+ —
   for the review-rewrite loop. Skip with `--no-adversarial` if
   absent.

Verify each:

```bash
which pipx                 # /opt/conda/bin/pipx or similar
which claude               # ~/.local/bin/claude or similar
ls "$BERIL_ROOT/.env"      # exists; contains CBORG_API_KEY
ls "$BERIL_ROOT/projects/" # at least one project_id
which beril-adversarial    # optional; v0.7.0.1+
```

## Install — three steps

### Step 1 — pipx install the package

From any cwd:

```bash
pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git
```

Alternative URL forms:

- **SSH (requires registered SSH key):**

  ```bash
  pipx install --force git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git
  ```

- **Specific version (recommended for production):**

  ```bash
  pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git@v0.3.4
  ```

Verify the install:

```bash
beril-presentation-maker --version    # should print 0.3.4 or later
```

### Step 2 — Deploy the skill into BERIL_ROOT

The `install-skill` subcommand copies the bundled SKILL.md, slash
commands, prompts, tools, and references into
`<BERIL_ROOT>/.claude/skills/beril-presentation-maker/`. Claude
Code auto-discovers skills under `.claude/skills/`, so this is
how the slash commands become available.

```bash
cd "$BERIL_ROOT"
beril-presentation-maker install-skill .
```

This will:

- Copy `SKILL.md`, `commands/*.md`, `prompts/*.md`, `tools/*.{py,sh}`,
  `references/templates/`, `references/slide_spec.schema.json` into
  `.claude/skills/beril-presentation-maker/`.
- Make `tools/presentation_maker.sh` executable.
- Skip if the destination is up-to-date (idempotent).

Verify:

```bash
ls "$BERIL_ROOT/.claude/skills/beril-presentation-maker/"
# Expect: SKILL.md, commands/, prompts/, tools/, references/
```

### Step 3 — Configure (verify dependencies)

```bash
beril-presentation-maker configure
```

This subcommand:

- Confirms `claude` is on PATH and reports the version.
- Confirms `python-pptx`, `Pillow`, `nbformat` are importable
  (these ride in the pipx venv from `pyproject.toml`).
- Reports CBORG_API_KEY status (set / not set in env / readable
  from `BERIL_ROOT/.env`).
- Reports adversarial CLI status (installed / version / has
  `review` subcommand).
- Does NOT make any LLM calls.

If any check fails, fix it and re-run. Common issues:

- **claude CLI missing:** install per Anthropic's docs; pipx-style
  install or system package.
- **`python-pptx` not importable:** re-run `pipx install --force`
  to rebuild the venv with all deps.
- **CBORG_API_KEY not found:** add to `BERIL_ROOT/.env`. The orchestrator
  reads it at startup; if absent, the `image_gen` stage will skip
  with `CBORG_API_KEY not set`.
- **adversarial CLI < v0.7.0.1:** upgrade or pass `--no-adversarial`
  on every run. v0.6.x produces v2 schema; presentation-maker
  consumes v3 in v0.3.4 (v2 still readable for forensic compat).

## First-run validation

Pick a small project for the first hub run. The recommended smoke:

```bash
cd "$BERIL_ROOT"
beril-presentation-maker draft <small_project_id> \
    --tier STRONG --mode talk-30 \
    --auto-advance \
    --no-adversarial \
    --auto-approve-images \
    --max-image-cost-usd 0.20
```

Expected:

- Wall clock: ~15-25 min on Sonnet.
- Cost: ~$2-4 (no adversarial; the loop is the variable
  cost-driver).
- Output: `<draft_dir>/deliverable/draft.pptx`.

Verify:

1. The deck file exists and is non-empty (>200KB typical).
2. `<draft_dir>/audit/` contains: `state.json`, `cost-log.jsonl`,
   `quantitative_grounding.{json,md}`, possibly
   `image_provenance.json`.
3. Open the deck in PowerPoint or Keynote — title slide + intro +
   substory dividers + content slides + acknowledgments +
   references should all render.

If anything fails:

- `audit/stage-logs/` has per-stage stdout/stderr.
- `audit/snapshots/slide_spec.raw.json` is the pre-validation merge
  output (useful when `slide_spec.json failed schema validation`).
- See `SKILL.md` "Pitfall detection" section for the broader
  protocol.

## Verifying the slash command

Inside Claude Code on the hub, the slash command should
auto-discover after install-skill. Type:

```
/beril-presentation-maker
```

The Claude Code agent should:

1. Verify `beril-presentation-maker --version` returns 0.3.4+.
2. Walk the 4-signal project resolution tree (explicit arg → git
   branch `projects/<id>` → cwd → ask user).
3. Confirm with the user before invoking.
4. Run the orchestrator in the foreground.
5. Surface the output and any adversarial / citation_reality
   findings.

If the slash command isn't recognized, check
`<BERIL_ROOT>/.claude/skills/beril-presentation-maker/SKILL.md`
exists and has the `user-invocable: true` frontmatter line.

## Upgrading

Re-run pipx install with the new version tag:

```bash
pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git@v0.3.x.y
beril-presentation-maker install-skill "$BERIL_ROOT"   # refresh skill files
beril-presentation-maker --version                      # confirm
```

The skill files in `<BERIL_ROOT>/.claude/skills/beril-presentation-maker/`
get refreshed to match the new package version. Existing draft
directories under `projects/<id>/talks/draft_N/` are unchanged
(forward-compat: v0.3.1+ layout is stable through v0.3.x).

## Uninstalling

```bash
pipx uninstall beril-presentation-maker-skill
rm -rf "$BERIL_ROOT/.claude/skills/beril-presentation-maker"
```

This removes the CLI and the skill files. Existing drafts under
`projects/<id>/talks/` are NOT touched — those are user-owned
artifacts.

## Troubleshooting

### "presentation_maker.sh not found in package data"

The pipx install is broken. Re-run:

```bash
pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git
```

### "PYTHON_BIN: command not found" or "missing python deps"

The orchestrator can't find a Python with the required deps. The
script auto-resolves the pipx venv's Python via the
`beril-presentation-maker` CLI's shebang. If `which
beril-presentation-maker` shows nothing, the install didn't
register. Re-run pipx install.

### "BERIL_ROOT does not contain .claude/skills/"

The orchestrator validates BERIL_ROOT at startup. Either:

1. Pass `--beril-root <path>` explicitly with the correct location.
2. Set `$BERIL_ROOT` env var.
3. cd into BERIL_ROOT before invoking.

### "CBORG_API_KEY not set"

The image_gen stage needs the key. Either:

- Add `CBORG_API_KEY=<key>` to `BERIL_ROOT/.env` (the orchestrator
  auto-loads it at startup).
- Export to shell env before running.
- Pass `--no-images` to skip the stage entirely.

### "image-gen worst-case $X > remaining budget $Y"

The `--max-image-cost-usd` cap is below the per-image bound.
v0.3.3.2 set worst-case at $0.05 (calibrated mean: $0.014/image).
Set `--max-image-cost-usd 0.10` or higher.

### "beril-adversarial review failed (rc=...)" / wrong schema

The adversarial CLI is missing or on a pre-v0.7.0.1 version.
Either:

- Install / upgrade:
  `pipx install --force git+https://github.com/ArkinLaboratory/beril-adversarial-skill.git@v0.7.0.1`
- Run with `--no-adversarial` to skip the review loop.

### "v0.3.0-shape draft is incompatible"

Pre-v0.3.1 drafts used a flat layout; v0.3.1+ uses 4-zone. There
is no migration tool. Either:

- Start a fresh draft via `/beril-presentation-maker`.
- Manually reorganize the old draft (move files into
  `deliverable/`, `narrative/`, `working/`, `audit/`).

## Hub-specific notes

- **CBORG vs Anthropic:** the hub uses CBORG (LBL gateway) for
  image generation. Text generation goes through whichever provider
  the user's `claude` CLI is configured for. The orchestrator
  doesn't manage Anthropic auth — that's `claude`'s concern.
- **Per-user storage:** drafts live under `projects/<id>/talks/`
  in the user's BERIL working tree, not in `~/.beril-*` or
  user-level state. Multiple users on the same hub stay isolated.
- **Concurrency:** the orchestrator allocates `draft_N` atomically
  via filesystem-level race-safety. Multiple parallel runs against
  the same project will get distinct draft directories.
- **Resumability:** `--resume-from <stage>` works across sessions
  and across pipx upgrades (within the same v0.3.x major). State
  is on-disk under `<draft_dir>/audit/state.json`.

## When to use each subcommand

| Subcommand | Use case |
|---|---|
| `beril-presentation-maker --version` | Sanity check |
| `beril-presentation-maker install-skill <BERIL_ROOT>` | One-time per hub deployment + after upgrade |
| `beril-presentation-maker configure` | One-time per hub deployment + after env changes |
| `beril-presentation-maker draft <project_id>` | Fresh draft from scratch |
| `beril-presentation-maker continue <draft_dir> --resume-from <stage>` | Resume / re-roll specific stages |
| `beril-presentation-maker assemble <draft_dir>` | Re-assemble .pptx from existing slide_spec.json (no LLM) |

End users on the hub will mostly use the slash commands
(`/beril-presentation-maker`, `/beril-presentation-maker-continue`)
inside Claude Code. The CLI subcommands are for operators,
scripted workflows, and recovery scenarios.
