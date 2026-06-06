# beril-presentation-maker-skill

A scientific presentation drafter for BERIL analysis projects. Takes
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
| **[HANDOFF.md](HANDOFF.md)** | Production engineer inheriting maintenance | Production-team handoff: stable surface, what's deferred, ownership boundaries (production-side vs vendor-side), operational envelope, release cadence, escalation path. **Read first if you're inheriting ops.** |
| **[CONTRACT.md](CONTRACT.md)** | Integrator consuming this skill's output, or another skill (e.g., adversarial) being consumed by it | Cross-skill interop pinning: slide_spec.json schema as the consumer surface for the assemble step, adversarial reviewer schema dependency (v3), per-draft layout contract (deliverable / narrative / working / audit), backwards-compatibility fallback patterns. **Read this first if you're integrating.** |
| **[RELEASE_NOTES.md](RELEASE_NOTES.md)** | Anyone tracking changes | Version-by-version history. |
| **[SPEC.md](SPEC.md)** | Maintainer / contributor | Design intent: 14-stage pipeline, prompt versioning, slide_spec contract origin, image-gen calibration verdicts. |
| **[LAYOUT.md](LAYOUT.md)** | Maintainer | Directory and file organization, runtime contracts (file paths, exit codes, state-file shapes). |
| **[DECISIONS.md](DECISIONS.md)** | Schema designer / consumer wanting design rationale | Why the slide_spec / layout vocabulary / draft-zone partition look the way they do. |
| Cross-skill: **[`docs/cross-skill/PARTICIPANT-RUNBOOK.md`](docs/cross-skill/PARTICIPANT-RUNBOOK.md)** | Researcher using ANY of the 4 BERIL plug-in skills (paper-writer / presentation-maker / adversarial / atlas) | Hub workflow integration (`/berdl_start` → install → configure → run any skill), cohort cheat-sheets, recovery, cost. Hosted here for event timing; will relocate post-event. |
| Historical: [`archive/punch-lists/`](archive/punch-lists/), [`archive/runbooks/`](archive/runbooks/), [`archive/V0_4_ARCHITECTURE.md`](archive/V0_4_ARCHITECTURE.md) | Archaeology — per-cycle punch lists and runbooks (M1-V0_7), v0.4 architecture pivot doc | Each carries historical context for the cycle it was written for; relocated at v0.8.0 packaging. |
| Active: [V0_8_PUNCH_LIST.md](V0_8_PUNCH_LIST.md) | Operator state for the current release | Current v0.8.0 release-blockers + v0.8.1 carries. Replaced per-cycle as each release ships. |

## Status

