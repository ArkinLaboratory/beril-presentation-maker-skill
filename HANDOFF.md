# beril-presentation-maker-skill — Production-Team Handoff

**Status:** v0.8.1 shipped 2026-06-03. Tagged `v0.8.1` on
`ArkinLaboratory/beril-presentation-maker-skill`. Operator the
skill expects: BERIL deployment with `.claude/skills/`, `.env`
with `CBORG_API_KEY`, optional `GOOGLE_AI_STUDIO_API_KEY` for
image-gen.

**Reader:** production engineer inheriting maintenance + ops for
this skill. This doc tells you the surface you're taking on,
what's stable enough to depend on, what's known-deferred, and
where the support seams are.

For end-user docs see README.md / TUTORIAL.md / HUB_INSTALL.md.
For interop schemas see CONTRACT.md. For design rationale see
SPEC.md / LAYOUT.md / DECISIONS.md. For per-release narrative
see RELEASE_NOTES.md.

---

## 1. What this skill does + how it's shaped

A pipx-installable Python package that drops a Claude Code skill
into a BERIL deployment under `.claude/skills/beril-presentation-maker/`.
The skill drafts KBase-branded scientific presentations (talks +
posters) from BERDL analysis projects, running a 14-17 stage LLM
pipeline against the project's `REPORT.md`, `RESEARCH_PLAN.md`,
`figures/`, and `notebooks/`.

**Shape (immutable across v0.x):**

- Python package at `src/beril_presentation_maker/` ships skill
  data (prompts, tools, references, tests/fixtures) as package
  data via `importlib.resources`.
- `beril-presentation-maker install-skill <BERIL_ROOT>` copies
  shipped data into `<BERIL_ROOT>/.claude/skills/beril-presentation-maker/`.
- Bash orchestrator (`tools/presentation_maker.sh`) sequences the
  pipeline stages; each stage invokes `claude -p` for an LLM
  pass (substory_design, slide_compose, etc.) or runs a Python
  tool (curate_figures, citation_pool, validate_presentation).
- Per-draft output lives under `<BERIL_ROOT>/projects/<id>/talks/draft_N/`
  in a 4-zone layout: `deliverable/` (audience-facing pptx + speaker
  notes), `narrative/` (decisions + throughline), `working/`
  (slide_spec.json + intermediate fragments), `audit/` (logs,
  cost, review outputs).
- Default invocation: `beril-presentation-maker draft <project_id>`.
  Resumes: `--resume-from <stage> --draft-dir <draft_N>`.

**Cross-skill dependencies:**

| Skill | Version | Optional? | What this skill consumes |
|---|---|---|---|
| beril-adversarial | v0.7.0.8+ | Optional (`--no-adversarial` to skip) | `adversarial review --type presentation` for the review-rewrite loop |
| beril-atlas | (operational) | Optional | Observability; this skill doesn't depend on atlas at runtime |
| beril-paper-writer | v1.0.0+ | Optional | If a sibling `papers/draft_N/` exists, citation_pool reuses its citations (D-009 "reuse-from-paper") |

No other external service dependencies beyond Claude (Anthropic
or CBORG-gateway) for LLM + Google AI Studio OR CBORG-Gemini for
image-gen.

## 2. What's stable (depend on this)

The following surface is stable across v0.x and intended to remain
stable through v1.0:

### CLI

- `beril-presentation-maker install-skill <BERIL_ROOT>` — idempotent
  skill data deployment.
