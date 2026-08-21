from __future__ import annotations

import base64
import io
import logging
import os
from dataclasses import dataclass
from typing import Literal

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

ImageProvider = Literal["cloudflare", "azure", "gemini"]


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    priority: int
    timeout: int


CF_KEY = os.environ.get("CLOUDFLARE_API_KEY", "")
CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

AZURE_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

CF_MODELS = {
    "sdxl": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "flux_schnell": "@cf/black-forest-labs/flux-1-schnell",
}

PROVIDER_ORDER: list[ProviderConfig] = [
    ProviderConfig("cloudflare", 1, 60),
    ProviderConfig("azure", 2, 180),
    ProviderConfig("gemini", 3, 120),
]


def _is_configured(provider: str) -> bool:
    if provider == "cloudflare":
        return bool(CF_KEY and CF_ACCOUNT)
    if provider == "azure":
        return bool(AZURE_KEY and AZURE_ENDPOINT)
    if provider == "gemini":
        return bool(GEMINI_KEY)
    return False


def generate_image(
    prompt: str,
    reference_image: Image.Image | None = None,
    preferred_provider: str | None = None,
    timeout: int | None = None,
) -> Image.Image:
    providers = list(PROVIDER_ORDER)
    if preferred_provider:
        providers.sort(key=lambda p: 0 if p.name == preferred_provider else p.priority)

    last_error: Exception | None = None
    for prov in providers:
        if not _is_configured(prov.name):
            logger.debug("[image_provider] %s not configured, skipping", prov.name)
            continue

        try:
            t = timeout or prov.timeout
            if prov.name == "cloudflare":
                return _generate_cloudflare(prompt, reference_image, t)
            elif prov.name == "azure":
                return _generate_azure(prompt, t)
            elif prov.name == "gemini":
                return _generate_gemini(prompt, reference_image, t)
        except Exception as e:
            logger.warning("[image_provider] %s failed: %s", prov.name, e)
            last_error = e
            continue

    raise RuntimeError(f"All image providers failed. Last error: {last_error}")


def _generate_cloudflare(
    prompt: str,
    reference_image: Image.Image | None = None,
    timeout: int = 60,
    model: str = "sdxl",
) -> Image.Image:
    model_slug = CF_MODELS.get(model, CF_MODELS["sdxl"])
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/{model_slug}"

    resp = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {CF_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "num_steps": 20,
        },
        timeout=timeout,
    )
    resp.raise_for_status()

    ct = resp.headers.get("content-type", "")
    if "image" in ct:
        return Image.open(io.BytesIO(resp.content))

    data = resp.json()
    if data.get("success") and data.get("result"):
        result = data["result"]
        if isinstance(result, dict) and "image" in result:
            b64 = result["image"]
            return Image.open(io.BytesIO(base64.b64decode(b64)))

    raise RuntimeError(f"Cloudflare returned no image. CT={ct}, body={resp.text[:300]}")


def _generate_azure(
    prompt: str,
    timeout: int = 180,
) -> Image.Image:
    api_version = "2025-04-01-preview"
    url = f"{AZURE_ENDPOINT}/images/generations?api-version={api_version}"

    resp = httpx.post(
        url,
        headers={
            "api-key": AZURE_KEY,
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        },
        timeout=timeout,
    )
    resp.raise_for_status()

    data = resp.json()
    if "data" in data and len(data["data"]) > 0:
        item = data["data"][0]
        b64 = item.get("b64_json", "")
        url_img = item.get("url", "")

        if b64:
            return Image.open(io.BytesIO(base64.b64decode(b64)))
        elif url_img:
            img_resp = httpx.get(url_img, timeout=30)
            img_resp.raise_for_status()
            return Image.open(io.BytesIO(img_resp.content))

    raise RuntimeError(f"Azure returned no image: {str(data)[:300]}")


def _generate_gemini(
    prompt: str,
    reference_image: Image.Image | None = None,
    timeout: int = 120,
) -> Image.Image:
    from .character import _pil_to_data_url

    parts: list[dict] = [{"text": prompt}]
    if reference_image is not None:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": _pil_to_data_url(reference_image)},
            }
        )

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent"

    resp = httpx.post(
        url,
        params={"key": GEMINI_KEY},
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        },
        timeout=timeout,
    )
    resp.raise_for_status()

    data = resp.json()
    if "candidates" in data:
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                b64 = part["inlineData"]["data"]
                return Image.open(io.BytesIO(base64.b64decode(b64)))

    raise RuntimeError(f"Gemini returned no image: {str(data)[:300]}")
