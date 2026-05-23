# M4a Punch List — Visual-QA + content discipline

**Filed:** 2026-05-23. **Status: PROPOSED — handoff artifact; awaiting Adam's sign-off on
the open design questions (DQ1–DQ4) at the start of the M4a build session.**
**Milestone:** M4a of the v0.4 pivot. M4 was split (Adam, 2026-05-23) into **M4a** —
this — and **M4b** the LLM review cascade; M4a ships before M4b.
**Predecessor:** M3 — per-substory parallel composition (complete, committed `01099d8`).
**Successor:** M4b — tiered review cascade (`V0_4_ARCHITECTURE.md` §16 M4b).
**Design source:** the M3 Tier-E render examination (`M3_PUNCH_LIST.md` E-phase patch log,
E-4 through E-7) + `V0_4_ARCHITECTURE.md` §16 M4a. Test vehicle:
`spike/beril-extended/projects/ibd_phage_targeting/talks/draft_1` (the deck rendered four
times during M3 Tier E — `deliverable/pngs{,2,3}/`, `pngs4/draft.pdf`).

## Status

| Tier | Scope | Status |
|---|---|---|
| A — explicit shrink-to-fit renderer + diagram connector labels | `assemble_pptx.py`, `diagram_render.py` | ✅ committed 2026-05-23 (suite 1058 passed; visual round pending in Tier E) |
| B — content-length caps (prompts + validator backstops) | prompts, `slide_spec.py` | ⬜ not started |
| C — the visual-QA pass | new `tools/visual_qa.py` + `visual_qa.v1.md` | ⬜ not started |
| D — test-hygiene tidy + Slide-13 verification | `test_adversarial_interop.py` | ⬜ not started |
| E — end-to-end render smoke on `ibd_phage_targeting` | live | ⬜ not started |
| F — closeout | paperwork | ⬜ not started |

## Why M4a exists — the defect taxonomy and the root cause

M3's Tier-E live smoke produced a structurally-valid 27-slide deck that *renders* badly.
Across four render rounds, the remaining problems resolved to **one root cause**:

> **Fixed-size assembler text boxes vs variable-length composer content.** The v0.3.x
> assembler's text slots — diagram node labels, workflow step-captions, `big_number`
> subtitle/sub_pointer, `data_table` caption — are fixed height and fixed font,
> calibrated for *short* content. The v2 composer (and the existing prompts) produce
> *longer* content. `word_wrap` wraps it; the box doesn't grow; the text spills past the
> box edge and collides with neighbouring elements or the footer logo strip.

Box-coordinate repositioning (M3 E-6) does not fix this — the next longer string
overflows again. The fix is two-pronged and neither half is an assembler coordinate
patch: **(1) real shrink-to-fit** (explicit `fontScale` — the only mechanism LibreOffice
honours at render; a bare `<a:normAutofit>` is not computed), and **(2) content-length
caps in the prompts**, because a node label is a phrase, not a sentence — ~90 chars
cannot be legible in a 1.75-in box at any font.

**The concrete defect inventory (from the M3 Tier-E examination):**

| Defect | Where | Slides (ibd draft_1) |
|---|---|---|
| Node label overruns the box | `diagram_render._render_node` | 6, 10, 19 |
| Workflow step-captions overflow + collide with the tool-version footer | `assemble_pptx._fill_workflow_diagram` | 6, 10, 15, 19 |
| `big_number` long subtitle overflows into sub_pointer/source_footer | `_fill_big_number` | 17 (7/11 OK — short content) |
| `data_table` caption overflows its fixed box | `_fill_data_table` | 21 |
| Workflow inter-box connector label sits behind boxes | `diagram_render._render_edge` | 10, 19 |
| Compound section-synthesis headline on a `data_figure` (headline↔body mismatch) | composer discipline | 13 |

(M3's E-4…E-7 fixed the *footer-collision* and *zero-width-placeholder* classes; what
remains is the *overflow* class above — the boxes are now in the right place but still
too small for long content.)

## Scope

M4a makes the v0.4 deck **render cleanly**: explicit shrink-to-fit so text stays inside
its box; content-length caps so the composer stops producing slot-busting strings; and a
**visual-QA pass** — render → PNG → vision review — so render defects are *caught*
mechanically instead of by a human reading 27 slides.

**What M4a is NOT:** the LLM review cascade (`review_cascade.py`, Tier 1/2/3 — that is
M4b); image-gen multi-provider (M5); the A/B cut-over (M6).

**Cost discipline:** the visual-QA pass costs a vision LLM call + a LibreOffice render per
invocation — DQ1 settles whether it auto-runs or is opt-in. No `--max-cost-usd` caps in
runbooks (`feedback_cost_record_dont_gate`).

## Open design questions — need Adam's sign-off before the affected tier

> **RESOLVED 2026-05-23 (build session open).** All four signed off by Adam.
> DQ1 → **opt-in** (verb + flag, advisory). DQ2 → **`soffice --headless --convert-to pdf` then `pdftoppm`** (Poppler) — `pdftoppm` confirmed present. DQ3 → **60% `fontScale` floor**; below-floor clamps at the floor + appends to `warnings`. DQ4 → **advisory soft-warning** (no hard reject; renderer is the safety net). Land as D-050..D-053 in Tier F.

