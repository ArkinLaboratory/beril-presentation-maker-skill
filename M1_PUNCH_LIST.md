# M1 Punch List — Phase 0 vendor ports (`extract_methods.py` + `claim_inventory.py`)

**Filed:** 2026-05-12. **Revised:** 2026-05-12 (Tier B scope corrected per D-040-rev1 after vendoring premise drift surfaced; see `feedback_vendor_port_verify_active_path.md`).
**Milestone:** M1 of v0.4 architectural pivot (per `V0_4_ARCHITECTURE.md` §16)
**Predecessor:** M0 spec sign-off (shipped 2026-05-12; D-030 through D-041)
**Successor:** M2 deck architect + composition pipeline
**Scope (REVISED, Option A):** Vendor `extract_methods.py` + `extract_claims.v1.md` (LLM prompt) + `validate_claim_inventory.py` from paper-writer's *active* path (not the deferred `claim_inventory.py`). Author `extract_claims.py` adapter. Author `phase0_reuse.py` reuse-from-paper-writer helper. Unit tests + dual-mode smoke against `ibd_phage_targeting`. No orchestrator changes. No architect prompt. Independently testable.
**LOC target:** ~1400 LOC vendored byte-portable + ~300 LOC new (adapter + reuse helper) + ~65 tests.
**Cost ceiling at smoke:** ≤$0.10 (extract_claims) per run on `ibd_phage_targeting`. `extract_methods.py` and `validate_claim_inventory.py` are deterministic — $0.00. If smoke spend exceeds the cap, reopen the calibration in the audit-jsonl analysis.

## Tier A + Tier B status (shipped 2026-05-12)

| Tier | Item | Status |
|---|---|---|
| A1 | Copy `extract_methods.py` + docstring attribution | ✅ done |
| A2 | Copy `test_extract_methods.py` + import adaptation + CLI SCRIPT path fix | ✅ done |
| B1 | Copy `validate_claim_inventory.py` + docstring attribution | ✅ done |
| B2 | Copy `extract_claims.v1.md` prompt | ✅ done |
| B3 | Author `tools/extract_claims.py` adapter (~340 LOC) | ✅ done |
| B4 | Author `test_validate_claim_inventory.py` (12 tests) | ✅ done |
| B5 | Author `test_extract_claims.py` (11 tests) | ✅ done |
| B6 | Pin model in `extract_claims.py` `claude -p` invocation (2026-05-14) | ✅ done |

**Pytest smoke (M1 §A+§B):** 66/66 new+adapted tests passing. Full presentation-maker suite: 928 passed, 1 skipped, 2 pre-existing environmental errors unrelated to M1.

**Sandbox dependencies added (pip install --break-system-packages):** pytest, nbformat. Production install picks these up via `pyproject.toml`; the sandbox lacks them by default.

**Surprises caught during ship:**
- Vendoring premise drift (memo M0 had us vendoring the deferred `claim_inventory.py` instead of the active path) — surfaced via the copied file's module-level STATUS note. Halted; reverted; revised vendor plan to Option A. Memory entry filed at `feedback_vendor_port_verify_active_path.md`.
- One hardcoded `beril_paper_writer` path in `test_extract_methods.py` line 542 (TestCLI.SCRIPT) — not caught by the single-line import adaptation; fixed during pytest smoke.
- Two new validator-test expectation bugs (mine, not upstream) — wrong-semantics assumptions about `rows_already_marked_unresolved` and `rows_with_source_notebook` counters. Upstream validator computes these AFTER clearing fabrications; tests now document this explicitly.

### B6 — model pin in `extract_claims.py` (post-Tier-B patch, shipped 2026-05-14)

Surfaced by the paper-writer team's Tier G heads-up (their draft_9
`source_notebook` regression post-mortem). `extract_claims.py`'s
`invoke_claude_extract()` invoked `claude -p` with **no `--model` flag** —
the only `claude -p` call site in presentation-maker that was unpinned
(`presentation_maker.sh:79` pins everything else to `claude-sonnet-4-6`).
An unpinned `claude -p` resolves a context-dependent default model; a
context-resolved model produced paper-writer's draft_9 bare-stem /
em-dash `source_notebook` format. Fix: `_DEFAULT_MODEL = "claude-sonnet-4-6"`
constant; `model` param on `invoke_claude_extract()`; `"--model", model`
in the `cmd` list; `model` in the diagnostic dict; `--model` CLI arg;
VERSION → `0.4.0-m1-tierB.1`. `test_extract_claims.py` gains
`test_invoke_claude_extract_model_override` + argv/diag assertions
(11 → 12 tests). Surgical — does NOT close the stream-json cost-parsing
gap (that is Tier F5; "subtraction over addition" keeps B6 minimal).



---

## Why a punch list

Per `feedback_punch_list_release_pattern.md`: M1 ships two vendored tools + a new reuse helper + dual-mode smoke + a cross-skill contract drift task. Five tiers of work with clear dep edges + smoke at every tier boundary. Less design risk than paper-writer's M1 (the Q1 cost-justification ablation and Q2 ground-truth completeness check already happened upstream; both tools shipped paper-writer M1 §B1 / §C0 in production) but more cross-skill coordination risk (the new `talks/draft_N/00_phase0/` sub-directory).

---

## Paper-writer ship status (vendoring readiness)

Per memory `project_paper_writer_v0_8_m1_a1.md` (2026-05-07):

- `extract_methods.py` — ran clean against `ibd_phage_targeting`; produced `methods_provenance.md` (227 lines, 32 notebooks, 6 unique stat tests). M1 §C0 status: shipped.
- `claim_inventory.py` — VERSION `0.8.0-m1-B1.abcd`; 18 unit tests passing; `claim_demarcate.v1.md` prompt shipped. M1 §B1 status: shipped.
- Both files exist at `spike/beril-paper-writer-skill-draft/src/beril_paper_writer/skill/tools/`.
- Tests at `spike/beril-paper-writer-skill-draft/tests/unit/test_{extract_methods,claim_inventory}.py`.
- Fixtures at `spike/beril-paper-writer-skill-draft/tests/fixtures/m1/`.

**Vendor port is unblocked.** Both tools can be ported in parallel.

---

## Tier A — `extract_methods.py` vendor port

Independent of Tier B; can ship first. ~1100 LOC source + ~25 tests.

### A1. Copy source + adapt to presentation-maker package shape

**Spec:** `V0_4_ARCHITECTURE.md` §4.5; D-040.

**Steps:**

A1.a Copy `spike/beril-paper-writer-skill-draft/src/beril_paper_writer/skill/tools/extract_methods.py` to `spike/beril-presentation-maker-skill-draft/src/beril_presentation_maker/skill/tools/extract_methods.py`.

