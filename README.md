# beril-presentation-maker-skill

A scientific presentation drafter for BERDL analysis projects. Takes
a finished project (research plan, report, notebooks, figures,
optional adversarial review, optional paper-writer outputs) and
produces a beautiful, evidence-grounded slide deck (talk) or poster,
in KBase brand. Speaker notes, anticipated Q&A, citation pool, and
AI-generated illustrations for concept slides accompany the deck.

Distributed as a Claude Code skill that runs inside a BERIL
deployment. Sister skill to `/beril-adversarial` (harsh review),
`/beril-atlas` (corpus metrics), and `/beril-paper-writer` (manuscript
drafter). The fourth in the BERIL drop-in skill quartet.

> **For participants and BERIL users running any of the four skills end-to-end**,
> see [`docs/cross-skill/PARTICIPANT-RUNBOOK.md`](docs/cross-skill/PARTICIPANT-RUNBOOK.md).
> The runbook is a durable cross-skill walkthrough hosted here for event-timing
> reasons; it covers all four skills, BERIL workflow integration, cohort cheat-
> sheets, troubleshooting, and cost expectations. The README below is
> presentation-maker–specific.

## Documentation map

| Doc | Audience | What's in it |
|---|---|---|
| **[TUTORIAL.md](TUTORIAL.md)** | Researcher using `/beril-presentation-maker` on the BERIL hub | Skill-specific: output tree, reading `slide_spec.json`, the 16 layouts, image-gen approval flow, iteration patterns (revise vs re-run), hand-editing the `.pptx`, deferred cosmetic-issues hand-fix list, presentation-maker-specific troubleshooting. **Defers cross-skill install/configure to PARTICIPANT-RUNBOOK below.** |
| **[HUB_INSTALL.md](HUB_INSTALL.md)** | Operator deploying on JupyterHub | pipx install + install-skill + configure runbook, first-run validation, slash command verification, upgrading, uninstalling, hub-specific troubleshooting. |
| **[CONTRACT.md](CONTRACT.md)** | Integrator consuming this skill's output, or another skill (e.g., adversarial) being consumed by it | Cross-skill interop pinning: slide_spec.json schema as the consumer surface for the assemble step, adversarial reviewer schema dependency (v3), per-draft layout contract (deliverable / narrative / working / audit), backwards-compatibility fallback patterns. **Read this first if you're integrating.** |
| **[RELEASE_NOTES.md](RELEASE_NOTES.md)** | Anyone tracking changes | Version-by-version history. |
| **[SPEC.md](SPEC.md)** | Maintainer / contributor | Design intent: 14-stage pipeline, prompt versioning, slide_spec contract origin, image-gen calibration verdicts. |
| **[LAYOUT.md](LAYOUT.md)** | Maintainer | Directory and file organization, runtime contracts (file paths, exit codes, state-file shapes). |
| **[DECISIONS.md](DECISIONS.md)** | Schema designer / consumer wanting design rationale | Why the slide_spec / layout vocabulary / draft-zone partition look the way they do. |
| Cross-skill: **[`docs/cross-skill/PARTICIPANT-RUNBOOK.md`](docs/cross-skill/PARTICIPANT-RUNBOOK.md)** | Researcher using ANY of the 4 BERIL plug-in skills (paper-writer / presentation-maker / adversarial / atlas) | Hub workflow integration (`/berdl_start` → install → configure → run any skill), cohort cheat-sheets, recovery, cost. Hosted here for event timing; will relocate post-event. |
| Historical: [V0_2_0_PUNCH_LIST.md](V0_2_0_PUNCH_LIST.md), [V0_3_1_PUNCH_LIST.md](V0_3_1_PUNCH_LIST.md), [V0_3_3_ARCHITECTURE.md](V0_3_3_ARCHITECTURE.md) | Archaeology — design rationale for older releases | Each carries historical context for the version it was written for. |

## Status

**v0.3.4.4 — production-ready, hub-deployable.** Builds on:

- v0.3.0 — Stream A (revise loop + add_slide.v1) + Stream B
  (image_gen calibration; CBORG-Gemini at $0.014/image).
- v0.3.1 — BREAKING 4-zone draft layout (deliverable / narrative /
  working / audit).
- v0.3.2 — `data_table` layout (16th in production vocabulary).
- v0.3.3 — image-gen orchestrator stage (Channel A end-to-end:
  per-slide decision + ai_image_prompt + approval gate +
  image_client + manifest binding through merge).
- v0.3.3.1 — adversarial v0.7.0.1 schema migration
  (`central_objection` rename, `citation_reality` routing).
- v0.3.3.2 — image-gen efficiency (request-cache reuse +
  worst-case-cost recalibration).
- v0.3.4 — hub-readiness docs (SKILL.md rewrite + slash commands +
  HUB_INSTALL.md).
- v0.3.4.1 — `prune` CLI subcommand for cleaning up old drafts.
- v0.3.4.2 — `audit/runs/run-N/summary.json` + `audit/stage-metadata.json`
  consolidations via finalize_run.py + bash trap-EXIT hook.
