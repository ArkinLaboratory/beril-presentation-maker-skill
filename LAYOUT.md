# beril-presentation-maker-skill — package layout + CLI structure

**Date:** 2026-04-25 (initial); 2026-04-26 (this draft)
**Status:** v0.1 design specification, captured pre-implementation.
The skill has since shipped through v0.3.4.4. The package shape +
CLI structure described here are the load-bearing intent; for the
current production-state CLI surface see [CONTRACT.md](CONTRACT.md)
§4 (the canonical reference) and [README.md](README.md). Drift
between this document and shipped code is expected for the v0.3.x
trajectory; a v0.4 docs cycle will fold the actual production
state back into this file.

This document specifies the shape of `kbaseincubator/beril-presentation-
maker-skill`. The skill mirrors `beril-paper-writer-skill`'s pipx-
installable, ships-the-skill-as-package-data pattern. Read [SPEC.md](SPEC.md)
first for *what* the skill does and *why*; this document is *how* it's
packaged.

## 1. Repository tree (planned)

```
kbaseincubator/beril-presentation-maker-skill/
├── pyproject.toml                hatchling build, 4 runtime deps
├── README.md, LICENSE, .gitignore, .gitattributes
├── SPEC.md, LAYOUT.md, DECISIONS.md
├── reference/
│   ├── presentation-best-practice-extract.md   ← Naegle 2021 + ASP + UVa
│   ├── kbase-style-extract.md                  ← brand colors/type/contrast
│   ├── prior-art-scan.md                       ← scanned competitor decks
│   └── master-template-source-notes.md         ← how master is derived from .potx
├── src/beril_presentation_maker/
│   ├── __init__.py               __version__
│   ├── cli.py                    argparse: install-skill, configure,
│   │                             continue, assemble
│   ├── discovery.py              BERIL_ROOT (vendored from adversarial)
│   ├── state.py                  state.json schema + read/write/diff
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── install_skill.py      copies skill/ via importlib.resources
│   │   ├── configure.py          claude on PATH; CBORG key check;
│   │   │                         optional beril-adversarial check;
│   │   │                         optional LibreOffice check (PDF render)
│   │   ├── continue_run.py       resume a paused draft
│   │   └── assemble.py           slide_spec → pptx via python-pptx
│   └── skill/                    ships as package_data
│       ├── SKILL.md
│       ├── commands/             slash-command markdowns (.md per CLI verb)
│       │   ├── beril-presentation-maker.md
│       │   ├── beril-presentation-maker-continue.md
│       │   ├── beril-presentation-maker-assemble.md
│       │   └── beril-presentation-maker-configure.md
│       ├── tools/
│       │   ├── presentation_maker.sh    orchestrator (planned ~1200 lines)
│       │   ├── stream_progress.py       reused parser pattern from
│       │   │                            adversarial / paper-writer
│       │   ├── extract_cross_tenant.py  scans REPORT/PLAN/notebooks for
│       │   │                            tenant + DB + sibling-project signal
│       │   ├── curate_figures.py        figure selection by mode budget
│       │   ├── citation_pool.py         pool builder + reuse-from-paper
│       │   ├── diagram_render.py        slide_spec diagram → python-pptx
│       │   │                            native shapes (Tier 2)
│       │   ├── image_client.py          Multi-provider image-gen client
│       │   │                            (Tier 3, opt-in). v0.3.x ships CBORG
│       │   │                            (OpenAI-compat); M5b/D-062 adds
│       │   │                            Google AI Studio native :generateContent
│       │   │                            (`gemini-3-pro-image-preview` →
│       │   │                            `gemini-3.1-flash-image-preview` →
│       │   │                            `gemini-2.5-flash-image` chain per
│       │   │                            D-035-rev1). New `probe` subcommand
│       │   │                            resolves AI Studio model + caches at
│       │   │                            `audit/ai_image_gen_probe.json`
│       │   │                            (D-063 sidecar). D-064 hybrid fallback
│       │   │                            on probe failure (silent → CBORG if
│       │   │                            available; else loud-warning disable).
│       │   ├── poster_fill.py           poster template placeholder fill
│       │   ├── validate_presentation.py P1–P10 mechanized checks
│       │   ├── assemble_pptx.py         slide_spec.json → pptx
│       │   ├── draft_paths.py           4-zone per-draft path resolver (v0.3.1+)
│       │   ├── extract_methods.py       v0.4 M1: Methods-grounding AST scan
│       │   │                            (vendored from paper-writer)
│       │   ├── extract_claims.py        v0.4 M1: claim_inventory.tsv adapter
│       │   │                            (claude -p extract_claims.v1.md + validator)
│       │   ├── validate_claim_inventory.py  v0.4 M1: source_notebook validator
│       │   │                            (vendored; 0.2.0-stage3-tierI)
│       │   ├── phase0_reuse.py          v0.4 M1: Phase-0 reuse/originate helper
│       │   ├── parse_deck_outline.py    v0.4 M2: extract deck-outline fields
│       │   │                            from the enriched 02_substories.md
│       │   ├── worker_pool.sh           v0.4 M3: bounded-concurrency batch
│       │   │                            runner (parallel slide_compose)
│       │   ├── reconcile_deck.py        v0.4 M3: post-merge conflict checker
│       │   │                            (dup figure / dup headline / image budget)
│       │   ├── visual_qa.py              v0.4 M4a: opt-in visual-QA pass —
│       │   │                            renders deck via soffice + pdftoppm
│       │   │                            (host-only deps), runs vision claude
│       │   │                            -p over per-slide PNGs, writes
│       │   │                            advisory audit/visual_qa.{md,json};
│       │   │                            graceful no-op stub when deps absent
│       │   │                            (D-050, D-051)
│       │   ├── review_cascade.py         v0.4 M4b: tiered review cascade
│       │   │                            orchestrator. Auto-runs by default
│       │   │                            (D-054); opt-out via
│       │   │                            --no-review-cascade. Aggregates Tier 1
│       │   │                            (deterministic + opt-in visual-QA),
│       │   │                            Tier 2 (Haiku narrative-light), Tier 3
│       │   │                            (canonical adversarial wrapper).
│       │   │                            DQ4 / D-057: Tier-1 P0 ({P3, P4, P5})
│       │   │                            short-circuits. P3 was briefly demoted
│       │   │                            (D-058, M4b Tier E) pending the v0.4
│       │   │                            rewrite; restored M5a Tier C per D-059.
│       │   │                            Writes audit/review_cascade.{md,json}.
│       │   ├── review_tier2.py           v0.4 M4b Tier C: cascade Tier-2
│       │   │                            invoker. Pinned claude-haiku-4-5
│       │   │                            (~$0.05/run target); Read+Write tools
│       │   │                            only. Writes
│       │   │                            audit/review_tier2.{md,json}; same
│       │   │                            stub-report fallback pattern as
│       │   │                            visual_qa.py.
│       │   ├── revise_invariance.py     v0.4 M5a Tier A: post-edit semantic-
│       │   │                            invariance check for the revise verb
│       │   │                            (contract `revise-invariance.v1`).
│       │   │                            Five §13 invariants over pre/post
│       │   │                            slide JSONs: claim_id cross-walk
│       │   │                            (DQ1 heuristic per D-060; skipped+
│       │   │                            advisory when claim_inventory.tsv
│       │   │                            absent), citation preservation
│       │   │                            (insertions AND deletions forbidden),
│       │   │                            numeric preservation (multiset; reuses
│       │   │                            check_quantitative_grounding.extract_
│       │   │                            numbers), hedge level (per-slide
│       │   │                            aggregation per DQ2 / D-060), layout
│       │   │                            preservation. CLI rc=0 pass / rc=1
│       │   │                            fail per DQ3 / D-061 hard-reject.
│       │   │                            Invoked by revise_loop.py via subprocess
│       │   │                            between LLM post-edit and spec merge;
│       │   │                            writes audit/revise_invariance/<finding_id>.json.
│       │   ├── m6_score.py               v0.4 M6 Tier A: A/B cut-over scoring
│       │   │                            script. Consumes existing per-stage
│       │   │                            audit JSONs (no state.json — per D-067);
│       │   │                            aggregates 6 metrics over 2-project
│       │   │                            A/B (wall-clock from orchestrator
│       │   │                            timestamp delta per Tier A.1, NOT
│       │   │                            sum-of-stage-elapsed; cost from
│       │   │                            runs/run-N/summary.json; adversarial
│       │   │                            from adversarial_review.json with
│       │   │                            cascade Tier-3 fallback per Tier C.1,
│       │   │                            distinguishes malformed-vs-absent;
│       │   │                            validators from
│       │   │                            presentation_validation.json; metric 5
│       │   │                            Adam-subjective via --subjective-scores
│       │   │                            JSON; image budget from
│       │   │                            image_provenance.json). Applies D-065
│       │   │                            advisory rule (≥4/6 on target + ≥40%
│       │   │                            wall-clock); renders Markdown report
│       │   │                            with D-066 Adam-veto checkboxes.
│       │   │                            Regenerable on any 2-project A/B audit
│       │   │                            dir pair (useful for v0.5 ongoing
│       │   │                            benchmarking).
│       │   └── build_master.py          .potx → kbase-presentation-master.pptx
│       │                                (build-time, not runtime; M4a Tier E
│       │                                round 2 added the watermark-strip pass)
│       ├── prompts/
│       │   ├── plan.v1.md               Plan-phase: triage + throughline
│       │   │                            candidates + substory sketch
│       │   ├── throughline.v1.md        Detailed throughline candidate gen
│       │   ├── substory_design.v1.md    Per-substory punchline + slide map
│       │   ├── slide_compose.v1.md      Slide-by-slide layout + content (v0_3)
│       │   ├── slide_compose.v2.md      v0.4 M3: v0_4 composer — advisory deck
│       │   │                            brief + fused speaker notes (D-033/D-044)
│       │   ├── speaker_notes.v1.md      100–150 wd/slide, evidence-anchored (v0_3)
│       │   ├── qa_prep.v1.md            10 anticipated questions + answers
│       │   ├── citation_pool.v1.md      Lit-scan + reuse-from-paper
│       │   ├── cross_tenant.v1.md       Cross-tenant integration extraction
│       │   ├── reframer.v1.md           Detect drift from REPORT, log honestly
│       │   ├── diagram_design.v1.md     Generate slide_spec diagram entries
│       │   ├── ai_image_prompt.v1.md    Gen + critique prompts for Tier 3
│       │   ├── fallback_reviewer.v1.md  Inline reviewer if beril-adversarial absent
│       │   ├── rewrite.v1.md            Apply review-driven fixes to slides
│       │   ├── extract_claims.v1.md     v0.4 M1: claim extraction (vendored from
│       │   │                            paper-writer; consumed by extract_claims.py)
│       │   ├── deck_outline.v1.md       v0.4 M2: deck-outline call (enriched
│       │   │                            substory clustering — V0_4_ARCHITECTURE §20)
│       │   ├── visual_qa.v1.md          v0.4 M4a: vision-reviewer system prompt
│       │   │                            for tools/visual_qa.py — five defect
│       │   │                            classes (container_breach, element_overlap,
│       │   │                            footer_or_title_collision, illegible_scale,
│       │   │                            headline_body_mismatch); structured JSON
│       │   │                            output; advisory severity
│       │   └── review_tier2.v1.md       v0.4 M4b Tier C: Tier-2 reviewer system
│       │                                prompt — four detection classes per
│       │                                §8.1 (register_drift, qa_softball,
│       │                                unbacked_quantitative, substory_arc).
│       │                                Severities P1/P2 only (DQ4 / D-057:
│       │                                Tier 2 never gates Tier 3). v1 ships
│       │                                per DQ3 / D-056 ship-then-iterate;
│       │                                v2 expansion candidates documented at
│       │                                draft/audit/review_tier2_calibration.md
│       │                                after the M4b Tier-E live probe.
│       └── references/
│           ├── presentation-checklist.md  P-tier validators in detail
│           ├── kbase-brand-tokens.json    colors / fonts / sizes
│           └── templates/
│               ├── kbase-presentation-master.pptx     ← 15 named layouts
│               ├── kbase-poster-horizontal.pptx       ← 48×36 fill template
│               └── kbase-poster-vertical.pptx         ← 36×48 fill template
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_smoke.py                  v0.1.0-spec only (CLI parses)
    │   ├── test_discovery.py
    │   ├── test_install_skill.py
    │   ├── test_state_diff.py
    │   ├── test_validate_presentation.py  P1–P10
    │   ├── test_extract_cross_tenant.py
    │   ├── test_curate_figures.py
    │   ├── test_diagram_render.py
    │   ├── test_assemble_pptx.py          slide_spec → pptx round-trip
    │   └── test_build_master.py           .potx → master idempotency
    └── integration/
        ├── __init__.py
        ├── conftest.py                    fixture project (small synthetic)
        ├── fixtures/
        │   └── synthetic_project/
        │       ├── RESEARCH_PLAN.md
        │       ├── REPORT.md
        │       ├── notebooks/01_demo.ipynb
        │       └── figures/fig01_demo.png
        ├── test_full_run_talk_30.py       end-to-end with stubbed claude
        ├── test_full_run_lightning.py
        ├── test_full_run_poster_h.py
        └── test_image_gen_optional.py     opt-in image-gen, skip if no key
```