**v0.8.0 — production-ready, hub-deployable.** Consolidates the
v0.4-v0.8 architecture/discipline/quality arc as a single
release. See [RELEASE_NOTES.md](RELEASE_NOTES.md#v080-2026-06-02--content-discipline--deterministic-layout-pass)
for the full per-decision narrative. Key v0.8.0 features:

- **Prompt stack v3.3** (opt-in via `--prompts-version v3.3`;
  default remains v2). v3 chain adds register discipline,
  figure-utilization contract, deck_close ownership,
  arc-transition support. Live-LLM smoke gate (D-076).
- **Tier G.10 deterministic layout pass** — bounding-box overlap
  detector (G.10-A) + geometry-aware fontScale that fixes the
  "touch the textbox to refit" symptom (G.10-B) + content_overflow
  finding emission with revise-loop routing (G.10-C).
- **Visual-QA mode-aware default-on** (D-096) for talk-30 STRONG
  + talk-15 STRONG/BRIEF. Opt-out with `--no-visual-qa`.
- **D-098 duplicate-deck_close fix** — root-caused as a
  prompt/architecture contradiction; two-layer fix (prompt
  rewrite + merger guard with D-098 warning).
- **AI image content-grounding** (D-097): DECK_POSITION input +
  intro-slide spoiler rule.
- **Curator figure-floor** (D-093): belt-and-suspenders for
  per-substory figure coverage.
- **install-skill ships smoke fixtures** + draft wrapper forwards
  the full v0.5-v0.8 flag surface (`--prompts-version`,
  `--resume-from`, `--revise-severity-floor`, etc.).

1946 unit tests passing (up from 726 at v0.3.4.4). v0.4
architecture pivot (parallel-compose) remains opt-in via
`--architecture-pipeline v0_4`. Default pipeline = v0_3
(sequential per-substory) + v2 prompts; existing v0.3.x runbooks
continue to work unchanged.

## What it does

Reads BERIL project artifacts and runs a multi-stage drafting
pipeline. v0.8.0 talk-30 STRONG runs through 17 stages (additional
stages relative to v0.3.x: `deck_close`, `visual_qa_final` +
optional 2nd revise pass per Tier G.7/G.8):

```
 1. plan.v1                   triage tier + scope                  ~$0.20
 2. throughline.v1            2-3 candidates → user picks          ~$0.25
 3. substory_design.v1        partition into substories            ~$0.20
 4. curate_figures            inventory + shortlist (Python)       ~$0
 5. citation_pool.v1          verify-by-resolution pool            ~$0.30
 6. cross_tenant.v1           KBase Lakehouse signal (optional)    ~$0-0.10
 7. intro.v1                  opening framing slides               ~$0.15
 8. slide_compose.v1          per-substory composition             ~$0.30-0.50
 9. qa_prep.v1                anticipated Q&A slides               ~$0.20
10. deck_close                closing-synthesis (talk-30 only)     ~$0.10
11. speaker_notes.v1          per-slide speaker notes              ~$0.20-0.40
12. image_gen                 concept_illustration → AI image      ~$0-0.50
13. merge_and_assemble        slide_spec + .pptx render            ~$0
14. adversarial_review        v0.7.0.8 v3 schema review            ~$0.50
15. revise_slides (1st pass)  review-rewrite loop (capped)         ~$0-5
16. visual_qa_final           overlap detector + visual-QA gate    ~$0.50
17. revise_slides (2nd pass)  VQ-only review loop (capped)         ~$0-2
```

Total typical: ~$3-6 on Sonnet for `talk-30 STRONG`. ~$8-15 if
both revise passes fire heavily.

Cost ceilings (configurable): `--max-revise-cost-usd` (default
$5.00 per revise pass), `--max-image-cost-usd` (default $0.50
cumulative), `--max-image-approvals` (default 4 per run).

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
# Run from BERIL_ROOT. In order: install package → verify CLI loads →
# deploy skill files into BERIL → bootstrap CRAFT runtime config.
cd <BERIL_ROOT>
pipx install --force git+https://github.com/kbaseincubator/beril-presentation-maker-skill.git@v1.1.0 \
  && beril-presentation-maker --version \
  && beril-presentation-maker install-skill . \
  && beril-presentation-maker configure .
```

For full operator runbook (prerequisites, troubleshooting, hub
deployment), see [HUB_INSTALL.md](HUB_INSTALL.md).

## Runtime configuration (provider + model tiers)

`configure` (above) wires `claude -p` to a CRAFT-contracted provider and is safe to
re-run when the environment changes (CRAFT-CONTRACT §3.4):

- **Provider** — `ACTIVE_PROVIDER` ∈ `anthropic | cborg | subscription` in
  `<BERIL_ROOT>/.env`; inferred from existing keys if unset, so an existing BERIL `.env`
  works unchanged.
- **Model tiers** — the skill maps its stages onto three tiers per the §3.4 default
  policy (`reasoning` for high-leverage framing + the review-incorporating synthesis,
  `standard` for high-volume composition, `fast` for classification/extraction/light
  review); `configure` pins a concrete model per tier into `.claude/settings.json` (no
  hardcoded ids). Override via `MODEL_{REASONING,STANDARD,FAST}` in `.env` or `--model`.
- **Image generation is separate** — an optional provider (CBORG-Gemini via the
  app-internal client, or `GOOGLE_AI_STUDIO_API_KEY`), NOT governed by `ACTIVE_PROVIDER`;
  absent → `image_gen` skips gracefully. One `CBORG_BASE_URL` serves both `claude -p`
  (bare host) and the image client (`/v1`, via `app_internal_base_url`).

See [HUB_INSTALL.md](HUB_INSTALL.md) §"Step 3 — Configure" for detail.

## Development

`pipx` (above) is the *skill install* path. To work on the code and
run the test suite, use a project-local virtualenv:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # full suite
```

Invoke the suite (and any helper) through `.venv/bin/python` **by
explicit path** — on macOS, bare `python3` / `pytest` resolve to a
PEP-668 system interpreter that lacks the project's deps, and `source
.venv/bin/activate` does not reliably persist across shells. The
`.venv/` directory is gitignored.

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
                          [--visual-qa]
                          [--no-review-cascade]
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
    ├── visual_qa.{json,md}     ← v0.4 M4a (opt-in --visual-qa); advisory
    │                             render-quality findings (5 defect classes)
    ├── review_cascade.{json,md} ← v0.4 M4b (auto-runs by default); tiered
    │                             review report (T1 deterministic + T2 Haiku
    │                             + T3 canonical adversarial)
    ├── review_tier2.{json,md}  ← v0.4 M4b Tier C output (read by cascade)
    ├── presentation_validation.json ← v0.4 M4b Tier B side-effect (P1-P10)
    └── revise_loop_metadata.json
```

### `--visual-qa` (v0.4 M4a Tier C, opt-in) — **read this section**

The visual-QA pass is **off by default** because it requires two
host-only deps (LibreOffice + Poppler) and adds ~$0.6–0.8 of vision-LLM
spend per run. You opt in because the renderer can ship a deck that
*validates* but renders poorly (a long subtitle that shrinks past the
60% floor, a diagram label that the shrink-to-fit can't save, a figure
caption that collides with the logo strip). Visual-QA catches that.

**When to use it:** before sharing the assembled deck with a real
audience. Run after assembly:

```bash
beril-presentation-maker draft <project_id> --visual-qa
# or, post-hoc on an existing draft:
.venv/bin/python <skill_path>/tools/visual_qa.py <draft_dir> --keep-pngs
```

**What it does:** renders the deck to per-slide PNGs via `soffice`
(`--headless --convert-to pdf`) → `pdftoppm` (`-png`), runs a
vision-capable `claude -p` (Sonnet 4.6) over them, writes advisory
`audit/visual_qa.{md,json}` with findings across **five defect classes**:

| Class | Catches |
|---|---|
| `container_breach` | text overflowing its box bounds |
| `element_overlap` | elements visibly colliding |
| `footer_or_title_collision` | body content into the logo strip / title band |
| `illegible_scale` | text too small to read at projection distance |
| `headline_body_mismatch` | title promises more/different than body delivers |

**Always rc=0; never blocks assembly.** Findings are advisory; the
revise loop and hand-edit pass own response. The M4b cascade reads
`audit/visual_qa.json` if present (per D-055) — opt in to visual-QA
to enrich the cascade's Tier-1 findings list.

**Requires** LibreOffice + Poppler on the host. Without them the
flag is a no-op with a stub report explaining what's missing —
**the skill ships portable** (no hard dep on either binary). Install
on macOS: `brew install --cask libreoffice && brew install poppler`.
Install on Linux: distro-appropriate `libreoffice` + `poppler-utils`
packages.

### Review cascade (v0.4 M4b, auto-runs)

After assembly, a three-tier review cascade orchestrates the
existing checks under one fail-fast contract. **Auto-runs by default**
(per D-054); opt out via `--no-review-cascade`.

| Tier | Cost | What it does |
|---|---|---|
| Tier 1 — deterministic | ~$0 | Aggregates P1–P10 validators + the three advisory checkers (`quantitative_grounding`, `no_artifact_refs`, `deck_reconciliation`) + `audit/visual_qa.json` if present (per D-055). Fail-fast: a P0 (P4 citation-pool or P5 brand-color violation; P3 is advisory per D-058) short-circuits Tier 2+3, saving ~$0.50+ of adversarial spend. |
| Tier 2 — Haiku narrative-light | ~$0.05 | Claude Haiku 4.5 reviews `slide_spec.json` + the narrative artifacts for four classes: `register_drift`, `qa_softball`, `unbacked_quantitative`, `substory_arc`. Always advisory (DQ4 / D-057); never gates Tier 3. |
| Tier 3 — canonical adversarial | ~$0.50–$1.50 | Wraps the existing `beril-adversarial review --type presentation` call. Lifts v3 findings + central_objection into the cascade JSON. Standalone `stage_adversarial_review` elides when cascade Tier 3 ran (de-dup; no double-spend). |

Output: `audit/review_cascade.{md,json}` with per-tier status,
findings, and `short_circuited_at`. The revise loop continues to read
`audit/adversarial_review.json` (which IS the cascade's Tier-3 output)
— no breaking change.

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
