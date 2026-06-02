# Substory clusters — `smoke_v3_fixture` / talk mode `talk-15`

**Throughline:** TL1 — Three reproducible clusters in the test corpus identify Cluster 3 as the biomarker-X-enriched target for follow-up.
**Tier:** STRONG
**Mode budget:** 10-15 slides per SPEC §5

## Mode-capacity check

- **Boilerplate slides:** 5
- **Per-substory content target:** 2
- **Required slides:** 9
- **Mode max:** 15

**Capacity verdict:** `fits`

## Substory clusters

### S1 — Cluster 3 carries the biomarker signal

**Question:** Which of the three reproducible clusters carries the biomarker-X enrichment that motivates follow-up?

**Punchline:** Cluster 3 is enriched for biomarker X with effect size OR=4.7, identifying it as the follow-up target.

**Critical analyses covered:**

- A1: K=3 clustering with bootstrap stability — REPORT §Finding 1
- A2: Cluster 3 enrichment for biomarker X — REPORT §Finding 2

**Cluster rationale:** The bootstrap-stable K=3 partition (ARI 0.91) gives reproducible clusters; Cluster 3 shows significant biomarker-X enrichment (Fisher p=0.003, OR=4.7) which is the operative finding that motivates downstream work.

**Proposed slide budget:** 3 content slides + 1 divider

**Slide kinds anticipated** (slide_compose refines):

- `section_divider` — Q-slide (names the Question)
- `big_number` (R-slide for the OR=4.7 effect size)
- `data_figure` (R-slide for the clustering bootstrap)
- `claim_evidence` (C-slide closing on Cluster-3 as the target)
