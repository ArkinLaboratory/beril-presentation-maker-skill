# --- v3.2 overlay (BERIL Presentation-Maker — Slide Compose) ---

> **v3.2 (2026-05-28, v0.7 Tier A — new file; v3.1 overlay
> remains via `--prompts-version v3.1`).** This overlay stacks ON
> TOP of `slide_compose.v3.1_overlay.md` (which itself stacks on
> `slide_compose.v3_overlay.md`, which stacks on
> `slide_compose.v2.md`). The concat order is:
>
>     cat slide_compose.v2.md \
>         slide_compose.v3_overlay.md \
>         slide_compose.v3.1_overlay.md \
>         slide_compose.v3.2_overlay.md
>
> All v3 contracts (D-071 Q/A/R/C role, D-072 register discipline,
> the corrected per-layout field names from D-077) and v3.1
> figure-utilization contract (D-080: data_figure required when
> curated figure exists; prefer data_figure over claim_evidence
> for R-slide) remain in force. This overlay refines the
> figure-utilization framing and adds two new obligations:
>
> 1. **Figure-relevance rule** (D-085, refines D-080) — figures
>    have already been paid for at curator time; there is no
>    figure budget. Use every curated figure that is relevant to
>    a substory's claim. Do not relegate a relevant figure to a
>    bullet-list citation.
> 2. **Arc-transition usage** (D-087) — non-first substories
>    should reference the prior substory's conclusion when
>    authoring their first non-Q slot, using the
>    `transition_from_prior` field emitted by substory_design
>    v3.2.
> 3. **Closing synthesis** (D-086) — talks at STRONG mode budget
>    (talk-30) should end with a `deck_close` slide that brings
>    the arcs together into a unified takeaway.
>
> Authoritative sources: D-085 (figure-relevance refinement;
> Adam-direction *"if useful use them, no budget"*); D-086
> (deck_close layout); D-087 (substory_design transition_from_prior
> field).

## v3.2 failure modes ADDED on top of v3.1

(v3's and v3.1's failure modes — register leakage, arc-role
drift, figure under-use — all still apply. v3.2 adds three.)

- **Figure-as-bullet-citation.** A substory cites a curated
  figure path inside a `data_source` field or in a
  `claim_evidence` bullet's evidence text, instead of composing
  a `data_figure` slide that displays the figure as principal
  evidence. The audience sees the bullet's claim but never sees
  the figure. → Compose a `data_figure` slide that displays the
  figure as principal evidence; cite the underlying notebook in
  the slide's `data_source`. v0.7
  `tools/check_figure_provenance.py` emits cascade Tier-1 P12
  `relevant_figure_not_used` soft-warnings.
- **Arc-independence drift.** Each substory is composed in
  isolation; the deck reads as N self-contained beats rather than
  a cumulative argument. → Use the `transition_from_prior` field
  (when present) to open non-first substories with a callback to
  the prior arc's conclusion before stating this substory's
  question.
- **Closing-synthesis absence.** A STRONG-mode talk ends with the
  final substory's C-slide and nothing else, leaving the audience
  to assemble the unified takeaway themselves. → Compose a
  `deck_close` slide that pulls unified_point + per-arc
  key_takeaways + a forward_call from the curator's
  `deck_close_signal.json`.

## v3.2 contract specifics — Figure-relevance (D-085, refines D-080)

The composer reads `CURATED_FIGURES_PATH` (the mode-bounded
shortlist at `working/curated_figures.md`) as in v3.1. v3.2
clarifies the *rule* (not the metric):

**Figures are paid for at curator time.** The curator's mode-
bounded shortlist already represents the "right" figures for
this deck — bounded by mode (talk-30 STRONG vs talk-15 BRIEF) +
curated for narrative fit. There is no per-deck figure budget,
no per-arc figure cap, no figure scarcity. The composer's job
is to USE every relevant figure, not to ration them.

**Per-substory rule (the load-bearing constraint, refined from
v3.1):**

For each substory you compose:

1. Look at the substory's **Critical analyses covered** list
   (from `02_substories.md`, the section you author against).
2. For each analysis ID/name in that list, check whether the
   curated-figures shortlist contains a figure that corresponds
   to that analysis (filename starts with `NB##_` matching the
   analysis's source notebook, OR the caption candidate
   explicitly names the analysis).
3. **For EACH curated figure whose NB-id matches the substory's
   analyses, compose a `data_figure` slide that uses that figure
   verbatim.** Not "at least one" — every relevant figure should
   appear as a data_figure somewhere in the substory's R-slide
   sequence.