A1.b Module docstring: keep paper-writer SPEC §6.3 reference (that's where the original design lives), add a "Vendored into beril-presentation-maker v0.4 per D-040" line at the top.

A1.c Default `--output-dir`: paper-writer defaults to `<project>/papers/draft_N/`. Presentation-maker default is `<project>/talks/draft_N/00_phase0/`. Change the help-string default AND the path-existence behavior. Verify `args.output_dir` writes land at the correct location for both work modes.

A1.d Audit JSONL location: paper-writer writes to `papers/draft_N/audit/phase0.jsonl`. Presentation-maker writes to `talks/draft_N/audit/phase0.jsonl`. Same path-discipline shift as A1.c.

A1.e No other code-body changes. Module-level constants (`_TEST_NAME_MAP`, etc.) port as-is — the dotted-path → canonical-test-name catalog is project-independent.

**AC:** `python3 src/beril_presentation_maker/skill/tools/extract_methods.py --help` shows the new defaults. File diff vs paper-writer's `extract_methods.py` is ≤30 lines (docstring + default paths only).

### A2. Unit tests

A2.a Copy `tests/unit/test_extract_methods.py` from paper-writer to presentation-maker.

A2.b Change one import: `from beril_paper_writer.skill.tools import extract_methods as em` → `from beril_presentation_maker.skill.tools import extract_methods as em`.

A2.c Copy `tests/fixtures/m1/` synthetic-project fixtures from paper-writer. If fixture paths reference `papers/draft_1/`, update to `talks/draft_1/00_phase0/` where the test asserts output location.

**AC:** `PYTHONPATH=src python3 -m pytest tests/unit/test_extract_methods.py -v` shows 25/25 passing (matches paper-writer's test count; adjust if paper-writer's count shifted).

### A3. Smoke against real project (no-paper mode)

A3.a Run `extract_methods.py <ibd_phage_targeting_dir> --output-dir <talks/draft_pilot/00_phase0/>` from clean state (no existing artifacts).

A3.b Verify: `methods_provenance.md` lands at `talks/draft_pilot/00_phase0/methods_provenance.md`; audit JSONL line written; output byte-equivalent to paper-writer's `papers/draft_1/methods_provenance.md` (the same project's notebooks → same extraction output).

**AC:** Smoke produces methods_provenance.md with the same 32 notebooks + 6 unique stat tests paper-writer's run produced; diff against paper-writer's output is empty (or trivial whitespace/header).

---

## Tier B (ORIGINAL — SUPERSEDED 2026-05-12 by Option A scope above)

The original Tier B vendored paper-writer's deferred `claim_inventory.py`
(M1 §B1.abcd ship state, 2400 LOC). On 2026-05-12 the vendoring
premise was discovered to have drifted: paper-writer's
STAGED_IMPROVEMENT_PLAN.md Stage 1 (closed 2026-05-11) deferred this
file from the active pipeline in favor of LLM-only extraction via
`extract_claims.v1.md` + `validate_claim_inventory.py`. D-040 was
amended to D-040-rev1 to match paper-writer's actual production path.

The original Tier B text below is preserved for audit / archeology;
it should NOT be executed.

---

## Tier B (ORIGINAL, DEPRECATED) — `claim_inventory.py` + `claim_demarcate.v1.md` vendor port

Independent of Tier A; can ship in parallel. ~2400 LOC source + ~500-line prompt + ~18 tests.

### B1. Copy source + adapt to presentation-maker package shape

B1.a Copy `spike/beril-paper-writer-skill-draft/src/beril_paper_writer/skill/tools/claim_inventory.py` to `spike/beril-presentation-maker-skill-draft/src/beril_presentation_maker/skill/tools/claim_inventory.py`.

B1.b Module docstring: same pattern as A1.b — keep paper-writer §4.6 reference, add the "Vendored into beril-presentation-maker v0.4 per D-040" attribution line.

B1.c Default `--output-dir`: change from `papers/draft_N/` to `talks/draft_N/00_phase0/` (same as A1.c).

B1.d Output filename: paper-writer writes `claim_inventory.tsv` at `<output-dir>/claim_inventory.tsv`. Keep the filename; the directory shift in B1.c is enough.

B1.e Audit JSONL: same path-discipline shift as A1.d.

B1.f Subprocess Claude-CLI invocation: paper-writer's tool invokes `claude -p ...` with the demarcator prompt. Verify the prompt-path resolution finds the new vendored location (presentation-maker's `prompts/claim_demarcate.v1.md`, not paper-writer's). This is the one place the port might break silently — the prompt-path lookup must use `importlib.resources` or a relative-to-`__file__` reference, NOT a hard-coded `beril_paper_writer.skill.prompts` path.

B1.g Cost-ceiling constants (`_COST_CEILING_USD`, demarcator batch-size): keep paper-writer's defaults; if presentation-maker's claim density differs, adjust at D2 smoke time, not here.

**AC:** `python3 src/beril_presentation_maker/skill/tools/claim_inventory.py --help` shows new defaults. Source diff vs paper-writer's `claim_inventory.py` is ≤50 lines (docstring + default paths + prompt-resolution).

### B2. Copy `claim_demarcate.v1.md` prompt

B2.a Copy `spike/beril-paper-writer-skill-draft/src/beril_paper_writer/skill/prompts/claim_demarcate.v1.md` to `spike/beril-presentation-maker-skill-draft/src/beril_presentation_maker/skill/prompts/claim_demarcate.v1.md`.

B2.b Cross-reference adaptation: prompt's footnote citing paper-writer SPEC §4.6 stays (provenance attribution); add a line "Vendored into beril-presentation-maker v0.4 per D-040; consumes the same REPORT.md + methods_provenance.md inputs in both skills."

**AC:** Prompt file exists at expected path; loaded by B1.f's prompt-path resolution.

### B3. Unit tests

B3.a Copy `tests/unit/test_claim_inventory.py` from paper-writer.

B3.b Change one import: `from beril_paper_writer.skill.tools import claim_inventory as ci` → `from beril_presentation_maker.skill.tools import claim_inventory as ci`.

B3.c Copy `tests/fixtures/m1/claim_inventory_synthetic_001/` synthetic fixtures from paper-writer.

**AC:** `PYTHONPATH=src python3 -m pytest tests/unit/test_claim_inventory.py -v` shows 18/18 passing (matches paper-writer's M1 §B1 ship state; adjust if paper-writer's count shifted post-2026-05-07).

### B4. Smoke against real project (no-paper mode, costs real money)

B4.a Run `claim_inventory.py <ibd_phage_targeting_dir> --output-dir <talks/draft_pilot/00_phase0/>` from clean state.

B4.b Verify: `claim_inventory.tsv` lands at `talks/draft_pilot/00_phase0/claim_inventory.tsv`; audit JSONL line written with cost ≤$0.10; every `source_notebook` resolves to a real notebook; every `source_cell` resolves to a cell in that notebook.

B4.c Cross-check: output should be byte-equivalent (or near-equivalent) to paper-writer's `papers/draft_1/claim_inventory.tsv`. Same REPORT.md → same demarcation. Any divergence is a port bug.

**AC:** Smoke produces a claim_inventory.tsv with the same ≥30 claim_ids paper-writer's smoke produced; per-row diff vs paper-writer's output is empty (or limited to the `notes` column on rows the LLM non-deterministically resolved differently — flagged but tolerated per paper-writer §B1.g).

