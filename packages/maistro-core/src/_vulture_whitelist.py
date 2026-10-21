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
)
