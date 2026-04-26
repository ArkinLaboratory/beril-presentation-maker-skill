#!/usr/bin/env python3
"""image_client.py — AI image-generation client (CBORG-Gemini default).

Per SPEC §8.3 + DECISIONS D-005-rev1, D-006. Tier 3 figure handling for
the `concept_illustration` slide layout. Default OFF (`--ai-diagrams off`);
enabled per-image via Channel A (LLM-proposed, opt-in flag) or Channel B
(user-requested at any pause point).

Provider abstraction:

  Default: CBORG (https://api.cborg.lbl.gov), model
  google/gemini-pro-image. Auth via CBORG_API_KEY env var (or .env at
  BERIL_ROOT — discovered upstream by configure).

  v0.2 reserves: direct Google AI Studio (GOOGLE_AI_STUDIO_API_KEY) and
  OpenAI gpt-image-1 (OPENAI_API_KEY) as alternatives if CBORG quality
  disappoints on conceptual illustrations.

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
DEFAULT_MODEL = "google/gemini-pro-image"

# Per-million-token cost estimates for cost-cap enforcement.
# Source: cborg.lbl.gov/models/ — gemini-pro-image: $2 / $12 per M tokens.
# (Image-gen tokens are different from text tokens; output_tokens include
# the encoded image, ~32K tokens at the model's max.)
_MODEL_RATES_USD_PER_M = {
    "google/gemini-pro-image":         {"input": 2.00, "output": 12.00},
    "google/gemini-3-pro-image":       {"input": 2.00, "output": 12.00},
    "google/gemini-3-pro-image-preview": {"input": 2.00, "output": 12.00},
}

# Channel labels per SPEC §8.3 two-channel design.
CHANNEL_A = "A"   # LLM-proposed (global flag opt-in)
CHANNEL_B = "B"   # user-requested (interactive override; bypasses Channel A)


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

        # Cost pre-flight (worst-case at this model's max output tokens).
        # Gemini-pro-image tops at ~32K output tokens per image. Estimate
        # ~10K input tokens (prompt + system).
        worst_cost = self.estimate_cost_usd(model, input_tokens=10_000,
                                            output_tokens=32_000)
        if budget_remaining_usd is not None and worst_cost > budget_remaining_usd:
            raise BudgetExceeded(
                f"image-gen worst-case ${worst_cost:.3f} > "
                f"remaining budget ${budget_remaining_usd:.3f}"
            )

        start = time.time()
        if self.provider == "cborg":
            image_bytes, usage = self._call_cborg(prompt, model, size)
        else:
            raise ImageClientError(
                f"provider {self.provider!r} not implemented in v0.1; "
                f"only 'cborg' supported. Direct Google / OpenAI keys are "
                f"v0.2 (D-006 / SPEC §8.3)."
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
            raise ImageClientError(f"CBORG request failed: {e}") from e

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
    api_key = args.api_key or os.environ.get("CBORG_API_KEY")
    if not api_key:
        print("CBORG_API_KEY not set (and --api-key not provided)",
              file=sys.stderr)
        return 3
    client = ImageClient.cborg(api_key=api_key, model=args.model)
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
    p_gen.add_argument("--model", default=DEFAULT_MODEL)
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
