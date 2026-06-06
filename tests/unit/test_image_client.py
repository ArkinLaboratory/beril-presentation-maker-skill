"""Tests for image_client.py — CBORG-Gemini image-gen client.

Mocks `requests.post` so no live API calls happen. Live-API tests are
gated behind the `image_gen` pytest marker (cost; deselected by default).

Coverage:
- ImageClient construction (cborg classmethod, default model).
- estimate_cost_usd math (sonnet/opus/haiku rates per million).
- BudgetExceeded raised pre-flight when worst-case > budget.
- generate() success: parses base64 image bytes from CBORG response.
- generate() failure: HTTP error → ImageClientError.
- Provenance: ImageResult.to_provenance_dict has all required keys.
- append_provenance: idempotent JSON append/create.
- score_quantitative_content: v0.1 stub returns 0.0.
- CLI: missing key returns 3, budget exceeded returns 4.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IC_PY = REPO_ROOT / "src" / "beril_presentation_maker" / "skill" / "tools" / "image_client.py"


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ic():
    return _import("image_client", IC_PY)


def _mock_cborg_response(
    image_bytes: bytes = b"fake-png", input_tokens: int = 1000, output_tokens: int = 5000
):
    """Build a Mock for requests.Session.post that returns a CBORG-shape JSON."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"b64_json": b64}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_image_client_defaults(ic, monkeypatch):
    # Round 2a fixup (1): ImageClient.cborg() now reads CBORG_BASE_URL
    # from the environment. Clear it so this test asserts the DEFAULT
    # path (the user override is exercised by the dedicated tests
    # below in the "CBORG_BASE_URL honored end-to-end" section).
    monkeypatch.delenv("CBORG_BASE_URL", raising=False)
    client = ic.ImageClient.cborg(api_key="test-key")
    assert client.provider == "cborg"
    assert client.base_url == ic.DEFAULT_CBORG_BASE_URL
    assert client.model == ic.DEFAULT_MODEL
    assert client.api_key == "test-key"


def test_image_client_custom_model(ic):
    client = ic.ImageClient.cborg(api_key="x", model="google/gemini-3-pro-image")
    assert client.model == "google/gemini-3-pro-image"


# ---------------------------------------------------------------------------
# CRAFT-CONTRACT §3.4 — CBORG_BASE_URL honored end-to-end
#
# Round 2a fixup (1): the user-facing CBORG_BASE_URL is the single
# OpenAI-style base for the app-internal CBORG client. The default ends
# in `/v1`; endpoint helpers append the path (no `/v1/...`). An override
# (proxy, alternate gateway) flows through end-to-end.
# ---------------------------------------------------------------------------


def test_default_base_url_includes_v1(ic):
    """The contract: default base ends in /v1 (OpenAI-style)."""
    assert ic.DEFAULT_CBORG_BASE_URL.endswith("/v1")


def test_default_cborg_url_byte_identical(ic, monkeypatch):
    """Round 2a fixup (1): default behavior must stay byte-identical.
    Net request URL is still `…/v1/images/generations`."""
    # Make sure CBORG_BASE_URL is NOT set in env, so the default fires.
    monkeypatch.delenv("CBORG_BASE_URL", raising=False)
    client = ic.ImageClient.cborg(api_key="x")
    # base_url is the OpenAI-style default
    assert client.base_url == "https://api.cborg.lbl.gov/v1"
    # concatenated URL matches the pre-fixup byte-for-byte
    assert (
        f"{client.base_url}/images/generations" == "https://api.cborg.lbl.gov/v1/images/generations"
    )


def test_cborg_base_url_env_override_honored(ic, monkeypatch):
    """A user CBORG_BASE_URL override (proxy, alternate gateway, /v2)
    is now respected end-to-end."""
    monkeypatch.setenv("CBORG_BASE_URL", "https://proxy.example.com/cborg/v1")
    client = ic.ImageClient.cborg(api_key="x")
    assert client.base_url == "https://proxy.example.com/cborg/v1"
    # No double-/v1 — the path is just `/images/generations`.
    assert (
        f"{client.base_url}/images/generations"
        == "https://proxy.example.com/cborg/v1/images/generations"
    )


def test_explicit_base_url_kwarg_still_wins(ic, monkeypatch):
    """An explicit `base_url=...` kwarg overrides both env and default.
    Used by tests that inject a mock URL."""
    monkeypatch.setenv("CBORG_BASE_URL", "https://env.example.com/v1")
    client = ic.ImageClient.cborg(api_key="x", base_url="https://kwarg.example.com/v1")
    assert client.base_url == "https://kwarg.example.com/v1"


def test_cborg_bare_host_env_gets_v1_appended(ic, monkeypatch):
    """CRAFT-CONTRACT §3.4 / Stage 6: if a user sets CBORG_BASE_URL to the
    BARE host (no `/v1`), the app-internal client now routes through
    `llm_config.app_internal_base_url`, which appends `/v1`. Pre-Stage-6
    the consumer read CBORG_BASE_URL raw and would 404 on /v1-less calls."""
    monkeypatch.setenv("CBORG_BASE_URL", "https://api.cborg.lbl.gov")
    client = ic.ImageClient.cborg(api_key="x")
    assert client.base_url == "https://api.cborg.lbl.gov/v1"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def test_estimate_cost_known_model(ic):
    cost = ic.ImageClient.estimate_cost_usd(
        "google/gemini-pro-image",
        input_tokens=1_000_000,
        output_tokens=100_000,
    )
    # 1M * $2 + 100K * $12 = $2 + $1.20 = $3.20
    assert abs(cost - 3.20) < 0.01


