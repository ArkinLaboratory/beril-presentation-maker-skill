# Deck outline (substory clusters) — `ibd_phage_targeting` / talk mode `talk-30`

**Throughline:** Ecotype-stratified microbiome analysis defines a state-dependent, hybrid phage-cocktail framework for Crohn's disease with concrete per-patient drafts
**Tier:** STRONG
**Mode budget:** 20–30 slides per SPEC §5

## Deck-level spec

**Register:** Audience is translational microbiome scientists and clinical gastroenterologists comfortable with differential-abundance statistics but not necessarily with ecotype methodology. Every section opens with a declarative claim ("we show that…") and closes on the implication for the next clinical step. Partial-evidence claims (A1, A6, A12) carry in-slide hedges — "provisional," "single-study," "n=1 trajectory" — rather than deferring caveats to a limitations slide. Punchline cadence: framework → targets → gaps → prescriptions. Hedge discipline: the ecotype framework's cross-study variance (LOSO ARI 0.113) is acknowledged in S1 and never re-opened; the E3 provisional status is acknowledged in S2 and carried forward as a scoping constraint in S4.

**Arc:** Ecotypes make confound-free target discovery possible (S1→S2); target discovery reveals that three of the six top pathobionts cannot be killed with existing phage, which forces a hybrid design rather than a cocktail (S2→S3); the hybrid design, when applied per-patient, produces concrete prescriptions for 61% of the cohort and a longitudinal dosing framework for the rest (S3→S4). Each section earns the next: without S1 there is no stratification, without S2 there are no targets, without S3 the prescriptions would over-promise, without S4 the clinical translation is incomplete.

**Image budget:** ≤2 AI concept illustrations deck-wide (one admissible in S1 for ecotype schematic, one admissible in S4 for clinical-workflow schematic). Data and procedural diagrams are uncapped — governed by the data, not a budget.

## Mode-capacity check

- **Boilerplate slides:** 8 (title + 4 dividers [one per substory] + cross_tenant_integration + acknowledgments + references)
- **Per-substory content target:** 3 for talk-30
- **Required slides:** 8 + 13 = 21
- **Mode max:** 30

**Capacity verdict:** `fits`

## Substory clusters

### S1 — Ecotyping is required, not optional

**Punchline:** Metagenomic ecotyping is required — clinical covariates cannot stratify CD patients

**Critical analyses covered:**

- A1: Four reproducible IBD ecotypes (E0/E1/E2/E3) — REPORT §"Finding 1" / NB01b consensus, NB04f LOSO
- A2: UC Davis CD patients span three ecotypes non-randomly — REPORT §"Finding 2" / NB02 projection
- A3: Clinical covariates alone cannot assign ecotype within an all-CD cohort — REPORT §"Finding 3" / NB03 minimal classifier

**Budget:** 3 content slides + 1 divider

**Headline slot:** C-021 — χ²(3)=10.0, p=0.019; UC Davis spans E0/E1/E3 non-randomly (the operative proof that stratification is non-trivial and patient-relevant)

**Transition in:** (deck opener — no prior section)

**Transition out:** Ecotypes are real and non-randomly occupied by UC Davis patients — but since metagenomics is required, the question becomes whether ecotype stratification actually yields distinct, replicable pathobiont targets worth the effort.

**Scoped figures:** (none)

**Cluster rationale:** A1, A2, and A3 jointly establish the stratification premise: ecotypes exist at scale (A1), UC Davis patients distribute across them non-randomly (A2), and clinical data alone cannot substitute for metagenomics to make ecotype calls (A3). All three are required to justify the ecotype-first design of the downstream pillars. A1 carries a ⚠ partial evidence flag (LOSO ARI 0.113, cross-study variance real); A2 and A3 are ✓ direct. The mixed confidence is unavoidable — the ecotype framework is the enabling premise of the talk, and its limitations belong here, not in a separate caveats slide. The composer should hedge A1 in-slide ("a usable framework, not bit-reproducible across studies") rather than overselling cross-study stability.

