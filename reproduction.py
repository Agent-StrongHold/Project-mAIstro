import asyncio

import aiosqlite

from maistro.persistence.learning_contract import LEARNING_PERSISTED_FIELDS
from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import Learning


async def main():
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteLearningStore(conn)
        await store.ensure_schema()

        learning = Learning(
            category="test",
            trigger_keys=["test"],
            learning="test learning",
            tool_name="test_tool",
            source_query="test_query",
            org_id="test_org",
            team_id="test_team",
            user_id="test_user",
            agent_id="test_agent",
        )

        print(f"Persisted fields: {LEARNING_PERSISTED_FIELDS}")

        lid = await store.store(learning)
        print(f"Stored ID: {lid}")

        # Check if it's in the DB
        async with conn.execute("SELECT * FROM learnings WHERE id = ?", (lid,)) as cursor:
            columns = [d[0] for d in cursor.description]
            row = await cursor.fetchone()
            row_dict = dict(zip(columns, row, strict=True))
            print(f"Row in DB: {row_dict}")

        # Check if find_relevant works with team_id and trigger_key match
        results = await store.find_relevant("test", team_id="test_team", org_id="test_org")
        print(f"Find relevant results: {results}")

        assert len(results) == 1
        assert results[0].team_id == "test_team"
        assert results[0].source_query == "test_query"
        print("Assertion passed: found learning with team_id and source_query")

        # Check if find_relevant filters by team_id
        results_wrong_team = await store.find_relevant(
            "test", team_id="wrong_team", org_id="test_org"
        )
        print(f"Find relevant results (wrong team): {results_wrong_team}")
        assert len(results_wrong_team) == 0
        print("Assertion passed: correctly filtered by team_id")

        # Check if source_query is persisted
        assert row_dict["source_query"] == "test_query"
        print("Assertion passed: source_query is persisted")


if __name__ == "__main__":
    asyncio.run(main())
