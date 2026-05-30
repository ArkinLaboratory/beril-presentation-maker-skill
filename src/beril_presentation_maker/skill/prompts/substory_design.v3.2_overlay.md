# --- v3.2 overlay (BERIL Presentation-Maker — Substory Design) ---

> **v3.2 (2026-05-30, v0.7 Tier B — new file; v3 overlay remains
> via `--prompts-version v3` or `v3.1`).** This overlay stacks ON
> TOP of `substory_design.v3_overlay.md` (which itself stacks on
> `substory_design.v1.md`). The concat order is:
>
>     cat substory_design.v1.md \
>         substory_design.v3_overlay.md \
>         substory_design.v3.2_overlay.md
>
> All v3 contracts (D-071 substory Q/A/R/C, the v3 punchline +
> cluster-rationale tightening, the v3 inviolable rules 3–5)
> remain in force. This overlay ADDS one obligation:
>
> 1. **`Transition from prior:` field** (D-087) — every substory
>    after the first MUST include a brief field summarizing what
>    claim from the prior substory this one builds on. The
>    composer (slide_compose v3.2) reads this field when authoring
>    the substory's first non-Q slot, so the deck reads as a
>    cumulative argument rather than N self-contained beats.
>
> Authoritative source: D-087 (substory_design.v3.2 owns
> cross-substory awareness; cleaner data flow per Adam Tier-0
> DQ3 vs a slide_compose-only solution); v0.6 Tier-F veto
> (D-084 finding 2: "no arc transitions / arcs don't build on
> each other").

## v3.2 failure modes ADDED on top of v3

(v3's failure modes — topic-as-Question, conclusion-as-recap,
handoff-break — all still apply. v3.2 adds one.)

- **Transition-absent.** A substory after S1 lacks a `Transition
  from prior:` field. The composer (slide_compose v3.2) has no
  cross-arc anchor to reference; the substory's first non-Q slot
  reads as if it's the deck's opening rather than a continuation.
  → Add the field; it should reference S(N-1)'s
  `Conclusion for next substory:` verbatim or in paraphrase, then
  state what S(N) does with that result.

## v3.2 contract specifics — Transition from prior (D-087)

The `Conclusion for next substory:` field (v3) is the *abstract*
handoff — it names the operative result S(N) hands forward.
The `Transition from prior:` field (v3.2) is the *concrete*
bridge S(N+1) opens with — it tells the composer how to start
S(N+1)'s first non-Q slide so the audience feels the build.

### The **Transition from prior:** field

- **Required on every substory except S1.** S1 opens the deck;
  it has no prior arc to transition from.
- **ABSENT (not "null", not empty) on S1.** The field is omitted
  on the first substory's block. The composer interprets absence
  as "no transition; open this substory fresh."
- **1–2 sentences.** Brief — this is a transition, not a recap.
  The full content of S(N-1) is on its slides; the audience just
  finished reading them.
- **Names the prior-arc result + this-arc question.** Pattern:
  *"S(N-1) established <prior result>. S(N) asks: <this
  substory's question>."* The first sentence names what the
  audience just learned; the second names what this substory
  does next.
- **Anchors to `Conclusion for next substory:` (v3 field).** If
  S(N-1) has `Conclusion for next substory: We identified 51
  candidate targets`, then S(N)'s `Transition from prior:` should
  build on that — *"With the 51-target shortlist from S1 in
  hand, S2 asks which subset is therapeutically tractable."* The
  v3 Conclusion → v3.2 Transition coupling makes the handoff
  audit-able (v3.2 composer can cross-check Transition references
  the prior Conclusion).

### How slide_compose v3.2 uses the field

The composer reads `Transition from prior:` when authoring the
substory's first non-Q slot (typically the A-slide answering the
substory's question, or the first R-slide if there's no explicit
A-slide). It opens with a brief clause referencing the prior
arc's conclusion before stating this substory's claim. See
`slide_compose.v3.2_overlay.md` §"Arc transitions (D-087)" for
the composer-side rule.

The field is also used at the section_divider's prose body (the
sentence or two below the punchline) — the divider can preview
the bridge before the audience sees the first content slide.

### Anti-example pairs (v3.2)

**BAD** (S2 of an ibd deck where S1 concluded with the
51-target shortlist):

```
### S2 — Therapeutic tractability of the 51 targets

**Question:** Which of the 51 candidate targets are therapeutically tractable?
**Conclusion for next substory:** 5 Tier-A targets have engraftment-confirmed CD elevation.
**Punchline:** 5 of 51 targets are Tier-A.
# (Transition from prior is ABSENT — composer has no bridge to open S2 with.)
```