---

## Tier C — Phase-0 reuse-from-paper-writer helper

Depends on A2 + B3 (vendored tools must work standalone before the reuse
helper wraps them).

**Scope:** decision-logic helper for the TWO new v0.4 artifacts only
(`methods_provenance.md` + `claim_inventory.tsv`). The other three Phase-0
artifacts named in V0_4_ARCHITECTURE.md §4.6 (`citation_pool.json`,
`cross_tenant_signal.md`, `curated_figures.md`) are pre-existing with their
own writers and their own reuse logic via `state.json.paper_writer_reuse`
(LAYOUT.md §6). Unifying all five under a single helper is deferred to v0.5
(see Tier F backlog).

**Spec resolutions (signed off Adam 2026-05-12, in-conversation):**
- Output layout uses **`working/00_phase0/`** under the 4-zone discipline
  (not `talks/draft_N/00_phase0/` per V0_4_ARCHITECTURE.md §4.6 as
  originally drafted). Reason: §4.6 conflicted with `draft_paths.py`'s
  hard rule of exactly four top-level zones. Doc fix to §4.6 lands as
  Tier E paperwork.
- Reuse decision is **presence-based**, not hash-equality-based against
  paper-writer. Reason: paper-writer does NOT stamp source-artifact
  hashes anywhere persistent (verified against `papers/draft_9/state.json`
  → `source_artifacts == []`, `audit/claim_inventory_validation.json`
  records exit status / row counts only). The decision-rule in the
  original punch-list draft was not implementable; revised to "if
  paper-writer artifact exists, COPY; else ORIGINATE" with `--force-originate`
  bypass. Cross-draft staleness detection (paper-writer's REPORT.md
  changed after paper-writer ran) is explicitly out of scope; user runs
  paper-writer again if they want fresher reuse.
- **Within-talk-draft idempotency** is hash-based: `phase0_reuse.py`
  writes the CURRENT source-artifact hashes to `audit/phase0.jsonl` on
  every decision. Re-invocation in the same talk-draft compares current
  hashes against the stamp; matched → no-op, drifted → re-run the
  decision (re-copy from paper-writer with fresh stamp on reuse path; or
  re-originate on originate path).

### C1. Implement `tools/phase0_reuse.py`

**CLI surface (final):**
```
python3 phase0_reuse.py \
  --project-dir <projects/<id>/> \
  --talk-draft-dir <talks/draft_N/> \
  --artifact {methods_provenance|claim_inventory|all} \
  [--force-originate] \
  [--claude-bin claude] \
  [--paper-draft-glob "papers/draft_*"]
```

**Output paths (use DraftPaths v0.3.1+ vocabulary; will add properties at C1.a):**
- `methods_provenance.md` → `<talk-draft-dir>/working/00_phase0/methods_provenance.md`
- `claim_inventory.tsv` → `<talk-draft-dir>/working/00_phase0/claim_inventory.tsv`
- audit stamp → `<talk-draft-dir>/audit/phase0.jsonl` (append-only;
  schema below; shares the file with `extract_claims.py`'s existing
  `append_audit()` writes — both tools append; the file is one-record-
  per-line JSONL).

**Decision logic per artifact (final):**
1. **Reuse predicate.** If `<project>/papers/draft_*/<artifact>` exists
   (most-recent draft wins; sort by draft number desc), AND
   `--force-originate` is NOT set → COPY paper-writer's file to
   `<talk-draft-dir>/working/00_phase0/<artifact>`. Stamp audit JSONL
   with `decision=reuse`, `source_path=<full path to paper-writer's
   draft>`, `inputs_hashed` computed at time of decision.
2. **Originate predicate.** Otherwise → invoke the vendored tool
   targeting `<talk-draft-dir>/working/00_phase0/`. For
   `methods_provenance`, `extract_methods.py --output-dir`. For
   `claim_inventory`, `extract_claims.py` (which chains the validator).
   Stamp audit JSONL with `decision=originate`, `source_path=null`,
   `cost_usd` from the tool's diagnostic for the LLM call (0.0 for
   `extract_methods.py`, ≤0.10 for `extract_claims.py`).
3. **Idempotent fast-path.** Before either predicate evaluates: if the
   talk-draft already has the target file AND the most-recent
   `audit/phase0.jsonl` entry for this artifact has `inputs_hashed`
   that matches CURRENT input hashes → no-op (write a `decision=no-op`
   stamp). This is the within-talk-draft re-run guard.

**Per-artifact input-hash specification:**

