"""Shared durable representation of the Sentinel decision envelope (#69).

The existing store-level audit proof uses ``signature``. The stronger Sentinel
proof has its own column, so a store cannot overwrite the decision it retains.
Only public evidence is serialized here; signing happens before persistence.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from maistro.security.integrity_types import DecisionSignature
from maistro.types.security import AuditEntry, Violation

DECISION_COLUMNS = {
    "action": "TEXT NOT NULL DEFAULT ''",
    "principal_id": "TEXT NOT NULL DEFAULT ''",
    "policy_snapshot": "TEXT NOT NULL DEFAULT ''",
    "payload": "TEXT NOT NULL DEFAULT ''",
    "decision_signature": "TEXT",
    "signature_key_id": "TEXT",
    "signature_algorithm": "TEXT",
    "signature_public_key": "TEXT",
    "violations": "TEXT NOT NULL DEFAULT '[]'",
    "inputs_hash": "TEXT NOT NULL DEFAULT ''",
}


def decision_values(entry: AuditEntry) -> tuple[Any, ...]:
    """Return values in DECISION_COLUMNS order without altering signed defaults."""
    proof = entry.integrity
    return (
        entry.action,
        entry.principal_id,
        entry.policy_snapshot,
        entry.payload,
        proof.signature if proof else None,
        proof.key_id if proof else None,
        proof.algorithm if proof else None,
        proof.public_key if proof else None,
        json.dumps([asdict(violation) for violation in entry.violations], sort_keys=True),
        entry.inputs_hash,
    )


def decision_fields(row: Any) -> dict[str, Any]:
    """Rebuild the signed envelope from a durable mapping, including old rows."""
    signature = row.get("decision_signature")
    key_id = row.get("signature_key_id")
    algorithm = row.get("signature_algorithm")
    public_key = row.get("signature_public_key")
    fields = {
        name: row.get(name, "") or ""
        for name in ("action", "principal_id", "policy_snapshot", "payload", "inputs_hash")
    }
    return {
        **fields,
        "integrity": (
            DecisionSignature(
                key_id=key_id or "",
                algorithm=algorithm or "",
                signature=signature or "",
                public_key=public_key or "",
            )
            if any((signature, key_id, algorithm, public_key))
            else None
        ),
        "violations": tuple(
            Violation(**item) for item in json.loads(row.get("violations", "[]") or "[]")
        ),
    }
