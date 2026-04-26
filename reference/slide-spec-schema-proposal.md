# slide_spec.json — schema proposal (v0.1)

**Status:** ACCEPTED 2026-04-26. Implemented at
`src/beril_presentation_maker/skill/tools/slide_spec.py` (validator,
types, examples) and
`src/beril_presentation_maker/skill/references/slide_spec.schema.json`
(JSON Schema document, generated from the validator).

This is the contract between four consumers:

1. **`assemble_pptx.py`** — reads slide_spec.json → emits .pptx.
2. **`validate_presentation.py`** — reads slide_spec.json → emits P1–P10 results.
3. **`slide_compose.v1.md`** (Phase 3 prompt) — emits slide_spec.json fragments.
4. **`revise` verb** — modifies a single slide's content in-place.

Schema drift is expensive across four consumers; this document fixes the
contract before code lands. Replaces SPEC.md §14.2's sketch.

---

## 1. Top-level shape

```json
{
  "schema_version": "1.0",
  "draft_dir": "projects/<project_id>/talks/draft_N/",
  "project_id": "functional_dark_matter",
  "mode": "talk-30",
  "audience": "peer",
  "tier": "STRONG",
  "created_at": "2026-04-26T15:00:00Z",
  "last_modified": "2026-04-26T15:42:00Z",
  "model_used": {
    "compose": "claude-opus-4-6",
    "image_gen": "google/gemini-pro-image"
  },

  "throughline": {
    "id": "TL2",
    "punchline": "Annotation is a hypothesis, not a fact — closing the loop turns dark genome matter into testable predictions.",
    "tier_evidence": "STRONG"
  },

  "substories": [
    {
      "id": "S1",
      "punchline": "Inner-loop annotation outperforms one-shot RAST on Morgan Price gold standard.",
      "slide_ids": [2, 3, 4, 5, 6],
      "approved_at": "2026-04-26T14:55:00Z"
    },
    {
      "id": "S2",
      "punchline": "K-BERDL data integration enables this loop at scale.",
      "slide_ids": [7, 8, 9, 10, 11]
    }
  ],

  "citation_pool_ref": "citation_pool.json",

  "slides": [
    { /* per-slide objects, see §2 */ }
  ]
}
```

**Fields:**
- `schema_version` — bump on breaking changes; consumers gate behavior on this.
- `mode` — one of `talk-30 | talk-15 | talk-45 | lightning-5 | poster-h | poster-v`.
- `audience` — `peer` only in v1; reserved for future tiers.
- `tier` — `STRONG | THIN | EXPLORATORY` from the plan-phase triage; affects validator behavior and prompt language.
- `throughline.punchline` — the meta-arc claim, used by validator and as `big_idea` slide content if user opts in.
- `substories[].slide_ids` — ordered list of slide IDs in this substory; substories are named clusters of analyses (D-002 rev1).
- `citation_pool_ref` — relative path to the pool JSON. Resolved against `draft_dir`.

---

## 2. Per-slide shape

Common fields (every slide has these):

```json
{
  "id": 5,
  "layout": "claim_evidence",
  "substory_id": "S1",
  "content": { /* layout-specific, see §3 */ },
  "speaker_notes": "Long-form notes for the presenter, 100–150 words. Cites Smith 2023 for the gold-standard methodology...",
  "speaker_notes_provenance": [
    {"claim": "90% accuracy on Morgan Price gold standard",
     "source": {"kind": "report_line", "path": "REPORT.md", "line": 142}},
    {"claim": "Smith 2023 methodology",
     "source": {"kind": "citation_pool_key", "key": "smith2023"}}
  ],
  "validator_status": {
    "P3_numeric_provenance": "pass",
    "P10_density": "pass"
  },
  "revision_log": [
    {
      "at": "2026-04-26T15:30:00Z",
      "instruction": "tighten the punchline; make the third bullet specific",
      "scope": "slide",
      "model": "claude-opus-4-6",
      "tokens_in": 4012,
      "tokens_out": 318
    }
  ]
}
```