| Artifact | Inputs hashed | Computation |
|---|---|---|
| `methods_provenance.md` | notebooks/ + src/ + analysis/ + scripts/ + RESEARCH_PLAN.md + requirements.txt + pyproject.toml + environment.yml | SHA256 over sorted [(rel_path, file_sha256)] tuples for every `.ipynb` / `.py` discovered by `extract_methods.find_notebooks()` + `find_scripts()`, plus the four direct-child files extract_methods also reads (RESEARCH_PLAN.md + the 3 package manifests `collect_package_versions()` folds into the artifact). *Manifest files added post-code-review (Should-fix #3) — omitting them let a dependency bump change the artifact without moving the hash.* |
| `claim_inventory.tsv` | REPORT.md + methods_provenance.md | SHA256 over `(report_md_sha256, methods_provenance_sha256)` tuple |

Each artifact's hash predicate is independent of the other. Helper
function `compute_input_hash(artifact: str, project_dir: Path,
talk_draft_dir: Path) -> str` lives in the module.

**Audit JSONL record schema (one per decision):**
```json
{
  "timestamp": "2026-05-13T14:32:00Z",
  "tool": "phase0_reuse",
  "version": "0.4.0-m1-tierC",
  "artifact": "methods_provenance | claim_inventory",
  "decision": "reuse | originate | no-op",
  "source_path": "<full path to paper-writer artifact, null otherwise>",
  "destination_path": "<full path to talk-draft artifact>",
  "inputs_hashed": "<sha256 hex>",
  "cost_usd": 0.0,
  "duration_sec": 0.42,
  "rationale": "<short string: 'paper_artifact_present' | 'force_originate' | 'paper_artifact_absent' | 'hashes_match'>"
}
```

`tool=phase0_reuse` distinguishes these records from
`extract_claims.py`'s `tool=extract_claims` writes in the same file.

**Exit codes:**
- 0 — decision executed cleanly (reuse, originate, or no-op).
- 1 — user error (missing `--project-dir`, malformed `--talk-draft-dir`).
- 2 — sub-tool invocation failed (only on originate path; surfaces the
  exit code from `extract_methods.py` / `extract_claims.py`).
- 3 — internal consistency error (e.g., reuse predicate true but copy
  failed; should not happen, halt loud per `feedback_no_benchmark_gaming.md`).

**Estimated LOC:** ~250 (slightly above the §16 ~200 estimate because
of the per-artifact hash dispatcher + idempotent fast-path).

**Sub-step breakdown:**

C1.a **`draft_paths.py` extension.** Add three properties to `DraftPaths`:
- `phase0_dir` → `working/00_phase0`
- `methods_provenance_phase0` → `working/00_phase0/methods_provenance.md`
- `claim_inventory_phase0` → `working/00_phase0/claim_inventory.tsv`

Add `working/00_phase0` to `LAYOUT_SUBDIRS` so `init_layout()` creates
it. ~10 LOC + 1 test in `test_draft_paths.py`.

C1.b **Module skeleton.** `tools/phase0_reuse.py` boilerplate (docstring
citing D-040-rev1 + V0_4_ARCHITECTURE §4.0/§4.6 + the spec resolutions
above), argparse with the CLI surface above, top-level `main(argv)`,
exit codes. ~50 LOC.

C1.c **Hash computation.** `compute_input_hash(artifact, project_dir,
talk_draft_dir) -> str`. Two strategies dispatched on artifact name.
Re-uses `extract_methods.find_notebooks()` / `find_scripts()` for the
methods-provenance case. ~50 LOC.

C1.d **Reuse-from-paper-writer locator.**
`find_paper_writer_artifact(project_dir, artifact, glob_pattern) ->
Optional[Path]`. Iterates `project_dir / "papers" / "draft_*"`, sorts
by integer draft number desc, returns the path to the most-recent
draft's artifact if present. ~30 LOC.

C1.e **Decision dispatcher.** Per-artifact `decide_and_act(artifact,
project_dir, talk_draft_dir, force_originate) -> dict` returns the
audit-record dict. Wraps the three predicates above (fast-path, reuse,
originate). Originate path invokes `extract_methods.main([...])` or
`extract_claims.main([...])` as a function call (not subprocess) so we
can mock cleanly in tests. ~80 LOC.

C1.f **Audit emission.** `append_audit_record(audit_dir, record_dict)`
mirrors `extract_claims.append_audit()`'s shape but writes the v0.4
record schema. Shares `<audit_dir>/phase0.jsonl` with `extract_claims`.
~15 LOC.

C1.g **`--artifact all` handler.** Dispatches both
`methods_provenance` and `claim_inventory` in order. Methods first so
its output is available as input for claim's hash predicate. Halts
between them if methods fails. ~20 LOC.

**AC for C1:** `python3 phase0_reuse.py --help` works and shows the
documented flags. `python3 phase0_reuse.py --project-dir <proj>
--talk-draft-dir <dir> --artifact all` runs end-to-end without
subprocess errors when both reuse paths trigger.

### C2. Unit tests for `phase0_reuse.py`

C2.a Land at `tests/unit/test_phase0_reuse.py`. ~14 tests (slight
upward revision from the §16 ~12 estimate to cover the no-op fast-path
+ exit-code paths).

**Test coverage matrix:**

| # | Test name | Verifies |
|---|---|---|
| 1 | `test_compute_input_hash_methods_stable` | Hash for methods_provenance inputs is deterministic across two calls on same fixture. |
| 2 | `test_compute_input_hash_methods_changes_on_notebook_edit` | Editing one NB cell changes the hash. |
| 3 | `test_compute_input_hash_claim_includes_methods_dependency` | Hash for claim_inventory inputs changes when methods_provenance.md changes (but not when notebooks change directly without methods regeneration). |
| 4 | `test_find_paper_writer_artifact_picks_most_recent` | Two paper drafts (`draft_1/`, `draft_2/`) both with the artifact; helper returns draft_2's path. |
| 5 | `test_find_paper_writer_artifact_skips_missing` | `draft_3/` exists but lacks the artifact; falls back to `draft_2/`. |
| 6 | `test_find_paper_writer_artifact_none_when_no_drafts` | No `papers/` dir; returns None. |
| 7 | `test_decide_reuse_when_paper_artifact_present` | Paper-writer artifact exists → decision=reuse, copy lands at correct path, audit record `tool=phase0_reuse`, `decision=reuse`, `source_path` set. |
| 8 | `test_decide_originate_when_paper_artifact_absent` | No paper-writer artifact → decision=originate, vendored tool invoked (mocked), output lands at `working/00_phase0/`. |
| 9 | `test_decide_originate_when_force_originate_set` | `--force-originate` bypasses reuse even when paper artifact present. |
| 10 | `test_decide_no_op_on_hash_match` | Existing talk-draft artifact + audit stamp with matching hash → decision=no-op, no copy / no tool invocation, audit record `decision=no-op`. |
| 11 | `test_decide_re_run_on_hash_mismatch` | Existing talk-draft artifact + audit stamp with DIFFERENT hash → re-runs decision (re-copy or re-originate per current predicates). |
| 12 | `test_audit_jsonl_appended_not_overwritten` | Run twice; audit JSONL has two records, both valid JSON. |
| 13 | `test_audit_jsonl_coexists_with_extract_claims_records` | Pre-existing `phase0.jsonl` written by `extract_claims.append_audit()` is not clobbered; `phase0_reuse.py` appends. |
| 14 | `test_artifact_all_runs_methods_then_claims` | `--artifact all` runs methods first (output present in talk-draft), then claims (consumes methods output for hash predicate). |

All tests use `tmp_path` for synthetic project + talk-draft scaffolding;
no live `claude -p` calls (vendored-tool invocations are mocked via
`unittest.mock.patch` on `extract_methods.main` / `extract_claims.main`).

**AC for C2:** `PYTHONPATH=src python3 -m pytest tests/unit/test_phase0_reuse.py -v`
shows 17/17 passing (14-matrix + 3 exit-code-contract tests; see Tier C
status deviations).

### User-runnable smoke commands

Per `feedback_sandbox_bash_vs_intermediate_checks.md`: C1 + C2 are
sandbox-confirmed `pytest` green. Adam can re-verify from a Mac shell at
`spike/beril-presentation-maker-skill-draft/`:

```bash
PYTHONPATH=src python3 -m pytest tests/unit/test_phase0_reuse.py -v
PYTHONPATH=src python3 -m pytest tests/unit/test_draft_paths.py -v       # DraftPaths extension; 78 pass
PYTHONPATH=src python3 -m pytest tests/unit/test_extract_claims.py -v    # B6 model pin; 12 pass
PYTHONPATH=src python3 -m pytest -q                                      # full suite; 949 passed, 1 skipped, 2 pre-existing errors
```

CLI manual check (no LLM cost, no network):
```bash
PYTHONPATH=src python3 -m beril_presentation_maker.skill.tools.phase0_reuse --help
```

### Tier C status (shipped 2026-05-14)

| Item | Status |
|---|---|
| C1.a — `DraftPaths` extension (`phase0_dir`, `methods_provenance_phase0`, `claim_inventory_phase0`; `working/00_phase0` in `LAYOUT_SUBDIRS`; 3 `shell_exports` entries) | ✅ done |
| C1.b–C1.g — `tools/phase0_reuse.py` (~470 LOC incl. docstring) | ✅ done |
| C2 — `tests/unit/test_phase0_reuse.py` (18 tests) | ✅ done |
| Code review — independent subagent, adversarial; 1 Blocker + 5 Should-fixes + 3 nitpicks all addressed | ✅ done |

**Pytest smoke (M1 Tier C, post-code-review):** 18/18 `test_phase0_reuse.py`
+ 78/78 `test_draft_paths.py` (was 75; +3 from `WORKING_ATTRS`
parametrization) + 12/12 `test_extract_claims.py` (was 11; +1 from B6).
Full presentation-maker suite: **950 passed, 1 skipped, 2 errors**.
Delta vs the 928 baseline is +22, fully accounted: B6 +1, C1.a +3,
C2 +17, code-review regression test +1. The 2 errors are the
pre-existing `test_check_no_artifact_refs.py` `PermissionError` on the
stale `/sessions/epic-peaceful-faraday/...` upload path (carried as
v0.3.x trailing cleanup in `V0_4_0_PUNCH_LIST.md`); unchanged by Tier C.
The 1 skip is the expected beril-adversarial-CLI-absent integration test.

**Code review (independent subagent, 2026-05-14).** Adversarial review
of B6 + `phase0_reuse.py` + `draft_paths.py` extension + the test files.
Verdict was "not yet — fix Blocker #1 first"; all findings verified
against the code and addressed:
- **Blocker #1 — no-op fast-path poisoned by a prior `error` stamp.**
  An `error` record carries `inputs_hashed`, and a failed `extract_claims`
  originate leaves a validator-rejected TSV on disk → next run saw a
  non-empty `dest` + a hash-matching stamp → spurious no-op, exit 0, bad
  artifact retained (the silent failure `feedback_no_benchmark_gaming.md`
  forbids). Fix: the fast-path now requires `prior["decision"] in
  ("reuse","originate","no-op")`. + regression test
  `test_decide_no_op_skipped_when_prior_stamp_is_error`.
- **Should-fix #1 — `--artifact all` ordering made explicit.** Was an
  implicit dict-insertion-order dependency; now a hardcoded
  `["methods_provenance", "claim_inventory"]` list with a comment.
- **Should-fix #2 — failed originate now `unlink(missing_ok=True)`s the
  bad artifact** so a known-bad file isn't left at the canonical path.
- **Should-fix #3 — methods_provenance input hash now includes
  `requirements.txt` + `pyproject.toml` + `environment.yml`.** These feed
  `extract_methods.collect_package_versions()` → the artifact; omitting
  them let a dependency bump change the artifact without moving the hash.
  Hash-spec table above + module docstring updated to match.
- **Should-fix #4 — `decide_and_act` resolves `project_dir`** at entry
  (it's public; M2 orchestrator + tests call it without `main()`'s
  resolve, leaving `relative_to()` unguarded).
- **Should-fix #5 — `read_last_phase0_reuse_stamp` warns on unparseable
  JSONL lines** instead of swallowing silently ("fail loud").
- **Nitpicks:** `shell_exports` value-match test extended to the 3 new
  Phase-0 vars; `cost_usd` contract now asserted in the `--artifact all`
  test (methods → 0.0, claim_inventory → null); cross-ref comment on the
  intentionally-duplicated `_DEFAULT_MODEL`.
- **Reviewer concerns confirmed already-fine (no change):** B6 model pin
  is load-bearing on every `claude -p` path; `draft_paths.py` properties
  are consistent with the frozen-dataclass pattern; the stale-dest unlink
  was already correct (reviewer self-withdrew its Blocker #2).
- **Deliberately not changed:** `read_last_phase0_reuse_stamp` reads the
  whole JSONL each call — fine at panel-of-one scale, premature to
  optimize; `find_paper_writer_artifact` `draft_02`/tie edge — paper-writer
  uses unpadded `draft_1..draft_N` with no dupes, not a real risk.

**Deviations from the signed-off Tier C spec (all benign, flagged for the record):**
- **Test count 14 → 18.** The 14-test matrix shipped verbatim, plus 3
  exit-code-contract tests (#15 claim_inventory-missing-methods-provenance
  → exit 1; #16 sub-tool-failure → exit 2; #17 main-bad-`--project-dir`
  → exit 1) and 1 code-review regression test (#18 error-stamp must not
  poison the no-op fast-path). The exit-code contract was otherwise
  untested; this is completeness, not scope creep.
- **`cost_usd` on the claim_inventory originate path is `null`, not a
  number.** As flagged before coding: `extract_claims.py` does not
  surface real LLM cost (no stream-json parsing — Tier B simplification).
  reuse / no-op / methods_provenance-originate record `0.0`;
  claim_inventory-originate records `null`. Wiring real cost parsing is
  Tier F5 below.
- **One extra audit-record field: `error_detail`.** Present only on
  `decision == "error"` records (additive; carries the sub-tool exit
  code or the missing-input path). The schema's documented fields are
  unchanged.
- **`phase0_reuse.py` calls `DraftPaths.init_layout()`** (idempotent) so
  it works on a not-yet-initialized talk-draft. Phase 0 runs first in
  the pipeline — there is no earlier tool to have created the layout —
  so this is correct, not a `assert_initialized()` violation. `main()`
  requires `--talk-draft-dir`'s *parent* to exist (guards typo-creates-junk)
  but lets `init_layout()` create the draft dir + zones.

**Carried into M2 / Tier E:** the two doc updates (V0_4_ARCHITECTURE.md
§4.6 path strings → `working/00_phase0/`; LAYOUT.md §5) are Tier E
paperwork. The cross-skill drift task on beril-adversarial (Tier E1)
and the auto-memory entry (Tier E4) remain ahead.

---

## Post-Tier-C — paper-writer v1.0.0 follow-ups (shipped 2026-05-21)

paper-writer tagged v1.0.0 (commit 46e8943, 2026-05-20). Its drop-in memo
flagged three surface changes; two were actioned here, one was no-op.

### Re-vendor — `validate_claim_inventory.py` 0.1.0 → 0.2.0-stage3-tierI

The validator vendored at M1 §B1 (`0.1.0-stage1-tierC`) was behind
paper-writer's Stage 3 Tier I notebook-repair pass (their commit e5fbed6).
Re-vendored to v1.0.0 state:

- **Active-path verified** per `feedback_vendor_port_verify_active_path.md`:
  paper-writer's `orchestrator.py:638` invokes the validator as a
  subprocess — the live path, not a deferred one.
- **Module body byte-identical** to paper-writer's v1.0.0 copy (verified
  by diff from `from __future__` onward); only the attribution docstring
  differs.
- The repair pass recovers `source_notebook` values that map
  UNAMBIGUOUSLY to a real notebook (bare stem, stem-plus-parenthetical,
  wrong-descriptive-suffix, missing-extension); genuinely-invented names,
  placeholders, slash-joined and two-notebook values still clear.
- Two additive diagnostic fields: `rows_repaired_this_run`,
  `repaired_notebooks`. `extract_claims.py` invokes the validator as a
  subprocess and parses only exit status / stdout / stderr — it never
  reads the validator JSON, so the new fields cannot break the adapter
  (confirmed: `test_extract_claims.py` still 12/12 green).
- `test_validate_claim_inventory.py`: 12 → 36 cases (+24). The original
  12 base tests are repair-compatible unchanged — they all use `NB99*`
  fabricated names with no real-notebook ID match, so they still clear.
  Added: `_notebook_id` extraction, four repair classes, four
  still-clears classes, the new diagnostic fields, repaired-row
  idempotency.

This makes Tier F4 real: `claim_inventory.tsv` rows can now carry a
`notebook-repaired:` notes prefix. F4 updated below.

### Re-vendor — `extract_claims.v1.md` 39 → 79 lines (source_notebook format rule)

Caught at Tier-D prep (2026-05-21), **not** in the 2026-05-21
paper-writer v1.0.0 sweep above — the same miss class that sweep was
meant to close. presentation-maker's B2-vendored prompt (copied
2026-05-12, 39 lines) predated paper-writer's draft-9 `source_notebook`
regression fix: paper-writer added a `## source_notebook format rule
(CRITICAL)` section (~40 lines — exact-`.ipynb`-filename discipline plus
a worked counter-example table of the bare-stem / parenthetical /
em-dash / slash-joined failure modes) some time after our copy was
taken.

