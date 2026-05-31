# --- v3.3 overlay (BERIL Presentation-Maker — Substory Design) ---

> **v3.3 (2026-05-31, v0.8 Tier C / D-095 — clean overlay on v1;
> retires v3 + v3.2 substory_design overlays as default).** This
> overlay stacks ON v1 directly. The concat order is:
>
>     cat substory_design.v1.md \
>         substory_design.v3.3_overlay.md
>
> v3.3 is NOT stacked on `substory_design.v3_overlay.md` or
> `substory_design.v3.2_overlay.md`. It consolidates the v3
> Q/A/R/C contract (D-071) + the v3.2 transition_from_prior
> field (D-087) into ONE unified template with all required
> fields named explicitly.
>
> **Why a clean rewrite, not v3.2-with-fixes** (v0.7 Tier-I
> finding 4 + D-092): the v3 → v3.1 → v3.2 substory_design
> chain hit a recency-bias displacement bug live. The v3.2
> overlay's example block re-showed the v3 fields correctly
> but lacked v3's explicit "this template SUPERSEDES v1"
> language. LLMs weight prompt-tail heavily; the v3.2
> example became authoritative + the v3-required fields not
> explicitly restated got silently dropped in live runs (4
> substories on ibd v3.2 had ZERO Conclusion-for-next or
> Transition-from-prior fields despite both contracts being
> in the upstream overlays). v3.3 prevents this by
> consolidating into ONE template that names every required
> field explicitly + carries the supersedes-clause v3 had.
>
> **What v3.3 ADDS on top of v1** (combined from D-071 + D-087):
>
> 1. **Substory Q/A/R/C contract** (from v3 / D-071) — each
>    substory MUST name its scientific Question + (unless
>    final) the Conclusion-for-the-next-substory. Punchline
>    derives from Question + Conclusion.
> 2. **`Transition from prior:` field** (from v3.2 / D-087) —
>    every substory after S1 MUST include a brief field
>    summarizing what claim from the prior substory this one
>    builds on. The composer (slide_compose v3.2 +) reads this
>    field when authoring the substory's first non-Q slot.
> 3. **Cluster rationale tightening** (from v3) — "the
>    analytical arc the listed analyses jointly tell," not
>    encyclopedic per-analysis description.
>
> **Output-format supersede clause.** The v1 "Output format
> (02_substories.md template)" section MUST be SUPERSEDED by
> the v3.3 template below — v1's template lacks the
> Transition / Question / Conclusion lines that this overlay
> requires. When the v1 template and the v3.3 template
> conflict, USE THE v3.3 TEMPLATE. Everything else in v1
> (clustering discipline, overflow protocol, mode-capacity
> check, escape hatches) still applies unchanged.

## v3.3 contract specifics

### The **Question:** field (required on every substory)

- **Required on EVERY substory.** Missing field →
  `check_substory_shape.py` emits `missing_question` finding
  at cascade Tier-1 P1.
- **≤25 words.** Audience holds the question in working
  memory while reading 3–5 result slides; longer questions
  force re-reading. Over the cap → `question_too_long`
  finding.
- **Real scientific question, not topic.** "How does X
  affect Y?" / "Why does X happen?" / "Which X is best for
  Y?" — NOT "Methods for X" or "X validation". The question
  must be answerable by the substory's analyses.
- **Connects to the throughline.** Each substory's Question
  should be a sub-question of the throughline; together the
  substory Questions should partition the throughline's full
  claim.

### The **Conclusion for next substory:** field (required on every non-final substory)

- **Required on EVERY non-final substory.** Missing on a
  non-final substory → `missing_conclusion` finding at
  Tier-1 P1.
- **OMITTED on the final substory.** The final substory's
  conclusion is the throughline's overall claim; no
  explicit handoff needed. Do NOT emit this field on the
  last substory in the list.
- **≤25 words.** Same audience-working-memory constraint
  as Question.