def test_estimate_cost_unknown_model_returns_zero(ic):
    cost = ic.ImageClient.estimate_cost_usd("unknown/model", input_tokens=10_000)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


def test_generate_raises_budget_exceeded(ic):
    """v0.3.3.2 (#62): worst-case is now $0.05 (was $0.404). With
    $0.01 budget, BudgetExceeded fires (0.05 > 0.01)."""
    client = ic.ImageClient.cborg(api_key="test")
    with pytest.raises(ic.BudgetExceeded) as exc:
        client.generate(prompt="x", budget_remaining_usd=0.01)
    msg = str(exc.value).lower()
    assert "worst-case" in msg
    # Hint should mention the calibrated mean so users know what to expect.
    assert "0.014" in msg


def test_worst_case_cost_recalibrated_against_v0_3_0_data(ic):
    """v0.3.3.2 (#62): the preflight constant is pinned to a value
    in [$0.03, $0.10] — generous headroom over the calibrated mean
    ($0.014/image, σ small) but tight enough to not false-positive
    --max-image-cost-usd 0.10. Catches accidental loosening (back
    toward $0.40) and accidental tightening (below the calibrated
    max ~$0.018 + headroom)."""
    assert 0.03 <= ic._WORST_CASE_COST_USD <= 0.10, (
        f"_WORST_CASE_COST_USD={ic._WORST_CASE_COST_USD} drifted out "
        f"of the calibrated band [0.03, 0.10]. If actual costs have "
        f"changed, re-run image_gen_calibration.py and update both "
        f"the constant and this test."
    )


def test_generate_clears_preflight_at_max_image_cost_default(ic):
    """The orchestrator default --max-image-cost-usd is 0.50. Preflight
    must clear at that level (and any reasonable user override above
    the worst-case bound)."""
    import requests

    sess = MagicMock()
    sess.post.side_effect = requests.RequestException("preflight passed")
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    # 0.50 (orchestrator default) and 0.10 (sane lower bound) both clear
    for budget in (0.50, 0.10):
        with pytest.raises(ic.ImageClientError) as exc:
            client.generate(prompt="x", budget_remaining_usd=budget)
        assert not isinstance(exc.value, ic.BudgetExceeded), (
            f"BudgetExceeded falsely fired at budget=${budget}"
        )


def test_generate_preflight_borderline_at_worst_case(ic):
    """Budget exactly equal to worst-case: NOT exceeded (uses >, not ≥).
    Pins the comparison-strictness in case anyone refactors to ≥."""
    import requests

    sess = MagicMock()
    sess.post.side_effect = requests.RequestException("preflight passed")
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=ic._WORST_CASE_COST_USD)
    assert not isinstance(exc.value, ic.BudgetExceeded)


def test_generate_within_budget_passes_preflight(ic):
    """A $5 budget allows the call — preflight passes. Use a
    RequestException side_effect so the client catches it and wraps as
    ImageClientError."""
    import requests

    sess = MagicMock()
    sess.post.side_effect = requests.RequestException("preflight passed")
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=5.00)
    # Should wrap the RequestException, not raise BudgetExceeded
    assert "request failed" in str(exc.value).lower()
    assert not isinstance(exc.value, ic.BudgetExceeded)


# ---------------------------------------------------------------------------
# generate() with mocked CBORG
# ---------------------------------------------------------------------------


def test_generate_parses_cborg_response(ic, monkeypatch):
    # Round 2a fixup (1): clear CBORG_BASE_URL so this test sees the
    # DEFAULT base URL (the override is exercised separately above).
    monkeypatch.delenv("CBORG_BASE_URL", raising=False)
    sess = MagicMock()
    sess.post.return_value = _mock_cborg_response(
        image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
    )
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    result = client.generate(prompt="test", budget_remaining_usd=10.00, channel="A")
    assert result.image_bytes.startswith(b"\x89PNG")
    assert result.model == ic.DEFAULT_MODEL
    assert result.prompt == "test"
    assert result.channel == "A"
    assert result.cost_usd > 0
    assert result.elapsed_seconds >= 0
    # CBORG was called with correct shape — the FULL URL on the default
    # path is byte-identical to pre-Round-2a (`/v1` lives in the base
    # URL constant, not the path).
    args, kwargs = sess.post.call_args
    assert "/v1/images/generations" in args[0]
    assert kwargs["json"]["prompt"] == "test"
    assert kwargs["json"]["model"] == ic.DEFAULT_MODEL
    # Authorization header set
    assert "Bearer test" in kwargs["headers"]["Authorization"]


def test_generate_missing_b64_raises(ic):
    sess = MagicMock()
    bad_resp = MagicMock()
    bad_resp.json.return_value = {"data": [{}]}  # no b64_json
    bad_resp.raise_for_status = MagicMock()
    sess.post.return_value = bad_resp
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "b64_json" in str(exc.value)


def test_generate_http_error_raises_image_client_error(ic):
    import requests

    sess = MagicMock()
    sess.post.side_effect = requests.RequestException("network error")
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "request failed" in str(exc.value).lower()


def test_generate_no_api_key_raises(ic):
    client = ic.ImageClient(provider="cborg", api_key=None)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "api_key" in str(exc.value)


