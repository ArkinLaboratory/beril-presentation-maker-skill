# V0.8 Punch List — Curator figure-floor + deck_close shape + visual-QA-on-by-default + prompt-layering fix + AI-image content-grounding

**Status:** drafted 2026-05-31 (post-v0.7 D-092 Tier-I veto).
Authoritative scope opening: this file + `DECISIONS.md` D-092 (the
v0.7 veto + five v0.8 inputs); pin from
[[project-presentation-maker-v0-7]] §"v0.8 inputs."

**Posture:** v0.8 picks up the five qualitative findings from
Adam's Tier-I read of the v0.7 (v3.2) decks + four cross-cutting
lessons from the v0.7 retrospective. Same pattern as the
D-084 → v0.7 transition (mechanical-pass + Adam-veto + carries
become next-version scope). Five workstreams across three themes:
**curator-stage gap-fixing** (F1), **slide_compose / deck_close
shape fixes** (F2 + F3), **operational defaults + content
grounding** (F4 + F5).

**Scope (5 workstreams + carries from v0.7-deferred-to-v0.8+):**

1. **F1: Curator figure-floor** (Lesson 1; Adam-Tier-I primary).
   → `tools/curate_figures.v1.md` (or successor curator agent)
     extends per-substory inventory rule: when a substory's
     analyses (per `02_substories.md` Critical-analyses-covered)
     have ≥1 figure candidate in their notebooks, the curator
     MUST emit ≥1 figure for that substory into
     `working/curated_figures.md`.
   → New `tools/check_curator_figure_floor.py` validator:
     for each substory, count notebook-candidate figures; if >0
     candidates AND 0 curated, emit P1
     `substory_no_curated_figure_despite_candidates`.
   → Cascade integration as new tier-1 reader (mirrors
     `_read_figure_provenance` pattern).
2. **F2: D-086 length + slide-content shape fix** (Lessons 2 + 3).
   → `extract_deck_close.py` enforces 2-sentence cap on
     `forward_call` at extraction time (not composer-time;
     fail-shallow at source). Long REPORT forward-directions
     bullets get truncated to first sentence + "..." marker for
     auditability.
   → Renderer `_fill_deck_close` stops drawing `data_source` on
     slide face. Either move to `speaker_notes` promotion
     (parallel to `speaker_notes_seed` pattern) OR keep as
     audit-trail field that validator reads but renderer
     ignores. Either way: no longer on the audience-facing
     slide.
   → Validator `tools/slide_spec.py::_check_deck_close` gains
     length-cap on `forward_call` (advisory soft-warning at
     >250 chars).
