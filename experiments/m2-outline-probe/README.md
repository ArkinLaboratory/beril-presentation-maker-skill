# M2-lite outline probe

A ~$2–4 experiment that decides whether to build **M2-lite** — the
shared-outline / pre-architecture call in the v0.4 presentation-maker
pivot (~12–18h of work).

## The question

Does a per-section slide composer that *also* sees a shared whole-deck
outline + a boundary brief produce better cross-section coordination —
transition-in/out coherence, register consistency, arc — than one that
sees only its own substory? If yes → build M2-lite. If a hand-crafted
ideal outline barely moves the needle → don't; just parallelise (M3)
and stop.

## What it does / doesn't prove

- **Tests Risk 1** — *does outline-as-context help the composer.*
- **Does NOT test Risk 2** — *can the outline call reliably generate a
  good outline.* `outline.md` is hand-written here (best-case input).
  Deliberate: if even an ideal outline doesn't help, M2-lite is dead
  regardless of Risk 2; if it helps, Risk 2 becomes the secondary,
  addressable question.

## Design

3 adjacent `ibd_phage_targeting` substories (a talk-30: framework →
targets → intervention), composed under up to 3 conditions:

| Cond | Composer sees | Role |
|---|---|---|
| **B** | its substory only — no prior fragments, no outline | naive parallel — the no-M2-lite counterfactual |
| **C** | its substory + the shared whole-deck `outline.md` + a boundary brief | M2-lite |
| **A** *(optional, `--with-today`)* | its substory + prior composed fragments (`PRIOR_SUBSTORY_OUTPUTS`) | today's sequential pipeline — regression reference |

Decision-critical comparison: **C vs B.** A answers the side question
"does parallel+outline regress vs today's sequential pipeline?"

All conditions use the same model (Sonnet 4.6, pinned), the same
hand-assembled inputs (`inputs/`), and the real `ibd_phage_targeting`
REPORT.md / notebooks. The only variable across arms is the outline
(and, for A, prior-fragment visibility). Figures and citations are run
empty on purpose — the probe isolates text coordination and keeps cost
low; `slide_compose`'s escape hatches cover empty figures/citations.

## Inputs (`inputs/`, hand-assembled from real material)

- `00_throughline.md` — copied verbatim from the project's real
  `papers/draft_2/00_throughline.md`.
- `00_plan.md` — critical-analysis inventory A1–A12; a reformat of the
  throughline's evidence map (same claims, strength glyphs, REPORT
  pointers).
- `02_substories.md` — the 13 throughline sub-claims partitioned into 3
  substory clusters.
- `curated_figures.md`, `citation_pool.json` — intentionally empty.
- `outline.md` — the hand-written M2-lite prototype (the experimental
  manipulation; condition C only).

## Run it

On a machine with an authenticated `claude` CLI (your Mac):

```bash
cd experiments/m2-outline-probe
./run_probe.sh                # conditions B + C — 6 calls, ~$2-4, ~20-30 min
./run_probe.sh --with-today   # adds condition A — 9 calls, ~$3-6, ~30-45 min
```

Outputs land in `out/`: `<cond>_<sid>_slides.json` (the composed
fragments), `<cond>_<sid>.envelope.json` (the `claude -p` json
envelope), `<cond>_<sid>.stderr`, and `cost.tsv` (per-call cost +
exit + whether a fragment was written).

## Assess

Read the fragments side by side, B vs C (and vs A if run). Score:

1. **Transition-in coherence** — does C/S2 open by connecting to S1's
   close? Does B/S2 open cold? (S1 has no prior section — judge S2, S3.)
2. **Register consistency** — punchline cadence + hedge handling across
   S1–S3: more uniform under C?
3. **Arc** — does the C set read as one deck (framework → targets →
   intervention earning each step), or three disconnected mini-decks?
4. **Headline-stat placement** — does C honour the outline's
   headline-number slots (8,489 / 88.2% / 95% / 61%)?

**Decision rule.** C visibly beats B on transitions + register → build
M2-lite. C ≈ B → don't; parallelise (M3) and stop. Mixed → scope
M2-lite down to just the wins that are real.

This directory is an untracked experiment — delete it when the probe
has served its purpose.
