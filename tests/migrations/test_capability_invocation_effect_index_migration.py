"""Migration conformance tests for the capability Invocation effect index (#1194).

Revision 043 recreates ``idx_capability_invocation_effect`` without
``node_run_id`` so the PostgreSQL ledger matches the SQLite twin: the
logical-effect lookup (``node_run_id=None`` — one history per Run across
every physical NodeRun) and the physical-visit lookup must both be served
by one index in both durable backends of the replay contract.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "043_capability_invocation_effect_index.py"


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invocation_effect_index_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Operations:
    def __init__(self) -> None:
        self.created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.dropped: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def create_index(self, *args: Any, **kwargs: Any) -> None:
        self.created.append((args, kwargs))

    def drop_index(self, *args: Any, **kwargs: Any) -> None:
        self.dropped.append((args, kwargs))


def test_effect_index_migration_follows_the_chain_tip() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    directory = ScriptDirectory.from_config(config)

    revision = directory.get_revision("043")
    assert revision.revision == "043"
    # 043 followed 042 when written, then re-parented onto develop's
    # `039_quota_usage_event_identity` (#1204) when that branch also took 042
    # as its parent, and once more onto #286's `044_canvas_store_tables`
    # (PR #1620) when develop claimed that parent while this branch was open
    # — the same renumbering this chain performs on every develop collision.
    # The invariant is one linear head — now `045`, this branch's Run-scoped
    # logical-effect admission revision that continues 043's chain — with the
    # revisions it superseded on its ancestor path, not any fixed parent.
    # `046_durable_elevation_grants` (#72) continues the chain after this
    # branch's `045`, and `047_capability_binding_revocations` (#1133) after
    # that; #398's `048_canvas_job_retry_backoff` continues it after `047`,
    # `049_design_artifact_versions` (#780) continues that; #774's
    # `050_design_creative_briefs` — renumbered past 048 and 049 as #398 and
    # #780 claimed them — continues after that; and #792's eval-score
    # evidence, which had taken `049` on this branch while develop's
    # artifact-version ledger took the same number on the same parent,
    # re-parents onto that `050` as `051_canonical_run_eval_scores`. Develop's
    # knowledge-stage ladder (M4-B1, ADR-103) then claimed `052` on the same
    # chain tip as `052_learning_stage_ladder`, and its learning-lifecycle
    # columns (M4-B, ADR-100126-8c2d) continued that tip as
    # `053_learning_lifecycle_columns`. The learning applicability
    # migration (M4-B3, #119) — after four collision renumberings — re-parents
    # onto that `053` as `054_learning_applicability_epistemics`. The forward
    # admission-generation representation (#1892) — numbered `053` when
    # written, re-parented to `054` unaware of the open `054` — landed
    # second again and re-parented onto the applicability tip as
    # `055_task_admission_generations`. #1047's user-model tables — numbered
    # `054` when written on the same `053` base, re-parented onto the first
    # `054` as `055` — collided a second time there and re-parented onto
    # that `055` as `056_user_model_facts`. The quota-door revision
    # (#1196/#718) then claimed `055`'s child slot as
    # `043_invocation_quota_door` — a third collision — so the quota door
    # keeps develop's parent. #863's planner-stability revision, numbered
    # `052` when written and re-parented onto the chain tip as `053`, `054`,
    # and `056` in the earlier collisions, landed on top of develop's
    # `056_user_model_facts` as `057`; and the Gauntlet provenance (#118,
    # M4-B2) — `053` through six collision renumberings, most recently past
    # `053_learning_lifecycle_columns` — re-parented onto that
    # planner-stability tip as `058_learning_validation_provenance`. The
    # backlog pair (#98/#102) then claimed the next two slots on that tip as
    # `059_backlog_work_source` and `060_backlog_authority_cutover`, so
    # #1109's pause-kind projection (M1-B8) — `059` when written on that
    # same `058` tip — renumbers past them (a landed trunk migration never
    # moves; 046 records the convention), re-parenting onto develop's `060`
    # as `061_hitl_pause_kind_index`. The single linear head is `061`.
    walked = {item.revision for item in directory.walk_revisions("base", "061")}
    assert "039_quota_usage_event_identity" in walked
    assert "044" in walked
    assert "043" in walked
    assert "045" in walked
    assert "046" in walked
    assert "047" in walked
    assert "048" in walked
    assert "049" in walked
    assert "050" in walked
    assert "051" in walked
    assert "052" in walked
    assert "053" in walked
    assert "054" in walked
    assert "055" in walked
    assert "043_invocation_quota_door" in walked
    assert "056" in walked
    assert "057" in walked
    assert "058" in walked
    assert "059" in walked
    assert "060" in walked
    assert directory.get_heads() == ["061"]


def test_upgrade_and_downgrade_swap_the_index_shape(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = _Operations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    # Drop first: the pre-#1194 shape led with node_run_id, so the
    # logical-effect lookup could not use it past the run_id prefix.
    assert operations.dropped == [
        (("idx_capability_invocation_effect",), {"table_name": "capability_invocations"})
    ]
    assert operations.created == [
        (
            (
                "idx_capability_invocation_effect",
                "capability_invocations",
                ["run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
            ),
            {},
        )
    ]

    migration.downgrade()

    # The downgrade restores the historical shape exactly: a deployment that
    # must roll back keeps the index it was migrated from.
    assert operations.created[-1] == (
        (
            "idx_capability_invocation_effect",
            "capability_invocations",
            ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
        ),
        {},
    )