**Field semantics:**
- `id` — integer, sequential from 1, stable across revisions.
- `layout` — one of the 15 vocabulary names. Drives content shape (§3).
- `substory_id` — string ref into `substories[].id`. `null` for boilerplate slides (`title`, `acknowledgments`, `references`, `qa_anticipated`).
- `content` — layout-discriminated object (§3).
- `speaker_notes` — markdown-allowed string. Length is mode-dependent (60 wd for lightning-5, 100–150 for talk-30, 150 for talk-45).
- `speaker_notes_provenance` — list of (claim → source) pairs. Validator P3 uses this to verify every numeric claim traces.
- `validator_status` — set by `validate_presentation.py`. Values per SPEC §13: `pass | soft-warning | accepted-with-warning | escalated | user-fixed | accepted-as-limitation`.
- `revision_log` — append-only on each `revise` invocation (D-026).

---

## 3. Per-layout content shapes

Discriminated by `layout`. JSON Schema enforces via `allOf` + `if/then`. The
Python types module (`slide_spec.py`) mirrors with TypedDicts.

### 3.1 `title`

```json
{
  "layout": "title",
  "content": {
    "title": "BERIL: Knowledge amplification at platform scale",
    "subtitle": "How the inner loop turns annotations into hypotheses",
    "presenter": "Adam Arkin",
    "affiliation": "UC Berkeley · LBNL",
    "date": "2026-06-12",
    "venue": "BER AI Summit"
  }
}
```
**Required:** `title`, `presenter`, `date`. **Optional:** `subtitle`, `affiliation`, `venue`.

### 3.2 `section_divider`

```json
{
  "layout": "section_divider",
  "content": {
    "punchline": "Inner-loop annotation outperforms one-shot RAST on Morgan Price gold standard.",
    "substory_number": 1
  }
}
```
**Required:** `punchline`. **Optional:** `substory_number` (1-based, derived from `substories[]` order if omitted).

### 3.3 `big_idea`

```json
{
  "layout": "big_idea",
  "content": {
    "title": "Annotation is a hypothesis, not a fact — it should improve over time.",
    "supporting_graphic": "figures/fig03_loop_concept.png"
  }
}
```
**Required:** `title`. **Optional:** `supporting_graphic` (path relative to draft_dir, must exist; validator P-figure checks).

### 3.4 `big_number`

```json
{
  "layout": "big_number",
  "content": {
    "headline": "27,000,000",
    "subtitle": "fitness scores integrated across 1,400 genomes",
    "sub_pointer": "see Substory 2 for K-BERDL integration details",
    "source_footer": "Source: REPORT.md §3.2"
  }
}
```
**Required:** `headline`, `subtitle`. **Optional:** `sub_pointer`, `source_footer`.

The `headline` is the slide title (renders in 66pt bold per LAYOUT_FIXES `big_number`).

### 3.5 `claim_evidence`

```json
{
  "layout": "claim_evidence",
  "content": {
    "title": "Annotation Agent reaches 90% accuracy on Morgan Price gold standard.",
    "bullets": [
      "Inner loop closes 47 of 52 'hypothetical protein' annotations after 3 cycles.",
      "Cross-author edge classification (atlas algorithm) confirms novelty against prior work.",
      "Per-genome runtime: 12 minutes on standard CBORG quotas."
    ],
    "figure": "figures/fig05_accuracy_comparison.png",
    "figure_caption": "Accuracy vs. baseline RAST on Morgan Price's curated set.",
    "citations": ["price2024", "smith2023"]
  }
}
```
**Required:** `title`, `bullets` (1–3 entries). **Optional:** `figure` + `figure_caption` (always together), `citations` (list of pool keys).

### 3.6 `two_column_compare`

