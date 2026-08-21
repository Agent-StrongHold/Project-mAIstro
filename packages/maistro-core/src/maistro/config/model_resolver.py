"""Model resolution — maps tier model names to Pydantic AI model strings.

Extracted from agents/conductor.py to keep infrastructure concerns
(URL manipulation, settings reads) separate from agent logic.
"""

from __future__ import annotations

from maistro.config.settings import get_settings


def resolve_model(tier_model: str) -> tuple[str, str | None, bool]:
    """Resolve a tier model name to (model_name, base_url, use_json_mode).

    Returns use_json_mode=True for Ollama models that need JSON-prompt fallback
    instead of tool-based structured output.
    """
    settings = get_settings()

    if settings.litellm.base_url and settings.litellm.base_url != "http://localhost:4000":
        model_name = tier_model.split("/")[-1]
        return f"openai:{model_name}", settings.litellm.base_url, False

    # Ollama: strip ollama/ prefix, use OpenAI-compat endpoint, enable JSON mode
    if tier_model.startswith("ollama/"):
        model_name = tier_model.removeprefix("ollama/")
        return f"openai:{model_name}", settings.ollama_base_url, True

    # Direct provider access — no base_url override
    return tier_model, None, False
