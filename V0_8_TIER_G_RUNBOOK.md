# V0.8 Tier G Runbook — live A/B re-run on `ibd_phage_targeting`

**Cost estimate:** ~$13 + ~$0.50 contingency for image-gen reruns + AI-image approvals (v0.7 spend baseline). Cascade + visual-QA (now default-on per D-096) add ~$1.50 on top of the v0.7 baseline.

**Pre-flight gate:** The smoke-pass record's prompt sha is stale as of HEAD (`d758198`) because Tier C added the v3.3 substory_design overlay (sha source changed). Per D-076 the orchestrator will REJECT a v3.3 live run unless smoke is re-run first. **Re-run smoke before invoking the live pipeline.**

---

## Step 1 — Reinstall the skill on the hub

The Tier A/B/C/D/E/F commits added new tools (`check_curator_figure_floor.py`, `substory_design.v3.3_overlay.md`, etc.), modified the orchestrator (`presentation_maker.sh`), modified the merger (`merge_compose_fragments.py`), modified the renderer (`assemble_pptx.py`), and modified the prompt (`ai_image_prompt.v1.md`). The installed skill at `$BERIL_ROOT/.claude/skills/beril-presentation-maker/` needs refreshed copies.

```bash
cd $BERIL_ROOT
pipx install --force git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git \
  && beril-presentation-maker --version \
  && beril-presentation-maker install-skill .
```

