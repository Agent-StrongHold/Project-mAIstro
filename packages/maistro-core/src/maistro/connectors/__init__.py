"""Connector/source SDK — third-party ingestion with canonical provenance.

Public surface for M9-E2 (issue #963). An out-of-tree connector imports
everything it needs from here, implements :class:`ConnectorSource`, declares
itself via :class:`ConnectorDescriptor`, and is driven only by the host's
:class:`SyncEngine` — which stamps provenance onto every item, keeps
restart-safe checkpoints per Workspace/config, treats deletion as explicit
tombstones, and normalizes upstream failures into the canonical error types.

Conformance is shared: :func:`run_connector_conformance` is the same suite
for built-in and external connectors, and ``maistro connectors verify`` runs
it from the operator CLI.
"""

from maistro.connectors.base import ConnectorSource
from maistro.connectors.conformance import run_connector_conformance
from maistro.connectors.scope import ConnectorInstance, ConnectorSession, SyncContext
from maistro.connectors.secrets import (
    SecretAuthority,
    StaticSecretAuthority,
)
from maistro.connectors.sync import (
    CheckpointStore,
    IngestStore,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SyncEngine,
    content_hash,
)
from maistro.connectors.types import (
    ConnectorCapability,
    ConnectorCapabilityError,
    ConnectorDescriptor,
    ConnectorError,
    ConnectorRateLimitedError,
    ConnectorScopeError,
    ConnectorUnavailableError,
    SecretRef,
    SourceItem,
    SourceRecord,
    SyncAction,
    SyncCursor,
    SyncOutcome,
    SyncPage,
    SyncReport,
)

__all__ = [
    "CheckpointStore",
    "ConnectorCapability",
    "ConnectorCapabilityError",
    "ConnectorDescriptor",
    "ConnectorError",
    "ConnectorInstance",
    "ConnectorRateLimitedError",
    "ConnectorScopeError",
    "ConnectorSession",
    "ConnectorSource",
    "ConnectorUnavailableError",
    "IngestStore",
    "MemoryCheckpointStore",
    "MemoryIngestStore",
    "SecretAuthority",
    "SecretRef",
    "SourceItem",
    "SourceRecord",
    "StaticSecretAuthority",
    "SyncAction",
    "SyncContext",
    "SyncCursor",
    "SyncEngine",
    "SyncOutcome",
    "SyncPage",
    "SyncReport",
    "content_hash",
    "run_connector_conformance",
]
