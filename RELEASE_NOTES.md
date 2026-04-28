# beril-presentation-maker-skill — Release Notes

## v0.2.0 (2026-04-27) — first install-shippable release

The fourth skill in the BERIL drop-in quartet (atlas, adversarial,
paper-writer, presentation-maker) reaches install-shippable parity.
The 11-stage drafting pipeline that grew under earlier `v0.1.x-*` and
`v0.2.x-pipeline` tags now ships behind a real CLI: pipx-installable,
deployable into a BERIL checkout via `install-skill`, and invocable
through `/beril-presentation-maker` slash commands.

### What's in this release

**Drafting pipeline (11 stages, all wired):**

1. `plan.v1` — triage + scope.
2. `throughline.v1` — 2-3 candidates with evidence map + glyph
   discipline.
3. `substory_design.v1` — 2-4 substories with punchlines (word-cap
   audit advisory).
4. `curate_figures.py` — inventory + mode-bounded shortlist (figure
   captions from REPORT.md / notebook savefig context / filename).
5. `citation_pool.v1` — DOI/PMID-verified pool with 9-field discipline.
6. `cross_tenant.v1` — K-BERDL cross-tenant signal extraction
   (optional; when project spans multiple tenants).
7. `intro.v1` — opening framing fragment.
8. `slide_compose.v1` — per-substory composition over the 15-layout
   vocabulary.
9. `qa_prep.v1` — anticipated Q&A.
10. `speaker_notes.v1` — per-slide notes.
11. `merge_and_assemble` — fragment merge → validator (P1-P10) →
    `assemble_pptx` → `draft.pptx`.

**Render layer:**

- `assemble_pptx.py` against the shipped KBase-branded master template
  (`references/templates/kbase-presentation-master.pptx`), 15 named
  layouts.
- `slide_spec.py` validator (15 layouts × per-layout shape rules +
  diagram sub-schema with 7 node shapes and 3 edge kinds).
- `poster_fill.py` for `--mode poster-h` and `poster-v`.
- LibreOffice-backed PDF render for `--format pdf`.
- `diagram_render.py` + `repair_diagram_stubs.py` for boxes-and-arrows
  workflow diagrams.

**CLI surface:**

- `beril-presentation-maker --version`
- `beril-presentation-maker install-skill <BERIL_ROOT>`
- `beril-presentation-maker configure`
- `beril-presentation-maker draft <project>`
- `beril-presentation-maker continue <draft_dir> --resume-from <stage>`
- `beril-presentation-maker assemble <draft_dir> [--format pptx|pdf]`
- Slash commands: `/beril-presentation-maker` and
  `/beril-presentation-maker-continue`.

**Packaging:**

- pipx-installable (mirrors paper-writer / adversarial / atlas pattern).
- `install-skill` copies SKILL.md + commands/ + prompts/ + references/
  + tools/ into `<BERIL>/.claude/skills/beril-presentation-maker/`.
  Preserves install-local `state/` (never overwritten).
- Hatchling wheel target excludes bytecode + cache cruft + the
  smoke-named orchestrator copy.

### What changed since the v0.2.1-pipeline tag

- **Real CLI.** `cli.py` and `commands/` modules ported from
  beril-paper-writer-skill (install_skill, configure, draft,
  continue_run, assemble). Previously: all stubs raising
  `NotImplementedError`.
- **Real `discovery.py`.** Ported from paper-writer with
  `SKILL_DIR_NAME = "beril-presentation-maker"`. Includes the
  marker-set BERIL_ROOT walk-up + tiebreaker scoring.
- **Real `state.py`.** Lightweight read/write helpers; the orchestrator
  is canonical for state semantics in v0.2.0. Promote to a dataclass-
  based machine if scope grows.
- **Real `SKILL.md`.** Rewritten from the v0.1.0-spec stub to the
  full slash-command + workflow + artifacts description.
- **Slash command markdowns.** `commands/beril-presentation-maker.md`
  and `commands/beril-presentation-maker-continue.md` shipped.
- **Orchestrator rename.** `presentation_maker_smoke.sh` →
  `presentation_maker.sh` (header rewritten; smoke disclaimer dropped).
  The old filename is excluded from sdist + wheel; Adam will `git rm`
  it post-tag.
- **`figures/curated/` contract drift fixed.** `slide_compose.v1.md`
  changelog + `slide_spec.py` `_check_figure_path` validator that
  hard-rejects the deprecated path convention. 5 new unit tests in
  `test_slide_spec.py`. Live failure mode (draft_8 fig34..fig37
  shipping picture-less) verified fixed.
- **Polish batch from commit `7077849`** included: figure path
  fallback (#77), workflow_diagram coords (#78), divider word cap
  (#79), cross_tenant JSON conversion (#75).

### Known gaps (deferred to v0.3+)

- **Adversarial review-rewrite loop.** Depends on
  `beril-adversarial --type presentation` mode (not yet shipped in
  beril-adversarial-skill).
- **`ai_image_prompt.v1` wired as a stage.** Currently the prompt
  exists; the orchestrator stage that fills `concept_illustration.
  image_path = "{TBD}"` placeholders does not.
- **5 deck formatting bugs** observed on draft_8 walk:
  section_divider title at `left=-0.09 in` (master bug);
  data_figure caption + source TextBox undersizing;
  qa_anticipated body 3× capacity overflow (~36-40 wrapped lines vs.
  cap 12); methods_summary body overflow; workflow_diagram
  caption-row + Oval-10 overflow. Fixes target master-template +
  qa_prep / methods_summary word-budget enforcement.
- **Tier 7 mermaid diagrams.** Cross-skill backlog with paper-writer.

### Upgrade path

For a fresh BERIL deployment:

```
pipx install --force \
  git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git
beril-presentation-maker install-skill <BERIL_ROOT>
beril-presentation-maker configure
```

For an existing deployment that has any pre-v0.2 install of this
skill: re-running `install-skill --force` overwrites the shipped
subdirectories without touching `state/`. No data loss.

### Acknowledgments

- The figures-curated regression smoke test that started this
  conversation surfaced the prompt-vs-tool contract drift class of
  failures, now memorialized in
  `.auto-memory/feedback_prompt_tool_contract_drift.md`.
- The pipx-installable pattern mirrors beril-paper-writer-skill
  (Adam Arkin / Arkin Laboratory) and beril-adversarial-skill.
