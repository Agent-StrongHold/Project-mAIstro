#!/usr/bin/env python3
"""Working-memory projection benchmark (issue #301 / ADR-082226-5104 §8).

Answers, with numbers instead of guesses, the open engineering questions
ADR-082226-5104 leaves to measurement, at the concurrency points the issue
names — 1, 10 and 100 concurrently active Workspace projections:

* RAM footprint per projection (current RSS delta + process high-water);
* hydration cost from authoritative-shaped records (wall time, per record);
* BM25 lexical recall latency (p50/p95);
* hybrid recall latency with stored embeddings (p50/p95) — one query embed,
  stored vectors only;
* graph traversal latency (p50/p95).

Everything is deterministic and offline: the corpus is generated, and the
embedder is a hashed bag-of-words, so numbers compare run-to-run. This is a
hot-projection benchmark, not a durable-store one — no PostgreSQL, no network.

Usage:
    uv run python scripts/bench_working_memory.py [--workspaces 1 10 100]
        [--records-per-workspace 100] [--queries 200] [--output results.json]
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "maistro-core" / "src"))

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.working.manager import WorkingMemoryManager
from maistro.memory.working.projection import WorkspaceWorkingMemoryProjection

_WORD = re.compile(r"[a-z]+")
_VOCAB = [
    "postgres",
    "pgvector",
    "ladybug",
    "workspace",
    "memory",
    "graph",
    "run",
    "node",
    "attempt",
    "schedule",
    "retry",
    "quota",
    "agent",
    "persona",
    "session",
    "artifact",
    " dreaming",
    "consolidation",
    "hypothesis",
    "budget",
    "token",
    "embedding",
    "similarity",
    "traversal",
    "entity",
    "mention",
    "cluster",
    "decay",
    "weight",
    "scope",
] * 4

_DIM = 64


class HashEmbedder:
    """Deterministic hashed bag-of-words embedder. Offline and fast."""

    def __init__(self, dim: int = _DIM) -> None:
        self.dim = dim
        self.calls = 0

    @property
    def dimension(self) -> int:
        return self.dim

    def vector_for(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            index = digest[0] % self.dim
            vec[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return self.vector_for(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


def _rss_kb() -> int:
    """Current RSS of this process, in KB (Linux /proc)."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def _make_records(workspace_index: int, count: int) -> list[EpisodicMemory]:
    records: list[EpisodicMemory] = []
    for i in range(count):
        words = [_VOCAB[(workspace_index * 7 + i * 3 + j) % len(_VOCAB)] for j in range(12)]
        content = f"Workspace{workspace_index} note {i}: " + " ".join(words)
        records.append(
            EpisodicMemory(
                memory_id=f"ws{workspace_index}-m{i}",
                tier=MemoryTier.LESSON,
                content=content,
                weight=0.4 + (i % 5) * 0.1,
                org_id=f"org-{workspace_index}",
                agent_id=f"agent-{i % 4}",
                project_id=f"proj-{i % 3}",
                run_id=f"run-{i}",
                node_run_id=f"node-{i}",
                attempt_id=f"attempt-{i}",
                scope=MemoryScope.AGENT,
            )
        )
    return records


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[max(index, 0)]


@dataclass
class WorkspaceBench:
    workspaces: int
    records_per_workspace: int
    rss_delta_kb: int
    rss_peak_kb: int
    hydration_seconds: float
    hydration_per_record_ms: float
    bm25_p50_ms: float
    bm25_p95_ms: float
    hybrid_p50_ms: float
    hybrid_p95_ms: float
    traverse_p50_ms: float
    traverse_p95_ms: float
    total_records: int
    total_entities: int
    total_relations: int


