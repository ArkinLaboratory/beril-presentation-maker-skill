# beril-presentation-maker — Specification (v0.1 design rationale)

**Status:** v0.1 design rationale, captured pre-implementation
(2026-04-25). The skill has since shipped through v0.3.4.4 and is
production-ready. This document remains the load-bearing rationale
for the original design choices; for the current operational state
see [README.md](README.md), [SKILL.md](src/beril_presentation_maker/skill/SKILL.md),
[CONTRACT.md](CONTRACT.md), and [RELEASE_NOTES.md](RELEASE_NOTES.md).
Decisions captured here are load-bearing for the build; deltas
between this spec and the shipped behavior should be reflected in
[DECISIONS.md](DECISIONS.md) with explicit "superseded by Dxxx"
annotations.

This document explains *what* the skill does and *why* the design choices
were made. It is the document an external reviewer should read to decide
whether to trust an output of this skill. [LAYOUT.md](LAYOUT.md) covers
internal architecture (package shape, CLI, file paths). [README.md](README.md)
is the quick-start.

The presentation-maker is the fourth in the BERIL drop-in skill quartet
(atlas, adversarial, paper-writer, presentation-maker). It mirrors the
paper-writer's pipx-installable, ships-the-skill-as-package-data pattern.
Many design decisions are inherited; departures are marked.

---

## 1. Purpose and scope

### 1.1 What this skill does

Takes a finished BERDL analysis project and produces a beautiful,
evidence-grounded scientific presentation in KBase brand. The presentation
is one of:

- a slide deck for a 30-minute peer-audience talk (default mode);
- a shorter or longer talk variant (15, 45, or 5-minute lightning);
- a poster (horizontal 48×36 in or vertical 36×48 in).

Where the underlying work cannot support a rigorous claim, the skill says
so on slide and in speaker notes — it does **not** paper over evidence
gaps with confident-sounding bullets. The skill ships an audit trail
(citation pool, notes-provenance, reframing log) so that every slide can
be defended.

### 1.2 What this skill is NOT

- Not a journal-style or vendor-template deck-formatter. v1 ships KBase
  brand only. Vendor templates (Nature presentation, Cell talk, conference
  poster grids beyond KBase's two) are post-MVP.
- Not a quantitative-figure generator. Charts, graphs, and any image
  containing numerical claims must come from the project's `figures/`
  directory or be re-rendered from notebook outputs (paper-writer pattern).
  See §8.
- Not a substitute for human delivery. The skill produces speaker notes
  and Q&A prep but the user must still rehearse, customize, and present.
- Not a lay-audience translator. v1 targets scientific peer audience only
  (see §1.3). Lay/program-officer/executive axes are v1.x scope.
- Not a substitute for adversarial review. The review-rewrite loop is for
  self-improvement before delivery, not a substitute for colleague review.
- Not a live IDE. The skill runs as a batched CLI/slash-command
  invocation with interactive pause-points (throughline, substory,
  per-image approval). Targeted post-assembled revision is supported
  via the `revise` verb (per-slide / per-substory; see §16.5);
  free-form editing of the produced .pptx happens in PowerPoint /
  Keynote / Google Slides.

### 1.3 Who this skill is for

BERIL users who have completed an analysis and need to present it to a
peer audience — group meeting, lab seminar, conference talk, program
review, poster session — with the discipline to:

- Refuse to put on a slide what the evidence doesn't support.
- Surface alternative throughlines so the user, not the LLM, picks the
  story (and the substory list under it).
- Make every numerical claim, every cited paper, every methods bullet
  traceable to a verified source — notebook output, REPORT.md line, or
  DOI/PMID.
- Keep visual coherence (KBase brand) and good-talk hygiene (one-idea-
  per-slide, punchline titles, consistent layouts) without inventing
  visuals that misrepresent the work.
- Hand off to harsh review and revise iteratively, with bounded cycles.

### 1.4 Best-practice anchors

The skill's slide composition prompts cite, and try to honor:

- Naegle (2021) — *How to give a great scientific talk* — particularly
  the "punchline as title", "one idea per slide", and the slide-density
  budget.
- ASP (American Society of Plant Biologists) — *Effective Presentations*
  — particularly the audience-progression and figure-readability
  guidance.
- UVa Chemistry's *How to prepare and present a scientific talk* —
  particularly the structure (hook → problem → approach → result →
  implication → Q&A) and the "what should the audience remember in 6
  weeks" framing.
- ICMJE recommendations as filtered through paper-writer's M3 (AI-
  disclosure) — the skill emits an "AI-Assisted Preparation" footnote
  on the references slide.

These references appear in the prompts, not on user slides.

---

## 2. Design premises (what we're optimizing for)

In rough order of priority:

1. **Honesty.** A slide must not fabricate citations, methods, or
   numerical claims. Where evidence is thin, the skill says so on slide
   and in speaker notes. A talk that *looks* polished about thin work is
   the primary failure mode to design against — more dangerous than a
   talk that refuses to oversell.
2. **Auditability.** Every claim on a slide must trace to (a) a project
   artifact (notebook output, REPORT.md line, figure file) or (b) a
   verified citation in the citation pool. The notes-provenance file
   makes the trace explicit and human-readable.
3. **Visual coherence.** KBase brand applied consistently across the
   deck, with named layouts driving composition rather than freeform
   shape placement. Not pretty for its own sake — pretty because
   inconsistency telegraphs sloppiness and makes the science look
   sloppy.
4. **User judgment over LLM judgment** at the load-bearing decisions:
   throughline pick, substory list approval, AI-image-gen approval.
5. **Bounded cost and latency.** Target $4–$10 per full talk-30 run,
   25–45 minutes. Every loop has a hard cap. No infinite revise-review
   cycles.
6. **Reuse over generation.** Reuse existing project figures, existing
   numerical claims from REPORT/notebooks, existing citations from
   `references.md` or paper-writer's pool. Generate only what doesn't
   already exist (and only the kinds of things that are safe to
   generate — illustrative diagrams, never quantitative figures).

These premises mirror paper-writer's premises (paper-writer SPEC §2)
with one explicit addition: visual coherence is a first-class concern
for this skill, not a byproduct.

---

## 3. Inputs (what the skill expects)

From the project directory (per the BERIL convention `projects/<id>/`):

- **`RESEARCH_PLAN.md`** (required) — the planned hypotheses and
  approach. Used to detect gap between plan and what was actually done;
  used in introduction/throughline framing.
- **`REPORT.md`** (required) — the canonical synthesized findings. The
  presentation MUST NOT silently contradict REPORT; reframing is logged
  explicitly in `reframing_log.md` (mirrors paper-writer §5.6).
- **`README.md`** (optional) — project-level context, often includes
  one-paragraph summary used in the title-slide subtitle.
- **`REVIEW.md`, `ADVERSARIAL_REVIEW_*.md`** (optional but strongly
  used) — prior reviews flag known weaknesses the talk must engage
  with rather than restate as findings.
- **Notebooks** (`*.ipynb`) — source of truth for methods (algorithms,
  parameters, package versions) and numerical claims. Methods-summary
  slides and speaker-notes "in case asked" content are extracted from
  notebooks, never generated from a free prompt.
- **Figures** (`figures/*.png` or similar) — reused as-is for the
  presentation; selection logic chooses 4–10 of typically 30+ project
  figures (mode-dependent budget).
- **`references.md`** (optional) — pre-existing citations. If absent,
  the skill builds a citation pool from scratch via literature search,
  or reuses paper-writer's pool if present (see §9.2).
- **`papers/draft_*/`** (optional) — paper-writer outputs. If present,
  the skill harvests the chosen throughline, citation pool, and
  curated figures for reuse (see §3.2).

### 3.1 Plan-phase triage

The skill runs the same STRONG / THIN / EXPLORATORY tier classification
as paper-writer (paper-writer SPEC §3.1), via the same plan prompt
shape but tuned for talk authoring:

- **STRONG** — clear research question, numbered findings with CIs/
  p-values, explicit limitations. → Talk drafts as a single coherent
  story with 1–3 substories. Big-idea slides at substory transitions.
  Methods-summary slide may be brief.
- **THIN** — novel finding, methodological gaps. → Talk frames the
  finding honestly, calls out the gaps on a "What we cannot conclude
  yet" slide, and recommends the next experiment as a closing call.
- **EXPLORATORY** — proof-of-concept, single layer, no validation. →
  Talk frames the work as exploratory; the title-slide subtitle says
  so; the conclusions slide says so. Speaker notes carry the explicit
  "this is hypothesis-generating, not confirmatory" caveat.

The triage informs language conservatism (declarative vs scoped vs
preliminary), claim certainty (tested vs hypothesis-generating), and
the weight of the limitations slides. Mirrors paper-writer's evidence-
strength framing (paper-writer SPEC §3.1.1).

### 3.2 Sibling-skill output reuse

If `papers/draft_*/` exists with a chosen throughline (`00_throughline.md`
present, `state.json` shows `phase != throughline_pick`), the
presentation-maker:

1. Defaults `--throughline auto-from-paper` rather than re-extracting.
2. Reuses the paper's `citation_pool.json` directly as the slide
   citation pool (saves a 3–8 minute literature-scan pass).
