# beril-presentation-maker — Decision Log

A running log of design decisions, with date, rationale, and (where
relevant) the alternatives that were considered and rejected. Future
spec revisions should append entries here rather than relitigate
settled questions silently.

Entry format: ID — date — short title. Body: decision, rationale,
alternatives considered, related SPEC/LAYOUT sections.

---

## D-001 — 2026-04-26 — Skill scope: peer-audience, single-project, talks + posters

**Decision:** v1 produces decks for a peer-audience talk (talk-30
default; talk-15, talk-45, lightning-5 variants) or a poster
(horizontal 48×36 in or vertical 36×48 in). Single-project only —
no cross-project synthesis decks like the Gazi 2026-and-beyond
example. Lay / program-officer / executive audiences are v1.x.

**Rationale:** Mirrors paper-writer's per-project scope (paper-writer
D-001). Cross-project synthesis is a different orchestration problem
(atlas-style discovery + harder narrative assembly); deferring keeps
v1 tractable. Adam confirmed peer-audience-only for v1 in scoping
conversation 2026-04-26.

**Alternatives considered:** (a) Multi-project synthesis from day
one — rejected as a 2× scope creep; the Gazi deck is a template
example for *style*, not for *scope*. (b) Lay/program audiences as
configurable axis from day one — rejected; tier-aware prompts (per
paper-writer SPEC §3.1) already absorb most of the variance, but
audience axis adds another dimension to every prompt and we don't
yet have peer-audience nailed.

**Related:** [SPEC](SPEC.md) §1.2, §1.3, §5.

---

## D-002 — 2026-04-26 (rev1: 2026-04-26) — User picks the throughline; substories are semantic clusters, not arbitrary count

**Decision:** Throughline selection AND substory-list approval are
the load-bearing user gates. The skill extracts 2–3 throughline
candidates with evidence maps, pauses for the user, then identifies
the critical analyses in REPORT and **groups them into semantic
clusters** (substories). The substory count emerges from the
clustering plus mode capacity, not from an arbitrary cap. The user
reviews and may split, merge, drop, or re-order substories at the
substory-approval gate. `--throughline auto` skips the first gate;
`--no-substory-pause` skips the second. Default is interactive on
both.

**Rationale (rev1, 2026-04-26):** Adam corrected the original
"1–3 substories" framing as too prescriptive and conceptually wrong.
Substories are *coherent clusters of related analyses*, not arbitrary
narrative beats. The discipline is to cover all critical analyses
in REPORT (no silent drops) and group them by sub-argument. Tighter
modes (lightning-5) force more aggressive grouping rather than
arbitrary count caps. The double-gate stays — both load-bearing —
but substory count is now a *result* of clustering + mode capacity,
not a parameter.

**Mode-capacity overflow:** when required_slides > mode_capacity, the
substory-approval gate halts and offers the user three options: pick
which substories to keep, escalate mode, or merge two substories
with acknowledged broader punchline. Default behavior never silently
drops a critical analysis. (D-027.)

**Alternatives considered:** (a) Single gate at throughline,
auto-substory — rejected; substory choice is too consequential to
delegate. (b) Auto-pick with user-veto on both — rejected; vetoes
require reading the alternative, which is more work than approving
from a slate. (c) [rev1, REJECTED]: capping substory count at 1–3 —
conflicts with "cover all critical analyses"; tight mode forces
grouping, not silent drops.

**Related:** [SPEC](SPEC.md) §4, §4.2, §4.2.1.

---

## D-003 — 2026-04-26 — Visual coherence is a first-class premise

**Decision:** "Visual coherence" is added to paper-writer's premise
list (paper-writer SPEC §2 has 5 premises: honesty, auditability,
user-judgment, bounded-cost, reuse-over-generation). The
presentation-maker has a 6th: visual coherence, ranked third (after
honesty and auditability, before user-judgment).

**Rationale:** Decks have a visual surface that papers don't.
Inconsistent visual styling — different fonts, sizes, layouts,
diagram styles across a deck — telegraphs sloppiness and makes the
science look sloppy. Paper-writer can punt on visual concerns
(Word's default IMRAD is fine). Presentation-maker cannot.

**Alternatives considered:** Treating visual coherence as an
implementation detail — rejected because it drives load-bearing
choices: own master template (D-007), named-layout vocabulary
(D-008), procedural diagrams over freeform (D-014), KBase style
guide as binding (D-015).

**Related:** [SPEC](SPEC.md) §2, §6, §14.

---

## D-004 — 2026-04-26 — Reuse existing project figures only for quantitative content

**Decision:** Quantitative figures (charts, graphs, anything with
data values) come from `figures/*.png` or notebook outputs only.
Generation, regeneration, and AI-touch-up of quantitative figures
are forbidden in v1. Illustrative diagrams (workflows, conceptual
schematics, before/after) are generated procedurally (Tier 2,
python-pptx native shapes) or via opt-in AI image gen (Tier 3,
non-quantitative metaphors only).

**Rationale:** Mirrors paper-writer D-004. Fabricating figures with
fake-but-plausible numbers is an existential failure mode. The
three-tier figure handling (SPEC §8) lets us be honest about what's
safe to generate.

**Alternatives considered:** (a) Allow re-rendering at higher resolution
for projection — partially valid; deferred to v1.x because we can't
guarantee the regen does not introduce visual edits that drift from
the source data. (b) Allow AI touch-up of charts (color adjustments,
axis label clarity) — rejected; same fabrication risk as full regen.

**Related:** [SPEC](SPEC.md) §8.

---

## D-005 — 2026-04-26 (rev1: 2026-04-26) — AI image-gen default OFF; two-channel control (global flag + interactive override)

**Decision:** Two channels control AI image generation:

- **Channel A (global flag).** `--ai-diagrams off | opt-in`, default
  `off`. Controls whether the LLM may **propose** AI illustrations
  spontaneously during slide composition. `opt-in` = LLM proposes,
  user still approves per-image.
- **Channel B (interactive override).** Regardless of Channel A's
  setting, the user may request `generate image for slide N:
  <prompt>` at any pause point or via the `revise --add-image N`
  CLI verb. Channel B bypasses the global flag but enforces all
  other constraints.

Common constraints (apply to both channels): per-image user-approval
gate; mandatory "AI-generated illustration" disclosure footer (8-pt
KBase-graphite-gray); LLM-as-judge validator forbidding quantitative
content; cost cap (`--ai-diagram-budget`, default $5.00 USD per
draft, hard-fail); provenance recorded in `image_provenance.json`
(includes channel A or B per image).

**Rationale (rev1, 2026-04-26):** Adam clarified that even with the
global flag off, the user should be able to request an AI image at
runtime. The original single-channel model conflated "default
behavior" with "user availability." Two-channel separates them:
default-off prevents the LLM from gratuitously proposing images
(bandwidth cost + quality variance), while interactive override
preserves the user's ability to use the capability when they want it.

**Alternatives considered:** (a) Default-on with override `--no-ai-
diagrams` — rejected; users may not notice ai images shipped on
slides they only skim. (b) Single-channel opt-in (no Channel B) —
rejected per Adam's feedback; constrains user agency. (c) Always-on
both channels — rejected; LLM proposing without restraint produces
deck-level visual cacophony.

**Related:** [SPEC](SPEC.md) §8.3, §8.3.1, §16.5; D-026 (revise verb).

---

## D-006 — 2026-04-26 — CBORG-Gemini is the default image-gen provider

**Decision:** Default model `google/gemini-pro-image` via CBORG
(`https://api.cborg.lbl.gov`, Bearer-auth via `CBORG_API_KEY`). Same
endpoint and key as text LLMs in this skill. Provider-abstraction
layer (`tools/image_client.py`) supports direct Google AI Studio or
OpenAI keys as alternatives, reserved for v0.2.

**Rationale:** Verified 2026-04-26: CBORG offers `gemini-pro-image`
and `gemini-3-pro-image-preview` via Google Vertex AI at $2 / $12
per M tokens. ChatGPT's `gpt-image-1` is NOT in CBORG's model list as
of that date. Gemini's image quality on conceptual diagrams is
generally regarded as strong (the "nano-banana" / Gemini 3 line). If
quality disappoints on real talks, v0.2 can route around CBORG via
direct keys.

**Alternatives considered:** (a) OpenAI gpt-image-1 default —
rejected, not available via CBORG; would require direct keys and
break the "everything goes through CBORG" pattern. (b) Multi-provider
voting — rejected as v1.x; adds cost without clear quality benefit
on conceptual illustrations.

**Related:** [SPEC](SPEC.md) §8.3; [LAYOUT](LAYOUT.md) §14.

---

## D-007 — 2026-04-26 — Ship a derived master template, not the user-supplied .potx

**Decision:** `kbase-presentation-master.pptx` ships as package data
under `skill/references/templates/`. The master is derived from
Adam's user-supplied `KBase 2026 and beyond.potx` by a build-time
script (`tools/build_master.py`) that:

1. Extracts brand tokens from the .potx (colors, fonts, logo
   placement).
2. Authors a clean master with 15 named layouts (per SPEC §6
   vocabulary) on top of the brand foundation.
3. Outputs the derived master.

The original .potx is NOT shipped in the package (it's a user-
supplied input, not redistributed).

**Rationale:** Inspecting the .potx revealed it has 32 layouts in 2
masters with auto-generated junk names (`TITLE_AND_BODY_1_1_1_1_1_1_1_1_1`),
and the actual Gazi deck uses only 3 of them, with all "fancy" slides
composed via freeform shape placement on top. This is a brand wrapper,
not a layout system. Generating a deck on the bare .potx forces
runtime shape composition with no consistent layout vocabulary —
fragile, ugly, and inconsistent across drafts.

**Alternatives considered:** (a) Edit the .potx in-place to add named
layouts — rejected; the .potx is Adam's source of truth and may be
re-exported from Google Slides; in-place edits would be lost. (b)
Author the deck against TITLE_AND_BODY freeform shape placement —
rejected; that's how Gazi did it for one deck and it's not
reproducible across many decks. (c) Ship the .potx unchanged and
inject layouts at runtime — rejected; runtime layout-injection is
high complexity for low payoff.

**Related:** [SPEC](SPEC.md) §14.1; [LAYOUT](LAYOUT.md) §13.

---

## D-008 — 2026-04-26 (rev1: 2026-04-26) — Closed slide-shape vocabulary (15 named layouts)

**Decision:** v1 ships exactly 15 named layouts: title,
section_divider, big_idea, **big_number** (D-029), claim_evidence,
two_column_compare, data_figure, workflow_diagram, methods_summary,
**concept_illustration** (D-028), cross_tenant_integration,
implications, acknowledgments, references, qa_anticipated. New
layout types require a DECISIONS.md entry and a master-template
update.

**Rationale:** Closed vocabulary means consistent visual style;
open vocabulary leads to one-off layouts that drift the brand. 15
covers the talk modes plus the two distinct slide kinds Adam called
out in spec review (rev1, 2026-04-26): big_number for headline
statistics ("90% accuracy", "27M scores") which differ visually from
big_idea (sentence-as-claim), and concept_illustration as the
designated home for AI-generated metaphor / infographic /
conceptual-diagram images (Tier 3, §8.3). Posters have their own
render path with separate templates (D-013).

**Alternatives considered:** (a) Open vocabulary with LLM picking
layouts — rejected per D-007 reasoning; LLM-chosen freeform layout
is exactly what we're avoiding. (b) Smaller vocabulary (e.g., 6
layouts) — considered; rejected because the cross_tenant_integration
slide is required (SPEC §7) and the qa_anticipated layout is
conditionally needed (SPEC §11.3) and consolidating them onto
generic content layouts would lose visual cues that audience members
need. (c) [rev1, REJECTED]: collapse big_number into big_idea —
rejected; visually distinct (huge centered numeric vs. sentence) and
prompt-construction is different. (d) [rev1, REJECTED]: three
separate layouts for metaphor / infographic / conceptual_diagram —
rejected; collapsed into one `concept_illustration` layout with
`style:` field in slide_spec. The placeholder positions are the
same; only the AI-prompt flavor differs (D-028).

**Related:** [SPEC](SPEC.md) §6; [LAYOUT](LAYOUT.md) §13.

---

## D-009 — 2026-04-26 — Reuse paper-writer outputs when present (default-on with opt-out)

**Decision:** If `papers/draft_*/` exists with a chosen throughline
under the same project, the maker defaults to:

- `--throughline auto-from-paper` (use paper's throughline; no
  re-extraction).
- Citation pool reuse from `papers/draft_N/citation_pool.json`.
- Figure budget seeded from `papers/draft_N/figures/`.

`--ignore-paper` opts out of all three.

**Rationale:** Saves a 3–8 minute literature-scan pass and keeps
narrative consistency between paper and talk for the same project.
Talks usually expand on the paper's claims with background and
implications context, so the citation pool is a starting set, not
a frozen final.

**Alternatives considered:** (a) Always opt-in to paper reuse —
rejected; reuse is the high-leverage default and users will forget
to set the flag. (b) Reuse pool but not throughline — rejected;
narrative drift between paper and talk is more confusing than helpful.

**Related:** [SPEC](SPEC.md) §3.2, §9.2.

---

## D-010 — 2026-04-26 (rev1: 2026-04-26) — Atlas is NOT a runtime input; we may borrow algorithms from atlas's source

**Decision:** The maker does not consume `~/.beril-atlas/runs/*`
output. Atlas data (citation graphs, sophistication scores,
research-line clustering) is project-corpus-wide; for a single-
project talk, none of those signals reduce work or improve content
in a way that justifies a runtime dependency. We **may copy and
adapt algorithmic code from atlas's source** (e.g., cross-author
edge classification, citation-graph parsing) into
presentation-maker if we need similar quantification — but the
maker runs that code over project-local artifacts only, never over
atlas's runtime output.

**Rationale (rev1, 2026-04-26):** Adam confirmed the decision and
clarified the source-borrow vs. runtime-dependency distinction.
"Atlas knows how" was meant as "atlas has working code we can copy,"
not "atlas should be a runtime input." The presentation-maker stays
independent and self-contained; if cross-tenant quantification needs
deeper signal (rare in v1), we adapt atlas's algorithm to operate
project-locally.

**Alternatives considered:** (a) Use atlas runtime output as a
backup signal for cross-tenant discovery — rejected per Adam's
correction; runtime dependencies between sibling skills are exactly
what we're avoiding. (b) Vendor atlas as a pip dependency — rejected;
even tighter coupling than the runtime-output approach.

**Related:** [SPEC](SPEC.md) §3.2, §3.3, §3.3.1.

---

## D-011 — 2026-04-26 — Cross-tenant integration is a required section, even if minimal

**Decision:** Every talk includes a cross-tenant slide section.
Slide budget is mode-dependent (1–2 slides for talk-30/45, 1 for
talk-15, optional speaker-notes-only for lightning-5, dedicated
panel for posters). If the project has zero cross-tenant signal, the
slide says so plainly: "All data sourced from `<tenant>`. This
project did not integrate across tenants."

**Rationale:** Cross-tenant integration is a KBase-platform-level
value proposition that should appear in every project's talk for two
reasons: (a) honest reporting of the project's data integration
shape, (b) institutional value framing for KBase audiences. The
no-signal fallback prevents fabrication while still acknowledging
the question. Adam confirmed required-section in scoping
conversation.

**Alternatives considered:** (a) Required only when signal is
non-zero — rejected; the no-signal case is itself informative
("this work did NOT integrate across tenants"). (b) Optional via
`--no-cross-tenant` flag — rejected; the flag would get used to
hide platform-level framing inconvenient to specific talks.

**Related:** [SPEC](SPEC.md) §3.3, §7.

---

## D-012 — 2026-04-26 — Speaker notes 100–150 wd/slide, evidence-anchored

**Decision:** Default speaker-notes length 100–150 words/slide for
talk-30/45. Lightning-5: 60 wd. talk-15: 100 wd.
`notes_provenance.md` companion file links every numeric claim and
every citation in notes to its source (notebook+cell, REPORT line,
or pool ref). Validator P-notes-provenance enforces.

**Rationale:** Notes are first-class output, not afterthought.
100–150 wd is "presenter could read aloud if they want; bullets if
they don't." The provenance discipline mirrors paper-writer's
methods_provenance pattern (D-003 there) — same rationale: fluent-
sounding speaker notes that cite hallucinated detail are dangerous;
the provenance file makes the trace explicit.

**Alternatives considered:** (a) Bullets-only notes — rejected;
fragile in a Q&A context where the presenter may need a sentence to
work from. (b) Full presenter manuscript (300+ wd/slide) — rejected;
nobody reads them, doubles cost.

**Related:** [SPEC](SPEC.md) §10.

---

## D-013 — 2026-04-26 — Posters are a separate render path, no animation, no notes

**Decision:** Poster modes (`poster-h`, `poster-v`) skip the slide-
compose pipeline entirely. They use a poster-fill script
(`tools/poster_fill.py`) that takes throughline + substories +
selected figures and writes directly into the placeholder positions
of `kbase-poster-{horizontal,vertical}.pptx`. No animation, no
speaker notes, no Q&A prep. Single-slide pptx output (also single-
page pdf).

**Rationale:** Posters are static deliverables. Forcing them through
the slide-compose pipeline (which assumes multiple slides) would
introduce bugs and complexity for no benefit. The two posters
templates are pre-positioned by Adam's design — we fill, we don't
reposition.

**Alternatives considered:** (a) Treat poster as 1-slide deck —
rejected; the slide-compose abstractions don't fit (no substory
dividers on a poster, no big-idea slide, etc.). (b) Custom poster
authoring DSL — rejected as scope creep; the existing fill-template
is sufficient.

**Related:** [SPEC](SPEC.md) §12, §15; [LAYOUT](LAYOUT.md) §5
(output routing for posters).

---

## D-014 — 2026-04-26 — Procedural diagrams via python-pptx native shapes (Tier 2)

**Decision:** Workflow / architecture / before-after diagrams are
generated as python-pptx native shapes (AutoShapes + Connectors +
TextBoxes), not as raster images, not via Mermaid CLI. Slide-compose
prompt produces a structured diagram description in
`slide_spec.json`; `tools/diagram_render.py` walks it into native
shapes.

**Rationale:** Native shapes are editable in PowerPoint/Keynote/
Slides — the user can move boxes, change colors, add annotations
without round-tripping through PNG. Raster diagrams freeze the
diagram at draft time and force re-renders for any tweak. Mermaid CLI
is a separate npm dependency we can't assume exists on remote BERIL
deploys.

