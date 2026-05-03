# beril-presentation-maker v0.3.3 — image-gen orchestrator architecture

**Status:** DRAFT 2026-05-03 — for review.
**Scope:** concrete design for the image-generation pipeline stage.
Extends `V0_3_1_PUNCH_LIST.md §v0.3.3`. The punch list keeps the
release-tracking bullet form; this doc holds the real design.

**Sanity-checked against existing code on 2026-05-03:**
`slide_compose.v1.md` L756-760 (placeholder convention),
`slide_spec.py::_check_concept_illustration` L561-598 (validator
required fields), `assemble_pptx.py::_fill_concept_illustration`
L1155 (assembler binds `image_path` to figure), `image_client.py`
(generate + provenance API),
`presentation_maker.sh::should_run` L1326-1340 (stage-ordering
table). No grep hits for `concept_illustration` in any live draft
under `spike/beril-extended/projects/*/talks/` — confirms the
layout has been blocked end-to-end by the missing image-gen stage.

---

## 1. Goal & non-goals

**Goal.** Slides flagged for AI image generation actually get an image,
end-to-end, gated by per-slide user approval, with cost capped, with
provenance. Channel A (LLM-initiated via `slide_compose` flagging
`concept_illustration`) ships in v0.3.3. Channel B (user-initiated,
post-hoc) is deferred to v0.4.x.

**Non-goals (v0.3.3).**
- Channel B (user-initiated images via revise loop or interactive
  command). Designed for, not shipped in v0.3.3.
- LLM-judgment "supplemental image needed?" decision on
  `claim_evidence` slides. Deferred to v0.3.4.
- Quant-content judge integration (vision-LLM scoring of generated
  images). The `score_quantitative_content` stub in `image_client.py`
  remains stub; user-approval gate is the load-bearing safety.
- Multi-provider routing (direct Google AI Studio / OpenAI). CBORG
  only, per `image_client.py` v0.1.

---

## 2. Architectural decision: collapse 3 layers → 2

The punch list calls for three LLM-driven layers (decision → brief →
prompt). On reading the existing `ai_image_prompt.v1.md`, the brief
and prompt are **the same artifact** — `ai_image_prompt.v1` already
reads slide stub + substory + throughline + tier and emits a complete
`image-request.v1` JSON that bundles subject, style, palette, negative
prompt, placement, cost, and approval flag. There is no missing
"brief" between stub and prompt; one is the input, the other is the
output, and the prompt template authors them in one pass.

**Collapse to two layers:**

1. **Decision layer (Python, deterministic).** Hard rules over slide
   layout + tier + flags. No LLM call. Cheap, auditable, testable.
2. **Prompt+request layer (LLM, existing `ai_image_prompt.v1.md`).**
   One Claude call per approved slide; emits `<slide_id>_request.json`.

This is cheaper (no per-slide decision LLM call), simpler (no separate
brief stage), and avoids inventing a contract for which the existing
prompt template is already sufficient. The aspirational three-layer
architecture is preserved as a v0.4.x option once we have evidence the
deterministic gate misses cases.

**Implication for the punch list.** Strike the
`ai_image_decision.v1.md` and `ai_image_brief.v1.md` items from the
v0.3.3 scope. Keep them as v0.3.4+ candidates IF the deterministic
gate proves too narrow.

---

## 3. Pipeline placement

Insert a single new stage `image_gen` between `speaker_notes` and
`merge`:

```
plan → throughline → (gate) → substory_design → (gate)
   → curate_figures → citation_pool → cross_tenant
   → intro → slide_compose → qa_prep → speaker_notes
   → image_gen   ←────── NEW (Stage 11/13, was stage 11)
   → merge → assemble → adversarial_review → revise_slides
```

**Why between speaker_notes and merge.** All slide content is settled
by speaker_notes; image-gen reads finished stubs. Merge then assembles
the final spec consuming both per-slide fragments and the image
manifest as a single read-only step. If the user rejects every image
request, the stage exits cleanly and merge proceeds with no images —
no rework anywhere upstream.