## 2. What ships vs. what runs

**Ships in the package (static, versioned):**

- Shell orchestrator `tools/presentation_maker.sh`
- Python helpers under `tools/` (extract_cross_tenant, curate_figures,
  citation_pool, diagram_render, image_client, poster_fill,
  validate_presentation, assemble_pptx, stream_progress, build_master,
  reconcile_deck, visual_qa, review_cascade, review_tier2,
  revise_invariance, m6_score)
- 15 versioned `.v1.md` system prompts under `prompts/`
  (incl. M4a `visual_qa.v1.md` + M4b `review_tier2.v1.md`)
- Reference rubric `references/presentation-checklist.md`
- Brand tokens `references/kbase-brand-tokens.json`
- Master + poster templates under `references/templates/`
- SKILL.md and slash command markdowns

**Runs at draft time (dynamic):**

- `claude -p` subprocess for each per-stage agent (Plan, Throughline,
  Substory, Slide-Compose, Speaker-Notes, Q&A-Prep, Cross-Tenant,
  Citation-Pool, Reframer, Diagram-Design, AI-Image-Prompt,
  Visual-QA opt-in, Tier-2 review)
- `python3` helper invocations for:
  - cross-tenant signal extraction
  - figure curation by mode budget
  - citation pool dedup + verification
  - diagram render (slide_spec → native shapes)
  - AI image gen (CBORG-Gemini, opt-in)
  - P1–P10 validators
  - hash-diff against `state.json` on `continue`
  - **M4b review cascade** (auto-runs by default per D-054; opt out
    via `--no-review-cascade`): orchestrates Tier 1 (deterministic
    + opt-in visual-QA) + Tier 2 (Haiku, ~$0.05) + Tier 3
    (canonical adversarial wrapper, ~$0.50–$1.50). Fail-fast on
    Tier-1 P0 (P4/P5; P3 demoted per D-058). The cascade replaces
    the standalone `stage_adversarial_review` invocation when
    cascade Tier 3 runs (de-dup via cascade JSON `tiers[2].status`
    read).