def test_generate_unsupported_provider_raises(ic):
    client = ic.ImageClient(provider="openai", api_key="x")
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "v0.1" in str(exc.value) or "not implemented" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_image_result_to_provenance_dict_keys(ic):
    result = ic.ImageResult(
        image_bytes=b"x",
        model="m",
        prompt="p",
        cost_usd=0.18,
        elapsed_seconds=2.5,
        channel="A",
        approved_at="2026-04-26T00:00:00Z",
        quant_content_score=0.04,
    )
    d = result.to_provenance_dict()
    expected_keys = {
        "model",
        "prompt",
        "cost_usd",
        "elapsed_seconds",
        "channel",
        "approved_at",
        "quant_content_score",
    }
    assert expected_keys.issubset(set(d.keys()))


def test_append_provenance_creates_new_file(ic, tmp_path):
    out = tmp_path / "image_provenance.json"
    result = ic.ImageResult(
        image_bytes=b"",
        model="m",
        prompt="p",
        cost_usd=0.10,
        elapsed_seconds=1.0,
        channel="A",
        approved_at="2026-04-26T00:00:00Z",
    )
    ic.append_provenance(out, result, image_path="ai_images/img01.png")
    parsed = json.loads(out.read_text())
    assert parsed["version"] == "1.0"
    assert len(parsed["entries"]) == 1
    assert parsed["entries"][0]["image_path"] == "ai_images/img01.png"


def test_append_provenance_appends_existing(ic, tmp_path):
    out = tmp_path / "image_provenance.json"
    out.write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": [
                    {
                        "model": "old",
                        "prompt": "old",
                        "cost_usd": 0,
                        "elapsed_seconds": 0,
                        "channel": "A",
                        "approved_at": "2026-04-26T00:00:00Z",
                        "quant_content_score": None,
                    }
                ],
            }
        )
    )
    result = ic.ImageResult(
        image_bytes=b"",
        model="new",
        prompt="new",
        cost_usd=0.20,
        elapsed_seconds=1.0,
        channel="B",
        approved_at="2026-04-26T01:00:00Z",
    )
    ic.append_provenance(out, result)
    parsed = json.loads(out.read_text())
    assert len(parsed["entries"]) == 2
    assert parsed["entries"][1]["model"] == "new"
    assert parsed["entries"][1]["channel"] == "B"


# ---------------------------------------------------------------------------
# Quant-content judge (v0.1 stub)
# ---------------------------------------------------------------------------


def test_score_quantitative_content_stub_returns_zero(ic):
    """v0.1 stub: always returns 0.0 (no quantitative content). Real
    vision-LLM integration ships in v0.2."""
    client = ic.ImageClient.cborg(api_key="x")
    score = client.score_quantitative_content(b"\x89PNG fake")
    assert score == 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_missing_api_key_returns_3(ic, monkeypatch):
    monkeypatch.delenv("CBORG_API_KEY", raising=False)
    rc = ic.main(["generate", "--prompt", "x", "--out", "/tmp/x.png", "--budget", "5.00"])
    assert rc == 3


def test_cli_budget_exceeded_returns_4(ic, monkeypatch, tmp_path):
    monkeypatch.setenv("CBORG_API_KEY", "test")
    rc = ic.main(
        ["generate", "--prompt", "x", "--out", str(tmp_path / "x.png"), "--budget", "0.0001"]
    )
    assert rc == 4


def test_cli_generate_with_mocked_session_writes_image(ic, monkeypatch, tmp_path):
    """End-to-end CLI with mocked HTTP. Verifies image file written +
    provenance appended."""
    monkeypatch.setenv("CBORG_API_KEY", "test")
    out_img = tmp_path / "img.png"
    prov = tmp_path / "image_provenance.json"

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.post.return_value = _mock_cborg_response(
        image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
    )
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    rc = ic.main(
        [
            "generate",
            "--prompt",
            "x",
            "--out",
            str(out_img),
            "--budget",
            "5.00",
            "--provenance",
            str(prov),
        ]
    )
    assert rc == 0
    assert out_img.is_file()
    assert prov.is_file()
    parsed = json.loads(prov.read_text())
    assert len(parsed["entries"]) == 1
    monkeypatch.setattr(ic.requests, "Session", real_session)


# ---------------------------------------------------------------------------
# AI Studio (M5b/D-062)
# ---------------------------------------------------------------------------


def _mock_ai_studio_response(
    image_bytes: bytes = b"fake-png",
    prompt_tokens: int = 100,
    candidates_tokens: int = 5000,
    mime_type: str = "image/png",
    include_text_part: bool = False,
):
    """Build a Mock for requests.Session.post returning AI Studio-shape JSON.

    AI Studio's :generateContent response shape:
      candidates[0].content.parts = [<text or inlineData parts>]
      usageMetadata = {promptTokenCount, candidatesTokenCount}
    """
    b64 = base64.b64encode(image_bytes).decode("ascii")
    parts = []
    if include_text_part:
        parts.append({"text": "Here is your image:"})
    parts.append({"inlineData": {"mimeType": mime_type, "data": b64}})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": parts}}],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidates_tokens,
        },
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# Construction + classmethod


def test_ai_studio_classmethod_defaults(ic):
    """google_ai_studio classmethod sets provider, base URL, default model."""
    client = ic.ImageClient.google_ai_studio(api_key="test-ai")
    assert client.provider == "google_ai_studio"
    assert client.base_url == ic.DEFAULT_AI_STUDIO_BASE_URL
    assert client.model == ic.DEFAULT_AI_STUDIO_MODEL
    assert client.api_key == "test-ai"


