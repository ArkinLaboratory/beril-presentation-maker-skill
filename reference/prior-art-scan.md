# Prior-Art Scan: Automated Scientific Presentation Generation

**Source:** Mixed — local copies under `repos-for-analysis/` for the
two we have on disk (claude-scientific-writer, AI-Scientist-v2 —
neither targets slides specifically), web-fetch + tool-vendor docs
for slide-specific systems (Marp, Slidev, Quarto-revealjs, Beautiful.ai,
Tome, Gamma). Retrieved 2026-04-26.

**How this document is used:** The "Patterns to ADOPT" lists below
are NOT all adopted as-is. SPEC §6, §8, §10, §13 and DECISIONS.md
record which patterns made it into v0.1 vs which were deferred or
rejected. The space of presentation-specific prior art is sparser
than the paper-writer space — most existing systems are either
markdown-to-slides converters (no LLM) or commercial deck-builders
(no scientific-evidence discipline). Read SPEC.md before treating
this document as a build spec.

---

## 1. Marp (markdown to slides)

**What it does:** Markdown-syntax-driven slide-deck compiler. Extends
CommonMark with slide separators (`---`), directive frontmatter
(theme, footer, paginate), and per-slide HTML class hooks. CLI,
VS Code extension, and core engine. Outputs HTML, PDF, PPTX.

**Patterns to ADOPT:**
- **ADOPT-MARP-1: Markdown-as-source-of-truth.** Version-control-friendly,
  diff-able, agent-friendly. Beril-presentation-maker takes a related
  but stricter approach: `slide_spec.json` is the machine-readable
  source of truth (typed schema, not free markdown), with companion
  `01_outline.md` for human review. Same intent (deck as code), tighter
  schema discipline.
- **ADOPT-MARP-2: Theme system as separable concern.** Marp ships a
  small set of base themes; users can swap or author. Mirrors our
  decision to ship `kbase-presentation-master.pptx` as the brand-
  bearing master separate from content (D-007).

**Patterns to IMPROVE:**
- **IMPROVE-MARP-1: No layout vocabulary.** Marp slides are freeform
  CommonMark blocks; "layout" is a CSS class hook with no semantic
  guarantees. Our 15-layout closed vocabulary (D-008) gives the
  drafting prompts type discipline that Marp lacks.
- **IMPROVE-MARP-2: No evidence grounding.** Marp doesn't know
  whether a number on a slide came from a notebook output or was
  invented. Beril-presentation-maker enforces P3 (numeric provenance).

**Patterns to SKIP:**
- **SKIP-MARP-1: Markdown frontmatter for theme.** We use a packaged
  `kbase-brand-tokens.json` instead — single source of truth, queryable
  by validators, no per-deck theme drift.
- **SKIP-MARP-2: HTML output as primary.** v1 prioritizes pptx
  (editable downstream) over HTML (live but locked).

**Risks they hit:**
- Diff-readability vs. visual fidelity tradeoff: pure markdown gives
  great diffs but no precise layout control.

---

## 2. Slidev (Vue-based slide framework)

**What it does:** Markdown + Vue components for highly interactive
slide decks. Live preview, code-block interactivity, MDX-style
component embedding. Targeted at developer audiences.

**Patterns to SKIP:**
- **SKIP-SLIDEV-1: Vue runtime dependency.** Adds Node.js + Vue toolchain
  to the deploy surface. Out of scope for a Python pipx package.
- **SKIP-SLIDEV-2: Web-first output.** Editable downstream is .pptx
  only in v1; live web slides are a v1.x consideration.

**Patterns to ADOPT:**
- **ADOPT-SLIDEV-1: Component-as-slide-shape.** Slidev's `<Tweet>`,
  `<Youtube>`, `<Github>` components are pre-baked layouts with
  typed inputs. Our 15-layout vocabulary plays the same role: each
  layout has typed `slide_spec.json` content that the assembler
  consumes.

**Risks they hit:**
- Tight coupling to Vue ecosystem; non-Vue users can't extend.

