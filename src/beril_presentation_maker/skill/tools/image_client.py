#!/usr/bin/env python3
"""image_client.py — AI image-generation client (multi-provider).

Per SPEC §8.3 + DECISIONS D-005-rev1, D-006, D-062..D-064. Tier 3 figure
handling for the `concept_illustration` slide layout. Default OFF
(`--ai-diagrams off`); enabled per-image via Channel A (LLM-proposed,
opt-in flag) or Channel B (user-requested at any pause point).

Provider abstraction:

  Default: CBORG (https://api.cborg.lbl.gov), model
  google/gemini-pro-image. Auth via CBORG_API_KEY env var (or .env at
  BERIL_ROOT — discovered upstream by the orchestrator).

  M5b (D-062): direct Google AI Studio (GOOGLE_AI_STUDIO_API_KEY).
  Native Gemini API at generativelanguage.googleapis.com/v1beta;
  `gemini-3.1-flash-image-preview` (Nano Banana 2) is the May-2026
  primary; pro lineage `gemini-3-pro-image-preview` and prior-gen
  `gemini-2.5-flash-image` are the fallback chain (resolve_ai_studio_model).
  Provider selected by the orchestrator (presentation_maker.sh) based
  on env-var precedence; per-draft probe cache lives at
  `audit/ai_image_gen_probe.json` (D-063).

  Future: OpenAI gpt-image-1 (OPENAI_API_KEY) as an alternative — not
  scheduled (not in the user's stated provider-needs).

Constraints (enforced here):
  - Per-image cost cap (caller supplies budget_remaining_usd).
  - LLM-as-judge `quant_content_score` (0.0–1.0) — caller rejects if
    >0.5 (SPEC §8.3 forbids quantitative content in AI-gen images).
  - Provenance recording (model, cost, channel, approved_at,
    quant_content_score) — written to image_provenance.json by the
    orchestrator.

This module does NOT implement the per-image user-approval gate — that
lives in the orchestrator (presentation_maker.sh, v0.1.0-prompts).
This module just generates an image given an approved prompt.

CLI:

    python3 image_client.py generate \\
        --prompt "..." --out img.png --budget 5.00 \\
        [--model google/gemini-pro-image]

Library:

    from image_client import ImageClient, ImageResult, BudgetExceeded
    client = ImageClient.cborg(api_key=os.environ["CBORG_API_KEY"])
    result = client.generate(
        prompt="A glowing brain made of microbes",
        purpose="metaphor",
        size=(1024, 1024),
        budget_remaining_usd=5.00,
    )
    if result.quant_content_score > 0.5:
        # reject + fall back to Tier 2 procedural diagram
        ...

Tests live at tests/unit/test_image_client.py. Live API tests are
gated behind the `image_gen` pytest marker (cost; deselected by
default).
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CBORG_BASE_URL = "https://api.cborg.lbl.gov"
DEFAULT_AI_STUDIO_BASE_URL = "https://generativelanguage.googleapis.com"
# 2026-04-30: CBORG model inventory uses bare names (not google/-prefixed).
# Default to gemini-3-pro-image (Gemini 3's image-gen, "nanobanana pro")
# — better text handling than gemini-pro-image. Override via --model.
DEFAULT_MODEL = "gemini-3-pro-image"
# AI Studio default if no probe cache hits — the primary May-2026 model
# per https://ai.google.dev/gemini-api/docs/image-generation. The probe
# (Tier C) walks the D-035-rev1 fallback chain and may pick a different
# model.
DEFAULT_AI_STUDIO_MODEL = "gemini-3.1-flash-image-preview"

# Per-million-token cost estimates for cost-cap enforcement.
# Source: cborg.lbl.gov/models/ — gemini image-gen models: $2 / $12 per M tokens.
# AI Studio rates from https://ai.google.dev/pricing — different lineage but
# the same general scale; calibrated via image_gen_calibration.py against
# each provider before _WORST_CASE_COST_USD is treated as load-bearing
# (image-gen tokens are different from text tokens; output_tokens include
# the encoded image, ~32K tokens at the model's max).
_MODEL_RATES_USD_PER_M = {
    # CBORG (proxied Google models, OpenAI-compat surface)
    "gemini-pro-image":                  {"input": 2.00, "output": 12.00},
    "gemini-3-pro-image":                {"input": 2.00, "output": 12.00},
    # Legacy google/-prefixed aliases — kept so old callers don't break,
    # but CBORG itself expects the bare names above.
    "google/gemini-pro-image":           {"input": 2.00, "output": 12.00},
    "google/gemini-3-pro-image":         {"input": 2.00, "output": 12.00},
    "google/gemini-3-pro-image-preview": {"input": 2.00, "output": 12.00},
    # AI Studio native (M5b/D-062). Conservative input/output rates until
    # image_gen_calibration.py runs against AI Studio (M5b Tier E).
    # Sourced from ai.google.dev/pricing (May 2026 published numbers).
    "gemini-3.1-flash-image-preview":    {"input": 0.30, "output": 30.00},
    "gemini-3-pro-image-preview":        {"input": 1.25, "output": 30.00},
    "gemini-2.5-flash-image":            {"input": 0.30, "output": 30.00},
}

# AI Studio fallback chain (D-035-rev1, M5b Tier A discovery: Google's
# May-2026 model lineup has shifted — the original D-035 chain
# `gemini-3-pro-image → gemini-2.5-flash-image → fail` is updated to
# match the actual published model names with `-preview` suffix on the
# 3.x line). probe_available_models() + resolve_ai_studio_model() pick
# the first present in this list.
AI_STUDIO_MODEL_FALLBACK_CHAIN = (
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
)

# Channel labels per SPEC §8.3 two-channel design.
CHANNEL_A = "A"   # LLM-proposed (global flag opt-in)
CHANNEL_B = "B"   # user-requested (interactive override; bypasses Channel A)


# AI Studio's image API accepts aspectRatio + imageSize (bucketed
# enums) — NOT free-form (width, height). Existing callers pass
# (width, height) tuples (e.g., (1024, 1024)); map to the closest
# supported bucket. CBORG's OpenAI-compat path keeps the WxH string
# form, so this mapping is only used on the AI Studio path.
#
# Supported AI Studio aspect ratios (per
# https://ai.google.dev/gemini-api/docs/image-generation, May 2026):
#   1:1, 2:3, 3:2, 4:3, 3:4, 16:9, 9:16, 4:5, 5:4, 21:9
# Supported imageSize values: "512", "1K", "2K", "4K".
_AI_STUDIO_ASPECT_RATIOS = (
    (1.0, "1:1"),
    (2.0 / 3.0, "2:3"),
    (3.0 / 2.0, "3:2"),
    (4.0 / 3.0, "4:3"),
    (3.0 / 4.0, "3:4"),
    (16.0 / 9.0, "16:9"),
    (9.0 / 16.0, "9:16"),
    (4.0 / 5.0, "4:5"),
    (5.0 / 4.0, "5:4"),
    (21.0 / 9.0, "21:9"),
)


def _size_to_ai_studio_config(size: tuple[int, int]) -> tuple[str, str]:
    """Map (width, height) → (aspectRatio, imageSize) bucket pair for
    AI Studio's responseFormat.image. Picks the closest supported
    aspectRatio by ratio distance, and the smallest imageSize bucket
    whose max-dimension covers the request.

    Example: (1024, 1024) → ("1:1", "1K")
    Example: (1920, 1080) → ("16:9", "2K")
    """
    width, height = size
    if width <= 0 or height <= 0:
        return "1:1", "1K"
    requested_ratio = width / height
    best = min(_AI_STUDIO_ASPECT_RATIOS,
               key=lambda pair: abs(pair[0] - requested_ratio))
    aspect_ratio = best[1]
    max_dim = max(width, height)
    if max_dim <= 512:
        image_size = "512"
    elif max_dim <= 1024:
        image_size = "1K"
    elif max_dim <= 2048:
        image_size = "2K"
    else:
        image_size = "4K"
    return aspect_ratio, image_size


# Worst-case cost preflight bound. v0.3.3.2 (#62) recalibrated against
# v0.3.0's 13-trial calibration data:
#   - 13 successful trials, total spend $0.177
#   - mean $0.014 / image, σ small
#   - max observed ~$0.018
# Pre-recalibration value was 32K-output × $12/M = $0.404 — 30× over the
# calibrated mean, which (a) was rejecting legitimate $0.10 caps mid-
# pipeline AFTER the API call had spent real money on the upstream
# ai_image_prompt LLM (~$0.14 wasted on each false-positive reject),
# and (b) led users to default --max-image-cost-usd 0.50 just to
# satisfy the preflight even when their actual budget was $0.10.
#
# New bound: $0.05 — ~3.7× calibrated mean, generous headroom against
# rate-card drift, but tight enough that --max-image-cost-usd 0.10
# clears (~7 images per cap rather than ~12 falsely rejected ones).
# Re-run image_gen_calibration.py if the model id or rate card changes.
#
# M5b status: shared constant across both providers until M5b Tier E
# calibrates the AI Studio path. AI Studio's `gemini-2.5-flash-image`
# has different per-image token economics from CBORG's
# `gemini-3-pro-image`; the $0.05 cap is held provisionally and re-
# evaluated at Tier E. If AI Studio's calibrated mean is materially
# higher, the band test below will flag it and a per-provider split
# may be warranted (deferred follow-up; not in M5b scope).
_WORST_CASE_COST_USD = 0.05


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ImageResult:
    """One image-generation result, including provenance."""
    image_bytes: bytes
    model: str
    prompt: str
    cost_usd: float
    elapsed_seconds: float
    channel: str             # "A" (LLM-proposed) | "B" (user-requested)
    approved_at: str         # ISO-8601
    quant_content_score: Optional[float] = None  # set by judge step
    error: Optional[str] = None

    def to_provenance_dict(self) -> dict:
        """Provenance dict for image_provenance.json (per SPEC §8.3)."""
        return {
            "model": self.model,
            "prompt": self.prompt,
            "cost_usd": self.cost_usd,
            "elapsed_seconds": self.elapsed_seconds,
            "channel": self.channel,
            "approved_at": self.approved_at,
            "quant_content_score": self.quant_content_score,
        }


class ImageClientError(RuntimeError):
    """Base for image-client errors."""


class BudgetExceeded(ImageClientError):
    """Raised when generating an image would exceed the per-draft budget."""


class QuantContentRejected(ImageClientError):
    """Raised when the LLM-as-judge score >0.5 (image contains
    quantitative content; reject per SPEC §8.3)."""


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class ImageClient:
    """Image-generation client. Default provider: CBORG."""

    def __init__(
        self,
        provider: str = "cborg",
        base_url: str = DEFAULT_CBORG_BASE_URL,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        timeout_s: int = 120,
        request_session: requests.Session | None = None,
    ):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        # Allow tests to inject a mock session
        self._session = request_session or requests.Session()

    @classmethod
    def cborg(cls, api_key: str, **kwargs) -> "ImageClient":
        return cls(provider="cborg", base_url=DEFAULT_CBORG_BASE_URL,
                   api_key=api_key, **kwargs)

    @classmethod
    def google_ai_studio(cls, api_key: str,
                         model: str = DEFAULT_AI_STUDIO_MODEL,
                         **kwargs) -> "ImageClient":
        """Construct an ImageClient that talks to AI Studio's native
        Gemini API. M5b/D-062.

        Caller is responsible for resolving the model via
        resolve_ai_studio_model() (Tier C) before constructing; this
        constructor accepts the resolved model name and doesn't probe.
        """
        return cls(provider="google_ai_studio",
                   base_url=DEFAULT_AI_STUDIO_BASE_URL,
                   model=model, api_key=api_key, **kwargs)

    # -----------------------------------------------------------------------
    # Cost estimation
    # -----------------------------------------------------------------------

    @staticmethod
    def estimate_cost_usd(model: str,
                          input_tokens: int = 0,
                          output_tokens: int = 0) -> float:
        """Estimate USD cost for an image-gen call. Falls back to 0.0 for
        unknown models."""
        rates = _MODEL_RATES_USD_PER_M.get(model)
        if rates is None:
            return 0.0
        return (input_tokens * rates["input"]
                + output_tokens * rates["output"]) / 1_000_000

    # -----------------------------------------------------------------------
    # Generation
    # -----------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        purpose: str = "conceptual_illustration",
        size: tuple[int, int] = (1024, 1024),
        budget_remaining_usd: float | None = None,
        channel: str = CHANNEL_A,
        model: str | None = None,
    ) -> ImageResult:
        """Generate one image. Returns an ImageResult. The caller is
        responsible for the user-approval gate, the quant-content judge
        rejection, and writing image_provenance.json.

        Args:
          prompt: free-form text prompt (already user-approved at the
                  orchestrator level).
          purpose: "metaphor" | "infographic" | "conceptual_diagram" |
                   "conceptual_illustration" — passed to the provider as
                   metadata; ignored by CBORG / Vertex but kept for
                   provider-abstraction parity.
          size: (width, height) in pixels.
          budget_remaining_usd: caller-supplied — if the worst-case cost
            for this call would exceed it, raises BudgetExceeded BEFORE
            making the API call.
          channel: "A" (LLM-proposed) or "B" (user-requested).
          model: optional model override.

        Raises:
          BudgetExceeded if estimated cost > budget_remaining_usd.
          ImageClientError on HTTP / API failure.
        """
        model = model or self.model

        # Cost pre-flight (worst-case bound). v0.3.3.2 (#62): recalibrated
        # constant ($0.05) replaces the 32K-output token-rate estimate
        # ($0.404) that was 30× the calibrated mean. See _WORST_CASE_COST_USD
        # docstring for rationale and re-calibration trigger.
        worst_cost = _WORST_CASE_COST_USD
        if budget_remaining_usd is not None and worst_cost > budget_remaining_usd:
            raise BudgetExceeded(
                f"image-gen worst-case ${worst_cost:.3f} > "
                f"remaining budget ${budget_remaining_usd:.3f} "
                f"(calibrated mean ~$0.014/image; raise "
                f"--max-image-cost-usd or check budget)"
            )

        start = time.time()
        if self.provider == "cborg":
            image_bytes, usage = self._call_cborg(prompt, model, size)
        elif self.provider == "google_ai_studio":
            image_bytes, usage = self._call_google_ai_studio(prompt, model, size)
        else:
            raise ImageClientError(
                f"provider {self.provider!r} not implemented; supported "
                f"providers: 'cborg' (CBORG_API_KEY) and 'google_ai_studio' "
                f"(GOOGLE_AI_STUDIO_API_KEY, M5b/D-062). See SPEC §8.3."
            )
        elapsed = time.time() - start

        cost = self.estimate_cost_usd(model,
                                      input_tokens=usage.get("input_tokens", 0),
                                      output_tokens=usage.get("output_tokens", 0))

        return ImageResult(
            image_bytes=image_bytes,
            model=model,
            prompt=prompt,
            cost_usd=cost,
            elapsed_seconds=elapsed,
            channel=channel,
            approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    # -----------------------------------------------------------------------
    # Provider implementations
    # -----------------------------------------------------------------------

    def _call_cborg(
        self,
        prompt: str,
        model: str,
        size: tuple[int, int],
    ) -> tuple[bytes, dict]:
        """POST to CBORG's image-generation endpoint. Returns (image_bytes,
        usage_dict).

        CBORG proxies provider-native API shapes; for Google Vertex AI
        image models it accepts the OpenAI-compatible /v1/images/generations
        shape. Image returned as base64 in `data[0].b64_json`. (This API
        contract is unverified at v0.1; see SPEC §20.2 — Gemini quality
        + endpoint may need tweaking on first live test.)
        """
        if not self.api_key:
            raise ImageClientError(
                "no api_key set; pass api_key=... or set CBORG_API_KEY env var"
            )
        url = f"{self.base_url}/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "prompt": prompt,
            "size": f"{size[0]}x{size[1]}",
            "n": 1,
            "response_format": "b64_json",
        }
        try:
            resp = self._session.post(url, headers=headers, json=payload,
                                       timeout=self.timeout_s)
            resp.raise_for_status()
        except requests.RequestException as e:
            # Surface the response body too — 400/422 errors typically
            # carry diagnostic JSON ({"error": {"message": "..."}}). The
            # status-line alone isn't actionable.
            body = ""
            try:
                if hasattr(e, "response") and e.response is not None:
                    body = e.response.text[:1000]
            except Exception:  # noqa: BLE001
                pass
            raise ImageClientError(
                f"CBORG request failed: {e}\n"
                f"  request payload: {json.dumps(payload)}\n"
                f"  response body: {body}"
            ) from e

        data = resp.json()
        try:
            b64 = data["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as e:
            raise ImageClientError(
                f"CBORG response missing data[0].b64_json: {data}"
            ) from e

        image_bytes = base64.b64decode(b64)
        usage = data.get("usage", {})
        # Normalize usage keys (CBORG-via-Gemini uses "promptTokenCount" /
        # "candidatesTokenCount" sometimes; OpenAI shape uses
        # "prompt_tokens" / "completion_tokens"). Permissive lookup.
        normalized = {
            "input_tokens": int(
                usage.get("input_tokens",
                          usage.get("prompt_tokens",
                                    usage.get("promptTokenCount", 0)))
            ),
            "output_tokens": int(
                usage.get("output_tokens",
                          usage.get("completion_tokens",
                                    usage.get("candidatesTokenCount", 0)))
            ),
        }
        return image_bytes, normalized

    def _call_google_ai_studio(
        self,
        prompt: str,
        model: str,
        size: tuple[int, int],
    ) -> tuple[bytes, dict]:
        """POST to AI Studio's native Gemini :generateContent endpoint.
        Returns (image_bytes, usage_dict). M5b/D-062.

        API contract per https://ai.google.dev/gemini-api/docs/image-generation
        (verified 2026-05-24 — May 2026 Gemini API).

        Request shape:
          POST /v1beta/models/<MODEL>:generateContent
          Headers: x-goog-api-key, Content-Type
          Body: {"contents":[{"parts":[{"text": prompt}]}],
                 "generationConfig":{"responseModalities":["IMAGE"],
                                     "responseFormat":{"image":{
                                       "aspectRatio": "1:1"|...,
                                       "imageSize": "1K"|"2K"|...}}}}

        Response shape: image bytes at
          candidates[0].content.parts[N].inlineData.data (base64).
          Walk parts looking for inlineData — model may emit a text
          part + an image part in either order.
          Usage at usageMetadata.{promptTokenCount, candidatesTokenCount}.
        """
        if not self.api_key:
            raise ImageClientError(
                "no api_key set; pass api_key=... or set "
                "GOOGLE_AI_STUDIO_API_KEY env var"
            )
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        aspect_ratio, image_size = _size_to_ai_studio_config(size)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "responseFormat": {
                    "image": {
                        "aspectRatio": aspect_ratio,
                        "imageSize": image_size,
                    },
                },
            },
        }
        try:
            resp = self._session.post(url, headers=headers, json=payload,
                                       timeout=self.timeout_s)
            resp.raise_for_status()
        except requests.RequestException as e:
            body = ""
            status = None
            try:
                if hasattr(e, "response") and e.response is not None:
                    body = e.response.text[:1000]
                    status = e.response.status_code
            except Exception:  # noqa: BLE001
                pass
            # 429: surface clearly per §14.2 rate-limit handling — AI
            # Studio's free tier rate-limits aggressively; per-image
            # approval gate is the natural spacer, but the user needs
            # to see the 429 distinctly so they don't blame the model
            # selection for a quota issue.
            if status == 429:
                raise ImageClientError(
                    f"AI Studio rate-limited (HTTP 429). Wait or check "
                    f"your AI Studio quota tier "
                    f"(https://ai.google.dev/gemini-api/docs/rate-limits). "
                    f"Response: {body}"
                ) from e
            raise ImageClientError(
                f"AI Studio request failed: {e}\n"
                f"  endpoint: {url}\n"
                f"  response body: {body}"
            ) from e

        data = resp.json()
        # Walk candidates[0].content.parts looking for inlineData (the
        # image bytes). Google's API may emit a text part alongside —
        # take the first part that has inlineData.data.
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as e:
            raise ImageClientError(
                f"AI Studio response missing candidates[0].content.parts: {data}"
            ) from e
        b64 = None
        mime_type = None
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if isinstance(inline, dict) and inline.get("data"):
                b64 = inline["data"]
                mime_type = inline.get("mimeType") or inline.get("mime_type")
                break
        if b64 is None:
            raise ImageClientError(
                f"AI Studio response had no inlineData part among "
                f"{len(parts)} parts: {data}"
            )
        if mime_type and not mime_type.startswith("image/"):
            # Defensive: don't assume bytes are an image if the model
            # somehow returned audio/text inline_data.
            raise ImageClientError(
                f"AI Studio returned non-image inlineData (mimeType="
                f"{mime_type!r}); refusing to write."
            )

        image_bytes = base64.b64decode(b64)
        usage = data.get("usageMetadata", {})
        # AI Studio uses camelCase names (promptTokenCount,
        # candidatesTokenCount). Normalize to the same shape as
        # _call_cborg so the caller's cost-estimate path is uniform.
        normalized = {
            "input_tokens": int(usage.get("promptTokenCount", 0)),
            "output_tokens": int(usage.get("candidatesTokenCount", 0)),
        }
        return image_bytes, normalized

    # -----------------------------------------------------------------------
    # Quant-content judge
    # -----------------------------------------------------------------------

    def score_quantitative_content(
        self,
        image_bytes: bytes,
        *,
        judge_model: str = "claude-sonnet-4-6",
    ) -> float:
        """Run an LLM-as-judge pass to score whether the image contains
        quantitative claims (axes labels, data values, numeric annotations).

        Returns a float in [0.0, 1.0]. 0.0 = no quantitative content;
        1.0 = obvious quantitative content. Caller rejects if >0.5
        (SPEC §8.3).

        Implementation note: v0.1 stub returns 0.0 for all images. Real
        vision-LLM integration ships in v0.2 — the orchestrator can
        invoke `claude -p` with a vision tool against the image bytes.
        Until then, the user-approval gate is the load-bearing safety.
        """
        # TODO(v0.2): vision-LLM integration via CBORG / direct provider.
        # The structure is: base64-encode image_bytes, send as a
        # `image_url` content block to claude-sonnet-4-6, ask the score
        # question, parse the score from the response.
        return 0.0


# ---------------------------------------------------------------------------
# Provenance file I/O
# ---------------------------------------------------------------------------

def append_provenance(
    provenance_path: Path,
    result: ImageResult,
    *,
    image_path: Path | str | None = None,
) -> None:
    """Append an entry to image_provenance.json (creating if absent).

    Schema:
        {
          "version": "1.0",
          "entries": [
            {
              "image_path": "...",
              "model": "...",
              "prompt": "...",
              "cost_usd": ...,
              "elapsed_seconds": ...,
              "channel": "A"|"B",
              "approved_at": "...",
              "quant_content_score": ...,
            },
            ...
          ]
        }
    """
    provenance_path = Path(provenance_path)
    if provenance_path.is_file():
        try:
            existing = json.loads(provenance_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {"version": "1.0", "entries": []}
    else:
        existing = {"version": "1.0", "entries": []}

    entry = result.to_provenance_dict()
    if image_path is not None:
        entry["image_path"] = str(image_path)
    existing["entries"].append(entry)

    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(existing, indent=2) + "\n",
                                encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_generate(args: argparse.Namespace) -> int:
    """Generate one image, save bytes + provenance."""
    provider = args.provider
    if provider == "cborg":
        api_key = args.api_key or os.environ.get("CBORG_API_KEY")
        if not api_key:
            print("CBORG_API_KEY not set (and --api-key not provided)",
                  file=sys.stderr)
            return 3
        model = args.model or DEFAULT_MODEL
        client = ImageClient.cborg(api_key=api_key, model=model)
    elif provider == "google_ai_studio":
        api_key = args.api_key or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
        if not api_key:
            print("GOOGLE_AI_STUDIO_API_KEY not set (and --api-key not "
                  "provided)", file=sys.stderr)
            return 3
        # When --provider google_ai_studio without an explicit --model,
        # default to the M5b primary. Tier C's probe is the canonical
        # resolver; the CLI is the bare-metal path that doesn't probe.
        model = args.model or DEFAULT_AI_STUDIO_MODEL
        client = ImageClient.google_ai_studio(api_key=api_key, model=model)
    else:
        print(f"unknown --provider {provider!r}; expected "
              f"'cborg' or 'google_ai_studio'", file=sys.stderr)
        return 3
    try:
        result = client.generate(
            prompt=args.prompt,
            size=(args.width, args.height),
            budget_remaining_usd=args.budget,
            channel=args.channel,
        )
    except BudgetExceeded as e:
        print(f"image_client: {e}", file=sys.stderr)
        return 4
    except ImageClientError as e:
        print(f"image_client: {e}", file=sys.stderr)
        return 2

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.image_bytes)
    print(f"wrote {out} ({len(result.image_bytes):,} bytes; "
          f"~${result.cost_usd:.3f}; {result.elapsed_seconds:.1f}s)",
          file=sys.stderr)

    if args.provenance:
        append_provenance(args.provenance, result, image_path=out)
        print(f"appended provenance: {args.provenance}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="image_client",
                                description="AI image-gen client (CBORG default).")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="Generate one image and save it.")
    p_gen.add_argument("--prompt", required=True)
    p_gen.add_argument("--out", required=True, help="Output image path (e.g., img.png).")
    p_gen.add_argument("--budget", type=float, default=5.00,
                       help="Remaining budget for this draft (USD); "
                            "if worst-case cost would exceed, exit 4.")
    p_gen.add_argument("--provider", choices=["cborg", "google_ai_studio"],
                       default="cborg",
                       help="Image-gen provider. 'cborg' (default) reads "
                            "CBORG_API_KEY; 'google_ai_studio' reads "
                            "GOOGLE_AI_STUDIO_API_KEY (M5b/D-062).")
    p_gen.add_argument("--model", default=None,
                       help="Model name. Defaults: 'gemini-3-pro-image' "
                            "(cborg) / 'gemini-3.1-flash-image-preview' "
                            "(google_ai_studio). Tier-C probe is the "
                            "canonical resolver for google_ai_studio.")
    p_gen.add_argument("--width", type=int, default=1024)
    p_gen.add_argument("--height", type=int, default=1024)
    p_gen.add_argument("--channel", choices=["A", "B"], default="A")
    p_gen.add_argument("--api-key", help="Override CBORG_API_KEY env var.")
    p_gen.add_argument("--provenance",
                       help="Append-to path for image_provenance.json.")
    p_gen.set_defaults(func=_cmd_generate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
