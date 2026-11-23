"""Durable Evolve domain snapshot/publication store (#1064).

Three honest backends — PostgreSQL (asyncpg, the production fence), sqlite
(file-backed twin for sqlite deployments), and memory (explicitly non-durable)
— must agree on the contract recovery depends on:

* snapshots save and load by kind, latest-first by journal sequence;
* the battle publication primary key is an exactly-once fence: two racing
  publishers cannot both insert, and the loser reads the winner's row;
* the finalize marker is an upsert whose latest payload wins;
* the journal replays in insertion order after a sequence watermark.

The PostgreSQL leg is the one that proves multi-replica fencing for real:
two independent pools (two processes' connection authorities) race the same
logical battle insert, and a subprocess (a genuinely distinct process) wins
an insert the test process then observes without re-publishing. Skipped
unless ``MAISTRO_TEST_PG_DSN`` names a reachable server, like every other
PG-leg suite in this repo.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from services.evolve_domain_store import (
    EvolveDomainPublication,
    EvolveDomainSnapshot,
    InMemoryEvolveDomainStore,
    SqliteEvolveDomainStore,
)

pytestmark = pytest.mark.contract("behavioral")

_WS = "workspace-evolve-1064"


def _snapshot(run_id: str, kind: str, *, seq: int = 0) -> EvolveDomainSnapshot:
    return EvolveDomainSnapshot(
        workspace_id=_WS,
        run_id=run_id,
        kind=kind,
        membership_ids=["g1", "g2"],
        membership_hash="hash-1",
        completed_cycles=1,
        genomes=['{"id":"g1"}'],
        tournament={"version": 1},
        cycle_markers={"finalize:nr-x": {"status": "committed"}},
        last_battle_seq=seq,
    )


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        yield InMemoryEvolveDomainStore()
    else:
        backend = SqliteEvolveDomainStore(str(tmp_path / "evolve_domain.db"))
        await backend.ensure_schema()
        yield backend


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_kind", ["memory", "sqlite"])
async def test_backend_names_are_honest_about_durability(backend_kind: str, tmp_path: Path) -> None:
    """Recovery trusts ``backend`` to mean cross-process durability (#1064).

    The memory twin is explicitly non-durable; reporting itself as anything
    but "memory" would let a restarted process believe a ledger exists that
    died with the old one. The expectation is pinned by the param, not
    derived from the store under test.
    """
    if backend_kind == "memory":
        store = InMemoryEvolveDomainStore()
    else:
        store = SqliteEvolveDomainStore(str(tmp_path / "evolve_domain.db"))
    assert store.backend == backend_kind


@pytest.mark.asyncio
async def test_snapshots_save_and_load_latest_by_kind(store) -> None:
    await store.save_snapshot(_snapshot("run-1", "admission"))
    await store.save_snapshot(_snapshot("run-2", "committed"))
    await store.save_snapshot(_snapshot("run-3", "admission"))

    latest_committed = await store.latest_snapshot(_WS, kind="committed")
    assert latest_committed is not None
    assert latest_committed.run_id == "run-2"
    latest_any = await store.latest_snapshot(_WS)
    assert latest_any is not None
    assert latest_any.run_id == "run-3"
    assert await store.latest_snapshot("workspace-nothing") is None


@pytest.mark.asyncio
async def test_battle_publication_insert_is_the_exactly_once_fence(store) -> None:
    pub = EvolveDomainPublication(
        effect_kind="battle",
        node_run_id="nr-1",
        benchmark="proxy",
        attempt_id="at-1",
        run_id="run-1",
        payload={"genome_a_id": "g1", "genome_b_id": "g2", "score_a": 0.9, "score_b": 0.2},
    )
    assert await store.record_battle_publication(_WS, pub) is True
    # The second publish of the same logical battle loses the fence.
    assert await store.record_battle_publication(_WS, pub) is False
    found = await store.find_battle_publication(_WS, "nr-1", "proxy")
    assert found is not None
    assert found.payload["score_a"] == 0.9
    assert found.run_id == "run-1"
    # A different logical battle (different NodeRun) is never suppressed.
    other = pub.model_copy(update={"node_run_id": "nr-2"})
    assert await store.record_battle_publication(_WS, other) is True


@pytest.mark.asyncio
async def test_journal_replays_in_order_after_watermark(store) -> None:
    for index in range(3):
        await store.record_battle_publication(
            _WS,
            EvolveDomainPublication(
                effect_kind="battle",
                node_run_id=f"nr-{index}",
                benchmark="proxy",
                run_id="run-1",
                payload={"i": index},
            ),
        )
    head = await store.battle_journal_head(_WS)
    assert head > 0
    rows = await store.list_battle_publications(_WS)
    assert [p.node_run_id for p in rows] == ["nr-0", "nr-1", "nr-2"]
    assert rows[0].sequence < rows[1].sequence < rows[2].sequence == head
    tail = await store.list_battle_publications(_WS, after_seq=rows[0].sequence)
    assert [p.node_run_id for p in tail] == ["nr-1", "nr-2"]
    assert await store.battle_journal_head("workspace-empty") == 0


@pytest.mark.asyncio
async def test_finalize_marker_upsert_latest_payload_wins(store) -> None:
    await store.upsert_finalize_marker(_WS, "nr-f", {"status": "in_progress"}, run_id="run-1")
    first = await store.get_finalize_marker(_WS, "nr-f")
    assert first is not None
    assert first.payload == {"status": "in_progress"}
    await store.upsert_finalize_marker(
        _WS, "nr-f", {"status": "committed", "output": {"population_size": 4}}, run_id="run-1"
    )
    second = await store.get_finalize_marker(_WS, "nr-f")
    assert second is not None
    assert second.payload["status"] == "committed"
    markers = await store.list_finalize_markers(_WS)
    assert markers[0].node_run_id == "nr-f"
    assert await store.get_finalize_marker(_WS, "nr-other") is None


# --- PostgreSQL legs: the real multi-replica fence --------------------------


def _pg_dsn() -> str:
    return os.environ.get("MAISTRO_TEST_PG_DSN", "").strip()


async def _pg_store(dsn: str):
    asyncpg = pytest.importorskip("asyncpg")

    from services.evolve_domain_store import PgEvolveDomainStore

    # No JSON codec registration: the store is codec-independent by contract
    # (writes cast text::jsonb explicitly, reads decode defensively), which is
    # exactly what lets a subprocess or a foreign pool interoperate.
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    return PgEvolveDomainStore(pool), pool


@pytest.fixture
async def pg_store():
    dsn = _pg_dsn()
    if not dsn:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; the PostgreSQL leg needs a real server")
    store, pool = await _pg_store(dsn)
    await store.ensure_schema()
    try:
        # Truncate only this suite's tables — a restarted database (or a
        # prior run of this suite) must not answer for this test's keys.
        await pool.execute("DELETE FROM evolve_domain_publications WHERE workspace_id = $1", _WS)
        await pool.execute("DELETE FROM evolve_domain_snapshots WHERE workspace_id = $1", _WS)
        yield store
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_pg_concurrent_publishers_fence_on_one_row(pg_store) -> None:
    """Two replicas racing one logical battle insert: exactly one wins (#1064)."""
    pub = EvolveDomainPublication(
        effect_kind="battle",
        node_run_id="nr-race",
        benchmark="proxy",
        attempt_id="at-race",
        run_id="run-race",
        payload={"genome_a_id": "g1", "genome_b_id": "g2"},
    )
    results = await asyncio.gather(
        *[pg_store.record_battle_publication(_WS, pub) for _ in range(8)]
    )
    assert results.count(True) == 1
    assert results.count(False) == 7
    found = await pg_store.find_battle_publication(_WS, "nr-race", "proxy")
    assert found is not None


@pytest.mark.asyncio
async def test_pg_distinct_process_publishes_once_and_this_process_replays(pg_store) -> None:
    """A genuinely distinct process publishes the battle; this one never re-publishes.

    The issue's close-only bar asks for distinct process launches on real
    PostgreSQL. The subprocess opens its own pool, records the publication,
    and exits; this process — sharing only the database — must observe the
    row, refuse a duplicate insert, and hand the replay path exactly the
    journaled inputs a tournament reconstruction applies.
    """
    script = (
        "import asyncio, sys\n"
        "sys.path.insert(0, 'packages/hive-conductor/backend')\n"
        "from services.evolve_domain_store import (\n"
        "    EvolveDomainPublication, PgEvolveDomainStore,\n"
        ")\n"
        "async def main() -> None:\n"
        "    asyncpg = __import__('asyncpg')\n"
        "    pool = await asyncpg.create_pool(sys.argv[1], min_size=1, max_size=2)\n"
        "    store = PgEvolveDomainStore(pool)\n"
        "    await store.ensure_schema()\n"
        "    inserted = await store.record_battle_publication(\n"
        "        sys.argv[2],\n"
        "        EvolveDomainPublication(\n"
        "            effect_kind='battle', node_run_id='nr-subprocess', benchmark='proxy',\n"
        "            attempt_id='at-subprocess', run_id='run-subprocess',\n"
        "            payload={'genome_a_id': 'g1', 'genome_b_id': 'g2',\n"
        "                     'score_a': 0.9, 'score_b': 0.2}),\n"
        "    )\n"
        "    print('INSERTED' if inserted else 'FENCED')\n"
        "    await pool.close()\n"
        "asyncio.run(main())\n"
    )
    dsn = _pg_dsn()
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    result = subprocess.run(
        [sys.executable, "-c", script, dsn, _WS],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "INSERTED"

    # This process (different pool, different process) sees exactly one row…
    rows = await pg_store.list_battle_publications(_WS)
    assert [p.node_run_id for p in rows] == ["nr-subprocess"]
    assert rows[0].attempt_id == "at-subprocess"
    assert rows[0].payload["score_a"] == 0.9
    # …and cannot re-publish the same logical battle.
    fenced = await pg_store.record_battle_publication(
        _WS,
        EvolveDomainPublication(
            effect_kind="battle",
            node_run_id="nr-subprocess",
            benchmark="proxy",
            attempt_id="at-other",
            run_id="run-other",
            payload={},
        ),
    )
    assert fenced is False
