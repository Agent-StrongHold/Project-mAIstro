from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from maistro.graph.types import GraphBlackboard


@dataclass
class CompactionConfig:
    threshold_tokens: int = 8000
    max_summaries: int = 5


class ContextCompactor:
    def __init__(self, config: CompactionConfig | None = None) -> None:
        self._config = config or CompactionConfig()
        self._summaries: list[str] = []

    def should_compact(self, blackboard: GraphBlackboard) -> bool:
        return self._estimate_tokens(blackboard) > self._config.threshold_tokens

    def compact(
        self,
        blackboard: GraphBlackboard,
        llm_call: Callable[..., str] | None = None,
    ) -> GraphBlackboard:
        if llm_call is not None:
            return self._llm_compact(blackboard, llm_call)
        return self._simple_compact(blackboard)

    def _build_compaction_prompt(
        self,
        previous_summary: str | None,
        blackboard: GraphBlackboard,
    ) -> str:
        parts = [
            "Summarize the following execution context concisely.",
        ]
        if previous_summary:
            parts.append(f"\n## Progress So Far\n{previous_summary}")
        parts.append(f"\n## Goal\n{blackboard.task_objective}")
        parts.append(f"\n## Iteration\n{blackboard.iteration}")
        if blackboard.node_annotations:
            annotation_lines = [f"- {k}: {v[:200]}" for k, v in blackboard.node_annotations.items()]
            parts.append("\n## Key Decisions Made\n" + "\n".join(annotation_lines))
        if blackboard.metadata:
            meta_lines = [f"- {k}: {str(v)[:200]}" for k, v in blackboard.metadata.items()]
            parts.append("\n## Critical Context\n" + "\n".join(meta_lines))
        parts.append("\nProduce a concise summary preserving all facts needed for remaining nodes.")
        return "\n".join(parts)

    def _simple_compact(self, blackboard: GraphBlackboard) -> GraphBlackboard:
        max_field_len = 500
        data = blackboard.model_dump()

        data["node_annotations"] = {
            k: v[:max_field_len] if isinstance(v, str) and len(v) > max_field_len else v
            for k, v in data.get("node_annotations", {}).items()
        }

        new_metadata: dict[str, Any] = {}
        for k, v in data.get("metadata", {}).items():
            sv = str(v)
            new_metadata[k] = sv[:max_field_len] if len(sv) > max_field_len else v
        data["metadata"] = new_metadata

        data["optimization_history"] = data.get("optimization_history", [])[-2:]

        summary = f"[Compacted at iteration {blackboard.iteration}]"
        data["metadata"]["_compaction_summary"] = summary

        if len(self._summaries) < self._config.max_summaries:
            self._summaries.append(summary)

        return GraphBlackboard(**data)

    def _llm_compact(
        self,
        blackboard: GraphBlackboard,
        llm_call: Callable[..., str],
    ) -> GraphBlackboard:
        previous = self._summaries[-1] if self._summaries else None
        prompt = self._build_compaction_prompt(previous, blackboard)
        summary = llm_call(prompt)
        if len(self._summaries) < self._config.max_summaries:
            self._summaries.append(summary)
        data = blackboard.model_dump()
        data["metadata"]["_compaction_summary"] = summary
        data["metadata"]["_previous_summary"] = previous
        return GraphBlackboard(**data)

    @staticmethod
    def _estimate_tokens(blackboard: GraphBlackboard) -> int:
        return len(blackboard.model_dump_json()) // 4