This is the **prevention** leg of the draft-9 post-mortem. B6 (model
pin, 2026-05-14) closed the *model* leg; the `validate_claim_inventory.py`
re-vendor above closed the *repair* leg; the prompt — the *prevention*
leg — was missed. Running D2/D3 against the stale prompt would have
emitted bare-stem `source_notebook` values for the validator to
repair-or-clear, burning LLM spend to rediscover a known,
already-fixed-upstream bug.

- **Active-path verified** per `feedback_vendor_port_verify_active_path.md`:
  paper-writer's `validate_claim_inventory.py` docstring names
  `extract_claims.v1.md` as the prompt `orchestrator`'s `phase_triage`
  uses to produce `claim_inventory.tsv`; paper-writer is at v1.0.0, so
  its on-disk prompt is the v1.0.0 active path.
- **Byte-exact re-vendor:** `cp` from paper-writer's v1.0.0 copy; the
  presentation-maker file is now `diff`-identical to it. Purely
  additive — the weak "…if applicable" qualifier on the
  source_notebook-mapping line is replaced by the strong section.
- **No test impact:** `test_extract_claims.py` mocks the `claude -p`
  subprocess and never asserts on prompt *content* (only that the
  prompt file exists and `--system-prompt` is passed). 12/12 still
  green; full-suite test count unchanged.
