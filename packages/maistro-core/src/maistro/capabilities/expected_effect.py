"""Recomputable expected-effect evidence for canonical Invocations."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ExpectedEffectEvidence(BaseModel):
    """Prediction inputs and host observation persisted on an Invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = ""
    capability: str
    provider: str
    materialized_arguments: dict[str, Any]
    arguments_digest: str = ""
    pre_state_digest: str
    expected_post_state: Any
    observed_post_state: Any | None = None
    matched: bool | None = None
    policy_version: str
    evidence_id: str = Field(default_factory=lambda: uuid4().hex)

    @model_validator(mode="after")
    def _validate_evidence(self) -> ExpectedEffectEvidence:
        if not self.capability.strip() or not self.provider.strip():
            raise ValueError("expected effect capability and provider are required")
        if not self.pre_state_digest.strip() or not self.policy_version.strip():
            raise ValueError("expected effect pre-state digest and policy version are required")
        actual = canonical_digest(self.materialized_arguments)
        if self.arguments_digest and self.arguments_digest != actual:
            raise ValueError(
                "expected effect arguments_digest does not match materialized arguments"
            )
        object.__setattr__(self, "arguments_digest", actual)
        return self

    @property
    def evidence_digest(self) -> str:
        """Digest of all prediction inputs, suitable for later recomputation."""

        return canonical_digest(
            {
                "capability": self.capability,
                "provider": self.provider,
                "materialized_arguments": self.materialized_arguments,
                "arguments_digest": self.arguments_digest,
                "pre_state_digest": self.pre_state_digest,
                "expected_post_state": self.expected_post_state,
                "policy_version": self.policy_version,
            }
        )

    def observed(self, post_state: Any) -> ExpectedEffectEvidence:
        """Return immutable evidence with a host-computed comparison result."""

        return self.model_copy(
            update={
                "observed_post_state": post_state,
                "matched": post_state == self.expected_post_state,
            }
        )


__all__ = ["ExpectedEffectEvidence", "canonical_digest"]
