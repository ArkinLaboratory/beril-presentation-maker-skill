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