**Alternatives considered:** (a) Mermaid CLI render to PNG —
considered; rejected as v0.2 enhancement only. (b) SVG → pptx import —
considered; rejected because python-pptx's SVG support is unreliable
and the lossy conversion produces ugly results. (c) Always
hand-author diagrams — rejected; defeats the skill's point.

**Related:** [SPEC](SPEC.md) §8.2; [LAYOUT](LAYOUT.md) §1
(`tools/diagram_render.py`).

---

## D-015 — 2026-04-26 — KBase style guide is binding for color and typography

**Decision:** All on-slide colors are drawn from the KBase primary
palette (microbe orange, grass green, freshwater blue, golden yellow,
spring green, ocean blue) and secondary palette (cyanobacteria teal,
lupine purple, frost blue, rainier cherry red, graphite gray) per
Style Guide June 2022. Body text in Oxygen (or Calibri fallback for
Google Slides), title text in Oxygen-Bold. Min 24-pt body, 36-pt
title. Contrast ≥ WCAG AA. Brand tokens shipped in
`references/kbase-brand-tokens.json` and are the single source of
truth for color/font selection.

**Rationale:** Brand discipline matters at platform-level. The KBase
brand is well-defined and deviating is sloppy. The brand tokens file
makes the palette accessible to validators (P5 contrast) without
parsing the style guide PDF.

**Alternatives considered:** (a) Allow user-supplied palette —
rejected; the skill is for KBase-branded output specifically. (b)
Loosely apply brand — rejected; "loosely applied" is "inconsistent"
in disguise.

**Related:** [SPEC](SPEC.md) §6.3 density discipline; [LAYOUT](LAYOUT.md) §1
(`references/kbase-brand-tokens.json`).

---

## D-016 — 2026-04-26 — python-pptx for assembly; LibreOffice optional for PDF

**Decision:** `tools/assemble_pptx.py` writes pptx via python-pptx
(pure Python, lxml wheel transitive). PDF render is opt-in via
`--format pdf`, which invokes `soffice --headless --convert-to pdf`
if LibreOffice is on PATH. If LibreOffice is absent, the assembler
emits pptx only and prints: "PDF render unavailable (LibreOffice not
found). Open slides.pptx in PowerPoint/Keynote and export to PDF
manually."

**Rationale:** Mirrors paper-writer's D-024 (python-docx, no system
binaries for the core path). Pure-Python pptx keeps pipx self-
contained. PDF is a less critical output (most talks ship pptx);
treating PDF render as optional avoids the deploy headache of
forcing LibreOffice on every BERIL system.

**Alternatives considered:** (a) Bundle a PDF renderer as a Python
dep — considered; rejected because the only viable Python PDF
renderers either require system binaries (weasyprint → cairo) or
produce ugly pptx-derived PDFs (custom rasterizer). (b) Defer PDF to
v0.2 entirely — rejected; users who have LibreOffice will be
disappointed if it's not used.

**Related:** [SPEC](SPEC.md) §14.3; [LAYOUT](LAYOUT.md) §3 (configure check
for soffice).

---

## D-017 — 2026-04-26 — Adversarial review uses paper type at v0.1; presentation type deferred

**Decision:** v0.1 calls `beril-adversarial --type paper` if the
sibling skill is on PATH (using the closest existing review type
even though the artifact is slides, not a manuscript). v0.2 will
add `--type presentation` upstream to beril-adversarial. Fallback if
beril-adversarial is absent: inline `prompts/fallback_reviewer.v1.md`.

**Rationale:** Mirrors paper-writer's D-... loose-coupling pattern
(the writer also ships before adversarial has paper-aware type
discipline; same trade-off). Adding `--type presentation` upstream
is a small change but it's a sibling-skill change and we want to
ship presentation-maker without a forced rev of adversarial.

**Alternatives considered:** (a) Add `--type presentation` to
adversarial in this PR — rejected; couples the release schedules. (b)
Skip adversarial integration in v0.1 and run inline only — rejected;
the real adversarial skill is consistently more useful and we
shouldn't gate users behind v0.2.

**Related:** [SPEC](SPEC.md) §18; [LAYOUT](LAYOUT.md) §15.

---

## D-018 — 2026-04-26 — Hard caps: 2 rewrites, $5 image-gen budget, 90-min soft wall-clock

**Decision:** Per-draft hard caps:

- 2 rewrite passes max (post-validator + post-adversarial).
- 1 substory-list approval round (re-running starts a new draft).
- $5.00 USD AI-image-gen budget per draft (overridable via
  `--ai-diagram-budget`).
- 90-minute wall-clock soft cap (warn at 90), 180-minute hard halt.

**Rationale:** Mirrors paper-writer's bounded-cost premise (paper-
writer SPEC §2 D-...). Without hard caps, LLM-driven loops drift
toward unbounded cost. The image-gen budget is set to 5 images at
the typical per-image cost ($0.30-1.00) — enough for a content-rich
deck but not a free-for-all.

**Alternatives considered:** (a) Cost cap only, no rewrite cap —
rejected; some failure modes loop on validator failures cheaply but
hours-long. (b) Hard halt at 90 min — rejected; some legitimate
deep-mode runs of talk-45 will exceed 90 min.

**Related:** [SPEC](SPEC.md) §16.4.

---

## D-019 — 2026-04-26 — Slide-shape vocabulary mandates big-idea slides at substory transitions

**Decision:** Each substory begins with a `big_idea` slide (single
sentence + supporting graphic). Non-negotiable. The slide-compose
prompt mandates it; validator P7 enforces. Punchline titles on every
content slide; validator flags titles that look like topics
("Methods", "Results", "Discussion", "Background").

**Rationale:** Naegle (2021) is unambiguous on this. Big-idea slides
at transitions give the audience a chance to refocus and mark the
pivot in the narrative. Topic titles on content slides waste a
sentence's worth of attention; punchline titles communicate the
slide's argument up front.

**Alternatives considered:** (a) Make big-idea slides optional —
rejected; they're optional precisely until they're missing, and
then the talk has no spine. (b) Allow topic titles for methods —
considered; rejected because "Methods" tells the audience nothing,
"Notebook AST extraction grounds Methods in code" tells them what
matters.

**Related:** [SPEC](SPEC.md) §6.1, §6.2, §1.4 (Naegle anchor).

---

## D-020 — 2026-04-26 — REPAIR_MODE for validator failures; bounded retry; escalation paths

**Decision:** When a validator (P1–P10) fails, the orchestrator
dispatches a REPAIR_MODE invocation to the relevant stage prompt,
following paper-writer's REPAIR_MODE pattern (paper-writer LAYOUT §
"REPAIR_MODE"). Bounded retry: 2 attempts per invocation. After 2
failures on the same validator, halt with one of four escalation
paths: auto-fix exhausted → user-modify, escalate-as-analysis-
request, accept-as-limitation, accept-with-warning (P10-only
mode-specific).

**Rationale:** Mirrors paper-writer's M-tier validator framework
(paper-writer SPEC §7.1.1). Bounded retry prevents validator-driven
infinite loops; escalation paths give the user agency without
forcing the skill to fabricate a fix.

**Alternatives considered:** (a) Auto-fix only (no escalation
paths) — rejected; some validator failures (P3 numeric provenance)
are irreparable without fabrication. (b) No retry — rejected; first-
shot prompts often fail on edge cases that a second-shot fixes.

**Related:** [SPEC](SPEC.md) §13; [LAYOUT](LAYOUT.md) §7.

---

## D-021 — 2026-04-26 — All slide content + speaker notes + Q&A in version-pinned prompts

**Decision:** All content-generating prompts are version-pinned
`.v1.md` files. Bumping `.v1.md` → `.v2.md` invalidates any cached
extraction or rendering keyed on prompt_version. Same convention as
beril-atlas / beril-adversarial / beril-paper-writer.

**Rationale:** Inherited convention. Prompt versions are the locus
of intelligence; version pinning enables idempotent re-runs and
clean cache invalidation.

**Alternatives considered:** None. Inherited.