**`should_run` ordering update.** Map after speaker_notes (10),
before merge (11):

```
plan:1 throughline:2 substory_design:3 curate_figures:4
citation_pool:5 cross_tenant:6 intro:7 slide_compose:8 qa_prep:9
speaker_notes:10 image_gen:11 merge:12 adversarial_review:13
revise_slides:14
```

This shifts merge / adversarial_review / revise_slides ordinals by 1.
The case statement for `--resume-from` extends correspondingly.

---

## 4. Per-slide artifact flow

For each slide produced by `slide_compose`, the image-gen stage walks:

```
working/03_slides/<sid>_slides.json    (input — slide stub)
        │
        ▼
[decision: pure Python rule eval]
        │
        ├── NO  → skip slide; no further work
        │
        └── YES → ai_image_prompt.v1 LLM call (one Claude call)
                  │
                  ▼
                  working/05_image_requests/<slide_id>_request.json
                  │
                  ▼
                  [user approval gate]
                  │
                  ├── reject → DROP slide from fragment (R6 Option A);
                  │             record rejection in manifest
                  │
                  ├── edit   → user-supplied override; re-stage request
                  │
                  └── approve
                              │
                              ▼
                              image_client.py generate
                              │
                              ▼
                              working/05_images/<slide_id>.png
                              │
                              ▼
                              update working/05_images/manifest.json
                              update audit/image_provenance.json
                              update working/03_slides/<sid>_slides.json
                                  to bind image_path → slide.figure
```

The slide-fragment update is in-place: `_slides.json` is an emitted
artifact of slide_compose, mutating it is acceptable. Snapshot the
pre-image-gen fragment to `audit/snapshots/03_slides_pre_image_gen/`
before mutation so revise_loop has a baseline to roll back to.

---

## 5. File-system zones (extends draft_paths.py)

New paths under `working/` and `audit/`:

| Path | Owner | Purpose |
|---|---|---|
| `working/05_image_requests/<slide_id>_request.json` | LLM (ai_image_prompt.v1) | Per-slide image request; gates user approval |
| `working/05_image_decisions.json` | Python decision layer | Audit trail: per-slide decision + reason |
| `working/05_images/<slide_id>.png` | image_client.py | Generated PNG |
| `working/05_images/manifest.json` | image-gen orchestrator | slide_id → image_path index; consumed by merge |
| `audit/image_provenance.json` | image_client.append_provenance | Append-only provenance log (existing schema) |
| `audit/snapshots/03_slides_pre_image_gen/<sid>_slides.json` | image-gen orchestrator | Pre-mutation snapshot for rollback |
| `audit/stage-logs/image_gen.{stdout,stderr}` | orchestrator wrapper | Stage stderr, like other stages |

`working/05_image_requests/` and `working/05_images/` are already
created by `init_draft_layout()` in v0.3.1. Add the two new files
(`05_image_decisions.json`, `05_images/manifest.json`) and the
snapshot subdir.

`draft_paths.py::DraftPaths` extended with three new fields:

```python
@property
def image_decisions_json(self) -> Path:
    return self.working / "05_image_decisions.json"

@property
def image_manifest_json(self) -> Path:
    return self.images_dir / "manifest.json"

@property
def image_provenance_json(self) -> Path:
    return self.audit / "image_provenance.json"
```

Plus a snapshot subdir helper. Test
`tests/unit/test_draft_paths.py` extended to assert the new paths
exist after `init()`.

---

## 6. Decision layer (Python)

**File:** `tools/image_gen_decision.py` (~120 LOC).

**Public API:**

```python
def decide(
    slide_stub: dict,             # parsed slide dict from _slides.json
    *,
    tier: str,                    # STRONG | THIN | EXPLORATORY
    mode: str,                    # talk-30 | talk-15 | etc.
    user_opt_in_exploratory: bool = False,
) -> Decision:
    """Return Decision(emit: bool, reason: str)."""
```

**Hard rules (in order):**

