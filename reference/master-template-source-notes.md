# Master template source notes

This document records how `kbase-presentation-master.pptx` (the
KBase-branded master that ships under
`src/beril_presentation_maker/skill/references/templates/`) is derived
from Adam's user-supplied source `.potx`. It exists so that brand
updates can be re-derived from a refreshed upstream without hand-
editing the shipped master.

**Status:** v0.1.0-spec — the shipped master and `tools/build_master.py`
are not yet authored. This document specifies the derivation contract
that both will satisfy.

---

## 1. Canonical source

**File:** `KBase 2026 and beyond.potx`
**Provenance:** Supplied by Adam Arkin on 2026-04-25 as the v1
authoritative KBase brand template. The .potx itself is gitignored
(`reference/master-template-source/` is in `.gitignore`); we ship
the *derived* master, not the source .potx.

**Why not redistribute the .potx?** Two reasons. (1) The .potx is
brand asset that may be re-exported from Google Slides on schedule
not under our control — we don't want our package's lifecycle to
chase upstream brand churn. (2) The .potx contains 32 layouts (mostly
auto-generated junk from Google Slides round-tripping) that we
deliberately *don't* expose; shipping it would invite users to draft
against those layouts and defeat the closed-vocabulary discipline
(D-008).

---

## 2. Inspection findings (recorded 2026-04-26)

`tools/build_master.py` operates on the .potx after the following
ground-truth findings:

- **Slide size:** 10.00 × 5.625 in (standard 16:9). Our master
  preserves this.
- **Two slide masters in the .potx:** master 0 is the canonical
  KBase brand; master 1 is an apparent Google-Slides round-trip
  duplicate of master 0. The build script ignores master 1.
- **32 layouts in master 0** (most auto-named with junk identifiers
  like `TITLE_AND_BODY_1_1_1_1_1_1_1_1_1`). The build script ignores
  the auto-generated layouts and reads only the brand metadata.
- **Brand metadata to extract:** color palette (cross-checked
  against the Style Guide June 2022 — see
  `reference/kbase-style-extract.md`); typography (Oxygen primary,
  Calibri fallback, sizes per the Style Guide); footer band height
  (≥ 36 pt logo + 0.5x clear space); header position; logo asset
  references (KBase preferred-with-tagline, stacked, symbol-only).
- **Slides used by the example deck (Gazi 2026 deck):** only 3
  layouts of the 32 are actually used — `TITLE_1_2`,
  `TITLE_AND_BODY_1_1_1_1_1_1_1_1_1`, and `CUSTOM_4`. Every "fancy"
  slide is freeform shape composition on top of `TITLE_AND_BODY`.
  Our derived master replaces this freeform pattern with explicit
  named layouts (D-007).

---

## 3. Derivation contract — what `build_master.py` produces

The build script:

1. Loads `KBase 2026 and beyond.potx` from
   `reference/master-template-source/` (gitignored — Adam supplies).
2. Extracts brand tokens (palette, fonts, sizes, logo positions) and
   writes them to `references/kbase-brand-tokens.json`.
3. Authors a fresh `kbase-presentation-master.pptx` with:
   - Single slide master (no Google Slides duplicates).
   - 15 named layouts mapped to the SPEC §6 vocabulary
     (`title`, `section_divider`, `big_idea`, `big_number`,
     `claim_evidence`, `two_column_compare`, `data_figure`,
     `workflow_diagram`, `methods_summary`, `concept_illustration`,
     `cross_tenant_integration`, `implications`, `acknowledgments`,
     `references`, `qa_anticipated`).
   - Each layout has a stable placeholder index that
     `tools/assemble_pptx.py` fills.
   - KBase brand colors applied per `kbase-brand-tokens.json`.
   - KBase Oxygen typography (Calibri fallback declared for
     environments without Oxygen).
   - KBase logo placement on every layout per Style Guide §1.
4. Writes the derived master to
   `src/beril_presentation_maker/skill/references/templates/kbase-presentation-master.pptx`.
5. Emits a build report (`build_master_report.md` in the build
   output dir, gitignored): shape counts, layout names, brand-token
   diffs against the previous master, font-availability checks.

**Idempotency:** Running `build_master.py` twice from the same .potx
produces byte-identical output (`test_build_master.py` enforces). If
it doesn't, the build is non-deterministic and we treat as a bug.

---

## 4. Layout-by-layout placeholder spec

Each layout has a fixed placeholder set that the assembler fills.
Indices are stable across builds; renaming a layout is a master-
breaking change (D-008: closed vocabulary).

The spec below uses python-pptx placeholder-type vocabulary (TITLE,
BODY, PICTURE, TEXT_BOX, etc.). Full implementation lands in
`tools/build_master.py` in the v0.1.0-master-draft phase.