def test_ai_studio_classmethod_model_override(ic):
    client = ic.ImageClient.google_ai_studio(api_key="x", model="gemini-3-pro-image-preview")
    assert client.model == "gemini-3-pro-image-preview"


def test_ai_studio_default_model_is_may_2026_primary(ic):
    """Pin the default model to the May-2026 primary discovered at Tier A
    (gemini-3.1-flash-image-preview = Nano Banana 2). If Google moves the
    default model line again, this test breaks and forces an explicit
    update to AI_STUDIO_MODEL_FALLBACK_CHAIN."""
    assert ic.DEFAULT_AI_STUDIO_MODEL == "gemini-3.1-flash-image-preview"
    assert ic.DEFAULT_AI_STUDIO_MODEL in ic.AI_STUDIO_MODEL_FALLBACK_CHAIN


def test_ai_studio_fallback_chain_order(ic):
    """D-035-rev1 (M5b Tier A): pro-preview → 3.1-flash-preview → 2.5-flash.
    Test pins both presence and order — the resolve function (Tier C)
    picks the first present in this chain."""
    assert ic.AI_STUDIO_MODEL_FALLBACK_CHAIN == (
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    )


# _size_to_ai_studio_config helper


def test_size_helper_1024_square_to_1k_1to1(ic):
    """Common case: orchestrator passes (1024, 1024) → ('1:1', '1K')."""
    assert ic._size_to_ai_studio_config((1024, 1024)) == ("1:1", "1K")


def test_size_helper_widescreen_to_16_9(ic):
    assert ic._size_to_ai_studio_config((1920, 1080)) == ("16:9", "2K")


def test_size_helper_portrait_to_2_3(ic):
    assert ic._size_to_ai_studio_config((512, 768)) == ("2:3", "1K")


def test_size_helper_large_square_to_2k(ic):
    assert ic._size_to_ai_studio_config((2048, 2048)) == ("1:1", "2K")


def test_size_helper_huge_to_4k(ic):
    assert ic._size_to_ai_studio_config((3000, 2000)) == ("3:2", "4K")


def test_size_helper_tiny_to_512(ic):
    assert ic._size_to_ai_studio_config((256, 256)) == ("1:1", "512")


def test_size_helper_zero_returns_safe_default(ic):
    assert ic._size_to_ai_studio_config((0, 0)) == ("1:1", "1K")


# Rate card


def test_ai_studio_rate_card_has_may_2026_models(ic):
    """All three models in the fallback chain must have rate-card entries
    so estimate_cost_usd doesn't silently return 0.0 (which would mask
    cost drift). Pinned at M5b Tier A; update with each Google price
    change."""
    for model in ic.AI_STUDIO_MODEL_FALLBACK_CHAIN:
        assert model in ic._MODEL_RATES_USD_PER_M, (
            f"AI Studio model {model!r} missing from rate card — "
            f"estimate_cost_usd would return 0.0 and mask spend"
        )
        rates = ic._MODEL_RATES_USD_PER_M[model]
        assert rates["input"] > 0 and rates["output"] > 0


# _call_google_ai_studio — request shape


def test_ai_studio_request_shape(ic):
    """Pin the request shape against Google's v1beta discovery doc
    (verified 2026-05-24). M5b Tier A.1: the human-docs page suggested
    `generationConfig.responseFormat.image.*` but the API rejects it
    (responseFormat takes ResponseFormatConfig, NOT ImageConfig). The
    canonical wrapper is `generationConfig.imageConfig.*` per the
    discovery doc's GenerationConfig.imageConfig → ImageConfig schema.
    If this test breaks, the API likely changed; re-fetch
    https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta
    and update."""
    sess = MagicMock()
    sess.post.return_value = _mock_ai_studio_response(
        image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
    )
    client = ic.ImageClient.google_ai_studio(api_key="ai-key", request_session=sess)
    client.generate(prompt="A glowing brain", budget_remaining_usd=10.00, size=(1024, 1024))
    args, kwargs = sess.post.call_args
    url = args[0]
    # Endpoint includes the model name + :generateContent
    assert ":generateContent" in url
    assert "gemini-3.1-flash-image-preview" in url
    assert "/v1beta/models/" in url
    # API key in header (not query string)
    assert kwargs["headers"]["x-goog-api-key"] == "ai-key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    # NOT an Authorization Bearer header (would be CBORG-style)
    assert "Authorization" not in kwargs["headers"]
    # Body shape: contents[0].parts[0].text + generationConfig.imageConfig
    body = kwargs["json"]
    assert body["contents"][0]["parts"][0]["text"] == "A glowing brain"
    gen_cfg = body["generationConfig"]
    assert gen_cfg["responseModalities"] == ["IMAGE"]
    img_cfg = gen_cfg["imageConfig"]
    assert img_cfg["aspectRatio"] == "1:1"
    assert img_cfg["imageSize"] == "1K"


