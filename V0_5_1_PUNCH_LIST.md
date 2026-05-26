# V0.5.1 Punch List — fix v3 prompt schema-drift root cause

**Status:** drafted 2026-05-26 post-abort. Authoritative root-cause:
`project_presentation_maker_v0_5_morning_abort.md` (auto-memory).

**Root cause discovered:** v3's `slide_compose.v3.md` is a 380-line
**standalone** prompt that describes the v2 schema as "(Unchanged
from v2)" without actually including it. The orchestrator passes
that single file as `--system-prompt` (see `presentation_maker.sh:730`,
`invoke_claude()` does `sys_prompt="$(cat "$sys_prompt_file")"`).
The LLM running v3 therefore has NO access to v2's ~900 lines of
per-layout authoring guidance — it must hallucinate field names.
Result: 21 identical `required field missing` errors per run; the
LLM produced `title`/`subtitle`/`transition_note` where v2 expects
`punchline`/`substory_number`, etc.

Even v3's OWN anti-pattern bullets use the wrong field name
("Opening section_divider whose `title` is a topic name…" — v2's
field is `punchline`, not `title`). The prompt-author (me, the
night before) didn't know v2's field names either; the
"strictly-additive overlay" design hid the gap.

**Posture:** v0.5.1 is a **prompt-architecture fix**, not a feature.
The v0.5 milestone scope (D-070: content-discipline via
register-discipline + Q/A/R/C contract) stands. v0.5 deliverables
that already shipped (validators, parse extension, orchestrator
flag) all remain. Only the v3 prompt itself needs to be
restructured so the LLM actually gets v2's authoring guidance.

**Cut-over rule:** unchanged from V0_5_PUNCH_LIST.md (D-065 + D-066
inherited). v0.5.1 must produce decks that pass schema validation
+ Adam-veto must approve on the same target/sanity projects (ibd
+ fdm).

## DQs to resolve at Tier 0 sign-off

### DQ1: v3 prompt assembly strategy

**Question:** How should v3's "v2 body + register-discipline + Q/A/R/C
overlay" composition work mechanically?

**Options:**
- **(a) Concatenated-at-runtime file**: `_slide_compose_prompt_path`
  for v3 emits a temp file = `cat v2.md v3_overlay.md`. Generated
  once at orchestrator start; cached; cleaned up at EXIT trap.
  `slide_compose.v3.md` is renamed/repurposed as
  `slide_compose.v3_overlay.md` (just the ~150-line overlay).
  **Cleanest.**
- **(b) Self-contained clone**: copy v2.md → v3.md, then add
  overlay sections inline. Single ~1400-line file. No dispatcher
  complexity; same per-invocation cost as v2. Trade-off: every
  future v2 prompt fix needs porting (drift risk).
- **(c) Runtime overlay via user-prompt heredoc**: dispatcher
  returns `slide_compose.v2.md` unchanged for v3; orchestrator
  appends a "V3_OVERLAY_RULES" block to the user prompt (alongside
  SUBSTORY_QUESTION etc.). LLM gets full v2 system prompt + v3
  rules in the user message. Trade-off: system vs user prompt
  asymmetry; the v3 rules don't get the same attention weight as
  the system prompt content.

**My read:** (a) — concatenation gives us the LLM-attention parity
of (b) without the drift risk. ~30 min implementation. (b) is the
safe fallback if (a) hits a shell-quoting or temp-file lifecycle
issue. (c) is rejected — system prompt is where authoring rules
belong.

**Resolves at Tier 0.**

### DQ2: live-LLM smoke test gating

