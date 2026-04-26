# beril-presentation-maker-skill

A scientific presentation drafter for BERDL analysis projects. Takes a
finished project (research plan, report, notebooks, figures, references,
optional adversarial review, optional paper-writer outputs) and produces
a beautiful, evidence-grounded slide deck (talks) or poster, in KBase
brand. Speaker notes and a Q&A-prep deliverable accompany the deck.

Distributed as a Claude Code skill that runs inside a BERIL deployment.
Sister skill to `/beril-adversarial` (harsh review), `/beril-atlas`
(corpus metrics), and `/beril-paper-writer` (manuscript drafter). The
fourth in the BERIL drop-in skill quartet.

## Status

**v0.1 — specification only.** No drafting code. The spec, layout,
decision log, and reference extracts are checked in for community
review. Implementation begins after spec sign-off.

## What it does (one paragraph)

1. Reads the project artifacts; classifies project quality (strong /
   thin / exploratory) — same tiering as paper-writer.
2. Extracts 2–3 candidate scientific throughlines from the evidence
   and surfaces them with evidence maps. **The user picks** (or
   `--throughline auto`/`--throughline auto-from-paper` opts into the
   maker's / paper-writer's choice).
3. Identifies the *critical analyses* in REPORT and groups them into
   semantic clusters — substories. The user reviews and may split,
   merge, drop, or re-order. Mode capacity overflow halts the gate
   with three options (pick / escalate-mode / merge); critical
   analyses are never silently dropped.
4. Drafts slides per substory using a closed 15-layout vocabulary
   (title, divider, big_idea, big_number, claim_evidence,
   two_column_compare, data_figure, workflow_diagram, methods_summary,
   concept_illustration, cross_tenant_integration, implications,
   acknowledgments, references, qa_anticipated). Slide titles are
   punchlines, not topics.
5. Reuses figures from the project's `figures/` and notebook outputs
   only — no fabrication of quantitative content. Procedural diagrams
   (workflows, schematics) are generated in python-pptx native shapes.
   AI-generated conceptual illustrations (CBORG-Gemini) are opt-in
   with per-image approval and a "AI-generated illustration"
   disclosure footer.
6. Writes 100–150-word speaker notes per slide, evidence-anchored to
   notebook+cell or REPORT line via `notes_provenance.md`.
7. Builds a Q&A-prep deliverable: 10 anticipated peer-reviewer
   questions with concise answers and evidence pointers.
8. Generates a required cross-tenant integration section even when
   signal is minimal — quantification is best-effort from project-
   local artifacts (DB count, tenant count, sibling-project ref count).
9. Hands off to `/beril-adversarial --type paper` for harsh review
   (or a fallback inline reviewer if `beril-adversarial` is not
   installed). Up to 2 review-driven rewrite passes.
10. Optional final assembly step (`beril-presentation-maker assemble`)
    renders `slide_spec.json` into `slides.pptx` (and `slides.pdf` if
    LibreOffice is on PATH).

The skill **pauses** at user-decision points and resumes via
`beril-presentation-maker continue <draft_dir>`. State lives on disk in
`talks/draft_N/state.json`. Targeted post-assembled revision is
supported via `beril-presentation-maker revise <draft_dir>` (per-slide,
per-substory, per-speaker-notes, per-add-image scopes).

## Install (planned)

```bash
pipx install git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git
cd <BERIL_ROOT>
beril-presentation-maker install-skill .
beril-presentation-maker configure   # sanity-check claude + CBORG key + optional sibling skills
```

## Usage (planned)

```
/beril-presentation-maker [<project_id>]
                          [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v]
                          [--throughline auto|interactive|auto-from-paper]
                          [--depth quick|standard|deep]
                          [--ai-diagrams off|opt-in]
                          [--ai-diagram-budget USD]
                          [--no-adversarial] [--no-stream]
                          [--max-rewrites N]

beril-presentation-maker continue <draft_dir>
beril-presentation-maker revise   <draft_dir> --slide N|--substory ID|--speaker-notes-only N|--add-image N "<instruction>"
beril-presentation-maker assemble <draft_dir> [--format pptx|pdf]
```

`--mode talk-30` (default) produces a 30-minute peer-audience talk.
Other modes: `talk-15`, `talk-45`, `lightning-5`, `poster-h` (48×36 in
horizontal), `poster-v` (36×48 in vertical). Audience axis is
peer-only in v1; lay/program-officer/executive are post-MVP. See
SPEC §5.

`<project_id>` auto-detects from cwd if you're inside `projects/<id>/`.

## What it produces