def test_ai_studio_request_shape_does_not_use_response_format_wrapper(ic):
    """Regression pin (M5b Tier A.1, live-discovered 2026-05-24): the
    initial Tier-A implementation wrapped image config under
    `generationConfig.responseFormat.image.*` based on the ai.google.dev
    human-docs page, but Google's v1beta API rejects that with
    INVALID_ARGUMENT (responseFormat expects a different schema —
    ResponseFormatConfig, not ImageConfig). The canonical wrapper is
    `generationConfig.imageConfig.*` per the v1beta discovery doc.

    This test asserts the *absence* of the wrong wrapper. If a future
    refactor reintroduces `responseFormat.image` here, the live API
    will 400 on the first call — pinning this prevents that recurrence.
    """
    sess = MagicMock()
    sess.post.return_value = _mock_ai_studio_response()
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    client.generate(prompt="x", budget_remaining_usd=10.00)
    body = sess.post.call_args[1]["json"]
    gen_cfg = body["generationConfig"]
    # The wrong wrapper must NOT appear.
    assert "responseFormat" not in gen_cfg, (
        f"AI Studio body should not include `responseFormat`; "
        f"image config goes under `imageConfig` per v1beta discovery "
        f"doc. Saw: {gen_cfg}"
    )
    # The right wrapper must appear.
    assert "imageConfig" in gen_cfg
    img_cfg = gen_cfg["imageConfig"]
    # Friendly aspect-ratio strings (NOT proto enum names like
    # ASPECT_RATIO_ONE_BY_ONE; those belong to ResponseFormatConfig's
    # schema, not ImageConfig). Discovery doc:
    #   "Supported aspect ratios: `1:1`, `1:4`, `4:1`, ... `16:9`, ..."
    assert ":" in img_cfg["aspectRatio"]  # friendly form, e.g. "1:1"
    # Friendly imageSize bucket names (NOT IMAGE_SIZE_1K). Discovery:
    #   "Supported values are `512`, `1K`, `2K`, `4K`."
    assert img_cfg["imageSize"] in {"512", "1K", "2K", "4K"}


# _call_google_ai_studio — response parsing


def test_ai_studio_parses_image_bytes(ic):
    sess = MagicMock()
    sess.post.return_value = _mock_ai_studio_response(
        image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
        prompt_tokens=200,
        candidates_tokens=8000,
    )
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    result = client.generate(prompt="test", budget_remaining_usd=10.00, channel="A")
    assert result.image_bytes.startswith(b"\x89PNG")
    assert result.model == ic.DEFAULT_AI_STUDIO_MODEL
    assert result.prompt == "test"
    assert result.channel == "A"
    # Cost calculated from rate card * usage
    assert result.cost_usd > 0
    # Token-count normalization: camelCase → input/output_tokens
    expected_cost = ic.ImageClient.estimate_cost_usd(
        ic.DEFAULT_AI_STUDIO_MODEL, input_tokens=200, output_tokens=8000
    )
    assert abs(result.cost_usd - expected_cost) < 1e-9


def test_ai_studio_handles_text_part_alongside_image(ic):
    """API may emit a text part + an image part; walker must find the
    inlineData part regardless of order."""
    sess = MagicMock()
    sess.post.return_value = _mock_ai_studio_response(
        image_bytes=b"\x89PNG bytes",
        include_text_part=True,  # text part precedes image part
    )
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    result = client.generate(prompt="x", budget_remaining_usd=10.00)
    assert result.image_bytes == b"\x89PNG bytes"


def test_ai_studio_missing_inline_data_raises(ic):
    """Defensive: response with only text parts → ImageClientError."""
    sess = MagicMock()
    bad_resp = MagicMock()
    bad_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "no image here"}]}}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    bad_resp.raise_for_status = MagicMock()
    sess.post.return_value = bad_resp
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "inlineData" in str(exc.value)


def test_ai_studio_non_image_mime_refused(ic):
    """Defensive: if model returns inline_data with mimeType=audio/wav,
    refuse rather than write bytes that aren't an image."""
    sess = MagicMock()
    sess.post.return_value = _mock_ai_studio_response(
        image_bytes=b"some bytes",
        mime_type="audio/wav",
    )
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "non-image" in str(exc.value)


def test_ai_studio_429_surfaces_clearly(ic):
    """Per §14.2: AI Studio free-tier rate-limits aggressively; 429 must
    surface as a distinct, actionable error (not a generic HTTP failure)."""
    import requests

    sess = MagicMock()
    err_resp = MagicMock()
    err_resp.status_code = 429
    err_resp.text = '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}'
    raise_err = requests.HTTPError("429 Too Many Requests")
    raise_err.response = err_resp
    err_resp.raise_for_status = MagicMock(side_effect=raise_err)
    sess.post.return_value = err_resp
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    msg = str(exc.value)
    assert "429" in msg
    assert "rate-limit" in msg.lower() or "rate limited" in msg.lower()


def test_ai_studio_generic_http_error_includes_endpoint(ic):
    import requests

    sess = MagicMock()
    sess.post.side_effect = requests.RequestException("connection refused")
    client = ic.ImageClient.google_ai_studio(api_key="x", request_session=sess)
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    msg = str(exc.value)
    assert "AI Studio" in msg
    assert "endpoint" in msg
    assert "generativelanguage.googleapis.com" in msg


def test_ai_studio_no_api_key_raises(ic):
    client = ic.ImageClient(
        provider="google_ai_studio",
        api_key=None,
        base_url=ic.DEFAULT_AI_STUDIO_BASE_URL,
        model=ic.DEFAULT_AI_STUDIO_MODEL,
    )
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    assert "GOOGLE_AI_STUDIO_API_KEY" in str(exc.value)


# Dispatch — cborg path unchanged + google_ai_studio added; unknown provider
# still names both supported options.


def test_dispatch_unsupported_provider_names_both(ic):
    """The unsupported-provider error must name both supported providers
    so users know what's available."""
    client = ic.ImageClient(provider="openai", api_key="x")
    with pytest.raises(ic.ImageClientError) as exc:
        client.generate(prompt="x", budget_remaining_usd=10.00)
    msg = str(exc.value)
    assert "cborg" in msg
    assert "google_ai_studio" in msg