- `python-pptx` for slide_spec → .pptx (only at `assemble` step). Pure
  Python, no system pandoc / LibreOffice binary needed for .pptx.
- `LibreOffice` (system binary, optional) for `--format pdf` AND for
  the opt-in `--visual-qa` pass (M4a Tier C). If absent, both degrade
  gracefully (`--format pdf` emits pptx-only with a message;
  `--visual-qa` writes an advisory stub report and rc=0).
- `Poppler` `pdftoppm` (system binary, optional) for the `--visual-qa`
  pass — converts the LibreOffice-rendered PDF to per-slide PNGs that
  the vision LLM reads. Same degrade-gracefully posture as soffice.

Nothing about *what* the slides say is hardcoded in Python. The
Python layer is install + configure + state-diff + validators +
assembly + diagram-render + image-client. Slide content = shell +
prompts + claude subprocess + project artifacts.

## 3. CLI

```
beril-presentation-maker install-skill [<BERIL_ROOT>] [--force]
beril-presentation-maker configure
beril-presentation-maker continue <draft_dir> [options]
beril-presentation-maker revise   <draft_dir> [scope] "<instruction>"
beril-presentation-maker assemble <draft_dir> [--format pptx|pdf]
```

Scopes for `revise`:
`--slide N` | `--substory <id>` | `--speaker-notes-only N` |
`--add-image N` (Channel B AI-image-gen, §8.3).

