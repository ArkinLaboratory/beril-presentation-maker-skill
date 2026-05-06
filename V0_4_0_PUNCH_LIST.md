# v0.4.x Punch List

**Last updated:** 2026-05-06
**Status:** active — opportunistic pre-May-7 ship; v0.3.6 is the safe Thursday floor.

## Framing

v0.3.6 (shipped 2026-05-06) closes the TTY-block bug that was breaking 100% of hub participants. That makes the May 7 event executable. Beyond v0.3.6, anything we ship is **improvement**, not blocker. Each item below has its own go/no-go gate; if any individual fix introduces ship risk inside the 36-hour pre-event window, hold it post-event.

The four highest-priority items surfaced by the 2026-05-06 review of the `ibd_phage_targeting` talk-45 deck (memoryless peer-scientist review + image-gen decision diagnostic). Plus the architectural follow-up (#85) which was always slated for post-event.

## Sequencing — go/no-go decision tree

```
v0.3.6 (SHIPPED) — TTY block + halt-and-handoff
  │
  ├─ Tier A (pre-May-7 IF time allows; independent — can land in either order)
  │   │
  │   ├─ #90 image_gen_decision LLM-judgment      [ ~6-8h, biggest visible uplift ]
  │   └─ #87 process-detail-bleed post-checker    [ ~6-8h, biggest perceived-quality uplift ]
  │
  ├─ Tier B (pre-May-7 IF Tier A landed cleanly; investigation-only, no ship risk)
  │   │
  │   └─ #89 wall-clock investigation             [ analysis only — no code ship pre-event ]
  │
  └─ Tier C (post-May-7, larger scope)
      │
      ├─ #85 state.json + Phase enum (paper-writer parity)
      ├─ #88 revise-loop caveat-handling rewrite
      └─ #74-77 layout cosmetic fixes
```

## Tier A — high-impact, ship-bounded

### #90 — image_gen_decision LLM-judgment layer

**Status:** in flight (this conversation)
**Effort:** 6-8 hours
**Ship plan:** v0.3.7 (own release; isolated to one Python module + one new prompt)

**Problem.** `image_gen_decision.py` has a `_DEFERRED_LLM_DECISION` frozenset listing 6 layouts (claim_evidence, workflow_diagram, two_column_compare, big_idea, big_number, implications). Current Python returns `emit=false` for all of them with reason "supplemental-image decision deferred to v0.3.4 LLM-judgment layer." The deferred layer was never built. Outcome on `ibd_phage_targeting` talk-45: 15 of 33 candidate slides got rejected → **zero** AI illustrations in a 37-slide deck.

**Acceptance criteria.**
1. New per-slide LLM call for slides whose layout is in `_DEFERRED_LLM_DECISION`. Prompt asks "would a conceptual AI illustration add value beyond what this layout's existing content provides?" with slide title, content, tier, substory context as input. Returns `yes|no` + brief reason.
2. Cost: ≤$0.01/slide (Sonnet 4.6 short-call); <$0.20 added per draft for typical 15-20 deferred slides.
3. Calibration on ≥2 projects post-implementation: expect 3-7 illustrations per talk-45 (not 15 — LLM should reject many; >0 is the bar).
4. Per-slide approval gate downstream still runs (`--auto-approve-images` aware).
5. Tests: unit-level mock of the LLM call; integration smoke that emit=true is achievable on candidate slides.

**Smoke at boundary.** Re-run draft on `ibd_phage_targeting` (or any STRONG project) → expect emit=true on a non-zero subset of deferred-layout slides. Inspect generated illustrations on 1-2 slides for quality.

**Go/no-go gate.** If LLM returns malformed responses on >10% of calls, hold post-event for prompt iteration. If costs spike beyond $0.30/draft, hold for cap revisit.

### #87 — process-detail-bleed post-checker + prompt rules

**Status:** specced (#87)
**Effort:** 6-8 hours
**Ship plan:** v0.3.8 (independent of #90; can interleave or sequence)

**Problem.** Memoryless reviewer flagged ~11 of 37 slides leaking internal artifact names (NB\d+, .ipynb, REPORT.md, .tsv, data/nb, §Pillar, A/H/L/E\d+) into slide bullets, captions, and speaker notes. Reads as internal jargon to peer audiences.

**Acceptance criteria.**
1. New `tools/check_no_artifact_refs.py` post-checker mirroring `check_quantitative_grounding.py` architecture. Regex scan over slide_spec.content + speaker_notes; advisory exit (rc=0 with diagnostic block to stderr); slide+location breakdown.
2. Wired into orchestrator at merge stage (after slide_spec is final, before assemble).
3. Prompt rules added to `slide_compose.v1.md` and `revise_slide.v1.md`: explicit anti-pattern + worked example showing artifact-citation → peer-citation substitution. Cite the live failure.
4. Citation_pool stage validator: any citation entry whose only source is a filename gets flagged (separate from regex check; addresses the deeper "citing files instead of papers" problem).
5. Tests: regex hit/miss on synthetic specs; integration smoke on a fabricated artifact-laden spec.

**Smoke at boundary.** Re-run on `ibd_phage_targeting` slide_spec.json → expect post-checker to flag ~11 slides matching the reviewer's manual-flagged set. Apply prompt rule fixes; re-run draft on a fresh project; verify <5 flagged slides on the new run.

**Go/no-go gate.** If prompt changes don't reduce artifact references in a fresh run, hold the prompt edits and ship just the post-checker (informative-only is still valuable for participants doing hand-edits).

## Tier B — investigation only, no pre-event ship

### #89 — wall-clock investigation

**Status:** specced (#89)
**Effort:** 2-3 hours analysis
**Ship plan:** post-event (any code fix from this lands in v0.4.0+; the diagnosis itself is enough)

**Problem.** `ibd_phage_targeting` talk-45 STRONG ran 2+ hours; documented expectation is 45-60 min for talk-30. Stage-1 (plan) alone took 9.6 min — suspect.

**Acceptance criteria for this tier:** produce a per-stage cost+wall-clock table (from `audit/stages/stage_metadata.json`), identify the 2-3 longest stages, write a 1-page memo on parallelization opportunities. No code change required pre-event.

**Smoke at boundary.** Memo + table delivered.

## Tier C — post-event

### #85 — state.json + Phase enum (paper-writer parity)

The full architectural follow-up to v0.3.6's minimal halt-and-handoff. Replaces single-purpose `.handoff.json` with a real state machine; migrates the substory_overflow gate too. ~1.5-2 days of focused work. Tracked separately; does NOT block any of Tier A or B.

### #88 — revise-loop caveat-handling rewrite

Taste-level prompt engineering; defer until #87 + #90 land.

### #74, #75, #76, #77 — layout cosmetic fixes

Hand-fixable in PowerPoint by participants for May 7. Defer until v0.4.x cycle.

## Cumulative scope check

If Tier A lands clean by Wednesday end-of-day, the Thursday hub experience improves materially:

- **Image-gen produces 3-7 illustrations per talk** instead of 0 (#90).
- **Process-detail bleed flagged** as advisory in the audit log so participants know what to hand-fix (#87 post-checker).
- **Slide-compose + revise prompts** generate cleaner first drafts (#87 prompt rules).

If only one tier-A item lands clean, prefer #90 — the visible-capability uplift is larger than the perceived-quality uplift from #87.

If neither lands clean, v0.3.6 is the floor and the docs already explain the limitations honestly. No regret path.

## Decision points

- **End of Wed work session (2026-05-06 EOD):** if either #90 or #87 is shippable with clean tests + smoke verified, tag as v0.3.7 / v0.3.8 and push. Otherwise, hold both for v0.4.0 post-event.
- **Thu morning pre-event:** participant runbook URL pinned to whatever is most recently tagged. v0.3.6 if nothing else shipped, v0.3.7+ if Tier A landed.
- **Post-event Mon/Tue (May 11-12):** start on #85 architectural rework + #88 / #74-77 cleanup.

## What's out of scope for this punch list

- Cross-skill items (paper-writer's HUB_INSTALL.md, atlas's CONTRACT.md if a real consumer emerges) — those teams own their cycles.
- BERIL upstream changes — never push.
- Per-cohort event handouts — Adam owns.