async def bench(workspaces: int, records_per_workspace: int, queries: int) -> WorkspaceBench:
    import asyncio

    embedder = HashEmbedder()
    manager = WorkingMemoryManager(
        workspace_id="ws-0",
        episodic_store=_NullStore(),
        embedding_client=embedder,
        embedding_model="bench-hash-embedder-v1",
    )
    projections: list[WorkspaceWorkingMemoryProjection] = []

    gc.collect()
    rss_before = _rss_kb()
    peak_before = _peak_rss_kb()

    corpora = [_make_records(w, records_per_workspace) for w in range(workspaces)]

    hydration_start = time.perf_counter()
    for w, records in enumerate(corpora):
        projection = manager.projection(f"ws-{w}")
        await projection.hydrate(records)
        projections.append(projection)
    hydration_seconds = time.perf_counter() - hydration_start

    rss_after = _rss_kb()

    total_records = sum(p.stats.records for p in projections)
    total_entities = sum(p.stats.entities for p in projections)
    total_relations = sum(p.stats.relations for p in projections)

    bm25_times: list[float] = []
    hybrid_times: list[float] = []
    traverse_times: list[float] = []
    projection = projections[0]
    for q in range(queries):
        query = f"workspace0 note {q % records_per_workspace} postgres pgvector memory"
        start = time.perf_counter()
        await projection.recall_lexical(query, limit=10)
        bm25_times.append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        await projection.recall(query, limit=10)
        hybrid_times.append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        await projection.traverse(_VOCAB[q % len(_VOCAB)].strip(), max_depth=2)
        traverse_times.append((time.perf_counter() - start) * 1000)
    # Let the loop's tasks settle before reporting.
    await asyncio.sleep(0)

    return WorkspaceBench(
        workspaces=workspaces,
        records_per_workspace=records_per_workspace,
        rss_delta_kb=rss_after - rss_before,
        rss_peak_kb=max(_peak_rss_kb() - peak_before, 0),
        hydration_seconds=round(hydration_seconds, 4),
        hydration_per_record_ms=round(hydration_seconds * 1000 / max(total_records, 1), 4),
        bm25_p50_ms=round(_percentile(bm25_times, 50), 4),
        bm25_p95_ms=round(_percentile(bm25_times, 95), 4),
        hybrid_p50_ms=round(_percentile(hybrid_times, 50), 4),
        hybrid_p95_ms=round(_percentile(hybrid_times, 95), 4),
        traverse_p50_ms=round(_percentile(traverse_times, 50), 4),
        traverse_p95_ms=round(_percentile(traverse_times, 95), 4),
        total_records=total_records,
        total_entities=total_entities,
        total_relations=total_relations,
    )


def _peak_rss_kb() -> int:
    """Process RSS high-water mark in KB (Linux: ru_maxrss is in KB)."""
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


class _NullStore:
    """Stand-in episodic store: the benchmark hydrates explicit record lists."""

    async def list_by_scope(self, **_kwargs: object) -> list[EpisodicMemory]:
        return []


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspaces", type=int, nargs="+", default=[1, 10, 100])
    parser.add_argument("--records-per-workspace", type=int, default=100)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    results = []
    for count in args.workspaces:
        row = await bench(count, args.records_per_workspace, args.queries)
        results.append(asdict(row))
        print(
            f"workspaces={row.workspaces:>3} records={row.total_records:>6} "
            f"rss_delta={row.rss_delta_kb:>7}KB peak_delta={row.rss_peak_kb:>7}KB "
            f"hydrate={row.hydration_seconds:>7.3f}s "
            f"({row.hydration_per_record_ms:.3f} ms/rec) "
            f"bm25 p50/p95={row.bm25_p50_ms:.3f}/{row.bm25_p95_ms:.3f}ms "
            f"hybrid p50/p95={row.hybrid_p50_ms:.3f}/{row.hybrid_p95_ms:.3f}ms "
            f"traverse p50/p95={row.traverse_p50_ms:.3f}/{row.traverse_p95_ms:.3f}ms",
            flush=True,
        )

    payload = {
        "benchmark": "working-memory-projection",
        "issue": "301",
        "adr": "ADR-082226-5104",
        "records_per_workspace": args.records_per_workspace,
        "queries_per_point": args.queries,
        "embedder": "hash-bag-of-words-64 (deterministic, offline)",
        "results": results,
    }
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