Exit codes (mirrors adversarial / paper-writer): `0` success / `1`
user error / `2` runtime / `3` config.

`install-skill` copies `skill/` into
`<BERIL_ROOT>/.claude/skills/beril-presentation-maker/` via
`importlib.resources`. Preserves install-local `state/`. Sets +x on
`tools/*.sh` and `tools/*.py` after copy.

`configure` verifies:

- `claude` is on PATH.
- `CBORG_API_KEY` is set (env var or in `.env` at BERIL_ROOT, never read
  contents; only checks presence).
- `beril-paper-writer` is on PATH (warn if not — pool reuse disabled).
- `beril-adversarial` is on PATH (warn if not — fallback reviewer used).
- `soffice` (LibreOffice) is on PATH (warn if not — PDF render unavailable).
- `python-pptx` import works.
- Master template loads without errors via `python-pptx`.

`continue` is the resume-after-pause subcommand. Reads `state.json`,
hash-diffs source artifacts, reports new/changed files to user, then
proceeds with whatever phase was paused (throughline-pick, substory-
approval, AI-image-gen approval, review acceptance).

`revise` is the targeted post-assembled revision subcommand (SPEC
§16.5). Re-runs `slide_compose.v1` (or `substory_design.v1` +
`slide_compose.v1` for substory scope) over the named slide(s) with
the user's instruction prepended. Other slides untouched. Validators
P3–P10 re-run on the revised slides only. The revision instruction
+ resulting changes are recorded in `reframing_log.md`. Throughline
and substory-list edits are NOT permitted via `revise`.

`assemble` is the final pptx render step. Runs final P1–P10
validators, walks `slide_spec.json` via `tools/assemble_pptx.py`,
emits `slides.pptx`. With `--format pdf`, additionally invokes
`soffice --headless --convert-to pdf slides.pptx` if available.

## 4. Slash commands

```
/beril-presentation-maker [<project_id>]
                          [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v]
                          [--throughline auto|interactive|auto-from-paper]
                          [--depth quick|standard|deep]
                          [--ai-diagrams off|opt-in]
                          [--ai-diagram-budget USD]
                          [--no-adversarial] [--no-stream]
                          [--max-rewrites N]
                          [--substories N]
                          [--qa-slides] [--kbase-platform-frame]
                          [--allow-dense]
                          [--ignore-paper] [--ignore-figures]
                          [--notes-words N]

/beril-presentation-maker-continue <draft_dir>
/beril-presentation-maker-revise   <draft_dir> [--slide N|--substory ID|--speaker-notes-only N|--add-image N] "<instruction>"
/beril-presentation-maker-assemble <draft_dir> [--format pptx|pdf]
```

`<project_id>` auto-detects from cwd if inside `projects/<id>/`,
matching the `/berdl-review`, `/submit`, `/beril-adversarial`,
`/beril-paper-writer` pattern.

**Defaults:**

- `--mode talk-30` (the default talk).
- `--throughline interactive` (the load-bearing user gate). If
  paper-writer outputs are present, defaults shift to
  `--throughline auto-from-paper` (D-009).
