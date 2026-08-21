"""Run the executable terminal benchmark with a configured model provider."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from maistro_evolve.benchmarks.executable_terminal import (
    HOLDOUT_TASKS,
    TRAINING_TASKS,
    append_jsonl,
    result_summary,
    run_executable_terminal_tasks,
)
from maistro_evolve.providers import CodexCliProvider, OpenAICompatibleProvider

ProviderName = Literal["codex", "openai-compatible"]


class ModelProvider(Protocol):
    async def __call__(self, prompt_or_messages: str | list[dict[str, Any]], **kwargs: Any) -> str:
        """Return a model response for the prompt or messages."""


async def run_once(
    *,
    ledger: Path,
    provider_name: ProviderName = "codex",
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    allow_unauthenticated_provider: bool = False,
) -> dict[str, object]:
    provider = build_provider(
        provider_name=provider_name,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        allow_unauthenticated_provider=allow_unauthenticated_provider,
    )
    training = await run_executable_terminal_tasks(TRAINING_TASKS, provider)
    training_summary = result_summary(training)
    append_jsonl(ledger, {"provider": provider_name, "phase": "training", **training_summary})

    feedback = _build_feedback(training_summary)
    if feedback:
        await provider(feedback)

    holdout = await run_executable_terminal_tasks(HOLDOUT_TASKS, provider)
    holdout_summary = result_summary(holdout)
    append_jsonl(ledger, {"provider": provider_name, "phase": "holdout", **holdout_summary})
    return {"training": training_summary, "holdout": holdout_summary}


def build_provider(
    *,
    provider_name: ProviderName,
    model: str | None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    allow_unauthenticated_provider: bool = False,
) -> ModelProvider:
    if provider_name == "codex":
        return cast(ModelProvider, CodexCliProvider(model=model))
    if provider_name == "openai-compatible":
        return cast(
            ModelProvider,
            OpenAICompatibleProvider(
                model=model,
                base_url=base_url,
                api_key_env=api_key_env,
                allow_unauthenticated=allow_unauthenticated_provider,
            ),
        )
    raise ValueError(f"Unsupported provider: {provider_name}")


def _build_feedback(summary: dict[str, object]) -> str:
    results = cast(dict[str, dict[str, Any]], summary["results"])
    failed = [
        f"{task_id}: {result.get('error') or result.get('mismatches')}"
        for task_id, result in results.items()
        if not result.get("passed")
    ]
    if not failed:
        return ""
    return (
        "Executable terminal benchmark feedback. Improve future responses while preserving the "
        "restricted action language, action budgets, and untrusted-data rule. Failed tasks:\n"
        + "\n".join(failed)
        + "\nReturn exactly READY."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run executable terminal eval with a model provider."
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("test-results/evolve/executable-terminal.jsonl"),
    )
    parser.add_argument(
        "--provider",
        choices=("codex", "openai-compatible"),
        default="codex",
        help="Model provider to call from the controller.",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Base URL for --provider openai-compatible. Defaults to MAISTRO_OPENAI_BASE_URL, "
            "OPENAI_BASE_URL, LITELLM_BASE_URL, then https://api.openai.com/v1."
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="Environment variable containing the OpenAI-compatible API key.",
    )
    parser.add_argument(
        "--allow-unauthenticated-provider",
        action="store_true",
        help="Permit an OpenAI-compatible local gateway without an Authorization header.",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run_once(
            ledger=args.ledger,
            provider_name=cast(ProviderName, args.provider),
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            allow_unauthenticated_provider=args.allow_unauthenticated_provider,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
