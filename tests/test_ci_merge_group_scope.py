from __future__ import annotations

from scripts.ci_merge_group_scope import LEGS, classify


def test_missing_diff_evidence_fails_closed() -> None:
    assert classify([]) == dict.fromkeys(LEGS, True)


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


def test_archive_change_runs_minio_wheel_and_docker_only() -> None:
    result = classify(["packages/maistro-core/src/maistro/archive/store.py"])
    assert result["object_storage"] is True
    assert result["wheel_imports"] is True
    assert result["docker_build"] is True
    assert result["postgres"] is False
    assert result["hive_e2e"] is False


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