- **No `extract_claims.py` `VERSION` bump:** the prompt carries no
  internal version string, the filename stays `extract_claims.v1.md`,
  and the re-vendor restores upstream parity rather than introducing
  new behavior — consistent with how the validator re-vendor above was
  handled.

### D-052 port — numeric-grounding false-positive fixes

paper-writer's memo (D-052) flagged four surface-form mismatch classes
producing false "ungrounded numeric" findings.
`check_quantitative_grounding.py` is an independent tool, but the failure
modes are medium-agnostic. Diagnose-first per
`feedback_no_benchmark_gaming.md`: 17 D-052 test cases written and run
against the unpatched tool — **all 17 failed**, confirming every class is
real in our checker. Then ported:

1. Superscript scientific notation (`1.1 x 10^-130` ↔ `1.1e-130`): new
   `_NUM_SCI_SUPER` extraction pass (caret required); the slide value
   extracts as ONE scientific number, not three bare ones.
2. K/M/G/T SI-suffix expansion, SOURCE-SIDE only (`83K` ↔ `83,000`):
   `_expand_si_suffixes` applied when building the REPORT index;
   mid-word lookahead keeps `1.5MHz` intact.
3. Trailing-zero canonicalization (`82.0` ↔ `82`, `0.30` ↔ `0.3`):
   `_canonical_form` via `%.10g` + exponent leading-zero strip.
4. Comma support in the `n=` extractor (`n=22,751` no longer truncates
   to `n=22`): regex widened, canonical strips the comma.

Classes 1–4 surface through a new final-fallback match form 7 in
`_find_in_report` — a canonical-numeric-set membership check. Form 7 is
strictly additive: it only ever converts a would-be false positive into a
grounded hit, never the reverse, so all 18 pre-existing grounding tests
are unchanged. `test_check_quantitative_grounding.py`: 18 → 35 (+17).

### No-op — D-053 deleted checkers

paper-writer deleted `paper_writer.sh` + 12 advisory checkers. None were
vendored by presentation-maker (we vendored only `extract_methods.py` +
`validate_claim_inventory.py` and built our own `extract_claims.py`). No
action. Minor: `feedback_pipx_venv_python_for_skill_helpers.md` cites
`paper_writer.sh`'s `discover_python_bin` as a reference — that file is
gone; our own `presentation_maker.sh` still embodies the pattern.
Memory-hygiene repoint deferred (low priority).

### Verification

Full presentation-maker suite on Adam's Mac (Python 3.14 `.venv`, the
canonical environment): **991 passed, 3 skipped, 0 errors**. Delta +41
vs the 950 Tier-C baseline (validate +24, D-052 +17). The 3 skips are
all environmental, none a code failure: 1 adversarial-interop
integration test (no v0.3.1+ draft present) + 2
`test_check_no_artifact_refs.py` real-deck tests (the
`ibd_phage_targeting` `slide_spec.json` fixture is not present). A
prior sandbox run reported those 2 as `errors` rather than `skips` — a
sandbox-only artifact of a stale upload path; the Mac result is
authoritative.

User-runnable re-verify from a Mac shell at
`spike/beril-presentation-maker-skill-draft/`:

```bash
.venv/bin/python -m pytest tests/unit/test_validate_claim_inventory.py -v      # 36 pass
.venv/bin/python -m pytest tests/unit/test_check_quantitative_grounding.py -v  # 35 pass
.venv/bin/python -m pytest tests/unit/test_extract_claims.py -v                # 12 pass (adapter regression)
.venv/bin/python -m pytest -q                                                 # 991 passed, 1 skipped, 2 pre-existing errors
```

---

## Tier D — Dual-mode smoke against real projects

Depends on C2 (the reuse helper must work).

### D1. Paper-exists mode smoke (`ibd_phage_targeting`)

