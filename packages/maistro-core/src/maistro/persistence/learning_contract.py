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
        # Gauntlet validation provenance (M4-B2) plus the knowledge-stage
        # ladder and pipeline epistemics (ADR-103, ADR-100126-8c2d, EPIC M4-B).
        # A restart must not strip a promoted learning of the evidence that
        # promoted it, demote a validated learning back to a local belief, or
        # resurrect a superseded one, so all of it is durable like every other
        # Learning field.
        "validated_by",
        "validated_evaluator_version",
        "validated_at",
        "validation_run_ids",
        "validation_content_hash",
        "stage",
        "epistemic_type",
        "confidence",
        "applicability",
        "reinforcement_count",
        "contradiction_count",
        "created_at",
        "last_confirmed_at",
        "promoted_by",
        "supersedes",
        "superseded_by",
    }
)