**DQ1 (gates Tier C) — does the visual-QA pass auto-run in the pipeline, or is it opt-in?**
It costs a LibreOffice render + a ~27-slide vision LLM call. **Recommendation: opt-in** —
a `beril-presentation-maker visual-qa <draft>` verb (and an orchestrator flag
`--visual-qa`), advisory output like `reconcile_deck.py`. Auto-running it on every draft
adds vision-LLM cost to every run before we have spend data; opt-in first, revisit
auto-running once M4b's cascade exists (it may belong as an M4b Tier-1 check).

**DQ2 (gates Tier C) — the render toolchain.** `visual_qa.py` must render `slide_spec` /
`draft.pptx` → per-slide PNG. M3 Tier E rendered manually (the `pngs*/` dirs + a
`draft.pdf`). **What did those renders use** — `soffice --headless --convert-to`, a
script, something else? `visual_qa.py` should shell to whatever is already on the deck
deployment host. Recommendation: `soffice --headless --convert-to pdf` then a PDF→PNG
step, or `--convert-to png`; document LibreOffice as the render dependency. Adam confirms
the available toolchain.

**DQ3 (gates Tier A) — the shrink-to-fit floor + flag-when-below.** A font has a minimum
readable projection size (~9–10 pt). If a slot's content is so long that even
maximum shrink would render below the floor, the renderer cannot save it.
**Recommendation:** the explicit-`fontScale` helper shrinks toward a documented floor and,
if the content would require going *below* it, clamps at the floor AND emits an assembler
warning (which the visual-QA pass also catches) — never silently renders sub-legible.
Decide the floor value.

**DQ4 (gates Tier B) — content caps: hard validator reject vs advisory warning.** A
backstop for the prompt-side length caps belongs in `slide_spec.py` (per
`feedback_prompt_discipline_needs_post_check`). **Recommendation: advisory soft-warning**,
not hard-reject — a slightly-long label should not fail the pipeline after LLM spend; the
renderer's shrink-to-fit (Tier A) is the safety net and the warning routes to the
hand-edit / revise pass. The existing `DATA_FIGURE_CAPTION_MAX_CHARS` is a hard cap —
M4a's new caps follow the softer model unless Adam wants parity.

---

## Tier A — explicit shrink-to-fit renderer + diagram connector labels

Renderer-only (`assemble_pptx.py`, `diagram_render.py`). The core fix. Needs a
render-validate loop with Adam.

**A1. Reusable explicit-fontScale helper.** Generalise the M3 E-5 `_fill_qa_anticipated`
adaptive ladder into a shared helper — `_fit_textbox(shape, *, max_pt, min_pt, chars)` or
an adaptive `fontScale` computed from content length — that writes an explicit
`<a:normAutofit fontScale=…>` (the LibreOffice-honoured form). One mechanism, applied
everywhere a fixed box holds variable text.

**A2. Apply to the overflow-prone slots.** `big_number` subtitle/sub_pointer;
`workflow_diagram` step-captions; `data_table` caption; `methods_summary` footer;
`diagram_render` node labels (replace the M3 E-6 `auto_size=TEXT_TO_FIT_SHAPE` — a bare
`normAutofit` LibreOffice ignores — with the A1 explicit-scale helper).

**A3. Diagram connector-label placement (M3-deferred).** `diagram_render._render_edge` —
the gray inter-box transition labels render behind / overlapped by node boxes (slides 10,
19). Position them clear of the boxes (in the inter-node gap, above the connector) and
confirm z-order (labels added after nodes → on top).

**AC for A:** a synthetic deck with deliberately slot-busting content assembles; the
geometry scan (width + footer-bottom, per M3 E-7's check, extended to assert explicit
`fontScale` present on the slots) passes; node labels contained. Full suite green.
**Visual confirmation needs a render round with Adam.**

## Tier B — content-length caps (prompts + validator backstops)

Prompt edits deferred to here per `feedback_punch_list_release_pattern` (prompt smokes are
expensive). Takes effect on the next `slide_compose` / `diagram_design` / `qa_prep` run.

**B1. Prompt caps.** `diagram_design.v1.md` — node `label` is a short phrase (~40 chars),
not a sentence. `slide_compose.v2.md` — `big_number` subtitle ≤ ~80 chars; workflow
`step_caption` ≤ ~70 chars/step. `qa_prep.v1.md` — `answer_summary` ≤ ~400 chars (the
residual flagged at M3 E-5: the slide answer is glanceable; depth lives in
`answer_detail`, which v0.4 routes to the notes pane).

**B2. Validator backstops** in `slide_spec.py` — per DQ4, advisory soft-warnings on the
new length caps (node label, big_number subtitle, step_caption) so prompt drift is caught
programmatically, not only by the prompt. + tests.

**AC for B:** prompt diffs reviewed by Adam before any live spend (mirrors M3 Tier D);
validator backstops + tests green; suite green.