D1.a Verify `<ibd_phage_targeting>/papers/draft_1/methods_provenance.md` + `claim_inventory.tsv` exist (paper-writer's own M1 §C smoke produced these).

D1.b Run `phase0_reuse.py --project-dir <ibd_phage_targeting> --talk-draft-dir <talks/draft_pilot_paper_exists> --artifact all`.

D1.c Verify: both artifacts present at `talks/draft_pilot_paper_exists/00_phase0/`; audit JSONL shows `decision: reuse` for both; cost=$0.00 (no LLM calls).

**AC:** Paper-exists mode reuse path produces both artifacts byte-equivalent to paper-writer's outputs, at the new talk-draft location, for $0.

### D2. No-paper mode smoke (`ibd_phage_targeting` with `--force-originate`)

D2.a Run `phase0_reuse.py --project-dir <ibd_phage_targeting> --talk-draft-dir <talks/draft_pilot_no_paper> --artifact all --force-originate`.

D2.b Verify: both artifacts present at `talks/draft_pilot_no_paper/00_phase0/`; audit JSONL shows `decision: originate` for both; cost ≤$0.10 (claim_inventory) + $0.00 (extract_methods).

D2.c Cross-check the originated `claim_inventory.tsv` against the reused-from-paper-writer version from D1. Should be byte-equivalent (modulo LLM non-determinism on a few `notes` rows per §B4.c).

**AC:** No-paper mode origination path produces both artifacts; outputs match (or near-match) the paper-writer-originated versions for the same project.

### D3. No-paper mode smoke (`functional_dark_matter`)

D3.a Run `phase0_reuse.py --project-dir <functional_dark_matter> --talk-draft-dir <talks/draft_pilot_fdm_no_paper> --artifact all --force-originate`. `functional_dark_matter` does not have a paper-writer draft, so `--force-originate` is redundant but harmless.

D3.b Verify: both artifacts present; audit JSONL shows `decision: originate`; cost ≤$0.10.

**AC:** No-paper mode works on a project where no paper-writer output exists at all; no spurious failures from missing-paper-draft checks.

### Tier D status (shipped 2026-05-21)

| Item | Status |
|---|---|
| Step 0 — re-vendor `extract_claims.v1.md` (39 → 79 lines; see Post-Tier-C) | ✅ done |
| D1 — paper-exists reuse smoke (`ibd_phage_targeting`, $0) | ✅ pass |
| D2 — no-paper originate smoke (`ibd_phage_targeting --force-originate`) | ✅ pass |
| D3 — no-paper originate smoke (`functional_dark_matter`) | ✅ pass |

**D1.** `phase0_reuse.py --artifact all` → `talks/draft_pilot_paper_exists/`.
Both artifacts `decision=reuse` from `papers/draft_2/` — most-recent-wins
correctly picked `draft_2` (the punch-list `draft_1` assumption was
stale: paper-writer is at v1.0.0 with `draft_1`,
`draft_1.pre-tier-s-snapshot`, `draft_2`). Both byte-identical to
`draft_2/`'s copies; `claim_inventory.tsv` 253 rows; 4-zone layout
created; idempotent re-run → `decision=no-op rationale=hashes_match`.

**D2.** `--force-originate` → `talks/draft_pilot_no_paper/`.
`extract_methods` deterministic ($0, 0.19 s). `extract_claims`
`claude -p` 369 s, exit 0. Validator: **219/219 rows resolve, 0
repaired, 0 cleared, 0 invalid** — the re-vendored prompt emitted full
`.ipynb` filenames with zero validator intervention (the Step 0
payoff).

**D3.** `--force-originate` → `talks/draft_pilot_fdm_no_paper/`.
`extract_methods` $0/0.22 s. `extract_claims` 225 s, exit 0. Validator:
**188/188 resolve, 0 repaired, 0 cleared, 0 invalid.** No spurious
failure from `functional_dark_matter`'s empty `papers/draft_1/` (only
`.DS_Store`).

**D2c cross-check — written AC superseded.** D1 reuse = 253 rows; D2
originate = 219. The "byte-equivalent modulo a few notes rows" AC was
unrealistic for an LLM *extract-every-numeric-claim* pass over a 300 KB
REPORT. Substantive checks all pass: 0 empty / 0 non-`.ipynb` / 0
invalid `source_notebook` in both; D2's 31 notebooks ⊂ D1's 32 (no
invented notebooks); 98 % of D2's numeric tokens (382/388) also in D1.
Variance is intrinsic — paper-writer's own two `ibd` drafts produced
341 and 253 claims (35 % spread); D2's 219-vs-253 (13 %) sits inside
that. Not a port bug; recorded as a documented deviation.

**Cost.** Not captured — `cost_usd: null` in both originate records
(Tier F5 gap; `extract_claims.py` does not parse stream-json).
Durations (369 s / 225 s) are the only proxy. Per
`feedback_cost_record_dont_gate` this is not a gate; the punch-list
`≤$0.10/run` ceiling is un-checkable from the audit until F5 lands.

---

## Tier E — Cross-skill contract drift filing + ship paperwork

Independent of D; can start after A4 / B5 land.

### E1. File cross-skill contract drift task on beril-adversarial

Per `feedback_cross_skill_contract_drift.md` + V0_4_ARCHITECTURE §10.1: the new `talks/draft_N/00_phase0/` subdirectory affects beril-adversarial's path detection for `--type presentation` reviews (per memory `project_adversarial_v0_5_x.md`, v0.5.2 last shifted that path logic).

E1.a Open an issue or memory-tracked task on beril-adversarial: "v0.4 presentation-maker introduces `talks/draft_N/00_phase0/<artifact>` subdirectory; ensure `adversarial_review.sh` path-detection logic handles this layout. Backwards-compat path: if `00_phase0/` absent, fall back to draft-dir top-level (today's behavior)."

E1.b Filed before M2 tags. Adversarial does not need to ship the fix before M2 — adversarial reviews v0.4 drafts at M3/M4 review-cascade phase, not M2 architect — but the task must exist.

**AC:** Task filed; reference recorded in V0_4_ARCHITECTURE.md §10.1 or a follow-up memory entry.

### E2. Update presentation-maker LAYOUT.md

E2.a Update `LAYOUT.md` §1 (repo tree) to list `extract_methods.py`, `claim_inventory.py`, `phase0_reuse.py` under `skill/tools/`; list `claim_demarcate.v1.md` under `skill/prompts/`.

E2.b Update `LAYOUT.md` §5 (output routing) to show the new `talks/draft_N/00_phase0/` subdirectory containing the four artifacts (per V0_4_ARCHITECTURE §4.6).

E2.c No changes to §6 (state.json schema) at M1 — phase enum updates land at M2 with the architect phase.

**AC:** LAYOUT.md reflects the M1 ship state.

### E3. Update V0_4_ARCHITECTURE.md M1 status

E3.a Change §16 M1 entry from "Vendor `claim_inventory.py` + `claim_demarcate.v1.md` from paper-writer..." to "**SHIPPED 2026-XX-XX.** Vendored... — see `project_presentation_maker_v0_4_m1.md`."

E3.b Front-matter status remains "SIGNED OFF — M0 complete..."; add "M1 shipped YYYY-MM-DD" line below.

**AC:** Memo accurately reflects M1 ship state.

### E4. Auto-memory entry

