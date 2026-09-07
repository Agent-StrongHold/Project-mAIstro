"""Durable admission snapshot for canonical Graph launch state.

A queued canonical Run can outlive the process that admitted it before the
first GraphContinuation exists. Recovery must therefore reconstruct the exact
launch inputs and blackboard metadata from durable admission facts; inventing
empty state would execute different work under the same Run identity.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from maistro.runs.model import Run
from maistro.runs.store import RunIntegrityError

DURABLE_GRAPH_LAUNCH_PROVENANCE = "durable_graph_launch"
_INITIAL_INPUTS = "initial_inputs"
_BLACKBOARD_METADATA = "blackboard_metadata"


def durable_graph_launch_provenance(
    *,
    inputs: Mapping[str, Any] | None = None,
    blackboard_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the immutable admission fact required for bootstrap recovery."""
    return {
        DURABLE_GRAPH_LAUNCH_PROVENANCE: {
            _INITIAL_INPUTS: copy.deepcopy(dict(inputs or {})),
            _BLACKBOARD_METADATA: copy.deepcopy(dict(blackboard_metadata or {})),
        }
    }


def launch_state_from_run(run: Run) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the exact durable Graph launch state recorded at admission.

    Runs admitted before this contract existed legitimately have no launch
    snapshot. They can only represent the historical empty-input/empty-metadata
    launch shape, so recovery preserves that compatibility. New non-empty
    launches are rejected before execution unless admission already recorded
    this snapshot.
    """
    raw = run.provenance.get(DURABLE_GRAPH_LAUNCH_PROVENANCE)
    if raw is None:
        return {}, {}
    if not isinstance(raw, Mapping):
        raise RunIntegrityError("durable_graph_launch provenance must be an object")

    inputs = raw.get(_INITIAL_INPUTS, {})
    metadata = raw.get(_BLACKBOARD_METADATA, {})
    if not isinstance(inputs, Mapping) or not isinstance(metadata, Mapping):
        raise RunIntegrityError(
            "durable_graph_launch initial_inputs and blackboard_metadata must be objects"
        )
    return copy.deepcopy(dict(inputs)), copy.deepcopy(dict(metadata))


def require_admitted_launch_state(
    run: Run,
    *,
    inputs: Mapping[str, Any] | None = None,
    blackboard_metadata: Mapping[str, Any] | None = None,
) -> None:
    """Refuse an admitted launch whose recoverable snapshot differs from execution.

    This check happens before checkpoint 1 and before physical work. If a caller
    wants non-empty launch state, it must include
    :func:`durable_graph_launch_provenance` in ``RunStore.create_run``. A crash
    immediately after admission can then recover exactly the same launch.
    """
    persisted_inputs, persisted_metadata = launch_state_from_run(run)
    requested_inputs = copy.deepcopy(dict(inputs or {}))
    requested_metadata = copy.deepcopy(dict(blackboard_metadata or {}))
    if persisted_inputs != requested_inputs or persisted_metadata != requested_metadata:
        raise RunIntegrityError(
            "admitted Run durable_graph_launch snapshot does not match requested launch state"
        )


__all__ = [
    "DURABLE_GRAPH_LAUNCH_PROVENANCE",
    "durable_graph_launch_provenance",
    "launch_state_from_run",
    "require_admitted_launch_state",
]
