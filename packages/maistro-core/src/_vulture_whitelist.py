"""Explicit Vulture references for framework/public surfaces in maistro-core.

This module is quality-scanner input only. ``maistro-core`` packages only
``src/maistro``, so this file is not shipped in the wheel. Vulture scans the
whole ``src`` directory and therefore sees these references to symbols whose
usage is implicit through Pydantic or intentionally external through the public
Invocation execution API.
"""

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

_VULTURE_WHITELIST = (
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
    # --- #102 backlog work-source (maistro.backlog) -----------------------
    # Pydantic invokes these field/model validators at runtime; static import
    # scanning cannot see decorator-based dispatch (same shape as
    # Binding._validate_binding above).
    BacklogClosure._require_non_blank_summary,
    BacklogClosure._require_resolvable_refs,
    BacklogClosure._normalize_closed_at,
    BacklogOrigin._require_non_blank,
    BacklogItem._require_non_blank,
    BacklogItem._status_is_a_defined_value,
    BacklogItem._clean_tags,
    BacklogItem._clean_dependencies,
    BacklogItem._require_positive_revision,
    BacklogItem._enforce_consistency,
    BacklogClaim._require_non_blank_identity,
    BacklogClaim._normalize_timestamps,
    BacklogEvent._require_non_blank_identity,
    BacklogEvent._normalize_at,
    # Declarative model field on BacklogItem: written by every store
    # (created_by=actor), validated at the boundary and serialized into the
    # item/event tables; vulture cannot count model_dump/INSERT serialization
    # as a read (same shape as ResolvedBinding.provider_trust_tier above).
    BacklogItem.created_by,
    # BacklogStore.extend_claim is the port's lease-extension operation,
    # conformance-pinned across all three backends
    # (packages/maistro-core/tests/backlog/test_backlog_store_conformance.py
    # :: expired-lease reclaim and claim exclusivity). Its production
    # consumers are the downstream agent/RSI loops the surface exists for;
    # within this repository no process entry point extends a lease yet.
    BacklogStore.extend_claim,
    InMemoryBacklogStore.extend_claim,
    SqliteBacklogStore.extend_claim,
    PgBacklogStore.extend_claim,
    # ParsedItem.written_block is the parse-record accessor the migration
    # round-trip suite asserts verbatim reconstruction with
    # (test_markdown_migration.py); it is the import-side twin of the
    # exporter's _render_header and is consumed outside the scanned tree by
    # the migration test suite and downstream import tooling.
    ParsedItem.written_block,
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