4. **Multiple relevant figures in one substory is fine.** If S2
   has 3 curated figures matching its analyses, S2 has 3
   `data_figure` slides (or more, if the analysis benefits from
   multi-panel treatment). The other Q/A/R/C slots remain as
   needed for the question + arc role beats.

Concretely: if S2's analyses cite NB13 (phage-cocktail design)
AND NB14 (phageome longitudinal) AND
`figures/NB13_phagefoundry_cocktail.png` +
`figures/NB14_phageome_longitudinal.png` are both on the curated
shortlist, S2 should have a `data_figure` slide for EACH of
those figures. Picking one and putting the other into a bullet
is a v3.2 violation.

**Why no figure budget?** Curated figures are not a scarce
resource. The curator already enforced the relevance filter
(mode-bounded shortlist). Asking the composer to ration them is
asking it to override the curator's judgment. The right
discipline is on the AI-image side (where cost is real per-
slide): D-088 imposes a ≤4-approvals/deck cap on AI image
generation.

**Pre-composition self-check (REFINED IN v3.2).** Before emitting
the fragment JSON, for EACH substory:

- Enumerate the curated figures that correspond to the
  substory's analyses (filenames or caption-matches).
- For EACH such figure, check whether a `data_figure` slide in
  your fragment references it. **If any relevant figure is
  unused, revise to add a data_figure slide for it before
  emitting.** No exceptions for "out of slots" or "ran out of
  space" — figures take slots; that's what the substory's R-slot
  sequence is for.

**Counting rule (unchanged from v3.1/D-081):** A `data_figure`
slide "uses" a curated figure iff the slide's `content.figure`
field exactly matches a path listed in
`working/curated_figures.md` (the post-validator
`tools/check_figure_provenance.py` enforces this with strict
path matching, plus the new v0.7
`relevant_figure_not_used` finding per D-085).

## v3.2 contract specifics — Arc transitions (D-087)

The substory_design v3.2 overlay instructs the substory-design
LLM to emit a `transition_from_prior` field per substory (null
for substory 1; a 1-2 sentence string for substories 2..N).
The field summarizes what claim or finding from the prior
substory this one builds on.

**Composer usage:**

For each substory after the first (substory_number > 1):

1. Read the substory's `transition_from_prior` field (if
   present in the substory_design output).