**Related:** [SPEC](SPEC.md) §16.2; [LAYOUT](LAYOUT.md) §1
(prompts/*.v1.md).

---

## D-022 — 2026-04-26 — `talks/draft_N/` output tree; numbered drafts, immutable per directory

**Decision:** Each invocation creates `talks/draft_N/` under
`projects/<id>/`. `N` increments; existing drafts are immutable
(re-run with `continue` modifies in place; new invocation creates
`draft_{N+1}/`). Posters use `talks/poster_<orientation>_N/`
(parallel structure).

**Rationale:** Mirrors paper-writer's `papers/draft_N/` pattern.
Numbered drafts give users an audit trail of revisions; immutability
prevents silent overwrites that would lose user-edited intermediate
files.

**Alternatives considered:** (a) Single mutable `talks/current/`
directory — rejected; loses revision history. (b) `talks/<title>_N/`
with user-supplied title — considered; rejected for v1 because title
might not exist at plan phase.

**Related:** [LAYOUT](LAYOUT.md) §5.

---

## D-023 — 2026-04-26 — `discovery.py` vendored from sibling skills

**Decision:** `discovery.py` is vendored literally from
beril-adversarial / beril-paper-writer in v0.1. Single source of
truth for BERIL_ROOT resolution across the quartet. Factor out to a
shared dependency (e.g., a `beril-skill-common` pip package) post-
MVP if drift becomes an issue.

**Rationale:** Identical resolution logic across the four skills is
load-bearing. Vendoring keeps each skill self-contained while keeping
the logic synchronized at v0.1; if we factor too early, we add a
dependency edge before we know the abstraction is right.

**Alternatives considered:** (a) Factor immediately into
beril-skill-common — rejected; premature abstraction; we have 1
real consumer (this skill) so far. (b) Re-implement from scratch —
rejected; defeats single-source-of-truth.

**Related:** [LAYOUT](LAYOUT.md) §10.

---

## D-024 — 2026-04-26 — Phased build plan: scaffold → master → extractors → prompts → poster → release

**Decision:** Build phases:

- **v0.1.0-spec** (this commit) — pyproject + scaffold + CLI stubs +
  smoke tests + SPEC + LAYOUT + DECISIONS. No drafting code.
- **v0.1.0-master-draft** — author `kbase-presentation-master.pptx`
  with 15 named layouts; Adam reviews.
- **v0.1.0-extractors** — Phase 2 (mirror paper-writer Phase 2):
  extract_cross_tenant, curate_figures, validate_presentation
  (P1–P10), citation_pool reuse from paper-writer, build_master,
  diagram_render, image_client.
- **v0.1.0-prompts** — Phase 3 (mirror paper-writer Phase 3):
  13 prompts.
- **v0.1.0-poster** — poster-fill render path.
- **v0.1.0** — full release after live test on 1–2 BERIL projects.

**Rationale:** Mirrors paper-writer's phased build (Phase 1
scaffolding → Phase 2 extractors → Phase 3 prompts). Master-template
authoring is a one-shot that benefits from Adam's eyes BEFORE code
depends on layout names — pulling it forward to its own phase.

**Alternatives considered:** (a) Single big-bang implementation —
rejected; review surface too large. (b) Reorder to prompts before
extractors — rejected; prompts depend on extractor outputs as
context.

**Related:** [SPEC](SPEC.md) §19; [LAYOUT](LAYOUT.md) §19.

---

## D-025 — 2026-04-26 — Live-test target projects from paper-writer's validation set

**Decision:** v0.1.0 is gated on successful talk drafts for at
least 2 of: `functional_dark_matter` (STRONG), `cf_formulation_design`
(STRONG), `genotype_to_phenotype_enigma` (THIN). Same fixtures
paper-writer used in Phase 2 extractor validation.

**Rationale:** Same projects = same expected behavior surface =
fastest validation. STRONG-tier targets confirm the happy path;
THIN-tier confirms the "we cannot conclude X yet" framing works in
talk format.

**Alternatives considered:** (a) Different projects to broaden the
test set — considered; deferred to v0.2 because we know less about
those projects' artifact shapes.

**Related:** [SPEC](SPEC.md) §20.1.

---

## D-026 — 2026-04-26 — Targeted post-assembled revision via `revise` verb (per-slide / per-substory)

**Decision:** After a draft reaches `assembled` phase, the user may
request targeted revisions via a new CLI verb `revise` with scope
flags `--slide N`, `--substory <id>`, `--speaker-notes-only N`, or
`--add-image N`. Each scope re-runs the relevant prompt over the
named slide(s) or notes only, leaving everything else untouched.
Validators P3–P10 re-run on the revised slides only (skip P1, P2
since slide count is unchanged). The user's instruction + resulting
changes are recorded in `reframing_log.md`. Throughline and
substory-list edits are NOT permitted via `revise` (those require a
fresh draft via `continue --re-evaluate-throughline`).

**Rationale:** Adam pushed back on the original "not a real-time
editor" framing. Users will frequently want to tweak a slide ("more
biological detail," "tighten the punchline," "swap the figure for
fig08") without starting over. Per-slide and per-substory
granularity covers the common cases without inviting structural
churn. Hard cap of 1 retry per `revise` invocation per D-018.

**Alternatives considered:** (a) Free-form regex / multi-section
edits — rejected; too unbounded, easy to introduce inconsistencies
between revised and unrevised slides. (b) Allow throughline edits
via revise — rejected; that's a structural change that warrants
fresh substory + slide work, not a per-slide patch. (c) Defer
revision support to v0.2 — rejected per Adam's explicit feedback;
this is essential to the user experience.

**Related:** [SPEC](SPEC.md) §16.5; [LAYOUT](LAYOUT.md) §3
(revise CLI), §4 (revise slash command).

---

## D-027 — 2026-04-26 — Mode-capacity overflow halts at substory-approval gate (default: ask user)

**Decision:** When `required_slides > mode_capacity` at the
substory-approval phase, the orchestrator halts with three options
for the user: (a) pick which substories to keep / drop, (b)
escalate mode (e.g., talk-15 → talk-30), or (c) merge two
substories into one with explicit acknowledgment of broader
punchline. The skill never silently drops a critical analysis.

**Rationale:** Adam confirmed (i) halt-and-ask as the correct
default. Auto-escalating mode (option ii in the offered set) is too
surprising — the user picked talk-15 for a reason. Auto-merging
(option iii) is too aggressive — merging analyses with different
sub-arguments produces incoherent substories. The user's judgment
on which sub-arguments matter most is the right place to put the
decision.

**Alternatives considered:** (a) Auto-escalate mode silently —
rejected per above. (b) Auto-compress with warning — rejected;
mergers without user judgment produce muddy talks.

**Related:** [SPEC](SPEC.md) §4.2.1; D-002 (rev1).

---

## D-028 — 2026-04-26 — `concept_illustration` is one layout with `style` variants

**Decision:** AI-generated conceptual illustrations live in a single
`concept_illustration` layout (SPEC §6 vocabulary) with a `style`
field in slide_spec carrying one of `metaphor | infographic |
conceptual_diagram`. The AI-prompt agent uses the style hint to bias
prompt construction. The placeholder positions and visual frame are
the same across all three styles — only the prompt flavor differs.

**Rationale:** Three layouts for what is fundamentally one slide
shape (centered AI image + punchline title + AI-disclosure footer)
inflates the vocabulary for no visual difference. One layout with a
style discriminator keeps the master template simple and
visualizes consistently. Adam confirmed (1) "one layout, accepted."

**Alternatives considered:** (a) Three separate layouts — rejected
per above. (b) Embed AI images inside other layouts (e.g., as the
figure slot of `claim_evidence`) — rejected; the AI-disclosure
footer is layout-level and conflating it with quantitative-figure
layouts loses the "this is conceptual, not data" cue.

**Related:** [SPEC](SPEC.md) §6, §8.3.1; D-005 (rev1).

---

## D-029 — 2026-04-26 — `big_number` layout for headline statistics

**Decision:** Add `big_number` as a 15th layout. Distinct from
`big_idea` (sentence-as-claim) and `claim_evidence` (claim with
bullets + figure). Slide content: a single huge number or short
stat phrase ("90% accuracy", "27M fitness scores", "149 novel
candidates"), one-line subtitle, optional sub-bullet pointer and
source-footer. Title is the headline statistic itself.

**Rationale:** Adam called this out in spec review (rev1,
2026-04-26). Headline statistics carry weight in talks that other
slide kinds cannot match — collapsing them into `big_idea`
sentences blunts the impact. Visually distinct: huge centered
numeric typeset vs. sentence typesetting. Common in KBase-platform
talks ("293K genomes", "1B genes", "27M fitness scores") so
deserves first-class layout support.

**Alternatives considered:** (a) Subsume into `big_idea` —
rejected; visual contract is different (number vs. sentence). (b)
Reuse `data_figure` with the number rendered as a "figure" —
rejected; data_figure is sourced from notebook output and carries
caption discipline; numbers on big_number can be paraphrases of
REPORT-level numerics.

**Related:** [SPEC](SPEC.md) §6.

---

## D-030 — 2026-05-12 — Discrepancy_register port: NO (paper-Methods-specific)

**Decision:** Do NOT port paper-writer's `discrepancy_register.py` / `audit_discrepancies.v1.md` into presentation-maker. The plan-vs-execution diff surface is load-bearing for paper Methods + Limitations but does not carry the same weight in talks (the `methods_summary` slide and Q&A prep operate at a different abstraction level).

**Rationale:** Paper-writer §4.5 lifts discrepancy detection upstream specifically to prevent Methods/Results/Limitations contradictions during single-pass holistic write. Presentation-maker's architect call is structural, not prose-integrative; the rationale doesn't transfer. Skipping this port keeps M1 scope tight.

**Alternatives considered:** (a) Port for Q&A-prep enrichment (anticipated questions could be calibrated against plan-vs-execution drift) — deferred to v0.5; (b) Vendor as a no-op stub for cross-skill schema parity — overdesign.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §4.0; paper-writer SPEC_v0_8 §4.5.

---

## D-031 — 2026-05-12 — Architect default model is Opus 4.6

> **SUPERSEDED 2026-05-23 by D-043.** M2-lite's `deck_outline.v1` call
> runs on Sonnet 4.6 — it emits an advisory outline, not a frozen
> contract, so the Opus premium no longer buys a commensurate margin.

**Decision:** `deck_architect.v1.md` defaults to `claude-opus-4-6`. `--architect-model claude-sonnet-4-6` is the cost-sensitive opt-in. Cost: $3.00–$5.00 per architect call vs Sonnet's $1.00–$2.00.

**Rationale:** The architect is the load-bearing cross-cutting planning agent; arc quality at this layer determines whether the parallel composers produce a coherent deck or locally-good slides that miss the through-arc. Paper-writer v0.8's analogous Phase 2 (D-034 Q4) chose Opus for the same kind of integrative-judgment reasons. The cost premium (~$2.70–$4.70 per draft net of today's `plan.v1` + `substory_design.v1` ≈ $0.30) is accepted; partially offset by reduced rewrite cycles when Tier 1 review fails less often.

**Alternatives considered:** Sonnet default with Opus opt-in (memo v1 proposal) — rejected; the deciding factor is that the architect's job is integrative across substories, and "downgrade only when bulk-draft economics dominate" is the right default polarity.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §6.8, §11; paper-writer SPEC_v0_8 D-034 Q4.

---

## D-032 — 2026-05-12 — Composer-architect deviation contract: RIGID

> **SUPERSEDED 2026-05-23 by D-044.** The M2-lite outline is advisory
> context, not a contract; there is no rigid plan to "deviate" from
> and no `architecture_conflict` halt.

**Decision:** When per-substory `slide_compose` finds the architecture's plan doesn't fit the evidence, it halts with `phase=architecture_conflict`, logs the deviation in `audit/architecture_conflicts.jsonl`, and the orchestrator re-runs the architect with the composer's complaint as amendment input. No advisory mode; no deck-level reconcile pass; composer cannot deviate silently.

**Rationale:** Clean blame attribution + simpler implementation are worth more in v0.4 pilot than the operational flexibility of advisory mode. If the architect's planning quality is high enough that conflicts are rare, the rigid contract pays no cost. If conflicts are frequent, that's a signal the architect prompt needs improvement — fix the cause, not the workaround. Advisory mode reconsidered at v0.5 only if empirical conflict rate justifies the bookkeeping.

**Alternatives considered:** (a) Advisory with logged deviation + post-composition reconcile pass — operational flexibility but weak accountability and another LLM call; (b) Two-pass (composer proposes alternative before doing full compose) — high quality, double latency.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §7.2.

---

## D-033 — 2026-05-12 — Speaker notes fused into per-substory slide_compose worker

**Decision:** One Claude call per substory worker writes both `compose-fragment.v1` JSON and `speaker_notes_seed.v1` JSON for the substory's slide range. Today's separate `slide_compose.v1` + `speaker_notes.v1` calls fuse into one per-substory worker invocation. `speaker_notes.v1.md` prompt content stays, but is invoked inline by the fused composer prompt.

**Rationale:** Composer and notes-author share the same context (architecture + throughline + assigned claims/citations/figures); the LLM's context-loading cost dominates and is paid only once when fused. Halves the per-substory LLM cost without quality loss — speaker-notes seeds are written immediately after the slide compose, in the same Claude conversation, so cross-coupling between slide and notes is tighter than today's two-call pattern.

**Alternatives considered:** Keep separate calls — rejected; doubles cost for no quality gain. Different model per call (e.g., Sonnet for compose + Haiku for notes) — rejected; speaker notes carry evidence anchors and are not Haiku-quality work.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §7.3; SPEC §10 speaker-notes discipline preserved.

---

## D-034 — 2026-05-12 — Revise-verb semantic-invariance post-check

**Decision:** `tools/revise_invariance.py` runs after every `revise` invocation enforcing 5 hard invariants modeled on paper-writer SPEC_v0_8 §11.2: (1) every pre-edit `claim_id` appears in post-edit at the same slide; (2) every citation token preserved byte-identical; (3) numeric tokens monotonically preserved; (4) hedge-marker level per-claim may decrease by ≤1 but not increase or flip scoped → declarative; (5) slide layout MUST NOT change via `revise` (layout changes require re-architecting).

**Rationale:** Per-slot LLM revisions silently change citation tokens, flip hedges, and introduce numeric assertions that weren't on the prior version — and the user is most likely to miss these because they're focused on whether the requested change happened. Programmatic invariance check is small surface, high catch-rate.

**Alternatives considered:** Line-diff cap (paper-writer's v0.7.x pattern) — rejected; too coarse for clarity rewrites. Soft warnings instead of halt — rejected; defeats the safety property.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §13; paper-writer SPEC_v0_8 §11.2.

---

## D-035 — 2026-05-12 — AI Studio model-probe fallback chain

**Decision:** `image_client.py` Google AI Studio provider probes `GET /v1beta/models` at startup, filters for image-capable models, picks `gemini-3-pro-image` if present, else `gemini-2.5-flash-image`, else fails with a clear message naming available models. Resolved choice cached in `state.json` per draft (`ai_image_gen.resolved_model`).

**Rationale:** Adam confirmed gemini-3-pro-image is being deprecated but should be used if available. Hard-coding either name is wrong; probing accommodates Google's model lineage rollovers without code change. Caching avoids per-invocation re-probe overhead.

**Alternatives considered:** Hard-code single model id — brittle. Always probe — unnecessary latency. Manual user selection via `--image-model` — possible override; not the default.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §14.2.

---

## D-036 — 2026-05-12 — Cut-over gate: dominate ≥5 of 7 metrics; wall-clock mandatory primary

**Decision:** v0.4.0 vs v0.3.8 A/B at M6 scores on 7 metrics (wall-clock, token cost, adversarial findings, Tier-1 failure rate, arc coherence, image-budget adherence, paper-review quality). v0.4 must dominate on ≥5 of 7. Wall-clock is the mandatory primary metric — if v0.4 doesn't reduce wall-clock by ≥30% (per D-039), the gate fails regardless of the other 6 scores.

**Rationale:** The parallelism investment must demonstrably pay off in wall-clock; arc-coherence and adversarial findings are softer signals that can be argued. Anchoring on wall-clock prevents the architecture-quality argument from masking failed parallelism.

**Alternatives considered:** ≥6 of 7 (stricter) — rejected for v0.4.0 to leave room for one regression in a multi-axis comparison; reconsider at v0.5 if M6 results suggest the threshold was too loose. ≥4 of 7 (looser) — rejected; defeats the cut-over rigor.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §15.

---

## D-037 — 2026-05-12 — M6 reviewer pool: Adam-only

**Decision:** v0.4.0 M6 cut-over go/no-go is Adam-only. Structured user-centered review (multi-reviewer, naive-reader pass, colleague cross-evaluation) deferred to a post-v0.4.0 launch milestone.

**Rationale:** Matches paper-writer SPEC_v0_8 Q8 / D-034 precedent. M6 is a research-iteration decision, not a public-launch decision; broader review fits the launch event, not the cut-over.

**Alternatives considered:** Multi-reviewer at M6 — rejected for scope creep; the panel-of-one team's bottleneck is cycle time, not reviewer coverage.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §15.

---

## D-038 — 2026-05-12 — State.json phase enum: hard schema bump to "0.4"

**Decision:** `state.json` schema bumps from "0.3" to "0.4". New phase enum: `plan → phase0_tooling → throughline_pick → deck_architect → deck_architecture_pick → composition → review_tier1 → review_tier2 → review_tier3 → assembled` (plus halt states). v0.4 runs do not back-migrate v0.3.x state; a one-way migration script (M6 deliverable) converts v0.3.x state.json into v0.4 shape for in-flight drafts.

**Rationale:** Clean break is operationally simpler than back-compat. The phase enum is structurally different enough (architect phase inserted, composition collapses into a single parallel phase, review tiers explicit) that overlay-compatibility would carry ongoing complexity for no real benefit. Paper-writer SPEC_v0_8 §13 set the precedent.

**Alternatives considered:** Maintain back-compat with optional fields — rejected; the phase enum's semantics shift and back-compat would lie about what the state means.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §10; LAYOUT.md §6 (legacy schema).

---

## D-039 — 2026-05-12 — Wall-clock primary-metric target: ≥30% reduction (hub)

**Decision:** Cut-over gate requires v0.4.0 reduce talk-45 STRONG wall-clock by ≥30% on the hub vs. v0.3.8's verified 222 min baseline. Target hub wall-clock post-pivot: ≤155 min on talk-45 STRONG.

**Rationale:** The honest math (per V0_4_ARCHITECTURE §11.3): V0_4_0_PUNCH_LIST's C1-alone estimate was 60–90 min saved; v0.4 adds 5–15 min from cascade fail-fast + 10–30 min from reduced rewrite cycles. Combined estimated post-pivot hub wall-clock 100–150 min (30–55% reduction range). Setting the target at ≥30% lands at the conservative end of this range with headroom for variance.

**Alternatives considered:** ≥40% (more aggressive) — rejected; not supported by the honest math without claiming savings beyond what parallelism + cascade can deliver. ≥20% — rejected; too lenient to motivate the architectural pivot.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §11.3, §15.

---

## D-040 — 2026-05-12 — Vendor active-path Phase-0 tools from paper-writer at M1

**Decision (REVISED 2026-05-12 as D-040-rev1):** M1 vendors paper-writer's *active production path* for Phase 0, not the deferred M1 §B1 surface. Three vendor copies + one authored adapter:

1. `extract_methods.py` — AST-based methods extraction (still active per paper-writer's draft_4 Stage 1 closure). ~1100 LOC byte-portable.
2. `extract_claims.v1.md` — 40-line LLM prompt invoked via `claude -p` for claim-inventory production. Paper-writer's `phase_triage` uses this; superseded the regex+demarcation tool.
3. `validate_claim_inventory.py` — 241-line post-validator (Stage 1 Tier C); clears LLM-fabricated `source_notebook` paths (~10% fabrication rate observed on paper-writer draft_3).
4. `extract_claims.py` (NEW, ~340 LOC) — adapter wrapping the `claude -p` invocation + chained validator as a standalone tool (paper-writer inlines this logic in orchestrator.py; presentation-maker exposes as a CLI for the M2 orchestrator to call).

DEFERRED (not vendored at M1): paper-writer's `claim_inventory.py` (~2400 LOC regex+LLM-demarcation tool). Paper-writer's STAGED_IMPROVEMENT_PLAN.md Stage 1 Tier E (closed 2026-05-11) deferred this from the active pipeline. We do not revive a deferred path; if presentation-maker hits LLM-extraction quality issues that justify the regex fallback, re-vendor from paper-writer's tree at that point.

**Rationale (rev1):** D-040 v1 was authored at M0 (2026-05-12 morning) on a stale read of paper-writer's state. Paper-writer's `project_paper_writer_v0_8_m1_a1.md` memory entry (2026-05-07) correctly reported `claim_inventory.py` as M1 §B1.abcd shipped — but paper-writer themselves deferred the file from active pipeline on 2026-05-11, one day before our M0. The drift was caught during M1 vendoring when the copied file's lines 4–15 surfaced its STATUS note ("M1-deferred path; not currently called by orchestrator.py"). M0's verification process did not check (a) the file's docstring or (b) paper-writer's most recent improvement-plan doc. Memory entry `feedback_vendor_port_verify_active_path.md` captures the cross-cutting lesson; this D-040-rev1 amends the per-decision record.

**Cost / LOC delta v1 → rev1:** vendored LOC drops from ~3500 to ~1400 (eliminates the 2400-LOC deferred tool); test count drops from 18 vendored (regression-net for deferred path) to ~12-15 authored (active-path coverage that paper-writer themselves lack). Adapter adds ~340 LOC of new code. Net: simpler, smaller, architecturally aligned with paper-writer's current production path.

**Alternatives considered (rev1):** Option B (charge ahead with `claim_inventory.py` as originally planned) — rejected; ships ~2400 LOC of code paper-writer doesn't actively run, creates technical-debt risk if paper-writer later removes the file. Option C (vendor active path + deferred path as fallback) — rejected; overbuilding for v0.4 pilot, can be revisited if LLM extraction quality fails.

**Ship verification 2026-05-12:** All vendored + authored tests passing (66/66 new+adapted across `test_extract_methods.py` + `test_validate_claim_inventory.py` + `test_extract_claims.py`). Full presentation-maker suite: 928 passed, 1 skipped, 2 pre-existing environmental errors unrelated to M1.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §4.4, §4.5, §16 M1; [M1_PUNCH_LIST.md](M1_PUNCH_LIST.md); memory `feedback_vendor_port_verify_active_path.md`; paper-writer `STAGED_IMPROVEMENT_PLAN.md` Stage 1 Tier E.

---

## D-041 — 2026-05-12 — Cut-over A/B must dominate in both work modes

**Decision:** M6 A/B test runs in BOTH work modes — `ibd_phage_targeting` paper-exists mode + `functional_dark_matter` no-paper mode. v0.4.0 must dominate v0.3.8 on ≥5 of 7 metrics IN BOTH MODES separately for the cut-over to pass.

**Rationale:** No-paper mode is the original primary workflow for presentation-maker, not a fallback. If v0.4 wins big in paper-exists mode but regresses in no-paper mode (because, say, Opus architect cost dominates when there's no citation-pool reuse to amortize it), the cut-over should fail — the no-paper workflow must not regress silently. Both modes are first-class production paths.

**Alternatives considered:** Cut-over passes if v0.4 dominates in either mode — rejected; allows silent regression in the harder workflow. Cut-over evaluated in paper-exists mode only — rejected; same reason.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §4.0, §15.

---

## D-042 — 2026-05-23 — M2 reshaped: heavyweight "deck architect" → M2-lite "deck-outline call"

**Decision:** Phase 2 (M2) is no longer the heavyweight deck architect of V0_4_ARCHITECTURE §6. It becomes **M2-lite**: a single `deck_outline.v1` call — an enrichment of the existing `substory_design.v1` prompt — that emits a terse, *prescriptive* whole-deck outline (per-section punchline, slide budget, headline-number slot assignment, explicit transition-in/out sentences, scoped figures + claim_ids, deck register spec). The outline is advisory context fed to the parallel composers, not a machine-validated artifact. Dropped vs §6: `01_deck_architecture.json` as a rigid schema, `deck_architecture.py` (JSON-schema validator), `check_architecture_drift.py`, the six §8.3 architecture-time validators. A ~30-line post-merge reconciliation check (duplicate-figure / double-headline / image-budget) replaces the drift checker. Estimated effort ~12–18h.

**Rationale:** The 2026-05-23 outline probe (`experiments/m2-outline-probe/`) composed 3 `ibd_phage_targeting` substories with and without a shared outline. The outline-fed composer won on transitions, headline-stat placement, slide-budget discipline, and structural consistency — but the gain was driven by terse explicit *prescriptions*, not by a rigid per-slide contract, and not by "seeing the whole" (the composer already sees the whole via `00_throughline.md` + `02_substories.md`). A rigid `01_deck_architecture.json` + drift-checker is over-engineering for the gain on offer.

**Alternatives considered:** Heavyweight architect as specced at M0 — rejected; the probe showed the rigid-contract machinery does not earn its build cost. Naive parallelization with no outline — rejected; the probe showed the outline-fed composer measurably beats it. Build M2-lite without a probe — rejected; a ~$3 probe de-risked a 12–18h build.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §20; `experiments/m2-outline-probe/`; supersedes the §6 design.

---

## D-043 — 2026-05-23 — Outline-call model: Sonnet 4.6 (supersedes D-031)

**Decision:** The `deck_outline.v1` call runs on Sonnet 4.6, not Opus 4.6. **Supersedes D-031** (which set the deck architect default to Opus 4.6 with a `--architect-model` Sonnet opt-in).

**Rationale:** D-031 chose Opus because the heavyweight architect emitted a frozen, downstream-load-bearing contract where arc-quality margin justified the ~3× cost ($3–5/call). M2-lite emits an *outline* — a prescription sheet — not a frozen contract; its load-bearing content is structured directives (slot assignments, budgets, one-sentence transitions) that Sonnet emits reliably. The Opus premium no longer buys a commensurate margin. Revisit only if coherence testing on real M2-lite output shows Opus materially helps.

**Alternatives considered:** Keep Opus per D-031 — rejected; pays a ~3× premium for a contract that no longer exists. Haiku — rejected; the outline still requires whole-deck arc judgment.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §20.2; supersedes D-031.

---

## D-044 — 2026-05-23 — Composer–outline contract: advisory, not rigid (supersedes D-032)

**Decision:** The per-section composer treats the outline as **advisory context**, not a rigid contract. **Supersedes D-032** (the RIGID halt-and-re-architect deviation contract). Dropped: the `architecture_conflict` halt state, the re-architect-with-amendment loop, `audit/architecture_conflicts.jsonl`, and the `architecture_blocked` halt state. Composers free-hand all local composition; the outline pre-assigns only scarce/conflict-prone resources (figures, headline `big_number` slots, image budget, transition placement), and the post-merge reconciliation check (D-042) catches residual conflicts.

**Rationale:** D-032's rigid contract existed to police a rigid `01_deck_architecture.json` that D-042 has eliminated. With an advisory outline there is nothing to "deviate" from in the contractual sense — a composer that judges a scoped claim doesn't fit simply composes the best section it can, and the post-merge check + Tier-1 review catch real problems. Rigid blame-attribution was D-032's stated benefit; it is not worth a halt-and-re-run loop when the outline is advisory.

**Alternatives considered:** Keep the rigid contract — rejected; it polices a contract that no longer exists. Two-pass advisory mode with a formal composer-complaint channel — rejected as over-built for v0.4; the post-merge check is sufficient.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §20.3, §7.2 (superseded); supersedes D-032.

---

## D-045 — 2026-05-23 — `deck_architecture_pick` user gate removed

**Decision:** The `deck_architecture_pick` human-approval gate (V0_4_ARCHITECTURE §6.7) is removed. The throughline-pick gate is the single load-bearing human gate in the v0.4 pipeline; the deck outline is computed and flows straight through to the parallel composers. Dropped with it: the `--amend-architecture` amendment loop, the 3-cycle amendment cap, the `--candidates`/`--pick` alternative-architecture selection, and the `architecture_blocked` halt state. The phase enum becomes `… → throughline_pick → deck_outline → composition (parallel) → …`.

**Rationale:** Adam's call (2026-05-23): the throughline-pick gate already secures the load-bearing user decision (which meta-arc the talk takes). An advisory outline derived from an already-approved throughline does not warrant a second gate — it adds a halt/resume round-trip for a low-stakes artifact the user can adjust later via the revise verb. One gate, not two.

**Alternatives considered:** Keep the architecture-approval gate — rejected; a second gate on an advisory artifact is friction without a commensurate decision at stake. Make the gate opt-in via a flag — rejected; an unused gate is dead code.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §20.2, §10.1; supersedes §6.7.

---

## D-046 — 2026-05-23 — M3: Phase-0 stages cluster after the throughline gate (DQ1)

**Decision:** On the v0.4 path, `phase0_tooling` and the other Phase-0 producers (`curate_figures`, `citation_pool`, `cross_tenant`) run as a contiguous cluster *after* the throughline-pick gate and immediately before `deck_outline` — not before the gate as the §10.1 enum sketch implied.

**Rationale:** `citation_pool` and `cross_tenant` need the approved throughline anyway; one contiguous reorder is lower-risk than scattering; Phase-0 spend ($0.50–$1.50) lands only on gate-approved runs. The §10.1 ordering is immaterial to correctness — `phase0_reuse.py` depends only on the project.

**Related:** [M3_PUNCH_LIST.md](M3_PUNCH_LIST.md) Tier A; V0_4_ARCHITECTURE §10.1.

---

## D-047 — 2026-05-23 — M3: bash `&`/`wait` worker-pool for parallel slide_compose (DQ2)

**Decision:** Parallel per-substory composition uses a bash `&`/`wait` worker-pool (`tools/worker_pool.sh`, `wp_run_pool`) that reuses `invoke_claude_with_retry` verbatim, rather than a Python `concurrent.futures` wrapper.

**Rationale:** `invoke_claude_with_retry` already encodes the load-bearing retry semantics (rc=2 Write-not-invoked; rc=4 API-transient backoff). A Python pool would reimplement them. The pool is bash-3.2-compatible (indexed arrays, no `wait -n`); the concurrency risk under `set -euo pipefail` is contained by per-worker `wait "$pid" || rc=$?` and per-worker stderr capture.

**Alternatives considered:** Python `concurrent.futures` subprocess wrapper — rejected; reimplements the retry/stream machinery for no gain.

**Related:** [M3_PUNCH_LIST.md](M3_PUNCH_LIST.md) Tier B; V0_4_ARCHITECTURE §7.3.

---

## D-048 — 2026-05-23 — M3: full speaker-notes fusion into the composer (DQ3)

**Decision:** The v0.4 composer (`slide_compose.v2.md`) authors the full 200–400-word speaker notes inline (one `speaker_notes` string per slide); the separate `speaker_notes.v1` stage is retired on the v0.4 path. Confirms D-033.

**Rationale:** §7.3's shared-context argument holds (don't reload REPORT/throughline/outline twice). D-033's original premise — a *narrowed* composer with spare capacity — partly eroded when M2-lite kept the composer full; so the decision carries a documented **un-fuse off-ramp**: if Tier-E notes quality disappoints, `speaker_notes` returns as its own stage, parallelized through `wp_run_pool`. Cross-skill: `merge_compose_fragments.py` derives `working/04_speaker_notes/{sid}_notes.json` so beril-adversarial's reviewer contract holds.

**Related:** [M3_PUNCH_LIST.md](M3_PUNCH_LIST.md) Tier D; D-033; `feedback_cross_skill_contract_drift`.

---

## D-049 — 2026-05-23 — M3: Tier-2 detection-class calibration deferred to M4b (DQ4)

**Decision:** The empirical Tier-2 adversarial-detection-class calibration that §16 originally assigned to "M3 start" is deferred to M4b (the review cascade).

**Rationale:** Tier 2 is a review-cascade component; calibrating detection classes for a cascade that does not exist yet is premature, and §16's assignment predates the M2-lite reshape.

**Related:** [M3_PUNCH_LIST.md](M3_PUNCH_LIST.md) DQ4; V0_4_ARCHITECTURE §16 M4b.

---

## D-050 — 2026-05-23 — M4a: visual-QA is opt-in, not auto-run (DQ1)

**Decision:** The Tier-C visual-QA pass runs only when the operator passes `--visual-qa` (orchestrator flag) or invokes the standalone `visual_qa.py` verb. Off by default (`VISUAL_QA=0` in `presentation_maker.sh`). Always advisory (rc=0; never blocks assembly); writes `audit/visual_qa.{md,json}`.

**Rationale:** The pass costs a LibreOffice render + a vision-LLM call (~$0.6–0.8 per 28-slide deck on Sonnet 4.6). Adding that to every run before there's a body of cost data is premature spend. Opt-in first; revisit auto-running once M4b's cascade exists (it may belong as an M4b Tier-1 check). Skill ships portable — soffice + pdftoppm are host-only runtime deps gated by the flag; a hub without them runs every other pipeline identically and the flag, if passed, writes a stub report.

**Alternatives considered:** Auto-run on every assemble — rejected per the cost-discipline argument. A `--no-visual-qa` opt-out instead — rejected; would normalize the cost before we have data.

**Related:** [M4_PUNCH_LIST.md](M4_PUNCH_LIST.md) DQ1; V0_4_ARCHITECTURE §16 M4a; `tools/visual_qa.py`; `prompts/visual_qa.v1.md`; `feedback_cost_record_dont_gate`.

---

## D-051 — 2026-05-23 — M4a: visual-QA render toolchain — soffice + pdftoppm (DQ2)

**Decision:** The Tier-C render pipeline is `soffice --headless --convert-to pdf` followed by `pdftoppm -png -r 100` (Poppler). One pptx → one pdf → N per-slide PNGs. Both binaries probed via `shutil.which` at tool start; missing → advisory stub report + rc=0.

**Rationale:** `soffice --convert-to png` only converts the first slide of a `.pptx` (single-image output), so the pdf-intermediate route is the standard one-shot for a multi-slide deck. `pdftoppm` is the Poppler default and matches what scientific-document toolchains use; confirmed present on Adam's Mac. The host-only runtime gate (D-050) prevents this from becoming a skill-install dependency.

**Alternatives considered:** ImageMagick `convert` instead of `pdftoppm` — rejected for being a heavier dep with a security history. `mutool draw` — viable alternative if Poppler is unavailable on a target host; revisit if a hub install lacks Poppler. Direct python-pptx → PIL render — rejected as lossy (the watermark + master template details only show up under real PowerPoint-spec rendering).

**Related:** [M4_PUNCH_LIST.md](M4_PUNCH_LIST.md) DQ2; `tools/visual_qa.py` `pptx_to_pdf` + `pdf_to_pngs`.

---

## D-052 — 2026-05-23 — M4a: shrink-to-fit floor at 60% fontScale + clamp warning (DQ3)

**Decision:** Tier-A's `_fit_textbox` (`assemble_pptx.py`) and `_apply_fontscale_to_shape` (`diagram_render.py`) shrink toward a documented floor of `60000` (60% of the master pt size) and clamp at the floor — never silently sub-60%. When the floor is reached, the assembler emits a soft-warning to its `warnings` channel (`AssemblyResult.warnings`); the Tier-C visual-QA pass and the operator both see it.

**Rationale:** 60% matches the M3 E-4 `_fill_qa_anticipated` adaptive ladder, which was empirically known-legible at projection distance on the v0.2.2 fixed-60% Q&A slides. A single floor (vs per-slot floors keyed to each slot's design pt size) keeps the helper simple; on the smallest text (workflow step_captions at 11pt × 60% = 6.6pt, references at 18pt × 60% = 10.8pt) the rendered text is tight but legible. Per-slot floors deferred until a slot pattern proves the single floor inadequate.

**Alternatives considered:** Per-slot floors keyed to each slot's design pt size — rejected as more complex than the gain. Hard-fail at the floor (refuse to render) — rejected; the renderer's job is to produce a deck, and clamping is the right safety net (the operator sees the warning and can hand-edit).

**Related:** [M4_PUNCH_LIST.md](M4_PUNCH_LIST.md) DQ3; `tools/assemble_pptx.py` `FONTSCALE_FLOOR` + `_fit_textbox`; `tools/diagram_render.py` `NODE_FONTSCALE_FLOOR` + `_apply_fontscale_to_shape`; M3 E-4 (precedent).

---

## D-053 — 2026-05-23 — M4a: content-cap validator backstops are advisory soft-warnings (DQ4)

**Decision:** The new Tier-B content-length caps (`BIG_NUMBER_SUBTITLE_MAX_CHARS=80`, `WORKFLOW_STEP_CAPTION_MAX_CHARS=70`, `QA_ANSWER_SUMMARY_MAX_CHARS=600`, `DIAGRAM_NODE_LABEL_MAX_CHARS=40` in `slide_spec.py`) emit `ValidatorIssue` with `severity="soft-warning"`. The assembler splits issues by severity: hard errors raise `AssemblyError` as before; soft-warnings surface through `AssemblyResult.warnings` (same channel as the Tier-A clamp warnings and missing-asset warnings). The pre-existing `DATA_FIGURE_CAPTION_MAX_CHARS=280` remains a hard-error (load-bearing for the no-shrink render of the `data_figure` caption per v0.3.5 motivation).

**Rationale:** The Tier-A renderer absorbs slightly-long content (shrink-to-fit toward the 60% floor). Failing the pipeline after LLM spend on a length the renderer can absorb is poor value; surfacing the cap as advisory lets prompt drift be caught programmatically while keeping the run alive. `--strict` continues to fail on any warning (including soft-warnings) — opt-in fail-on-warning, unchanged contract.

**Live failure pin:** during Tier E round-1 recompose on `ibd_phage_targeting/draft_1`, the bash orchestrator's `slide_spec.py validate` CLI call (separate from the in-process assembler split) initially returned `rc=1` on a spec with 19 soft-warnings + 0 errors — `_cli_validate` was missed in the Tier-B commit. Hotpatch `53dfaf5` made the CLI severity-aware too; both code paths now agree.

**Alternatives considered:** Hard-reject parity with `DATA_FIGURE_CAPTION_MAX_CHARS` — rejected; the four new caps are aesthetic (renderer absorbs), not load-bearing. New `severity="info"` tier for "just track it" — rejected as premature; two severities cover the current cases.

**Related:** [M4_PUNCH_LIST.md](M4_PUNCH_LIST.md) DQ4; `tools/slide_spec.py` `ValidatorIssue.severity` + `_check_advisory_max_chars`; `tools/assemble_pptx.py` `assemble()` issue-split; M4a Tier E round-1 CLI hotpatch (commit `53dfaf5`); `feedback_prompt_discipline_needs_post_check`.

---

## D-054 — 2026-05-24 — M4b: review cascade auto-runs by default (DQ1)

**Decision:** The Tier-B/C/D review cascade (`tools/review_cascade.py`) auto-runs by default after `stage_merge_and_assemble` in `presentation_maker.sh`. Opt out via `--no-review-cascade`. Distinct from M4a's `--visual-qa` (which is opt-in per D-050) because the cascade's value proposition IS fail-fast: making it opt-in defeats the cost-savings it's supposed to deliver.

**Rationale:** Tier 1 is ~free (deterministic + audit-file reads). Tier 2 is ~$0.05 (Haiku narrative-light). Tier 3 is the existing canonical adversarial (~$0.50–$1.50) that ALREADY runs by default; the cascade just orchestrates around it with fail-fast guards. So the marginal cost of cascade auto-run vs status quo is the ~$0.05 Tier 2 layer — well below the ~$0.50+ savings on every Tier-1-P0 draft. Opt-in posture would have asymmetric value (~$0.05 cost to opt in; ~$0.50+ saved when Tier 1 catches a real defect).

**Alternatives considered:**
- **Opt-in via `--review-cascade`** — rejected; defeats the fail-fast value prop. Operators who don't know the flag exists never get the cascade.
- **Opt-out per-tier (`--no-tier2`, `--no-tier3`)** — kept these for surgical use (e.g., re-running cascade after a code change without re-spending Tier 3). The CLI flags exist; the orchestrator just doesn't expose them.

**Related:** [M4b_PUNCH_LIST.md](M4b_PUNCH_LIST.md) DQ1; `tools/review_cascade.py`; `tools/presentation_maker.sh` `NO_REVIEW_CASCADE` flag + `stage_review_cascade` dispatch.

---

## D-055 — 2026-05-24 — M4b: cascade reads `audit/visual_qa.json` if present; never invokes `visual_qa.py` (DQ2)

**Decision:** Cascade Tier 1 reads `audit/visual_qa.json` if it exists and lifts findings into cascade findings (confidence=high → P1; medium/low → P2). The cascade NEVER invokes `tools/visual_qa.py` itself. Operators opt in to visual-QA via the existing `--visual-qa` flag (per D-050); the cascade just consumes whatever the operator chose to produce.

**Rationale:** D-050's portability posture is load-bearing — the skill ships without LibreOffice or Poppler as hard deps. If the cascade invoked `visual_qa.py`, then every cascade run would either spend the vision-LLM cost or write a stub-report; either way, the M4a opt-in semantic is broken. Reading the file if-present preserves both contracts: operators who passed `--visual-qa` get visual findings in the cascade JSON; operators who didn't see no change. Adam emphasized: **the `--visual-qa` option needs prominent documentation** (Tier F deliverable in HUB_INSTALL.md + README.md) so operators discover the integration.

**Stub-report handling:** the M4a stub-report posture writes `audit/visual_qa.json` with `findings: []` + a `note` (toolchain missing, spec missing, etc.). The cascade's `_read_visual_qa` ignores stubs (zero findings → no lift) so cascade JSON doesn't surface phantom "toolchain missing" noise.

**Alternatives considered:**
- **Auto-invoke visual-QA from cascade** — rejected; breaks D-050 + the portability posture.
- **Cascade flag to opt in to visual-QA-on-cascade-run** — rejected as duplicate of `--visual-qa`; one opt-in flag is cleaner.

**Related:** [M4b_PUNCH_LIST.md](M4b_PUNCH_LIST.md) DQ2; D-050 (visual-QA opt-in); `tools/review_cascade.py` `_read_visual_qa`.

---

## D-056 — 2026-05-24 — M4b: Tier 2 ships §8.1 candidate-four classes as v1; calibration is one-off + ship-then-iterate (DQ3)

**Decision:** Tier-2 reviewer (`prompts/review_tier2.v1.md`) ships the four detection classes from `V0_4_ARCHITECTURE.md` §8.1 — `register_drift`, `qa_softball`, `unbacked_quantitative`, `substory_arc` — as v1. Empirical calibration (per D-049, deferred from M3) is a single Tier-E live probe against Tier-3 adversarial output on `ibd_phage_targeting/draft_1`; results captured at `audit/review_tier2_calibration.md` in the live draft. Fine-grained calibration (prompt iteration based on more drafts' worth of data) is deferred to post-ship — DQ3-(c) ship-then-iterate, matching M4a's posture.

**Rationale:** Calibration before Tier 2 ships is premature — the 4-class scope is well-motivated from §8.1's design analysis; whether the classes are tuned correctly is empirically answerable only by running Tier 2 against real decks AND a Tier 3 ground truth. The Tier-E probe validates that Tier 2 (a) doesn't hallucinate findings (0 of 6 findings on the calibration deck were hallucinations) and (b) catches real defects that Tier 3 would otherwise find more expensively. v2 expansion candidates (additional classes: `claim_evidence`, `throughline_drift`, `unbacked_citation`; tighten `qa_softball`) are documented in the calibration artifact for the next prompt iteration.

**Live probe data** (Tier-E commit `b774e66`, `ibd_phage_targeting/draft_1`):
- T2 found 6 findings across all 4 classes; T3 found 14 findings (8 classes).
- Slide-level overlap: 0 (T2 + T3 catch different slides even within the same class — Tier 2 catches cheap/narrow wins, Tier 3 catches the rest).
- Substory-level overlap: 1/1 (both T2 and T3 flagged substory S4's arc).
- T2 false-positive rate: 0% (all 6 findings are real defects).

**Alternatives considered:**
- **Calibrate-before-ship via paper-writer's calibration data** — rejected; presentation-maker's defect classes differ from paper-writer's; cross-skill calibration is a poor proxy.
- **Ship Tier 2 with NO detection-class spec; let the model decide** — rejected; the structured prompt is what keeps Tier 2 cheap and focused vs Tier 3.

**Related:** [M4b_PUNCH_LIST.md](M4b_PUNCH_LIST.md) DQ3; D-049 (Tier-2 calibration deferred from M3); `prompts/review_tier2.v1.md`; live calibration artifact at `<draft_dir>/audit/review_tier2_calibration.md`.

---

## D-057 — 2026-05-24 — M4b: operator-gated fail-fast (Tier 1 P0 short-circuits Tier 2+3; Tier 2 never gates; Tier 3 runs unconditionally per scope) (DQ4)

**Decision:** Cascade short-circuit semantics: a Tier-1 P0 finding (P3/P4/P5 fail per `_P0_VALIDATORS`; D-058 later removes P3) causes Tier 2 + Tier 3 to SKIP with a `note: "short-circuited at tier1"`. Tier 2 findings are ALWAYS advisory (P1 or P2; the cascade dispatcher demotes a rogue Tier-2 P0 to P1 as an invariant guard); they NEVER trigger short-circuit; Tier 3 always runs after Tier 2 (unless explicitly `--no-tier3` or the standalone `--no-adversarial`). Tier 3 has full editorial authority and lifts v3 P0/P1/info findings as cascade P0/P1/P2, but Tier 3 is the bottom tier — its P0s do not short-circuit anything (nothing below to short-circuit).

**Rationale:** Tier-1 short-circuit is where the cascade earns its keep — Tier-3 adversarial costs ~$0.50–$1.50 per run, and running it on a deck with a mechanical fail (a number that contradicts REPORT, a citation that doesn't exist in the pool, a brand-color violation) is wasted spend. Tier 2 is a NEW pass with NO calibration history (D-049 deferred; D-056 ship-then-iterate); giving Tier-2 findings short-circuit authority before we have precision data would risk new false-positive short-circuits that defeat the cost-savings the cascade is supposed to deliver. Tier 3's authority is unchanged — it's still the canonical reviewer.

**DQ4 invariant enforcement:** the cascade dispatcher in `run_tier2` reads the model's emitted severity and demotes any P0 to P1. Pinned by `test_tier2_dispatcher_demotes_rogue_p0_to_p1`. If a future Tier-2 prompt iteration legitimately needs P0 authority (e.g., catches a never-Tier-3-misses defect type), this decision revisits.

**Alternatives considered:**
- **Strict P0 only** (only validator-emitted P0s short-circuit; Tier 2 + Tier 3 always run regardless of Tier 2 findings) — equivalent to current behaviour for the Tier-2-doesn't-gate part; differs only in how the cascade names the short-circuit semantic. Kept the "operator-gated" framing for clarity.
- **Inclusive P0** (Tier 2 + Tier 3 high-severity findings short-circuit later tiers) — rejected; Tier 2 has no calibration, Tier 3 IS the last tier.

**Related:** [M4b_PUNCH_LIST.md](M4b_PUNCH_LIST.md) DQ4; `tools/review_cascade.py` `run_cascade` short-circuit logic + `run_tier2` P0-demote invariant; tests `test_run_cascade_tier1_p0_short_circuits_2_and_3` + `test_tier2_dispatcher_demotes_rogue_p0_to_p1`.

---

## D-058 — 2026-05-24 — M4b: demote P3 from P0 to P1 on the v0.4 cascade; retire P3 in M5

**Decision:** The Tier-1 cascade's `_P0_VALIDATORS` set (`tools/review_cascade.py`) drops `"P3"`; only `"P4"` (citation pool) and `"P5"` (brand color) remain as P0 short-circuit triggers. P3's findings still appear in the cascade as advisory `P1` (so the operator sees them) but no longer block Tiers 2 + 3.

**Rationale:** P3 validates a `speaker_notes_provenance` index that the v0.3 composer + `speaker_notes.v1` stage emitted as a structured field. The v0.4 composer (`slide_compose.v2.md`, M3 fused-notes path per D-033 / D-044) writes `speaker_notes` as a single string and does NOT emit the structured provenance index. So P3 sees zero entries on every v0.4 deck and emits a fail for every number on every slide — 282 P0 findings on `ibd_phage_targeting/draft_1` (M4b Tier E probe, 2026-05-24), short-circuiting Tiers 2 + 3 on EVERY v0.4 draft. The cascade's value prop (skip ~$0.50–$1.50 of adversarial when Tier 1 finds a real mechanical fail) is destroyed if Tier 1 always short-circuits on a v0.3-era contract mismatch.

The v0.4 authoritative numeric-provenance check is `check_quantitative_grounding.py` (already wired into `stage_merge_and_assemble`; already read by Tier 1's `_read_quantitative_grounding` aggregator): it walks slide content, extracts numbers, greps `REPORT.md` for each. On the same `ibd_phage_targeting/draft_1` deck, it reports 273/278 grounded (98.2% pass rate, 3 ungrounded all advisory) — the deck IS well-grounded; P3 was wrong about every fail.

**Implementation:** `_P0_VALIDATORS` constant in `review_cascade.py` updated; new test `test_tier1_p0_validators_pinned_to_p4_p5` pins the v0.4 cascade contract; comment + commit message capture the rationale.

**Retirement schedule (M5):** P3 itself stays in `validate_presentation.py` for the v0.3 audit trail (specs from before D-044 may still have the `speaker_notes_provenance` field; P3 still validates them correctly). The M5 retirement deletes P3 OR rewrites it to wrap `quantitative_grounding.py` (the v0.4 authoritative check). M5 also updates `SPEC.md §13.1` (the P3 documentation) to point at the new check. Until M5 lands, P3 stays in the validator set as advisory-only on the cascade path; `validate_presentation` CLI users (if any) still see P3 fail as a hard error per its original v0.3 contract.

**Alternatives considered:**
- **Skip P3 entirely on v0.4** — rejected; preserves the audit trail (P3 findings still appear in `audit/presentation_validation.json` and cascade JSON as advisory), and v0.3-style specs (if anyone re-runs old specs) still benefit from the check.
- **Spend new compose iteration to teach v0.4 composer to emit `speaker_notes_provenance`** — rejected; ~$5 of compose spend per probe, and `quantitative_grounding.py` already implements the same intent more correctly (greps REPORT.md directly rather than maintaining a parallel structured index).
- **Make P3 conditional on presence of `speaker_notes_provenance` in any slide** — rejected; cleaner to drop P3 from cascade P0 outright and let M5 handle the proper retirement; conditional logic in `_P0_VALIDATORS` adds complexity without unlocking value.

**Live failure pin:** M4b Tier E live cascade probe on `ibd_phage_targeting/draft_1` (2026-05-24, log at the time of this decision):
```
review-cascade: 586 finding(s) across 3 tier(s) ($0.0000, short-circuited at tier1)
  ! tier1: fail (586 finding(s))     # 282 P0 P3 + 285 P2 no_artifact_refs + 16 P1 quant/visual_qa + 3 P1 visual_qa
  · tier2: skipped
  · tier3: skipped
```

**Related:** [M4b_PUNCH_LIST.md](M4b_PUNCH_LIST.md) Tier E; [SPEC.md](SPEC.md) §13.1 (P3 documentation — M5 update target); D-033 + D-044 (v0.4 fused-notes composer); `tools/review_cascade.py` `_P0_VALIDATORS`; `tools/check_quantitative_grounding.py` (the v0.4 authoritative numeric check); `tools/validate_presentation.py` (P3 stays for v0.3 audit trail until M5).

---

## D-059 — 2026-05-24 — M5a: P3 retirement complete; rewrite in-place as `check_quantitative_grounding` wrapper (closes D-058)

**Decision:** `validate_p3_numeric_provenance` is rewritten **in-place** (same `P3` id, same SPEC §13.1 reference, same severity position) to wrap `tools/check_quantitative_grounding.check_grounding(draft_dir)`. The v0.3 `speaker_notes_provenance` contract is RETIRED — no fallback path. Cascade `_P0_VALIDATORS` re-adds P3 (M4b D-058 demote becomes obsolete; cascade fail-fast on numeric defects is restored).

**Rationale:** D-058 demoted P3 from cascade P0 to P1 because the v0.3 implementation walked a per-slide `speaker_notes_provenance` index that the v0.4 fused-notes composer (D-033 / D-044) doesn't emit. The v0.4-native authority for "every numeric claim traces to evidence" is `check_quantitative_grounding.py` — already wired into `stage_merge_and_assemble` and already read by the M4b cascade Tier-1 `_read_quantitative_grounding` aggregator. Wrapping it from P3 reuses the working code and preserves P3's identity in the cascade contract.

**In-place rewrite vs new validator id:** considered renaming to `validate_p3b_grounded_numbers` (DQ4-(b) in the M5a punch list). Rejected per DQ4-(a): same id, same severity position, lower churn in DECISIONS / SPEC / cascade. The mechanism changed; the intent ("every numeric claim traces to primary evidence") and the SPEC §13.1 anti-fabrication discipline didn't.

**v0.3 fallback retired:** no `speaker_notes_provenance`-based fallback in the new P3. Legacy `validate_p3_numeric_provenance(spec)` calls without `draft_dir` return `status="skipped"` with a Violation noting the rewrite. v0.3-shape specs (if anyone re-runs them) now go through the REPORT-walking check; if their REPORT.md still exists, they get the v0.4 behaviour; if it doesn't, P3 skips with a clear note rather than the old `speaker_notes_provenance` lookup. The v0.3 unit tests `test_p3_*` were replaced by v0.4-shaped tests; the `_extract_numeric_claims` helper that the old P3 used is now dead code but kept (still has unit-test coverage of its own behaviour; cleanup is a small follow-on, not blocking).

**Related:** [M5a_PUNCH_LIST.md](M5a_PUNCH_LIST.md) Tier C; [SPEC.md](SPEC.md) §13.1 (updated this commit); D-058 (M4b Tier E demote — obsolete); `tools/validate_presentation.py` `validate_p3_numeric_provenance`; `tools/check_quantitative_grounding.py`; `tools/review_cascade.py` `_P0_VALIDATORS`.

---

## D-060 — 2026-05-24 — M5a: revise_invariance DQ1 (heuristic claim_id) + DQ2 (per-slide hedge aggregation)

**Decision:** `tools/revise_invariance.py` ships the five §13 invariants in M5a v1. Two pinned design choices:
- **DQ1 — invariant 1 `claim_id_cross_walk` ships with a heuristic.** Reads `<draft_dir>/working/00_phase0/claim_inventory.tsv` (M1 standard location); extracts the `claim_id` column; substring-matches mentions in slide text + speaker_notes; per-slide set must be equal pre vs post. Misses claims referenced without quoting the id (a real false-negative class); catches the common case where the composer reuses the id in `evidence_pointer`-style fields. Absent claim_inventory → invariant 1 SKIPPED (audit JSON records it; the other 4 invariants still gate).
- **DQ2 — invariant 4 `hedge_level` uses per-slide aggregation** + the §13-listed 5 markers as a `HEDGE_MARKERS` constant in `revise_invariance.py` (`may`, `suggests`, `appears`, `candidate`, `preliminary`). Per-slide sum across content + speaker_notes; ≤1 decrease allowed (rephrasing); increase or >1 decrease fail.

**Rationale (DQ1 reversal):** the M5a punch list originally recommended DQ1-(a) (defer invariant 1 until composer emits inline `[claim_id]` tokens). Adam reversed → ship the heuristic now. The heuristic's false-negatives are bounded by which slides quote ids in `evidence_pointer` fields (most do, per M1 + M2-lite per-substory briefs); the gain is that the revise verb is gated on all 5 invariants from §13 in M5a v1, not 4.

**Rationale (DQ2):** matches the M4a/M4b "ship the mechanism; iterate the parameters" posture. Per-slide aggregation is the simplest implementation; per-claim attribution (option b in the M5a punch list) is an empirical refinement once we have revise-failure data showing the per-slide aggregate is too coarse. The 5-marker dictionary is the §13 list; future extensions (`consistent with`, `might`, `hint`, `indicate`) become a single constant edit + retest.

**Alternatives considered:**
- **DQ1-(a) defer invariant 1** — Adam rejected; ship now with the heuristic.
- **DQ2 per-claim attribution** — deferred; no data yet on whether per-slide aggregation is too coarse.
- **Hedge dictionary as external JSON** — rejected; the dictionary is small and rarely changes; a constant in code is simpler.

**Related:** [M5a_PUNCH_LIST.md](M5a_PUNCH_LIST.md) DQ1 + DQ2; [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §13 (the 5-invariant contract); `tools/revise_invariance.py` `_check_claim_id_cross_walk` + `_check_hedge_level` + `HEDGE_MARKERS`.

---

## D-061 — 2026-05-24 — M5a: revise_invariance DQ3 (hard reject) + P3-vs-aggregator double-lift split (DQ4 follow-on)

**Decision:** Two split decisions captured together (the M5a `revise_invariance` gate + the M5a P3 rewrite both touch how cascade severity flows):

**A. revise_invariance DQ3 — hard reject on any failed invariant.** The `revise_loop._process_finding` gate (M5a Tier B) treats any invariant violation as terminal: the post-edit slide is REJECTED (not merged into the spec); the finding lands in `state.findings_invariance_violated` (distinct from `findings_failed` for operator visibility) and ALSO in `findings_failed` (backward-compat); the retry counter is NOT incremented (semantic failures rarely fix on naive retry); per-finding audit JSON at `audit/revise_invariance/<finding_id>.json`; `next_actions.md` surfaces the violations as a distinct line.

**B. P3-vs-aggregator double-lift split (D-061 follow-on to D-059).** The new M5a P3 reads `check_quantitative_grounding.GroundingReport.findings` and lifts ONLY high-severity findings (per `check_grounding._classify_severity`: n=X claims, ratios, scientific, integers >1000) as `Violation(severity="error")` → become P0 in the M4b cascade `_P0_VALIDATORS` short-circuit set. Medium/low-severity findings (percent, decimal, small integer) are intentionally NOT lifted by P3; the M4b cascade Tier-1 `_read_quantitative_grounding` aggregator continues to lift them as P1/P2 advisory. The split prevents double-lifting on the same number (operator would see the same defect counted twice with conflicting severity) while preserving P3's role as the load-bearing mechanical fail-fast surface for high-stakes numbers AND the aggregator's role as the operator-visibility surface for everything else.

**Rationale (A):** §13 says "the revise is rejected wholesale; halt with `phase=revise_invariance_violated`". The hard-reject contract is in the spec; M5a implements it. Retry-with-prompt-aware-feedback (option (b) in the M5a punch list) is a future iteration once we see how often invariance failures happen in practice.

**Rationale (B):** the alternative (P3 lifts EVERYTHING, aggregator stays out) collapses the severity stratification — every ungrounded percent becomes a cascade P0, defeating fail-fast. The alternative (aggregator lifts EVERYTHING, P3 stays out) loses P3's ability to short-circuit on high-stakes numbers. The split keeps both surfaces useful.

**Alternatives considered:**
- **A (revise_invariance) retry-with-feedback** — deferred per DQ3 ship-then-iterate; no calibration data yet on invariance-failure retry success.
- **B (P3 split) lift everything to P3** — rejected; collapses severity stratification.
- **B lift everything to aggregator** — rejected; loses fail-fast on high-stakes numbers.

**Related:** [M5a_PUNCH_LIST.md](M5a_PUNCH_LIST.md) DQ3 + DQ4; [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §13 (hard-reject contract); `tools/revise_invariance.py` (CLI rc=1 hard reject); `tools/revise_loop.py` `_check_revise_invariance` + `LoopState.findings_invariance_violated`; `tools/validate_presentation.py` `validate_p3_numeric_provenance` (high-only lifter); `tools/review_cascade.py` `_read_quantitative_grounding` (medium/low aggregator).

---

## D-035-rev1 — 2026-05-24 — M5b Tier A: AI Studio fallback chain updated for May-2026 model names

**Decision:** The D-035 model fallback chain is updated to match Google's actual May-2026 published model names (verified via WebFetch against `ai.google.dev/gemini-api/docs/image-generation` at M5b Tier A). New chain (`tools/image_client.py::AI_STUDIO_MODEL_FALLBACK_CHAIN`):

  `gemini-3-pro-image-preview` → `gemini-3.1-flash-image-preview` → `gemini-2.5-flash-image`

D-035's original chain was `gemini-3-pro-image → gemini-2.5-flash-image → fail`; Google's model line shifted under it. Specifically: the 3.x line on AI Studio carries a `-preview` suffix (CBORG's proxy strips it, which is why the original D-035 didn't anticipate); a new mid-tier `gemini-3.1-flash-image-preview` ("Nano Banana 2") is the May-2026 primary recommendation and slots between the pro and the prior-gen 2.5-flash.

**Rationale:** D-035's *intent* — "prefer pro lineage if available, fall back to flash, fail loudly if neither" — is unchanged. Only the *names* changed. Treating this as a rev rather than a new D-N preserves the cross-reference history (M5b carry-out items still cite D-035) while documenting the actual shipped chain.

**Alternatives considered:** New D-N for the chain — rejected; the intent and posture are identical to D-035. Hard-code only the May-2026 primary — rejected; the probe + fallback is the whole point of D-035.

**Related:** [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §14.2 (probe contract); D-035 (original chain); [M5b_PUNCH_LIST.md](M5b_PUNCH_LIST.md) Tier A; `tools/image_client.py::AI_STUDIO_MODEL_FALLBACK_CHAIN`; `resolve_ai_studio_model` test pins (test_image_client.py:test_ai_studio_fallback_chain_order, test_resolve_picks_pro_over_flash_when_both_available).

---

## D-062 — 2026-05-24 — M5b: AI Studio image-gen auth discovery lives in the shell orchestrator (DQ1)

**Decision:** Provider precedence and auth-discovery for the AI Studio image-gen path live in `tools/presentation_maker.sh`, NOT in a new Python helper. The existing `CBORG_API_KEY` `.env` resolution block (v0.3.3) is extended to a single-pass loop that also resolves `GOOGLE_AI_STUDIO_API_KEY`. Provider precedence:

1. Explicit `--image-provider {cborg|google_ai_studio}` wins (validated at parse time; unknown values exit 2 with clear error).
2. `GOOGLE_AI_STUDIO_API_KEY` present → `IMAGE_PROVIDER=google_ai_studio` (honours Adam's stated intent in §14.1).
3. `CBORG_API_KEY` present → `IMAGE_PROVIDER=cborg`.
4. Neither → `IMAGE_PROVIDER=""`; downstream `image_client.py` invocation defaults to `cborg` and exits 3 with the "CBORG_API_KEY not set" message — surfaces the misconfiguration loudly.

Resolved `IMAGE_PROVIDER` is exported + threaded into the `image_client.py generate` invocation via `--provider $IMAGE_PROVIDER`.

**Rationale:** Smallest blast radius. The CBORG `.env` parse already exists, is well-tested, and follows the `feedback_secret_file_handling` discipline (never echo values; extract single vars; strip matched quotes). Extending it costs ~5 lines of Python heredoc + a `while-read` loop in shell. A new `tools/auth_discovery.py` helper would have been over-engineered for two env vars; embedding the resolution in `image_client.py` would have duplicated the `.env` walk that the shell already does.

**Alternatives considered:**
- **`image_client.py` self-resolves** — rejected; duplicates the shell's `.env` walk.
- **New `tools/auth_discovery.py`** — rejected; over-engineered for two env vars + cross-language invocation cost.
- **`commands/configure.py`** (named in §14.2's original wording) — that file doesn't exist; would have been a third option but isn't built.

**Related:** [M5b_PUNCH_LIST.md](M5b_PUNCH_LIST.md) DQ1; [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §14.2; `tools/presentation_maker.sh` (auth-discovery + provider-precedence block, lines ~356-440); `tests/unit/test_orchestrator_image_provider.py` (13 tests pinning precedence + .env loading + defensive non-echo).

---

## D-063 — 2026-05-24 — M5b: AI Studio model probe caches in `audit/ai_image_gen_probe.json` sidecar (DQ2)

**Decision:** The AI Studio model-availability probe (M5b Tier C / D-035-rev1) caches its result in `<draft>/audit/ai_image_gen_probe.json`. Cache schema (`schema_version: "ai-image-gen-probe.v1"`):

  - `api_key_fingerprint`: short (8-hex) sha256 of the key; detects rotation without persisting the key.
  - `probed_at`: ISO-8601 timestamp.
  - `available_models`: full list returned by the probe (image-capable filter applied).
  - `resolved_model`: the chain-walk result (may be `null` → triggers D-064).
  - `from_override`: `true` if `GOOGLE_AI_STUDIO_MODEL` env var was used (probe skipped).
  - `chain_walked`: the D-035-rev1 fallback chain at the time of write.

Cache hit logic: same `schema_version` AND same `api_key_fingerprint` → return cached record (one HTTP probe per draft + key combination). Corrupt JSON re-probes defensively. `--force-refresh` re-probes unconditionally.

**Rationale:** Per-draft scope, one-time cost (~200ms HTTP). Doesn't depend on the still-settling v0.4 `state.json` schema (M6 will migrate v0.3→v0.4; adding fields now would risk rework). Matches the audit-file pattern used throughout v0.4 (`audit/review_cascade.json`, `audit/review_tier2.json`, `audit/visual_qa.json`, `audit/quantitative_grounding.json`, `audit/revise_invariance/<finding_id>.json`).

Fingerprinting the key (not persisting it) is the safety property — operators auditing the sidecar see only the first 8 hex chars of a SHA-256 hash, never the raw key. Collision resistance at that length is fine for the "did the key change?" use case (NOT cryptographic identity).

**Alternatives considered:**
- **`state.json` per-draft** (per §14.2's original wording) — rejected; couples to a schema that's in flux at M6.
- **No cache; probe every invocation** — rejected; burns AI Studio's rate-limit budget for a value that almost never changes mid-draft (~200ms per call × ~30 images = ~6s wall-clock saved per draft + free-tier quota preserved).
- **Workspace-level cache (one for all drafts)** — rejected; cross-draft staleness would silently mask a user changing their `GOOGLE_AI_STUDIO_API_KEY` between drafts.

**Related:** [M5b_PUNCH_LIST.md](M5b_PUNCH_LIST.md) DQ2; `tools/image_client.py::load_or_probe_ai_studio_model`, `_fingerprint_api_key`, `PROBE_SCHEMA_VERSION`; [SPEC.md](SPEC.md) §8.3.2 (probe + cache narrative); `tests/unit/test_image_client.py` (sidecar round-trip, key-fingerprint rotation, corrupt-cache recovery, schema-version pin).

---

## D-064 — 2026-05-24 — M5b: AI Studio probe-failure posture is hybrid (silent CBORG fallback if available; else loud-warning disable) (DQ3)

**Decision:** When the AI Studio probe finds no usable model in the D-035-rev1 fallback chain, behavior depends on whether CBORG is also configured:

- **`CBORG_API_KEY` set** → silent fallback to CBORG: override `IMAGE_PROVIDER=cborg` for the rest of this draft + emit a one-line stderr log: `[image-gen probe] AI Studio probe found no usable model; falling back to CBORG (silent fallback per D-064; CBORG_API_KEY is set)`. The image-gen stage proceeds.
- **No `CBORG_API_KEY`** → loud-warning disable: emit a multi-line stderr diagnostic naming each chain model with present/absent marker + image-capable models seen on the key + explicit actionable next steps (set `CBORG_API_KEY`, set `GOOGLE_AI_STUDIO_MODEL=<name>` to pin, or fix AI Studio access). Image-gen is disabled for this run (treat as `--no-images`).

The probe CLI emits `rc=5` for "no usable model" + writes the diagnostic to stderr; the orchestrator branches based on `${CBORG_API_KEY:+set}`.

**Rationale:** Preserves the user's stated intent ("use my Gemini Studio license if available" — §14.1) while not breaking the run when the license is misconfigured. The silent CBORG fallback IS the kindness — if we already have a working alternative, use it without forcing the user to re-invoke. The loud-warning branch ensures the user is NEVER silently downgraded without seeing exactly what was tried (which provider, which model chain, which env vars detected, what to do next).

The single-line "silent" fallback log message is still visible — it's not literally silent; it's just not a wall of text. Operators tailing stderr see the fallback happened; they don't get a 10-line diagnostic for a path that's working.

**Alternatives considered:**
- **Hard-fail on probe failure** (matching D-035's original "→ fail" terminator) — rejected; too brittle when CBORG is available as an obvious fallback.
- **Always silent fallback to CBORG (when set)** with no log — rejected; operators need to see the fallback happened, even briefly.
- **Always disable image-gen on probe failure** — rejected; ignores Adam's stated intent; CBORG is a working path.

**Related:** [M5b_PUNCH_LIST.md](M5b_PUNCH_LIST.md) DQ3; [SPEC.md](SPEC.md) §8.3.2 (D-064 narrative); `tools/image_client.py::format_probe_failure_diagnostic`, `_cmd_probe` (rc=5 + stderr); `tools/presentation_maker.sh::stage_image_gen` (probe block + hybrid branching); `tests/unit/test_image_client.py` (diagnostic tests for both branches; CLI rc=5 pin).

---

## D-065 — 2026-05-24 — M6: drop metric 7 (paper-review skill quality) from the A/B cut-over gate (DQ2)

**Decision:** Drop §15 metric 7 ("Paper-review skill quality assessment of the deck's narrative arc") from the M6 A/B cut-over decision rule. The adjusted decision rule: v0.4 must dominate v0.3.8 on **≥4 of 6** metrics (was ≥5 of 7); primary wall-clock metric remains mandatory.

**Rationale:** There is no skill named `paper-review` in the workspace. The §15 reference was a phantom dependency carried over from `SPEC_v0_8.md`'s pattern. The paper-writer skill drafts manuscripts; the adversarial skill reviews; neither has a "paper-review" verb that operates on presentations. Building one for M6 alone is out of scope (and unclear what the contract would even be — paper-writer expects a manuscript; an unedited deck's speaker-notes export isn't quite the same shape).

**Alternatives considered:**
- **Build `tools/m6_review_pass.py` that re-runs adversarial with narrative-quality filter** — rejected as duplicating metric 3 (adversarial findings count). The filter logic would be subjective and would itself need calibration.
- **Replace metric 7 with "Adam reads both decks and rates quality 1–5"** — rejected as overlapping metric 5 (cross-substory arc coherence; also Adam-subjective). Two subjective metrics from one reader on the same input is double-counting.
- **Defer the metric to v0.4.1 once a paper-review skill exists** — rejected as kicking the decision down the road. The cut-over gate needs to be runnable now.

**Related:** [M6_PUNCH_LIST.md](M6_PUNCH_LIST.md) DQ2; [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §15 (the original 7-metric list; this DECISION supersedes the metric-7 line); `tools/m6_score.py` (M6 Tier A; implements the 6-metric scoring + the ≥4/6 decision-rule check).

---

## D-066 — 2026-05-24 — M6: Adam-veto is explicit; the ≥4/6 metric rule is advisory (DQ4)

**Decision:** The M6 cut-over decision is **panel-of-one-final**. The ≥4/6 metric rule (per D-065) + the wall-clock primary gate are **advisory**; Adam reads both pairs of decks (ibd_phage_targeting v0.3 vs v0.4; functional_dark_matter v0.3 vs v0.4) and casts an explicit veto either way. Three veto outcomes:

- **Ship**: v0.4 becomes default; v0.3 prompts move to `prompts/archive/v0_3/`.
- **Don't ship**: v0.4 stays opt-in via `--architecture-pipeline v0_4`; v0.3 remains default; failed-metric follow-ups filed.
- **Ship-but-flag**: v0.4 becomes default but a stderr warning prints "v0.4 pipeline (experimental — known regressions: X, Y)" for one release.

The veto can override the count either direction: ship despite missing a metric if the failure is non-substantive; don't-ship despite dominating ≥4/6 if Adam reads the decks and judges v0.4's narrative inferior.

**Rationale:** Per the augmentation-stream project's panel-of-one posture. Mechanical scores aggregate signals but don't capture the actual ship-quality judgment — that's the human reviewer's job. The score rule exists to keep the decision *honest* (forces concrete metric capture; surfaces tradeoffs) rather than to *make* the decision.

**Alternatives considered:**
- **Hard "≥4/6 OR fail" rule** with no veto — rejected; under-specifies what to do on edge cases (e.g., 4/6 with a major adversarial regression vs 4/6 with all-positive deltas of varying magnitude).
- **Second hard gate: metric 3 cannot regress >20%** — rejected; encodes a specific concern (adversarial regression) into the gate rule, but the same logic could apply to any metric. Better to let the human reviewer handle individual-metric concerns.

**Related:** [M6_PUNCH_LIST.md](M6_PUNCH_LIST.md) DQ4 + Tier D (Adam-veto decision artifact); [V0_4_ARCHITECTURE.md](V0_4_ARCHITECTURE.md) §15 (the original mechanical rule wording); D-065 (the ≥4/6 adjusted rule this veto can override).

---

## D-067 — 2026-05-24 — M6 Tier 0: drop the v0.3 → v0.4 state-schema migration deliverable; D-038 obsoleted

**Decision:** The "state-schema v0.3 → v0.4 migration script" deliverable named in §16 M6 (and ratified at M0 as D-038) is **dropped from M6 entirely**. No migration script is built; no centralized `state.json` is introduced for presentation-maker. D-038 is obsoleted as written. The orchestrator-canonical state model (variables + per-stage audit JSONs) remains the contract.

**Rationale (M6 Tier 0 investigation, 2026-05-24):**

1. **No v0.3 schema exists to migrate FROM.** Presentation-maker has never had a centralized `state.json`. The orchestrator's own comment at `presentation_maker.sh:19` says "no centralized state.json yet — the orchestrator is canonical." `find ... -name 'state.json'` in `talks/` returns zero files across all projects. D-038 was framed as "v0.3 → v0.4 migration" but the v0.3 schema to migrate FROM doesn't exist.

2. **M6 A/B scoring doesn't need state.json.** The data needed for metrics 1, 2, 3, 4, 6 is already on disk in per-stage audit JSONs and per-run summaries:
   - `audit/runs/run-N/summary.json` (schema `run-summary.v1`, written by `finalize_run.py` via an EXIT trap): `total_elapsed_seconds`, `total_cost_usd`, `total_input_tokens`/`output_tokens`, `stages_run`, `exit_code` — metrics 1 + 2.
   - `audit/stage-metadata.json` (schema `stage-metadata.v1`): per-stage cost/tokens/wall-clock — finer-grained breakdown.
   - `audit/review_cascade.json`: tier-3 adversarial findings — metric 3.
   - `audit/presentation_validation.json`: P1–P10 violations — metric 4.
   - `audit/image_provenance.json`: per-image costs — metric 6.

3. **No operational request for resume-with-state-restore.** A grep across auto-memory turned up zero `feedback_*_state_*` or similar entries. The only `state.json` reference in memory was MY OWN deflection in M5b D-063 ("doesn't couple to the still-settling state.json schema"). Resume-from-stage today works on file-presence (`validate_resume_prereqs` checks for upstream artifacts on disk; no state needed).

4. **Paper-writer's pattern is real value but a different scope.** Paper-writer's `state.py` is 687 lines: `DraftState` with 13 fields, `ArtifactHash` + `compute_artifact_hashes` + `diff_artifacts` for hash-based source-change detection, `is_user_edited` for user-edit detection on writer-generated manuscripts. The value proposition is "re-run `continue`, paper-writer reports which source artifacts changed since last build, refuses to silently overwrite user edits." Presentation-maker's source surface is different (REPORT.md + notebooks + figures vs paper-writer's manuscript pipeline) and the user-edit-detection isn't applicable to a deck (slide_spec.json is generated end-to-end per run, not iteratively edited). Adopting paper-writer's pattern at scale would be a v0.5 milestone, not an M6 deliverable.

**Alternatives considered:**

- **(b) Adopt paper-writer pattern at scale** — rejected for M6 (3–5 days of work; pushes M6 substantially; no demonstrated user need). Could be a v0.5 milestone if hash-diff source-change detection becomes valuable.
- **(c) Lightweight state.json without hash-diff** (~1 day, fits in M6) — rejected; the data it would capture is already in `runs/run-N/summary.json` + `stage-metadata.json`. Duplicating means two sources of truth + drift risk. The "lightweight state.json" would be solving a problem we don't have.

**Related:** [M6_PUNCH_LIST.md](M6_PUNCH_LIST.md) DQ1 + Tier 0 (this investigation); D-038 (2026-05-12 M0 decision; **OBSOLETED** by this DECISION); D-040 (Phase enum from paper-writer; the corresponding port for presentation-maker is also moot per this DECISION); paper-writer `src/beril_paper_writer/state.py` (687 lines; reference implementation NOT being adopted here); `tools/finalize_run.py` (the actual mechanism: writes `audit/runs/run-N/summary.json` on EXIT trap; `run-summary.v1` schema); `tools/presentation_maker.sh:19` (line that names the orchestrator-canonical posture).

---

## D-068 — 2026-05-25 — M6 Tier C.1: demote `data_figure` caption cap from hard error to soft-warning

**Decision:** `tools/slide_spec.py::_check_data_figure` emits `severity="soft-warning"` (not `severity="error"`) for `data_figure` captions exceeding `DATA_FIGURE_CAPTION_MAX_CHARS=280`. The 280-char threshold remains; only the validator severity changes. Matches the M4a Tier B / DQ4 / D-053 posture for the other four length caps (`BIG_NUMBER_SUBTITLE_MAX_CHARS`, `WORKFLOW_STEP_CAPTION_MAX_CHARS`, `QA_ANSWER_SUMMARY_MAX_CHARS`, `DIAGRAM_NODE_LABEL_MAX_CHARS`).

**Rationale (live-triggered at M6 Tier C, 2026-05-25):**

1. **Original v0.3.5 hard-error motivation is obsolete.** The hard cap was added 2026-05-04 after `gene_function_ecological_agora` draft_1 slides 21+23 produced ~410-char captions that overflowed past the `data_source` band and bled into the y=5.00 brand strip. At that time, `assemble_pptx._fill_data_figure` did NOT set shrink-to-fit on the caption textbox; the validator was the only safety net. That changed: `_fill_data_figure` now sets `MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE` on the caption textbox, absorbing long captions visually. The original "no fallback" premise no longer holds.

2. **Prompt-vs-code mismatch.** `slide_compose.v1.md` + `.v2.md` both say *"the validator will flag captions over 280 chars at advisory severity"* — but the code emitted `error` severity. The prompts promised soft-warning behaviour the code didn't deliver.

3. **Live trigger.** M6 Tier C: fdm v0.4 (`functional_dark_matter` talks/draft_3) slide 13 caption was 290 chars (10 over the cap). Pipeline hard-failed at merge/assemble; no `.pptx` delivered. v0.3 on the same project produced 273-char captions (within band but close). Both pipelines can stochastically land in the 280-300 range; ~3% of runs hard-failing for a render artifact that shrink-to-fit absorbs is too brittle a posture for a soft constraint.

4. **Matches existing length-cap posture.** D-053 / M4a DQ4 established soft-warning as the right severity for length caps the renderer can absorb. This decision aligns `data_figure caption` with the same rule.

**Alternatives considered:**
- **Lower the threshold (e.g., 200 chars) + keep hard-error.** Rejected — makes the prompt unreachable; LLMs will hit the limit constantly + the revise-loop will spend tokens re-shortening for a render concern shrink-to-fit handles.
- **Keep hard-error + remove shrink-to-fit on data_figure captions.** Rejected — visual regression for a marginal correctness gain.
- **Two-tier (soft at 280, hard at 400).** Rejected — adds complexity without clear value; if shrink-to-fit works at 290, it works at 400.

**Related:** [M6_PUNCH_LIST.md](M6_PUNCH_LIST.md) Tier C.1; D-053 (M4a Tier B / DQ4 — the soft-warning posture for the other length caps); `tools/slide_spec.py::_check_data_figure` + `DATA_FIGURE_CAPTION_MAX_CHARS` docstring; `tools/assemble_pptx.py::_fill_data_figure` (the load-bearing shrink-to-fit fallback); `tests/unit/test_slide_spec.py::test_data_figure_caption_demoted_to_soft_warning` (regression pin); `prompts/slide_compose.v1.md` + `.v2.md` (the prompts that already said "advisory").

---

## D-069 — 2026-05-25 — M6 Tier D outcome: don't ship v0.4 as default; v0.4 stays opt-in via `--architecture-pipeline v0_4`

**Decision:** v0.4 (architect-then-parallel-compose) does NOT become the default pipeline. v0.3 (sequential per-substory) remains the default. v0.4 is available via the existing opt-in flag: `presentation_maker.sh --architecture-pipeline v0_4 ...`. The skill ships as `v0.4.0-experimental` (per D-066 Adam-veto third option: "ship-but-flag" semantics — except framed at the version-tag level rather than per-run stderr warning, since the opt-in flag itself is the user-visible gate).

**Mechanical M6 result (per D-065 + D-066 rule; complete report at `/tmp/m6_final_report.md`, regenerable via `tools/m6_score.py`):**

| Project | Role (D-041) | v0.4 wins | Wall-clock Δ | Cost Δ | Adv findings Δ |
|---|---|---|---|---|---|
| `ibd_phage_targeting` (target) | must dominate ≥4/6 | **2/6** (wall-clock + adversarial) | **-15.2%** | -3.0% (tie) | -47.1% |
| `functional_dark_matter` (sanity) | second data point | **3/6** (wall-clock, cost, validators) | **-36.7%** | **-41.9%** | **+33.3% (v0.3 wins)** |

- v0.4 wins 2/6 on the target — **needs ≥4/6** to pass the count rule. Mechanical FAIL.
- Max wall-clock reduction is -36.7% on fdm — **needs ≥40%** to clear the primary gate. Mechanical FAIL.
- Metric 5 (Adam-subjective arc coherence): target tied at 2/5 (both pipelines equally poor); sanity v0.3=3, v0.4=2 (v0.4 regressed).

**Adam-veto rationale (the actual decision, per D-066):**

The mechanical FAIL is consistent with the qualitative read. Three substantive findings drove the veto:

1. **v0.4 doesn't help on ibd narrative coherence.** Both ibd drafts equally poor on overall arc + story. The architecture pivot doesn't pay off where the deck was already weak on narrative shape; speeds it up + reduces token cost without improving the user-facing artifact.

2. **v0.4 actively regresses on fdm.** Adam read fdm v0.3 (draft_2) as significantly better than v0.4 (draft_5). Cross-slide consistency loss: adversarial flagged 2 P0 `unbacked_quantitative` findings on the SAME wrong denominator (`10/137` on slides 11 + 14; REPORT says `10/151`) — the parallel-compose architecture composed those slides independently and both fabricated the same error. v0.4 also introduced 2 `substory_arc` P1s (v0.3 had 0): per-substory workers compose without seeing the substory-level arc shape, so closes break. These are exactly the failure modes parallel-compose worries about; M6 surfaced them empirically.

3. **The bigger issue is upstream of v0.4 vs v0.3.** Adam's read named the load-bearing weakness: *"Overall arc and stories are obscure. Substory division is OK but could be sharper, but in no case is the question → clear analysis → results → conclusions clear. We get walls of text poisoned by specialist reference to, for example, specific notebooks rather than a general analytical discussion. The stories don't build and/or aren't brought together to make an overall point."* This is **present in both pipelines on both projects** — it's a v0.3-inheritance content-shape problem, not a v0.4 architectural one. v0.5 will address it (see D-070).

**Implications:**

- v0.4 code paths remain live + supported. `--architecture-pipeline v0_4` users get the speed/cost wins; ibd users see fewer adversarial findings; fdm users should NOT use v0.4 (or should be ready to manually correct cross-slide numeric drift + substory arc closes).
- v0.3 remains the default. The v0.3 default-prompt set stays in `prompts/` (NOT moved to `prompts/archive/v0_3/`); v0.3.x continues to evolve alongside v0.4.x until v0.5 supersedes both.
- Skill ships as `v0.4.0-experimental` git tag — captures the architectural work + the cut-over framing (not-default, opt-in) explicitly. Avoids the misleading "v0.4.0" tag that would imply default-pipeline cut-over happened.

**Alternatives considered:**

- **Ship as default ("ship" veto option).** Rejected; the fdm regression is real + the underlying content-shape weakness affects both pipelines equally. Promoting v0.4 doesn't fix what's broken; it just locks in the regression on the fdm-shape projects.
- **Ship-but-flag with stderr warning per run.** Rejected as the wrong framing; the version-tag (`v0.4.0-experimental`) + opt-in flag together communicate the same "not-default" status without adding per-run noise to operators who explicitly chose v0.4.

**Related:** [M6_PUNCH_LIST.md](M6_PUNCH_LIST.md) Tier D; D-041 (target vs sanity project assignment); D-065 (≥4/6 rule); D-066 (Adam-veto explicit final); D-068 (M6 Tier C.1 caption demote — necessary for fdm v0.4 to render at all); D-070 (v0.5 scope opening — addresses the upstream content-shape weakness); `tools/m6_score.py` + `audit/runs/run-N/summary.json` (the data infrastructure that surfaced the result honestly).

---

## D-070 — 2026-05-25 — M6 closeout: open v0.5 as a content-discipline milestone (not architectural)

**Decision:** v0.5 is scoped as a **content-discipline** milestone, NOT another architectural pivot. The framing is: "v0.3 is sequential per-substory; v0.4 is architect-then-parallel-compose; v0.5 doesn't touch the per-substory dispatch — it rewrites the per-substory + cross-substory CONTRACTS the dispatch operates over." v0.5 punch list at `V0_5_PUNCH_LIST.md` captures the scope.

**Rationale (from M6 Tier D Adam read):**

The M6 A/B surfaced that v0.4 vs v0.3 was the wrong question. Both pipelines feed identical prompts + per-slide layout vocabulary; neither produces the **Question → Analysis → Results → Conclusions** narrative shape Adam expects from a scientific presentation. Specifically:

- **Substory shape is undefined.** `substory_design.v1.md` asks for a punchline + slide map; doesn't require the substory to answer one Q with one A and hand a question forward to the next substory.
- **Specialist-register leakage.** Notebook IDs (`NB10 §3`), figure file names (`F03_recovery_by_method.png`), REPORT.md-style citations leak into audience-facing slide prose where general analytical statements belong. No validator catches register drift; the slide_compose prompts are evidence-grounded but not audience-aware.
- **Cross-substory bridging is templated.** `section_divider` slides are boilerplate; the substory `punchline` field is the only between-substory text + adversarial repeatedly flagged it as filler ("S2 punchline is filler — names no specific finding, no specific numbers").
- **Figure utilization is decorative, not evidentiary.** Figures are present but don't drive the slide's claim; the `data_figure` layout doesn't enforce "the figure IS the evidence for this slide's title."

**Initial v0.5 scope (open for refinement during v0.5 punch-list DQ surfacing):**

1. **Substory-shape contract** — Q/A/R/C per substory + cross-substory question handoffs. New `substory_design.v2.md` + `tools/check_substory_shape.py` post-check.
2. **Register-discipline validator** — detect specialist references (notebook IDs, file paths, internal artifact names) in audience-facing slide prose. New `tools/check_register_discipline.py` + soft-warning by default.
3. **Cross-substory throughline-bridge pass** — rewrite `section_divider` slides + substory openings to explicitly carry the question forward. New `prompts/throughline_bridge.v1.md` + `tools/bridge_substories.py`.
4. **Figure-utilization contract** — enforce "figure is evidence for the slide's claim" on `data_figure` + `concept_illustration`. Likely a new `tools/check_figure_provenance.py` or extension to `validate_p1_p10`.

**What v0.5 explicitly does NOT do:**

- Touch the per-substory dispatch (parallel vs sequential is settled — v0.4 opt-in flag stays; both modes feed the same v0.5 contracts).
- Re-litigate the v0.4 architecture (D-069 settled that v0.4 stays opt-in; nothing in v0.5 changes that posture).
- Add a new image-gen provider, validator framework rewrite, state.json migration, or other infrastructure work. v0.5 is content-shape only.

**Alternatives considered:**

- **Skip v0.5; treat as v0.4.1 carry.** Rejected; the content-shape work is too large to be a "tidy" release. The three v0.5 sub-deliverables each warrant punch-list-tier scope.
- **Make v0.5 an architectural rewrite (e.g., agentic deck-architect via Agent SDK).** Rejected; the M6 Tier D read says the problem is content-shape, not orchestration. Re-architecting the orchestration doesn't fix walls of text or arc obscurity.
- **Defer v0.5 indefinitely; ship v0.4-experimental + walk away.** Rejected per Adam's call 2026-05-25 ("Let's review the full deck creation strategy"); the M6 finding is too valuable to leave un-acted-upon.

**Related:** [M6_PUNCH_LIST.md](M6_PUNCH_LIST.md) Tier D (the Adam read that drove this); D-069 (v0.4 ships as experimental; v0.5 is the next default-target); D-066 (Adam-veto pattern continues at v0.5 cut-over); [V0_5_PUNCH_LIST.md](V0_5_PUNCH_LIST.md) (v0.5 scope + DQs); auto-memory `project_presentation_maker_v0_4_m6.md` (M6 retrospective including the read that drove v0.5 framing).

---

## D-071 — 2026-05-25 — v0.5 Tier 0 / DQ1: Q/A/R/C contract shape — slide-shape mapping (middle ground)

**Decision:** v0.5's substory Q/A/R/C contract is implemented as **slide-shape mapping** per V0_5_PUNCH_LIST.md DQ1 option (b). Each substory gets explicit slide-role slots: Q-slide, A-slide(s), R-slide(s), C-slide. The composer picks which layouts (from the existing 16-layout vocabulary) fill each slot — preserving layout flexibility while enforcing the analytical arc.

New substory-level metadata fields in `substory_design.v3.md` output:
- `question:` — the one scientific question this substory answers (≤25 words; mandatory).
- `conclusion_for_next_substory:` — one-sentence handoff to next (≤25 words; mandatory unless this is the final substory).
- `slide_roles:` (implicit via slide ordering; Q-slide is position 0 or 1 of the substory, A-slide(s) follow, R-slide(s) follow, C-slide is the substory's last content slide before the next divider).

**Rationale:**

1. **Today's contract has zero arc-shape.** Tier-0 audit: all four M6 drafts (ibd+fdm, v0.3+v0.4) have `**Punchline:**` fields but ZERO `**Question:**`, `**Conclusion:**`, or `**Handoff:**` fields. The substory_design.v1.md template asks for punchline + critical-analyses list + cluster rationale — no analytical-arc field. The Adam M6 read ("no question → analysis → results → conclusions") is structurally caused: the contract doesn't ask for those, so the LLM doesn't emit them.

2. **Option (a) substory-level explicit Q/A/R/C fields** rejected: too rigid — forces a 4-slot decomposition even when a substory's natural shape is more like 1 Q-slide + 3 R-slides + 1 C-slide. The slide-role-via-position approach (b) gives the composer flexibility while still enforcing the question + conclusion fields.

3. **Option (c) soft framing in prompt only** rejected: today's prompt already SAYS "tell a story" without enforcing structure; the result is what M6 surfaced. Soft framing without field-level enforcement doesn't change LLM behavior reliably.

**Alternatives considered (with detail):**

- **(a) Substory-level Q/A/R/C fields with mandatory 4 fields**: rejected as documented above; over-engineered.
- **(c) Prompt-only ("organize the slide map as a Q→A→R→C arc")**: rejected as documented above; v0.3 prompts already gestured at narrative discipline without enforcement and produced the M6 result.
- **(d) Per-slide role tag** (each slide has `slide_role: Q|A|R|C`): considered but rejected as adding complexity to slide_spec without adding capability beyond (b).

**Related:** [V0_5_PUNCH_LIST.md](V0_5_PUNCH_LIST.md) DQ1 + Tier A; D-070 (v0.5 scope); M6 Tier D Adam read (the gap this addresses); `prompts/substory_design.v1.md` (the v0.5 Tier-A target for v3 rewrite); Tier-0 audit script in this session (all 4 M6 drafts had 0 question fields).

---

## D-072 — 2026-05-25 — v0.5 Tier 0 / DQ2: register-discipline heuristic is field-class-aware soft-warning

**Decision:** The register-discipline validator (`tools/check_register_discipline.py`, v0.5 Tier A.1) is **field-class-aware**: distinct severity rules for operator-facing fields (`data_source`, `notes`) vs audience-facing fields (`title`, `headline`, `subtitle`, `caption`, `bullets`, `answer_summary`, `step_caption`, etc.) vs structural fields (`workflow_diagram.nodes[].label`, `methods_summary.method_*`). Lands as **P11** validator (next slot after P10). Severity: **soft-warning** by default per D-053 / M4a Tier B posture; per-project allowlist mechanism.

**Heuristic specification (per Tier-0 audit data):**

| Pattern | Regex | Operator-field severity | Audience-field severity |
|---|---|---|---|
| Notebook IDs (`NB##`, `NB##b`) | `\bNB\d+\w?(?:\s*§\d+)?\b` | allowed | **soft-warning** |
| Notebook filenames (`##_name.ipynb`) | `\b\d{2}_\w+\.ipynb\b` | allowed | **soft-warning** |
| REPORT section markers (`§Finding N`, `§Step N`) | `§(?:Finding\|Step\|Interpretation\|Hypothesis)\s+\d+` | allowed | **soft-warning** |
| Notebook cell refs (`cell N`) | `\bcell\s+\d+\b` | allowed | **soft-warning** |
| Figure filenames (`fig##_*.png`) | `\bf?ig?\d{1,3}[a-z]?_\w+\.(?:png\|jpg\|svg\|pdf)\b` | allowed | **soft-warning** |
| Tool versions (`Bakta v1.12.0`) | `\b[A-Z][a-z]+\s+v\d+(?:\.\d+){1,3}\b` | allowed | allowed (audience-relevant) |
| Schema versions (`slide_spec.v1`) | `\b[a-z_]+\.v\d+\b` | allowed | **soft-warning** (rarely needed in audience prose) |

**Allowlist mechanism (per-project escape hatch):**
- A `references/register_allowlist.md` file at the project root may list terms that the validator permits in audience-facing prose for that talk. Format: one allowed term per line, free text.
- Allowlist applies only to audience-facing fields. Operator fields don't need an allowlist (everything is allowed there).
- Allowlist matches as literal substring (case-sensitive) — keeps the matcher simple; project-specific (e.g., "RAST", "Bakta" could be permitted if a particular talk needs to name the tool).

**Output:** `audit/presentation_validation.json` gains a `P11` entry (matches the M4b cascade Tier-1 aggregator's expected validator shape); soft-warning per-slide entries reference the specific pattern + the field; cascade Tier-1 reads it and surfaces as advisory.

**Rationale (per Tier-0 audit on 4 M6 drafts):**

1. **Field-class matters.** Many notebook-ID violations live in `data_source` fields, which are intentional operator-facing provenance (e.g., `"data_source": "REPORT.md §Finding 13; 09_final_synthesis.ipynb"`). A flat "no NB-refs anywhere" rule would generate huge false-positive volume. Audit data: ibd-v0.3 has 3 op-field NB-refs vs 8 audience-field — only the latter are the bug.

2. **Project-dependent severity.** ibd-v0.4 had MORE audience-field NB-refs (18) than v0.3 (8); fdm-v0.4 had FEWER (1 vs 9). Project-dependent + pipeline-dependent — needs a tunable allowlist, not a hard-coded blocklist.

3. **Tool names + audience-relevance.** "Bakta v1.12.0" sometimes IS what the audience needs (the talk's contribution is "annotation tool version matters"); sometimes it's specialist leakage. The default rule for tool-version names is **allowed** (don't false-positive flag); the allowlist lets a project add specific tools to a no-list if its talk is general-audience.

4. **Soft-warning matches D-053 / M4a Tier B precedent.** The 4 existing length-cap validators are soft-warning; the renderer/audience absorbs minor noise; revise-loop can act on them via the M4b cascade. Same posture here. The bar to promote to error is "M6-style cut-over A/B shows soft-warning is being ignored at high enough rate to materially degrade decks" — TBD post-v0.5 ship.

**Alternatives considered:**

- **Hard error severity by default** — rejected; would force revise-loop iteration on every register-flag, eating tokens; matches paper-writer's posture for some pre-publication blocks but not appropriate for a talk-presentation skill where shrink-to-fit-equivalent (audience reads with author present) absorbs minor noise.
- **Per-project blocklist instead of allowlist** — rejected; more verbose to maintain (need to list every notebook ID per project vs allowing once).
- **No allowlist at all** — rejected; some projects have legitimate audience-relevant tool/version references; the validator must let those through.
- **LLM-as-judge for register classification** — rejected as over-engineered for a v0.5 first cut; regex + allowlist is the cheap correct heuristic.

**Related:** [V0_5_PUNCH_LIST.md](V0_5_PUNCH_LIST.md) DQ2 + Tier A.1; D-053 (M4a Tier B / DQ4 soft-warning posture for length caps); D-068 (M6 Tier C.1 data_figure caption demote to soft-warning); Tier-0 audit script in this session (4-draft inventory + field-class split); M4b `review_cascade.py::_validate_p1_p10` (the integration point where P11 plugs in).

---

## D-073 — 2026-05-25 — v0.5 Tier 0 / DQ3: substory-shape enforcement via cascade Tier-2 finding (not hard error)

**Decision:** `tools/check_substory_shape.py` (v0.5 Tier B) emits findings into the M4b review cascade as **`kind=substory_arc` Tier-2 entries** at severity **P1** — NOT as a `validate_slide_spec` hard error. Matches the M4b cascade's narrative-light posture; revise_loop can act on it without halting the pipeline.

**Operational contract:**

- Substory-shape findings appear in `audit/review_cascade.json::tiers[1].findings[]` with `kind=substory_arc`, severity `P1`, and a `slide_id` pointing at the substory's representative slide (Q-slide or C-slide depending on which structural element is missing).
- Reuses the existing `substory_arc` class beril-adversarial already emits (v3 schema; first surfaced at M5b — see M6 retrospective fdm-v0.4 findings F011, F012).
- Cascade Tier-2 (Haiku narrative-light) augments the existing 4 detection classes per M4b D-056; substory-shape is the 5th.
- Soft, NOT hard: missing-Q, missing-C, or broken-handoff doesn't fail the pipeline — it surfaces in the cascade output for revise_loop OR operator inspection.

**Rationale:**

1. **Matches narrative-light tier posture (D-049, M4b).** The cascade's Tier 2 is explicitly for narrative-quality checks that don't gate the pipeline; substory-shape is a narrative-quality check by definition.
2. **Leverages existing infrastructure.** The cascade JSON consumer (review_cascade.v1) already supports new finding classes per D-056 ship-then-iterate posture. No new schema; no new orchestrator stage.
3. **Soft enforcement matches D-072.** Same posture as register-discipline: revise-loop OR operator can act on it; pipeline doesn't halt; promote to hard-error only if v0.5 A/B shows soft enforcement is insufficient.

**Alternatives considered:**

- **(a) Hard error in `validate_slide_spec`** — rejected; forces revise-loop iteration; halts pipeline; over-rigid for the first v0.5 ship.
- **(b) Soft-warning in `audit/presentation_validation.json` (the P-validator surface)** — rejected; P-validators are mechanical/structural; substory-shape is narrative-quality; goes in the cascade Tier 2 surface where narrative-quality findings live.
- **(d) Adversarial v3 finding class** — paper-writer-style "let beril-adversarial flag it" — rejected; the substory-shape check is deterministic + can run pre-adversarial; no need to spend adversarial LLM cost on it.

**Related:** [V0_5_PUNCH_LIST.md](V0_5_PUNCH_LIST.md) DQ3 + Tier B; D-049 (M4b cascade narrative-light tier); D-056 (cascade ship-then-iterate; v2 expansion candidates included substory_arc); `tools/review_cascade.py::run_tier1` (the integration point); M4b retrospective (the cascade infrastructure substory_shape integrates into); beril-adversarial v3 schema (defines the `substory_arc` finding class this reuses).

---

## D-074 — 2026-05-25 — v0.5 Tier 0 / DQ4: `--prompts-version` defaults to v2 until v0.5 A/B passes; flips to v3 at Tier E ship

**Decision:** New orchestrator flag `--prompts-version {v1,v2,v3}` defaults to **v2** at v0.5 initial ship (matching D-069 v0.4 opt-in posture). Adam-veto at Tier E decides whether to flip the default to v3 in a follow-up v0.5.1 release. Operators can mix-and-match `--prompts-version` with `--architecture-pipeline` (independent axes); 4-way matrix (v1×v0_3, v1×v0_4, v2×v0_3, v2×v0_4, v3×v0_3, v3×v0_4) supported but the cut-over A/B compares against the v0.3/v0.4 baselines on disk from M6.

**Rationale:**

1. **Matches D-069 v0.4 opt-in posture.** Adam-veto rationale for D-069 was "the architecture pivot's wins on speed/cost don't outweigh the quality regressions; ship as opt-in, default unchanged." Same logic applies pre-v0.5-cut-over: ship v3 prompts as opt-in; flip default only if Tier E veto passes.
2. **Conservative for operational users.** Users between v0.4-experimental ship and v0.5 cut-over should see no behavior change unless they explicitly opt in to v3.
3. **Independent axes.** `--prompts-version` and `--architecture-pipeline` are orthogonal: v3 prompts work under either v0_3 (sequential) or v0_4 (parallel-compose) dispatch. The 4-way matrix isn't fully exercised but Tier C/D will at least run v3×v0_3 vs the v0.3 baseline.

**Alternatives considered:**

- **(a) Default to v3 at v0.5 ship** — rejected; assumes Tier E veto outcome before it happens; same mistake as M6 v0.4 would have been if we'd shipped as default.
- **(c) v3 only on architecture=v0_4 (couple to the experimental axis)** — rejected; couples two orthogonal axes for no benefit; if v3 prompts work cleanly on v0_3 sequential dispatch, they should be available there.

**Related:** [V0_5_PUNCH_LIST.md](V0_5_PUNCH_LIST.md) DQ4 + Tier A.3 (flag wiring); D-069 (v0.4 opt-in posture v0.5 mirrors); D-066 (Adam-veto pattern continues at v0.5 cut-over Tier E); `tools/presentation_maker.sh` `--architecture-pipeline` flag (the precedent dispatch shape); v0.5 Tier E (the gate for default-flip).

---

## D-075 — 2026-05-26 — v0.5.1 Tier 0 / DQ1: v3 prompts compose via runtime concatenation of v2 body + v3 overlay

**Context:** v0.5 Tier C/D live A/B on 2026-05-26 morning hard-failed
at schema validation with 21 identical `required field missing`
errors per run on both ibd + fdm. Root cause: `slide_compose.v3.md`
is a 380-line standalone prompt that describes v2's per-layout
authoring rules as "(Unchanged from v2)" without including the
~900-line body. The orchestrator passes the v3 file as
`--system-prompt` (presentation_maker.sh:730); the LLM has zero
access to v2 when running v3, so it hallucinates field names
(`title`/`subtitle` instead of v2's `punchline`/`substory_number`
for `section_divider`; `headline` instead of layout-specific names
for `big_number`; etc.). See
`project_presentation_maker_v0_5_morning_abort.md` for the full
forensic record.

**Decision:** Restructure v3 as a runtime concatenation of v2's
full body + a small v3 overlay file. Specifically:

- `prompts/slide_compose.v3.md` is renamed to
  `prompts/slide_compose.v3_overlay.md` (~150 lines) containing
  ONLY the v3-additive sections: header banner, register-discipline
  preamble (D-072), Q/A/R/C role guidance (D-071), post-composition
  self-check, anti-patterns, and the v3-additions to "Inviolable
  rules."
- `prompts/substory_design.v3.md` gets the same treatment per
  DQ4 inspection (also a standalone-with-disclaimers problem;
  see D-078).
- `_slide_compose_prompt_path` (in `tools/presentation_maker.sh`)
  for `PROMPTS_VERSION=v3` emits a concatenated temp file =
  `cat slide_compose.v2.md slide_compose.v3_overlay.md` written
  to `audit/_prompts/slide_compose.v3.concat.md` (per project)
  once at orchestrator start. Cached for the run; cleaned up at
  EXIT trap. Same for `_substory_design_prompt_path`.
- Concat order: **v2 first, overlay last.** The LLM's attention
  is strongest at the tail of the system prompt; putting the
  overlay last lets it override v2 on conflicts (e.g., the
  register-discipline rule).

**Rationale:** The LLM running v3 needs to see v2's per-layout
field names verbatim — anything less is hallucination-bait. The
concat fix gives v3 the LLM-attention parity of a full self-contained
prompt without the maintenance drift risk of a v2-cloned-and-edited
file (which would diverge every time v2 gets a fix). The
implementation is small (~30 min of dispatcher work + 5 min of
EXIT-trap cleanup); the prompt-token cost increase is ~10% of
system-prompt size (~140 of ~1400 lines added); user-prompt and
tool-results dominate the per-invocation cost so the impact is
negligible. The pattern is also reusable for any future "vN-as-
overlay-on-vN-1" prompt-version transition.

**Alternatives considered:**

- **(b) Self-contained clone (v2 → v3 + inline overlays)** —
  rejected; produces a ~1400-line standalone v3.md that every
  future v2 fix must be ported to manually. Drift risk in the
  near term (we're actively iterating on v2 prompts per M4b
  Tier-2 calibration carry items). The concat fix is strictly
  better unless the temp-file lifecycle proves unworkable, which
  it isn't — the orchestrator already uses similar per-run
  artifacts under `audit/_prompts/` and `audit/snapshots/`.
- **(c) Runtime overlay via user-prompt heredoc** — rejected;
  asymmetric attention weight between system + user prompt
  weakens the v3 overlay enforcement (Anthropic guidance: system
  prompt anchors model behavior; user prompt is "data + per-call
  instructions"). The overlay IS authoring guidance, which
  belongs in system. The morning abort suggests the v3 overlay
  rules need MORE attention weight, not less.

**Related:** [V0_5_1_PUNCH_LIST.md](V0_5_1_PUNCH_LIST.md) DQ1 + Tier
A; D-074 (`--prompts-version` flag — unchanged); D-072
(register-discipline scope); D-071 (Q/A/R/C contract scope);
`prompts/slide_compose.v2.md` (the authoritative per-layout
vocabulary v3 must inherit); `tools/presentation_maker.sh:730`
(the single-cat-file invariant the concat fix preserves);
`project_presentation_maker_v0_5_morning_abort.md` (root cause
+ forensic evidence).

---

## D-076 — 2026-05-26 — v0.5.1 Tier 0 / DQ2: `--prompts-version v3` gated on a recent live-LLM smoke-pass record

**Context:** Per the cross-cutting lesson now thrice-recurring (M5b
Tier A.1 imageConfig wrapper; v0.5 morning abort lessons #1 + #2):
unit tests that mock the LLM's output can't catch prompt-vs-schema
drift, because they NEVER call the real LLM. The morning abort
burned ~$30 surfacing two LLM-output-shape bugs (top-level shape +
per-layout field names) that 1404 unit tests passed cleanly. A
$0.30 single-substory live smoke would have caught both before
spending $13 on the full ibd run.

**Decision:** Add `tools/smoke_v3_prompt.py` that:

- Composes ONE substory fragment against the real LLM using the
  current concatenated v3 prompt (D-075).
- Validates the fragment against the `compose-fragment.v2` /
  `.v3` schema using `slide_spec.py::_cli_validate` (the same
  validator the orchestrator's `[Final] merge` stage hits).
- On pass: writes `audit/v3_smoke_pass.json` to the skill repo
  (NOT to a per-project audit dir — the smoke is prompt-level,
  not project-level) with timestamp + commit-sha of `prompts/`
  + sha of the concatenated prompt body.
- On fail: writes `audit/v3_smoke_fail.json` with the validation
  errors + the broken fragment for inspection.

Gate `--prompts-version v3` in `presentation_maker.sh` on a fresh
smoke-pass: if `--prompts-version v3` is passed and no
`audit/v3_smoke_pass.json` exists, OR the recorded prompt-body sha
doesn't match the current prompts, OR the record is > 7 days old,
refuse to run with rc=2 + a clear message telling the operator to
run `tools/smoke_v3_prompt.py` first.

**Rationale:** $0.30 per smoke vs $30 lesson per missed bug; pays
for itself in O(1) recurrences. Sidecar JSON cache pattern matches
M5b's `ai_image_gen_probe.json` (D-064). Gating forces operator
discipline — the morning's runbook had "verify state" as Step 1
but the verification was mechanical (does the file exist?) rather
than semantic (does the prompt actually compose validly?). The
gate makes the semantic check mandatory.

**Alternatives considered:**

- **(a) Build smoke without gate; operator-discretion** —
  rejected; the morning abort proved operator-discretion gets
  skipped under time pressure. Adam approved the morning run on
  the strength of the unit-test suite passing; a non-gated smoke
  would have been skipped under the same pressure.
- **(c) Defer to v0.5.2** — rejected; if v0.5.1 ships a fixed v3
  but no smoke gate, the next prompt-content change (likely v0.6
  throughline-bridge or figure-utilization) will recur the same
  failure mode. The smoke gate is anti-recurrence infrastructure
  that pays for itself the first time it catches a regression.

**Related:** [V0_5_1_PUNCH_LIST.md](V0_5_1_PUNCH_LIST.md) DQ2 + Tier
B; D-064 (M5b sidecar cache pattern this reuses); M5b Tier A.1
imageConfig retro (precedent recurrence of the lesson);
`project_presentation_maker_v0_5_morning_abort.md` lesson 1.

---

## D-077 — 2026-05-26 — v0.5.1 Tier 0 / DQ3: v3 overlay's anti-pattern bullets fix verbatim against v2 field names

**Context:** `slide_compose.v3.md` lines 341-356 contain anti-pattern
bullets that name the WRONG field names: "Opening section_divider
whose `title` is a topic name…" — v2's actual `section_divider`
schema requires `{punchline, substory_number}` (slide_compose.v2.md
line 569); `title` isn't even a field on section_divider. Same for
the C-slide bullet ("Closing claim_evidence whose `punchline`
doesn't STATE the SUBSTORY_CONCLUSION" — `punchline` is correct
there; checked claim_evidence's v2 schema). The Q-slide + C-slide
bullets are inconsistent: one is right, one is wrong, because the
v3 prompt-author (Claude, 2026-05-25 evening) didn't know v2's
field-name vocabulary.

**Decision:** Mechanical find-and-replace fix:

- Q-slide anti-pattern (line 351): `title` → `punchline` (the
  section_divider's principal field per v2:569).
- C-slide anti-pattern (line 354-355): keep `punchline` — already
  correct.
- Audit pass: walk the rest of v3_overlay.md (the v3 overlay file
  per D-075) for any other field-name references and verify each
  against v2's per-layout schema in slide_compose.v2.md.

Add one unit test pinning the corrected field name (snapshot test
on the rendered v3 overlay).

**Rationale:** Mechanical fix; ~5 minutes. The bug was a sin of
hubris not omission — the v3-prompt-author assumed they knew
v2's schema without checking. The test pins it so the regression
can't recur via a future re-edit.

**Alternatives considered:**

- **(b) Reframe layout-agnostic** ("section_divider whose
  principal-text-field is a topic…") — rejected; adds vague
  language. The whole point of fixing v3 is to make field names
  *more* concrete, not less.
- **(c) Drop the anti-pattern bullets** — rejected; the
  register-discipline + Q/A/R/C role guidance live elsewhere in
  v3 overlay, but the anti-pattern bullets serve a different
  pedagogical role (named failure modes for the LLM to
  recognize). Removing them weakens the overlay's teaching value.

**Related:** [V0_5_1_PUNCH_LIST.md](V0_5_1_PUNCH_LIST.md) DQ3 + Tier
A.1; D-075 (the concat fix this sits within);
`prompts/slide_compose.v2.md` line 569 (the field-name authority).

---

## D-078 — 2026-05-26 — v0.5.1 Tier 0 / DQ4: `substory_design.v3.md` also restructured per D-075 concat fix

**Context:** Per DQ4 inspection at v0.5.1 Tier 0: `substory_design.v3.md`
is 369 lines (vs v1's 448 lines) with 11 "Unchanged from v" disclaimers.
SAME standalone-vs-overlay problem as slide_compose.v3.md per D-075
root cause. The morning abort didn't trip a substory_design schema
bug because the substory_design output is markdown (not JSON), so
"missing field" doesn't fail-fast the same way — but the v3 prompt's
Q + Conclusion-for-next-substory authoring still happens without
the LLM seeing v1's clustering discipline, tier-aware framing,
self-review pass, etc. That's latent risk: the substories the v3
prompt produces could be subtly off-contract (wrong clustering
granularity, missing tier hedging) without ever tripping a
schema error.

**Decision:** Apply the same concat fix per D-075:

- Rename `prompts/substory_design.v3.md` →
  `prompts/substory_design.v3_overlay.md` (~80 lines containing
  ONLY the D-071 Q/A/R/C contract additions + anti-pattern bullets).
- `_substory_design_prompt_path` for `PROMPTS_VERSION=v3` emits
  `cat substory_design.v1.md substory_design.v3_overlay.md` to
  `audit/_prompts/substory_design.v3.concat.md` (per project; same
  cache-and-cleanup pattern as the slide_compose concat).
- Audit the v3 overlay's field-name and section references for the
  same kind of D-077 hallucination bug.

**Rationale:** Same root cause; same fix. Doing both in v0.5.1 Tier A
batches the work efficiently (one dispatcher change pattern applied
to two helpers). Leaving substory_design.v3 broken would mean v0.5.1
ships a prompt-architecture inconsistency: slide_compose is now
overlay-on-v2, but substory_design is still standalone-pretending-
to-overlay-on-v1. The asymmetry would be a footgun for v0.6.

**Alternatives considered:**

- **(b) Defer substory_design.v3 fix to v0.5.2** — rejected;
  inconsistent prompt architecture costs more in cognitive load
  than the ~15 minutes of additional work the fix takes. Same
  pattern, same test surface.

**Related:** [V0_5_1_PUNCH_LIST.md](V0_5_1_PUNCH_LIST.md) DQ4 + Tier
A.2; D-075 (the parent decision this mirrors); D-071 (the Q/A/R/C
contract substory_design.v3 implements).


---

## D-079 — 2026-05-27 — v0.5.1 Tier E veto: DON'T SHIP; treat as research finding for v0.6

**Context:** v0.5.1 Tier C/D live A/B re-ran ibd_phage_targeting +
functional_dark_matter on 2026-05-26 evening using the
D-075/D-077/D-078 prompt-architecture fixes + the D-076 smoke gate.
Both runs completed with valid schema (0 errors vs the morning's
21-per-run validation failures). Quantitative wins on the two
v0.5 lever metrics:

- **Audience-prose specialist-reference violations** (the M6
  Tier-D "walls of text poisoned by specialist reference"
  complaint):
  - ibd: 24 (v0.3) / 36 (v0.4exp) → **17 (v0.5.1)**
    [-29% / -53%]
  - fdm: 19 (v0.3) / 9 (v0.4exp) → **3 (v0.5.1)** [-84% / -67%]
- **Q/A/R/C contract violations** (D-071; missing_question +
  missing_conclusion + missing_c_slide; the "no question →
  clear analysis → results → conclusions" arc Adam named):
  - ibd: 7 (v0.3) / 12 (v0.4exp) → **0 (v0.5.1)**
  - fdm: 7 (v0.3) / 5 (v0.4exp) → **0 (v0.5.1)**

**Adam Tier-E read 2026-05-27 morning identified four remaining
quality problems** that the metric wins don't capture:

1. **Retraction leakage.** ibd v0.5.1 still references NB04
   ("Retract leaky NB04 analysis (14/18 sig...") as if it were
   a story beat. The composer pulled the analysis from the plan
   inventory; the substory_design step didn't filter it; v0.5
   register-discipline caught "NB04" as a notebook_id audience
   violation but DOES NOT catch the upstream content problem
   ("don't talk about retracted/discarded results at all").
2. **Figure under-use.** ibd v0.5.1 used 3 of 7 curated figures
   (43%); 3 of 34 slides are `data_figure`. Already in D-070
   v0.6 carry. Adam-rubric for v0.6: *"every arc should back a
   claim or finding by relevant figure if possible."*
3. **No AI-generated images.** Both decks: 0 images approved
   despite 31 image-gen decisions on ibd. Root-cause not
   diagnosed (sandbox blocked inspection of the working/
   image_decisions.json from this session). Could be the
   decision layer's conservative concept_illustration-only
   policy; could be a real bug.
4. **Compression: budgets perhaps over-compressing the story.**
   Both decks at talk-30 STRONG (mode budget 18-32); ibd
   landed at 34 slides, fdm at 29. The v3 overlay's Q/A/R/C
   contract may be forcing slot-compression *within* each
   substory (e.g., one R-slide where two would breathe
   better). New finding from this read.

**Decision:** **DON'T SHIP** v0.5.1 as a release. No tag. v0.5.1
work becomes evidence informing the v0.6 design. The architectural
fix (D-075/D-078 concat overlay; D-076 smoke gate) remains on main
and is structurally sound — but the content-quality gaps named in
the Tier-E read mean v0.5.1 wouldn't satisfy the "ship-as-default"
test even at experimental tier.

**Rationale:**

- **v0.4 shipped at experimental** (2026-05-25, D-066) because
  the A/B was mechanical FAIL on the target. v0.5.1 has the
  opposite shape: the mechanical-style metrics PASS (-29% to -84%
  on the content-discipline lever; 100% on Q/A/R/C arc), but
  the Tier-E read surfaces failures the metrics don't cover. The
  M6 lesson Adam carried forward — "Adam-veto is final
  regardless of mechanical result" (D-066) — applies here.
- v0.5.1-experimental was offered but rejected: the four
  problems (especially NB04-retraction-leakage and the
  compression finding) are about CONTENT, not architecture, and
  shipping at experimental would invite operators to use v3
  prompts in production where they'd encounter those content
  problems. Cleaner to fix in v0.6 + ship as default then.
- The "fix compression + ship v0.5.2" option was also offered
  but rejected: compression is one of FOUR problems; piecemeal
  fixing one then re-reading is more cycles than batching them
  in v0.6.

**Alternatives considered:**

- **(a) Ship v0.5.1-experimental** — rejected; content-quality
  gaps make the experimental opt-in misleading.
- **(c) Ship v0.5.1 as default** — rejected; same content
  reason + the figure under-use is a real regression risk
  (operators may have been getting acceptable figure usage
  under v0.3 sequential composer; v3 may make it worse).
- **(d) Quick v0.5.2 to address compression** — rejected;
  partial fix; v0.6 batches all four findings.

**What does ship on main as v0.5.1 work:**

- The D-075/D-078 concat-overlay architecture (slide_compose.v3
  + substory_design.v3 both as v_n_body + v3_overlay
  concatenation; orchestrator builds at startup).
- The D-076 live-LLM smoke + gate (`tools/smoke_v3_prompt.py`).
- The D-077 v3 overlay field-name fixes (claim_evidence →
  `title`; section_divider → `punchline`; explicit per-layout
  enumeration in inviolable-rules).
- 36 new tests (1404 → 1440); both Tier C/D draft_6 dirs
  on disk for v0.6 inspection.

**What goes to v0.6 (carry items):**

- **NB04-retraction-leakage** root cause + fix
  (substory_design / plan filter on discarded-results).
- **Figure-utilization contract** (D-070 carry; Adam-rubric
  pin: "every arc backed by relevant figure if possible").
- **No-images diagnostic** (root-cause why 0/31 image-gen
  decisions approved on ibd; rerun image-gen probe to surface
  whether it's policy or bug).
- **Compression** (v3 overlay's Q/A/R/C contract over-rigid;
  consider widening R-slide allowance OR loosening mode-budget
  caps when STRONG-tier substory has multiple R-slot candidates).
- **Orchestrator tee/BlockingIOError bug** (surfaced live on
  fdm v0.5.1; benign because validation passed; separable from
  prompt-architecture work).

**Related:** [V0_5_1_PUNCH_LIST.md](V0_5_1_PUNCH_LIST.md) Tier E
+ Tier F/G (cancelled per this veto); D-066 (Adam-veto pattern
inherited); D-070 (v0.5 scope opening; v0.6 figure-utilization
carry); D-071/D-072 (the contracts that fired the wins);
`project_presentation_maker_v0_5_morning_abort.md` (the
prompt-architecture bug v0.5.1 fixed);
`project_presentation_maker_v0_5_1.md` (this Tier-E
retrospective; to be written).