**Noted exclusion (from throughline's "What this talk would NOT include"):** The NB04 failure arc and rigor-repair methodology (NB04→NB04b→c→d→e) are not a substory of their own; they are reduced to a brief Methods mention and are not the talk's central thread.

**Slide kinds anticipated** (slide_compose refines):

- section_divider (substory opener; SPEC §6.2 — non-negotiable)
- big_number (C-021: χ²=10.0, p=0.019)
- claim_evidence × 2 (A1 with hedged ecotype-framework summary; A3 classifier-collapse evidence)

---

### S2 — Six confound-free pathobionts replicate across cohorts

**Punchline:** Confound-free within-ecotype meta-analysis yields six actionable pathobionts that replicate externally

**Critical analyses covered:**

- A4: Six actionable Tier-A pathobionts from confound-free meta-analysis — REPORT §"Finding 5c" / NB04e candidates; NB05 actionable set
- A5: E1 Tier-A replicates at 88.2% sign concordance on held-out HMP2 — REPORT §"Finding 5f" / NB04h cross-cohort
- A6: E3 Tier-A is single-study and provisional — REPORT §"Finding 5c" + Limitations §"E3 Tier-A" / NB04e E3 cell
- A7: Pathobionts form a single co-occurrence module per ecotype — REPORT §"Finding 5h" / NB06 H2d

**Budget:** 4 content slides + 1 divider

**Headline slot:** C-012 — 88.2% Tier-A sign concordance on held-out HMP2 (45/51 E1 candidates CD↑ in both cohorts) (the section's strongest replicated result and the primary rebuttal to the "small discovery cohort" objection)

**Transition in:** S1 closed on the necessity of metagenomics — now answer the pay-off question: does ecotype stratification actually produce distinct, externally-validated targets, or does rigor-controlled analysis collapse to the same list a pooled analysis would give?

**Transition out:** Six targets are validated — but not all six are equally tractable with phage; the next section maps which targets can be killed with existing lytic phage and which require non-phage alternatives.

**Scoped figures:** (none)

**Cluster rationale:** A4–A7 jointly establish the target-discovery argument: rigorous design (within-ecotype × within-substudy) identifies six targets (A4); the E1 list is externally validated at high sign concordance (A5); the E3 list is provisional and scoped accordingly (A6); all six form a co-occurrence module, justifying a multi-target approach (A7). A5 is the rebuttal evidence against the sharpest anticipated critique (LOSO ARI 0.113 → "the ecotype framework is unstable, therefore the targets are unstable") — composer should draw the distinction explicitly: framework stability and operational-claim replication are separate properties. A6 is ⚠ partial and must be hedged in-slide: "E3 Tier-A is single-study; 31% of UC Davis patients are E3 and their recommendations inherit this provisional status."

**Slide kinds anticipated** (slide_compose refines):

- section_divider (substory opener; SPEC §6.2 — non-negotiable)
- big_number (C-012: 88.2% external replication)
- claim_evidence × 2 (A4: six-target scoring table summary; A7: co-occurrence module structure)
- methods_summary × 1 (confound-free within-ecotype × within-substudy design rationale — this is novel enough to warrant a slide)

---

### S3 — Phage gaps force a hybrid, not a pure cocktail

**Punchline:** Phage gaps in three top targets make a pure phage cocktail infeasible

**Critical analyses covered:**

- A8: A 3-layer phage-evidence stack yields a 5-phage E. coli AIEC cocktail at 95% strain coverage — REPORT §"Pillar 4 deliverables" / NB13 set-cover
- A9: Three of six Tier-A targets have no lytic phage — REPORT §"Pillar 4 closure synthesis" / NB12 4-class stratification
- A10: A pure phage cocktail is infeasible for the dominant E1 ecotype; a hybrid framework is required — REPORT §"Pillar 5 Principle 1" / NB15

**Budget:** 3 content slides + 1 divider

**Headline slot:** C-003 — 5-phage E. coli AIEC cocktail covering 95% of 188 PhageFoundry-tested strains (the section's concrete positive deliverable; the gap finding is the structural argument, but the cocktail is the memorable number)

**Transition in:** S2 closed on six validated targets — now map which of those six can actually be addressed with phage and which have coverage gaps that change the design from a cocktail to a hybrid framework.

**Transition out:** The targetability landscape is mapped — a 5-phage E. coli cocktail works, but three top-scoring targets require non-phage alternatives; now apply this hybrid design per-patient to the UC Davis cohort.

**Scoped figures:** (none)

**Cluster rationale:** A8, A9, and A10 jointly establish the targetability argument: the 3-layer phage-evidence stack produces a concrete E. coli cocktail at high strain coverage (A8); systematic 4-class stratification reveals that two of the highest-scoring targets (H. hathewayi 4.0, F. plautii 3.3) are in the phage GAP and M. gnavus (3.8) is temperate-only (A9); taken together these gaps make a pure phage cocktail structurally infeasible for the dominant E1 ecotype (A10). All three are ✓ direct. The A8 positive result (95% E. coli coverage) should lead; the A9/A10 gap finding should follow as the honest constraint that drives the hybrid-framework design. Composer should NOT frame this as a failure — the hybrid framework is the paper's novel contribution, not a fallback.

**Slide kinds anticipated** (slide_compose refines):

- section_divider (substory opener; SPEC §6.2 — non-negotiable)
- big_number (C-003: 95% strain coverage, 5-phage cocktail)
- claim_evidence × 1 (A9: 4-class stratification of all six targets by phage availability)
- claim_evidence × 1 (A10: hybrid 3-strategy framework — direct phage / alternative therapy / limited or engineered)

---

### S4 — 61% of patients get concrete cocktail drafts with dosing rules

**Punchline:** 61% of UC Davis patients receive concrete cocktail drafts with state-dependent dosing rules

**Critical analyses covered:**

- A11: 14 of 23 UC Davis patients (61%) receive concrete cocktail drafts — REPORT §"Finding 15" / NB15 + NB17 master table
- A12: Longitudinal ecotype drift motivates five state-dependent dosing rules — REPORT §"Finding 16" + §"Novel Contribution #24" / NB16 longitudinal

**Budget:** 3 content slides + 1 divider

**Headline slot:** C-005 — 14/23 patients (61%) receive concrete phage cocktail drafts (the section's direct patient-count deliverable; most decision-relevant number for a clinical audience)

**Transition in:** S3 closed on the hybrid framework design — now apply it: which UC Davis patients get a concrete phage-draft today, and what does ecotype drift mean for dosing over time?

**Transition out:** (deck close — no hand-off)

**Scoped figures:** (none)

**Cluster rationale:** A11 and A12 jointly close the clinical-translation arc: the per-patient master table applies the hybrid framework to all 23 patients and delivers concrete drafts to 61% (A11); the single longitudinal patient (6967) grounds the five state-dependent dosing rules and the M. gnavus qPCR proxy (A12). A11 is ✓ direct; A12 is ⚠ partial (n=1 trajectory; qPCR proxy is a hypothesis). Composer must hedge A12 in-slide: "based on a single longitudinal trajectory; the qPCR proxy is a hypothesis, not a validated assay." The 39% of patients without a concrete draft (E0 limited targets; E3 provisional-only) also belongs in this section as an honest accounting of the framework's current scope — it is not a liability but a research roadmap item.

**Slide kinds anticipated** (slide_compose refines):

- section_divider (substory opener; SPEC §6.2 — non-negotiable)
- big_number (C-005: 61% / 14 of 23 patients)
- claim_evidence × 1 (A11: per-ecotype cocktail strategy distribution with patient counts)
- claim_evidence × 1 (A12: patient 6967 E1→E3 drift, M. gnavus 14× expansion, 5 dosing rules — hedged for n=1)

---
