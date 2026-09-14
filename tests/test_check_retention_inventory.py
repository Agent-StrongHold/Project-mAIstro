from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def checker():
    import runpy

    return runpy.run_path("scripts/check-retention-inventory.py")


def test_repository_inventory_covers_migrations(checker) -> None:
    assert checker["check"](Path(".")) == []


def test_inventory_rejects_missing_required_policy_fields(checker) -> None:
    with pytest.raises(ValueError, match="missing fields"):
        checker["inventory_tables"]({"tables": [{"table": "audit_log"}]})


def test_inventory_rejects_duplicate_table_entries(checker) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        checker["inventory_tables"](
            {
                "tables": [
                    {
                        "table": "audit_log",
                        "data_class": "audit",
                        "owner": "security",
                        "legal_security_requirement": "audit",
                        "growth_rate": "high",
                        "policy": "delete",
                        "action": "delete",
                    },
                    {
                        "table": "audit_log",
                        "data_class": "audit",
                        "owner": "security",
                        "legal_security_requirement": "audit",
                        "growth_rate": "high",
                        "policy": "delete",
                        "action": "delete",
                    },
                ]
            }
        )
