# M2 Punch List — M2-lite: the deck-outline call

**Filed:** 2026-05-23.
**Milestone:** M2 of the v0.4 architectural pivot (`V0_4_ARCHITECTURE.md` §16 + §20).
**Predecessor:** M1 — Phase-0 vendor ports (shipped 2026-05-21).
**Successor:** M3 — per-substory parallel composition (consumes the outline; adds the per-section composer brief + the post-merge reconciliation check).
**Design source:** `V0_4_ARCHITECTURE.md` §20 (v0.4.1 revision); decisions D-042–D-045; the outline probe (`experiments/m2-outline-probe/`).

## Status — M2-lite SHIPPED 2026-05-23

| Tier | Status |
|---|---|
| A — `deck_outline.v1.md` prompt | ✅ signed off (536 lines, incl. the D-phase patch) |
| B — `parse_deck_outline.py` + 15 tests | ✅ shipped; full suite 1014 passed; `parse_substories.py` untouched + still green on the enriched fixture |
| C — orchestrator wiring | ✅ shipped — `--architecture-pipeline {v0_3\|v0_4}` flag + `stage_deck_outline` + dispatch branch + `--resume-from` / `should_run` entries; `bash -n` clean; suite still 1014 |
| D — smoke | ✅ pass — `deck_outline` produced a real enriched `02_substories.md` on `ibd_phage_targeting` (Sonnet, $0.40); both parsers clean; transitions chain S→S; budgets within talk-30; capacity `fits` |
| E — closeout | ✅ this section + LAYOUT.md / V0_4_ARCHITECTURE §16+§20 / `--help` / auto-memory |

**D-phase patch (1 of the budgeted 1–3).** The first smoke run produced
bloated `Headline slot` fields — two `claim_id`s + a `Note:` appendage
per section. Root cause: the headline-slot rule over-weighted the
`effect_size` / `ci` / `pvalue` flags, treating a legitimate measured
proportion (88.2 % replication, 61 % of patients) as "ungrounded" and
forcing the model into a dual-headline workaround. Patched
`deck_outline.v1.md`: the flags are a context signal, not a gate;
proportions are valid headlines; one `claim_id` per slot (PA-5
reframed to "headline-slot bloat"). The confirming re-run ($0.40)
produced clean single-claim one-line headline slots.

**M3-carried dependency.** `deck_outline` reads the Phase-0 artifacts
(`claim_inventory.tsv`, `methods_provenance.md`) from
`working/00_phase0/`, which `phase0_reuse.py` produces — but
`phase0_reuse.py` is not yet wired into the orchestrator (M1 Tier F1).
The v0.4 orchestrator path cannot run end-to-end until M3 adds the
`phase0_tooling` stage. M2's Tier D smoke ran `deck_outline` standalone
with the Phase-0 inputs passed directly, so this did not block M2.

## Scope

