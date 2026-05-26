# --- v3 overlay (BERIL Presentation-Maker — Slide Compose) ---

> **v3 (2026-05-26, v0.5.1 — concat overlay).** Everything ABOVE
> this overlay marker is the full `slide_compose.v2.md` body and
> remains authoritative for layout vocabulary, per-layout field
> names, speaker-notes authoring, evidence-anchor discipline,
> self-review checklist, and output protocol. This overlay ADDS
> two content-discipline obligations on top of v2:
>
> 1. **Register discipline** (D-072) — audience-facing prose must
>    avoid specialist references; provenance lives in
>    `data_source`.
> 2. **Q/A/R/C slide-role awareness** (D-071) — each substory's
>    slide arc opens with the Question and closes with the
>    Conclusion-for-next-substory; the user prompt passes both as
>    new inputs (`SUBSTORY_QUESTION`, `SUBSTORY_CONCLUSION`).
>
> **Schema:** wire-identical to v2; the only difference is
> `schema_version: "compose-fragment.v3"` (v2 emits
> `compose-fragment.v2`). The flat `slides[]` array, per-layout
> required fields, citation contract, and speaker-notes shape
> are all UNCHANGED — use v2's per-layout authoring rules above
> verbatim. **Do NOT** emit `section_divider` / `content_slides`
> as top-level keys.

## v3 failure modes ADDED on top of v2

The four v2 failure modes (layout-fit drift, citation fabrication,
rehearsed-vague delivery, caveat erosion) all still apply. v3 adds
two more:

- **Register leakage.** Specialist references (notebook IDs like
  `NB10`, `§Finding 7`, figure file names like `F03_...png`)
  appearing in audience-facing prose where the audience hears
  noise, not signal. Operator-facing `data_source` is the right
  home for these. v0.5 `tools/check_register_discipline.py`
  emits cascade Tier-1 P11 soft-warnings on register leakage;
  this overlay is the upstream cure.
- **Arc-role drift.** A slide composed without awareness of its
  substory role (Q/A/R/C) — an opening slide that doesn't name
  the question; a closing slide that doesn't state the
  conclusion. v0.5 `tools/check_substory_shape.py` enforces
  presence of Q+R+C slides per substory; this overlay is the
  upstream cure.

## v3 contract specifics — Register discipline (D-072)

**Audience-facing fields** (the slide's user-facing prose; the
audience reads these projected at 12-24pt on screen):

- v2's principal-text fields per layout (`title`, `headline`,
  `subtitle`, `punchline`, `bullets`, `caption`, `answer_summary`,
  `step_caption`, `metric_value`, `context`, `implication`,
  `concession`, `left_col_content`, `right_col_content`, and any
  other text the audience reads).
- v3 D-071 fields when present as slide-level: the prose that
  names a Question or states a Conclusion.

