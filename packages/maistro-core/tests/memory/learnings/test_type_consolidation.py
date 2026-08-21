"""Regression tests for the Learning/Outcome/EpisodicMemory type consolidation.

The maistro.memory.types module and maistro.types.memory module used to define
two divergent dataclass families. Concrete stores/extractors imported the short
variant (missing rca_*/*_after_use/charged_microchips fields) while protocols and
persistence imported the full one. This module pins the behavior that depends on
the full field set, plus the org_id contract on HybridLearningStore.find_relevant.
"""

from __future__ import annotations

from typing import Any

from maistro.memory.learnings.embeddings import FakeEmbeddingClient, HybridLearningStore
from maistro.memory.learnings.extractor import RCAExtractor
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning, MemoryScope


class _FakeLLM:
    """Minimal LLMClient stand-in — satisfies the runtime_checkable protocol."""

    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, **_kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover - unused
        raise NotImplementedError


def _lr(keys: list[str], org: str = "org-1", agent: str | None = "agent-1") -> Learning:
    return Learning(
        tool_name="shell",
        trigger_keys=keys,
        learning="do X not Y",
        org_id=org,
        agent_id=agent,
        scope=MemoryScope.AGENT,
    )


class TestTypeSingleSourceOfTruth:
    def test_memory_types_learning_is_full_variant(self) -> None:
        """maistro.memory.types.Learning must expose the full field set."""
        lr = Learning()
        assert hasattr(lr, "rca_category")
        assert hasattr(lr, "rca_prevention")
        assert hasattr(lr, "success_after_use")
        assert hasattr(lr, "failure_after_use")

    def test_memory_types_learning_is_the_canonical_class(self) -> None:
        from maistro.memory.types import Learning as ShortLearning
        from maistro.types.memory import Learning as FullLearning

        assert ShortLearning is FullLearning

    def test_memory_types_outcome_is_the_canonical_class(self) -> None:
        from maistro.memory.types import Outcome as ShortOutcome
        from maistro.types.memory import Outcome as FullOutcome

        assert ShortOutcome is FullOutcome

    def test_memory_types_episodic_is_the_canonical_class(self) -> None:
        from maistro.memory.types import EpisodicMemory as ShortEpisodic
        from maistro.types.memory import EpisodicMemory as FullEpisodic

        assert ShortEpisodic is FullEpisodic

    def test_outcome_has_both_billing_and_phase2_fields(self) -> None:
        """The canonical Outcome is the union of both former variants."""
        from maistro.types.memory import Outcome

        outcome = Outcome(
            charged_microchips=5,
            pricing_version="v1",
            project_id="proj",
            dag_id="dag",
            dag_run_id="run",
            node_id="node",
            thumb="down",
            thumb_comment="bad",
            eval_judge_score=42.0,
        )
        assert outcome.charged_microchips == 5
        assert outcome.pricing_version == "v1"
        assert outcome.project_id == "proj"
        assert outcome.thumb == "down"
        assert outcome.eval_judge_score == 42.0


class TestRCAExtractorPopulatesRcaFields:
    async def test_extract_rca_returns_learning_with_rca_fields(self) -> None:
        llm = _FakeLLM(
            "CATEGORY: rate_limit\nROOT CAUSE: hit api cap\nPREVENTION: back off and retry"
        )
        extractor = RCAExtractor(llm_client=llm, rca_model="fast")
        history: list[dict[str, object]] = [
            {"tool_name": "api_call", "arguments": {"x": 1}, "result": "Error: 429 rate limit"}
        ]

        learning = await extractor.extract_rca("please call the api now", history)

        assert learning is not None
        assert learning.category == "rca"
        assert learning.rca_category == "rate_limit"
        assert learning.rca_prevention == "back off and retry"

    async def test_extract_rca_unknown_category_when_unrecognized(self) -> None:
        llm = _FakeLLM("CATEGORY: nonsense\nROOT CAUSE: x\nPREVENTION: y")
        extractor = RCAExtractor(llm_client=llm, rca_model="fast")
        history: list[dict[str, object]] = [
            {"tool_name": "api_call", "arguments": {}, "result": "Error: boom"}
        ]

        learning = await extractor.extract_rca("call the api", history)

        assert learning is not None
        assert learning.rca_category == "unknown"

    async def test_extract_rca_none_when_no_failures(self) -> None:
        llm = _FakeLLM("CATEGORY: rate_limit\nPREVENTION: x")
        extractor = RCAExtractor(llm_client=llm)
        history: list[dict[str, object]] = [
            {"tool_name": "api_call", "arguments": {}, "result": "ok"}
        ]

        assert await extractor.extract_rca("call the api", history) is None


class TestHybridFindRelevantHonorsOrgId:
    async def test_org_id_isolation(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["python"], org="org-A"))
        await store.store(_lr(keys=["python"], org="org-B"))
        hybrid = HybridLearningStore(store, FakeEmbeddingClient())

        results = await hybrid.find_relevant("python error", org_id="org-A")

        assert len(results) == 1
        assert results[0].org_id == "org-A"

    async def test_org_id_keyword_only_fallback(self) -> None:
        store = InMemoryLearningStore()
        await store.store(_lr(keys=["docker"], org="org-A"))
        await store.store(_lr(keys=["docker"], org="org-B"))
        hybrid = HybridLearningStore(store, embedding_client=None)

        results = await hybrid.find_relevant("docker build", org_id="org-B")

        assert len(results) == 1
        assert results[0].org_id == "org-B"