> **Note:** the URL above is the full literal — `git+ssh://git@github.com/ArkinLaboratory/beril-presentation-maker-skill.git`. Don't substitute `...` placeholders; pip treats them literally and fails with `fatal: no path specified`. If you don't have SSH set up with GitHub, use HTTPS instead: `git+https://github.com/ArkinLaboratory/beril-presentation-maker-skill.git` (you'll be prompted for credentials).

Verify the install caught all v0.8 files:

```bash
ls -la $BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/check_curator_figure_floor.py
ls -la $BERIL_ROOT/.claude/skills/beril-presentation-maker/prompts/substory_design.v3.3_overlay.md
grep "v0.8/D-096" $BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/presentation_maker.sh | head -3
grep "v0.8/D-097" $BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/presentation_maker.sh | head -3
grep "v0.8/D-094" $BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/merge_compose_fragments.py | head -3
```

All four greps should match. If any missing, the install didn't refresh — re-run `install-skill --force` (the install command has a `--force` flag per its argparse).

---

## Step 2 — Re-run the smoke (gate-required)

The orchestrator gates v3.3 invocation on a fresh smoke-pass record per D-076. Run smoke against the INSTALLED skill so the pass record lands where the orchestrator looks for it:

```bash
python $BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/smoke_v3_prompt.py
```

Cost: ~$0.60. Wall-clock: ~1-2 min. Expected stderr tail:
```
[smoke_v3.3] PASS — wrote .../.claude/skills/beril-presentation-maker/audit/v3_smoke_pass.json
```

Verify the pass record landed at the right place AND has the matching sha:

```bash
python $BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/smoke_v3_prompt.py --check-recent
```

Expected: `pass record fresh; v3 invocation allowed` (or similar). If this still fails after the smoke run, the sha source list in `compute_prompt_sha()` may have drifted; flag immediately rather than bypassing with `--force-v3-smoke-stale`.

**If smoke FAILS:** the failure record at `.../audit/v3_smoke_fail.json` contains the diagnostic. The new v3.3-specific assertion `validate_substory_design_fields()` may flag a field-presence regression in the LLM output. Triage by reading the failure record before retrying.

---

## Step 3 — Run the live A/B

From a Claude Code session on the hub (the slash command needs the TTY-loop):

```
/beril-presentation-maker ibd_phage_targeting --mode talk-30 --tier STRONG --prompts-version v3.3 --auto-advance
```

Or via direct bash (skips the throughline-pick gate by auto-advancing to TL1):

```bash
cd $BERIL_ROOT
$BERIL_ROOT/.claude/skills/beril-presentation-maker/tools/presentation_maker.sh \
  ibd_phage_targeting \
  --mode talk-30 --tier STRONG \
  --prompts-version v3.3 \
  --auto-advance
```

**Do NOT pass `--no-visual-qa`** — we explicitly want the auto-on behavior to fire for the first time live.

---

## Step 4 — Watch stderr for v0.8-specific markers

Each marker confirms one of the v0.8 build-tier changes engaged. Missing markers indicate the install didn't pick up the change.

| When | Marker | Source | Tier |
|---|---|---|---|
| ~10s in (post-MODE/TIER validation) | `[v0.8/D-096] visual-QA auto-on for talk-30 STRONG (audience-facing mode; ~$1 + ~30s/deck; --no-visual-qa to opt out)` | orchestrator default-init | D |
| Stage 3.5/5 curate_figures | `curate: per-substory floor enabled (N_substories=4; source=.../narrative/02_substories.md)` | curate_figures.py --substories-path | A |
| Same stage, after curation | `-> figure-floor check: N substory/ies uncovered (advisory)` | check_curator_figure_floor.py | A |
| Stage 11/14 image_gen, per slide | (per-slide ai_image_prompt invocation) — user_prompt contains `DECK_POSITION=intro` or `DECK_POSITION=body` | orchestrator stage_image_gen | E |
| Post-assembly | `running visual-QA pass (--visual-qa)...` | stage_visual_qa | D |
| Stage merger (substory_design) | `[smoke gate] v3.3 substory_design fresh-pass-record satisfied` (or similar; or the gate-fail diagnostic if smoke wasn't re-run) | smoke gate | F |

---

## Step 5 — Post-run audit checklist

After the pipeline completes, inspect the draft directory at `$BERIL_ROOT/projects/ibd_phage_targeting/talks/draft_*/`. Most recent draft is the one Tier G produced.

### v0.8-specific audit files

| File | Verifies | Expected content |
|---|---|---|
| `audit/curator_figure_floor.json` | Tier A | `findings[]` may be empty (curator floor satisfied) OR contain `substory_no_curated_figure_despite_candidates` entries (advisory, not failures); `summary.coverage_rate` should be ≥ v0.7 baseline |
| `audit/visual_qa.json` | Tier D | exists (didn't exist on v0.7 ibd because visual-QA was opt-in); `n_slides_reviewed` ≈ deck length; `findings[]` may flag legit render issues for Tier I review |
| `narrative/02_substories.md` | Tier C/F | per substory: **Question:** present on ALL; **Conclusion for next substory:** present on non-final; **Transition from prior:** present on non-first. The v3.3 field-presence smoke check would have caught a regression pre-live; this is the live confirmation |
| `working/slide_spec.json` deck_close slide | Tier B | `slides[].content.data_source` preserved verbatim per D-086; `slides[].speaker_notes` contains `**Sources:** <data_source>` appendix; renderer-side: the rendered slide must NOT visibly show data_source on its face |
| `05_image_requests/*.json` | Tier E | for intro slides (`pos*_request.json`), the `image_prompt` must NOT include result-level statistics (specific %, p-values, OR/HR/AUC, named outcomes); body-slide requests are exempt |
| `audit/review_cascade.json` | A+B+E aggregate | Tier-1 findings should include `curator_figure_floor:*` entries; should NOT show `figure_provenance:relevant_figure_not_used` regression vs v0.7 |

### Slide-face inspection (the v0.7 leak class)

Open `deliverable/draft.pptx` (or the slide-renders if visual-QA produced them):

- **Slide closing the deck (deck_close)** — should show: title (unified_point), 3-5 bullets (key_takeaways), one short forward_call line. NO citation footer ("S1 C-slot", "REPORT.md §X"). The presenter's speaker_notes pane should contain those citations as `**Sources:**` block.
- **Slide 3 (intro pos1 with AI image)** — image should illustrate a study-design / scope / conceptual framework. NO embedded percentages, p-values, or named downstream metrics. If it slips through, Tier I notes it; the v0.8.1 escalation hook activates.

---

## Step 6 — Mechanical pass/fail gates

Pass the following gates before scoring Tier H (functional_dark_matter) — failures here indicate a v0.8 regression to fix before the second wet run:

| Gate | Target | Why |
|---|---|---|
| Pipeline completes rc=0 | required | otherwise something broke the build-tier integration |
| `audit/curator_figure_floor.json` exists | required | Tier A invocation wired correctly |
| `audit/visual_qa.json` exists | required | Tier D auto-on fired |
| 02_substories.md has Question on ALL substories | required | v3.3 field-presence holds live |
| 02_substories.md has Conclusion-for-next on non-final | required | v3.2 field-drop regression fixed |
| 02_substories.md has Transition-from-prior on non-first | required | v3.2 field-drop regression fixed |
| deck_close slide_spec content.data_source preserved | required | D-094 schema stability |
| deck_close speaker_notes contains **Sources:** | required | D-094 promotion fired |
| No `relevant_figure_not_used` cascade findings on substories with candidates | strong-pref | per-substory floor working |

If ALL gates pass → proceed to Tier H (functional_dark_matter).
If any FAIL → triage + commit-message + re-run as needed; the new commits land in a `v0.8` cycle pre-Tier-H.

---

## Cost-control reminders

- `--auto-approve-images` will skip per-slide image approval prompts (v0.7 used this on the second of two ibd runs to recover faster). The first run should NOT auto-approve so you see the new DECK_POSITION-aware prompts as they come.
- `--max-image-cost-usd 5` caps image-gen spend (default is higher; v0.7 used the default).
- The visual-QA pass adds ~$1 + ~30s. If you want to skip on this dry-run for cost reasons, pass `--no-visual-qa` — but the auto-on stderr line WILL still announce, then the suppression takes effect.

---

## Sanity: what's different from v0.7 Tier G

| Surface | v0.7 baseline | v0.8 expected |
|---|---|---|
| Cascade Tier-1 readers | 8 sources | 9 sources (+ curator_figure_floor) |
| visual-QA invocation | opt-in (--visual-qa) | auto-on for STRONG + talk-30/talk-15 (per D-096) |
| substory_design prompt stack | v1 + v3 + v3.2 (3 sources) | v1 + v3.3 (2 sources; clean overlay per D-095) |
| 02_substories.md fields per substory | Question; v3.2-required Conclusion + Transition silently dropped | Question + Conclusion (non-final) + Transition (non-first) all reliably present |
| deck_close slide face | data_source footer band at y=4.52 | NO data_source on face; promoted to speaker_notes as **Sources:** |
| AI image prompts | no position awareness | DECK_POSITION=intro\|body passed; intro-slide spoiler rule + PA-9 in prompt |
| Default flag set | `--prompts-version v3.2` default in orchestrator | `--prompts-version v3.2` still default (CLI), v3.3 must be explicit |

---

## What to paste back for Tier H / Tier I review

After the run completes successfully, paste the following so I can triage + draft any in-flight fixes BEFORE Tier H:

1. Last ~50 lines of stderr (auto-on announcement, curator floor log, visual-QA invocation, cascade summary).
2. `audit/curator_figure_floor.json` (full content; small file).
3. `audit/visual_qa.json` summary (findings count by kind + the first 3 findings).
4. First substory's section from `narrative/02_substories.md` (verifies v3.3 field presence on the load-bearing case).
5. The deck_close slide's `content` + `speaker_notes` fields from `working/slide_spec.json`.
6. One intro-slide image request JSON (`05_image_requests/pos*_request.json`) so we can audit the image_prompt for spoiler-class statistics.

That's enough for me to confirm v0.8 mechanical pass and either green-light Tier H or land in-flight fixes first.
