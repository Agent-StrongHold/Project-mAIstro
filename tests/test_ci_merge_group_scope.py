from __future__ import annotations

import json

import pytest
from scripts.ci_merge_group_scope import LEGS, classify, main


def test_missing_diff_evidence_fails_closed() -> None:
    assert classify([]) == dict.fromkeys(LEGS, True)


def test_durable_or_event_change_runs_durable_events_leg() -> None:
    result = classify(["packages/maistro-core/src/maistro/events/bus.py"])
    assert result["durable_events"] is True
    assert result["postgres"] is False


def test_attempt_change_runs_strike_ladder_leg() -> None:
    result = classify(["packages/maistro-core/src/maistro/runs/attempt.py"])
    assert result["strike_ladder"] is True


def test_cli_main_prints_plain_legs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["ci_merge_group_scope.py", "uv.lock"])
    assert main() == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [f"{leg}=true" for leg in LEGS]


def test_cli_main_prints_json_legs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["ci_merge_group_scope.py", "docs/ci/MERGE-QUEUE.md", "--json"],
    )
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["docker_build"] is True
    assert result["postgres"] is False


def test_shared_dependency_change_runs_every_specialized_leg() -> None:
    assert classify(["uv.lock"]) == dict.fromkeys(LEGS, True)


def test_docs_only_change_skips_service_legs_but_not_docker() -> None:
    result = classify(["docs/ci/MERGE-QUEUE.md"])
    assert result == {
        "postgres": False,
        "object_storage": False,
        "durable_events": False,
        "strike_ladder": False,
        "hive_e2e": False,
        "wheel_imports": False,
        "docker_build": True,
    }


def test_archive_change_runs_minio_wheel_docker_and_hive_e2e() -> None:
    result = classify(["packages/maistro-core/src/maistro/archive/store.py"])
    assert result["object_storage"] is True
    assert result["wheel_imports"] is True
    assert result["docker_build"] is True
    assert result["postgres"] is False
    # Hive imports and ships maistro-core in its E2E image, so any core
    # change can break the live Conductor flow that leg verifies.
    assert result["hive_e2e"] is True


def test_core_only_change_runs_hive_e2e_too() -> None:
    result = classify(["packages/maistro-core/src/maistro/types.py"])
    assert result["hive_e2e"] is True


def test_alembic_ini_runs_postgres_and_docker() -> None:
    result = classify(["alembic.ini"])
    assert result["postgres"] is True
    assert result["docker_build"] is True


def test_durable_events_migration_runs_durable_events_leg() -> None:
    result = classify(["alembic/versions/004_durable_events.py"])
    assert result["postgres"] is True
    assert result["durable_events"] is True


def test_root_file_outside_every_prefix_skips_docker_build_too() -> None:
    assert classify(["LICENSE"]) == dict.fromkeys(LEGS, False)


def test_migration_change_runs_postgres_and_docker() -> None:
    result = classify(["alembic/versions/123_add_table.py"])
    assert result["postgres"] is True
    assert result["docker_build"] is True
    assert result["object_storage"] is False


def test_hive_change_runs_hive_wheel_and_docker() -> None:
    result = classify(["packages/hive-conductor/backend/routes/runs.py"])
    assert result["hive_e2e"] is True
    assert result["wheel_imports"] is True
    assert result["docker_build"] is True


def test_quality_only_change_does_not_claim_service_impact() -> None:
    result = classify(["quality/vulture-baseline.json"])
    assert result["docker_build"] is True
    assert all(not result[leg] for leg in LEGS if leg != "docker_build")


def test_ci_workflow_change_runs_everything() -> None:
    assert classify([".github/workflows/ci.yml"]) == dict.fromkeys(LEGS, True)