(See v2 §"Per-layout authoring rules" above for the exact field
names per layout. v3 does NOT introduce new fields — it
constrains the *content* of v2's existing fields.)

**Operator-facing fields** (audit/provenance; only operators see
these in audit JSONs or the deck's notes pane):

- `data_source` — REPORT/notebook citations LIVE HERE. Example:
  `"data_source": "REPORT.md §Finding 7; 04_lab_field_concordance.ipynb"`
- `speaker_notes` (the fused notes from v2 / D-033) — these go
  in the notes pane behind the slide. The speaker reads them;
  the audience doesn't. Specialist references are acceptable
  here.

**Specialist references to AVOID in audience-facing fields:**

| Pattern | Avoid in audience prose | Where to put it instead |
|---|---|---|
| `NB10`, `NB04b`, `NB10 §3` | always | `data_source` |
| `§Finding 7`, `§Step 13` | always | `data_source` |
| `01_demo.ipynb`, `04_lab_field.ipynb` | always | `data_source` |
| `cell 21`, `Cell 5` | always | `data_source` |
| `F03_recovery.png`, `fig28_domain.svg` | always | (don't reference filename in prose; the figure shows up in the slot) |
| `slide_spec.v1`, schema versions | always | (don't mention internal schema versions to the audience) |
| `Bakta v1.12.0`, tool versions | only if audience-relevant | `data_source` if you're hiding it; principal-text field if the talk's contribution IS "annotation tool version matters" |

**Specialist references to TRANSLATE in audience prose:**

| Bad (specialist) | Good (audience) |
|---|---|
| "Per §Finding 7 hedges" | "The analysis explicitly hedges" |
| "NB10 §3 shows ρ=0.982" | "Our species-count scoring shows ρ=0.982" |
| "From `02_gapmind_concordance_phylo.ipynb`" | "From the GapMind concordance analysis" |
| "Bakta v1.12.0 reannotated 83.7%" | "Updated annotation reclassified 83.7%" (if version isn't the point) OR keep "Bakta v1.12.0" (if it IS the point) |
| "fig03_recovery.png demonstrates …" | "[the figure on this slide] demonstrates …" |

**Tool names + versions (NUANCED per D-072):**

- "Bakta", "GapMind", "RAST" — tool *names* are usually
  audience-OK (audiences in the field recognize them).
- Tool *versions* (e.g., "v1.12.0") — usually NOT audience-OK
  unless the talk's contribution depends on the version.
- The per-project allowlist at `references/register_allowlist.md`
  (passed via `ALLOWLIST_TERMS` user-prompt input) can override:
  a project that says "we used Bakta v1.12.0 specifically because
  the database changed" can add `Bakta v1.12.0` to the allowlist.

## v3 contract specifics — Q/A/R/C slide-role awareness (D-071)

The user prompt will pass three substory-metadata fields you
didn't have in v2:

- `SUBSTORY_QUESTION` — the substory's scientific Question (≤25
  words; per D-071 substory_design.v3 contract).
- `SUBSTORY_CONCLUSION` — the substory's Conclusion for next
  substory (≤25 words; empty for the final substory).
- `ALLOWLIST_TERMS` — per-project register-discipline allowlist
  (comma-separated; empty default).

Use these to shape the substory's slide arc:

**Q-slide (opener — substory's first slide):**

- Default layout: `section_divider`. v2 requires this layout's
  fields per its per-layout rules above; the section_divider's
  principal-text field should NAME the SUBSTORY_QUESTION.
- Alternative: opening `big_idea` if the substory's question is
  itself the big idea. Use v2's `big_idea` field schema.
- Audience hears the question and prepares to follow.

**A-slides (analytical context; optional):**

- Layouts: `methods_summary`, `workflow_diagram`,
  `two_column_compare` per v2's per-layout rules.
- Only emit A-slides when the substory's analytical method needs
  explicit naming (a novel pipeline, a non-obvious comparison).
- For straightforward analyses, jump from Q-slide directly to
  R-slides.

**R-slides (results; required ≥1 per substory):**

- Layouts: `data_figure`, `data_table`, `big_number`,
  `two_column_compare`.
- The substory's evidence lives here. The R-slides answer the
  Q-slide's Question.
- Punchline-title per SPEC §6.1: each R-slide's title is the
  *claim the figure/data supports*, not "Results" or "Recovery
  rates" (those are topics, not punchlines).

**C-slide (closer — substory's last content slide; required
exactly 1):**

- Default layout: `claim_evidence`. v2's per-layout rule for
  `claim_evidence` requires the `title` field (annotated "the
  punchline; declarative") plus `bullets`. The `title` should
  STATE the SUBSTORY_CONCLUSION — the operative result that
  motivates the next substory's Question. The `bullets` are 1-3
  statements backing the claim.
- Alternative: closing `big_idea` (v2 requires `title`; same
  rule — the `title` STATES the SUBSTORY_CONCLUSION).

The cascade Tier-1 `tools/check_substory_shape.py` emits P1
soft-warnings if Q/R/C slides are absent. This overlay is
upstream of that check; getting the shape right here means the
cascade is clean.

## Post-composition self-check (NEW IN v3)

**Before emitting the fragment JSON**, re-read each slide and
do two passes IN ADDITION to v2's self-review pass:

### Pass 1 — Register discipline

For each audience-facing field (per the v3 table above), scan
for specialist-reference patterns. Replace with general
analytical language per the translation table.

Common automatic substitutions:

- `§Finding N` → "the analysis" or "this finding"
- `NB##` → "our [topic] analysis" (e.g., "our species-count
  scoring")
- `##_name.ipynb` → "the [topic] notebook" → usually drop
  entirely (audience doesn't need notebook attribution;
  `data_source` carries provenance)
- `cell ##` → drop entirely
- `fig##_name.png` → "[the figure on this slide]" or just remove
- `tool_name vN.M.O` → either keep (if audience-relevant) or
  drop version

If a specialist reference is genuinely required (e.g., the
talk's contribution IS naming a specific tool version), keep it
AND ensure the per-project allowlist (`ALLOWLIST_TERMS`)
includes it.

### Pass 2 — Q/A/R/C role check

For each slide:

- Is it the Q-slide (substory's first slide)? → Does its
  principal-text field name the SUBSTORY_QUESTION?
- Is it an R-slide? → Is the punchline a *claim*, not a topic?
- Is it the C-slide (substory's last content slide)? → Does its
  `title` (per v2's claim_evidence schema — annotated as "the
  punchline; declarative") STATE the SUBSTORY_CONCLUSION? On the
  final substory, state the throughline-level conclusion.

If a slide doesn't pass its role check, revise BEFORE emitting
JSON.

## v3 anti-patterns (additive to v2's failure-mode catalog)

(v2 failure modes above all apply; v3 adds the following.
Field-name references below match v2's per-layout schema
above — DO NOT substitute generic names like `title` for
layout-specific names like `punchline`.)

- **Specialist leakage.** Slide bullets containing NB-IDs or
  §Finding markers. → Replace with general analytical language;
  move provenance to `data_source`.
- **Topic-as-title.** R-slide whose principal-text field is a
  topic ("Recovery rates") rather than a claim. → Re-write as
  the claim ("Recovery rate is 91.6%, above competing methods").
- **Q-slide without question.** Opening section_divider whose
  `punchline` (per v2's section_divider schema) is a topic name
  rather than the SUBSTORY_QUESTION. → Re-write the `punchline`
  to NAME the SUBSTORY_QUESTION.
- **C-slide without conclusion.** Closing claim_evidence whose
  `title` (per v2's claim_evidence schema — the "title is the
  punchline; declarative" rule) doesn't STATE the
  SUBSTORY_CONCLUSION. → Re-write the `title` to be the explicit
  handoff statement.

## v3 inviolable rules (additive to v2's inviolable-rules list)

(v2 rules 1-4 above all apply; v3 adds:)

5. **v3:** Audience-facing prose is free of specialist
   references (NB-IDs, §Finding markers, file names, schema
   versions) — provenance lives in `data_source`.
6. **v3:** Q-slide (substory's first slide) names the
   SUBSTORY_QUESTION via the layout's principal-text field —
   for `section_divider` that's `punchline`; for opening
   `big_idea` that's `title` (per v2's per-layout rules above).
   C-slide (substory's last content slide) states the
   SUBSTORY_CONCLUSION via the layout's principal-text field —
   for `claim_evidence` that's `title` (annotated "the
   punchline; declarative" in v2); for closing `big_idea` that's
   `title`. **Do NOT** substitute generic names — use v2's
   layout-specific required field-name verbatim.
7. **v3:** The output `schema_version` is `compose-fragment.v3`
   (not `.v2`). Wire schema is otherwise IDENTICAL to v2 — flat
   `slides[]` array, same per-layout fields, same speaker_notes
   shape.