- **Acts as the handoff.** Phrase as the *operative result*
  that motivates S(N+1)'s Question. E.g., "S1: We
  identified 51 candidate targets" → "S2: Which of those 51
  is therapeutically tractable?" The Conclusion + next
  Question together form a single narrative beat the
  audience traverses at the section_divider.
- **NOT a recap.** Don't restate the substory's analyses —
  name the one thing the audience should *carry forward*.

### The **Transition from prior:** field (required on every substory after S1)

- **Required on EVERY substory after S1.** Missing on a
  non-first substory → check_substory_shape.py emits
  `missing_transition_from_prior` finding at Tier-1 P1.
- **OMITTED (not "null", not empty) on S1.** S1 opens the
  deck; there is no prior arc to transition from. Do NOT
  emit this field on the first substory.
- **1–2 sentences.** Brief — this is a transition, not a
  recap. The full content of S(N-1) is on its slides; the
  audience just finished reading them.
- **Names the prior-arc result + this-arc question.**
  Pattern: *"S(N-1) established <prior result>. S(N) asks:
  <this substory's question>."* The first sentence names
  what the audience just learned; the second names what
  this substory does next.
- **Anchors to `Conclusion for next substory:` (the
  v3.3 field two-rules-above).** If S(N-1) has
  `Conclusion for next substory: We identified 51 candidate
  targets`, then S(N)'s `Transition from prior:` should
  build on that — *"With the 51-target shortlist from S1
  in hand, S2 asks which subset is therapeutically
  tractable."* The Conclusion → Transition coupling makes
  the handoff audit-able.

### Q/A/R/C slide-role mapping (advisory at substory_design time)

The substory's slide budget should reflect:

- **Q-slide** (substory opener): `section_divider` OR
  opening `big_idea`. The slide_compose stage will author
  the slide; this stage's job is to ensure the
  **Question** is stated clearly enough that the composer
  can title the Q-slide from it.
- **A-slide(s)** (analytical context): `methods_summary`,
  `workflow_diagram`, or `two_column_compare`. Optional if
  the analysis is straightforward.
- **R-slide(s)** (results): `data_figure`, `data_table`,
  `big_number`, or `two_column_compare`. At least one
  R-slide is required per substory.
- **C-slide** (substory closer): `claim_evidence` OR
  closing `big_idea`. The slide_compose stage will state
  the **Conclusion** there.

`check_substory_shape.py` enforces presence of Q + R + C
slides per substory at cascade Tier-1.

### Punchline (v1-compat field; kept)

The v1 `**Punchline:**` field remains in v3.3 for
back-compat. It now serves as the section_divider's
`punchline` field (per v2 slide_compose's section_divider
schema), summarizing **Question:** + **Conclusion for next
substory:** as a single sentence. The section_divider's
prose can elaborate; the Punchline is the section's
headline.

## v3.3 Output format (REPLACES v1's "Output format (02_substories.md template)" above)

**THIS IS THE AUTHORITATIVE OUTPUT TEMPLATE.** When you
generate `02_substories.md`, follow THIS template exactly.
The v1 template above is superseded; ignore its field list
and use the per-substory shape shown here. Every field
listed below as "required" MUST appear in the output for
the substories where it applies.

