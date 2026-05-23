# Throughline

**Selected:** TL1 (carried verbatim from plan.v1 candidate; no user revision applied).

**Statement:** Ecotype-stratified microbiome analysis defines a state-dependent, hybrid phage-cocktail framework for Crohn's disease with concrete per-patient drafts

**Evidence map:**

| Sub-claim | Source | Strength |
|---|---|---|
| Four reproducible IBD ecotypes (E0/E1/E2/E3) stratify CD patients into biologically distinct groups | REPORT §"Finding 1" (NB01b K=4 consensus, cross-method ARI local max; 8,489 samples) | ⚠ partial — ecotype framework has real cross-study variance (NB04f LOSO ARI 0.113, range 0.000–0.282); usable but not bit-reproducible across studies |
| UC Davis CD patients span three ecotypes non-randomly (χ²=10.0, p=0.019) | REPORT §"Finding 2" (NB02 projection: E0 27%, E1 42%, E3 31%, E2 0%) | ✓ direct |
| Clinical covariates alone cannot assign ecotype within an all-CD cohort (AUC 0.80 but 41% patient agreement) | REPORT §"Finding 3" (NB03 minimal classifier collapses to IBD→E1) | ✓ direct |
| Six actionable Tier-A pathobionts emerge from confound-free within-ecotype × within-substudy meta-analysis | REPORT §"Finding 5c" (NB04e: E1 51 candidates meta-viable; NB05: 6 actionable at score ≥2.5) | ✓ direct |
| E1 Tier-A replicates at 88.2% sign concordance on independently-held-out HMP2 cohort | REPORT §"Finding 5f" (NB04h: 45/51 E1 candidates CD↑ in both cohorts) | ✓ direct |
| E3 Tier-A is single-study (HallAB_2017 only); provisional | REPORT §"Finding 5c" + Limitations §"E3 Tier-A" | ⚠ partial — needs replication; HMP2 has only 10 E3 subjects |
| Pathobionts form a single co-occurrence module per ecotype (NB06 H2d) | REPORT §"Finding 5h" (4–5 of 6 actionable Tier-A in one module per subnet) | ✓ direct |
| 3-layer phage-evidence stack (NB12 + NB13 + NB14) yields 5-phage E. coli AIEC cocktail at 95% strain coverage | REPORT §"Pillar 4 deliverables" (NB13 greedy set-cover on 96 phages × 188 strains) | ✓ direct |
| Three of six Tier-A targets are in phage GAP (H. hathewayi, F. plautii) or temperate-only (M. gnavus) | REPORT §"Pillar 4 closure synthesis" (NB12 4-class stratification) | ✓ direct |
| Pure phage cocktail is structurally infeasible for dominant E1 ecotype; hybrid 3-strategy framework required | REPORT §"Pillar 5 Principle 1" (NB15: 3 GAP species require non-phage alternatives) | ✓ direct |
| 14 of 23 UC Davis patients (61%) receive concrete phage cocktail drafts | REPORT §"Finding 15" (NB15 + NB17 per-patient master table) | ✓ direct |
| Patient 6967 shows E1→E3 ecotype drift with M. gnavus 14× expansion; cocktail Jaccard 0.60 between visits | REPORT §"Finding 16" (NB16 longitudinal) | ⚠ partial — n=1 longitudinal trajectory; ecotype call confidence moderate (0.64 / 0.41) |
| Five state-dependent dosing rules + clinical workflow (ecotype re-test / M. gnavus qPCR proxy) | REPORT §"Novel Contribution #24" (NB16 §5) | ⚠ partial — n=1 trajectory; qPCR proxy is a hypothesis, not validated assay |

**Weakness inventory:**

- Gap: E3 Tier-A list is single-study evidence (HallAB_2017); only 10 of 130 HMP2 subjects in E3, so HMP2 cannot rescue E3 replication. 31% of UC Davis patients are E3 — their cocktail recommendations inherit this provisional status.
- Gap: Three of six highest-scoring pathobionts (H. hathewayi 4.0, M. gnavus 3.8, F. plautii 3.3) have no lytic phage — the "concrete cocktail" for E1 patients is actually a hybrid framework mixing phages + non-phage alternatives. The paper must honestly frame this as a design-template, not a ready-to-deploy cocktail.
- Rebuttal a sharp reviewer would offer: "Ecotype framework has LOSO ARI 0.113; calling these 'reproducible ecotypes' overstates the evidence. Your patient-stratification premise rests on a framework whose cluster boundaries shift substantially across training-set sub-studies." Counter: NB04h shows the operational Tier-A replicates at 88.2% despite framework variance — framework stability and operational-claim replication are distinct properties (Novel Contribution #11).
- Rebuttal: "n=23 UC Davis patients is too small to generalize per-patient cocktail recommendations." Counter: the paper's contribution is the framework + templates, not the specific per-patient assignments; generalization requires multi-center validation (acknowledged).
- Methodological caveat: Kaiju↔MetaPhlAn3 classifier mismatch in UC Davis projection (LDA robust, GMM fragile); Tier-A presence calls on UC Davis have lower confidence than CMD analyses.
- Methodological caveat: State-dependent dosing rule based on n=1 longitudinal trajectory (patient 6967). The 5-fold M. gnavus qPCR threshold is hypothesis, not validated.

**What this paper would NOT include if this is chosen:**

- The NB04 failure arc and rigor-repair methodology (NB04→NB04b→c→d→e) — reduced to brief Methods mention; the generalizable methodological lessons (feature leakage, cMD substudy nesting) → appendix or separate methods paper
- Detailed Pillar 3 mechanism narratives (iron-acquisition 6-line convergence, bile-acid 7α-dehydroxylation network) — summarized in Results but not the paper's central thread; molecular mechanism detail → supplement
- NB07d CC1 multi-omics joint factor (r=0.96) — mentioned as corroborative but not foregrounded
- Kumbhari strain-adaptation methodology (NB10a H3b) — mentioned for F. plautii informative null only
- Serology-pathobiont integration (NB11 H3e) — partial result, likely supplement only
- Cross-cohort metabolomics replication detail (NB09b) — summarized; theme-level replication stats go in supplement
- Category-schema methodology lesson (NB07 v1.7→v1.8 reversal) — appendix or separate paper