M2-lite **produces the deck outline, end to end, validated on `ibd_phage_targeting` — no composition.** (Mirrors the original M2's "produces an architecture end-to-end, no composition yet.")

The outline is an **enriched `narrative/02_substories.md`**: the existing backward-compatible skeleton (`### S{N} —` headers, `**Punchline:**`, `**Critical analyses covered:**`, `**Capacity verdict:**`) — so `parse_substories.py` and beril-adversarial's `--type presentation` reviewer keep working untouched — PLUS new per-section fields (`**Budget:**`, `**Headline slot:**`, `**Transition in:**` / `**Transition out:**`, `**Scoped figures:**`) and a deck-level spec block (register, arc, image budget). The artifact is **not renamed** — beril-adversarial's `CONTRACT.md` reads `narrative/02_substories.md`; renaming it would be exactly the cross-skill contract drift the project keeps getting burned by.

**What M2-lite is NOT:** the per-section composer brief, parallel composition, and the post-merge reconciliation check are **M3**.

**LOC target:** `deck_outline.v1.md` ~550–650 lines (enrichment of the 449-line `substory_design.v1.md`); `parse_deck_outline.py` ~150 LOC + ~15 tests; orchestrator delta moderate.
**Cost ceiling at smoke:** one Sonnet `deck_outline` call, ~$0.30–0.80 on `ibd_phage_targeting`.

## Resolved design question — gate behaviour

`substory_design.v1` today is the **second user gate** (D-002 rev1 — substory-approval; it pauses-and-exits). v0.4.1 D-045 makes throughline-pick the *single routine* gate, so `deck_outline.v1` does **not** pause-and-exit on a routine run — it writes the outline and the pipeline flows through. **Exception:** D-027 (never silently drop a critical analysis when the mode budget overflows) is inviolable. So `deck_outline.v1` keeps a **conditional halt on overflow only**: routine runs flow through; an overflow run still halts with the drop/escalate/merge options for the user. Routine = flow-through; overflow = conditional halt.

## Tier A — `deck_outline.v1.md` prompt

Enrich `substory_design.v1.md` into a new prompt file `deck_outline.v1.md` (`substory_design.v1.md` stays in-tree until M6 archives the v0.3.x prompts).

**Carried from `substory_design.v1`:** clustering discipline, the mode-capacity overflow protocol (D-027), punchline word-count discipline, self-review pass, anti-patterns.

**Removed:** the routine pause-and-exit gate behaviour (D-045 — flow-through; conditional halt on overflow only).

**Added — per-section fields:**

- `**Budget:**` — content-slide budget (was `**Proposed slide budget:**`).
- `**Headline slot:**` — which claim/number is this section's `big_number`. Constrained: prefer a claim that carries an `effect_size_present` / `ci_present` / `pvalue_present` flag in `claim_inventory.tsv` — do not headline an ungrounded number (the §4.4 insight, applied at outline time instead of post-composition).
- `**Transition in:**` / `**Transition out:**` — one sentence each: how the section leads in from the prior section's close and hands off to the next. The outline probe showed these are the load-bearing coordination element — a composer that receives them bridges; one that doesn't opens cold.
- `**Scoped figures:**` — figure_ids from `curated_figures.md` assigned to this section (a scope hint for M3's composers; the scarce-resource pre-assignment).

**Added — deck-level spec block:** `**Register:**` (tier-aware — assertive / scoped / observational + hedge discipline), `**Arc:**` (how the sections earn each other), `**Image budget:**` (≤N AI concept illustrations deck-wide).

**Added inputs:** `deck_outline.v1` reads the Phase-0 artifacts (`claim_inventory.tsv`, `curated_figures.md`, `citation_pool.json`, `cross_tenant_signal.md`, `methods_provenance.md`) in addition to throughline + plan — it needs them to assign headline slots and scoped figures/claims. `substory_design.v1` read only throughline + plan + REPORT.

**AC:** `deck_outline.v1.md` exists; the output-format template shows the enriched `02_substories.md` with the backward-compatible skeleton intact + the new fields; **reviewed by Adam before Tier C wiring / Tier D smoke** (no token spend until the prompt is signed off).

## Tier B — `parse_deck_outline.py` + tests

`tools/parse_deck_outline.py` — extracts the new fields (per-section budget, headline-slot, transition-in/out, scoped figures; deck-level register / arc / image-budget). Mirrors `parse_substories.py`'s regex approach and CLI shape. `parse_substories.py` is **untouched** — it still parses the carried skeleton; that backward-compat is a Tier-B test. + ~15 unit tests.

**AC:** `parse_deck_outline.py --field {...}` extracts each new field from a fixture enriched `02_substories.md`; new tests green; `parse_substories.py`'s existing tests still green against the same fixture.

## Tier C — orchestrator wiring

`presentation_maker.sh`: a `deck_outline` stage replaces the `substory_design` stage — invokes `deck_outline.v1.md` via `claude -p` (Sonnet, `--output-format json` for F5-style cost capture). The state-machine phase enum gains `deck_outline`. `plan.v1` stays a separate upstream stage. No new `draft_paths.py` artifact path (the outline stays `narrative/02_substories.md`); add a phase constant if `state.py` enumerates phases.

**AC:** `presentation_maker.sh --stage deck_outline` dispatches the new stage; state enum updated; the full existing test suite stays green.

## Tier D — smoke

Propose a runbook, then run `deck_outline` end-to-end on `ibd_phage_targeting`. Needs throughline + the Phase-0 artifacts present: the Tier-D `talks/draft_pilot_no_paper/` draft already holds the originated Phase-0 artifacts; the throughline seeds from `papers/draft_2/00_throughline.md`. Produce a real enriched `02_substories.md`; eyeball it against the hand-written probe `outline.md` (`experiments/m2-outline-probe/outline.md`).

**AC:** a real enriched `02_substories.md` is produced; `parse_substories.py` AND `parse_deck_outline.py` both parse it cleanly; the new fields are populated and sane (headline slots reference grounded claims, transitions chain, budgets sum within mode); cost recorded from the `--output-format json` envelope.

## Tier E — closeout

`LAYOUT.md` §1 (`deck_outline.v1.md` under `prompts/`, `parse_deck_outline.py` under `tools/`); `V0_4_ARCHITECTURE.md` §16 + §20 M2 status → SHIPPED; this punch list's per-tier status table; auto-memory `project_presentation_maker_v0_4_m2.md` + `MEMORY.md` index line.

## Dep edges

```
A → B → C → D → E
```

A (prompt) gates B — the parser must match the prompt's exact output field names — and C — the wiring invokes the prompt. D (smoke) needs A+B+C. E ships after D's smoke gate passes.

## Smoke gate

- **D smoke gate:** `deck_outline` produces a parseable, populated, sane enriched `02_substories.md` on `ibd_phage_targeting`. Failure stops Tier E until the gate passes; expect 1–3 prompt patches in the D phase per `feedback_punch_list_release_pattern.md`.

## What M2-lite does NOT do (carried into M3)

- Per-section composer briefing (the whole outline + boundaries + scoped claims + visual brief fed to each composer).
- Parallel per-substory composition + the `slide_compose` narrowing.
- The ~30-line post-merge reconciliation check (duplicate-figure / double-headline / image-budget).

These are M3. M2-lite ends when a real, sane deck outline is produced and parseable.