**GOOD:**

```
### S2 — Therapeutic tractability of the 51 targets

**Transition from prior:** S1 identified 51 candidate pathobiont targets across the E1 cohort. S2 asks which subset is therapeutically tractable — meeting both the engraftment-confirmation and CD-elevation thresholds for a clinical-pilot cocktail.

**Question:** Which of the 51 candidate targets are therapeutically tractable?
**Conclusion for next substory:** 5 Tier-A targets have engraftment-confirmed CD elevation.
**Punchline:** 5 of 51 targets are Tier-A.
```

## v3.2 Output format additions

The v3 Output format template (above) lists per-substory fields
in this order:

```
### S{N} — {short cluster name}

**Question:** {...}

**Conclusion for next substory:** {...}

**Punchline:** {...}

**Critical analyses covered:**
...
```

v3.2 inserts the `Transition from prior:` field FIRST (before
**Question:**), on substories S2..SN. The full template per
substory becomes:

```markdown
### S{N} — {short cluster name}

**Transition from prior:** {1-2 sentences — references S(N-1)'s Conclusion + names this substory's Question. OMIT this field entirely on the first substory.}

**Question:** {one sentence ≤25 words — the scientific question this substory answers}

**Conclusion for next substory:** {one sentence ≤25 words — the operative conclusion this substory establishes that hands a question forward to S(N+1); OMIT this field on the final substory}

**Punchline:** {one sentence — what does this slice prove? Should summarize Question + Conclusion as a single statement; this is the section_divider's `punchline` field}

**Critical analyses covered:**

- A1: {analysis name from plan inventory} — REPORT §X / notebook Y cell Z
- A3: {...}
- A5: {...}

**Cluster rationale:** {one paragraph about the analytical arc}

**Proposed slide budget:** {N content slides + 1 divider}

**Slide kinds anticipated** (slide_compose refines):

- (per v3 — section_divider/big_idea Q-slide, data_figure R-slides, claim_evidence C-slide, etc.)
```

The order matters: putting `Transition from prior:` FIRST makes
the substory's opening obvious to the slide_compose stage (it
reads top-down per substory). The Question still anchors the
substory's scientific intent; the Transition just contextualizes
where that question comes from in the deck's argument flow.

## v3.2 self-review pass (additive to v3's self-review checklist)

(All v1 + v3 self-review items above still apply. v3.2 adds:)

### Validator-blocking (v3.2)

- S1 does NOT have a `Transition from prior:` field (it's the
  deck's opener; nothing prior to transition from).
- Every substory after S1 has a `Transition from prior:` field.
- The Transition references the prior substory's
  `Conclusion for next substory:` (verbatim or paraphrased) +
  names this substory's question.
- Transitions are 1–2 sentences, not recaps; the audience just
  finished reading the prior substory.

### Coherence check (v3.2)

Walking S1 → SN: read each substory's `Transition from prior:`
in sequence. The transitions should read as a coherent narrative
spine — each transition picks up where the prior one left off.
If a transition jumps topic or repeats material from two
substories back, the substory ordering or clustering needs
revision.

## v3.2 anti-patterns (additive to v3's failure-mode catalog)

(v3 failure modes above all apply; v3.2 adds:)

- **Transition-as-recap.** The Transition field summarizes
  S(N-1)'s entire content rather than naming the operative
  prior-result + this-question. → Tighten to 1–2 sentences;
  reference S(N-1)'s `Conclusion for next substory:` directly
  (paraphrase is fine).
- **Transition-mismatched-handoff.** Transition references a
  prior result that doesn't appear in S(N-1)'s
  `Conclusion for next substory:`. → Either fix the Transition
  to match the actual handoff or fix the v3 Conclusion to name
  what S(N) actually builds on.
- **Transition-on-S1.** Transition field present on the first
  substory. → Remove; S1 opens the deck; absence is the correct
  signal.

## v3.2 inviolable rules (additive to v3's inviolable-rules list)

(v3 rules 3–5 above all apply. v3.2 adds:)

6. **v3.2:** every substory after S1 has a `**Transition from
   prior:**` field (1–2 sentences). The field is OMITTED on S1.
7. **v3.2:** the Transition field references the prior
   substory's `**Conclusion for next substory:**` (verbatim or
   paraphrased) — the Conclusion-to-Transition coupling is the
   load-bearing audit point.