| Layout | Placeholders (idx → type → purpose) |
|---|---|
| `title` | 0 → TITLE → deck title; 1 → SUBTITLE → subtitle; 2 → TEXT_BOX → presenter+date+venue; 3 → PICTURE → KBase preferred-with-tagline logo |
| `section_divider` | 0 → TITLE → substory punchline (large, centered); 1 → TEXT_BOX → substory number (small, footer); 2 → PICTURE → KBase symbol mark |
| `big_idea` | 0 → TITLE → one-sentence claim (large, centered); 1 → PICTURE → optional supporting graphic; 2 → TEXT_BOX → footer (substory ID + page number) |
| `big_number` | 0 → TITLE → headline statistic (huge, centered); 1 → SUBTITLE → one-line subtitle; 2 → BODY → optional sub-bullet pointer; 3 → TEXT_BOX → source-footer |
| `claim_evidence` | 0 → TITLE → punchline title; 1 → BODY → ≤3 evidence bullets; 2 → PICTURE → one figure; 3 → TEXT_BOX → citation footer |
| `two_column_compare` | 0 → TITLE → optional top punchline; 1 → BODY → left col title + content; 2 → BODY → right col title + content; 3 → TEXT_BOX → footer |
| `data_figure` | 0 → TITLE → interpretation-as-title; 1 → PICTURE → one chart from REPORT/notebook; 2 → TEXT_BOX → caption; 3 → TEXT_BOX → data-source footer |
| `workflow_diagram` | 0 → TITLE → punchline; 1 → PICTURE → diagram (or composed shape group); 2 → BODY → 3-step caption; 3 → TEXT_BOX → tool/version footer |
| `methods_summary` | 0 → TITLE → punchline; 1 → BODY → 5–10 bullets; 2 → TEXT_BOX → "see speaker notes for detail" |
| `concept_illustration` | 0 → TITLE → punchline; 1 → PICTURE → AI-generated image; 2 → TEXT_BOX → caption; 3 → TEXT_BOX → AI-disclosure footer (8 pt, graphite-gray) |
| `cross_tenant_integration` | 0 → TITLE → "How this work integrated across the platform" (or punchline); 1 → BODY → tenant list; 2 → BODY → K-BERDL DB list; 3 → BODY → sibling-project refs; 4 → PICTURE → optional data-flow diagram |
| `implications` | 0 → TITLE → "What this means" (or punchline); 1 → BODY → 3 bullets max with per-bullet evidence pointer |
| `acknowledgments` | 0 → TITLE → "Acknowledgments"; 1 → BODY → contributor list; 2 → PICTURE → funder logos; 3 → TEXT_BOX → tenant-attribution footer |
| `references` | 0 → TITLE → "References"; 1 → BODY → ≤8 short-form refs (Author Year); 2 → TEXT_BOX → AI-disclosure ("Slides drafted with beril-presentation-maker; full bibliography in speaker notes") |
| `qa_anticipated` | 0 → TITLE → anticipated question; 1 → BODY → rehearsable answer; 2 → BODY → evidence pointer (notebook+cell or ref) |

This table is the **authoritative placeholder map**. Changes to it
require a master-template-version bump and a coordinated update to
`tools/assemble_pptx.py`.

---

## 5. Update workflow when KBase brand evolves

If KBase ships a refreshed style guide or a new master .potx:

1. Adam saves the new `.potx` to `reference/master-template-source/`
   (gitignored).
2. Adam updates `reference/kbase-style-extract.md` with quoted
   excerpts from the new style guide.
3. `python tools/build_master.py` regenerates the derived master.
4. The shipped master pptx is overwritten; the build report shows
   diff against prior version.
5. `tests/unit/test_build_master.py` verifies idempotency,
   placeholder presence, and brand-token application.
6. Bump master-template-version (e.g., `1.0` → `1.1`); document in
   CHANGELOG (when we have one — v1.x).

---

## 6. Failure modes the build script must guard against

- **Missing `.potx`.** If `reference/master-template-source/KBase 2026 and beyond.potx`
  is absent, `build_master.py` fails loud with a path hint and a
  reminder that the .potx is user-supplied (not in the repo).
- **Style guide / .potx drift.** If the .potx's palette doesn't match
  the style guide's quoted hex values (e.g., a manual edit in the
  .potx introduces an off-palette color), the build halts with a
  diff report. Adam either updates the style-extract or fixes the
  .potx.
- **Font availability.** The Oxygen face is not always preinstalled
  on macOS / Windows / Linux. The master declares Calibri as
  fallback (per KBase Style Guide, "When Oxygen is not accessible
  i.e., Google Drive, etc."). `build_master.py` does not check font
  installation at runtime; the test suite verifies that both names
  are declared in the master XML.
- **Logo asset missing.** If the .potx references a logo PNG/SVG
  that's not embedded in the file, the build halts and asks Adam
  to re-export the .potx with embedded assets.

---

## 7. v0.1.0-master-draft phase deliverables

This document is the spec; the actual deliverables for the
v0.1.0-master-draft phase (per D-024) are:

- `tools/build_master.py` — the build script (planned ~250 LOC).
- `references/kbase-brand-tokens.json` — extracted brand tokens.
- `references/templates/kbase-presentation-master.pptx` — derived master.
- `tests/unit/test_build_master.py` — idempotency + placeholder tests.

Adam reviews the master template (visually open in PowerPoint /
Keynote) before code in subsequent phases (extractors, prompts,
poster) commits to the layout names. Layout renaming after that
point is a breaking change.
