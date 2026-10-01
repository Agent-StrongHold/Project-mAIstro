"""Explicit Vulture references for framework/public surfaces in maistro-core.

This module is quality-scanner input only. ``maistro-core`` packages only
``src/maistro``, so this file is not shipped in the wheel. Vulture scans the
whole ``src`` directory and therefore sees these references to symbols whose
usage is implicit through Pydantic or intentionally external through the public
Invocation execution API.
"""

import maistro.identity
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationExecutionService
from maistro.container import Container
from maistro.identity import Principal
from maistro.identity._crypto import ConductorSeed, DerivedKey
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
    # ADR-068 cutover bridges (Workspace P0.1) between hive
    # ``request.state.user`` dicts and the canonical Principal. Their callers
    # are the downstream products still on the dict shape during the
    # migration, plus the bridge-behavior lock in
    # tests/identity/test_principal_bridge.py and the extra-guard suite, none
    # of which this packages/*/src scan walks.
    Principal.from_legacy_dict,
    Principal.to_legacy_dict,
    # ADR-021 BIP39/BIP32 root-of-trust API on ConductorSeed. The methods are
    # the published seed surface for downstream products: from_mnemonic /
    # derive_named / mnemonic_words are pinned by
    # tests/identity/test_seed.py and tests/identity/test_lifecycle.py,
    # did_key is the seed-level counterpart of lifecycle's
    # did_key_from_public_key, and zero() is the memory-hygiene call made in
    # production by packages/hive-conductor/backend/services/
    # identity_health.py, which this packages/*/src scan does not walk.
    ConductorSeed.did_key,
    ConductorSeed.derive_named,
    ConductorSeed.from_mnemonic,
    ConductorSeed.mnemonic_words,
    ConductorSeed.zero,
    # Declarative curve field of the ADR-021 DerivedKey record, asserted by
    # tests/identity/test_seed.py; dataclass fields are constructed by
    # convention, not read at every call site.
    DerivedKey.curve,
    # PEP 562 lazy-loading hook: attribute access on maistro.identity (e.g.
    # ``from maistro.identity import ConductorSeed``) invokes __getattr__
    # implicitly to keep Principal importable without the crypto extra.
    maistro.identity.__getattr__,
)