- `--depth standard` (~25–45 min; quick is ~12–20, deep is ~50–70).
- `--ai-diagrams off` (D-005).
- `--ai-diagram-budget 5.00` (USD per draft).
- `--max-rewrites 2` (hard cap from SPEC §16.4).
- Adversarial review ON by default; `--no-adversarial` falls back to
  inline reviewer.

## 5. Output routing

Each invocation creates `talks/draft_N/` under the project directory.
`N` increments from existing draft directories. Drafts are immutable
within a directory (re-run with `continue` modifies in place; new
invocation creates `draft_{N+1}/`).

Posters write to `talks/poster_<orientation>_N/` (e.g.,
`talks/poster_h_1/`, `talks/poster_v_1/`).

Per-draft layout is the v0.3.1+ **4-zone** discipline
(`deliverable/` `narrative/` `working/` `audit/`) — the top level of
`draft_N/` has exactly four entries. The canonical source of truth
for every path is `tools/draft_paths.py` (`DraftPaths` +
`LAYOUT_SUBDIRS`); the tree below tracks it but `draft_paths.py`
wins on any disagreement. (This tree was refreshed 2026-05-14 from a
stale pre-v0.3.1 flat layout that had drifted out of sync; the
poster tree below may carry the same drift — not yet audited.)

```
projects/<project_id>/talks/draft_N/
├── deliverable/                       ← what the user opens / presents
│   ├── draft.pptx
│   ├── draft.pdf                      ←   only after assemble --format pdf
│   └── speaker-notes.pdf              ←   optional
├── narrative/                         ← human-readable story (user-editable between revisions)
│   ├── 00_throughline.md              ←   chosen meta-arc + evidence map
│   ├── 02_substories.md               ←   substory list with punchlines
│   ├── references.md                  ←   short-form, numbered, on-slide
│   ├── bibliography.bib
│   └── citation_map.md                ←   claim → reference index
├── working/                           ← intermediate pipeline state
│   ├── 00_phase0/                     ←   v0.4 M1: Phase-0 reuse/originate staging
│   │   ├── methods_provenance.md      ←     reused from papers/draft_*/ or originated
│   │   └── claim_inventory.tsv        ←     written by phase0_reuse.py (see V0_4_ARCHITECTURE.md §4.6)
│   ├── 00_plan.md
│   ├── 00_throughline_candidates.md   ←   rejected alternatives (audit)
│   ├── 03_slides/                     ←   per-substory compose fragments
│   ├── 04_speaker_notes/              ←   per-substory speaker notes
│   ├── 05_image_decisions.json        ←   v0.3.3 image-gen decisions
│   ├── 05_image_requests/             ←   v0.3.3 per-slide request JSONs
│   ├── 05_images/                     ←   v0.3.3 generated PNGs + manifest.json
│   ├── slide_spec.json                ←   machine-readable, drives python-pptx
│   ├── citation_pool.json             ←   reused from paper-writer if present
│   ├── cross_tenant_signal.{md,json}  ←   discovered tenant/DB/project signal
│   ├── curated_figures.md             ←   mode-bounded figure shortlist
│   ├── figures_inventory.md
│   ├── diagram_repair_report.md
│   └── next_actions.md                ←   surfaced findings (citation_reality, etc.)
└── audit/                             ← provenance + debug history
    ├── state.json                     ←   stop/resume state, hashes, choices
    ├── cost-log.jsonl
    ├── stage-metadata.json            ←   v0.3.4.2 consolidated per-stage metadata
    ├── phase0.jsonl                   ←   v0.4 M1: phase0_reuse + extract_claims invocation log
    ├── stage-logs/
    ├── snapshots/                     ←   immutable spec snapshots (+ 03_slides_pre_image_gen/)
    ├── manual-edits/                  ←   preserved user edits to draft.pptx
    ├── runs/run-N/summary.json        ←   v0.3.4.2 per-invocation summaries
    ├── adversarial_review.{json,md}   ←   v3 schema (v0.3.3.1+)
    ├── quantitative_grounding.{json,md}
    ├── image_provenance.json          ←   v0.3.3 image-gen append-log
    └── revise_loop_metadata.json
```

For posters:

```
projects/<project_id>/talks/poster_h_N/
├── state.json
├── poster_outline.md
├── poster_spec.json
├── figures/
├── citation_pool.json
├── poster.pptx
└── poster.pdf
```

## 6. state.json schema (informal)

Mirrors paper-writer with talk-specific phase additions:

