"""I32: Concurrency testing — async strike tracker race conditions."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.security.strikes import InMemoryStrikeTracker, StrikeRecord


async def _record_n_violations(tracker: InMemoryStrikeTracker, user_id: str, n: int) -> None:
    tasks = []
    for i in range(n):
        tasks.append(
            tracker.record_violation(
                user_id=user_id,
                flags=(f"flag_{i}",),
                boundary="user_input",
                detail=f"concurrent test {i}",
            )
        )
    await asyncio.gather(*tasks)


async def _record_sequential(tracker: InMemoryStrikeTracker, user_id: str, n: int) -> list[StrikeRecord]:
    results = []
    for i in range(n):
        r = await tracker.record_violation(
            user_id=user_id,
            flags=(f"flag_{i}",),
            boundary="user_input",
            detail=f"sequential test {i}",
        )
        results.append(r)
    return results


class TestStrikeConcurrency:
    def test_concurrent_violations_count_correctly(self):
        tracker = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker, "user1", 3))
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.strike_count == 3
        assert record.disabled

    def test_concurrent_violations_all_recorded(self):
        tracker = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker, "user1", 5))
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert len(record.violations) == 5

    def test_concurrent_vs_same_count(self):
        tracker_concurrent = InMemoryStrikeTracker()
        tracker_sequential = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker_concurrent, "u1", 3))
        asyncio.run(_record_sequential(tracker_sequential, "u1", 3))
        rec_c = asyncio.run(tracker_concurrent.get("u1"))
        rec_s = asyncio.run(tracker_sequential.get("u1"))
        assert rec_c is not None and rec_s is not None
        assert rec_c.strike_count == rec_s.strike_count == 3

    def test_concurrent_different_users_independent(self):
        tracker = InMemoryStrikeTracker()

        async def run():
            await asyncio.gather(
                _record_n_violations(tracker, "alice", 2),
                _record_n_violations(tracker, "bob", 3),
            )

        asyncio.run(run())
        alice = asyncio.run(tracker.get("alice"))
        bob = asyncio.run(tracker.get("bob"))
        assert alice is not None
        assert bob is not None
        assert alice.strike_count == 2
        assert bob.strike_count == 3
        assert not alice.disabled
        assert bob.disabled

    def test_concurrent_violations_scrutiny_level(self):
        tracker = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker, "user1", 1))
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.scrutiny_level == "elevated"

    def test_concurrent_lock_after_two(self):
        tracker = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker, "user1", 2))
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.locked_until is not None
        assert not record.disabled

    def test_high_concurrency_20_violations(self):
        tracker = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker, "user1", 20))
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.strike_count == 20
        assert record.disabled
        assert len(record.violations) == 20

    def test_concurrent_unlock_and_record(self):
        tracker = InMemoryStrikeTracker()

        async def run():
            await _record_n_violations(tracker, "user1", 2)
            await tracker.unlock("user1")
            await tracker.record_violation(
                user_id="user1",
                flags=("flag_new",),
                boundary="user_input",
                detail="after unlock",
            )

        asyncio.run(run())
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.strike_count == 3
        assert record.disabled

    def test_concurrent_enable_and_record(self):
        tracker = InMemoryStrikeTracker()

        async def run():
            await _record_n_violations(tracker, "user1", 3)
            await tracker.enable("user1")
            await tracker.record_violation(
                user_id="user1",
                flags=("flag_new",),
                boundary="user_input",
                detail="after enable",
            )

        asyncio.run(run())
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.strike_count == 4

    @given(n=st.integers(min_value=1, max_value=10))
    @settings(max_examples=20)
    def test_concurrent_count_matches_n(self, n):
        tracker = InMemoryStrikeTracker()
        asyncio.run(_record_n_violations(tracker, "user1", n))
        record = asyncio.run(tracker.get("user1"))
        assert record is not None
        assert record.strike_count == n
        assert len(record.violations) == n