3. Reuses `figures/` (the paper-writer's curated subset) as the
   starting figure budget; talk-specific selection trims further.

`--ignore-paper` opts out of all three.

The skill does **not** consume atlas runtime output (D-010). The
presentation-maker is independent — it must work whether or not
atlas has been run. We may borrow *algorithmic code* from atlas's
source (e.g., the cross-author edge classification logic, citation
graph parsing) by copy-and-adapt, but the maker has no runtime
dependency on atlas's data products.

### 3.3 Cross-tenant integration discovery

A required section of every talk is "How this work integrated data
across tenants and prior projects." This is a KBase-platform-level value
proposition (cross-tenant network effects) and should appear in every
project's talk even if minimally.

The skill discovers cross-tenant signal from project-local artifacts
only (no atlas dependency, per D-010):

1. **`README.md` / `RESEARCH_PLAN.md` / `REPORT.md` prose mentions** —
   regex+LLM extraction of K-BERDL database names, tenant IDs, and
   sibling-project references.
2. **Notebooks** — parse `berdl_query` calls; extract database names
   and table names from SQL strings; extract any `requests.get` /
   `urlopen` against `*.kbase.us` / `*.berdl.lbl.gov` / `*.lbl.gov`.
3. **`references.md`** — internal-reference patterns ("see project
   `<other_id>`", "results from `<sibling>`").

#### 3.3.1 Quantification (best-effort, project-local)

The cross-tenant slide should include counts where possible, NOT
just prose. From project-local artifacts the skill can cheaply
quantify:

- Number of K-BERDL databases queried (from notebook SQL extraction).
- Number of distinct tenants mentioned (from REPORT/PLAN/README).
- Number of explicit sibling-project references (from references.md
  patterns).

These counts are best-effort and shallow. Deeper quantification
(cross-author edge classification, project-graph distance, atlas-
quality citation analysis) requires the algorithm we'd borrow from
atlas, but **that algorithm runs over project-local artifacts only**
in this skill — never over atlas's runtime output. If a project
genuinely needs the corpus-wide signal that only atlas computes
(rare in v1), the user runs atlas separately and feeds the result
back via `--cross-tenant-data path/to/atlas-export.json` (v1.x
feature, deferred from v0.1).

If discovery yields zero cross-tenant signal, the skill emits a
single-slide "All data sourced from <tenant>" with a brief note in
speaker notes that this work did not integrate across tenants.
Atlas-style scanning of citation graphs across the project corpus is
out of scope for v0.1.

### 3.4 Clean inputs / dirty inputs

Same convention as paper-writer:

- Treat REPORT.md as authoritative. If it disagrees with notebook
  outputs, log in `reframing_log.md` (REPORT line vs notebook output).
- Treat RESEARCH_PLAN as intent. If actual work diverges from plan,
  log in `reframing_log.md` (plan vs execution).
- Never silently "correct" REPORT to match notebooks. Reframing is
  always explicit and user-visible.

---

## 4. Throughline + substory extraction

This is the load-bearing user gate. Mirrors paper-writer §4 with one
addition: substories.

### 4.1 Throughline meta-arc

The skill extracts 2–3 candidate meta-arcs for the talk. Each candidate
is a one-sentence claim plus an evidence map:

- Sub-claim 1 → source artifact (with strength: direct / partial /
  contradicts / orthogonal)
- Sub-claim 2 → source artifact ...
- Slide-count estimate at each tier (talk-30 vs talk-15 vs poster)
- Estimated visual coherence cost (figures available for this arc;
  procedural diagrams needed; AI-image-gen needed)

Default behavior: `--throughline interactive` — pause for user pick.
`--throughline auto` opts into the highest-evidence-density candidate.
This is the load-bearing gate; an LLM left to auto-pick will favor the
arc easiest to write over the arc that fits the data. (D-002.)

### 4.2 Substory list — semantic clustering of REPORT analyses

Once the meta-arc is fixed, the skill identifies the *critical
analyses* in `REPORT.md` (the work that bears on the chosen
throughline) and **groups them into substories**. A substory is a
semantic cluster of related analyses that together tell one coherent
sub-argument with a single punchline. **Substories are not 1:1 with
analyses** — multiple analyses typically combine into one substory.

The discipline:

- Cover **all** critical analyses from REPORT — none silently dropped.
- Group analyses by the sub-argument they support, not by chronology
  or notebook order.
- Each substory has a punchline ("what does this slice prove?") that
  goes on its divider slide. If the cluster has no clear unifying
  punchline, the grouping is wrong; split or re-cluster.
- Tighter modes force more aggressive grouping (lightning-5 may
  collapse all analyses into a single substory whose punchline is
  the meta-arc itself).

The clustering result is shown to the user with a per-substory slide
budget; user approves (or splits / merges / re-orders) before slide
drafting starts.

#### 4.2.1 Mode-capacity overflow

`mode_capacity` = mode_slide_budget − boilerplate_slides (title,
divider per substory, cross_tenant, acknowledgments, references).
`required_slides` = sum of evidence slides each substory needs to
make its case.

If `required_slides > mode_capacity`, the orchestrator halts at the
substory-approval gate with three options for the user to pick:

(a) Pick which substories to keep / drop (user decides which sub-
arguments matter most for this audience).
(b) Escalate mode (talk-15 → talk-30 → talk-45). Re-plans automatically.
(c) Merge substories (combine two clusters into one with explicit
acknowledgment that the resulting punchline is broader).

**Default: halt and ask.** Never silently drop a critical analysis.
(D-027.)

`--substories N` is a soft override that proposes a target number of
clusters to the LLM but does NOT cap the count if the LLM cannot fit
all critical analyses into N clusters honestly; in that case the
overflow gate triggers. `--substory-skip <id>` is a user-override at
the approval gate that drops one cluster (with a reframing-log entry
documenting what was dropped).

### 4.3 Throughline candidates artifact

`throughline_candidates.md` is written before the user is prompted, and
**not deleted** when the user picks. Rejected alternatives stay as audit
trail. Mirrors paper-writer §4.4.

---

## 5. Mode dispatch

The `--mode` flag picks a render path and slide budget. Mode-specific
defaults are fixed; users can override slide budgets but not the
render path.

| Mode | Render path | Slide budget (default) | Speaker notes | Q&A prep | Posters? |
|---|---|---|---|---|---|
| `talk-30` | slide deck | 25–32 | yes (100–150 wd/slide) | yes (10 questions) | n/a |
| `talk-15` | slide deck | 13–17 | yes (100 wd/slide) | yes (5 questions) | n/a |
| `talk-45` | slide deck | 35–48 | yes (150 wd/slide) | yes (12 questions) | n/a |
| `lightning-5` | slide deck | 5–8 | yes (60 wd/slide) | no | n/a |
| `poster-h` | poster (single) | 1 (filled grid) | no | no | horizontal 48×36 in |
| `poster-v` | poster (single) | 1 (filled grid) | no | no | vertical 36×48 in |

Mode dispatch is set at plan phase. Mode change after plan phase
forces re-plan (new throughline candidates, new substory list); state
machine warns user before destruction.

---

## 6. Slide-shape vocabulary

The skill composes slides from a fixed vocabulary of named layouts.
Each layout is shipped in `kbase-presentation-master.pptx` (see
§14.1). Layouts:

| Layout | Purpose | Required content | Optional content |
|---|---|---|---|
| `title` | Title slide | title, subtitle, presenter, date | venue, affiliation, KBase logo |
| `section_divider` | Substory transition | substory punchline (large) | substory number, KBase mark |
| `big_idea` | Single-claim slide, meta-arc punchline (sentence) | one sentence, large | one supporting graphic |
| `big_number` | Headline statistic — single number / short stat phrase | huge number or short stat ("90% accuracy", "27M scores"), one-line subtitle | sub-bullet pointer, source-footer |
| `claim_evidence` | Punchline + 2–3 evidence bullets + 1 figure | claim title, ≤3 bullets, 1 figure | citation footer |
| `two_column_compare` | Before/after, ours/theirs, with-X/without-X | left col title + content, right col title + content | top punchline |
| `data_figure` | One chart from REPORT/notebook + caption + interpretation | figure, caption, interpretation-as-title | data-source footer |
| `workflow_diagram` | Procedural diagram (boxes + arrows) | diagram, 3-step caption | tool/version footer |
| `methods_summary` | Lightweight methods (5–10 bullets) | bullets, key tools/versions | "see speaker notes for detail" |
| `concept_illustration` | AI-generated conceptual illustration (Tier 3 image-gen) — one layout with `style: metaphor \| infographic \| conceptual_diagram` | AI-generated image, punchline title, AI-disclosure footer | one-line caption, source prompt in speaker notes |
| `cross_tenant_integration` | Required section: data sources + sibling-project leverage | tenant list, K-BERDL DB list, sibling-project refs | data-flow diagram |
| `implications` | What changes if this is true; ranked | 3 bullets max | per-bullet evidence pointer |
| `acknowledgments` | Funders, contributors, KBase tenants | funder logos/names, contributor list | tenant-attribution footer |
| `references` | Short-form citations + AI-disclosure | ≤8 short refs (Author Year), AI-disclosure | "full bibliography in speaker notes" |
| `qa_anticipated` | Hidden Q&A appendix slides (visible_count+) | one anticipated question per slide | rehearsable answer + evidence |

Vocabulary is closed at v0.1. New layout types require a DECISIONS.md
entry and a master-template update.

### 6.1 Punchline titles (apply to all content slides regardless of layout)

Every content slide's *title* is a punchline, not a topic. **Layout
names are kind (machine-readable); slide titles are content
(audience-facing).** The `methods_summary` and `workflow_diagram`
layouts both depict methods — but their titles are punchlines, not
"Methods" or "Workflow". For example, a `workflow_diagram` slide
might be titled "Notebook AST extraction grounds every claim in
code", not "Methods Pipeline".

Topic-style titles ("Methods", "Results", "Discussion",
"Background", "Workflow", "Pipeline", "Approach", "Overview") are
banned by validator P-titles. The slide-compose prompt enforces the
rule; REPAIR_MODE rewrites topic titles into punchlines using the
slide's content as input.

The `references` and `acknowledgments` layouts are exempt — their
titles are conventional and need no punchline. The `section_divider`
layout's "title" is by definition the substory's punchline (single
large sentence). The `big_number` layout's "title" is the headline
statistic itself.

### 6.2 Big-idea slides at substory transitions

Each substory begins with a `big_idea` slide (single sentence,
supporting graphic). This is non-negotiable per Naegle (2021); the
slide-compose prompt mandates it and the validator enforces.

### 6.3 Density discipline

- Max 5 content elements per slide (bullets, figures, captions
  combined; counts text boxes).
- Max 35 words per slide (excluding speaker notes).
- Min 24 pt body text; 36 pt title text (KBase style guide minima).
- Max 2 figures per slide (forces careful curation).

Validator P-density enforces. User override `--allow-dense` for
exceptional slides (e.g., the architecture diagram in the example
deck has 38 text boxes; that's a known exception, not a target).

---

## 7. Cross-tenant integration section (required)

Every talk includes a cross-tenant slide section, even if minimal.
The section answers: how did this work integrate data across tenants
and leverage results from other projects?

### 7.1 Discovery

Per §3.3, the skill scans `README.md`, `RESEARCH_PLAN.md`,
`REPORT.md`, notebooks, and `references.md` for cross-tenant signal.

### 7.2 Slide allocation

- talk-30 / talk-45: 1–2 slides (one for K-BERDL data integration,
  optional second for sibling-project leverage).
- talk-15: 1 slide (combined).
- lightning-5: 1 slide if signal is non-trivial; else mentioned in
  speaker notes only.
- poster: dedicated panel in the lower-third zone of the poster grid.

### 7.3 No-signal fallback

If discovery yields zero cross-tenant signal, the skill emits a
single-line slide: "All data sourced from `<tenant>`. This project
did not integrate across tenants." Speaker notes elaborate honestly.
This avoids fabricating cross-tenant value.

### 7.4 KBase-platform value framing

The cross-tenant slide is also where KBase's institutional value
proposition (data integration across BER) shows up. Speaker notes
include a sentence about how K-BERDL made this integration possible
when relevant; the slide does not preach. (Default-off; user enables
with `--kbase-platform-frame` if presenting to a KBase audience.)

---

## 8. Figure handling

Three tiers, listed by descending preference:

### 8.1 Tier 1 — reuse from REPORT/notebooks (always-on)

Default. Identical to paper-writer §6 figure handling: notebook
outputs and existing `figures/*.png` are reused as-is. Captions are
extracted from REPORT/notebook savefig context; no captioning prompt
runs unless §8.4 escalation triggers.

### 8.2 Tier 2 — procedural diagrams via python-pptx (always-on)

The skill generates illustrative diagrams (workflows, conceptual
schematics, layered-architecture views, before/after comparisons)
using python-pptx native shapes:

- AutoShapes (rectangles, rounded rectangles, ellipses, parallelograms,
  cylinders for databases, callouts).
- Connectors (straight, elbow, curved).
- Text boxes with KBase-brand fonts/colors.

These diagrams are quantitatively safe — they cannot embed numerical
claims because the skill emits no axes labels with numbers. They are
shape-and-text only.

The slide-compose prompt produces a structured `slide_spec.json`
diagram description (boxes-and-arrows representation); a Python
helper (`tools/diagram_render.py`) walks it into python-pptx native
shapes. Mermaid input is accepted as an alternative spec format
(parsed and rendered to native shapes; Mermaid CLI is NOT a runtime
dependency).

### 8.3 Tier 3 — AI image generation (opt-in; CBORG or AI Studio)

Default off. `--ai-diagrams opt-in` enables. Two providers ship in
v0.4:

- **CBORG** (default; v0.3.x baseline): `google/gemini-pro-image` /
  `gemini-3-pro-image` via `CBORG_API_KEY` against
  `https://api.cborg.lbl.gov` (OpenAI-compatible image-gen surface).
- **AI Studio** (M5b / D-062; honours the user's own Google AI Studio
  license per Adam's stated intent in V0_4_ARCHITECTURE §14.1):
  native Gemini API at
  `https://generativelanguage.googleapis.com/v1beta` via
  `GOOGLE_AI_STUDIO_API_KEY`. The May-2026 model fallback chain
  (D-035-rev1) is `gemini-3-pro-image-preview` →
  `gemini-3.1-flash-image-preview` → `gemini-2.5-flash-image`;
  resolved at draft time via the model-availability probe (see §8.3.2
  below).

Provider precedence (D-062 / orchestrator-resolved):

1. Explicit `--image-provider {cborg|google_ai_studio}` wins.
2. `GOOGLE_AI_STUDIO_API_KEY` env present → AI Studio.
3. `CBORG_API_KEY` env present → CBORG.
4. Neither → image-gen disabled for this run (treat as `--no-images`).

Both keys are resolved from `BERIL_ROOT/.env` if not in shell env
(same defensive `.env` parse that the v0.3.3 CBORG path used; never
echoes key values — only a `[orchestrator] <KEY> loaded from
BERIL_ROOT/.env` marker line per memory `feedback_secret_file_handling`).

Two-channel control model (D-005-rev1):

- **Channel A — global flag (`--ai-diagrams off | opt-in`).** Default
  `off`. Controls whether the LLM may **propose** AI illustrations
  spontaneously during slide composition. `off` = LLM never proposes;
  `opt-in` = LLM proposes when the throughline benefits from a
  metaphor / infographic / conceptual diagram, each proposal still
  requires user approval per the gate below.
- **Channel B — interactive override (always available).** At any
  pause point (throughline, substory approval, slide review, post-
  validator REPAIR), the user can request `generate image for slide
  N: <prompt>`. This bypasses Channel A's setting (i.e., works even
  when `--ai-diagrams off`) but still enforces all other constraints.

Common constraints (apply to both channels):

- **Per-image user-approval gate.** Whether LLM-proposed (Channel A)
  or user-requested (Channel B), the skill emits the prompt + cost
  estimate and waits for explicit approval. User can edit the prompt
  before approving.
- **Mandatory disclosure footer.** "AI-generated illustration" appears
  in 8-pt KBase-graphite-gray on every AI-generated image's slide.
- **Quantitative-content forbidden.** A validator runs an LLM-as-judge
  pass on every generated image: "does this image contain
  quantitative claims, axes labels with numbers, or numeric
  annotations?" Yes → image rejected, slide falls back to procedural
  Tier-2 or omits the image.
- **Cost cap.** `--ai-diagram-budget USD` (default $5.00) — total
  spend across the draft, hard-fail if exceeded. Channel B requests
  count against the same budget.
- **Provenance recorded.** Each generated image's prompt, model,
  cost, channel (A or B), and approval timestamp are recorded in
  `image_provenance.json` (mirrors `notes_provenance.md` discipline).

The intent of Tier 3 is conceptual metaphors and infographic flavor:
"a brain made of microbes," "a knowledge-amplification engine icon,"
"a stylized petri dish with arrows" — never a chart, never an
annotated genome, never a spectrum.

### 8.3.1 The `concept_illustration` slide layout

Tier 3 images live in slides assigned the `concept_illustration`
layout (SPEC §6 vocabulary). The layout has a `style` field in
slide_spec carrying one of `metaphor | infographic |
conceptual_diagram`, which the AI-prompt agent uses to bias prompt
construction. Same layout for all three styles — only the prompt
flavor differs.

### 8.3.2 AI Studio model-availability probe + hybrid fallback (M5b)

When the resolved provider is `google_ai_studio`, the orchestrator
runs `image_client.py probe` once at the top of the image-gen stage
to resolve which model in the D-035-rev1 fallback chain is actually
available on the user's API key:

  `gemini-3-pro-image-preview` (preferred)
  → `gemini-3.1-flash-image-preview`
  → `gemini-2.5-flash-image`
  → none → fall back per D-064 (below)

The resolved model is cached at
`<draft>/audit/ai_image_gen_probe.json` (D-063 sidecar). The cache
is keyed by a short non-reversible fingerprint of the API key
(sha256 prefix) so key rotation triggers a re-probe without
persisting the key itself; corrupt sidecars are re-probed
defensively. The cache is per-draft (one fresh probe per `draft_N`).

**Manual override (C5).** `GOOGLE_AI_STUDIO_MODEL=<name>` env var
short-circuits the probe entirely and pins the named model. Useful
for pinning a specific model for reproducibility or working around
probe failures.

**D-064 hybrid fallback** when the probe finds no usable model in
the chain:

- **CBORG fallback (silent).** If `CBORG_API_KEY` is also set:
  override `IMAGE_PROVIDER=cborg` for the rest of this draft + emit
  a one-line `[image-gen probe] AI Studio probe found no usable
  model; falling back to CBORG` log line on stderr. The image-gen
  stage proceeds.
- **Loud-warning disable.** If no `CBORG_API_KEY`: emit the full
  multi-line diagnostic on stderr (chain walked, each model marked
  present/absent; image-capable models seen on the key; actionable
  next steps: set CBORG_API_KEY, set GOOGLE_AI_STUDIO_MODEL=<name>,
  or fix AI Studio access), then disable image-gen for this run
  (treat as `--no-images`).

This posture preserves the user's stated intent ("use my Gemini
Studio license if available") while not breaking the run when the
license is misconfigured — and always surfaces what was tried so
the user is never silently downgraded without seeing the chain.

### 8.4 Caption integrity

For Tier 1 reused figures, captions are extracted, not generated. If
the figure has no caption candidate (no REPORT line, no notebook
savefig context, filename uninformative), the slide-compose prompt
emits `[CAPTION NEEDED: figure_name.png]` and the validator
(P-caption) flags it.

For Tier 2 procedural diagrams, captions are generated from the
substory context but bound to the diagram's structural content (boxes
+ arrows), not the substory narrative. The validator checks
caption-vs-diagram structural fidelity (LLM-as-judge: "does the
caption describe what the diagram shows, or claim something the
diagram does not show?").

For Tier 3 AI-generated images, captions are generated from the
approved prompt (not the substory), and disclosure footer overrides.

---

## 9. Citation pool + on-slide referencing

### 9.1 Citation discipline

Same 10-field strict citation format as paper-writer (paper-writer
SPEC §6.4) for the citation pool. On-slide rendering is short-form
("Smith 2023"), full citation lives in speaker notes and on the
references slide.

### 9.2 Pool reuse

If `papers/draft_*/citation_pool.json` exists and `--ignore-paper` is
not set, the skill loads that pool as starting state and adds only
new pool entries (talks often cite background that papers don't).
This skips a 3–8 minute literature-scan pass — a meaningful cost
saving when both run on the same project.

### 9.3 Pool exhaustion

Same three options as paper-writer (paper-writer SPEC §6.4 pool
exhaustion): scope-down (drop the claim), citation-request (gap-fill
round), accept-as-limitation (slide flags it explicitly with `[no
citation found]`).

### 9.4 References slide

Final slide before `qa_anticipated` appendix. Lists ≤8 short-form
citations from the pool that appeared on slides. Full pool (up to
80 refs) lives in `references.md` artifact and in speaker notes.

### 9.5 AI-disclosure on references slide

A line at the bottom of the references slide: "Slides drafted with
beril-presentation-maker (Claude); evidence anchored to project
notebooks and REPORT.md." Same intent as paper-writer's M3 (AI-
disclosure paragraph).

---

## 10. Speaker notes

Speaker notes are first-class output, not afterthought. Mirror
paper-writer's methods_provenance discipline (paper-writer SPEC §6.3).

### 10.1 Length

100–150 words per slide (talk-30 default). Mode-dependent: 60 wd for
lightning-5, 150 wd for talk-45. Configurable via `--notes-words N`.

### 10.2 Content

Each slide's notes contain:

- A 1–2 sentence "what to say" lede that the presenter can read aloud.
- The full citation(s) for any short-form references on the slide.
- Backup numbers — the precise values that justify the slide claim
  (CIs, p-values, n) — so that on a Q&A challenge the presenter can
  answer.
- A "transition" line — what the next slide builds toward.

### 10.3 Provenance

`notes_provenance.md` links every backup-number claim and every
citation to its source: notebook+cell, REPORT line, or pool ref.
Mirrors `methods_provenance.md` structure. Validator P-notes-
provenance enforces (every numeric claim traceable).

### 10.4 Speaker notes are not on-slide

The slide-compose prompt is forbidden from putting speaker-notes
content on the slide itself. The validator P-density enforces (max 35
words on slide; speaker notes can be 150 words). If the presenter
needs the detail visible, they can hide-or-show speaker notes in
their tool of choice (PowerPoint presenter view, Keynote rehearsal
mode).

---

## 11. Q&A preparation deliverable

`qa_prep.md` — separate output, not a slide section by default
(except as `qa_anticipated` appendix slides; see §6).

### 11.1 Question generation

For talk-30: 10 questions. talk-15: 5. talk-45: 12. Lightning-5: none.

Question generation prompt synthesizes from:

- Adversarial review (if present): the harshest unresolved findings
  become anticipated questions.
- Limitations slides on the deck: each gap is a likely question.
- Cross-tenant slide: questions about platform reach and integration.
- The throughline: any sub-claim with `partial` or `contradicts`
  evidence strength is a likely challenge.

### 11.2 Answer structure

Each Q&A entry has:

- Question (one sentence, in the voice of a tough peer reviewer).
- Brief answer (3–5 sentences, answerable from project artifacts).
- Evidence pointers (notebook+cell, REPORT line, citation).
- Follow-up depth (one sentence: "if asked again, also mention X").

### 11.3 Hidden appendix slides (optional)

If `--qa-slides` is set, the skill emits `qa_anticipated`-layout
slides at the end of the deck (slide IDs > visible_count). The
presenter can navigate to them by slide number during Q&A or hide
them entirely. Default off (most presenters prefer notes-only).

---

## 12. Posters (separate render path)

Posters are NOT animated, NOT speaker-noted, NOT interactive. They
are a single fixed-grid layout filled from the same throughline +
substory plan as a talk.

### 12.1 Templates

Two templates, both shipped under `skill/references/templates/`:

- `kbase-poster-horizontal.pptx` — 48×36 in, landscape.
- `kbase-poster-vertical.pptx` — 36×48 in, portrait.

Each has fixed text-box and figure-frame placeholders pre-positioned.
The skill fills placeholders, does not reposition them.

### 12.2 Content selection for posters

A poster's content is the talk's content compressed:

- Title (presenter, affiliation, contact).
- Abstract / TL;DR (the meta-arc punchline + 1 sentence per substory).
- Methods summary (the `methods_summary` slide content).
- 2–4 figures (the most evidence-dense from the talk).
- Cross-tenant integration (mandatory, single panel).
- Conclusions / Implications (the `implications` slide content).
- Acknowledgments (single line).
- References (3–5 short-form).

### 12.3 No animation, no Q&A prep, no speaker notes

By design. Posters are a static deliverable.

### 12.4 Render path

Poster mode skips the slide-compose prompt entirely; uses a poster-
fill script that takes throughline + substories + selected figures
and writes directly into the template's placeholders.

---

## 13. Mechanized validators (P1–P10)

Mirrors paper-writer's M1–M10 (paper-writer SPEC §7). Each validator
has 4 escalation paths: auto-fix | escalate-as-analysis-request |
user-modify | accept-as-limitation.

| ID | Validator | Description | Escalation default |
|---|---|---|---|
| P1 | Mode budget | Slide count within mode's range (e.g., talk-30: 25–32) | auto-fix (re-allocate) |
| P2 | Time budget | Estimated time/slide × slide count = mode minutes ± 20% | auto-fix (re-allocate) |
| P3 | Numeric provenance | Every numeric claim on slide traces to REPORT.md (v0.4 M5a wrapper around `check_quantitative_grounding`); v0.3 `speaker_notes_provenance` retired per D-059 | escalate (notebook) |
| P4 | Citation pool integrity | Every short-form ref on slide resolves to verified pool entry | scope-down |
| P5 | Contrast WCAG AA | Body text ≥4.5:1 contrast vs background; title ≥3:1 (large text) | auto-fix (color swap) |
| P6 | Figure resolution | Embedded images ≥1080p in their displayed area; not stretched | escalate (regen at higher res) or auto-fix (unstretch) |
| P7 | Divider slides | One `section_divider` between substories; one `big_idea` opening each substory | auto-fix (insert) |
| P8 | Required slides present | Title, cross-tenant, acknowledgments, references all present | auto-fix (insert) |
| P9 | No orphan citations | Every pool entry that's cited on a slide also lives in references slide and speaker notes | auto-fix (insert) |
| P10 | Density discipline | Max 35 words/slide, max 5 elements/slide, ≥24pt body text | escalate (slide split) or accept-with-warning |

Hard caps: 2 rewrite passes total (mirrors paper-writer §8.3). After
2 passes with unresolved validators, the skill halts with a
checkpoint and a list of unresolved P-violations for user decision.

### 13.1 P3 (numeric provenance) is the most-load-bearing validator

If P3 fails, the slide makes a numerical claim that the skill cannot
trace. This is the primary risk surface. Default escalation is
`escalate-as-analysis-request` — the orchestrator emits a structured
request: "claim X on slide Y references no notebook output;
re-extract from notebooks under <hypothesis>, or remove the claim."
User-modify and accept-as-limitation are valid alternatives but the
orchestrator does not auto-fix P3 (it would require fabricating
numbers).

**v0.4 mechanism (M5a Tier C, 2026-05-24 per D-058 + D-059):** P3 is
implemented as a thin wrapper around
`tools/check_quantitative_grounding.check_grounding(draft_dir)` —
the v0.4 REPORT-walking authority. It walks every numeric literal
on the slide and greps `REPORT.md` for verbatim matches (with
canonical-form normalization for thousands-commas, SI suffixes,
etc.). The v0.3 contract was different: per-slide
`speaker_notes_provenance` index that the composer emitted
alongside speaker notes. The v0.4 fused-notes composer
(`slide_compose.v2.md`, M3 per D-033/D-044) doesn't emit that
index, so the v0.3 P3 implementation was no longer correct on v0.4
specs (M4b Tier E live probe found it fired on every number on
every slide, 282 false positives on `ibd_phage_targeting/draft_1`).
The M5a rewrite restores P3's load-bearing P0 status in the M4b
cascade `_P0_VALIDATORS` set (D-058 demote obsolete).

**Severity mapping** (D-061): only HIGH-severity ungrounded numbers
(per `check_quantitative_grounding._classify_severity`: n=X claims,
ratios, scientific notation, integers >1000) become P3 Violations
with `severity="error"`. Medium/low-severity findings (percent,
decimal, small integer) are lifted as P1/P2 advisory by the M4b
cascade's `_read_quantitative_grounding` aggregator instead. The
split prevents double-lifting on the same number while preserving
P3's role as the load-bearing mechanical fail-fast surface for
high-stakes numbers.

**P3 requires draft_dir.** Legacy `validate_p3_numeric_provenance(spec)`
calls without draft_dir return `status="skipped"` with a note — the
v0.3 `speaker_notes_provenance` fallback is retired; there is no
no-draft-dir code path. The M4b cascade always passes draft_dir.

### 13.2 P-validator dispatch table

| Validator | Section/file | Notes |
|---|---|---|
| P1 | (orchestrator) | Slide count is a budget concern; orchestrator re-allocates |
| P2 | (orchestrator) | Time budget; re-allocate |
| P3 | `tools/check_quantitative_grounding.py` (wrapped) | v0.4 walks REPORT.md (D-059). v0.3 escalated to `slide_compose.v1` / `speaker_notes.v1` via the per-slide provenance index (retired). |
| P4 | `slide_compose.v1` or `citation_pool.v1` | Pool gap → pool gen agent; on-slide ref drift → compose agent |
| P5 | (orchestrator) | Color swap is mechanical |
| P6 | (orchestrator) or escalation | Figure regen is gap-fill |
| P7 | `substory_design.v1` | Divider/big-idea structure is substory's responsibility |
| P8 | (orchestrator) | Boilerplate inserts |
| P9 | (orchestrator) | Mechanical |
| P10 | `slide_compose.v1` | Density is composition concern |

---

## 14. Assembly

### 14.1 Master template

`kbase-presentation-master.pptx` — derived from the user-supplied
.potx (`KBase 2026 and beyond.potx`). Brand kept from .potx (colors,
fonts, logo, footer treatment). Layouts replaced with the 15 named
layouts in §6. Shipped as package data; loaded via importlib.resources
at assembly time.

The master is regenerated from a script (`tools/build_master.py`) so
that brand updates can be re-derived from a refreshed .potx without
hand-editing the master. (D-007.)

### 14.2 Slide-spec → pptx

The orchestrator emits `slide_spec.json` per draft, then the assembler
walks it into python-pptx slides. The schema is the contract between
four consumers (assembler, validator, slide-compose prompt, revise
verb).

**Authoritative source of the contract:**
[`src/beril_presentation_maker/skill/tools/slide_spec.py`](src/beril_presentation_maker/skill/tools/slide_spec.py)
— pure-stdlib hand-rolled validator (~700 LOC), constants, per-layout
checkers, and a CLI (`validate | schema-json | example`).

**Generated documentation:**
[`src/beril_presentation_maker/skill/references/slide_spec.schema.json`](src/beril_presentation_maker/skill/references/slide_spec.schema.json)
— JSON Schema Draft 2020-12 doc emitted by `slide_spec.py schema-json`.
Useful for prompt-context hygiene; the Python validator is authoritative.

**Design rationale + open questions resolved:**
[`reference/slide-spec-schema-proposal.md`](reference/slide-spec-schema-proposal.md)
— Adam-signed-off proposal documenting the 5 substantive decisions:
hand-rolled validator, 7 diagram node shapes (incl. swimlane),
`tools_versions` as Option A list-of-objects, on-slide `revision_log`,
on-slide `validator_status`.

**Top-level shape (abridged; see proposal §1 for full):**

```json
{
  "schema_version": "1.0",
  "project_id": "<id>",
  "mode": "talk-30 | talk-15 | talk-45 | lightning-5 | poster-h | poster-v",
  "audience": "peer",
  "tier": "STRONG | THIN | EXPLORATORY",
  "throughline": {"id": "TL1", "punchline": "...", "tier_evidence": "STRONG"},
  "substories": [{"id": "S1", "punchline": "...", "slide_ids": [...]}],
  "slides": [
    {
      "id": 1,
      "layout": "<one of 15>",
      "substory_id": "S1 | null",
      "content": { /* layout-discriminated; see proposal §3 */ },
      "speaker_notes": "...",
      "speaker_notes_provenance": [...],
      "validator_status": {"P3": "pass", "P10": "soft-warning"},
      "revision_log": [...]
    }
  ]
}
```

Use `python3 src/.../skill/tools/slide_spec.py example all` to dump a
minimal valid spec covering every layout. Use `... example <layout>` for
a single-slide example.

### 14.3 PDF output

`assemble --format pdf` produces `slides.pdf` from `slides.pptx`.
This requires LibreOffice on PATH (`soffice --headless --convert-to
pdf`). On systems without LibreOffice, the assembler emits
`slides.pptx` only and prints: "PDF render unavailable (LibreOffice
not found). Open slides.pptx in PowerPoint/Keynote and export to PDF
manually." Documented in SKILL.md.

This is a deliberate choice not to bundle a PDF renderer. (D-024 in
paper-writer set the precedent: pure-Python deps only for the core
package; system binaries only when explicitly opt-in.)

---

## 15. Posters (assembly)

Posters skip the slide-compose path entirely. The assembler:

1. Loads `kbase-poster-horizontal.pptx` or `-vertical.pptx`.
2. Maps poster-sections to template placeholders (title-author,
   abstract, methods, figures, cross-tenant, conclusions,
   acknowledgments, references).
3. Fills placeholders. No new shapes added; placeholders are sized
   for the content they hold.
4. Validates: P5 (contrast, on poster), P6 (figure resolution at
   300dpi for print), P10 (density: posters tolerate higher density
   than slides; the threshold is 1500 chars/panel, not 35 words/slide).
5. Outputs `poster.pptx` and optionally `poster.pdf`.

No speaker notes, no Q&A prep. Done.

---

## 16. State machine

Mirrors paper-writer's state machine (paper-writer LAYOUT.md §6
state.json schema), with talk-specific phase additions.

### 16.1 Phases

```
plan → throughline_pick → substory_approval → drafting → review → assembled
```

- `plan` — read inputs, classify tier, emit triage message.
- `throughline_pick` — emit candidates, pause for user (default).
  `--throughline auto` skips the pause.
- `substory_approval` — emit substory list, pause for user. `--no-
  substory-pause` skips.
- `drafting` — generate slide_spec.json + speaker notes + Q&A prep
  + cross-tenant section + diagrams + image-gen approvals.
- `review` — invoke beril-adversarial (or fallback reviewer); apply
  rewrite pass(es); re-run validators.
- `assembled` — slide_spec → pptx; optionally pdf.

### 16.2 Persistence

All phase transitions written to `state.json`. Each prompt invocation
gets a one-line entry in `audit/<phase>.stream.log`. Cost summary
appended to `talks/cost-log.jsonl` at end of each phase.

### 16.3 Resume semantics

`continue` reads `state.json`, hash-diffs source artifacts (REPORT,
RESEARCH_PLAN, notebooks, figures), reports new/changed files to user,
and proceeds with the paused phase. If a source artifact has changed
in a way that affects the throughline, the orchestrator triggers a
throughline re-evaluation prompt before proceeding (mirrors paper-
writer's `throughline.reevaluations[]`).

### 16.4 Hard caps

- 2 rewrite passes max.
- 1 substory-list approval round (re-running starts a new draft).
- $X AI-image-gen budget (`--ai-diagram-budget`, default $5.00).
- 90-minute wall-clock soft cap (warn at 90, halt at 180).
- Per-`revise` invocation: 1 retry max (D-026).

### 16.5 Targeted revision via `revise` (post-assembled)

After a draft reaches `assembled` phase, the user may request
targeted revisions without restarting the draft (D-026). The
`revise` CLI verb takes a draft directory and a target scope:

```
beril-presentation-maker revise <draft_dir> --slide N "<instruction>"
beril-presentation-maker revise <draft_dir> --substory <id> "<instruction>"
beril-presentation-maker revise <draft_dir> --speaker-notes-only N "<instruction>"
beril-presentation-maker revise <draft_dir> --add-image N "<image-prompt>"
```

Scope semantics:

- `--slide N` — re-runs `slide_compose.v1` for slide N only, with the
  existing slide_spec entry as starting context plus the instruction.
  Other slides untouched. Speaker notes for that slide regenerate.
- `--substory <id>` — re-runs `substory_design.v1` + `slide_compose.v1`
  for all slides in that substory. Other substories untouched.
- `--speaker-notes-only N` — regenerates speaker notes for slide N
  without touching slide content. Cheap; for "say it differently."
- `--add-image N "prompt"` — interactive override channel (Channel B,
  §8.3) injecting an AI-generated image into slide N.

After every revise, the affected slides re-run validators P3–P10
(skip P1, P2 — slide count and time budget unchanged). Failures
re-enter REPAIR_MODE bounded retry (D-020). Reframing-log entries
record the user instruction and the resulting change.

Throughline and substory-list edits are NOT permitted via `revise`
(those are structural changes that warrant a fresh draft via
`continue --re-evaluate-throughline`).

After all revisions land, the user runs `assemble` to re-render the
pptx.

---

## 17. Cost / latency targets

| Phase | Wall clock | Tokens | Notes |
|---|---|---|---|
| Plan + Triage | 1–2 min | ~25K input, ~3K output | reads inputs, classifies |
| Throughline candidates | 2–4 min | ~40K, ~8K | extracts evidence maps |
| Substory design | 1–2 min | ~15K, ~3K | per-substory punchlines |
| Citation pool (build or reuse) | 0–6 min | ~0 (reuse) or ~80K, ~5K | reuses from paper if present |
| Cross-tenant discovery | 1–2 min | ~20K, ~2K | regex + LLM extraction |
| Figure curation | 1–2 min | ~10K, ~1K | selects 4–10 figures |
| Slide composition | 5–10 min | ~150K, ~20K | per-substory parallel |
| Speaker notes | 2–4 min | ~50K, ~10K | per-slide pass |
| Q&A prep | 2–3 min | ~20K, ~3K | one big call |
| AI-image-gen (if enabled) | varies | (CBORG cost) | per-image approval gate |
| Validation pass | <1 min | <1K, <1K | mechanical |
| Adversarial review | 5–10 min | (separate skill cost) | fallback if absent: 3–6 min inline |
| 1 rewrite pass | 3–6 min | ~80K, ~10K | targeted |
| Assembly | <1 min | 0, 0 | python-pptx only |
| **Total (talk-30 default)** | **25–45 min** | **~410K input, ~60K output** | **~$4–$10 + adversarial + image-gen** |

If approaching 2× upper bound on either dimension, fail loud with
checkpoint + user prompt to continue. Cost summary in
`audit/cost-summary.md` at end.

Talk-15 / lightning-5: roughly half the time and cost. Talk-45: 1.3×.
Posters: 8–15 min, ~$2–$4 (no speaker notes, no Q&A, no rewrite pass).

---

## 18. Coupling to beril-adversarial

Loose coupling, mirrors paper-writer §6. The skill shells out to
`beril-adversarial` if installed. v1 uses `--type paper` (the closest
existing type) until `--type presentation` is added upstream (deferred
to v0.2 of presentation-maker; D-018).

Fallback: inline `prompts/fallback_reviewer.v1.md` runs as a
memoryless adversarial pass on the assembled deck before the rewrite
loop. Cheaper but less harsh than the real adversarial skill.

---

## 19. Repo and release plan

- Source dev: `spike/beril-presentation-maker-skill-draft/`.
- Remote: `ArkinLaboratory/beril-presentation-maker-skill` (private
  while in development).
- v0.1.0-spec — this commit. Spec + scaffold + smoke tests only. No
  drafting code.
- v0.1.0-master-draft — author the master template, get Adam's
  review of the 15 named layouts. No drafting code.
- v0.1.0-extractors — Phase 2 (mirror paper-writer Phase 2):
  cross_tenant_discovery, figure_curate, validate_presentation
  (P1–P10), citation_pool reuse from paper-writer.
- v0.1.0-prompts — Phase 3 (mirror paper-writer Phase 3): plan,
  throughline, substory_design, slide_compose, speaker_notes,
  qa_prep, fallback_reviewer, rewrite, diagram_design.
- v0.1.0-poster — poster render path.
- v0.1.0 — full release after live test on 1–2 BERIL projects.

---

## 20. Open questions for revisit

1. **Live test target projects.** Need 2 BERIL projects to validate
   the talk pipeline against (one STRONG, one THIN, one
   EXPLORATORY). Candidates: `functional_dark_matter` (STRONG),
   `cf_formulation_design` (STRONG), `genotype_to_phenotype_enigma`
   (THIN). Same set as paper-writer Phase 2 validation.
2. **AI-image-gen quality.** Gemini Pro Image quality on scientific
   conceptual diagrams is unknown until tested. May need to fall back
   to OpenAI gpt-image-1 directly (key in `.env`) if Gemini disappoints.
3. **Procedural-diagram expressiveness.** python-pptx native shapes
   are limited compared to SVG. Some workflow diagrams may look ugly
   compared to hand-drawn equivalents. Mermaid pre-render to PNG (via
   mermaid-cli npm dep) is a v1.x option.
4. **Master-template authoring.** The 15 named layouts are derived
   from the .potx but require one-time hand authoring. Adam reviews
   the layouts before code depends on them.
5. **Paper-writer pool reuse format.** Paper-writer uses a 10-field
   strict citation format (Phase 2 done). Pool format must be
   stable for reuse to work. If paper-writer changes pool format
   in Phase 3, presentation-maker breaks.
6. **Lay/program-officer audience.** Out of v1 scope but the prompts
   should be structured so adding `--audience lay` later is a prompt
   variant, not an architectural change.
