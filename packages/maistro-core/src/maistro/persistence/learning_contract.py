"""Shared persistence contract for the Learning record.

The in-memory, SQLite and PostgreSQL stores are implementations of one record
contract. Keeping the field disposition explicit gives conformance tests a
stable tripwire when the dataclass gains a field: it must be persisted by both
twins or be deliberately classified as generated.
"""

from __future__ import annotations

# The contract names are the module's public surface: the SQL twins consume the
# field sets, and the conformance tests pin the disposition partition. Vulture
# only sees the src-side readers, so without ``__all__`` it mistakes the
# test-pinned partition for dead code.
__all__ = [
    "LEARNING_FIELD_DISPOSITIONS",
    "LEARNING_GENERATED_FIELDS",
    "LEARNING_PERSISTED_FIELDS",
]

# ``id`` is assigned by each store's identity mechanism. Every other declared
# Learning field is durable and must be represented by both SQL twins.
LEARNING_GENERATED_FIELDS = frozenset({"id"})
LEARNING_PERSISTED_FIELDS = frozenset(
    {
        "category",
        "trigger_keys",
        "learning",
        "tool_name",
        "source_query",
        "org_id",
        "team_id",
        "agent_id",
        "user_id",
        "scope",
        "hit_count",
        "status",
        "rca_category",
        "rca_prevention",
        "success_after_use",
        "failure_after_use",
        "run_id",
        "node_run_id",
        "attempt_id",
    }
)

# This is intentionally a complete partition rather than a list of known
# fields: adding a Learning field without choosing a disposition fails the
# machine-checked contract test.
LEARNING_FIELD_DISPOSITIONS = {
    **dict.fromkeys(LEARNING_PERSISTED_FIELDS, "persisted"),
    **dict.fromkeys(LEARNING_GENERATED_FIELDS, "generated"),
}