# CLI — --provider flag


def test_cli_ai_studio_missing_api_key_returns_3(ic, monkeypatch):
    monkeypatch.delenv("GOOGLE_AI_STUDIO_API_KEY", raising=False)
    rc = ic.main(
        [
            "generate",
            "--provider",
            "google_ai_studio",
            "--prompt",
            "x",
            "--out",
            "/tmp/x.png",
            "--budget",
            "5.00",
        ]
    )
    assert rc == 3


def test_cli_ai_studio_generate_with_mocked_session(ic, monkeypatch, tmp_path):
    """End-to-end CLI on the AI Studio path with mocked HTTP."""
    monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-ai")
    out_img = tmp_path / "img.png"
    prov = tmp_path / "image_provenance.json"

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.post.return_value = _mock_ai_studio_response(
        image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
    )
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    rc = ic.main(
        [
            "generate",
            "--provider",
            "google_ai_studio",
            "--prompt",
            "x",
            "--out",
            str(out_img),
            "--budget",
            "5.00",
            "--provenance",
            str(prov),
        ]
    )
    assert rc == 0
    assert out_img.is_file()
    assert prov.is_file()
    parsed = json.loads(prov.read_text())
    assert len(parsed["entries"]) == 1
    # Provenance records the AI Studio model, not the CBORG default
    assert parsed["entries"][0]["model"] == ic.DEFAULT_AI_STUDIO_MODEL
    monkeypatch.setattr(ic.requests, "Session", real_session)


def test_cli_unknown_provider_returns_3(ic, monkeypatch, tmp_path):
    """argparse rejects unknown --provider value at parse time → SystemExit.
    Pin that the choice-list is exactly {cborg, google_ai_studio} so we
    don't accidentally accept 'openai' or similar."""
    with pytest.raises(SystemExit):
        ic.main(
            [
                "generate",
                "--provider",
                "openai",
                "--prompt",
                "x",
                "--out",
                str(tmp_path / "x.png"),
                "--budget",
                "5.00",
            ]
        )


# ---------------------------------------------------------------------------
# Tier C — AI Studio model-availability probe (D-063, D-064)
# ---------------------------------------------------------------------------


def _mock_list_models_response(
    image_model_names: list[str], non_image_names: list[str] | None = None
):
    """Build a Mock for requests.Session.get returning AI Studio's
    /v1beta/models response shape with the given model names.

    Image models include 'image' in name + supportedGenerationMethods
    contains 'generateContent'. Non-image models also support
    generateContent but don't have 'image' in the name — used to test
    the filter.
    """
    non_image_names = non_image_names or []
    models = []
    for n in image_model_names:
        models.append(
            {
                "name": f"models/{n}",
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            }
        )
    for n in non_image_names:
        models.append(
            {
                "name": f"models/{n}",
                "supportedGenerationMethods": ["generateContent"],
            }
        )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": models}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# probe_available_models


def test_probe_returns_image_capable_models(ic):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"],
        non_image_names=["gemini-2.0-flash", "gemini-2.0-pro"],
    )
    out = ic.probe_available_models(api_key="x", request_session=sess)
    # Strips "models/" prefix
    assert "gemini-3.1-flash-image-preview" in out
    assert "gemini-3-pro-image-preview" in out
    # Filter excludes non-image models
    assert "gemini-2.0-flash" not in out
    assert "gemini-2.0-pro" not in out


def test_probe_uses_x_goog_api_key_header(ic):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(image_model_names=[])
    ic.probe_available_models(api_key="probe-key", request_session=sess)
    _args, kwargs = sess.get.call_args
    assert kwargs["headers"]["x-goog-api-key"] == "probe-key"
    # NOT Authorization header (would be CBORG-style)
    assert "Authorization" not in kwargs["headers"]


def test_probe_hits_v1beta_models_endpoint(ic):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(image_model_names=[])
    ic.probe_available_models(api_key="x", request_session=sess)
    args, _kwargs = sess.get.call_args
    assert "/v1beta/models" in args[0]
    assert args[0].endswith("/v1beta/models")
    # NOT a query-string key (we use header auth)
    assert "?key=" not in args[0]


def test_probe_returns_empty_on_http_error(ic):
    import requests

    sess = MagicMock()
    sess.get.side_effect = requests.RequestException("network error")
    out = ic.probe_available_models(api_key="x", request_session=sess)
    assert out == []


def test_probe_returns_empty_on_bad_json(ic):
    sess = MagicMock()
    bad_resp = MagicMock()
    bad_resp.json.side_effect = ValueError("not json")
    bad_resp.raise_for_status = MagicMock()
    sess.get.return_value = bad_resp
    out = ic.probe_available_models(api_key="x", request_session=sess)
    assert out == []


def test_probe_returns_empty_on_no_models_field(ic):
    """Defensive: API returns 200 with empty/unexpected body."""
    sess = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {}  # no "models" key
    resp.raise_for_status = MagicMock()
    sess.get.return_value = resp
    out = ic.probe_available_models(api_key="x", request_session=sess)
    assert out == []


# resolve_ai_studio_model


def test_resolve_picks_first_chain_model_present(ic):
    """Walks AI_STUDIO_MODEL_FALLBACK_CHAIN in order; returns first
    present in available."""
    chain = ic.AI_STUDIO_MODEL_FALLBACK_CHAIN
    # User has only the 2.5-flash (last in chain)
    out = ic.resolve_ai_studio_model([chain[2]])
    assert out == chain[2]