| Rule | Layout(s) | Verdict | Reason string |
|---|---|---|---|
| 1 | `data_figure` | NO | "data_figure has its own figure" |
| 2 | `data_table` | NO | "data_table is the content" |
| 3 | `acknowledgments`, `references`, `qa_anticipated`, `methods_summary`, `section_divider`, `title` | NO | "structural slide; no image needed" |
| 4 | `concept_illustration` | YES | "concept_illustration layout is the AI-image vehicle" |
| 5 | `claim_evidence`, `workflow_diagram`, `two_column_compare`, `big_idea`, `big_number` | NO (v0.3.3) | "supplemental image deferred to v0.3.4 LLM-decision layer" |
| 6 | tier == EXPLORATORY AND not user_opt_in_exploratory | NO (overrides rule 4) | "EXPLORATORY tier requires --image-allow-exploratory" |
| 7 | unknown layout | NO | "unrecognized layout; default no" |

The list is closed-set: the 16-layout vocabulary as of v0.3.2 is
known. Adding a new layout in v0.4 requires a corresponding decision
rule (raise `UnknownLayoutError` if not catalogued — fail loud).

**Output artifact:** `working/05_image_decisions.json`.

```json
{
  "schema_version": "image-decisions.v1",
  "decisions": [
    {"slide_id": "S2-pos4", "layout": "concept_illustration",
     "emit": true, "reason": "concept_illustration layout is the AI-image vehicle"},
    {"slide_id": "S2-pos5", "layout": "claim_evidence",
     "emit": false, "reason": "supplemental image deferred to v0.3.4 LLM-decision layer"},
    ...
  ]
}
```

**Tests** (`tests/unit/test_image_gen_decision.py`):
- One test per rule (7 tests).
- "EXPLORATORY-with-opt-in lets concept_illustration through" (rule 6 inversion).
- "All 16 layouts have a verdict" (closed-set guarantee).
- "Unknown layout fails loud" (raises UnknownLayoutError).

---

## 7. Prompt+request layer (LLM, existing prompt)

`ai_image_prompt.v1.md` already produces the full request JSON;
v0.3.3 wires it into the orchestrator. No prompt changes required for
v0.3.3 ship (calibration verdicts are encoded; field rules are
sufficient).

**Invocation pattern** (mirrors `slide_compose` per-substory loop):

```bash
stage_image_gen() {
  # 1. Run decision layer (pure Python)
  "$PYTHON_BIN" "$TOOLS_DIR/image_gen_decision.py" emit-decisions \
    --slides-dir "$SLIDES_DIR" \
    --tier "$TIER" --mode "$MODE" \
    $([[ $IMAGE_ALLOW_EXPLORATORY -eq 1 ]] && echo "--allow-exploratory") \
    --out "$IMAGE_DECISIONS_JSON"

  # 2. For each slide with emit=true, invoke ai_image_prompt.v1
  local approved_slides=()
  for slide_id in $(parse_decisions_yes "$IMAGE_DECISIONS_JSON"); do
    local stub_path="$SLIDES_DIR/$(stub_path_for_slide_id "$slide_id")"
    local req_path="$IMAGE_REQUESTS_DIR/${slide_id}_request.json"
    invoke_claude_with_retry \
      "$PROMPTS_DIR/ai_image_prompt.v1.md" \
      "$(build_user_prompt_for_slide "$slide_id" "$stub_path")" \
      "$req_path" "image_prompt-$slide_id"
    approved_slides+=("$slide_id")
  done

  # 3. Per-slide approval gate
  for slide_id in "${approved_slides[@]}"; do
    local req_path="$IMAGE_REQUESTS_DIR/${slide_id}_request.json"
    if approve_request "$req_path"; then
      generate_image "$slide_id" "$req_path"
      bind_image_to_slide "$slide_id"
      record_in_manifest "$slide_id"
    fi
  done
}
```

The user-prompt builder for `ai_image_prompt.v1` populates the
inputs the prompt expects (`OUT_PATH`, `CHANNEL=A`, `SLIDE_ID_TARGET`,
`STUB_PATH`, `THROUGHLINE_PATH`, `SUBSTORY_PATH`, `MODE`, `TIER`,
`BUDGET_USD_REMAINING`).