2. When composing the substory's **first non-Q slot**
   (typically the A-slide answering the substory's question, OR
   the first R-slide if there's no explicit A-slide), open with
   a clause that references the prior arc's conclusion before
   stating this substory's claim.
3. The reference should be brief (one phrase / one sentence at
   the start of the slide's principal text or first bullet);
   it's a *transition*, not a *recap*.

Example (S3 of an ibd deck where S2 concluded "iron-acquisition
and bile-acid 7α-dehydroxylation form two cross-corroborated
6-line narratives"):

- WITHOUT transition: S3's A-slide opens "Phage-feasibility
  stratifies 6 targets into Tier-1/Tier-2 prescribing categories."
- WITH transition: S3's A-slide opens "Building on the
  two-narrative cocktail target list from S2, phage-feasibility
  stratifies the 6 targets into Tier-1/Tier-2 prescribing
  categories."

**Soft preference, not inviolable.** If the
`transition_from_prior` field is absent / null / empty, compose
the substory normally without transition language. If the field
is present but the natural composition doesn't benefit from a
callback (rare), prefer the natural composition; document the
choice in speaker notes. v0.7 measures arc-transition presence
qualitatively at Tier-F, not as a hard validator.

**`transition_from_prior` field shape (from substory_design
v3.2):**

```yaml
substories:
  - substory_number: 1
    # ... existing fields ...
    transition_from_prior: null     # always null for first substory
  - substory_number: 2
    # ... existing fields ...
    transition_from_prior: "S1 established that UC Davis distributes non-randomly across 3 ecotypes with E1 as the highest-burden stratum. S2 asks: which pathobionts drive that E1 burden?"
```

The field is free-text; structured references (e.g.,
`references_claim: <substory-id.claim-id>`) are a v0.8+ design
surface if v0.7 reads show free-text transitions drift.

## v3.2 contract specifics — Closing synthesis (D-086)

For STRONG-mode talks (talk-30; mode budget 18-32 slides), the
deck must end with a `deck_close` slide. The composer does NOT
author this slide ad-hoc; the curator produces a structured
`working/deck_close_signal.json` artifact and the composer reads
its fields verbatim.

**deck_close layout schema:**

```yaml
layout: deck_close
content:
  unified_point: <string>      # the deck's overall takeaway (1-2 sentences)
  key_takeaways: <list[str]>   # 3-5 bullets, each tying to one arc/substory
  forward_call: <string>       # implication / next-step / open question
  data_source: <string>        # cited substories or REPORT sections grounding the synthesis
```

**Composer rule:**

- Read `working/deck_close_signal.json` if it exists.
- Compose ONE `deck_close` slide at the end of the deck (after
  the final substory's C-slot, before references /
  acknowledgments).
- Use the structured fields VERBATIM; do not embellish
  `unified_point` or `key_takeaways` with composer interpretation.
  The curator's structured artifact represents the deck's
  agreed-upon synthesis.
- The `forward_call` should be a forward-looking statement that
  the audience can act on (next experiment, open question,
  pending validation) — not a generic "thank you for your
  attention" or "questions welcome."

**Skip rule:** if mode is not STRONG (lightning-5, talk-15
BRIEF), the deck_close slide is OPTIONAL. The validator gates
presence-required-iff-mode-≥-STRONG (the orchestrator passes the
mode value into the cascade). Below STRONG, the deck's
per-substory C-slots already provide sufficient closure.

**If `deck_close_signal.json` is absent:** emit a warning in
speaker notes of the final substory's C-slot and compose without
a deck_close slide. The curator should always emit this artifact
on STRONG-mode talks; absence is a curator-stage bug to surface
at Tier-F.

## v3.2 anti-patterns (additive to v3 + v3.1 failure-mode catalog)

(v3 + v3.1 failure modes above all apply; v3.2 adds:)

- **Figure-as-bullet-citation.** Cited above as a v3.2 failure
  mode. The composer cites `figures/NB##_*.png` inside a
  `claim_evidence` bullet's text or in a `data_source` field
  instead of composing a `data_figure` slide. → Compose a
  `data_figure` slide; the bullet becomes the slide's
  caption/punchline.
- **Transition-as-recap.** The substory's first non-Q slot
  spends 2+ bullets reviewing the prior substory before stating
  the current substory's claim. → Transitions are one phrase / one
  sentence at the start; the slide's body is the current
  substory's content.
- **deck_close-as-generic-thanks.** The `forward_call` field
  contains audience-management language ("thank you for your
  attention," "I'm happy to take questions") instead of a
  forward-looking actionable statement. → forward_call must
  carry substantive content (next experiment / open question /
  validation gap / cohort expansion).
- **deck_close-skip-on-STRONG.** A talk-30 STRONG deck without a
  `deck_close` slide. → Always compose deck_close for talk-30+
  STRONG; the cascade validator P-check enforces presence per
  D-086.

## v3.2 inviolable rules (additive to v3 + v3.1 inviolable-rules list)

(v3 rules 1–7 and v3.1 rules 8–9 above all apply; v3.2 adds:)

10. **v3.2 (refines v3.1 rule 8):** For each substory, EVERY
    curated figure in `CURATED_FIGURES_PATH` whose NB-id
    corresponds to one of the substory's critical analyses MUST
    appear as a `data_figure` slide somewhere in that substory's
    R-slide sequence. Not "at least one" — every relevant
    figure. There is no figure budget; figures are pre-paid at
    curator time per D-085.

11. **v3.2:** A figure listed in `working/curated_figures.md`
    must NEVER appear in any other field
    (`claim_evidence.bullets`, `data_source` text,
    `speaker_notes` body) UNLESS it is also composed as a
    `data_figure` slide somewhere in the deck. Referencing a
    curated figure without displaying it as principal evidence is
    figure-as-bullet-citation (the v3.2 failure mode).

12. **v3.2:** For non-first substories whose substory_design
    output emits a non-null `transition_from_prior` field, the
    substory's first non-Q slot SHOULD open with a brief
    transition phrase referencing the prior arc's conclusion.
    Soft preference (no hard validator); used by Tier-F
    qualitative read. Skip when the natural composition is
    clearly better without it; document the choice in speaker
    notes when skipped.

13. **v3.2:** A STRONG-mode talk (talk-30; mode budget 18-32)
    MUST end with a `deck_close` slide whose `unified_point`,
    `key_takeaways`, `forward_call`, and `data_source` fields
    are read verbatim from `working/deck_close_signal.json` when
    that artifact exists. Below STRONG mode, deck_close is
    optional. The orchestrator's validator
    (`check_figure_provenance.py` + the cascade Tier-1 layer)
    fires a P1 finding if a STRONG talk lacks deck_close.
