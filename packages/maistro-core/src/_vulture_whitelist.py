"""Explicit Vulture references for framework/public surfaces in maistro-core.

This module is quality-scanner input only. ``maistro-core`` packages only
``src/maistro``, so this file is not shipped in the wheel. Vulture scans the
whole ``src`` directory and therefore sees these references to symbols whose
usage is implicit through Pydantic or intentionally external through the public
Invocation execution API.
"""

from maistro import identity as identity_package
from maistro.a2a.external import ExternalAgentRegistry
from maistro.backlog.markdown_io import ParsedItem
from maistro.backlog.model import (
    BacklogClaim,
    BacklogClosure,
    BacklogEvent,
    BacklogItem,
    BacklogOrigin,
)
from maistro.backlog.pg_store import PgBacklogStore
from maistro.backlog.sqlite_store import SqliteBacklogStore
from maistro.backlog.store import BacklogStore, InMemoryBacklogStore
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationExecutionService
from maistro.container import Container
from maistro.runs.scoped_reads import ScopedRunReader
from maistro.state import PersistedStore
from maistro.workspaces.campaigns.model import (
    Actor,
    AreaRef,
    BacklogItemView,
    CampaignDefinition,
    ControlRecord,
    ItemPolicyRecord,
    ParkEvidence,
    ParkRecord,
    ParkUnpark,
)
from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore
from maistro.workspaces.campaigns.store import CampaignSelector

# OpenTelemetry API keywords mirrored by the Protocol signature in
# maistro.observability.telemetry_safety.TelemetryTracer. The keywords are
# the API contract callers pass (``record_exception=False`` disables vendor
# exception export), so the parameters are referenced here rather than
# renamed or dropped.
record_exception = "record_exception"
set_status_on_exception = "set_status_on_exception"

_VULTURE_REFERENCES = (record_exception, set_status_on_exception)

# EvalSummary's projection field (#792). A frozen-dataclass instance attribute:
# a class-object reference would not typecheck, so the whitelist below names it
# through this module variable instead. The name is distinctive enough to be
# safe at name level.
latest_by_dimension = "latest_by_dimension"

# Root-admission envelope snapshot fields (#1851, parent #1845). Frozen-dataclass
# instance attributes like latest_by_dimension above: a class-object reference
# would not typecheck, so they are named through these module variables instead.
# The names are distinctive enough to be safe at name level.
receipt_snapshot = "receipt_snapshot"
provenance_snapshot = "provenance_snapshot"
format_version = "format_version"

_VULTURE_WHITELIST = (
    # P0.1 identity split (#53): Principal is always importable; crypto and lifecycle
    # symbols load through __getattr__ and ConductorSeed's public API.
    identity_getattr,
    Principal.from_legacy_dict,
    Principal.to_legacy_dict,
    ConductorSeed.from_mnemonic,
    ConductorSeed.derive_named,
    ConductorSeed.did_key,
    ConductorSeed.mnemonic_words,
    ConductorSeed.zero,
    DerivedKey.curve,
    Binding._validate_binding,
    ResolvedBinding._validate_resolved,
    ResolvedBinding.provider_trust_tier,
    ResolvedBinding.resolved_at,
    Invocation._validate_invocation,
    InvocationExecutionService.invoke,
    # PersistedStore's atomic username-claim transactions (#1061). The durable
    # backend is reached from packages/hive-conductor's username_registry via
    # getattr(backend, ...) duck-typing, so no scanned call site names these
    # methods; they are the production allocation/rollback boundary, not dead
    # code.
    PersistedStore.delete_raw_with_unique_claims,
    PersistedStore.put_raw_with_unique_claims,
    # The scoped canonical Run read seam (#1152) is consumed by Hive's
    # backend (services/engine.py, services/dag_run_inspection.py), which
    # this `packages/*/src` scan does not walk.
    Container.run_reader,
    ScopedRunReader.get_runs,
    # Workspace work campaigns (#103, SPEC-092626-1831). Pydantic invokes the
    # validators; the Actor-valued fields are serialization surface written
    # through model_dump_json and read by consumers outside this scan (the
    # HTTP API responses and the importing product's UI).
    Actor._require_identity,
    AreaRef._require_value,
    BacklogItemView._require_identity,
    CampaignDefinition._require_campaign_text,
    ControlRecord._scope_matches_kind,
    ParkEvidence._require_reason,
    CampaignDefinition.created_by,
    ControlRecord.set_by,
    ControlRecord.cleared_by,
    ItemPolicyRecord.updated_by,
    ParkRecord.parked_by,
    ParkUnpark.unparked_by,
    # The retention deletion path is resolved dynamically by
    # scripts/check-durable-table-inventory.py from
    # quality/durable-table-retention.json; no scanned call site names it.
    SqliteCampaignStore.delete_campaign,
    # The selection entrypoint is the contract's public face (#804 persistent
    # Workspace Agent now, #50 RSI later). Consumers live outside this scan
    # until those issues land; the contract ships first by design.
    CampaignSelector.eligible_items,
    CampaignSelector.select_next,
)
