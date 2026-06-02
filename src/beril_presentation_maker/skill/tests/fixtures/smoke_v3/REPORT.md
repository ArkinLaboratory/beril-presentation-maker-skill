# Test Project — Smoke v3 Fixture

A minimal REPORT.md used by `tools/smoke_v3_prompt.py` to exercise
the v3 concatenated prompts. The content is deliberately small
(one finding, two numbers) so the smoke costs ≤ ~$0.30 per run.

## §Finding 1 — Three reproducible clusters

We analyzed 100 samples using K-means clustering with K=3. The
clustering reproduces across bootstrap resamples (Adjusted Rand
Index 0.91 over 1,000 bootstraps; baseline=0.05 for K=3 under
random labels). Each cluster maps to a distinct biological
gradient.

The clustering is not deterministic in absolute label assignment,
but the partition structure is stable.

**Numbers cited:**
- 100 samples
- K=3 clusters
- Adjusted Rand Index 0.91 over 1,000 bootstraps
- ARI baseline 0.05 for random labels

## §Finding 2 — Cluster-3 enrichment for biomarker X

Cluster 3 (n=34) is significantly enriched for biomarker X
(Fisher's exact p=0.003 vs the other two clusters pooled; effect
size OR=4.7, 95% CI [1.7, 13.1]).

This is the operative finding for follow-up.