**Question:** Per the cross-cutting lesson in
[[project-presentation-maker-v0-5-morning-abort]] (lesson 1: "mocked
tests aren't contract tests"), should the v3 prompt flag be gated
on a live-LLM smoke test? If so, where does it run?

**Options:**
- **(a) Add a `tools/smoke_v3_prompt.py` script** that composes ONE
  substory fragment against the real LLM, validates the fragment
  against the v2 schema, and exits non-zero on failure. Run
  manually before each `--prompts-version v3` live use. Cost:
  ~$0.30 per smoke. Not in CI (no provider keys in CI).
- **(b) Add it AND gate the orchestrator on it**: if
  `--prompts-version v3` is passed and no recent smoke-pass record
  exists (e.g., `audit/v3_smoke_pass.json` < 7 days old per
  project), refuse to run. Forces the operator to smoke before
  burning ~$13 on a full run.
- **(c) Defer**: v0.5.1 ships the prompt fix; smoke harness is a
  v0.5.2 carry. Risk: regression-by-future-edit recurs.

**My read:** (b) — the abort was a $30 lesson; building the gate is
$30 of dev time + $0.30 per use. Trivially pays for itself the
next time we touch prompt content. Reuse the M5b
ai_image_gen_probe.json sidecar pattern.

**Resolves at Tier 0.**

### DQ3: handle v3 overlay's broken anti-pattern bullets

**Question:** v3's anti-pattern section (lines 341-356) names the
wrong field names: "Opening section_divider whose `title` is a
topic name…" — v2's actual field is `punchline`. Same for
Q-slide / C-slide. After concatenation, the LLM will see v2's
authoritative `punchline` field name AND v3's overlay calling it
`title`. Conflict.

**Options:**
- **(a) Fix v3 overlay to use v2's field names verbatim** (find
  + replace `title`→`punchline` in the Q-slide anti-pattern
  bullets; verify against v2's per-layout section for each layout
  v3 references).