E4.a Write `project_presentation_maker_v0_4_m1.md` capturing: what shipped (the two vendor ports + reuse helper), test counts, smoke verdict (paper-exists + no-paper modes), watchpoints carried into M2 (architect prompt's input contract assumes both artifacts at `talks/draft_N/00_phase0/`).

**AC:** Memory entry written.

### E5. Update MEMORY.md index

E5.a Add one-line entry under Augmentation stream pointing at E4. Keep it terse (MEMORY.md is at soft-cap).

**AC:** Index updated.

### Tier E status (shipped 2026-05-21)

| Item | Status |
|---|---|
| E1 — cross-skill contract-drift check on beril-adversarial | ✅ done — **verified no drift; no task filed** |
| E2 — LAYOUT.md §1 + §5 | ✅ done |
| E3 — V0_4_ARCHITECTURE.md §16 + front-matter M1-SHIPPED | ✅ done |
| E4 — `project_presentation_maker_v0_4_m1.md` auto-memory entry | ✅ done |
| E5 — MEMORY.md index pointer | ✅ done |

**E1 — verified no drift; no task filed (deviation from the written
E1).** The punch list and the M0-memo watchpoint said to *file* a
consumer-update task on beril-adversarial because the new `00_phase0/`
subdir would affect its `--type presentation` path detection. That
premise no longer holds. The M0 watchpoint assumed Phase-0 artifacts at
draft-**root** `00_phase0/` (a 5th top-level entry); Tier C moved them
to `working/00_phase0/`, inside the `working/` zone.
`adversarial_review.sh`'s v0.5.2 layout detection (verified by reading
the script, lines 313-356) probes the exact path
`working/slide_spec.json` and reads fixed paths
(`working/03_slides/qa_anticipated.json`, `working/04_speaker_notes/`,
`narrative/00_throughline.md`, `narrative/02_substories.md`) — it never
zone-globs or counts draft-root entries. `working/00_phase0/` is
invisible to it; `audit/phase0.jsonl` does not collide with the
reviewer's `audit/adversarial_review.{md,json}`. Filing a task would be
make-work. Verification recorded in V0_4_ARCHITECTURE.md §10.1. The
genuine cross-skill item — reviewer awareness of
`01_deck_architecture.json` — is M2+ scope.

**E2.** LAYOUT.md §5 (output routing) already carried
`working/00_phase0/` + `audit/phase0.jsonl` (added during Tier C). §1
(repo tree) updated here: `tools/` gains `extract_methods.py`,
`extract_claims.py`, `validate_claim_inventory.py`, `phase0_reuse.py`,
`draft_paths.py`; `prompts/` gains `extract_claims.v1.md`. §6
(state.json) untouched — phase-enum changes land at M2.

**E3.** V0_4_ARCHITECTURE.md §16 M1 entry rewritten to **SHIPPED
2026-05-21**; front-matter status gained the M1-shipped line; §10.1
gained the E1 verification note.

---

## Tier F — Backlog (NOT M1 work)

Filed for M2:

- F1. `phase0_reuse.py` is the M1-shipped *helper*. M2's `presentation_maker.sh` orchestrator should invoke it at the new `phase0_tooling` phase (per V0_4_ARCHITECTURE §10.1 phase enum). The invocation contract is part of M2's orchestrator-rewrite scope, NOT M1. The shell layout vars `PHASE0_DIR` / `METHODS_PROVENANCE_PHASE0` / `CLAIM_INVENTORY_PHASE0` are already emitted by `draft_paths.shell_exports()` (C1.a).
- F2. Architect prompt's input wiring (consumes `methods_provenance.md` + `claim_inventory.tsv` from `working/00_phase0/`) lands at M2.
- F3. State.json v0.4 schema bump lands at M6 per D-038.
- F4. **M2 architect must distinguish `notebook-repaired:` (good — recovered provenance) from `unresolved-notebook:` (bad — genuinely unresolvable) note prefixes in `claim_inventory.tsv`.** Paper-writer's Tier I repair pass — **vendored 2026-05-21, validator now `0.2.0-stage3-tierI` (see Post-Tier-C section above)** — rewrites `source_notebook` in place to a full real filename on repair and prefixes `notes` with `notebook-repaired: <orig> -> <full>`. Any M2 logic that keys on the `unresolved-notebook:` prefix as the "bad provenance" signal MUST NOT lump the two — a repaired row carries trustworthy provenance. Source: paper-writer team reply 2026-05-14; repair pass now live in-tree.
- F5. **Wire real stream-json cost parsing into `extract_claims.py`.** Today `invoke_claude_extract()` runs plain `claude -p` and the diagnostic carries no `cost_usd` (Tier B simplification — the same gap paper-writer closed with `_run_claude_p_with_cost`). Consequence: `phase0_reuse.py`'s audit record carries `cost_usd: null` on the claim_inventory originate path. Fix is `--output-format stream-json` + parse the cost line into the diagnostic; then `phase0_reuse.py` can record a real number. Not M1 scope; deliberately kept out of B6 per "subtraction over addition."

---

## Dep edges

```
A1 → A2 → A3 ─┐
              ├→ C1 → C2 → D1 → D2 → D3 ─┐
B1 → B2 → B3 → B4 ─────────────────────────┤
                                            ├→ E2, E3, E4, E5 (ship paperwork)
              E1 (start after A2/B3) ──────┘
```

Tier A and Tier B run in parallel (no shared module). Tier C waits on both. Tier D waits on Tier C. Tier E ships after Tier D.

---

## Smoke gates

- **A3 smoke gate:** extract_methods on `ibd_phage_targeting` produces matched-to-paper-writer methods_provenance.md.
- **B4 smoke gate:** claim_inventory on `ibd_phage_targeting` produces ≥30 claim_ids, cost ≤$0.10, near-byte-equivalent to paper-writer's output.
- **D1 smoke gate:** paper-exists reuse path produces both artifacts for $0.
- **D2 smoke gate:** no-paper origination path produces both artifacts.
- **D3 smoke gate:** no-paper mode works on a second project (`functional_dark_matter`).

Failure at any smoke gate stops downstream work until the gate passes.

---

## What M1 does NOT do (carried into M2+)

- `deck_architect.v1.md` prompt (M2).
- Architect-architecture artifact (`01_deck_architecture.json`) (M2).
- Per-substory parallel composition (M3).
- Review cascade (M4).
- Image-gen multi-provider (M5).
- A/B cut-over gate (M6).

M1 is Phase-0 tooling only. It ships independently and v0.3.x default behavior is unchanged.

---

## Estimated effort

- Tier A: 3–4 hours focused (vendor + adapt + test + smoke).
- Tier B: 4–5 hours focused (longer source; more careful prompt-path resolution check).
- Tier C: 4–6 hours (new code; ~200 LOC + 12 tests).
- Tier D: 2–3 hours (smoke + cost verify + cross-check).
- Tier E: 1–2 hours (paperwork).

Total: 14–20 hours over 2–3 working days, assuming no smoke-gate failures forcing rework. Punch-list expected to absorb 2–4 patches in the smoke-test phase (D-tier) per the `feedback_punch_list_release_pattern.md` 4+ patch threshold.

---

## First action

A1.a + B1.a in parallel: copy both source files into presentation-maker's tree. Both are byte-portable and the parallel-port is the cheapest path to a green smoke.

When you're ready to start, I'll execute the copy + docstring adaptation + import adaptation for both files in one pass, run the unit-test smoke locally, and report.