```markdown
# Substory clusters — `{project_id}` / talk mode `{mode}`

**Throughline:** {chosen TL claim, one sentence}
**Tier:** {STRONG | THIN | EXPLORATORY}
**Mode budget:** {min}-{max} slides per SPEC §5

## Mode-capacity check

- **Boilerplate slides:** {N} (title + 1 divider per substory + cross_tenant_integration + acknowledgments + references; qa_anticipated optional)
- **Per-substory content target:** {3 for talk-30/45, 2 for talk-15, 1 for lightning-5}
- **Required slides:** {boilerplate + ∑ per-substory content}
- **Mode max:** {max}

**Capacity verdict:** `fits` | `overflow` | `under-utilized`

## Substory clusters

### S1 — {short cluster name}

**Question:** {required; one sentence ≤25 words — the scientific question this substory answers}

**Conclusion for next substory:** {required if non-final; one sentence ≤25 words — the operative conclusion this substory establishes that hands a question forward to S2; OMIT this field entirely on the FINAL substory}

**Punchline:** {required; one sentence — what does this slice prove? Should summarize Question + Conclusion as a single statement; this is the section_divider's `punchline` field}

**Critical analyses covered:**

- A1: {analysis name from plan inventory} — REPORT §X / notebook Y cell Z
- A3: {...}
- A5: {...}

**Cluster rationale:** {one paragraph about the *analytical arc* — how the listed analyses jointly answer the **Question:** and arrive at the **Conclusion for next substory:**. NOT an encyclopedic per-analysis description; the point is the story the analyses tell *as a sequence*, not what each analysis individually shows.}

**Proposed slide budget:** {N content slides + 1 divider} (per SPEC §6.2)

**Slide kinds anticipated** (slide_compose refines):

- `section_divider` OR `big_idea` — the **Q-slide** (substory opener; names the Question; SPEC §6.2 non-negotiable)
- `data_figure` × {N} (R-slides — results)
- `data_table` × {N} (R-slides if comparison tables apply)
- `big_number` (R-slide if a single headline quantity drives the substory)
- `workflow_diagram` (A-slide if the analytical method is diagrammatic)
- `methods_summary` (A-slide if methods need explicit listing)
- `claim_evidence` (C-slide — closing claim that states the Conclusion-for-next-substory; SPEC §6.2 closing slot)

---

### S2 — {short cluster name}

**Transition from prior:** {REQUIRED on S2..SN; 1-2 sentences — references S1's Conclusion + names this substory's Question. OMIT this field entirely on S1.}

**Question:** {required; one sentence ≤25 words}

**Conclusion for next substory:** {required if non-final; one sentence ≤25 words}

**Punchline:** {required; one sentence — summarizes Question + Conclusion}

**Critical analyses covered:**

- A2: {...}
- A4: {...}

**Cluster rationale:** {one paragraph about the analytical arc}

**Proposed slide budget:** {N content slides + 1 divider}

**Slide kinds anticipated** (slide_compose refines):

- (per the slide-role mapping above)

---

### S{N} — {short cluster name} (FINAL substory)

**Transition from prior:** {required on this final substory if N>1; 1-2 sentences}

**Question:** {required}

(**Conclusion for next substory:** OMITTED — this is the final substory; no next-substory exists to hand off to)

**Punchline:** {required}

**Critical analyses covered:**

- ...

**Cluster rationale:** {one paragraph}

**Proposed slide budget:** {N content slides + 1 divider}

**Slide kinds anticipated** (slide_compose refines):

- (per the slide-role mapping above)
```

### Field requirements summary (canonical reference)

For every substory in the output:

| Field | S1 | S2..S(N-1) | S(N) (final) |
|---|---|---|---|
| `**Transition from prior:**` | OMIT | REQUIRED | REQUIRED if N>1 |
| `**Question:**` | REQUIRED | REQUIRED | REQUIRED |
| `**Conclusion for next substory:**` | REQUIRED | REQUIRED | OMIT |
| `**Punchline:**` | REQUIRED | REQUIRED | REQUIRED |
| `**Critical analyses covered:**` | REQUIRED | REQUIRED | REQUIRED |
| `**Cluster rationale:**` | REQUIRED | REQUIRED | REQUIRED |
| `**Proposed slide budget:**` | REQUIRED | REQUIRED | REQUIRED |
| `**Slide kinds anticipated**` | REQUIRED | REQUIRED | REQUIRED |

If a single substory (N=1), the substory is both S1 (omit
Transition) and final (omit Conclusion).

## v3.3 self-review pass (additive to v1's self-review checklist)

(All v1 self-review items above still apply. v3.3 adds:)

### Validator-blocking (v3.3)

- Every substory has a `**Question:**` field, ≤25 words.
- Every non-final substory has a `**Conclusion for next
  substory:**` field, ≤25 words. The final substory does
  NOT have this field.
- Every substory after S1 has a `**Transition from
  prior:**` field, 1-2 sentences. S1 does NOT have this
  field.