def test_resolve_picks_pro_over_flash_when_both_available(ic):
    """If the user has access to multiple chain models, picks the
    highest-priority (chain order: pro → 3.1-flash → 2.5-flash)."""
    chain = ic.AI_STUDIO_MODEL_FALLBACK_CHAIN
    out = ic.resolve_ai_studio_model(list(chain))
    assert out == chain[0]  # gemini-3-pro-image-preview


def test_resolve_returns_none_when_no_chain_match(ic):
    """User has image models but none are in our chain → return None.
    Triggers the D-064 hybrid fallback path."""
    out = ic.resolve_ai_studio_model(["imagen-4", "gemini-2.0-flash-image"])
    assert out is None


def test_resolve_returns_none_on_empty_available(ic):
    assert ic.resolve_ai_studio_model([]) is None


# load_or_probe_ai_studio_model — sidecar cache (D-063)


def test_load_or_probe_writes_sidecar_on_fresh_probe(ic, tmp_path):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    record = ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    sidecar = tmp_path / "ai_image_gen_probe.json"
    assert sidecar.is_file()
    assert record["resolved_model"] == "gemini-3.1-flash-image-preview"
    assert record["from_cache"] is False
    assert record["from_override"] is False
    assert record["schema_version"] == ic.PROBE_SCHEMA_VERSION
    # Fingerprint is short hash, NOT the raw key
    assert record["api_key_fingerprint"] != "x"
    assert len(record["api_key_fingerprint"]) == 8


def test_load_or_probe_hits_cache_on_repeat(ic, tmp_path):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    # First call: fresh probe.
    r1 = ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    assert r1["from_cache"] is False
    assert sess.get.call_count == 1
    # Second call: cache hit; HTTP NOT called again.
    r2 = ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    assert r2["from_cache"] is True
    assert r2["resolved_model"] == r1["resolved_model"]
    assert sess.get.call_count == 1  # unchanged — still 1


def test_load_or_probe_re_probes_on_different_api_key(ic, tmp_path):
    """Cache fingerprints the key; rotating keys forces a re-probe.
    Prevents stale cache from one user/account leaking into another."""
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    r1 = ic.load_or_probe_ai_studio_model(api_key="key-A", audit_dir=tmp_path, request_session=sess)
    r2 = ic.load_or_probe_ai_studio_model(api_key="key-B", audit_dir=tmp_path, request_session=sess)
    assert r1["api_key_fingerprint"] != r2["api_key_fingerprint"]
    assert r2["from_cache"] is False
    assert sess.get.call_count == 2


def test_load_or_probe_force_refresh_re_probes(ic, tmp_path):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    r2 = ic.load_or_probe_ai_studio_model(
        api_key="x", audit_dir=tmp_path, request_session=sess, force_refresh=True
    )
    assert r2["from_cache"] is False
    assert sess.get.call_count == 2


def test_load_or_probe_override_skips_probe(ic, tmp_path):
    """GOOGLE_AI_STUDIO_MODEL override (C5): skip probe entirely, pin
    the named model. Records from_override=True."""
    sess = MagicMock()
    # Session GET should NOT be invoked when override is set.
    sess.get.side_effect = AssertionError("probe was called despite override")
    record = ic.load_or_probe_ai_studio_model(
        api_key="x", audit_dir=tmp_path, override_model="my-custom-model", request_session=sess
    )
    assert record["resolved_model"] == "my-custom-model"
    assert record["from_override"] is True
    assert sess.get.call_count == 0


def test_load_or_probe_recovers_from_corrupt_cache(ic, tmp_path):
    """Sidecar JSON corrupted (e.g., partial write) → re-probe rather
    than fail. Defensive."""
    sidecar = tmp_path / "ai_image_gen_probe.json"
    sidecar.write_text("{not json{", encoding="utf-8")
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    record = ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    assert record["resolved_model"] == "gemini-3.1-flash-image-preview"
    assert record["from_cache"] is False  # re-probed; cache was unreadable


def test_load_or_probe_records_none_when_no_chain_match(ic, tmp_path):
    """API returns models but none in our chain → cache records
    resolved_model=None; triggers D-064 in caller."""
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["imagen-4"],  # not in our chain
    )
    record = ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    assert record["resolved_model"] is None
    assert record["available_models"] == ["imagen-4"]
    # Cache still written so we don't re-probe next call.
    cached = json.loads((tmp_path / "ai_image_gen_probe.json").read_text())
    assert cached["resolved_model"] is None


# format_probe_failure_diagnostic — D-064


def test_diagnostic_loud_when_no_cborg(ic):
    """No CBORG fallback → diagnostic must say 'image-gen DISABLED'
    plus suggest the next steps the user can take."""
    record = {
        "available_models": ["imagen-4", "gemini-2.0-flash-image"],
        "chain_walked": list(ic.AI_STUDIO_MODEL_FALLBACK_CHAIN),
    }
    diag = ic.format_probe_failure_diagnostic(record, cborg_available=False)
    assert "DISABLED" in diag
    assert "No CBORG_API_KEY" in diag
    # Names what user can do to fix it
    assert "GOOGLE_AI_STUDIO_MODEL" in diag
    # Names every chain model + its availability
    for m in ic.AI_STUDIO_MODEL_FALLBACK_CHAIN:
        assert m in diag