- **(b) Reframe v3 anti-patterns to be LAYOUT-AGNOSTIC** (e.g.,
  "Opening section_divider whose principal-text-field is a topic
  rather than the Question…") — punts the field-name authority
  back to v2 entirely.
- **(c) Drop the v3 anti-pattern bullets**: register-discipline
  + Q/A/R/C role guidance already live elsewhere in v3; the
  anti-pattern bullets just summarize them.

**My read:** (a). Fix the bug, don't dodge it. The field-name fix
is mechanical (5-10 minutes) and gives the LLM consistent
direction. (b) sounds clean but adds vague language; (c) drops
useful guidance.

**Resolves at Tier 0.**

### DQ4: handle `substory_design.v3.md` (the OTHER v3 prompt)

**Question:** `substory_design.v3.md` is the other v3 prompt
(adds Q + Conclusion fields). Does it have the same
standalone-vs-overlay problem?

**Options:**
- **(a) Inspect-and-fix**: read substory_design.v3.md; if it's
  ALSO a standalone-with-Unchanged-from-v1-disclaimers, apply the
  same concat fix.
- **(b) Defer**: the morning abort didn't trip a
  substory_design-shape bug — only slide_compose. substory_design
  may be fine because the Q/A/R/C fields it adds aren't on the
  schema-validation hot path the way slide_compose fields are.

**My read:** (a) — inspect first. If it's standalone-broken,
apply the same fix. If not, this DQ resolves to "no change."

**Resolves at Tier 0 inspection.**

## Per-tier scope

| Tier | Scope | Status |
|---|---|---|
| 0 — DQ1-DQ4 sign-off + substory_design.v3 inspection | research + DECISIONS | ✅ DECISIONS D-075..D-078 committed; substory_design.v3.md inspection confirmed same standalone problem (369 lines, 11 "Unchanged" disclaimers); concat fix lands in Tier A.2 (no longer conditional) |
| A — restructure slide_compose.v3.md per D-075 (concat fix) | prompts + orchestrator dispatcher | ✅ ready to commit 2026-05-26 (deleted broken standalone `prompts/slide_compose.v3.md`; created `prompts/slide_compose.v3_overlay.md` (~243 lines) containing ONLY v3-additive sections (header banner + register-discipline preamble + Q/A/R/C role guidance + post-composition self-check + anti-patterns + inviolable rules additions); orchestrator changes: pre-flight loop swap (v3.md → v3_overlay.md); new `build_v3_concat_prompts()` runs after `set_draft_paths` and writes `$AUDIT_DIR/_prompts/slide_compose.v3.concat.md` (= cat v2.md v3_overlay.md, v2 first); shell vars `SLIDE_COMPOSE_V3_CONCAT_PATH` + `SUBSTORY_DESIGN_V3_CONCAT_PATH` populated at build time; dispatchers echo the path vars; substory_design.v3 still standalone (TODO marker in `build_v3_concat_prompts` for D-078/Tier A.2 to wire); --help docstring updated. 4 new tests: build_v3_concat happy-path (audit/_prompts file present + v2 marker before v3 marker + shell-vars populated), no-op-on-v1-v2 path, overlay-present-on-disk belt+suspenders, old-standalone-retired guard. 2 existing tests updated for new shell-var dispatcher contract + new pre-flight literal (now requires v3_overlay.md, forbids v3.md). Suite 1408 passed (was 1404; +4 new tests)) |
| A.1 — fix v3 overlay anti-pattern field names per D-077 | prompts | ✅ ready to commit 2026-05-26 (audited overlay against v2's authoritative per-layout schema; found 3 distinct sites where claim_evidence's required field was wrongly named `punchline` instead of `title` — same root-cause bug as the dead standalone v3.md, just in slightly different prose. Fixed: (1) C-slide guidance block now names `title` + cites v2's "title is the punchline; declarative" annotation; (2) post-composition Pass 2 self-check now references `title` for claim_evidence; (3) C-slide anti-pattern bullet now references `title`. Also strengthened the inviolable-rules Q+C clause to enumerate both layout→field pairs explicitly (`section_divider`→`punchline`, `big_idea`→`title` for Q; `claim_evidence`→`title`, `big_idea`→`title` for C) + warns "Do NOT substitute generic names." Per v2 ground truth: `section_divider` requires `punchline`+`substory_number`; `claim_evidence` requires `title`+`bullets`; `big_idea` requires `title`. Added 3 anti-recurrence unit tests pinning each fix (C-slide cites `title`, Q-slide cites `punchline`, inviolable-rules enumerate both pairs + warn against generic-name substitution). Suite 1411 passed (was 1408)) |
| A.2 — restructure substory_design.v3.md per D-078 (same concat fix) | prompts + orchestrator dispatcher | ✅ ready to commit 2026-05-26 (mirrors Tier A on substory_design: deleted broken standalone `prompts/substory_design.v3.md`; created `prompts/substory_design.v3_overlay.md` (~208 lines) containing ONLY v3-additive sections — header banner + Q/A/R/C contract specifics (D-071) + v3 Output-format-supersedes-v1 template + v3 self-review pass + v3 anti-patterns + v3 inviolable rules. Critical design point: v3's output template CHANGES v1's (adds Question + Conclusion fields per substory). Overlay header explicitly says "Output-format change. The v1 'Output format' section above must be SUPERSEDED by the v3 template below — when the v1 template and the v3 template conflict, use the v3 template." LLM sees both templates back-to-back; overlay-LAST attention plus the explicit supersede statement makes v3 win. Orchestrator changes: pre-flight loop swap (substory_design.v3.md → substory_design.v3_overlay.md); `build_v3_concat_prompts` TODO stanza replaced with the real concat (`cat substory_design.v1.md substory_design.v3_overlay.md` → `audit/_prompts/substory_design.v3.concat.md`); --help docstring updated to name both concats. Tests: 1 dispatcher test updated (v3 → substory_design.v3.concat.md); pre-flight test updated to require substory_design.v3_overlay.md + reject the standalone v3.md (regex word-boundary so `v3_overlay.md` doesn't false-match `v3.md`); build_v3_concat test extended to assert BOTH concat files written with correct order; overlay-present + old-retired tests extended for both files. Suite 1411 passed) |
| B — `tools/smoke_v3_prompt.py` + gating per D-076 | new tool + orchestrator | ⬜ not started |
| C — live A/B re-run on ibd_phage_targeting | live (~$13) | ⬜ not started |
| D — live A/B re-run on functional_dark_matter (sanity) | live (~$13) | ⬜ not started |
| E — Adam reads decks + scores metric 5 + veto | review + DECISION | ⬜ not started |
| F — docs (DECISIONS + V0_4_ARCH + RELEASE_NOTES + LAYOUT) | docs | ⬜ not started |
| G — closeout + auto-memory + tag (v0.5.0 / v0.5.0-experimental) | paperwork + tag | ⬜ not started |

## Test strategy (anti-recurrence)

The 1404 unit tests didn't catch the v3 schema-drift bugs because
they all mock the LLM's composed output to match v2 shape. v0.5.1
adds TWO new test surfaces:

1. **Prompt-schema-consistency static check** (`tools/check_prompt_schema_consistency.py`):
   walks `prompts/*.md`, extracts the JSON schema example blocks,
   and compares them against the actual JSON Schema referenced by
   the slide_spec validator. Fails if v3's example schema
   diverges from what the merger expects. Catches Bug 1 (top-level
   shape drift) class.
2. **Live-LLM smoke** (`tools/smoke_v3_prompt.py` per DQ2):
   composes ONE substory fragment + validates. Catches Bug 2
   (per-layout field-name drift) class.

Both are pre-existing test-pattern reuses (sidecar JSON cache + JSON
schema introspection), not novel infra. ~3-4 hours to land both.

## What v0.5.1 does NOT do

- **No NEW content-discipline features.** D-072 (register-discipline)
  + D-071 (Q/A/R/C contract) are the v0.5 scope; v0.5.1 just makes
  them work. No v0.5 carry items get promoted.
- **No architecture changes.** v0_3 vs v0_4 settled per D-069.
- **No widening of v3 scope.** Throughline-bridge + figure-utilization
  remain deferred to v0.6 per D-070.

## Cost estimate

| Tier | Estimate |
|---|---|
| 0 — DQ sign-off + substory_design inspection | 30-45min |
| A — restructure v3 + dispatcher + tests | 1.5-2h |
| A.1 — anti-pattern field name fix | 15min |
| A.2 — substory_design.v3 fix (conditional) | 15-30min |
| B — smoke harness + gating + tests | 1-2h |
| C — ibd v0.5.1 re-run | ~50min wall + ~$13 spend |
| D — fdm v0.5.1 re-run | ~50min wall + ~$13 spend |
| E — Adam read + veto | 30-60min Adam-time |
| F — docs | 1h |
| G — closeout + tag | 30min |
| **Total** | ~5-7h coding/docs; ~$26 live spend; ~1h Adam-attention |

This is ~30% of v0.5's original scope (the validators + parse
extension + orchestrator flag are already done; v0.5.1 is just
fixing the prompt-content-side of the contract).

## Dep edges

```
Tier 0 (DQ sign-off) → unlocks A + A.1 + A.2 + B in parallel
Tier A → Tier B (smoke needs the fixed v3)
Tier A + A.1 + A.2 + B → Tier C/D (need fixed v3 + smoke gating)
Tier C + D → Tier E (Adam read needs both project pairs)
Tier E → Tier F + G (paperwork)
```

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Concatenation produces a too-long system prompt (~1400 lines + overlay → ~1600); LLM context bloat | Per-invocation system-prompt cost goes up ~10%; user-prompt + tool-results dominate token budget so impact is minor. Smoke harness catches if quality degrades. |
| Temp-file lifecycle issues (orphan files, race in parallel composers) | Generate concat once at orchestrator start (single threaded); store path in shell variable; remove via EXIT trap. The pattern is already used elsewhere in the orchestrator for working/ artifacts. |
| Anti-pattern field-name fix introduces a different bug | A.1 fix is mechanical + small; cover with at least one unit test pinning the corrected field name. |
| Live smoke harness costs add up if iterated many times | `--prompts-version v3` is opt-in; default is v2; smoke only runs when operator explicitly uses v3. ~$0.30 per smoke. |
| substory_design.v3.md also broken; A.2 finds bigger blast radius | Inspect first; DQ4 conditional gate prevents implementing the wrong fix. |
| Concat order matters (v3 overlay should be LATER than v2 so it "wins" on conflicts) | The concat order is v2 + v3_overlay (overlay goes last; final text in system prompt = anchored at end of LLM attention). Reverse order would weaken the overlay. |

## Ref

- `project_presentation_maker_v0_5_morning_abort.md` (auto-memory):
  full root-cause analysis + forensic evidence pointers.
- Commit d682d45: partial fix (Bug 1 top-level shape) + runbook
  update.
- `$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_6/` +
  `$BERIL_ROOT/projects/functional_dark_matter/talks/draft_6/`:
  forensic evidence (broken v3-composed fragments).
- `presentation_maker.sh:730` (`sys_prompt="$(cat "$sys_prompt_file")"`):
  the single-cat-file invariant the concat fix preserves.
- `prompts/slide_compose.v2.md` (1267 lines): the authoritative
  per-layout authoring vocabulary v3 must inherit verbatim.
- `prompts/slide_compose.v3.md` (380 lines, broken): becomes
  `slide_compose.v3_overlay.md` (~150 lines, register-discipline +
  Q/A/R/C only).