---

## 8. Approval gate

Per-slide interactive gate, modeled on `gate_throughline_pick`:

```
========================================================
Image request: S2-pos4 (concept_illustration)
   Slide title: "Inner-loop iteration of dark-matter annotation"
   Style:       scientific_illustration
   Worst-case:  $0.04 (budget remaining: $0.46)
   Prompt (preview, 280/350 chars):
     "A scientific illustration of the inner-loop annotation
      refinement workflow as a 3-step cyclic process: (1)
      initial RAST pass, (2) biosynthesis-prior refinement,
      (3) gold-standard verification, with a feedback arrow
      returning from step 3 to step 2. Style: clean
      scientific illustration..."

[a]pprove / [r]eject / [v]iew full prompt / [e]dit prompt /
[A]pprove all remaining / [R]eject all remaining / [q]uit:
========================================================
```

**Choices:**
- `a` — approve this slide; proceed to image_client.py.
- `r` — reject; record in manifest with `approved: false` AND
  drop the slide from its fragment (Option A in R6 — keeps the
  validator clean, since placeholder provenance with `approved_at:
  "TBD"` would otherwise fail downstream ISO-8601 check). The
  pre-rejection fragment is preserved at
  `audit/snapshots/03_slides_pre_image_gen/`.
- `v` — print full prompt to stderr; re-show menu.
- `e` — open `$EDITOR` on the request.json for user to tweak
  `image_prompt` / `style` / `negative_prompt`. Re-validate
  `schema_version="image-request.v1"`. Re-show menu.
- `A` — approve this AND every remaining; bypass per-slide gate
  for the rest of the run. Used by power users.
- `R` — reject this AND every remaining; same bypass.
- `q` — abort the stage entirely; pipeline continues from merge
  with no images. Decisions recorded in manifest.

**Bulk-approve flag:** `--auto-approve-images` short-circuits the
gate (treats every emit=true as auto-approved). Used in CI / smoke
tests against known projects. Cost cap still applies.

**Accessibility note.** The gate writes to stderr and reads from
`/dev/tty` (per `gate_throughline_pick` precedent). Smoke runs with
`--auto-advance` SHOULD ALSO automatically pass `--auto-approve-images`
unless the user explicitly opts out. Document this in SKILL.md.

---

## 9. Image generation

`image_client.py generate` already covers the call. Wiring:

```bash
generate_image() {
  local slide_id="$1"
  local req_path="$2"
  local out_path="$IMAGES_DIR/${slide_id}.png"

  # Parse request to extract prompt + size + budget
  local image_prompt cost_ceil
  image_prompt="$("$PYTHON_BIN" -c "
import json
print(json.load(open('$req_path'))['image_prompt'])
")"
  cost_ceil="$("$PYTHON_BIN" -c "
import json
print(json.load(open('$req_path'))['worst_case_cost_usd'])
")"

  # Compute remaining budget
  local budget_remaining
  budget_remaining="$("$PYTHON_BIN" "$TOOLS_DIR/image_gen_budget.py" \
    remaining --manifest "$IMAGE_MANIFEST_JSON" \
    --cap "$MAX_IMAGE_COST_USD")"

  "$PYTHON_BIN" "$TOOLS_DIR/image_client.py" generate \
    --prompt "$image_prompt" \
    --out "$out_path" \
    --budget "$budget_remaining" \
    --channel A \
    --provenance "$IMAGE_PROVENANCE_JSON"
}
```

`image_client.py` writes the PNG, appends to `image_provenance.json`.
The orchestrator then writes the manifest entry (image_path,
slide_id, cost, approved_at).

---

## 10. Manifest write + merge integration

**Manifest schema:**

```json
{
  "schema_version": "image-manifest.v1",
  "entries": [
    {
      "slide_id": "S2-pos4",
      "image_path": "working/05_images/S2-pos4.png",
      "request_path": "working/05_image_requests/S2-pos4_request.json",
      "channel": "A",
      "approved_at": "2026-05-03T14:32:11Z",
      "cost_usd": 0.014,
      "model": "gemini-3-pro-image",
      "approved": true
    },
    {
      "slide_id": "S2-pos7",
      "approved": false,
      "rejected_at": "2026-05-03T14:32:35Z",
      "reason": "user-rejected: prompt drift from substory"
    }
  ]
}
```

