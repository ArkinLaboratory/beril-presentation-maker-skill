# --- v3 overlay (BERIL Presentation-Maker — Substory Design) ---

> **v3 (2026-05-26, v0.5.1 — concat overlay).** Everything ABOVE
> this overlay marker is the full `substory_design.v1.md` body and
> remains authoritative for clustering discipline, mode-capacity
> overflow protocol, tier-aware framing, escape hatches, and
> output protocol. This overlay ADDS the v0.5 content-discipline
> contract on top of v1:
>
> 1. **Substory Q/A/R/C contract** (D-071) — each substory MUST
>    name its scientific Question and (unless final) the
>    Conclusion-for-the-next-substory. `tools/check_substory_shape.py`
>    enforces presence + 25-word cap.
> 2. **Punchline derives from Question + Conclusion** (rather than
>    being a free-floating cluster headline).
> 3. **Cluster rationale tightens** to "the analytical arc the
>    listed analyses jointly tell," not encyclopedic per-analysis
>    description.
>
> **Output-format change.** The v1 "Output format (02_substories.md
> template)" section above must be SUPERSEDED by the v3 template
> below — v1's template lacks the **Question:** and **Conclusion
> for next substory:** lines that this overlay's validators
> require. When the v1 template and the v3 template conflict, use
> the **v3 template** (this overlay). Everything else in v1
> (clustering discipline, overflow protocol, capacity check, etc.)
> still applies unchanged.

## v3 contract specifics (D-071)

### The **Question:** field

- **Required on every substory.** Missing field → `check_substory_shape.py`
  emits `missing_question` finding at cascade Tier-1 P1.
- **≤25 words.** Audience must hold the question in working memory
  while reading 3–5 result slides; longer questions force
  re-reading. Over the cap → `question_too_long` finding.
- **Real scientific question, not topic.** "How does X affect Y?"
  or "Why does X happen?" — NOT "Methods for X" or "X validation".
  The question must be answerable by the substory's analyses.
- **Connects to the throughline.** Each substory's Question should
  be a sub-question of the throughline; together the substory
  Questions should partition the throughline's full claim.

### The **Conclusion for next substory:** field

- **Required on every non-final substory.** Missing on a non-final
  substory → `missing_conclusion` finding at Tier-1 P1.
- **OMITTED on the final substory.** The final substory's
  conclusion is the throughline's overall claim; no explicit
  handoff needed.
- **≤25 words.** Same audience-working-memory constraint as
  Question.
- **Acts as the handoff.** Phrase it as the *operative result*
  that motivates S(N+1)'s Question. E.g., "S1: We identified 51
  candidate targets" → "S2: Which of those 51 targets is
  therapeutically tractable?" The Conclusion + next Question
  together form a single narrative beat the audience traverses
  at the section_divider.
- **NOT a recap.** Don't restate the substory's analyses — name
  the one thing the audience should *carry forward*.

### Q/A/R/C slide-role mapping (advisory at substory_design time)

The substory's slide budget should reflect:

- **Q-slide** (substory opener): `section_divider` OR opening
  `big_idea`. The slide_compose stage will author the slide; this
  stage's job is to ensure the **Question** is stated clearly
  enough that the composer can title the Q-slide from it.
- **A-slide(s)** (analytical context): `methods_summary`,
  `workflow_diagram`, or `two_column_compare`. Optional if the
  analysis is straightforward.
- **R-slide(s)** (results): `data_figure`, `data_table`,
  `big_number`, or `two_column_compare`. At least one R-slide is
  required per substory.
- **C-slide** (substory closer): `claim_evidence` OR closing
  `big_idea`. The slide_compose stage will state the
  **Conclusion** there.

`check_substory_shape.py` enforces presence of Q + R + C slides
per substory at cascade Tier-1.

### Punchline (v1-compat field; kept)

The v1 `**Punchline:**` field remains in v3 for back-compat. It
now serves as the section_divider's `punchline` field (per v2
slide_compose's section_divider schema), summarizing
**Question:** + **Conclusion for next substory:** as a single
sentence. The section_divider's prose can elaborate; the
Punchline is the section's headline.

## v3 Output format (REPLACES v1's "Output format (02_substories.md template)" above)

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

**Question:** {one sentence ≤25 words — the scientific question this substory answers}

**Conclusion for next substory:** {one sentence ≤25 words — the operative conclusion this substory establishes that hands a question forward to S2; OMIT this field on the final substory}

**Punchline:** {one sentence — what does this slice prove? Should summarize Question + Conclusion as a single statement; this is the section_divider's `punchline` field}

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

(Same template per cluster. **Question:** of S2 should be a natural
extension of S1's **Conclusion for next substory:** — the handoff is
the load-bearing bridge.)

---
```

## v3 self-review pass (additive to v1's self-review checklist)

(All v1 self-review items above still apply. v3 adds:)

### Validator-blocking (v3)

- Every substory has a `**Question:**` field, ≤25 words.
- Every non-final substory has a `**Conclusion for next substory:**`
  field, ≤25 words. The final substory does NOT have this field.
- The first substory's Question is the natural opening of the
  throughline; the final substory's Conclusion (or its slide
  C-slide content) lands the throughline.
- Adjacent substories' Conclusion → Question handoffs are
  coherent: S1's Conclusion should make S2's Question feel
  natural.

### Anti-example pairs (v3)

**BAD:**
```
**Question:** Methods for E1 target identification.
**Conclusion for next substory:** We did the methods.
**Punchline:** Methods overview.
```

**GOOD:**
```
**Question:** Which of the 17,344 dark genes show evidence of conserved function?
**Conclusion for next substory:** 511 dark genes have both accessory conservation and strong fitness signal — the actionable target shortlist.
**Punchline:** 511 dark genes carry conserved-function evidence and define the actionable target list.
```

## v3 anti-patterns (additive to v1's failure-mode catalog)

(v1 failure modes above all apply; v3 adds:)

- **Topic-as-Question.** Question field reads "Methods for X" or
  "X overview" rather than a real scientific question. → Re-write
  as "How does X work?" or "Why does X happen?" or "Which X is
  best for Y?".
- **Conclusion-as-Recap.** Conclusion field restates what the
  substory's slides did. → Re-write as the *operative result*
  the next substory needs.
- **Handoff-Break.** S2's Question doesn't follow from S1's
  Conclusion. → Re-cluster substories so the analytical arc is
  continuous, OR re-write the Conclusion to actually motivate S2.

## v3 inviolable rules (additive to v1's inviolable-rules list)

(v1 rules above all apply. v3 adds:)

3. **v3:** every substory has `**Question:**` (≤25 words).
4. **v3:** every non-final substory has `**Conclusion for next
   substory:**` (≤25 words).
5. **v3:** the Q/Conclusion fields together form an analytical
   arc across substories — each Conclusion → next Question
   handoff is coherent.