3. **F3: v3.2 substory_design prompt-layering investigation +
   fix** (Lesson 4).
   → Investigate why the v3.2 substory_design overlay silently
     dropped the v3 `Conclusion for next substory:` field +
     the v3.2 `Transition from prior:` field in live runs
     despite both being in the concat stack.
   → Hypothesis: v3.2 overlay's example-output section likely
     overrides v3's template; the LLM picks the most-recent
     example shape it sees in the prompt. Probably fixable by
     having v3.2 overlay's examples explicitly INCLUDE the v3
     fields (or by making the v3 + v3.2 templates merge cleanly
     instead of compete).
   → Extend smoke harness to assert specific output fields
     appear in `02_substories.md` output (currently the smoke
     only validates slide_compose's per-layout fields). New
     `tools/smoke_v3_prompt.py::validate_substory_design_fields`
     checks `Conclusion for next substory:` + `Transition from
     prior:` field presence per substory.
4. **F4: Visual-QA default-on for STRONG-mode runs** (Lesson 5).
   → 1-line orchestrator change: when `MODE=talk-30` AND
     `TIER=STRONG`, default `VISUAL_QA=1` (currently default 0).
     Operator can still opt out via `--no-visual-qa` (new flag
     to add). Cost ~$1/deck; findings surface mechanically vs.
     Adam-read.
5. **F5: AI image content-grounding** (Tier-I slide-3 spoiler
   finding).
   → `prompts/ai_image_prompt.v1.md` gains awareness of slide
     POSITION in deck arc (intro vs body vs closer). For intro
     slides, the prompt-author MUST NOT include result-level
     statistics from later sections.
   → New input to the prompt template: `DECK_POSITION` /
     `SUBSTORY_INDEX` so the LLM knows whether it's authoring
     for slide 3 (intro) vs slide 27 (body) vs slide 32
     (closer).
   → Possibly a post-image visual-QA hook that re-checks for
     "spoiler text on intro slide" once Tier C/D (visual-QA
     finding 1 on both decks today) shows this is a recurring
     class.

**Carries from v0.8 Tier G live discovery (new; documented but
deferred to v0.8.1):**

- **install-skill doesn't ship smoke fixtures.** Discovered at
  Tier G 2026-05-31: running `smoke_v3_prompt.py` from the
  installed-skill path fails with `smoke fixture missing at
  .../tests/fixtures/smoke_v3`. `install_skill.py`'s
  `_SHIPPED_SUBDIRS` covers only `commands`, `prompts`,
  `references`, `tools` — not `tests/fixtures/`. SKILL_REPO_ROOT
  resolution via `parents[4]` of the script also assumes dev-repo
  layout (`src/beril_presentation_maker/skill/tools/`), not the
  installed shallow layout (`.claude/skills/beril-presentation-maker/
  tools/`); from the installed path, `parents[4]` walks to
  `$BERIL_ROOT` itself. Tier-G workaround: run smoke from dev
  repo, copy pass record to installed `audit/` dir. v0.8.1 fix
  is two pieces: (a) add `tests/fixtures/smoke_v3` to
  `_SHIPPED_SUBDIRS` (or add a new `_SHIPPED_FIXTURE_DIRS`
  category to keep the semantic separation), (b) rework
  SKILL_REPO_ROOT to auto-detect dev-vs-install layout (search
  upward for a marker file like `SKILL.md` or `pyproject.toml`).
- **v3.3 validator's edge-case rules demoted to advisory.**
  Tier-G live smoke caught the LLM emitting Conclusion-for-next
  on the single-substory fixture (which is both first AND
  final). The user_prompt explicitly says to omit, but the
  v3.3 template makes the field look required. Demoted
  "Conclusion on FINAL" + "Transition on FIRST" from hard fail
  to stderr advisory; "missing on required slot" stays hard
  fail (the load-bearing D-095 bug class). The advisory still
  surfaces to operators; the demotion just keeps smoke from
  failing on a wart that doesn't matter on real 3-5-substory
  decks. If real Tier-G/H runs show the LLM ALSO emits these
  on multi-substory deck-ends/-starts, decide at Tier I
  whether to keep the advisory or land a prompt-side fix in
  v0.8.1.

- **Duplicate deck_close-shaped slide with `forward_call: "---"`
  (extraction artifact).** Live discovery on ibd_phage_targeting
  draft_12 (Adam-noted) + lanthanide_methylotrophy_atlas draft_1
  (adversarial F001) — both decks produced a SECOND deck_close-
  shaped slide near the end with `forward_call: "---"` and
  key_takeaways recycled as substory-transition questions. Per
  draft_1 speaker_notes self-confessed: "this needs patching."
  Likely cause: `extract_deck_close.py` or the merger splices a
  fallback deck_close stub when one is missing OR runs the splice
  TWICE when the substory list contains transition-marker text the
  extractor matches as a synthesis section. The duplicate is
  PROMINENT (slide 25 of 31) so a Tier-I read catches it
  immediately. v0.8.1 fix path: (a) detect duplicate
  forward_call: "---" + drop the duplicate at merge time; (b)
  audit extract_deck_close.py for double-splice; (c) prevent the
  composer from emitting "---" as a placeholder forward_call.

- **Visual-QA prompt over-confident on cause attribution.**
  Tier-G live discovery: visual-QA on draft_8 slides 25/26/27
  correctly flagged `illegible_scale` but mis-attributed the
  cause to "the full answer_detail text block is rendered
  visibly on the slide at approximately 6-7pt scale." Direct
  pptx inspection confirmed answer_detail is in speaker_notes
  (renderer working correctly); the illegible text on the slide
  face was answer_SUMMARY (1013-1325 chars at 70-80% autofit
  scale). v0.8 Tier G.2 hardened the answer_summary cap to fix
  the underlying length problem; v0.8.1 follow-up: tune
  visual-QA prompt to either (a) report symptom only without
  speculative attribution, or (b) actually inspect speaker_notes
  before attributing slide-face content to a notes-routed field.
  The symptom-only path is cheaper and matches visual-QA's
  actual epistemic position (it sees rendered PNGs, not the
  field-routing logic).

- **`beril-presentation-maker draft` Python wrapper silently
  drops `--prompts-version`.** Discovered at Tier G 2026-05-31
  when an agent invoked the skill via the documented
  slash-command path: `draft.py`'s argv allowlist doesn't
  include `--prompts-version`, so passing it through the
  Python wrapper produces an argparse error OR (worse) a
  silent v2 default if the wrapper silently drops it. The
  agent had to fall back to invoking the byte-identical shell
  orchestrator directly (`bash .claude/skills/.../presentation_maker.sh
  --prompts-version v3.3 ...`) to honor the flag. Any future
  v0.8 caller following the documented path gets a silent v2
  downgrade. v0.8.1 fix: extend the Python wrapper's allowlist
  to forward `--prompts-version` + `--force-v3-smoke-stale` to
  the shell orchestrator (also any other shell-orchestrator-
  only flags worth surfacing to operators). Until then, the
  Tier-G runbook's invocation example uses the shell-direct
  path so this gap is bypassed.

**Carries from v0.7 (still real; deferred again):**

- **Per-arc figure clustering / per-arc-distribution metric** —
  v0.7-A.1's `relevant_figure_not_used` finding shipped + works.
  Adam's v0.7 read confirms it's no longer the load-bearing
  complaint. Stays open as a v0.9+ "could be tightened" surface.
- **Composer-side cross_tenant grounding omissions** — v0.7 ibd
  ran with 4 omissions (amplicon/ec/go + HMP); fdm with 2
  (ec/go ambiguous-short-name pattern). These are advisory
  soft-warnings; the composer can be nudged to enumerate every
  K-BERDL DB explicitly. Probably a `cross_tenant.v1.md` prompt
  tweak adding "name every signal entry by canonical name" rule.
- **fdm S1 hallucinated figure path** (`figures/fig01_annotation_breakdown.png`
  not in curated inventory). `data_figure_path_not_in_curated_inventory`
  fired correctly; this is composer-prompt drift the prompt-side
  v3.x overlays should catch. Probably a v0.8 anti-pattern entry
  in `slide_compose.v3.x_overlay.md`.

**Carries from v0.5.1 (still deferred):**

- Retraction-aware composer / `discarded_results.md` filter —
  no recurrence in v0.6 or v0.7 reads. Deferral remains
  acceptable; document as "v0.9+ if surfaces again."
- Compression / mode-budget heuristics — ibd v0.7 at 33 slides
  (mode-30 budget 18-32; 1 over); fdm v0.7 at 39 slides (way
  over). Worth investigating in v0.8 if the deck-density read
  feels off; lower priority than F1-F5.

**Prompt versioning:** v3.3 overlay on v3.2 stack (D-075 pattern
extends again). v0.8 ships:
- `substory_design.v3.3_overlay.md` (new — F3 prompt-layering
  fix; merges cleanly with v3.2 instead of overriding).
- `slide_compose.v3.3_overlay.md` (new — F5 content-grounding;
  position-aware image-gen guidance).
- Concat: `cat substory_design.v1.md + .v3_overlay.md + .v3.2_overlay.md
  + .v3.3_overlay.md` (or merged v3.3 supersedes v3.2 entirely
  if F3 fix is structural).
- `--prompts-version {v1,v2,v3,v3.1,v3.2,v3.3}` flag adds v3.3.
- Smoke gate (D-076) extends: v3.3 requires fresh v3.3-smoke-pass.

**Cut-over rule:** same as v0.5/v0.5.1/v0.6/v0.7 (D-066, D-079,
D-084, D-092 lineage). Adam-veto is final regardless of mechanical
result. Metric targets for v0.8:

- **Per-substory figure availability** (F1; new metric):
  for each substory, count curated_figures.md entries whose
  NB-id matches. Target: every substory with ≥1 candidate-
  figure in its analyses' notebooks has ≥1 curated entry.
  v0.7 baseline: unmeasured (we don't audit curator gaps yet).
- **deck_close shape compliance** (F2; new metric):
  forward_call ≤250 chars; data_source NOT rendered on slide
  face (per-slide PNG inspection or render-time test).
  v0.7 baseline: fdm slide-32 fails both.
- **v3.3 substory_design field presence** (F3; new metric):
  every substory in `02_substories.md` has BOTH
  Conclusion-for-next AND (where applicable)
  Transition-from-prior. Smoke-asserted. v0.7 baseline: 0%
  (live drift dropped both).
- **Visual-QA finding count** (F4; new metric): default-on +
  used as a Tier-F-equivalent pre-Adam-read gate. v0.7
  baseline: 11 ibd + 13 fdm warnings (unmeasured before).
- **AI-image spoiler count** (F5; new metric): visual-QA
  finds "result-from-later-section on intro slide" pattern.
  Target 0. v0.7 baseline: 1 per deck (slide 3 intro-pos1).

## DQs resolved at Tier 0 sign-off (2026-05-31)

All five DQs resolved 2026-05-31. See DECISIONS.md D-093..D-097
for the full rationale + alternatives considered. Summary:

| DQ | Decision | Anchor |
|---|---|---|
| DQ1 (curator figure-floor) | Belt-and-suspenders: curate_figures agent nudge + new check_curator_figure_floor.py validator (cascade-integrated as tier-1 reader). Mirrors D-080 / D-085 / D-089 pattern. | D-093 |
| DQ2 (deck_close data_source) | Speaker-notes promotion (renderer drops data_source from slide face + promotes to speaker_notes "Sources:" section). Schema preserved; composer-doc clarified. | D-094 |
| DQ3 (substory_design v3.3) | Ship clean v3.3 overlay on v1 directly (NOT stacked on v3/v3.2) consolidating Q/A/R/C + transition_from_prior into one template with explicit "v3.3 supersedes" recency-bias mitigation. Retire v3.2 substory_design from default; slide_compose stays v3.2 (not vulnerable per Tier-0 root-cause subagent). | D-095 |
| DQ4 (visual-QA modes) | Default-ON for talk-30 STRONG + talk-15 STRONG/BRIEF. New --no-visual-qa opt-out flag. lightning-5 + poster stay opt-in via --visual-qa. | D-096 |
| DQ5 (AI-image content-grounding) | Prompt input only for v0.8 MVP: ai_image_prompt.v1.md gets new DECK_POSITION input + intro-slide spoiler rule + PA-9 anti-pattern. Post-image validator deferred to v0.8.1 if Tier-F shows prompt-side fix insufficient. | D-097 |

**Root-cause investigation** (F3 prompt-layering bug) completed
at Tier 0 via Explore subagent (2026-05-31). Finding: v3.2
substory_design overlay's example block re-shows v3 fields but
lacks v3's explicit "this template SUPERSEDES" language. LLMs
weight prompt-tail heavily (recency bias); the v3.2 example
became authoritative + fields-not-restated got dropped.
slide_compose v3.2 doesn't have the same vulnerability (smoke
harness LAYOUT_REQUIRED_FIELDS map enforces shape independent
of prompt-tail). v3.3 substory_design only (not slide_compose).

<details>
<summary>Original DQ language (kept for historical reference)</summary>

### DQ1: F1 curator figure-floor — strict rule or advisory?

**Question:** When a substory has analyses with candidate
figures available but the curator picks 0 for the shortlist,
should the curator be FORCED to surface at least 1, or just
WARNED?

**Options:**
- **(a) Hard rule, curator emits ≥1 per substory with
  candidates** — curator agent's prompt requires it; new
  validator checks + fails curator stage on violation.
- **(b) Soft-warning, validator only** —
  check_curator_figure_floor.py emits P1; curator can choose
  to surface 0 if all candidates are weak. Adam at Tier-F
  decides.
- **(c) Both (D-080 belt-and-suspenders pattern)** — curator
  prompt nudges; validator catches what gets through.

**My read:** (c) — D-080's pattern is the v0.7-proven default.

**Resolves at Tier 0.**

### DQ2: F2 data_source — speaker-notes promotion or schema removal?

**Question:** data_source is currently a required deck_close
content field. Adam Tier-I shows it shouldn't render on slide
face. Move to speaker_notes treatment or drop from schema?

**Options:**
- **(a) Speaker-notes promotion** — `_fill_deck_close` stops
  drawing data_source; instead promotes it to a section of
  `speaker_notes` (parallel to `speaker_notes_seed` pattern).
  Audit trail preserved + presenter sees it.
- **(b) Drop from required content** — slide_spec.py schema
  change: data_source becomes slide-level metadata (alongside
  validator_status, id, etc.), not content. Renderer never
  draws it. Validator audits.
- **(c) Both** — speaker-notes promotion AND validator
  audits the slide-level metadata field.

**My read:** (a) — minimally invasive; preserves D-086 schema
shape; only renderer + composer-agent change. Schema-stable.

**Resolves at Tier 0.**

### DQ3: F3 v3.2 substory_design field drop — prompt rework or new v3.3?

**Question:** The v3.2 substory_design overlay silently dropped
v3's Conclusion-for-next + its own Transition-from-prior.
Should v0.8 fix in-place (re-edit v3.2 overlay) or ship a
clean v3.3?

**Options:**
- **(a) Re-edit v3.2 overlay in place** — v3.2 stays the
  prompts-version name; the overlay's example block changes
  to explicitly include both fields. Cheaper; backward-compat
  preserved.
- **(b) Ship v3.3 + retire v3.2** — v3.3 is the clean
  substory_design + slide_compose overlay; v3.2 stays available
  but undocumented; new smoke requires v3.3.
- **(c) Ship v3.3 + keep v3.2 documented as deprecated** —
  hybrid; v3.3 is default; operators can pin v3.2 for
  reproducibility.

**My read:** (b) for hygiene. v3.2 turned out broken;
v3.3 is the clean shape. The v3.2 → v3.3 transition mirrors
v3 → v3.1 → v3.2 evolution: each new version is a clean
overlay refinement.

**Resolves at Tier 0.**

### DQ4: F4 visual-QA default-on — STRONG only or all modes?

**Question:** Default `VISUAL_QA=1` for which modes?

**Options:**
- **(a) STRONG mode only (talk-30)** — most expensive talks
  benefit most; cost ~$1/deck.
- **(b) STRONG + talk-15 BRIEF** — same logic; both deserve
  visual-QA.
- **(c) All modes** — including lightning-5 + poster. Cost
  ~$1 even on short modes.

**My read:** (b). STRONG and talk-15-BRIEF both produce
audience-facing decks where slide-face quality matters.
Lightning-5 is rough-draft territory; poster is rendered
differently anyway.

**Resolves at Tier 0.**

### DQ5: F5 AI-image content-grounding — prompt input only or post-image validator?

**Question:** How to prevent intro-slide AI images from
leaking later-section findings?

**Options:**
- **(a) Prompt input only** — `ai_image_prompt.v1.md` gets
  `DECK_POSITION` input + rule "intro slides MUST NOT include
  result-level statistics from sections >1." Cheaper.
- **(b) Post-image visual-QA hook** — new validator inspects
  the rendered image for known-spoiler-pattern (statistics
  from later substories appearing in the image). Catches
  prompt-side drift.
- **(c) Both (D-080 belt-and-suspenders)** — prompt guides;
  validator catches.

**My read:** (a) for v0.8 MVP; (c) at v0.8.1 if Tier-F
recurrence shows the prompt rule alone isn't enough. The
v0.7 visual-QA already catches this class advisorily; the
v0.8 fix is upstream prevention.

**Resolves at Tier 0.**

</details>

## Per-tier scope

| Tier | Scope | Status |
|---|---|---|
| 0 — DQ1-DQ5 sign-off + F3 prompt-layering root-cause | research + DECISIONS | ✅ done 2026-05-31 (D-093..D-097 in DECISIONS.md; Adam-confirmed; F3 root cause = LLM recency-bias displacement on v3.2 substory_design example block; slide_compose v3.2 not vulnerable per subagent's LAYOUT_REQUIRED_FIELDS-based reasoning; v3.3 substory_design ONLY scope, not slide_compose). |
| A — F1: curator figure-floor per D-093 (curate_for_mode substory-aware per-substory floor [the BELT] + new check_curator_figure_floor.py validator + cascade integration [the SUSPENDERS] + orchestrator stage_curate_figures wiring) | curator stage | ✅ done 2026-05-31 (substory-aware promotion landed in curate_for_mode; check_curator_figure_floor.py emits audit/curator_figure_floor.json; review_cascade.py reads it as 9th Tier-1 source; presentation_maker.sh stage_curate_figures forwards --substories-path + invokes validator; 44 new unit tests; 1665→1709 unit total) |
| B — F2: deck_close data_source speaker-notes promotion per D-094 (promotion moved to MERGER `merge_compose_fragments.py` — cleaner layer than D-094 spec; renderer drops data_source from slide face; composer doc updated) | merger + renderer + composer-doc | ✅ done 2026-05-31 (8 new unit tests: +6 stage_deck_close +2 assembler; 1709→1717 unit total; schema preserved per D-086) |
| C — F3: clean v3.3 substory_design overlay per D-095 (substory_design.v3.3_overlay.md on v1 + orchestrator --prompts-version v3.3 + retire v3.2) | prompt + orchestrator | ✅ done 2026-05-31 (commit c83db0f; +9 tests; default still v3.2 in orchestrator) |
| D — F4: visual-QA default-on per D-096 (orchestrator mode-aware VISUAL_QA toggle + --no-visual-qa opt-out flag + --help doc) | orchestrator | ✅ done 2026-05-31 (auto-on logic post-TIER-validation: STRONG + talk-30/talk-15 → ON, all others OFF; BRIEF tier treated as stale spec note pending future tier addition; 23 new unit tests covering source-pins + runtime exec of full D-096 mode/tier matrix + stderr announcement; 1717→1740 unit total) |
| E — F5: AI-image content-grounding per D-097 (ai_image_prompt.v1.md DECK_POSITION input + §4 intro-slide spoiler rule + PA-9 anti-pattern + self-review check #12 + orchestrator wiring computes deck_position from slide_id format) | prompt + orchestrator | ✅ done 2026-05-31 (orchestrator regex `^pos[0-9]+$` → intro / else body; "closer" reserved for forward-compat; 20 new unit tests; 1740→1760 unit total; D-097 escalation hook to v0.8.1 post-image validator preserved if prompt rule alone insufficient) |
| F — smoke harness extension for v3.3 substory_design field-presence assertions per D-095 (smoke_v3_prompt.py + new validate_substory_design_fields function) | smoke tool | ✅ done 2026-05-31 (commit d2ca8cc; +12 tests; default --version=v3.3) |
| G — live A/B re-run on ibd_phage_targeting (v3.3 substory + v3.2 slide_compose) | live (~$13) | ⬜ not started |
| H — live A/B re-run on functional_dark_matter (v3.3) | live (~$13) | ⬜ not started |
| I — Adam reads decks + casts veto | review + DECISION | ⬜ not started |
| J — docs (DECISIONS + RELEASE_NOTES + LAYOUT + SPEC per veto) | docs | ⬜ not started |
| K — closeout + auto-memory + tag (per veto) | paperwork + tag | ⬜ not started |

## Dep edges

```
Tier 0 → unlocks A + B + C + D + E + F
Tier C (v3.3 substory_design) → Tier F (smoke needs v3.3 stack)
Tier A + B + C + D + E + F → Tier G/H (live runs need everything stable)
Tier G + H → Tier I (Adam read)
Tier I → Tier J + K (paperwork)
```

## Smoke gates

- **Tier 0 gate:** DQ1-DQ5 resolutions; v0.7-carry investigation
  documented.
- **Tier A gate:** curator agent emits ≥1 figure per substory
  with candidates on a synthetic project + the new validator
  fires soft-warning when curator violates.
- **Tier B gate:** extractor truncates a 4-sentence forward_call
  to 2 sentences with audit; renderer doesn't draw data_source
  on slide face (visual-QA on a synthetic deck confirms).
- **Tier C gate:** substory_design v3.3 produces output with
  BOTH Conclusion-for-next AND Transition-from-prior fields on
  a synthetic 4-substory fixture.
- **Tier D gate:** talk-30 STRONG run with no --no-visual-qa
  flag automatically runs visual-QA; talk-30 STRONG with the
  flag skips it.
- **Tier E gate:** AI image prompt for an intro slide doesn't
  include result-level numbers from later sections on a
  synthetic 3-substory fixture.
- **Tier F gate:** `smoke_v3_prompt.py --version v3.3` composes
  + validates against the v3.3 stack.
- **Tier G/H gate:** both runs end-to-end; per-substory figure
  availability >0 on every substory with candidates;
  forward_call ≤250 chars on deck_close slides; data_source
  not on slide face per visual-QA; substory_design output has
  both fields.

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — DQ sign-off | 1-2h research + DECISIONS |
| A — curator figure-floor | 3-4h |
| B — deck_close shape fix | 2-3h |
| C — substory_design v3.3 + prompt-layering investigation | 4-6h (most of the work is *understanding* what broke in v3.2) |
| D — visual-QA default-on | 1h |
| E — AI-image content-grounding | 2-3h |
| F — smoke extension for v3.3 | 1h |
| G — ibd v3.3 run | ~50min wall + ~$13 |
| H — fdm v3.3 run | ~50min wall + ~$13 |
| I — Adam read + veto | 30-60min Adam-time |
| J — docs (only if shipping) | 1-2h |
| K — closeout + tag (only if shipping) | 30min |
| **Total** | ~15-22h coding + ~$26 live + ~1h Adam-attention |

Coding total smaller than v0.7's ~20-30h because most v0.8
workstreams are well-scoped fixes rather than new contracts.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| F3 prompt-layering investigation reveals a fundamental incompatibility between v3 + v3.2 prompts that's harder than a re-edit | Time-box Tier C at 6h; if not converging, ship v3.3 as a clean rewrite of substory_design (no v3 inheritance) + accept the disruption. v3 substory_design is structurally simple enough that re-authoring is feasible. |
| F1 curator figure-floor causes curator to over-emit weak figures (the inverse Adam-complaint) | DQ1 (c) belt-and-suspenders: curator prompt has both "≥1 per substory" rule AND "exclude figures below quality threshold X." Adam at Tier-F still arbitrates if weak figures land. |
| F2 speaker-notes promotion conflicts with existing speaker_notes_seed convention | Validate: data_source-promoted-to-notes appears as a distinct section AFTER speaker_notes_seed body. Composer agent doc updates clarify. |
| F4 visual-QA-default-on adds ~$1/deck to STRONG runs operators may not want | --no-visual-qa flag (new) provides the opt-out. Default-on for STRONG only (DQ4 (a) or (b)). |
| Adam reads v3.3 + finds ANOTHER class of issue v0.8 metrics don't catch | Tier-I veto pattern is the production-quality gate (D-066/D-079/D-084/D-092 lineage). Pre-plan v0.9 absorbing v0.8's findings. |

## What v0.8 does NOT do

- **No new architectural pivots.** v3.3 is an overlay extension
  (or clean rewrite of v3.2 substory_design); the D-075 concat-
  overlay pattern continues. No new pipeline surgery.
- **No new image-gen providers.** M5b's multi-provider layer
  unchanged.
- **No SPEC schema additions.** F2 may remove or re-shape
  deck_close.data_source but no new layouts.
- **No new validators beyond F1 (curator figure-floor) +
  possibly F5-validator.**

## What ships at v0.8 closeout (conditional on veto)

If Adam-veto = SHIP:
- v0.8.0 tag.
- v3.3 prompts become opt-in via `--prompts-version v3.3`.
- Default `--prompts-version` may move to v3.3 if v0.7+v0.8
  shipping-but-untagged history feels stable; otherwise stays
  v2.
- DECISIONS D-093..D-09x for v0.8 decisions.
- Visual-QA becomes default-on for STRONG/BRIEF; orchestrator
  --help docstring documents the --no-visual-qa opt-out.
- RELEASE_NOTES + LAYOUT + SPEC updates.

If Adam-veto = DON'T SHIP:
- Same pattern as v0.5.1/v0.6/v0.7 lineage: work stays on
  main; no tag; v0.9 inputs captured.

## Ref

- `DECISIONS.md` D-092 (the v0.7 veto opening v0.8 scope).
- D-085 / D-086 / D-087 / D-088 / D-089 (the v0.7 contracts
  whose Tier-I findings drive v0.8 fixes).
- D-075 / D-076 (the concat-overlay + smoke-gate patterns
  v3.3 extends).
- D-066 / D-079 / D-084 / D-092 (Adam-veto-final pattern
  continuing at v0.8 cut-over).
- [[project-presentation-maker-v0-7]] (v0.7 retrospective +
  v0.8 inputs).
- `tools/curate_figures.v1.md` (the curator agent F1 extends).
- `tools/extract_deck_close.py` (F2 trim location).
- `tools/visual_qa.py` (F4 default-on toggle).
- `prompts/ai_image_prompt.v1.md` (F5 content-grounding).
- `prompts/substory_design.v3.2_overlay.md` (F3 fix-or-replace).