```
projects/<project_id>/
├── README.md, RESEARCH_PLAN.md, REPORT.md, REVIEW.md, ADVERSARIAL_REVIEW_*.md
├── talks/
│   ├── draft_1/
│   │   ├── state.json                  ← stop / resume state, hashes, choices
│   │   ├── slides.pptx                  ← assembled deck (regen each pass)
│   │   ├── slides.pdf                   ← only after `assemble --format pdf`
│   │   ├── 00_throughline.md            ← chosen meta-arc + evidence map
│   │   ├── 01_outline.md                ← human-reviewable slide-by-slide spec
│   │   ├── 02_substories.md             ← substory list with punchlines
│   │   ├── slide_spec.json              ← machine-readable, drives python-pptx
│   │   ├── speaker_notes.md             ← 100–150 wd/slide, evidence-anchored
│   │   ├── notes_provenance.md          ← speaker-note claims ↔ source
│   │   ├── qa_prep.md                   ← 10 anticipated questions + answers
│   │   ├── cross_tenant_signal.md       ← discovered tenant/DB/project signal
│   │   ├── citation_pool.json           ← reused from paper-writer if present
│   │   ├── references.md, citation_map.md
│   │   ├── reframing_log.md             ← deviations from REPORT.md (auditable)
│   │   ├── throughline_candidates.md    ← rejected alternatives
│   │   ├── image_provenance.json        ← AI-gen prompts + costs + approvals
│   │   ├── figures/                     ← curated subset of project figures
│   │   ├── diagrams/                    ← procedural diagrams (Tier 2)
│   │   ├── ai_images/                   ← AI-generated images (Tier 3, if any)
│   │   ├── reviews/                     ← if beril-adversarial run
│   │   └── audit/                       ← per-call streaming logs, costs
│   ├── draft_2/                         ← next invocation creates new dir
│   └── poster_h_1/                      ← parallel structure for posters
```

Each invocation creates a new numbered draft directory. Decks are
versioned, not edited in place. `revise` modifies in-place within a
draft.

## How it fits into the BERIL workflow

`/berdl_start` opens an analysis session. The user iterates on
RESEARCH_PLAN.md and notebooks within that session, calling BERIL
skills (`/berdl-query`, `/berdl-discover`, `/berdl-minio`,
`/literature-review`, etc.) as needed. `/synthesize` then produces
REPORT.md.

```
  /berdl_start → (iterate within session) → /synthesize → REPORT.md
       │
       ▼
  /beril-adversarial               harsh project review
       │
       ▼
  /beril-paper-writer              draft manuscript (optional but recommended)
       │
       ▼
  /beril-presentation-maker        draft slide deck or poster
       │                                              ┌──────────────────┐
       ▼                                              │  reuse from      │
  user picks throughline;                             │  paper if present│
  approves substory clustering                ◄───────┤  (throughline +  │
       │                                              │   citation pool +│
       ▼                                              │   figures)       │
  drafting (slides + speaker notes + Q&A prep         └──────────────────┘
       │  + cross-tenant + diagrams + opt-in AI images)
       ▼
  /beril-adversarial --type paper  harsh deck review
       │
       ▼
  beril-presentation-maker continue (rewrite pass)  (×1 — hard cap)
       │
       ▼
  beril-presentation-maker assemble    → slides.pptx [ + slides.pdf ]
       │
       ▼
  (optional) beril-presentation-maker revise <draft> --slide N "..."
       │     (targeted per-slide / per-substory edits, no restart)
       ▼
  beril-presentation-maker assemble    → re-rendered .pptx
```

## Status caveats

- v1 reuses existing project figures only for quantitative content —
  no figure regeneration. Conceptual illustrations are generated
  procedurally (python-pptx native shapes) or via opt-in AI image
  generation (CBORG-Gemini) with per-image approval and a "AI-
  generated illustration" disclosure footer. See SPEC §8.
- v1 has no journal-specific or vendor templates (no Nature deck, no
  Cell talk, no conference poster grids beyond KBase's two). KBase
  brand only. Vendor templates are post-MVP.
- v1 audience is scientific peer only. Lay / program-officer /
  executive axes are post-MVP. See SPEC §1.3.
- v1 declines to compress critical analyses out of a tight talk
  silently. When mode capacity is exceeded, the substory-approval
  gate halts with three options (pick / escalate-mode / merge). See
  SPEC §4.2.1.
- AI-disclosure footnote is auto-emitted on the references slide.
  Speaker name, affiliation, venue, date are placeholders the user
  must fill before delivery.

## See also

- [SPEC.md](SPEC.md) — community-facing design rationale (the load-bearing doc)
- [LAYOUT.md](LAYOUT.md) — internal architecture, CLI, package shape
- [DECISIONS.md](DECISIONS.md) — running log of design decisions with dates
- [reference/](reference/) — supporting research: best-practice extract,
  KBase brand extract, prior-art scan, master-template source notes

## License

MIT. See [LICENSE](LICENSE).
