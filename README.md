# beril-presentation-maker-skill

**Status:** v0.1.0-spec — specification only. No implementation yet.
The fourth in the BERIL drop-in skill quartet (atlas, adversarial,
paper-writer, presentation-maker).

Read in this order:

1. **[SPEC.md](SPEC.md)** — what the skill does and why. ~700 lines.
   Load-bearing for build trust.
2. **[LAYOUT.md](LAYOUT.md)** — package shape, CLI, output tree,
   prompts. ~350 lines.
3. **[DECISIONS.md](DECISIONS.md)** — numbered design decisions with
   rationale and rejected alternatives.

## What this skill does

Drafts a beautiful, evidence-grounded scientific presentation
(slide deck or poster) from a finished BERDL analysis project. KBase
brand. Reuses figures from the project (no fabrication). Generates
illustrative diagrams (workflows, conceptual schematics) procedurally
or via opt-in AI image generation. Produces speaker notes anchored to
notebook outputs and REPORT.md statements. Surfaces a Q&A prep
deliverable. Hands off to harsh review and revises iteratively.

Modes: `talk-30` (default), `talk-15`, `talk-45`, `lightning-5`,
`poster-h`, `poster-v`. Audience: scientific peer (v1).

## What this skill is NOT

- Not a journal-formatter or a vendor-template engine.
- Not a figure generator for quantitative content. Quant figures come
  from the project's `figures/` and notebook outputs only.
- Not a substitute for human authorship — slides need a presenter.
- Not a lay-audience translator (v1 targets peer audience; lay/program
  axes are v1.x).

## Install (planned — code does not yet exist)

```bash
pipx install git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git
beril-presentation-maker install-skill <BERIL_ROOT>
beril-presentation-maker configure
```

After install, slash command appears inside Claude Code at the
BERIL root:

```
/beril-presentation-maker [<project_id>] [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v]
                          [--throughline auto|interactive]
                          [--depth quick|standard|deep]
                          [--ai-diagrams off|opt-in]
                          [--ai-diagram-budget 5.00]
                          [--no-adversarial] [--no-stream]
                          [--max-rewrites N]
```

## Output

```
projects/<project_id>/talks/draft_N/
├── slides.pptx                    final deck (pptx)
├── slides.pdf                     only after `assemble --pdf`
├── speaker_notes.md               100–150 words/slide, evidence-anchored
├── qa_prep.md                     10 anticipated questions + answers
├── 00_throughline.md              chosen meta-arc + substory list
├── 01_outline.md                  slide-by-slide spec, human-reviewable
├── slide_spec.json                machine-readable, drives python-pptx
├── figures/                       curated subset of project figures
├── citation_pool.json             reused from paper-writer if present
├── notes_provenance.md            speaker-notes claims ↔ source
├── reframing_log.md               deviations from REPORT (auditable)
├── reviews/                       adversarial review outputs (if run)
├── audit/                         per-call streaming logs, costs
└── state.json                     stop/resume state
```

## Repo

- Source dev: `spike/beril-presentation-maker-skill-draft/`
- Remote: `https://github.com/ArkinLaboratory/beril-presentation-maker-skill` (planned)
- Tag `v0.1.0-spec` = spec-only; subsequent commits land code.

## License

MIT. See [LICENSE](LICENSE).