**Merge integration.** `merge_compose_fragments.py` gains one new
arg: `--image-manifest <path>`. After loading slide fragments, it
loads the manifest and binds each `approved=true` entry's
`image_path` to the matching slide's figure field. For `concept_illustration`
slides, `image_path` becomes the slide's primary figure. For other
layouts (deferred to v0.3.4), it would become a supplemental figure.

**Test:** synthetic merge with one fragment containing a
concept_illustration slide + manifest with one entry → resulting
spec has the slide's figure populated with `working/05_images/S2-pos4.png`.

---

## 11. Orchestrator wiring

New CLI flags on `presentation_maker.sh`:

| Flag | Default | Semantics |
|---|---|---|
| `--no-images` | (off) | Skip image_gen stage entirely; merge proceeds without images |
| `--auto-approve-images` | (off) | Bypass per-slide gate; treat every emit=true as approved |
| `--image-allow-exploratory` | (off) | Override rule 6: allow concept_illustration on EXPLORATORY tier |
| `--max-image-cost-usd <n>` | `0.50` | Cumulative cap; image_gen halts when exhausted |
| `--image-style <style>` | (none) | Force style override across all images this run |

**`should_run` ordinal table extended.** New value `image_gen:11`
inserted; `merge:11→12`, `adversarial_review:12→13`, `revise_slides:13→14`.
The `--resume-from` case statement adds `image_gen` to the valid
list.

**Resume-from behavior.** `--resume-from image_gen` lets the user
re-run image generation against an existing draft (e.g., to re-roll
images after adjusting prompt). Pre-image-gen slide-fragment snapshots
in `audit/snapshots/03_slides_pre_image_gen/` are restored before the
new run, so we don't compound mutations.

**Resume-from merge.** When `--resume-from merge`, image_gen is
skipped; merge reads the existing manifest. Useful for
"approved images already generated, just rebuild the deck."

---

## 12. Cost cap

Cumulative-budget enforcement, per-image worst-case preflight (already
in `image_client.py::BudgetExceeded`), surfaced at orchestrator level:

- `--max-image-cost-usd` is total deck budget.
- Before each image's `image_client.py generate`, compute remaining
  budget = cap − sum(approved entries in manifest).
- Pass remaining as `--budget` to image_client; it raises
  `BudgetExceeded` if worst-case exceeds.
- Orchestrator catches BudgetExceeded → halts image_gen with a clear
  message: "image budget exhausted at slide X; remaining slides
  skipped. Rerun with --max-image-cost-usd N to continue."

**Calibrated default.** $0.50 covers ~30 images at the v0.3.0
calibrated $0.014/image, with 2× headroom against rate-card drift.
Power users override.

---

## 13. Tests-first plan

Build in test order to keep each step pinned by the prior:

**Tier 1 — Decision layer** (`tools/image_gen_decision.py`).
- `test_image_gen_decision.py`: 10 tests (one per rule + 3 edge cases).
- Exit: deterministic, zero LLM cost.

**Tier 2 — draft_paths extension.**
- `test_draft_paths.py` + 3 new assertions (decisions_json,
  manifest_json, provenance_json paths exist after init).
- Exit: layout schema test stays green.

**Tier 3 — Manifest writer** (`tools/image_gen_manifest.py`).
- `test_image_gen_manifest.py`: schema validation, append-entry,
  rejection-recording, idempotency-of-double-write.
- Exit: round-trip read/write.

**Tier 4 — merge_compose_fragments image binding.**
- Extend `test_merge_compose_fragments.py`: synthetic spec with one
  concept_illustration slide + manifest entry → bound figure path.
