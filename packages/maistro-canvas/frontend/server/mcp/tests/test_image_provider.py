import base64
import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from server.mcp.image_provider import (
    _generate_azure,
    _generate_cloudflare,
    _generate_gemini,
    _is_configured,
    generate_image,
)


def _make_png_bytes():
    img = Image.new("RGB", (10, 10), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _make_png_b64():
    return base64.b64encode(_make_png_bytes()).decode("ascii")


class TestIsConfigured:
    @patch("server.mcp.image_provider.CF_KEY", "test-key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "test-acct")
    def test_cloudflare_configured_both_set(self):
        assert _is_configured("cloudflare") is True

    @patch("server.mcp.image_provider.CF_KEY", "")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "test-acct")
    def test_cloudflare_missing_key(self):
        assert _is_configured("cloudflare") is False

    @patch("server.mcp.image_provider.CF_KEY", "test-key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "")
    def test_cloudflare_missing_account(self):
        assert _is_configured("cloudflare") is False

    @patch("server.mcp.image_provider.CF_KEY", "")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "")
    def test_cloudflare_both_empty(self):
        assert _is_configured("cloudflare") is False

    @patch("server.mcp.image_provider.AZURE_KEY", "test-key")
    def test_azure_configured(self):
        assert _is_configured("azure") is True

    @patch("server.mcp.image_provider.AZURE_KEY", "")
    def test_azure_not_configured(self):
        assert _is_configured("azure") is False

    @patch("server.mcp.image_provider.GEMINI_KEY", "test-key")
    def test_gemini_configured(self):
        assert _is_configured("gemini") is True

    @patch("server.mcp.image_provider.GEMINI_KEY", "")
    def test_gemini_not_configured(self):
        assert _is_configured("gemini") is False

    def test_unknown_provider_always_false(self):
        assert _is_configured("openai") is False
        assert _is_configured("") is False
        assert _is_configured("anything") is False


class TestGenerateImageFallback:
    @patch("server.mcp.image_provider._generate_cloudflare")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    @patch("server.mcp.image_provider.AZURE_KEY", "")
    @patch("server.mcp.image_provider.GEMINI_KEY", "")
    def test_cloudflare_only_succeeds(self, mock_cf):
        expected = Image.new("RGB", (10, 10))
        mock_cf.return_value = expected
        result = generate_image("test prompt")
        assert result is expected
        mock_cf.assert_called_once()

    @patch("server.mcp.image_provider._generate_azure")
    @patch("server.mcp.image_provider._generate_cloudflare")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    @patch("server.mcp.image_provider.AZURE_KEY", "key")
    @patch("server.mcp.image_provider.GEMINI_KEY", "")
    def test_cloudflare_fails_fallback_azure(self, mock_cf, mock_azure):
        mock_cf.side_effect = RuntimeError("CF down")
        expected = Image.new("RGB", (10, 10))
        mock_azure.return_value = expected
        result = generate_image("test prompt")
        assert result is expected
        mock_cf.assert_called_once()
        mock_azure.assert_called_once()

    @patch("server.mcp.image_provider._generate_gemini")
    @patch("server.mcp.image_provider.CF_KEY", "")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "")
    @patch("server.mcp.image_provider.AZURE_KEY", "")
    @patch("server.mcp.image_provider.GEMINI_KEY", "key")
    def test_only_gemini_configured(self, mock_gemini):
        expected = Image.new("RGB", (10, 10))
        mock_gemini.return_value = expected
        result = generate_image("test prompt")
        assert result is expected
        mock_gemini.assert_called_once()

    @patch("server.mcp.image_provider.CF_KEY", "")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "")
    @patch("server.mcp.image_provider.AZURE_KEY", "")
    @patch("server.mcp.image_provider.GEMINI_KEY", "")
    def test_none_configured_raises(self):
        with pytest.raises(RuntimeError, match="All image providers failed"):
            generate_image("test prompt")

    @patch("server.mcp.image_provider._generate_gemini")
    @patch("server.mcp.image_provider._generate_azure")
    @patch("server.mcp.image_provider._generate_cloudflare")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    @patch("server.mcp.image_provider.AZURE_KEY", "key")
    @patch("server.mcp.image_provider.GEMINI_KEY", "key")
    def test_preferred_provider_resorts_order(self, mock_cf, mock_azure, mock_gemini):
        expected = Image.new("RGB", (10, 10))
        mock_gemini.return_value = expected
        mock_cf.return_value = Image.new("RGB", (10, 10))
        mock_azure.return_value = Image.new("RGB", (10, 10))
        result = generate_image("test prompt", preferred_provider="gemini")
        assert result is expected
        mock_gemini.assert_called_once()
        mock_cf.assert_not_called()
        mock_azure.assert_not_called()


