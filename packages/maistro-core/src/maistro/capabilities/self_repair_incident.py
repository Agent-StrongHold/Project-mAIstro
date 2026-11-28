"""Stable incident identity for durable self-repair approval admission (#2405).

The first M1-B8 admission keyed its effect and canonical Run claim on
``id(proposal)`` — a Python object allocation identity that dies with the
process. A restart (or a second replica) observing the same unhealthy
incident therefore computed a *different* key and admitted a second
approval Run for one unresolved incident, breaking the one-in-flight-per-
resource safety promise.

The identity here is derived only from durable facts — Workspace/Project
scope, the affected resource, the requested action and a canonical digest
of the request payload — so every process that observes the same logical
incident computes the same identity, and distinct incidents never alias.

The canonical Run claim rides the existing occurrence-claim machinery
(``runs.sources`` + the unique expression index): the incident scope is the
claim namespace (``schedule_id``) and the episode token is the operation
digest (``schedule_fire_id``, which the store claims as ``manual:<token>``,
disjoint from nominal cron instants). A second process racing the same
incident loses ``create_run`` to ``DuplicateOccurrence`` and reconciles to
the winner's Run — check-then-insert alone is never the authority.

A genuinely new incident *after terminal settlement* must still admit. The
episode token therefore chains: the token after terminal Run ``R`` is a
digest over the base operation plus ``R``'s run_id. Every process derives
the same chain from the same durable fact, the unique claim still decides
the race, and an over-long chain simply fails closed instead of minting a
duplicate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from maistro.runs.sources import SCHEDULE_FIRE_ID_KEY, SCHEDULE_ID_KEY

#: ``admission_source`` provenance value stamped on self-repair approval Runs.
SELF_REPAIR_ADMISSION_SOURCE = "self_repair"

#: Prefix of the occurrence-claim namespace (`schedule_id`) this module mints.
#: A real Schedule id can never take this shape, so the two claim spaces stay
#: disjoint by construction.
INCIDENT_CLAIM_PREFIX = "self-repair-approval"

#: Provenance keys this module adds around the occurrence claim.
INCIDENT_RESOURCE_KEY = "self_repair_resource"
INCIDENT_EPISODE_KEY = "self_repair_episode"

#: Chain depth bound. Each settled episode adds one link; a caller walking
#: past this bound refuses rather than minting a possibly-duplicate claim.
MAX_EPISODE_CHAIN = 16


def incident_operation_digest(resource: str, action: str, params: Mapping[str, Any]) -> str:
    """Stable digest of one logical self-repair operation (process-independent)."""
    payload = json.dumps(
        {"resource": resource, "action": action, "params": dict(params)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stable_effect_key(resource: str, action: str, params: Mapping[str, Any]) -> str:
    """The durable effect key for one self-repair operation.

    Replaces the ``id(proposal)`` suffix: two processes (or one process
    before and after a restart) observing the same incident compute the same
    key, so the governed Invocation ledger and the durable approval both
    bind to one logical effect.
    """
    return f"self_repair:{resource}:{action}:{incident_operation_digest(resource, action, params)[:16]}"


def incident_claim_scope(workspace_id: str, project_id: str, resource: str) -> str:
    """The occurrence-claim namespace for one scoped incident."""
    return f"{INCIDENT_CLAIM_PREFIX}:{workspace_id}:{project_id}:{resource}"


def incident_episode_token(resource: str, action: str, params: Mapping[str, Any]) -> str:
    """The episode-0 claim token: the operation digest itself."""
    return incident_operation_digest(resource, action, params)


def chained_episode_token(token: str, previous_run_id: str) -> str:
    """The token that supersedes a *terminal* episode's claim.

    Deterministic from durable facts (the previous token and the settled
    Run's id), so a restart and a second replica chain to the same next
    episode — and the unique claim, not local bookkeeping, still decides
    which process wins it.
    """
    digest = hashlib.sha256(f"{token}:{previous_run_id}".encode()).hexdigest()
    return digest


def incident_claim(
    *,
    workspace_id: str,
    project_id: str,
    resource: str,
    action: str,
    params: Mapping[str, Any],
) -> dict[str, str]:
    """Provenance keys atomically claiming one incident episode in the RunStore.

    The keys are the occurrence-claim contract (`runs.sources`): the claim
    namespace and the manual-fire token. ``create_run`` enforces uniqueness
    through the store's claim index and raises ``DuplicateOccurrence`` to the
    loser of a race; ``find_occurrence_run`` resolves the winner.
    """
    return {
        SCHEDULE_ID_KEY: incident_claim_scope(workspace_id, project_id, resource),
        SCHEDULE_FIRE_ID_KEY: incident_episode_token(resource, action, params),
        INCIDENT_RESOURCE_KEY: resource,
    }


def chain_incident_claim(claim: Mapping[str, str], previous_run_id: str) -> dict[str, str]:
    """The next episode's claim, superseding a terminal episode's claim."""
    token = str(claim.get(SCHEDULE_FIRE_ID_KEY) or "")
    if not token or not previous_run_id:
        raise ValueError("chaining an incident claim requires its token and the settled run id")
    return {
        **dict(claim),
        SCHEDULE_FIRE_ID_KEY: chained_episode_token(token, previous_run_id),
    }


def is_incident_claim(provenance: Mapping[str, Any] | None) -> bool:
    """Whether provenance carries this module's occurrence claim namespace."""
    if not provenance:
        return False
    scope = provenance.get(SCHEDULE_ID_KEY)
    return isinstance(scope, str) and scope.startswith(f"{INCIDENT_CLAIM_PREFIX}:")


__all__ = [
    "CHAIN_LIMIT_ERROR",
    "INCIDENT_CLAIM_PREFIX",
    "INCIDENT_EPISODE_KEY",
    "INCIDENT_RESOURCE_KEY",
    "MAX_EPISODE_CHAIN",
    "SELF_REPAIR_ADMISSION_SOURCE",
    "chain_incident_claim",
    "chained_episode_token",
    "incident_claim",
    "incident_claim_scope",
    "incident_episode_token",
    "incident_operation_digest",
    "is_incident_claim",
    "stable_effect_key",
]

#: Error text when the episode chain exceeds ``MAX_EPISODE_CHAIN``. Admission
#: fails closed rather than minting an unchained duplicate claim.
CHAIN_LIMIT_ERROR = (
    f"self-repair incident episode chain exceeded {MAX_EPISODE_CHAIN} settled claims; "
    "refusing to admit without a resolvable episode identity"
)