- The Transition references the prior substory's
  `**Conclusion for next substory:**` (verbatim or
  paraphrased).
- The first substory's Question is the natural opening of
  the throughline; the final substory's Conclusion (or its
  slide C-slide content) lands the throughline.
- Adjacent substories' Conclusion → Question handoffs are
  coherent: S1's Conclusion should make S2's Question feel
  natural.

### Coherence check (v3.3)

Walking S1 → SN: read each substory's `Transition from
prior:` in sequence (S2..SN). The transitions should read
as a coherent narrative spine — each transition picks up
where the prior one left off. If a transition jumps topic
or repeats material from two substories back, the substory
ordering or clustering needs revision.

### Anti-example pairs (v3.3)

**BAD (drops Conclusion + Transition):**
```
### S2 — Therapeutic tractability
**Question:** Which targets are therapeutically tractable?
**Punchline:** 5 of 51 targets are Tier-A.
```

**GOOD (all required fields):**
```
### S2 — Therapeutic tractability
**Transition from prior:** S1 identified 51 candidate pathobiont targets across the E1 cohort. S2 asks which subset is therapeutically tractable.
**Question:** Which targets are therapeutically tractable?
**Conclusion for next substory:** 5 Tier-A targets have engraftment-confirmed CD elevation.
**Punchline:** 5 of 51 targets are Tier-A.
```

**BAD (puts Transition on S1):**
```
### S1 — Ecotype identification
**Transition from prior:** (no prior substory)
**Question:** ...
```

**GOOD (S1 omits Transition entirely):**
```
### S1 — Ecotype identification
**Question:** ...
```

## v3.3 anti-patterns (additive to v1's failure-mode catalog)

(v1 failure modes above all apply; v3.3 adds:)

- **Field-drop.** A substory that omits required fields
  (Question on any substory; Conclusion on a non-final
  substory; Transition on a non-first substory). The
  v0.7 Tier-I bug class this overlay was specifically
  designed to prevent. → Use the v3.3 template; check
  the field-requirements table above before emitting.
- **Topic-as-Question.** Question field reads "Methods for
  X" or "X overview" rather than a real scientific
  question. → Re-write as "How does X work?" or "Why does
  X happen?" or "Which X is best for Y?".
- **Conclusion-as-Recap.** Conclusion field restates what
  the substory's slides did. → Re-write as the
  *operative result* the next substory needs.
- **Handoff-Break.** S2's Question doesn't follow from
  S1's Conclusion. → Re-cluster substories so the
  analytical arc is continuous, OR re-write the
  Conclusion to actually motivate S2.
- **Transition-as-recap.** The Transition field
  summarizes S(N-1)'s entire content rather than naming
  the operative prior-result + this-question. → Tighten
  to 1–2 sentences; reference S(N-1)'s
  `Conclusion for next substory:` directly (paraphrase
  is fine).
- **Transition-mismatched-handoff.** Transition references
  a prior result that doesn't appear in S(N-1)'s
  `Conclusion for next substory:`. → Either fix the
  Transition to match the actual handoff OR fix the
  Conclusion to name what S(N) actually builds on.
- **Transition-on-S1.** Transition field present on the
  first substory. → Remove; S1 opens the deck; absence
  is the correct signal.

## v3.3 inviolable rules (additive to v1's inviolable-rules list)

(v1 rules above all apply. v3.3 adds:)

3. **v3.3:** every substory has `**Question:**` (≤25
   words).
4. **v3.3:** every non-final substory has `**Conclusion
   for next substory:**` (≤25 words). The final substory
   does NOT have this field.
5. **v3.3:** the Q/Conclusion fields together form an
   analytical arc across substories — each Conclusion →
   next Question handoff is coherent.
6. **v3.3:** every substory after S1 has a
   `**Transition from prior:**` field (1–2 sentences). The
   field is OMITTED on S1.
7. **v3.3:** the Transition field references the prior
   substory's `**Conclusion for next substory:**` (verbatim
   or paraphrased) — the Conclusion-to-Transition coupling
   is the load-bearing audit point.