```json
{
  "version": "0.1",
  "project_id": "functional_dark_matter",
  "draft_number": 1,
  "mode": "talk-30",
  "phase": "plan | throughline_pick | substory_approval | drafting | review | assembled",
  "throughline": {
    "candidate_id": "TL2",
    "chosen_at": "2026-04-26T14:32:00Z",
    "source": "user-pick | auto | from-paper-draft-1",
    "revision": 0,
    "artifact_hash_at_confirmation": "<sha256 of source artifacts>",
    "reevaluations": []
  },
  "substories": [
    {"id": "S1", "punchline": "...", "slide_budget": 8, "approved_at": "..."},
    {"id": "S2", "punchline": "...", "slide_budget": 10, "approved_at": "..."}
  ],
  "source_artifacts": [
    {"path": "REPORT.md", "sha256": "...", "mtime": 1714000000.0},
    {"path": "RESEARCH_PLAN.md", "sha256": "...", "mtime": ...},
    {"path": "notebooks/01.ipynb", "sha256": "...", "mtime": ...}
  ],
  "paper_writer_reuse": {
    "available": true,
    "draft_dir": "papers/draft_1",
    "throughline_used": true,
    "citation_pool_used": true,
    "figures_seeded": true
  },
  "ai_image_gen": {
    "enabled": false,
    "budget_usd": 5.00,
    "spent_usd": 0.00,
    "images_generated": [],
    "images_rejected_quant_content": []
  },
  "iteration": {"rewrite_passes": 0, "substory_approvals": 1},
  "cost_so_far_usd": 3.42,
  "elapsed_seconds": 1240,
  "validator_status": {
    "P1": "pass",
    "P3": "escalated",
    "P5": "user-fixed",
    "P10": "accepted-with-warning"
  }
}
```

`validator_status` enum: `pass`, `soft-warning`,
`accepted-with-warning`, `escalated`, `user-fixed`,
`accepted-as-limitation`. P-tier labels (`P1`...`P10`) match SPEC §13.

## 7. Per-stage prompt invocation contract

Same shape as paper-writer's per-section prompt invocation contract
(paper-writer LAYOUT.md §"Per-section prompt invocation contract"),
adapted for talk stages:

### 7.1 Drafting mode (default)

The stage prompt is invoked with the full input set. Each prompt:

- Reads its inputs (paths passed as arguments via the Write tool's
  user prompt).
- Drafts its output.
- Runs its own self-review checklist.
- Writes the output via the `Write` tool to the absolute path
  passed in.
- Emits a one-line closing message.

The stage prompt does NOT invoke the deck-level validators
(`validate_presentation.py` P1–P10). P1 (mode budget) and P7
(divider slides) cannot pass on a partial draft. The orchestrator
runs validators once after all stages complete, before the
adversarial-review loop and again at `assemble`.

### 7.2 REPAIR_MODE

After running `validate_presentation.py` and finding failures, the
orchestrator dispatches each failure to the relevant stage prompt
in REPAIR_MODE. Inputs in addition to drafting-mode set:

- `REPAIR_MODE` — `"true"`.
- `NAMED_VALIDATOR` — one of `P1`...`P10`.
- `VALIDATOR_OUTPUT_PATH` — file containing structured failure detail.
- `REPAIR_TARGET_PATH` — the file to modify (`slide_spec.json`,
  `speaker_notes.md`, etc.).

REPAIR_MODE behavior: read failure detail, fix only the named span,
re-write target, bounded retry (2 attempts/invocation). After 2
failures on same validator, halt with escalation per SPEC §13.

### 7.3 Validator → stage dispatch

| Validator | Stage prompt | Notes |
|---|---|---|
| P1 (mode budget) | (orchestrator) | Slide count concern; orchestrator re-allocates by adjusting substory budgets |
| P2 (time budget) | (orchestrator) | Same |
| P3 (numeric provenance) | `slide_compose.v1` or `speaker_notes.v1` | Whichever carries the unprovenanced claim |
| P4 (citation pool integrity) | `citation_pool.v1` (gap) or `slide_compose.v1` (drift) | |
| P5 (contrast) | (orchestrator) | Mechanical color swap from brand tokens |
| P6 (figure resolution) | (orchestrator or escalation) | Auto-fix unstretch; escalate regen |
| P7 (divider slides) | `substory_design.v1` | Substory-level structure |
| P8 (required slides) | (orchestrator) | Insert from boilerplate |
| P9 (no orphan citations) | (orchestrator) | Mechanical |
| P10 (density) | `slide_compose.v1` | Density is composition concern |

## 8. Path resolution

User prompts pass **absolute paths** for the Write target (lesson
learned from beril-adversarial — relative paths sometimes nest under
unexpected bases). Each per-stage subagent gets the absolute path of
the file it should write.

`presentation_maker.sh` derives BERIL_ROOT from its install path
(symlink-safe via `pwd -P`) and `cd`'s there before invoking claude.
Same pattern as paper-writer.

## 9. Stream-json parser + retry

Reuses the pattern from beril-adversarial / paper-writer:

- `tools/stream_progress.py` (cleanly forked; same programmatic Write
  verification + cost summary + sidecar log).
- Per-stage calls go through `invoke_claude_with_retry` (max 3 attempts).
- Exit 2 → retry with escalated prompt prefix; exit 3 → hard fail with
  `mv` recovery hint; other non-zero → hard fail with diagnostic.

Stream logs preserved per-stage under `audit/<stage>.stream.log` for
post-mortem.

## 10. BERIL_ROOT discovery