class TestGenerateCloudflare:
    def _mock_response(self, headers, json_body=None, content=None, text=""):
        resp = MagicMock()
        resp.headers = headers
        resp.content = content or b""
        resp.text = text
        if json_body is not None:
            resp.json.return_value = json_body
        resp.raise_for_status = MagicMock()
        return resp

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    def test_binary_png_response(self, mock_httpx):
        png_data = _make_png_bytes()
        mock_httpx.post.return_value = self._mock_response(
            headers={"content-type": "image/png"},
            content=png_data,
        )
        result = _generate_cloudflare("a cute cat")
        assert isinstance(result, Image.Image)
        assert result.size == (10, 10)

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    def test_json_b64_response(self, mock_httpx):
        b64 = _make_png_b64()
        mock_httpx.post.return_value = self._mock_response(
            headers={"content-type": "application/json"},
            json_body={"success": True, "result": {"image": b64}},
        )
        result = _generate_cloudflare("a cute dog")
        assert isinstance(result, Image.Image)
        assert result.size == (10, 10)

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    def test_failure_raises_runtime_error(self, mock_httpx):
        mock_httpx.post.return_value = self._mock_response(
            headers={"content-type": "text/plain"},
            json_body={"success": False},
            text="bad request",
        )
        with pytest.raises(RuntimeError, match="Cloudflare returned no image"):
            _generate_cloudflare("a cute fish")

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.CF_KEY", "key")
    @patch("server.mcp.image_provider.CF_ACCOUNT", "acct")
    def test_json_missing_result_raises(self, mock_httpx):
        mock_httpx.post.return_value = self._mock_response(
            headers={"content-type": "application/json"},
            json_body={"success": True, "result": None},
            text='{"success":true,"result":null}',
        )
        with pytest.raises(RuntimeError, match="Cloudflare returned no image"):
            _generate_cloudflare("prompt")


class TestGenerateAzure:
    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.AZURE_KEY", "key")
    def test_b64_json_response(self, mock_httpx):
        b64 = _make_png_b64()
        resp = MagicMock()
        resp.json.return_value = {"data": [{"b64_json": b64}]}
        resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = resp
        result = _generate_azure("a sunset")
        assert isinstance(result, Image.Image)
        assert result.size == (10, 10)

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.AZURE_KEY", "key")
    def test_url_response(self, mock_httpx):
        png_data = _make_png_bytes()
        post_resp = MagicMock()
        post_resp.json.return_value = {"data": [{"url": "https://example.com/img.png"}]}
        post_resp.raise_for_status = MagicMock()
        get_resp = MagicMock()
        get_resp.content = png_data
        get_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = post_resp
        mock_httpx.get.return_value = get_resp
        result = _generate_azure("a sunrise")
        assert isinstance(result, Image.Image)
        assert result.size == (10, 10)
        mock_httpx.get.assert_called_once_with("https://example.com/img.png", timeout=30)

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.AZURE_KEY", "key")
    def test_empty_data_raises(self, mock_httpx):
        resp = MagicMock()
        resp.json.return_value = {"data": []}
        resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = resp
        with pytest.raises(RuntimeError, match="Azure returned no image"):
            _generate_azure("prompt")

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.AZURE_KEY", "key")
    def test_missing_data_key_raises(self, mock_httpx):
        resp = MagicMock()
        resp.json.return_value = {"error": "something"}
        resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = resp
        with pytest.raises(RuntimeError, match="Azure returned no image"):
            _generate_azure("prompt")


class TestGenerateGemini:
    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.GEMINI_KEY", "key")
    def test_inline_data_response(self, mock_httpx):
        b64 = _make_png_b64()
        resp = MagicMock()
        resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"inlineData": {"data": b64}}]}}]
        }
        resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = resp
        result = _generate_gemini("a robot")
        assert isinstance(result, Image.Image)
        assert result.size == (10, 10)

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.GEMINI_KEY", "key")
    def test_missing_candidates_raises(self, mock_httpx):
        resp = MagicMock()
        resp.json.return_value = {"error": "no candidates"}
        resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = resp
        with pytest.raises(RuntimeError, match="Gemini returned no image"):
            _generate_gemini("prompt")

    @patch("server.mcp.image_provider.httpx")
    @patch("server.mcp.image_provider.GEMINI_KEY", "key")
    def test_candidates_without_inline_data_raises(self, mock_httpx):
        resp = MagicMock()
        resp.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Here is a description instead of an image"}]}}
            ]
        }
        resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = resp
        with pytest.raises(RuntimeError, match="Gemini returned no image"):
            _generate_gemini("prompt")
