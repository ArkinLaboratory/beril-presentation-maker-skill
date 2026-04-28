# beril-presentation-maker-skill v0.2.0 — release punch list

**Date:** 2026-04-27
**Goal:** Mark v0.2.0. First pipx-installable, install-skill-deployable
release of presentation-maker. Functional pipeline already at v0.2.1+,
this release closes the metadata + plumbing gap so a user can actually
`pipx install beril-presentation-maker-skill` and have the skill work.

## Tier A — CLI plumbing (UNBLOCKS B, C, D)

- [x] A1. Port `commands/install_skill.py` from paper-writer.
- [x] A2. Port `commands/configure.py` from paper-writer.
- [x] A3. Port `commands/draft.py` from paper-writer; wire to
  `presentation_maker.sh`.
- [x] A4. Port `commands/continue_run.py` from paper-writer.
- [x] A5. Port `commands/assemble.py` from paper-writer; wire to
  `assemble_pptx.assemble()`.
- [x] A6. Rewrite `cli.py` to dispatch to `commands/` modules.
- [x] A7. Replace `state.py` stub with the orchestrator-backed
  contract.

## Tier B — Skill artifacts (UNBLOCKS C, D)

- [x] B1. Rewrite `skill/SKILL.md` (currently a v0.1.0-spec stub).
- [x] B2. Create `skill/commands/beril-presentation-maker.md`.
- [x] B3. Create `skill/commands/beril-presentation-maker-continue.md`.
- [x] B4. Rename `presentation_maker_smoke.sh` →
  `presentation_maker.sh`; rewrite header.

## Tier C — Packaging hygiene + version bump (BLOCKED-BY A, B)

- [x] C1. Bump `pyproject.toml` version `0.1.0.dev0` → `0.2.0`.
- [x] C2. Bump classifier `2 - Pre-Alpha` → `3 - Alpha`.
- [x] C3. `cli.py` `--version` reads from package `__version__`.
- [x] C4. Add explicit `[tool.hatch.build.targets.wheel.exclude]`.
- [x] C5. Write `RELEASE_NOTES.md`.
- [x] C6. Document `git clean -fdx` cruft for Adam.

## Tier D — Verification (BLOCKED-BY A, B, C)

- [x] D1. Run `python -m build`; confirm wheel + sdist build clean.
- [x] D2. Inspect wheel contents; verify no cruft.
- [x] D3. Simulate pipx install via `pip install --target`.
- [x] D4. Run `install-skill <fake_beril>`; diff deployed tree.
- [x] D5. Re-run curated/ regression smoke against deployed skill.

## Tier E — Handoff (BLOCKED-BY D)

- [x] E1. Stage all changes; write `.commit-message-v0_2_0.txt`.
- [x] E2. Hand off to Adam to commit + tag `v0.2.0`.

## Recovery (post-incident, 2026-04-27)

A `git clean -fdx` on Adam's first ship attempt removed all the new
untracked files (commands/, skill/commands/, presentation_maker.sh,
RELEASE_NOTES.md, V0_2_0_PUNCH_LIST.md, .commit-message-v0_2_0.txt)
because the `-e` flag only excluded `reference/master-template-source/`,
not the new release artifacts. The .git/index.lock contention then
prevented `git commit`, but `git tag v0.2.0` succeeded — tagging the
old polish-batch commit `7077849` instead of the v0.2.0 release. The
bogus tag pushed.

Recovery actions (Adam's Mac shell):

```bash
cd /Users/aparkin/Documents/Claude/Projects/research-coscientist-dev/spike/beril-presentation-maker-skill-draft

# 1. Clean the orphan index.lock
rm -f .git/index.lock

# 2. Delete the bogus v0.2.0 tag (local + remote)
git tag -d v0.2.0
git push origin :refs/tags/v0.2.0

# 3. Verify the v0.2.0 files are restored (this conversation recreated them)
ls src/beril_presentation_maker/commands/
# Expected: __init__.py assemble.py configure.py continue_run.py draft.py install_skill.py
ls src/beril_presentation_maker/skill/commands/
# Expected: beril-presentation-maker.md beril-presentation-maker-continue.md
ls src/beril_presentation_maker/skill/tools/presentation_maker.sh
# Expected: present
ls RELEASE_NOTES.md V0_2_0_PUNCH_LIST.md .commit-message-v0_2_0.txt
# Expected: all present

# 4. Remove the smoke-named orchestrator copy
git rm src/beril_presentation_maker/skill/tools/presentation_maker_smoke.sh

# 5. Stage everything + commit + retag
git add -A
git commit -F .commit-message-v0_2_0.txt
git tag v0.2.0

# 6. Push
git push && git push --tags
```

Do NOT run `git clean -fdx` again until after the v0.2.0 commit lands.

## What's NOT in scope for v0.2.0

- Adversarial review-rewrite loop integration. Defers to v0.3.0.
- `ai_image_prompt.v1` wired as a stage. Defers to v0.3.0.
- The 5 deck formatting bugs from draft_8 walk. Defers to v0.2.x.
- Tier 7 mermaid diagrams. Cross-skill backlog with paper-writer.

## Fixed in this release (already landed pre-punch-list)

- The `figures/curated/` prompt-vs-tool contract drift, fixed earlier
  this conversation: slide_compose.v1.md changelog +
  `_check_figure_path` validator + 5 unit tests. Smoke verified 4
  pictures land on draft_8 slides 8/9/15/19.
- The polish batch (issues #75, #77, #78, #79) — figure path fallback,
  workflow_diagram coords, divider word cap, cross_tenant JSON
  conversion. Already at HEAD as commit `7077849`; staged for v0.2.0.
