"""`llm.summarize` — single-shot LLM summarization against the LLM gateway.

The model is configurable per-node (the optimizer swaps when latency/cost
budgets demand). The base URL + API key come from the runtime context
(maistro config) — not from the DAG definition — so user-saved DAGs are
portable across environments.
"""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic import BaseModel, Field

from maistro.http import shared_client

from . import register_node
from .base import BaseNode, NodeContext


class LlmSummarizeIn(BaseModel):
    text: str = Field(description="Source text to summarize")
    style: str = Field(
        default="bullet",
        description="bullet | paragraph | exec_summary | tldr",
    )
    model: str = Field(
        default="gemini-3.1-flash-lite",
        description="Model alias on the LLM gateway",
    )
    max_tokens: int = Field(default=512, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    system_prompt_extra: str = Field(
        default="",
        description="Optional extra system context (e.g. project profile)",
    )
    timeout_s: float = 30.0


class LlmSummarizeOut(BaseModel):
    summary: str
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0


_STYLE_PROMPTS = {
    "bullet": "Summarize the text as a concise bullet list. Use - prefix; one bullet per distinct point.",
    "paragraph": "Summarize the text as a single tight paragraph (3-5 sentences).",
    "exec_summary": (
        "Summarize as an executive summary: a one-line headline, then 3 bullets "
        "of key wins / blockers / next actions."
    ),
    "tldr": "Give a one-sentence TL;DR.",
}


@register_node
class LlmSummarizeNode(BaseNode[LlmSummarizeIn, LlmSummarizeOut]):
    kind: ClassVar[str] = "llm.summarize"
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = LlmSummarizeIn
    output_schema: ClassVar[type[BaseModel]] = LlmSummarizeOut
    cost_hint: ClassVar[float] = 3.0  # billable LLM call
    idempotent: ClassVar[bool] = False  # LLM output varies; not safe to retry blindly
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "LLM: summarize"
    description: ClassVar[str] = (
        "One-shot LLM summarization (bullet / paragraph / exec / tldr). "
        "Runs against the configured LLM gateway."
    )

    async def _execute(self, inputs: LlmSummarizeIn, ctx: NodeContext) -> LlmSummarizeOut:
        # LLM gateway endpoint + key — pulled from env (maistro config layer
        # already loads these). The node never hardcodes credentials.
        base_url = (
            os.environ.get("MAISTRO_LLM_BASE_URL")
            or os.environ.get("LITELLM_URL")
            or os.environ.get("LITELLM_API_BASE")
            or ""
        ).rstrip("/")
        api_key = (
            os.environ.get("MAISTRO_LLM_API_KEY")
            or os.environ.get("LITELLM_API_KEY")
            or os.environ.get("LITELLM_MASTER_KEY")
            or ""
        )
        if not base_url:
            raise RuntimeError("llm.summarize: no LLM base URL configured")

        sys_prompt = _STYLE_PROMPTS.get(inputs.style, _STYLE_PROMPTS["bullet"])
        if inputs.system_prompt_extra:
            sys_prompt = sys_prompt + "\n\n" + inputs.system_prompt_extra

        payload = {
            "model": inputs.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": inputs.text},
            ],
            "max_tokens": inputs.max_tokens,
            "temperature": inputs.temperature,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with shared_client(timeout=inputs.timeout_s) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions", json=payload, headers=headers
            )

        if resp.status_code == 401:
            raise PermissionError("llm_auth_failed status=401 (check LITELLM_API_KEY)")
        if resp.status_code == 429:
            raise RuntimeError("llm_rate_limited status=429")
        if resp.status_code >= 400:
            raise RuntimeError(f"llm_http_error status={resp.status_code}")

        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
        usage = data.get("usage", {}) or {}
        return LlmSummarizeOut(
            summary=text.strip(),
            model_used=data.get("model", inputs.model),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )
