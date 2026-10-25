"""Code registry entry types (SPEC-257 / ADR-069)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CodeKind(StrEnum):
    COMPENSATOR = "compensator"
    IMPACT_ESTIMATOR = "impact_estimator"
    IDEMPOTENCY_KEY = "idempotency_key"
    MERGE_RESOLVER = "merge_resolver"
    DYNAMIC_GATE = "dynamic_gate"


@dataclass(frozen=True)
class CodeEntry:
    name: str
    version: str
    kind: CodeKind
    code_sha256: str
    signature: bytes
    trusted: bool = False


class CodeRefUnresolved(Exception):
    pass


class InvalidSignature(Exception):
    pass