---

## 3. Quarto-revealjs (academic markdown → revealjs)

**What it does:** Quarto is a multi-format scientific authoring tool
(papers, books, websites, slides). Quarto-revealjs is its
slide-output target; takes a `.qmd` (Quarto markdown) file with
embedded R/Python code blocks and renders an HTML revealjs deck (or
PDF / pptx). Used heavily in the bioinformatics / data-science
community.

**Patterns to ADOPT:**
- **ADOPT-QUARTO-1: Code-cell execution at render time.** Quarto runs
  R/Python during render; figures are produced fresh from the
  notebook. We don't go this far (v1 reuses existing figures only,
  D-004), but the *idea* — bind figures to source code — is preserved
  in our `notes_provenance.md` discipline (every numeric claim traces
  to notebook+cell).
- **ADOPT-QUARTO-2: Cross-format authoring.** Quarto's same `.qmd`
  source can produce HTML, PDF, pptx. Our slide_spec.json plays a
  similar role: one source of truth, two render targets (talk pptx,
  poster pptx via separate template).
- **ADOPT-QUARTO-3: Bibliography integration.** Quarto consumes
  `.bib` files and renders citations. Our `bibliography.bib` (reused
  from paper-writer) follows the same pattern.

**Patterns to SKIP:**
- **SKIP-QUARTO-1: Live code execution.** Out of v1 scope. Talks
  consume the project's already-completed analysis; live re-execution
  is a v1.x consideration.
- **SKIP-QUARTO-2: Pandoc dependency.** Quarto wraps pandoc; we use
  python-pptx directly for the same reason paper-writer chose
  python-docx — pure-Python pipx install (D-016).

**Patterns to IMPROVE:**
- **IMPROVE-QUARTO-1: No throughline gate.** Quarto compiles whatever
  the user wrote; there's no "let me show you 3 candidate stories
  and pause for your pick" step. Our load-bearing user gate (D-002)
  is the safety we add.

**Risks they hit:**
- Pandoc version drift; complex theme overrides break across versions.

---

## 4. claude-scientific-writer (paper-writer prior art, included for completeness)

**What it does:** See paper-writer's `reference/prior-art-scan.md`
§1. The system targets paper / PDF generation, not slides.

**Relevance to presentation-maker:** Mostly indirect. The literature-
search + Perplexity Sonar Pro pattern in claude-scientific-writer is
not used here — citation pool is reused from paper-writer when
present (D-009) or built fresh via `citation_pool.v1.md` matching
paper-writer's discipline.

**Patterns to ADOPT:** None directly — paper-writer's
`reference/prior-art-scan.md` already documents the lifts from this
system.

**Patterns to SKIP:**
- The PDF-as-canonical-output stance — we want pptx editable
  downstream.

---

## 5. AI-Scientist-v2 (Sakana, paper-writer prior art, included for completeness)

**What it does:** See paper-writer's `reference/prior-art-scan.md`
§2. Targets LaTeX paper writeups via tree-search agentic ideation.

**Relevance to presentation-maker:** Indirect. Their template-
constrained writing (`blank_icml_latex/`) plays the same role as our
master template (D-007). Their citation key extraction +
deduplication parallels our citation-pool reuse (D-009).

**Patterns to ADOPT:** None directly — paper-writer adopted what was
relevant.

---

## 6. Beautiful.ai / Tome / Gamma (commercial AI deck generators)

**What they do:** Commercial SaaS tools that generate slide decks
from a prompt. Beautiful.ai uses "Smart Slides" with auto-layout;
Tome positions itself as "an AI assistant for storytellers"; Gamma
is "AI-powered presentations" with Notion-style editing.

**Patterns to ADOPT:**
- **ADOPT-COMM-1: Auto-layout from content.** All three pick a layout
  template based on content type (text-heavy vs. quote vs. image).
  Our slide-compose prompt does this explicitly via the 15-layout
  vocabulary, with the LLM choosing layout per slide based on the
  substory's content shape.