def test_diagnostic_lists_available_models(ic):
    """The diagnostic shows image-capable models seen on the key so
    the user has options for GOOGLE_AI_STUDIO_MODEL override."""
    record = {
        "available_models": ["imagen-4", "gemini-2.0-flash-image"],
        "chain_walked": list(ic.AI_STUDIO_MODEL_FALLBACK_CHAIN),
    }
    diag = ic.format_probe_failure_diagnostic(record, cborg_available=False)
    assert "imagen-4" in diag
    assert "gemini-2.0-flash-image" in diag


def test_diagnostic_when_no_image_models_at_all(ic):
    record = {
        "available_models": [],
        "chain_walked": list(ic.AI_STUDIO_MODEL_FALLBACK_CHAIN),
    }
    diag = ic.format_probe_failure_diagnostic(record, cborg_available=False)
    assert "NONE" in diag


def test_diagnostic_notes_cborg_available_branch(ic):
    """When CBORG is available, the diagnostic acknowledges that path
    (even though this function is normally only invoked on the
    loud-warning branch)."""
    record = {
        "available_models": ["imagen-4"],
        "chain_walked": list(ic.AI_STUDIO_MODEL_FALLBACK_CHAIN),
    }
    diag = ic.format_probe_failure_diagnostic(record, cborg_available=True)
    assert "CBORG_API_KEY is set" in diag


# CLI — probe subcommand


def test_cli_probe_missing_api_key_returns_3(ic, monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_AI_STUDIO_API_KEY", raising=False)
    rc = ic.main(["probe", "--audit-dir", str(tmp_path)])
    assert rc == 3


def test_cli_probe_success_prints_model_to_stdout(ic, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_AI_STUDIO_MODEL", raising=False)

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    rc = ic.main(["probe", "--audit-dir", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    # Resolved model on stdout (orchestrator captures via $(...))
    assert captured.out.strip() == "gemini-3.1-flash-image-preview"
    # Diagnostic on stderr
    assert "resolved" in captured.err
    # Sidecar written
    assert (tmp_path / "ai_image_gen_probe.json").is_file()
    monkeypatch.setattr(ic.requests, "Session", real_session)


def test_cli_probe_no_match_returns_5(ic, monkeypatch, tmp_path, capsys):
    """D-064: probe finds models but none in our chain → rc=5 + loud
    diagnostic. Orchestrator decides next action based on
    --cborg-available."""
    monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_AI_STUDIO_MODEL", raising=False)

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.get.return_value = _mock_list_models_response(
        image_model_names=["imagen-4"],  # not in our chain
    )
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    rc = ic.main(["probe", "--audit-dir", str(tmp_path)])
    assert rc == 5
    captured = capsys.readouterr()
    assert "DISABLED" in captured.err
    monkeypatch.setattr(ic.requests, "Session", real_session)


def test_cli_probe_honours_override_env_var(ic, monkeypatch, tmp_path, capsys):
    """GOOGLE_AI_STUDIO_MODEL env var short-circuits the probe (C5)."""
    monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_AI_STUDIO_MODEL", "gemini-experimental")

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.get.side_effect = AssertionError("HTTP probe ran despite override")
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    rc = ic.main(["probe", "--audit-dir", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "gemini-experimental"
    assert "override" in captured.err.lower()
    monkeypatch.setattr(ic.requests, "Session", real_session)


def test_cli_probe_cache_hit_does_not_re_probe(ic, monkeypatch, tmp_path, capsys):
    """Second invocation reads sidecar, doesn't issue HTTP."""
    monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_AI_STUDIO_MODEL", raising=False)

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    # First call: probe.
    rc1 = ic.main(["probe", "--audit-dir", str(tmp_path)])
    assert rc1 == 0
    capsys.readouterr()  # drain
    # Second call: should hit cache.
    rc2 = ic.main(["probe", "--audit-dir", str(tmp_path)])
    assert rc2 == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "gemini-3.1-flash-image-preview"
    assert "cache" in captured.err
    assert sess_mock.get.call_count == 1  # unchanged on second call
    monkeypatch.setattr(ic.requests, "Session", real_session)


def test_cli_probe_force_refresh(ic, monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_AI_STUDIO_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_AI_STUDIO_MODEL", raising=False)

    real_session = ic.requests.Session
    sess_mock = MagicMock()
    sess_mock.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    monkeypatch.setattr(ic.requests, "Session", lambda: sess_mock)
    ic.main(["probe", "--audit-dir", str(tmp_path)])
    ic.main(["probe", "--audit-dir", str(tmp_path), "--force-refresh"])
    assert sess_mock.get.call_count == 2
    monkeypatch.setattr(ic.requests, "Session", real_session)


# Sidecar schema pin


def test_probe_schema_version_pin(ic):
    """If the schema changes, the cache invalidates safely (old records
    skipped). Pin the schema version literal so any change is explicit."""
    assert ic.PROBE_SCHEMA_VERSION == "ai-image-gen-probe.v1"


def test_sidecar_has_expected_keys(ic, tmp_path):
    sess = MagicMock()
    sess.get.return_value = _mock_list_models_response(
        image_model_names=["gemini-3.1-flash-image-preview"],
    )
    ic.load_or_probe_ai_studio_model(api_key="x", audit_dir=tmp_path, request_session=sess)
    cached = json.loads((tmp_path / "ai_image_gen_probe.json").read_text())
    expected = {
        "schema_version",
        "api_key_fingerprint",
        "probed_at",
        "available_models",
        "resolved_model",
        "from_override",
        "chain_walked",
    }
    assert expected.issubset(set(cached.keys()))
    # api_key_fingerprint must NOT be the raw key
    assert cached["api_key_fingerprint"] != "x"