```json
{
  "layout": "two_column_compare",
  "content": {
    "title": "Inner-loop annotation: before vs. after",
    "left_col_title": "Before (one-shot RAST)",
    "left_col_content": [
      "60% accuracy",
      "37 unresolved hypothetical proteins",
      "No iteration"
    ],
    "right_col_title": "After (inner loop, 3 cycles)",
    "right_col_content": [
      "90% accuracy",
      "5 unresolved",
      "12 min/genome"
    ]
  }
}
```
**Required:** all 5 fields. `left_col_content` and `right_col_content` are lists of strings (rendered as bullets) OR a single block of markdown.

### 3.7 `data_figure`

```json
{
  "layout": "data_figure",
  "content": {
    "title": "Fitness scores cluster by metal type — chromate stress separates clearly.",
    "figure": "figures/fig08_metal_clustering.png",
    "caption": "PCA of fitness scores across 12 metal-stress conditions in DvH.",
    "data_source": "K-BERDL fitnessbrowser, snapshot 2026-04-15"
  }
}
```
**Required:** `title`, `figure`, `caption`. **Optional:** `data_source` (footer).

The `title` is the *interpretation*, not "Figure 8" — punchline rule.

### 3.8 `workflow_diagram`

```json
{
  "layout": "workflow_diagram",
  "content": {
    "title": "Cycle: gap detection → LLM resolution → model rebuild → next gap",
    "diagram": {
      "kind": "boxes_and_arrows",
      "nodes": [
        {"id": "n1", "label": "REPORT.md", "shape": "rectangle", "x": 0.5, "y": 1.5, "w": 1.5, "h": 0.8},
        {"id": "n2", "label": "Gap detector",   "shape": "rounded", "x": 2.5, "y": 1.5, "w": 1.6, "h": 0.8},
        {"id": "n3", "label": "LLM resolution", "shape": "rounded", "x": 4.7, "y": 1.5, "w": 1.6, "h": 0.8},
        {"id": "n4", "label": "Model rebuild",  "shape": "cylinder", "x": 6.9, "y": 1.5, "w": 1.6, "h": 0.8}
      ],
      "edges": [
        {"from": "n1", "to": "n2", "kind": "elbow"},
        {"from": "n2", "to": "n3", "kind": "straight", "label": "open gaps"},
        {"from": "n3", "to": "n4", "kind": "straight"},
        {"from": "n4", "to": "n2", "kind": "curved", "label": "next cycle"}
      ]
    },
    "step_caption": [
      "1. Detect annotation gaps from REPORT-level analyses.",
      "2. Resolve via LLM with notebook-grounded context.",
      "3. Rebuild metabolic model; emit new gaps."
    ],
    "tool_version_footer": "diagram_render v0.1; python-pptx native shapes"
  }
}
```
**Required:** `title`, `diagram`, `step_caption` (exactly 3 entries). **Optional:** `tool_version_footer`.