- `beril-presentation-maker configure` — environment + dependency
  verification (advisory; doesn't block).
- `beril-presentation-maker draft <project_id>` — full pipeline.
  Flag set: `--mode {talk-30,talk-15,talk-45,lightning-5,poster-h,poster-v}`,
  `--tier {STRONG,THIN,EXPLORATORY}`, `--prompts-version {v1,v2,v3,v3.1,v3.2,v3.3}`,
  `--architecture-pipeline {v0_3,v0_4}`, `--resume-from <stage>`,
  `--draft-dir <path>`, `--auto-advance`, `--no-images`,
  `--auto-approve-images`, `--max-image-cost-usd`,
  `--max-image-approvals`, `--max-revise-cost-usd`,
  `--max-revisions`, `--revise-severity-floor {P0,P1,P2}`,
  `--visual-qa`, `--no-visual-qa`, `--image-provider {auto,cbio,google-ai-studio}`,
  `--no-adversarial`, `--model <claude-model>`, `--no-stream`.

### File layout (the 4-zone draft contract)

```
<BERIL_ROOT>/projects/<id>/talks/draft_N/
├── deliverable/           # audience-facing
│   ├── draft.pptx
│   └── speaker-notes.md
├── narrative/             # decision artifacts
│   ├── 00_throughline.md
│   ├── 02_substories.md
│   └── ...
├── working/               # machine-readable intermediates
│   ├── slide_spec.json    # the canonical structured deck
│   ├── citation_pool.json
│   ├── 03_slides/         # per-substory compose fragments
│   ├── 04_speaker_notes/  # per-substory speaker notes
│   └── 05_images/         # AI-generated images + manifest
└── audit/                 # logs + cost + review
    ├── adversarial_review.{json,md}
    ├── review_cascade.{json,md}
    ├── content_overflow.json   # v0.8.0+
    ├── layout_overlaps.json    # v0.8.0+
    ├── visual_qa.{json,md}
    ├── visual_qa_final.{json,md}  # v0.8.0+
    ├── revise_loop_metadata.json
    ├── state.json
    └── snapshots/         # pre-revise spec backups
```

This contract has been stable since v0.3.1 (3+ months of operational
use). The `audit/*.json` artifacts are versioned schemas (see
`CONTRACT.md` §3 for shape pins).

### Schemas (per CONTRACT.md)

- **`slide_spec.v1`** — the canonical deck representation.
  17-layout closed vocabulary. Stable.
- **`adversarial-review-presentation.v3`** — consumer schema from
  beril-adversarial-skill. Pinned to v3 with `central_objection`
  rename + `citation_reality` routing.
- **`compose-fragment.v1` / `compose-fragment.v2`** — per-substory
  composer fragments. v2 is the v0.4 fused-notes shape.
- **`layout-overlaps.v1`** — deterministic overlap detector output
  (v0.8.0 G.10-A).
- **`content-overflow.v1`** — renderer-emitted overflow findings
  (v0.8.0 G.10-C).
- **`review-cascade.v1`** — tiered review aggregator output.

Adding fields to any of these is non-breaking. Adding or removing
keys or changing semantics requires a schema-version bump + dual
support window.

## 3. What's deferred (don't be surprised)

These are documented gaps the production team should know about.
None are blockers; all are documented as v0.9+ work.

### v0.8.1 Tier-H carries (cosmetic, hand-fixable)

- **Pre-v0.8.0 saved fragments may contain `---` artifact** —
  `working/03_slides/deck_close.json` from old drafts can have
  `forward_call: "---"` (an extractor bug from REPORT.md HR
  capture). v0.8.0's extractor fix prevents this on new drafts;
  old drafts may need a one-line hand-fix to `forward_call`.

### v0.9+ (real, not load-bearing)

These have been deferred across multiple v0.x cycles because
the load-bearing complaint kept shifting elsewhere. Each is real
work but none has been the operator's top complaint:

- **Per-arc figure clustering** (v0.7 carry). `relevant_figure_not_used`
  finding fires but doesn't enforce ARC-level figure placement.
- **Composer-side cross_tenant grounding omissions** (v0.7 carry).
  Advisory soft-warnings; the composer can be nudged to enumerate
  every K-BERDL DB explicitly.
- **Retraction-aware composer** / `discarded_results.md` filter
  (v0.5.1 carry). No recurrence in v0.6+ reads; defer until it
  surfaces again.
- **Compression / mode-budget heuristics** (v0.5.1 carry). Decks
  can overshoot the mode-N slide budget; advisory soft-warning
  surfaces this but no auto-compress path.

### v0.9+ (architectural — would need design)

These would be material new work, not incremental:

- **LLM-driven layout patches** (Tier G.10 scoping discussion).
  Defer until deterministic G.10-A overlap findings show what the
  geometric resolver can't handle. As of v0.8.1, most overlaps
  resolve via content_overflow → revise loop; the LLM-patch path
  may not be needed.
- **Real font-metrics text measurement** (replacing the heuristic
  `_AVG_GLYPH_WIDTH_RATIO`). Would require fonttools + PIL +
  actual font files in the wheel. Defer until heuristic
  miscalibration is the load-bearing complaint.
- **Multi-language support** (the master is Oxygen-family + the
  glyph-width calibration is tuned for English). Out of scope
  for v0.x.

## 4. Operational envelope

### Cost + wall-clock (typical talk-30 STRONG)

| Stage | Cost | Wall-clock |
|---|---|---|
| Setup (plan + throughline + substory_design + curate + citation_pool + cross_tenant + intro) | $1.50-2.50 | 15-25 min |
| Compose (slide_compose × N substories) | $0.50-1.50 | 4-8 min/substory; parallel on v0.4 |
| QA prep + deck_close + speaker_notes | $0.80-1.20 | 5-10 min |
| Image gen (multi-provider) | $0.10-0.20 | 30-90s per image |
| Merge + assemble + cascade + adversarial | $0.50-1.00 | 2-5 min |
| Revise loop (1st pass) | $0-5 (capped) | 5-15 min |
| Visual QA + 2nd revise pass | $0.50-3 | 5-15 min |
| **Total** | **$3-12** | **45-90 min** |

The `--max-revise-cost-usd` cap (default $5) is the primary cost
control; the revise loop short-circuits when it hits this OR
`--max-revisions` (default 6). Hub batch use should set
`--auto-advance --auto-approve-images` to skip interactive gates.

### Resource use

- ~1.5GB pipx venv (python-pptx + Pillow + nbformat + tenacity).
- ~2-3MB per draft (slide_spec.json + audit logs).
- ~500KB per AI-generated image (PNG, ~1024×768 typical).
- Renders cleanly on python 3.10+ (tested 3.10, 3.12, 3.14).
- No GPU required.
- LibreOffice (optional) for PDF export + visual-QA. The skill
  falls back to PPTX-only without it.

### Concurrency model

- Draft directories are allocated atomically (`projects/<id>/talks/draft_N`
  picks the next N via filesystem-level race-safe alloc).
- Multiple parallel runs on the same project get distinct
  `draft_N/` directories — no cross-contamination.
- No global state in the pipx install; per-user / per-hub-user
  isolation by filesystem layout.

### Failure modes + recovery

- **Pipeline halt:** the orchestrator writes `audit/state.json` on
  every stage transition; `--resume-from <stage> --draft-dir <path>`
  picks up where it stopped.
- **Adversarial CLI missing:** falls back to "skip review loop" with
  a warning. Operator can re-run with `--no-adversarial`.
- **Image-gen failure:** the per-image probe + provider auto-discovery
  catches most cases. Falls back to no-image rendering. Cost cap
  prevents runaway.
- **LLM output malformed (rare):** REPAIR_MODE-style bounded retry
  inside each stage. After 3 retries the stage fails + writes
  partial output to `audit/stages/<stage>/`.
- **slide_spec validation failure:** the validator emits structured
  ValidatorIssue findings with severity. Hard errors halt assembly;
  soft-warnings surface in `audit/presentation_validation.json` +
  the assembler banner but don't block.

## 5. What the production team owns vs. vendor-side

### Production team owns

- **Deployment** to the BERIL hub: pipx install from tag +
  `install-skill` invocation per host.
- **Per-tenant configuration:** `.env` setup, `CBORG_API_KEY` /
  `GOOGLE_AI_STUDIO_API_KEY` provisioning.
- **Operational monitoring:** wall-clock anomalies, cost drift,
  failure-mode trending (via `audit/runs/run-N/summary.json`).
- **First-line user support:** tutorial pointers, common
  configuration issues. `HUB_INSTALL.md` covers the
  troubleshooting basics.
- **Incident triage:** when the orchestrator halts, the audit
  artifacts under `<draft_N>/audit/` are the forensic surface.
  No special tooling needed — JSON files + stderr logs.
- **Version pinning:** when to upgrade pipx-installed version.
  Recommend pinning to the latest `v0.x.y` tag; bump deliberately
  per release-notes review.

### Vendor-side (this skill's maintainers) owns

- **Skill code maintenance** — bug fixes, schema migrations,
  cross-skill compat (especially when adversarial-skill upgrades).
- **Prompt engineering** — v3.x prompt-stack iteration, new
  layouts, content-discipline rules. Versioned via
  `--prompts-version` for safe rollout.
- **Image-gen provider integration** — Google AI Studio + CBORG
  multi-provider layer, calibration cost-caps.
- **New layout authoring** — additions to the 17-layout vocabulary
  require master-template work + validator updates + per-layout
  fill handler.
- **Cost-model recalibration** — image-gen worst-case + token
  estimates, drift from real-world hub use.

### Boundary (shared)

- **New audit artifact requests** — production team flags
  observability needs; vendor adds the artifact + schema-versions
  it. Recent example: `audit/content_overflow.json` (v0.8.0
  G.10-C) emerged from operator-visible regression patterns.
- **Production incident → reproducer** — production team forwards
  the failing draft directory; vendor reproduces + fixes. The
  4-zone layout makes this clean.

## 6. Release cadence + support contract

### Release cadence (vendor-side)

- **Patch releases (`v0.x.y`)** when a Tier-I read surfaces
  actionable carries. Roughly quarterly so far; faster when
  active development is happening.
- **Minor releases (`v0.x.0`)** introduce new pipeline stages,
  prompt-stack versions, or layout additions. Documented in
  RELEASE_NOTES.md before release.
- **Major release (`v1.0.0`)** is the production-handoff
  milestone (this document). Bumps imply a deliberate
  re-evaluation of stable surface.

### What "production-ready" means

- All 17-layout fill handlers are stable + tested.
- The 4-zone draft layout has been load-bearing since v0.3.1.
- 1967 unit tests passing as of v0.8.1.
- Multi-project tested: lanthanide_methylotrophy_atlas,
  ibd_phage_targeting, functional_dark_matter, conservation_vs_fitness,
  phb_granule_ecology, amr_pangenome_atlas (and earlier projects
  through the v0.3-v0.7 cycles).
- Cross-skill integration: paper-writer reuse path, adversarial v3
  schema, atlas observability all proven on hub deployments.

### What's NOT production-ready (escalation needed)

- Multi-user web wrap (the Agent SDK probe path). This skill is a
  CLI-style invocation; multi-tenant web service is out of scope.
- Non-English projects (calibration is English-only).
- Non-KBase brand templates (the master is KBase-branded; brand
  swap requires master rebuild).

### Escalation path

For production incidents:
1. Capture the failing `<draft_N>/audit/` directory.
2. File issue at
   `github.com/ArkinLaboratory/beril-presentation-maker-skill/issues`
   with the draft dir + reproduction command + invocation flags.
3. Vendor turn-around: P0 (next-day reproduction); P1 (next
   patch release); P2 (next minor release).

For feature requests:
1. Open issue with the operational need + a sample project that
   demonstrates the gap.
2. Vendor triages against the v0.9+ deferred list (§3).

## 7. Quick-start verification (for the production team)

After deploying to a hub:

```bash
# 1. Install verified
beril-presentation-maker --version    # should print 0.8.1+

# 2. BERIL deployment verified
beril-presentation-maker configure
# Expects: CBORG_API_KEY present, claude on PATH, python-pptx + Pillow
# importable, BERIL_ROOT/.claude/skills/ present.

# 3. Smoke run (small project, no adversarial, capped image cost)
cd "$BERIL_ROOT"
beril-presentation-maker draft <small_project_id> \
    --tier STRONG --mode talk-30 \
    --auto-advance \
    --no-adversarial \
    --auto-approve-images \
    --max-image-cost-usd 0.20
```

Expected:
- Wall clock 15-25 min, cost $2-4 (no adversarial).
- `<draft_dir>/deliverable/draft.pptx` exists + non-empty (>200KB).
- `<draft_dir>/audit/state.json` shows all stages reached "complete".
- Open the .pptx in PowerPoint/Keynote + verify title + intro +
  per-substory slides + acknowledgments render.

If any of these fail, escalate per §6.

---

*This document is the v0.8.1 handoff surface. Updates when material
changes affect the production-team-owned interface (CLI flags, file
layout, schemas, dependencies). Bump alongside RELEASE_NOTES.md
when those surfaces drift.*
