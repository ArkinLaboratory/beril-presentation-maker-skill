# beril-presentation-maker-skill v0.3.1 — punch list

**Date:** 2026-04-30
**Goal:** Close the residue from v0.3.0 (Stream A wrinkles surfaced
during draft_10 live test + image-gen orchestrator stage wiring) and
add the missing `data_table` layout. None of these are ship-blockers
for v0.3.0; collected here as a focused next-cycle plan.

## Tier A — Stream A wrinkles (small, do first)

These were flagged during the draft_10 live test that landed F001 +
F003 cleanly. The fixes are localized and well-scoped.

### A1. `_insert_slide_into_spec` position fallback

**Problem.** `add_slide.v1` produced F003 with `position=9` and
substory_id from the finding's `fix_hint`. The new slide landed at
end-of-deck instead of after slide 9 because existing slides in the
spec lack `position` fields, so the insert function fell through to
"append at end".

**Fix.** In `tools/revise_loop.py::_insert_slide_into_spec` (or wherever
the insert logic lives — verify), when sibling slides lack `position`:

1. First fallback: use `substory_id` to identify the substory's last
   slide and insert immediately after it.
2. Second fallback: index by slide-array order matching the
   finding's `fix_hint` text ("between current slides 8 and 9").
3. Third fallback: append-at-end (current behavior) **with a
   warning** in the loop's stderr surfacing the position drift.

**Acceptance.** Synthetic test: spec with no position fields + new
slide with `position=9` lands at array-index 9, not end-of-deck.
Existing F003-style live retest passes.

**Owner.** TBD. ~1-day work + tests.

### A2. Register discipline propagation in `add_slide.v1.md`

**Problem.** F003's new slide title contained "high-confidence" — the
exact overclaim F001 fixed elsewhere. `add_slide.v1.md` doesn't read
the deck-level tier register, so it can introduce drift even when
adjacent slides have been corrected.

**Fix.** Add an explicit anti-pattern section to `add_slide.v1.md`:

> **PA-N: Tier-violating language on new slides.** EXPLORATORY-tier
> decks must not get new slides with "high-confidence", "robust",
> "definitive", or similar overclaim verbs. THIN-tier decks must
> hedge with "preliminary", "candidate", "early-stage". Read the
> `TIER` input verbatim; check the slide's title + bullets against
> the per-tier register cheat-sheet (mirror the cheat-sheet from
> `revise_slide.v1.md`).

Plus: add a self-review checklist item ("Does any title or bullet
contain a tier-forbidden verb? See TIER cheat-sheet.").

**Acceptance.** Re-run F003 against the updated prompt; new slide
title no longer contains "high-confidence". Add a unit test that
mocks the prompt against an EXPLORATORY-tier finding with a
high-confidence-leaning data shape; assert the LLM's output does not
contain forbidden verbs.

**Owner.** TBD. ~0.5-day prompt edit + 1 test.

## Tier B — Image-gen orchestrator stage (BLOCKED-BY: nothing)

### B1. Three-layer image-gen architecture

**Problem.** v0.3.0 ships the calibrated client + the calibrated
prompt template, but the orchestrator does not automatically flag
`concept_illustration` slides for image generation. Channel A (LLM-
initiated) is wired from a prompt-spec standpoint but no production
stage actually invokes it.

**Design.** Three-layer pipeline, inserted into the orchestrator
between `slide_compose` and `merge_compose_fragments`:

1. **Decision layer.** Per-slide gate: does this slide actually
   benefit from an image? Inputs: slide layout, substory shape,
   tier register, deck mode. Outputs: `image_helps: {true | false}`
   plus rationale. Implemented as a small subagent prompt
   (`ai_image_decision.v1.md`) with hard rules: never on
   `data_figure` (already has a figure), never on `data_table`
   (table IS the content), never on `acknowledgments`, etc.
2. **Spec layer.** When decision=true, generate an `image_brief`:
   what concept to depict, what aspect ratio, what region of the
   slide, what to AVOID. Same calibrated style/palette defaults as
   `ai_image_prompt.v1`. Implemented as `ai_image_brief.v1.md`.
3. **Prompt layer.** `ai_image_prompt.v1.md` (already in v0.3.0)
   takes the brief + composes the model-ready prompt + stages the
   request JSON. Already calibrated.

The orchestrator then gates user approval per existing D-029
contract (`approval_required: true`) before invoking
`tools/image_client.py`.

**Acceptance.** Live retest on draft_10 (or new project) where
~5–10 slides flagged for images, all gated through user approval,
~$0.15 budget for the run, generated images land in
`figures/<slide_id>.png` and integrate into `curated_figures.md` as
candidates. No regression on existing pipeline.

**Owner.** TBD. ~3-day work: 2 new prompts + orchestrator stage +
tests + smoke.

## Tier C — `data_table` layout (BLOCKED-BY: nothing)

### C1. Add `data_table` layout

**Problem.** `add_slide.v1.md` already references `data_table` as a
target for "Top-N ranking with multiple columns" but the layout
doesn't exist in `slide_spec.py` or `assemble_pptx.py`. The current
fallback is `claim_evidence` with bullets-as-rows, capped at 3.

**Reference.** `beril-paper-writer` ships table rendering via
python-docx; adapt the table structure for python-pptx (different
API: `slide.shapes.add_table(rows, cols, left, top, width, height)`).

**Design.**

- Spec schema: `{layout: "data_table", content: {title, columns:
  [str], rows: [[str, ...]], caption?, footnote?}}`. Cap rows at 12
  (validator-blocking); cap columns at 6.
- Master template: add a `data_table` layout with title placeholder
  + body region for the table. Layout fix in `build_master.py`.
- Assembler: `_fill_data_table` handler in `assemble_pptx.py`. Table
  styling per KBase brand (header row in `#007DC3` blue, alternating
  row bands, `#F78E1E` highlight if a row is flagged
  `highlight: true`).
- Validator: enforce row/column caps; verify all cells are strings
  (not numbers — let the caller stringify with the right precision).

**Acceptance.** `add_slide.v1.md`'s fallback note updated to
reference v0.3.1's data_table; live test where a missing_slide
finding requests "top-10 candidates" produces a clean table. Master
re-render passes the layout walker.

**Owner.** TBD. ~2-day work: schema + master fix + assembler handler
+ tests.

## Sequencing

```
A1 (position fallback)  ─┐
A2 (register propagation) │
                          ├─ ship v0.3.1
C1 (data_table)          ─┤
                          │
B1 (orchestrator stage)  ─┘
```

A1 + A2 are independent, fast. C1 is independent, ~2 days. B1 is
the biggest single item but doesn't block anything else. Ship in one
patch release once A1 + A2 + C1 land; B1 can be its own v0.3.2 if
the calendar pulls.

## Out of scope for v0.3.x

- Multi-project testing on 3 BERDL projects (gate before v1.0).
- v1.0 release (after multi-project testing).
- KBase Co-Scientist orchestrator integration (separate stream).
