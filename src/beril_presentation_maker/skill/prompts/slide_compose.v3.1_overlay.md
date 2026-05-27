# --- v3.1 overlay (BERIL Presentation-Maker — Slide Compose) ---

> **v3.1 (2026-05-27, v0.6 Tier A — new file; v3 overlay
> remains via `--prompts-version v3`).** This overlay stacks ON
> TOP of `slide_compose.v3_overlay.md` (which itself stacks on
> `slide_compose.v2.md`). The concat order is:
>
>     cat slide_compose.v2.md \
>         slide_compose.v3_overlay.md \
>         slide_compose.v3.1_overlay.md
>
> All v3 contracts (D-071 Q/A/R/C role, D-072 register discipline,
> the corrected per-layout field names from D-077) remain in
> force. This overlay ADDS one obligation:
>
> 1. **Figure-utilization contract** (D-080) — every substory's
>    R-slides MUST use the curated figures available for that
>    substory's analyses. The figure is the slide's principal
>    evidence; you place it on a `data_figure` slide, not as a
>    decorative addition to a `claim_evidence` text slide.
>
> Authoritative source: D-080 (figure-utilization contract);
> Adam-rubric pin from D-079: *"every arc should back a claim
> or finding by relevant figure if possible."*

## v3.1 failure modes ADDED on top of v3

(v3's failure modes — register leakage, arc-role drift — all
still apply. v3.1 adds one.)

- **Figure under-use.** A substory whose analyses cite a curated
  figure (in `CURATED_FIGURES_PATH`) but whose composed R-slides
  use text-only layouts (`claim_evidence` bullets) instead of a
  `data_figure` slide pointing at that curated figure. The
  audience hears the claim but sees no evidence; the curated
  figure stays unused on disk. v0.6
  `tools/check_figure_provenance.py` emits cascade Tier-1 P12
  soft-warnings on figure under-use; this overlay is the
  upstream cure.

## v3.1 contract specifics — Figure-utilization (D-080)

The composer reads `CURATED_FIGURES_PATH` (the mode-bounded
shortlist at `working/curated_figures.md`). Each entry lists a
figure path + a caption candidate. The figures are tied to
specific analyses by their filenames and captions
(e.g. `NB13_phagefoundry_cocktail.png` corresponds to the
phage-cocktail design analysis from NB13).

**Per-substory rule (the load-bearing constraint):**

For each substory you compose:

1. Look at the substory's **Critical analyses covered** list
   (from `02_substories.md`, the section you author against).
2. For each analysis ID/name in that list, check whether the
   curated-figures shortlist contains a figure that corresponds
   to that analysis (filename starts with `NB##_` matching the
   analysis's source notebook, OR the caption candidate
   explicitly names the analysis).
3. **If a curated figure exists for the substory's analyses,
   at least one R-slide in that substory MUST be a
   `data_figure` slide that uses that curated figure** (in the
   `figure:` field, per v2's data_figure schema).

Concretely: if S2's analyses cite NB13 (phage-cocktail design)
and `figures/NB13_phagefoundry_cocktail.png` is on the curated
shortlist, S2 must have a `data_figure` slide with
`figure: "figures/NB13_phagefoundry_cocktail.png"` somewhere in
its R-slide sequence. Substituting a `claim_evidence` slide with
the same bullets but no figure is a v3.1 violation.

**Prefer data_figure over claim_evidence when a curated figure
exists.** If you're choosing the layout for an R-slide AND the
substory has an unused curated figure that maps to the analysis
being shown, pick `data_figure`. Use `claim_evidence` only when:

- No curated figure corresponds to the analysis, OR
- The analysis is a synthesis/comparison without a single
  illustrative figure (in which case `two_column_compare` or
  `data_table` may be better than either).

**Pre-composition self-check (NEW IN v3.1).** Before emitting
the fragment JSON, for EACH substory:

- List the curated figures that correspond to the substory's
  analyses (filenames or caption-matches).
- Count the `data_figure` slides in your composed fragment that
  reference any of those curated figures.
- If the count is 0 but the list is non-empty: **revise to add
  at least one `data_figure` slide before emitting**.

**Counting rule:** A `data_figure` slide "uses" a curated figure
iff the slide's `content.figure` field exactly matches a path
listed in `working/curated_figures.md` (the post-validator
`tools/check_figure_provenance.py` enforces this per D-081 with
strict path matching).

## v3.1 anti-patterns (additive to v3's failure-mode catalog)

(v3 failure modes above all apply; v3.1 adds:)

- **Figure-as-decoration.** A `claim_evidence` slide with a
  curated figure attached only as a thumbnail or supporting
  element rather than the slide's focal evidence. The audience
  doesn't read the figure as the proof; they read the bullets
  AS the proof. → Restructure: emit a `data_figure` slide where
  the figure IS the principal evidence (large center area), and
  the punchline is the claim the figure supports.
- **Figure orphaning.** The curated figure is referenced in a
  slide's `data_source` field but no slide actually displays it
  as a `data_figure`. Provenance without presentation. → Add
  a `data_figure` slide that displays the figure as principal
  evidence.
- **Curated-figure-substitution.** Composing a `data_figure`
  slide with a `figure:` path that ISN'T in
  `working/curated_figures.md` when a curated figure for the
  same analysis IS available. The curator already did the
  scoring work; respect it. → Use the curated figure path
  verbatim from the shortlist.

## v3.1 inviolable rules (additive to v3's inviolable-rules list)

(v3 rules 1–7 above all apply; v3.1 adds:)

8. **v3.1:** For each substory, if the
   `CURATED_FIGURES_PATH` shortlist contains a figure that
   corresponds to one of the substory's critical analyses, at
   least one R-slide in that substory MUST be a `data_figure`
   slide whose `content.figure` field references that curated
   figure verbatim (matching the path in
   `working/curated_figures.md`).
9. **v3.1:** When choosing between `data_figure` and
   `claim_evidence` for an R-slide that has a curated figure
   available, choose `data_figure`. The figure is the slide's
   principal evidence per the Adam-rubric: *"every arc should
   back a claim or finding by relevant figure if possible."*
