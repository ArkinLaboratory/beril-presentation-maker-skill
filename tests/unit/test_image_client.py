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
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
IC_PY = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
         / "tools" / "image_client.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ic():
    return _import("image_client", IC_PY)


def _mock_cborg_response(image_bytes: bytes = b"fake-png",
                         input_tokens: int = 1000,
                         output_tokens: int = 5000):
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

def test_image_client_defaults(ic):
    client = ic.ImageClient.cborg(api_key="test-key")
    assert client.provider == "cborg"
    assert client.base_url == ic.DEFAULT_CBORG_BASE_URL
    assert client.model == ic.DEFAULT_MODEL
    assert client.api_key == "test-key"


def test_image_client_custom_model(ic):
    client = ic.ImageClient.cborg(api_key="x", model="google/gemini-3-pro-image")
    assert client.model == "google/gemini-3-pro-image"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def test_estimate_cost_known_model(ic):
    cost = ic.ImageClient.estimate_cost_usd(
        "google/gemini-pro-image",
        input_tokens=1_000_000, output_tokens=100_000,
    )
    # 1M * $2 + 100K * $12 = $2 + $1.20 = $3.20
    assert abs(cost - 3.20) < 0.01


def test_estimate_cost_unknown_model_returns_zero(ic):
    cost = ic.ImageClient.estimate_cost_usd("unknown/model",
                                             input_tokens=10_000)
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

def test_generate_parses_cborg_response(ic):
    sess = MagicMock()
    sess.post.return_value = _mock_cborg_response(
        image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
    )
    client = ic.ImageClient.cborg(api_key="test", request_session=sess)
    result = client.generate(prompt="test", budget_remaining_usd=10.00,
                             channel="A")
    assert result.image_bytes.startswith(b"\x89PNG")
    assert result.model == ic.DEFAULT_MODEL
    assert result.prompt == "test"
    assert result.channel == "A"
    assert result.cost_usd > 0
    assert result.elapsed_seconds >= 0
    # CBORG was called with correct shape
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
        image_bytes=b"x", model="m", prompt="p",
        cost_usd=0.18, elapsed_seconds=2.5,
        channel="A", approved_at="2026-04-26T00:00:00Z",
        quant_content_score=0.04,
    )
    d = result.to_provenance_dict()
    expected_keys = {"model", "prompt", "cost_usd", "elapsed_seconds",
                     "channel", "approved_at", "quant_content_score"}
    assert expected_keys.issubset(set(d.keys()))


def test_append_provenance_creates_new_file(ic, tmp_path):
    out = tmp_path / "image_provenance.json"
    result = ic.ImageResult(
        image_bytes=b"", model="m", prompt="p", cost_usd=0.10,
        elapsed_seconds=1.0, channel="A",
        approved_at="2026-04-26T00:00:00Z",
    )
    ic.append_provenance(out, result, image_path="ai_images/img01.png")
    parsed = json.loads(out.read_text())
    assert parsed["version"] == "1.0"
    assert len(parsed["entries"]) == 1
    assert parsed["entries"][0]["image_path"] == "ai_images/img01.png"


def test_append_provenance_appends_existing(ic, tmp_path):
    out = tmp_path / "image_provenance.json"
    out.write_text(json.dumps({
        "version": "1.0",
        "entries": [{"model": "old", "prompt": "old", "cost_usd": 0,
                     "elapsed_seconds": 0, "channel": "A",
                     "approved_at": "2026-04-26T00:00:00Z",
                     "quant_content_score": None}],
    }))
    result = ic.ImageResult(image_bytes=b"", model="new", prompt="new",
                             cost_usd=0.20, elapsed_seconds=1.0,
                             channel="B",
                             approved_at="2026-04-26T01:00:00Z")
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
    rc = ic.main(["generate", "--prompt", "x", "--out", "/tmp/x.png",
                  "--budget", "5.00"])
    assert rc == 3


def test_cli_budget_exceeded_returns_4(ic, monkeypatch, tmp_path):
    monkeypatch.setenv("CBORG_API_KEY", "test")
    rc = ic.main(["generate", "--prompt", "x",
                  "--out", str(tmp_path / "x.png"),
                  "--budget", "0.0001"])
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
    rc = ic.main([
        "generate", "--prompt", "x",
        "--out", str(out_img),
        "--budget", "5.00",
        "--provenance", str(prov),
    ])
    assert rc == 0
    assert out_img.is_file()
    assert prov.is_file()
    parsed = json.loads(prov.read_text())
    assert len(parsed["entries"]) == 1
    monkeypatch.setattr(ic.requests, "Session", real_session)