- Negative test: manifest entry for non-existent slide_id → warning
  + skip (don't crash).
- Exit: merge integration is invisible when manifest absent
  (backwards-compat with v0.3.2 drafts).

**Tier 5 — Approval-gate parser.**
- Extracted helper `_prompt_approval(req_dict, budget_remaining)` in
  Python that returns a verdict — testable without /dev/tty.
- 5 tests covering each menu choice.
- Bash side: thin wrapper around the Python helper.

**Tier 6 — Live-API integration test** (gated behind `image_gen` marker).
- `tests/integration/test_image_gen_live.py`: synthetic 1-slide draft
  → run image_gen with `--auto-approve-images` → assert PNG exists +
  manifest has 1 entry + provenance recorded.
- Cost: ~$0.014 per run; deselected by default.

**Tier 7 — Smoke**.
- Re-run on `core_gene_tradeoffs/draft_2` (or fresh draft_3) with
  full pipeline + `--auto-approve-images` + `--max-image-cost-usd 0.10`.
- Acceptance: 1-3 concept_illustration slides flagged; all images
  generate; manifest correct; deck assembles with images embedded.

**Total: ~30 new unit tests + 1 live-marked integration test.**

---

## 14. Open questions / risks

**Q1 (RESOLVED).** `concept_illustration` slides are flagged by
`slide_compose.v1.md` (L756-760) as: `layout: "concept_illustration"`
with `image_path: "{TBD}"` and `provenance: {model: "TBD",
cost_usd: 0, channel: "A", approved_at: "TBD"}`. There is no
separate `requires_ai_image` flag. The decision layer's signal is
simply `layout == "concept_illustration"` (rule 4). The
`{TBD}`-placeholder convention is what ai_image_prompt.v1 was
designed to consume; the v0.3.3 stage closes the loop by actually
calling that prompt.

**R1. Slide-fragment mutation breaks the "fragments are immutable
once written" invariant.** Snapshot to
`audit/snapshots/03_slides_pre_image_gen/` BEFORE mutation. Add a test
for snapshot existence post-stage. Document that fragments under
`audit/snapshots/` ARE the immutable record; `working/03_slides/` is
"working state."

**R2. `--auto-approve-images` opens an attack surface where a
malicious slide stub could induce a high-cost prompt.** Mitigated by
the per-image cost cap (worst-case $0.04 per `gemini-3-pro-image`)
and the cumulative `--max-image-cost-usd $0.50` cap. Worst case: 30
auto-approved bad images = $0.42. Acceptable for v0.3.3.

**R3. The user-edit path in the approval gate (`e` choice) needs
re-validation of the edited request.json.** Add `slide_spec.py`-style
schema validator for `image-request.v1` that runs after edit; reject
edits that break required fields with a clear message + re-show menu.

**R4. EXPLORATORY-tier opt-in name is awkward.**
`--image-allow-exploratory` is verbose. Alternatives:
`--exploratory-images`, `--allow-exploratory-images`. Settle on the
verbose form; tier is a load-bearing concept and the flag should
mention it explicitly.

**R5. Budget halts mid-stage leave `working/05_images/` in a
half-populated state.** Manifest correctly records what was
generated; merge tolerates the partial set. Re-running with
`--resume-from image_gen` and a higher cap continues from the
gap. Document this in SKILL.md §image-generation.

**R6. Rejection of a `concept_illustration` slide leaves placeholder
provenance (`approved_at: "TBD"`) which fails the ISO-8601
validator check.** Two cleanup options on rejection:

  - **Option A — drop slide.** Mutate the fragment to remove the
    rejected slide entirely. Renumber positions in the substory.
    Cleanest from a deck-coherence standpoint; user explicitly said
    "no image" and the slide was nothing-but-image.
  - **Option B — convert to fallback layout.** Rewrite the slide as
    a `claim_evidence` with the original `image_prompt` text as a
    single bullet and no figure. Keeps the substory's slide count
    stable but ships an image-less placeholder slide.

  **v0.3.3 ships Option A** (drop). It's simpler, doesn't introduce
  a new layout-rewrite path, and the user-visible behavior matches
  intent: "I rejected this image; the slide it was for goes away."
  Snapshot lives in `audit/snapshots/03_slides_pre_image_gen/` for
  recovery if the user changes their mind.

  Test: synthetic fragment with one concept_illustration → reject
  → fragment has the slide removed + position renumbering correct
  + manifest records the rejection.

**Q2. Should image generation respect `--no-stream`?** No — the
image gen stage doesn't use `claude -p` with `--output-format
stream-json` for the image generation itself (only for the request
authoring). The `--no-stream` flag continues to control
`stream_progress.py` parser; image generation is independent.

---

## 15. Out of v0.3.3 scope

- **Channel B** (user-initiated images via revise_loop or interactive
  command). Punch list calls this out; v0.4.x.
- **`claim_evidence` LLM-decision** for supplemental images. v0.3.4
  if smoke shows the deterministic gate misses real cases.
- **Quant-content judge.** vision-LLM scoring of generated images;
  `score_quantitative_content` is a stub. v0.4 needs vision-LLM
  integration via CBORG.
- **Direct-provider routing** (Google AI Studio / OpenAI). CBORG
  only. v0.4+.
- **Re-roll on rejection.** If user rejects with reason "drift from
  substory," there's no automatic re-prompt with stricter directives.
  User edits the request.json manually via `e` choice. v0.4 could
  add a "re-author with corrective hint" sub-loop.
- **Image quality review by adversarial reviewer.** beril-adversarial
  v0.7+ could include an `image_drift` detection class. Out of
  presentation-maker's scope; coordinate with adversarial team.

---

## 16. Effort & schedule

- Decision layer + tests: 0.5 days
- draft_paths extension + tests: 0.25 days
- Manifest writer + tests: 0.25 days
- merge_compose_fragments image-binding + tests: 0.5 days
- Approval gate (Python helper + bash wrapper): 0.5 days
- Orchestrator stage wiring + new flags: 0.5 days
- Live integration test (1-slide synthetic): 0.25 days
- Smoke + iteration: 0.5–1 day
- RELEASE_NOTES + commit message + version bump: 0.25 days

**Total: ~3.5 working days.** Aligns with punch list's "~3 days"
estimate.

---

## 17. Acceptance criteria (mirrors punch list, sharpened)

1. Live test on a MEDIUM BERDL project (target: `fitness_modules` or
   similar with multiple `concept_illustration` slides).
2. Decision layer flags 1–5 slides per the deterministic rules; zero
   false positives (no images on data_figure / data_table / structural
   slides).
3. All flagged slides produce a valid `image-request.v1` JSON that
   passes the v1 schema validator.
4. Per-slide approval gate gates each request; rejections are
   recorded in the manifest with no PNG written.
5. Approved slides generate PNGs at `working/05_images/<slide_id>.png`
   under the cumulative cost cap.
6. Manifest reflects every emit=true decision (approved / rejected /
   budget-skipped).
7. `merge_compose_fragments` binds each approved image to its slide's
   figure field; assembled deck embeds the PNGs.
8. `--no-images` flag disables the stage cleanly; resulting deck is
   identical to a v0.3.2 deck on the same project.
9. `--resume-from image_gen` re-runs against an existing draft using
   the pre-image-gen snapshot.
10. 30+ new unit tests + 1 live-marked integration test green.
11. Total run cost on smoke project ≤ $0.30 (image budget $0.10 +
    LLM request authoring $0.05–$0.20 across 1–5 slides).

---

## 18. Coordination with adversarial team

When the v0.7.0 adversarial schema lands (per memory entry
`project_adversarial_v0_6_x_taxonomy.md`):

- The new `central_objection` class (rename of `narrative_weakness`)
  needs revise_loop dispatch — separate task #57/#58 territory; not
  v0.3.3 scope.
- The proposed `citation_reality` class is paper-only; doesn't
  affect presentation-maker.
- Eventually adversarial v0.8 might add `image_drift` (image
  illustrates a concept inconsistent with the slide's claim).
  v0.3.3 doesn't need to anticipate this; it's a v0.4+ adversarial
  feature, and the manifest already captures slide_id → image_path
  + provenance for that future audit.

No coordination blocker for v0.3.3 ship.