- v0.3.4.3 — CONTRACT.md cross-skill interop pinning.
- v0.3.4.4 — README + RELEASE_NOTES rollup; pre-hub-install cleanup.

726 unit tests + 1 marker-gated live integration test, all passing.
Multi-project smoke + KBERDL hub install (#50) is the v1.0 gate.

## What it does

Reads BERDL project artifacts and runs a 14-stage drafting pipeline:

```
1.  plan.v1                  triage tier + scope                   ~$0.20
2.  throughline.v1           2-3 candidates → user picks           ~$0.25
3.  substory_design.v1       partition into substories             ~$0.20
4.  curate_figures           inventory + shortlist (Python)        ~$0
5.  citation_pool.v1         verify-by-resolution pool             ~$0.30
6.  cross_tenant.v1          K-BERDL signal (optional)             ~$0-0.10
7.  intro.v1                 opening framing slides                ~$0.15
8.  slide_compose.v1         per-substory composition              ~$0.30-0.50
9.  qa_prep.v1               anticipated Q&A slides                ~$0.20
10. speaker_notes.v1         per-slide speaker notes               ~$0.20-0.40
11. image_gen                concept_illustration → AI image       ~$0-0.50
12. merge_and_assemble       slide_spec + .pptx render             ~$0
13. adversarial_review       v0.7.0.1 v3 schema review             ~$0.50
14. revise_slides            review-rewrite loop (capped)          ~$0-5
```

Total typical: ~$2-4 on Sonnet for `talk-30 STRONG`. ~$5-7 if the
revise loop fires heavily.

The pipeline:
- Tiers project quality (STRONG / THIN / EXPLORATORY).
- Extracts 2-3 candidate scientific throughlines and surfaces them
  with evidence maps. The user picks (or `--auto-advance` picks TL1).
- Identifies critical analyses in REPORT.md, groups into 2-4
  substories with punchlines.
- Drafts slides per substory using a closed 16-layout vocabulary
  (`title`, `section_divider`, `big_idea`, `big_number`,
  `claim_evidence`, `two_column_compare`, `data_figure`, `data_table`,
  `workflow_diagram`, `methods_summary`, `concept_illustration`,
  `cross_tenant_integration`, `implications`, `acknowledgments`,
  `references`, `qa_anticipated`). Slide titles are punchlines, not
  topics.
- Reuses figures from `figures/` and notebook outputs verbatim — no
  fabrication of quantitative content.
- Generates AI illustrations for `concept_illustration` slides via
  CBORG-Gemini. Per-slide approval gate; calibrated $0.014/image;
  cumulative budget cap; "AI-generated illustration" disclosure
  footer.
- Writes 200-400-word speaker notes per slide, evidence-anchored.
- Builds anticipated Q&A slides for the back of the deck.
- Hands off to `/beril-adversarial --type presentation` for harsh
  review. Up to 6 P0 findings auto-revised in-loop (cost-capped at
  $5 default).
- Surfaces `citation_reality` findings (v3) for human verification —
  citations don't auto-revise.
- Final assembly renders `slide_spec.json` to KBase-branded `.pptx`.

The skill **pauses** at user-decision points and resumes via
`beril-presentation-maker continue <draft_dir> --resume-from <stage>`.
State lives on disk in the v0.3.1+ 4-zone layout under
`talks/draft_N/`. Each invocation creates a new numbered draft
directory. Old drafts are pruned via
`beril-presentation-maker prune <project_id>`.

## Install

```bash
# Run from BERIL_ROOT. Steps in order: install package → verify CLI loads →
# configure dependencies → deploy skill files into BERIL.
cd <BERIL_ROOT>
pipx install --force git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git@v0.3.4.4 \
  && beril-presentation-maker --version \
  && beril-presentation-maker configure \
  && beril-presentation-maker install-skill .
```

For full operator runbook (prerequisites, troubleshooting, hub
deployment), see [HUB_INSTALL.md](HUB_INSTALL.md).

## Usage

```
# Inside Claude Code on the hub:
/beril-presentation-maker [<project_id>]
                          [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v]
                          [--tier STRONG|THIN|EXPLORATORY]
                          [--audience peer]
                          [--auto-advance]
                          [--no-adversarial]
                          [--no-images] [--auto-approve-images]
                          [--max-image-cost-usd <n>]
                          [--image-allow-exploratory]
                          [--image-style <style>]
                          [--max-revise-cost-usd <n>] [--max-revisions <n>]
                          [--skip-assembly]
                          [--model <model_id>] [--no-stream]

# From the shell (operators / scripts):
beril-presentation-maker draft <project_id> [...]
beril-presentation-maker continue <draft_dir> --resume-from <stage> [...]
beril-presentation-maker assemble <draft_dir>
beril-presentation-maker prune <project_id> [--keep N] [--apply | --archive <path>]
```

For full reference (mode matrix, output artifacts catalog,
cost-control flag table, manual-edit workflow), see
[SKILL.md](src/beril_presentation_maker/skill/SKILL.md).

`<project_id>` auto-resolves on the hub via the 4-signal tree:
explicit arg → git branch (`projects/<id>` convention) → cwd →
ask user. Mirrors the adversarial v0.7.0.1 pattern.

## What it produces

```
projects/<project_id>/talks/draft_N/
├── deliverable/                ← what you open / present
│   ├── draft.pptx
│   └── draft.pdf (optional)
├── narrative/                  ← human-readable story (user-editable)
│   ├── 00_throughline.md
│   ├── 02_substories.md
│   └── references.md, bibliography.bib, citation_map.md
├── working/                    ← intermediate pipeline state
│   ├── slide_spec.json         ← machine-readable, drives python-pptx
│   ├── 03_slides/              ← per-substory compose fragments
│   ├── 04_speaker_notes/       ← per-substory speaker notes
│   ├── 05_image_decisions.json ← v0.3.3 image-gen decisions
│   ├── 05_image_requests/      ← v0.3.3 per-slide request JSONs
│   ├── 05_images/              ← v0.3.3 generated PNGs + manifest.json
│   ├── citation_pool.json      ← verified literature pool
│   ├── curated_figures.md      ← mode-bounded figure shortlist
│   └── next_actions.md         ← surfaced findings (citation_reality, etc.)
└── audit/                      ← provenance + debug history
    ├── state.json
    ├── cost-log.jsonl
    ├── stage-metadata.json     ← v0.3.4.2 consolidated per-stage metadata
    ├── stage-logs/
    ├── snapshots/              ← immutable spec snapshots
    ├── manual-edits/           ← preserved user edits to draft.pptx
    ├── runs/                   ← v0.3.4.2 per-invocation summaries
    │   └── run-N/summary.json
    ├── adversarial_review.{json,md}    ← v3 schema (v0.3.3.1+)
    ├── quantitative_grounding.{json,md}
    ├── image_provenance.json   ← v0.3.3 image-gen append-log
    └── revise_loop_metadata.json
```

Each invocation creates a new numbered draft directory. Decks are
versioned, not edited in place. v0.3.1+ 4-zone layout is stable
through v0.3.x; v0.3.0-shape drafts are non-migratable (clean break).

## How it fits into the BERIL workflow

```
  /berdl_start → (iterate within session) → /synthesize → REPORT.md
       │
       ▼
  /beril-adversarial               harsh project review
       │
       ▼
  /beril-paper-writer              draft manuscript (optional)
       │
       ▼
  /beril-presentation-maker        draft slide deck or poster
       │                                              ┌──────────────────┐
       ▼                                              │  reuse from      │
  user picks throughline;                             │  paper if present│
  approves substory clustering                ◄───────┤  (citation pool, │
       │                                              │   throughline)   │
       ▼                                              └──────────────────┘
  drafting (slides + speaker notes + Q&A
       │  + cross-tenant + AI illustrations)
       ▼
  /beril-adversarial --type presentation   harsh deck review (v3)
       │
       ▼
  revise loop (in-orchestrator, cost-capped)
       │
       ▼
  beril-presentation-maker assemble    → deliverable/draft.pptx
       │
       ▼
  (operator) beril-presentation-maker prune <project_id>  cleanup
```

## Status caveats

- v0.3.4.x reuses existing project figures verbatim for quantitative
  content — no figure regeneration. Conceptual illustrations are
  generated via opt-in CBORG-Gemini AI image-gen with per-image
  approval and a "AI-generated illustration" disclosure footer.
- v0.3.4.x has no journal-specific or vendor templates. KBase brand
  only. Vendor templates are post-MVP.
- v0.3.4.x audience is scientific peer only. Lay / program-officer /
  executive registers are post-MVP.
- AI-disclosure footnote is auto-emitted on slides with AI-generated
  images. Speaker name, affiliation, venue, date are placeholders the
  user must fill before delivery.
- `citation_reality` adversarial findings (v3 schema) are
  surfaced in `working/next_actions.md` rather than auto-revised —
  citations need human verification before shipping.
- Manual edits to `deliverable/draft.pptx` are preserved (archived
  to `audit/manual-edits/`) but not absorbed back into
  `slide_spec.json`. Edit upstream (`narrative/`) and re-run, or
  copy the deck out for separate polishing.

## See also

- [SKILL.md](src/beril_presentation_maker/skill/SKILL.md) — agent-facing
  skill instructions (slash commands, workflow, output artifacts)
- [HUB_INSTALL.md](HUB_INSTALL.md) — operator install runbook
- [CONTRACT.md](CONTRACT.md) — cross-skill interop pinning (schemas,
  CLI surface, versioning policy)
- [SPEC.md](SPEC.md) — community-facing design rationale
- [LAYOUT.md](LAYOUT.md) — internal architecture, CLI, package shape
- [DECISIONS.md](DECISIONS.md) — running log of design decisions
- [RELEASE_NOTES.md](RELEASE_NOTES.md) — per-version changelog
- [reference/](reference/) — supporting research: best-practice
  extract, KBase brand extract, prior-art scan, master-template
  source notes

## License

MIT. See [LICENSE](LICENSE).