**Patterns to IMPROVE:**
- **IMPROVE-COMM-1: No evidence grounding.** None of these tools know
  whether a stat on a slide is a real number from a real analysis or
  invented. They fabricate plausibly. This is the existential failure
  mode we design against (SPEC §1.2 "not a quantitative-figure
  generator," P3 numeric provenance).
- **IMPROVE-COMM-2: No throughline gate.** Commercial tools optimize
  for "compelling deck right now"; the LLM picks the story. Our
  load-bearing user gate (D-002) is a deliberate slowdown.
- **IMPROVE-COMM-3: No closed brand discipline.** Commercial tools
  have themes but allow free deviation; we ship one brand (KBase)
  and validators enforce.
- **IMPROVE-COMM-4: No speaker notes with provenance.** Commercial
  tools generate speaker notes loosely; ours are evidence-anchored
  (SPEC §10.3, `notes_provenance.md`).

**Patterns to SKIP:**
- **SKIP-COMM-1: Web-locked editing experience.** All three are
  cloud SaaS; the deck lives in their app. Our pptx output is
  editable in PowerPoint / Keynote / Google Slides — local files,
  user-owned.
- **SKIP-COMM-2: Subscription pricing model.** Out of scope.
- **SKIP-COMM-3: No on-slide audit trail.** Commercial tools do not
  expose the provenance graph; we do (`notes_provenance.md`,
  `image_provenance.json`, `reframing_log.md`).

**Risks they hit:**
- Confident-sounding statistical claims with no source.
- Visual coherence drift across slides as the LLM picks layouts
  case-by-case without a closed vocabulary.
- Citation hallucination on slides that include "as shown by Smith
  2023".

---

## 7. python-pptx (the runtime library we depend on)

**What it does:** Pure-Python library for reading and writing
.pptx files. Maintains slide layouts, placeholders, autoshapes,
connectors, text formatting, embedded images. Widely used,
well-documented.

**Patterns to ADOPT:**
- **ADOPT-PPTX-1: Layout-driven authoring.** python-pptx exposes
  slide layouts as named, looked-up-by-name objects. Our master
  template's 15 named layouts (D-008) plug directly into this idiom.
- **ADOPT-PPTX-2: Placeholder-based content.** Each layout's
  placeholders have stable indices; the assembler fills by index,
  not by hand-positioning shapes. Eliminates a class of layout-drift
  bugs.

**Risks:**
- The library is mature but not actively developed at high velocity;
  known bugs in chart embedding and theme inheritance. v1 avoids
  python-pptx's chart embedding (we use pre-rendered figures from the
  project) and avoids deep theme manipulation (master is authored
  once, not modified at runtime).

---

## 8. Apple Keynote / Microsoft PowerPoint AI features

**What they do:** PowerPoint has Microsoft Designer (auto-layout
suggestions); Keynote has "Magic Move" transitions. Neither is a
full-deck-from-prompt generator.

**Patterns to SKIP:**
- Vendor-specific features that don't translate to pptx.

---

## 9. Critical commentary on the prior-art space

The space of LLM-driven scientific presentation generation is
genuinely thin compared to LLM-driven paper generation. Most
prior art falls into one of three categories:

1. **Markdown-to-slides converters** (Marp, Slidev,
   Quarto-revealjs) — no LLM, no evidence discipline. They're
   compilers, not authors. Adopt their idiom of "deck-as-code"; skip
   their lack of authoring guidance.
2. **Commercial AI deck builders** (Beautiful.ai, Tome, Gamma) — LLM,
   but no evidence discipline, no scientific honesty constraints,
   no audit trail. Adopt nothing of consequence; document what we
   improve against.
3. **Paper-generation systems with optional slide output**
   (claude-scientific-writer, AI-Scientist-v2) — neither is slide-
   primary. Their patterns inform paper-writer, not us.

**The specific gaps beril-presentation-maker addresses:**

- **Evidence-grounding for slides.** Every numeric claim provenanced
  to notebook+cell or REPORT line. No prior art enforces this for
  presentations.