`discovery.py` resolves BERIL_ROOT identically to beril-adversarial
and beril-paper-writer (intentionally — single source of truth
pattern):

1. `--beril-root <path>` flag
2. `BERIL_ROOT` environment variable
3. Walk up from cwd looking for `.env` + `.claude/skills/` + at least
   one BERIL-core skill (`submit/`, `berdl/`, `suggest-research/`)
4. Fail loud with diagnostic naming which marker failed

May literally vendor `discovery.py` from beril-adversarial in v0.1;
factor to a shared dependency post-MVP if drift becomes an issue.

## 11. Tests (planned)

Initial target: ~30 tests across unit + integration. Modeled on
beril-adversarial's 29-test suite + paper-writer's 239-test target
(adjusted for less prompt-content surface).

- `test_smoke.py` — CLI parses, package imports (v0.1.0-spec, 7 tests).
- `test_discovery.py` — BERIL_ROOT resolution.
- `test_install_skill.py` — copy + executable-bit + state preservation.
- `test_state_diff.py` — hash-diff for resume; substory-list-affecting
  changes; throughline-affecting changes.
- `test_validate_presentation.py` — P1–P10 validators (each + edges).
- `test_extract_cross_tenant.py` — cross-tenant signal extraction
  from REPORT/PLAN/notebooks.
- `test_curate_figures.py` — mode-budget figure selection.
- `test_diagram_render.py` — slide_spec diagram → python-pptx shapes
  (golden-file comparison on shape count + layout key).
- `test_assemble_pptx.py` — slide_spec.json → pptx round-trip; layout
  names resolve in master; placeholder fills don't error.
- `test_build_master.py` — .potx → kbase-presentation-master.pptx
  idempotency; named layouts present; brand tokens applied.
- `test_full_run_talk_30.py` — end-to-end with stubbed claude.
- `test_full_run_lightning.py` — short-mode integration.
- `test_full_run_poster_h.py` — poster render path.
- `test_image_gen_optional.py` — opt-in image-gen; skip if no
  CBORG_API_KEY (CI).

Live-LLM tests not in CI (cost + brittleness). Image-gen tests
gated on `image_gen` pytest marker.

## 12. Cost / latency targets

(SPEC §17 has the full table.) Summary:

| Mode | Wall clock | Cost (default) |
|---|---|---|
| talk-30 (default) | 25–45 min | $4–$10 + adversarial + image-gen |
| talk-15 | 13–22 min | $2–$5 + adversarial |
| talk-45 | 35–60 min | $6–$13 + adversarial + image-gen |
| lightning-5 | 8–15 min | $1.50–$3 (no rewrite, no Q&A) |
| poster-h | 8–15 min | $2–$4 (no notes, no Q&A, no rewrite) |
| poster-v | 8–15 min | $2–$4 |

If approaching 2× upper bound on either dimension, fail loud with
checkpoint + user prompt to continue. Cost summary in
`audit/cost-summary.md` at end.

## 13. Master template build (build-time, not runtime)

`tools/build_master.py` is run once when authoring the master, and
ships the master `.pptx` as binary package data. It is NOT invoked at
draft time. The script:

1. Loads the user-supplied `KBase 2026 and beyond.potx` from
   `reference/master-template-source/` (gitignored — the .potx itself
   is a user-supplied input we do not redistribute; we ship the
   derived master only).
2. Extracts brand tokens (colors, fonts, logo positions) into
   `references/kbase-brand-tokens.json`.
3. Authors a clean master with 15 named layouts (per SPEC §6
   vocabulary) over the brand foundation.
4. Outputs `references/templates/kbase-presentation-master.pptx`.

Tests verify the master output is reproducible from the same inputs
(`test_build_master.py`). If brand updates land in a refreshed
.potx, the user re-runs `build_master.py` to regenerate the master.

The poster templates ship as-is from Adam's uploads (already KBase-
branded fill templates); no derived-master step needed for posters.

## 14. Image-gen client (opt-in; CBORG or AI Studio)

`tools/image_client.py` — provider-abstraction layer for AI-image-gen.
Two providers:

- **CBORG (v0.3.x baseline).** Endpoint `https://api.cborg.lbl.gov`,
  Bearer-auth via `CBORG_API_KEY`. Models: `google/gemini-pro-image`
  and `google/gemini-3-pro-image-preview` (OpenAI-compatible
  `/v1/images/generations` shape).
- **Google AI Studio (M5b / D-062).** Endpoint
  `https://generativelanguage.googleapis.com/v1beta`,
  `x-goog-api-key`-auth via `GOOGLE_AI_STUDIO_API_KEY`. Native Gemini
  `:generateContent` API. Honours the user's own AI Studio license
  per V0_4_ARCHITECTURE §14.1. Model fallback chain (D-035-rev1):
  `gemini-3-pro-image-preview` → `gemini-3.1-flash-image-preview` →
  `gemini-2.5-flash-image`. The model in use on a given draft is
  resolved by `image_client.py probe` (sidecar cache at
  `audit/ai_image_gen_probe.json`, D-063).