The `diagram` field is consumed by `diagram_render.py` (Tier 2, native python-pptx shapes). Coordinate units are inches; `(0,0)` is upper-left of the diagram region (which the renderer maps to the layout's body placeholder). See §4 for diagram sub-schema.

### 3.9 `methods_summary`

```json
{
  "layout": "methods_summary",
  "content": {
    "title": "Methods grounded in notebooks; full detail in speaker notes.",
    "bullets": [
      "Annotation: gene-annotate v2.3 with CBORG-Claude-Sonnet",
      "Modeling: COBRApy 0.29; biomass from BiGG iML1515",
      "Validation: 932 reannotations vs. Morgan Price",
      "Statistical tests: Fisher exact (alpha=0.05); Bonferroni for 47 comparisons"
    ],
    "tools_versions": [
      {"tool": "gene-annotate", "version": "2.3.1"},
      {"tool": "COBRApy", "version": "0.29.0"}
    ],
    "see_notes_footer": true
  }
}
```
**Required:** `title`, `bullets` (5–10 entries). **Optional:** `tools_versions` (structured), `see_notes_footer` (boolean, default true).

### 3.10 `concept_illustration`

```json
{
  "layout": "concept_illustration",
  "content": {
    "title": "K-BERDL as a knowledge-amplification engine.",
    "image_path": "ai_images/img02_amplification_metaphor.png",
    "image_prompt": "A glowing brain made of microbes, network of pulsing connections, KBase teal and orange palette, conceptual illustration",
    "style": "metaphor",
    "caption": "Conceptual schematic — not data.",
    "ai_disclosure_footer": true,
    "provenance": {
      "model": "google/gemini-pro-image",
      "cost_usd": 0.18,
      "channel": "A",
      "approved_at": "2026-04-26T15:12:00Z",
      "quant_content_score": 0.04
    }
  }
}
```
**Required:** `title`, `image_path`, `image_prompt`, `style`, `provenance`. **Optional:** `caption`, `ai_disclosure_footer` (boolean, default true; always rendered per SPEC §8.3).

`style` is one of `metaphor | infographic | conceptual_diagram` (D-028).

`provenance.quant_content_score` is set by the LLM-as-judge validator; >0.5 → image rejected. Validator P-ai-image rechecks at validation time.

### 3.11 `cross_tenant_integration` (REQUIRED slide on every deck per SPEC §7)

```json
{
  "layout": "cross_tenant_integration",
  "content": {
    "title": "This work integrates 4 K-BERDL databases across 3 tenants.",
    "tenant_list": ["enigma", "pmi", "phage_foundry"],
    "kberdl_db_list": ["fitnessbrowser", "paperblast", "rast", "isolates"],
    "sibling_project_refs": [
      {"project_id": "metal_atlas", "what_was_leveraged": "metal-stress fitness profiles"},
      {"project_id": "annotation_agent_v1", "what_was_leveraged": "baseline annotations for comparison"}
    ],
    "data_flow_diagram": null,
    "no_signal_fallback": false
  }
}
```
**Required:** `title`. **Optional:** all others.

If discovery yielded zero cross-tenant signal, `no_signal_fallback` is `true` and the slide renders the honest fallback: "All data sourced from `<tenant>`. This project did not integrate across tenants."

`data_flow_diagram` is an optional `workflow_diagram`-style sub-spec (same shape as §3.8's `diagram` field).

### 3.12 `implications`

```json
{
  "layout": "implications",
  "content": {
    "title": "Three things change if this is true.",
    "bullets": [
      {
        "claim": "Annotation pipelines become continuous, not one-shot.",
        "evidence_pointer": "Substory 1, slides 5–6"
      },
      {
        "claim": "Cross-tenant model improvements compound at K-BERDL scale.",
        "evidence_pointer": "REPORT.md §4.3; atlas-style cross-author analysis"
      },
      {
        "claim": "Hypothetical-protein curation becomes triageable, not exhaustive.",
        "evidence_pointer": "47/52 resolved in 3 cycles"
      }
    ]
  }
}
```
**Required:** `title`, `bullets` (1–3 entries, each `{claim, evidence_pointer}`).

### 3.13 `acknowledgments`

```json
{
  "layout": "acknowledgments",
  "content": {
    "contributors": ["Morgan Price", "ENIGMA SFA team", "K-BERDL infrastructure"],
    "funder_logos": ["funders/doe.png", "funders/nsf.png"],
    "tenant_attribution": "Data: ENIGMA, PMI, Phage Foundry tenants",
    "code_repo_url": "https://github.com/ArkinLaboratory/functional-dark-matter"
  }
}
```
**Required:** `contributors`. **Optional:** `funder_logos`, `tenant_attribution`, `code_repo_url`.

The slide title is hard-coded "Acknowledgments" by the assembler — exempt from punchline rule per SPEC §6.1.

### 3.14 `references`

```json
{
  "layout": "references",
  "content": {
    "refs_short": [
      "Price 2024",
      "Smith 2023",
      "Naegle 2021",
      "ENIGMA et al. 2024"
    ],
    "ai_disclosure": "Slides drafted with beril-presentation-maker (Claude Opus 4.6); evidence anchored to project notebooks and REPORT.md.",
    "full_pool_in_speaker_notes": true
  }
}
```
**Required:** `refs_short` (≤8 entries). **Optional:** `ai_disclosure` (string; default emitted by assembler if omitted), `full_pool_in_speaker_notes` (boolean, default true).

The slide title is hard-coded "References" — exempt from punchline rule.

### 3.15 `qa_anticipated`

```json
{
  "layout": "qa_anticipated",
  "content": {
    "question": "What about non-DvH organisms? How does the inner loop generalize?",
    "answer_summary": "Loop is organism-agnostic; tested on D. vulgaris and Pseudomonad pilot.",
    "answer_detail": "The annotation agent uses sequence-based features (DIAMOND, PaperBLAST) that don't assume organism context. The model-rebuild step uses COBRApy biomass templates from BiGG which cover ~3000 species. We tested the full loop on a Pseudomonas spike and got comparable accuracy gains (84% → 91%) — see speaker notes for specifics.",
    "evidence_pointer": "Substory 2 slide 9; REPORT.md §6.1 (organism-generalization test)"
  }
}
```
**Required:** `question`, `answer_summary`, `evidence_pointer`. **Optional:** `answer_detail` (longer-form for speaker rehearsal).

`qa_anticipated` slides are typically hidden appendix (slide IDs > visible_count) per SPEC §11.3.

---

## 4. Diagram sub-schema (used by `workflow_diagram` and `cross_tenant_integration.data_flow_diagram`)

```json
{
  "kind": "boxes_and_arrows",
  "nodes": [
    {
      "id": "string-unique-within-diagram",
      "label": "displayed text",
      "shape": "rectangle | rounded | ellipse | parallelogram | cylinder | callout",
      "x": 0.5, "y": 1.5, "w": 1.5, "h": 0.8,
      "fill_color": "freshwater_blue",
      "text_color": "white"
    }
  ],
  "edges": [
    {
      "from": "node_id",
      "to": "node_id",
      "kind": "straight | elbow | curved",
      "label": "optional edge label"
    }
  ]
}
```

**Required:** `kind`, `nodes`, `edges`. Coordinates in inches; `(0,0)` upper-left of body placeholder. Colors must be brand-token names from `kbase-brand-tokens.json` palette.

`kind` is currently always `boxes_and_arrows`. Reserved for future kinds like `mermaid` (Mermaid markup → render).

---

## 5. Validation strategy

JSON Schema (Draft 2020-12) is the canonical contract. Python helpers in
`tools/slide_spec.py` use the `jsonschema` library OR fall back to a
hand-rolled validator (~150 LOC) if we want to avoid an extra runtime dep.

**Decision needed:** add `jsonschema` to runtime deps, or hand-roll? My
strawman: hand-roll. The schema is closed and small; jsonschema is a
heavy transitive dep for this single use. Pushback welcome.

Validator entry point:

```python
from beril_presentation_maker.skill.tools.slide_spec import (
    SlideSpec, validate_slide_spec, ValidationError
)
spec = SlideSpec.from_json(path)
validate_slide_spec(spec)   # raises on contract violations
```

`validate_presentation.py` (the P1–P10 module) uses this AS A PRE-FLIGHT
CHECK before running its own P-tier checks. Schema-valid is necessary but
not sufficient — P3 (numeric provenance) and P4 (citation pool integrity)
require cross-reference checks that are out of scope for JSON Schema.

---

## 6. Extension story

When a new layout is added (post-MVP):

1. SPEC §6 vocabulary table grows.
2. DECISIONS.md gets an entry.
3. `LAYOUT_RENAMES` and the master gain a layout.
4. This schema gains a §3.X entry + JSON Schema branch.
5. `slide_spec.py` TypedDicts gain a class.
6. `assemble_pptx.py` gains a layout-handler.
7. `validate_presentation.py` gains layout-specific checks.

Six places to change is a lot, but each change is small and the seven-file
pattern is rigid enough that drift is unlikely.

---

## 7. Decisions (Adam sign-off 2026-04-26)

**Q1: `jsonschema` runtime dep, or hand-roll validator? — DECIDED: hand-roll.**
Pure stdlib (`dataclasses`, `re`, `json`). One fewer transitive dep on
remote BERIL deploys. Mirrors paper-writer's `validate_manuscript.py`
discipline. Implemented in `slide_spec.py::validate_slide_spec()` (~700
LOC including per-layout checkers). The library `jsonschema` would have
been ~50 LOC of schema definition but adds an external runtime dep we
don't otherwise need.

**Q2: Diagram sub-schema vocabulary — DECIDED: 7 node shapes (added `swimlane`); tree deferred.**
v0.1 ships node shapes `rectangle | rounded | ellipse | parallelogram |
cylinder | callout | swimlane`. Edge kinds `straight | elbow | curved`.
ER diagrams represented as `rectangle` nodes with labeled edges (cardinality
in label). Decision trees represented as `rounded` + curved arrows (no
auto-layout). Hierarchy / org tree (`kind: "tree"` with parent/child
relations + auto-layout) is deferred to v0.2 — coordinate-driven works
for v1 and auto-layout adds complexity disproportionate to v1 needs.

**Q3: `tools_versions` shape — DECIDED: Option A, list of `{tool, version}` objects.**
Negligible additional friction for the slide-compose prompt (already
emits structured fields throughout). Material validator-hygiene benefit:
P-tools-versions can cleanly cross-check against `methods_provenance.md`
as dict lookup, no regex parsing of `"tool x.y.z"` strings with format
variation (semver, dotted, dated, "v2.3", etc.).

**Q4: `revision_log` location — DECIDED: on each slide.**
Append-only entries (~200 bytes each). Co-located with the content they
describe. Easier to answer "what was this slide before?" without cross-
file coordination. Bounded growth (revisions are user-initiated and
infrequent).

**Q5: `validator_status` location — DECIDED: on each slide.**
Validator writes back, next pass reads from same place. Cross-file
coordination would invite drift between intent (slide content) and
results (validation outcomes).

---

## 8. Implementation status (2026-04-26)

DONE in this commit:

1. ✅ `src/.../skill/tools/slide_spec.py` (~870 LOC) — constants, per-layout
   checkers, top-level validator, JSON Schema export, examples,
   CLI (validate / schema-json / example).
2. ✅ `src/.../skill/references/slide_spec.schema.json` — generated from
   `slide_spec.py::dump_json_schema()`. Test
   `test_schema_json_on_disk_matches_dump` ensures the on-disk file
   stays in sync with the live dump.
3. ✅ `tests/unit/test_slide_spec.py` (~440 LOC, 53 tests) — covers all 15
   layouts, top-level field enforcement, diagram sub-schema, JSON Schema
   round-trip, CLI surface.
4. ✅ SPEC §14.2 updated to reference `slide_spec.py` and the JSON Schema
   doc as the contract source-of-truth.

Total: 53 new tests; full sweep 81/81 pass. Approximately 1.5 hours
focused work (faster than the 2-hour estimate; faster because we'd
already specified the contract here).

## 9. Next phase (per LAYOUT.md §1)

With the schema pinned, the remaining v0.1.0-extractors-a deliverables are:

- `assemble_pptx.py` — slide_spec.json → .pptx (uses python-pptx + the
  derived master). The schema dictates layout dispatch.
- `validate_presentation.py` — P1–P10 mechanized checks. Uses
  `validate_slide_spec()` as a pre-flight, then runs P-tier semantic
  cross-checks (numeric provenance against notebooks, citation pool
  integrity, etc.).
- `stream_progress.py` — fork from paper-writer.

Then v0.1.0-extractors-b (content extractors), then -c (visual generators),
then a single integration test that exercises the full pipeline on the
synthetic-project fixture.