- **Closed slide-shape vocabulary.** 15 named layouts mapped 1:1 to
  master-template layouts; visual coherence is structural, not
  cultural. No prior art does this for science decks.
- **Throughline + substory gate as user-owned.** The load-bearing
  decision (what story to tell) is the user's, not the LLM's.
  Commercial tools optimize for "compelling," not "honest."
- **Cross-tenant integration as a required section.** KBase-platform-
  level value framing baked into the deck shape. No prior art has
  this concept.
- **Speaker notes with provenance + Q&A prep with evidence
  pointers.** Both commercial and OSS tools generate notes loosely;
  we anchor every claim.
- **Adversarial review loop integration.** Sister-skill coupling
  (loose) means decks get harsh review before they're delivered.
  No prior art ships this in the same package.

---

## 10. Consolidated ADOPT / IMPROVE / SKIP table

| ID | Source | Pattern | Disposition |
|---|---|---|---|
| ADOPT-MARP-1 | Marp | Markdown-as-source-of-truth | Adopted (slide_spec.json + 01_outline.md) |
| ADOPT-MARP-2 | Marp | Theme as separable concern | Adopted (D-007 master) |
| ADOPT-SLIDEV-1 | Slidev | Component-as-typed-slide | Adopted (15-layout vocabulary) |
| ADOPT-QUARTO-1 | Quarto | Code-cell binding | Partial (notes_provenance, not live exec) |
| ADOPT-QUARTO-2 | Quarto | Cross-format from one source | Adopted (talk + poster from same plan) |
| ADOPT-QUARTO-3 | Quarto | Bibliography integration | Adopted (paper-writer pool reuse) |
| ADOPT-COMM-1 | Beautiful.ai/Tome/Gamma | Auto-layout from content | Adopted (slide-compose picks layout) |
| ADOPT-PPTX-1 | python-pptx | Layout-driven authoring | Adopted (master + assembler) |
| ADOPT-PPTX-2 | python-pptx | Placeholder-based content | Adopted (assemble_pptx) |
| IMPROVE-MARP-1 | Marp | No layout vocabulary | Improved via 15-layout closed set |
| IMPROVE-MARP-2 | Marp | No evidence grounding | Improved via P3 + provenance |
| IMPROVE-QUARTO-1 | Quarto | No throughline gate | Improved via D-002 user gate |
| IMPROVE-COMM-1 | Commercial | No evidence grounding | Improved via P3 + provenance |
| IMPROVE-COMM-2 | Commercial | No throughline gate | Improved via D-002 |
| IMPROVE-COMM-3 | Commercial | No closed brand | Improved via D-015 + P5 |
| IMPROVE-COMM-4 | Commercial | No speaker-notes provenance | Improved via SPEC §10.3 |
| SKIP-MARP-1/-2 | Marp | Frontmatter theme; HTML primary | Skipped |
| SKIP-SLIDEV-1/-2 | Slidev | Vue runtime; web-first | Skipped |
| SKIP-QUARTO-1/-2 | Quarto | Live exec; pandoc dep | Skipped |
| SKIP-COMM-1/-2/-3 | Commercial | Web-locked; sub pricing; no audit | Skipped |

---

## 11. Open questions for v1.x

1. **Live web preview.** Slidev / Reveal.js have a "watch mode"
   where the deck re-renders on edit. Could be useful for `revise`
   iteration; not in v1.
2. **Quarto-revealjs as alternate render path.** Some BERIL users
   may want HTML output for web-embedding. v1.x consideration.
3. **MS Designer-style auto-layout suggestions.** Could the
   slide-compose prompt offer 2–3 layout candidates per slide and
   let the user pick? More gates = more friction; deferred.
4. **Cross-deck style learning (atlas-pattern).** If we run on many
   talks across the BERIL corpus, learned patterns of what works
   visually could feed back into the slide-compose prompt. Atlas
   does this for project-level patterns; presentation-maker doesn't
   have an equivalent yet.