Provider precedence resolved by the orchestrator:
`--image-provider` CLI arg → `GOOGLE_AI_STUDIO_API_KEY` present
→ `CBORG_API_KEY` present → image-gen disabled. D-064 hybrid fallback
on probe failure: silent → CBORG if `CBORG_API_KEY` set; else
loud-warning disable for the run.

Common interface:

```python
class ImageClient:
    def generate(
        self,
        prompt: str,
        purpose: str,                # "workflow_diagram" | "conceptual_metaphor" | ...
        size: tuple[int, int],       # px
        budget_usd_remaining: float,
    ) -> ImageResult:
        """Returns ImageResult with bytes, model, cost, quant_content_score."""
```

`ImageResult.quant_content_score` is set by an LLM-as-judge follow-
up call: "does this image contain quantitative claims (axes labels,
numeric annotations, data values)?" Score >0.5 → caller rejects per
SPEC §8.3.

## 15. Coupling to beril-adversarial

Loose coupling, mirrors paper-writer LAYOUT §"Coupling to beril-
adversarial":

- The maker shells out to `beril-adversarial` if installed:
  ```bash
  beril-adversarial-cli --type paper "$DRAFT_DIR" 2>&1 | tee "$REVIEW_LOG"
  ```
- v0.1 uses `--type paper` (closest existing). v0.2 may add `--type
  presentation` upstream.
- `configure` warns at install time if beril-adversarial is not on
  PATH. Run-time fallback: `prompts/fallback_reviewer.v1.md`.

## 16. Coupling to beril-paper-writer

New coupling not in paper-writer's spec: the maker can reuse paper-
writer outputs.

- At plan phase, the maker checks for `papers/draft_*/` under the
  project. If present and complete, the maker:
  - Reads `papers/draft_N/00_throughline.md` for the chosen throughline.
  - Reads `papers/draft_N/citation_pool.json` for the pool.
  - Reads `papers/draft_N/figures/` for the seeded figure set.
- `--ignore-paper` opts out of all three reuses.
- `configure` reports paper-writer presence; absence is informational,
  not a warning.

## 17. Reviewer memory (learned-patterns)

`<BERIL_ROOT>/.claude/skills/beril-presentation-maker/state/learned-patterns.md`

Cross-project meta-memory of presentation patterns. Same convention as
beril-adversarial / paper-writer's learned-patterns. Examples:

- "Projects with `cross_tenant_signal == 0` are usually pure-tenant
  reanalyses; the cross-tenant slide should say so plainly."
- "When throughline auto-pick from paper-writer chooses a STRONG-tier
  arc but the talk mode is `lightning-5`, compress to one substory
  with the meta-arc as the slide title."

Read at start of plan phase; appended at end if a novel pattern
emerged. Install-local; never shipped.

## 18. Cross-platform

Python 3.10+. `pathlib.Path` everywhere. Bash 3.2-compatible (macOS
default), confirmed by `bash -n` syntax check. `.gitattributes`
enforces LF endings on `.sh`/`.py`/`.md`/`.toml`/`.json`. The assemble
step uses `python-pptx` (pure Python, lxml wheel). PDF render is
opt-in via LibreOffice (system binary, not bundled).

Windows users run under WSL or Git Bash; PowerShell parity not promised.

## 19. Deliverables this document blocks

1. Repo init: `gh repo create kbaseincubator/beril-presentation-maker-skill --private --clone`
2. Initial commit + tag `v0.1.0-spec` (spec + scaffold + smoke tests).
3. Master template draft authored + Adam reviews layouts.
4. After spec sign-off + master sign-off: implementation begins
   per LAYOUT (Phase 2 extractors, Phase 3 prompts, Phase 4 poster).
5. After live-test signoff: tag `v0.1.0` (full release).

## 20. Open questions for revisit

1. **Pandoc vs. python-pptx vs. python-pptx + LibreOffice for PDF.**
   Decided: python-pptx for pptx (pure-Python), LibreOffice for PDF
   (opt-in, system binary). Same trade-off as paper-writer's D-024.
2. **Figure regen at presentation resolution.** Paper-writer reuses
   figures as-is. Talks may need higher-res versions for projection
   (1080p+ at slide-fill). v1 leaves this to the user (figures go in
   at native resolution; P6 warns); v1.x could add a regen pass.
3. **Per-substory parallel slide composition.** Substories don't
   depend on each other after substory-design phase; could parallelize
   slide_compose. Saves wall-clock; adds orchestration complexity. v1
   sequential.
4. **Mermaid CLI as runtime dep.** Currently parses Mermaid into
   native shapes (no CLI). If shape complexity outgrows what we can
   render natively, add `mermaid-cli` as opt-in npm dep. v1.x.
5. **Pre-built prompt-corpus size.** 13 prompts may total ~3500–4500
   lines. Larger than paper-writer's 10/3000. May need prompt-
   compression pass before release if subagent calls hit context-
   window pressure.
6. **Adversarial `--type presentation`.** Defer to v0.2. Document the
   need so when the time comes the upstream change is small.
