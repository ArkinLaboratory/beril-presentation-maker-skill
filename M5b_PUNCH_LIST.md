# M5b Punch List — AI Studio image-gen multi-provider

**Status:** drafted 2026-05-24 (post-M5a). Authoritative scope:
`V0_4_ARCHITECTURE.md` §14 + §16 M5b. DQ resolutions inlined below
(Adam's calls 2026-05-24).

**Posture.** Pure provider extension. The architecture doesn't
change (no new validators, no new cascade tiers, no new prompts).
`image_client.py` learns a second provider; the orchestrator's
auth-discovery block learns a second key; the calibration harness
re-runs against the new path so the worst-case cost cap stays
trustworthy.

## Per-tier status

| Tier | Scope | Status |
|---|---|---|
| A — `image_client.py` provider extension (dispatch + `_call_google_ai_studio` + rate card) | `tools/image_client.py` edit | ✅ ready to commit 2026-05-24 (new `ImageClient.google_ai_studio` classmethod + `_call_google_ai_studio` against native `:generateContent`; `_size_to_ai_studio_config` helper maps `(w,h)` → bucketed `aspectRatio`+`imageSize`; rate-card adds 3 May-2026 models; CLI `--provider` flag wired; **D-035 fallback chain updated to D-035-rev1** to match Google's May-2026 model names (`-preview` suffix on 3.x line) — Tier-A discovery via WebFetch of ai.google.dev docs; 24 new tests pin request shape + response parsing + 429 handling + dispatch + CLI; suite 1236 passed) |
| B — orchestrator auth discovery (mirror CBORG block for AI Studio) + `--image-provider` flag wiring | `tools/presentation_maker.sh` edit | ⬜ not started |
| C — model-availability probe + sidecar cache (`audit/ai_image_gen_probe.json`) + DQ3 fallback chain | `tools/image_client.py` (new helper) + orchestrator wire | ⬜ not started |
| D — SPEC.md §8.3 + DECISIONS.md D-062..D-064 + LAYOUT.md | docs | ⬜ not started |
| E — Tier-E live smoke: 1 image per path + AI Studio calibration re-run (`image_gen_calibration.py` against AI Studio) | live (~$0.55) | ⬜ not started |
| F — closeout (V0_4_ARCHITECTURE §16 M5b → SHIPPED; auto-memory) | paperwork | ⬜ not started |

## DQ resolutions (Adam 2026-05-24)

- **DQ1: Auth discovery home** — **(a) Shell orchestrator (mirror CBORG).**
  Extend the existing `presentation_maker.sh` block that resolves
  `CBORG_API_KEY` from env / `BERIL_ROOT/.env` to also resolve
  `GOOGLE_AI_STUDIO_API_KEY` the same way. Lands as **D-062**.
  Rationale: smallest blast radius; identical pattern; no new
  Python module; provider precedence decided in shell before
  invoking `image_client.py`.

- **DQ2: Model-availability probe cache** — **(a) Sidecar JSON in
  draft's audit dir** (`audit/ai_image_gen_probe.json`). Lands as
  **D-063**. Rationale: per-draft scope (probe re-runs on each new
  draft; one-time cost ~200ms); doesn't depend on the still-settling
  v0.4 state.json schema (M6 will migrate v0.3→v0.4); matches the
  audit-file pattern used throughout v0.4.

- **DQ3: AI Studio probe-failure posture** — **HYBRID: silent
  fallback to CBORG when `CBORG_API_KEY` is set; else loud-warning
  disable image-gen with full fallback-chain diagnostic.**
  Lands as **D-064**. Rationale: preserves the user's stated intent
  ("use my Gemini Studio license if available") while not breaking
  the run when the license is misconfigured. Always surfaces what
  was tried (which provider, which model fallback chain walked,
  which env vars detected) — the user is never silently downgraded
  without seeing the chain in stderr.

- **DQ4: Tier-E live spend** — **YES, full Tier E as scoped (~$0.55):**
  1 image per path on `ibd_phage_targeting/talk-30` + AI Studio
  calibration re-run (~13 trials at the new path). End state:
  `_WORST_CASE_COST_USD` calibrated for the AI Studio path; smoke
  confirms both paths render end-to-end. Adam's explicit go-ahead
  at the gate; no separate D-N.

## Tier A — `image_client.py` provider extension

Three sub-changes:

**A1. Dispatch.** Extend `ImageClient.__init__`'s provider arg from
`{"cborg"}` to `{"cborg", "google_ai_studio"}` (snake_case
internal). Add a `@classmethod google_ai_studio(cls, api_key, **kw)`
constructor matching the existing `cborg` classmethod. The
generate() dispatcher (currently a single `if self.provider ==
"cborg":` branch) grows an `elif self.provider == "google_ai_studio":`
branch calling `_call_google_ai_studio`. Else-branch error message
updated to name both providers.

**A2. `_call_google_ai_studio(prompt, model, size) → (bytes, usage)`.**
Native Google API shape (NOT CBORG's OpenAI-compat):
- URL: `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`
- Headers: `x-goog-api-key: <api_key>` + `Content-Type: application/json`
- Body: `{"contents":[{"parts":[{"text": prompt}]}], "generationConfig":{...}}`
  (size encoded in generationConfig per Google's image-output API;
  exact field name to be confirmed at Tier E first call — Google's
  docs at https://ai.google.dev/gemini-api/docs/image-generation
  are the authority).
- Response: image bytes at `candidates[0].content.parts[N].inline_data.data`
  (base64). Walk parts looking for the `inline_data` key (the LLM
  may emit a text part + an image part; order isn't guaranteed).
- Usage: extract from `usageMetadata.promptTokenCount` +
  `candidatesTokenCount` (Google's native names; differs from CBORG's
  OpenAI-compat `prompt_tokens`/`completion_tokens`).
- 429 handling per §14.2: detect, surface a clear error including
  the rate-limit header value if present, don't retry blindly.

**A3. Rate card.** Add `gemini-2.5-flash-image` to
`_MODEL_RATES_USD_PER_M` with AI Studio's published rate. Per §14.2
the conservative pre-calibration value is `_WORST_CASE_COST_USD = 0.08`
for the AI Studio path; Tier E re-calibrates and lowers if warranted.

For now: keep `_WORST_CASE_COST_USD` as a single constant (it's a
worst-case over both providers); use the higher value (0.08) until
Tier E. If Tier E shows AI Studio's actual mean is materially
different from CBORG's, split into per-provider worst-case in a
follow-up tier (not M5b).

**AC for A:** unit tests on dispatch (cborg path unchanged), the
new google_ai_studio classmethod, `_call_google_ai_studio` request
shape (mocked Session), response-parsing (base64 → bytes, usage
normalization), and the 429 surface. No live calls.

## Tier B — orchestrator auth discovery + `--image-provider` flag

**B1. Auth discovery (DQ1).** Extend the existing `presentation_maker.sh`
block (~line 356, "v0.3.3 image-gen: resolve CBORG_API_KEY"). After
the CBORG resolution, add a mirroring block that resolves
`GOOGLE_AI_STUDIO_API_KEY` (env → `$BERIL_ROOT/.env` parse → unset
if both fail). Same `.env` line-parse pattern (`^GOOGLE_AI_STUDIO_API_KEY=(.*)$`)
re-using the same Python heredoc — extend it to look for either key
in one pass.

**B2. Provider precedence.** After both resolutions:
- `--image-provider` CLI arg explicit → use it (caller error if the
  named provider's key isn't set).
- Else `GOOGLE_AI_STUDIO_API_KEY` set → `IMAGE_PROVIDER=google-ai-studio`.
- Else `CBORG_API_KEY` set → `IMAGE_PROVIDER=cborg`.
- Else: same fail as today's "no CBORG_API_KEY" path, but error
  message names both env vars.

**B3. `--image-provider` flag.** Add a long-form opt to the
orchestrator's CLI arg-parse (alongside `--ai-diagrams`,
`--max-image-cost-usd`); pass through as `--provider` to
`image_client.py`. (Note: `image_client.py`'s CLI currently lacks
`--provider`; Tier A adds it.)

**B4. Pass through to image_client.py invocation.** The existing
`image_client.py generate` invocation at `presentation_maker.sh:1809`
gains `--provider "$IMAGE_PROVIDER"` and uses the
provider-appropriate env var (`CBORG_API_KEY` vs
`GOOGLE_AI_STUDIO_API_KEY`). Same with `image_gen_calibration.py`
(Tier E will exercise both).

**AC for B:** unit test on the shell-snippet (extract → test via
`bash -c` against a synthetic .env); orchestrator CLI help string
mentions `--image-provider {cborg|google-ai-studio}`; downstream
`image_client.py` invocation receives the right provider name.

## Tier C — model-availability probe + sidecar cache + fallback chain

**C1. Probe (new function in `image_client.py`).**
`probe_available_models(api_key, *, base_url=None, timeout_s=10) → list[str]`.
- AI Studio path only (CBORG doesn't need a probe; we know it has
  the model).
- `GET https://generativelanguage.googleapis.com/v1beta/models`
  with `x-goog-api-key`. Returns the model `name` list (strip the
  `models/` prefix). Filter for ones whose `supportedGenerationMethods`
  includes `generateContent` AND whose `name` matches `gemini-*-image`.
- Errors → empty list (caller decides next action per DQ3).

**C2. Model resolution.**
`resolve_ai_studio_model(available_models) → str | None`.
- Fallback chain per D-035: `gemini-3-pro-image` (Adam's "use it if
  we see it") → `gemini-2.5-flash-image` → None.
- Pick first present in `available_models`.

**C3. Sidecar cache (DQ2).** New helper
`load_or_probe_ai_studio_model(api_key, audit_dir) → str`:
- If `<audit_dir>/ai_image_gen_probe.json` exists and was probed
  for the same api_key fingerprint (first 8 chars hash, NOT the
  raw key) → return cached `resolved_model`.
- Else: probe → resolve → write sidecar
  (`{"schema_version":"ai-image-gen-probe.v1", "api_key_fingerprint":
  "<hash>", "probed_at": iso, "available_models": [...],
  "resolved_model": "..."}`) → return resolved.

**C4. DQ3 fallback chain.** When `resolved_model is None` AND
provider was selected as `google_ai_studio`:
- If `CBORG_API_KEY` is set: stderr WARNING + silent fallback to
  CBORG (the orchestrator re-invokes with `--provider cborg`; or
  `image_client.py` itself accepts a `--fallback-provider` arg —
  TBD at Tier B/C boundary). Caches the fallback decision in the
  sidecar.
- Else: stderr LOUD WARNING (multi-line: "AI Studio image-gen
  unavailable. Probe chain walked: gemini-3-pro-image (absent),
  gemini-2.5-flash-image (absent). Available models: [...]. No
  CBORG_API_KEY for fallback. Image-gen disabled for this run.
  To use CBORG, set CBORG_API_KEY. To use a different AI Studio
  model, set GOOGLE_AI_STUDIO_MODEL=<name>.") + return a sentinel
  the orchestrator interprets as "disable image-gen this run"
  (mirrors the `--ai-diagrams off` path).

**C5. Manual override env var.** Add `GOOGLE_AI_STUDIO_MODEL` env
var that short-circuits the probe (skip probe; use the named
model). Useful for: (a) the loud-warning fix suggestion, (b)
debugging probe issues, (c) pinning a specific model for
reproducibility.

**AC for C:** unit tests on probe (mocked Session), resolve (each
fallback step), sidecar load/store (round-trip), DQ3 fallback
both branches (CBORG-present vs absent). Diagnostic strings
literally match the spec — pinned by test so they don't drift.

## Tier D — docs

**D1. `SPEC.md` §8.3** — add AI Studio provider; describe the
fallback chain; describe the `--image-provider` flag and
`GOOGLE_AI_STUDIO_API_KEY` + `GOOGLE_AI_STUDIO_MODEL` env vars.

**D2. `LAYOUT.md`** — update the `image_client.py` entry (now
supports two providers + the probe); orchestrator's
`presentation_maker.sh` description line that mentions
image-gen auth.

**D3. `DECISIONS.md` D-062..D-064** —
- **D-062:** auth-discovery home (DQ1).
- **D-063:** probe-cache mechanism (DQ2 sidecar JSON).
- **D-064:** probe-failure posture (DQ3 hybrid: silent CBORG
  fallback if available, else loud-warning disable).

**D4. `V0_4_ARCHITECTURE.md` §16 M5b** — split into M5b SHIPPED
block + carry-out items (same structure as M5a's SHIPPED block).

**AC for D:** docs render; DECISIONS chronological order
maintained; SPEC §8.3 + LAYOUT cross-references intact.

## Tier E — live smoke + AI Studio calibration

**E1. Smoke on both paths.** On `ibd_phage_targeting/talks/draft_1`
(M5a-closed), invoke `image_client.py generate` directly with one
short prompt against each path:
- CBORG path: confirm no regression (~$0.014).
- AI Studio path: confirm end-to-end render (~$0.04 worst case).

Both succeed → both image files exist + provenance.json updated.

**E2. AI Studio calibration re-run.** Run
`image_gen_calibration.py` against the AI Studio path with the
same 13-trial prompt set used in v0.3.3.2 CBORG calibration.
- Capture mean, σ, max observed cost.
- Update `_WORST_CASE_COST_USD` if the calibrated mean is
  materially different (or document why we keep the conservative
  $0.08 cap).
- Write `audit/image_gen_calibration_ai_studio_2026-05-24.md`
  with the calibration data (mirrors the v0.3.3.2 calibration
  artifact).

**E3. Provenance check.** Confirm `image_provenance.json` entries
for the smoke images include the right `model` (named for the
provider, e.g., `gemini-2.5-flash-image` for AI Studio, not
`gemini-3-pro-image` if AI Studio resolved to flash).

**AC for E:** both paths render an image; provenance reflects the
real provider+model; calibration artifact written; cost-cap
constant updated (or rationale documented if unchanged).

## Tier F — closeout

`V0_4_ARCHITECTURE.md` §16 M5b → SHIPPED; `LAYOUT.md` updated;
this punch list's status table; auto-memory
`project_presentation_maker_v0_4_m5b.md` + MEMORY.md index line.

## Dep edges

```
A ──┬──> C (probe needs the AI Studio dispatch in place)
    └──> B (orchestrator passes --provider to A's CLI)
B ──> E (live spend needs orchestrator wiring)
C ──> E (probe needs to work before calibration can pick a model)
D ─── runs anytime after A+B+C land (paperwork)
F ─── after E
```

A is the foundation. B+C are independent of each other (one is
shell, one is Python) but both depend on A's CLI surface. E
integrates everything. D + F are paperwork.

## Smoke gates

- **A gate:** unit tests on dispatch + `_call_google_ai_studio`
  request shape (mocked) + response parsing + 429 surface; CBORG
  tests still green; rate-card test pins the new entry.
- **B gate:** orchestrator shell-snippet test (synthetic .env);
  CLI `--image-provider` flag wired; downstream invocation
  receives the right provider arg.
- **C gate:** probe + resolve + sidecar round-trip tests;
  DQ3 fallback branches both tested (CBORG-present vs absent);
  diagnostic-string pin test.
- **E gate:** 1 image per path renders; calibration artifact
  exists; constant updated or rationale recorded.

## What M5b does NOT do (→ later milestones)

- **OpenAI gpt-image-1 provider** (mentioned in v0.2 reserves in
  `image_client.py`'s docstring). Defer — Adam hasn't asked for
  it; AI Studio fills the user-license intent.
- **Per-provider `_WORST_CASE_COST_USD` split** (mentioned in
  Tier A.3). Defer to a follow-up only if Tier E shows the two
  providers' cost distributions are materially different.
- **Vision-LLM `quant_content_score` real implementation** (today's
  v0.1 stub returns 0.0). Orthogonal to provider extension; defer.
- **State-schema v0.3 → v0.4 migration** (M6).
- **A/B test + cut-over decision** (M6).

## Cost estimate

| Tier | Estimate |
|---|---|
| A — image_client.py extension | 3–4 h (dispatch + new provider + tests) |
| B — orchestrator wiring | 1–2 h (shell snippet + CLI flag + tests) |
| C — probe + sidecar + fallback | 3–4 h (probe + resolve + cache + DQ3 chain + tests) |
| D — docs | 1 h (SPEC + LAYOUT + DECISIONS + arch) |
| E — live smoke + calibration | 1–2 h wall-clock (+ ~$0.55 spend) |
| F — closeout | 0.5 h paperwork |
| **Total** | ~10–14 h coding; ~$0.55 live spend |

## Ref

- `V0_4_ARCHITECTURE.md` §14 (image-gen multi-provider) + §16 M5b.
- `src/beril_presentation_maker/skill/tools/image_client.py`
  (today's implementation; CBORG-only).
- `src/beril_presentation_maker/skill/tools/image_gen_calibration.py`
  (calibration harness; CBORG-only today).
- `src/beril_presentation_maker/skill/tools/presentation_maker.sh`
  lines 356–378 (CBORG auth-discovery block; B1 mirrors it),
  line 1809 (image_client.py invocation; B4 extends it).
- `DECISIONS.md` D-035 (model fallback chain).
- M5a punch-list pattern (same six-tier shape).
