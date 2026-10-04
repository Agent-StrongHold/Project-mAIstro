"""Shared persistence contract for the Learning record.

The in-memory, SQLite and PostgreSQL stores are implementations of one record
contract. Keeping the field disposition explicit gives conformance tests a
stable tripwire when the dataclass gains a field: it must be persisted by both
twins or be deliberately classified as generated.
"""

from __future__ import annotations

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
        # Gauntlet validation provenance (M4-B2): durable like every other
        # Learning field, so a restart cannot strip a promoted learning of the
        # evidence that promoted it.
        "validated_by",
        "validated_evaluator_version",
        "validated_at",
        "validation_run_ids",
        "validation_content_hash",
        # Knowledge-stage ladder (M4-B1 / ADR-103).
        "stage",
        "promoted_by",
    }
)