## Tier C — the visual-QA pass

The durable detector — render → see → flag. New `tools/visual_qa.py` + `visual_qa.v1.md`.

**C1. `tools/visual_qa.py`.** Renders a draft's `slide_spec.json` / `draft.pptx` → per-slide
PNG (via the DQ2 toolchain), invokes a `claude -p` vision pass over the PNGs, writes
advisory `audit/visual_qa.{md,json}`. Findings taxonomy: text overflow / container
breach, element overlap, footer-strip & title-band collision, illegible-scale, and
headline↔body coherence (the Slide-13 class — a text-level check that does not strictly
need the render but belongs in the same pass).

**C2. `prompts/visual_qa.v1.md`** — the vision-reviewer system prompt: per-slide, flag the
taxonomy above; advisory, structured JSON output.

**C3. Wiring** — per DQ1, an opt-in `visual-qa` CLI verb + an orchestrator `--visual-qa`
flag. Advisory (rc=0), never blocks assembly.

**AC for C:** `visual_qa.py` on the `ibd_phage_targeting` draft_1 deck flags the known
defects (the Tier-A targets pre-fix; ideally clean post-fix); rc=0 always; cost recorded.

## Tier D — test-hygiene tidy + Slide-13 verification

**D1.** `tests/integration/test_adversarial_interop.py::test_live_adversarial_review_emits_v3_schema`
makes a live, paid, multi-minute `claude -p` call and auto-fires on `pytest tests/`
whenever a draft happens to exist on disk (it stalled Adam's M3 commit-gate run for 3.5
min). Gate it behind an explicit opt-in — require `$TEST_DRAFT_DIR` to be *set by the
operator* (not auto-discovered) or a `--run-live` marker — so the routine unit/integration
run never invokes a live LLM.

**D2.** Verify M3's E-3 fix (the `data_figure` compound-headline discipline in
`slide_compose.v2.md`) on a fresh compose — covered by Tier E's recompose; confirm Slide
13's headline now describes its figure.

## Tier E — end-to-end render smoke on `ibd_phage_targeting`

Recompose the v0_4 deck fresh (so Tier B's content caps and E-3 take effect — a
`--resume-from` re-assemble is not enough; the composer must re-run), render, run the
Tier C `visual-qa` pass, and eyeball. This is the convergence gate — the render-validate
loop that M3's per-slide cycle should have been.

**AC for E:** the deck renders with no container breaches, no overlaps, no footer/title
collisions; the `visual-qa` pass reports clean (or only accepted residuals); the diagram
node labels and connector labels are legible and contained. Expect 1–2 render rounds.

## Tier F — closeout

`V0_4_ARCHITECTURE.md` §16 M4a → SHIPPED; `LAYOUT.md` (`visual_qa.py`, `visual_qa.v1.md`);
this punch list's status table; `DECISIONS.md` (DQ1–DQ4 → D-050+); auto-memory
`project_presentation_maker_v0_4_m4a.md` + `MEMORY.md`.

## Dep edges

```
A ──┬────────────────► E ──► F
B ──┤  (B needs a recompose to take effect; A is render-only)
C ──┘  (C is the detector; usable against the deck once A+B land)
D ───────────────────► (independent; land any time)
```

A (renderer) and B (content caps) are independent builds; both must land before Tier E's
recompose+render shows a clean deck. C (the visual-QA tool) is independent to *build* but
most useful run against the post-A+B deck. D is independent.

## Smoke gates

- **A gate:** synthetic slot-busting deck assembles; geometry scan clean; suite green. Then a render round with Adam.
- **B gate:** prompt diffs signed off by Adam; validator backstop tests green.
- **C gate:** `visual_qa.py` flags the known M3 defects on draft_1 pre-fix.
- **E gate:** the recomposed + rendered deck is clean per the visual-QA pass + Adam's eye.

## What M4a does NOT do (→ M4b / M5 / M6)

- The LLM review cascade — `review_cascade.py`, Tier 1/2/3, detection-class calibration (M4b).
- Image-gen multi-provider + revise-invariance (M5).
- State-schema v0.3→v0.4 migration + the A/B cut-over (M6).

## Estimated effort

| Tier | Estimate |
|---|---|
| A — shrink-to-fit + connector labels | 4–6 h + 1–2 render rounds |
| B — content caps + validator backstops | 3–4 h |
| C — visual-QA pass (new tool + vision prompt) | 6–10 h (the largest tier) |
| D — test-hygiene tidy | 1–2 h |
| E — render smoke | 3–5 h (recompose cost + 1–2 rounds) |
| F — closeout | 1–2 h |

Total ~20–30 h over 4–6 working days, render rounds permitting.

## First action (M4a build session)

Read `CLAUDE.md` → `augmentation-stream-plan.md` → this file → auto-memory
`project_presentation_maker_v0_4_m3.md` (the M3 retrospective + the render-debt
characterisation). Then Adam resolves DQ1–DQ4. Then Tier A — the explicit-fontScale
helper is the keystone; everything else hangs off it.
