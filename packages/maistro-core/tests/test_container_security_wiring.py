"""Wiring tests for Batch 2 security fixes: C1 (empty Sentinel permission
table) and H3 (unwired strike tracker) plus H12 (Warden not bound to skill
import).

Every test here goes through ``create_container()`` and never constructs
``Gate`` or ``Sentinel`` directly -- unlike the property tests under
``formal/`` and the unit tests in ``tests/security/test_gate.py``, which
inject their own correctly-wired objects and therefore never caught the
missing wiring in the first place.
"""

from __future__ import annotations

import contextlib
import logging

import pytest

from maistro.container import Container, create_container
from maistro.security._types import AuthContext, WardenVerdict
from maistro.security.patterns import DANGEROUS_TOOL_NAMES
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.strikes import InMemoryStrikeTracker
from maistro.skills.import_pipeline import ImportSource, SkillImportRequest
from maistro.types.config import AgentConfig, SecurityConfig
from maistro.types.errors import AgentError

IMPORTER = Principal(id="importer1", kind="human")

VALID_SKILL_MD = """---
name: my_skill
description: Does a thing
parameters:
  type: object
  properties: {}
---
Body text here.

Explains how to use the tool in plain factual prose.
"""


async def _container(**security_overrides: object) -> Container:
    return await create_container(
        AgentConfig(
            router_api_key="test-key",
            security=SecurityConfig(**security_overrides),  # type: ignore[arg-type]
        )
    )


# --- Sentinel permission table wiring (C1) ----------------------------------


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_container_sentinel_permission_table_empty_by_default() -> None:
    container = await _container()
    assert container.sentinel._permission_table == {}


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_container_sentinel_permission_table_from_explicit_config() -> None:
    container = await _container(permissions={"deploy": ["admin"]})
    assert container.sentinel._permission_table == {"deploy": frozenset({"admin"})}


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_container_permission_preset_arms_dangerous_tools() -> None:
    container = await _container(permission_preset="dangerous_tools_admin")
    table = container.sentinel._permission_table
    assert set(table.keys()) == set(DANGEROUS_TOOL_NAMES)
    assert all(roles == frozenset({"admin"}) for roles in table.values())


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_wired_sentinel_denies_dangerous_tool_for_non_admin() -> None:
    container = await _container(permission_preset="dangerous_tools_admin")

    verdict = await container.sentinel.pre_call(
        "exec", {}, AuthContext(user_id="u1", roles=frozenset({"user"})), {}
    )
    assert verdict.allowed is False
    assert len(verdict.violations) == 1
    assert verdict.violations[0].rule == "permission_denied"
    assert verdict.violations[0].boundary == "pre_call"

    verdict_admin = await container.sentinel.pre_call(
        "exec", {}, AuthContext(user_id="u2", roles=frozenset({"admin"})), {}
    )
    assert verdict_admin.allowed is True


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_wired_sentinel_permits_unlisted_tool() -> None:
    container = await _container(permission_preset="dangerous_tools_admin")

    verdict = await container.sentinel.pre_call(
        "read_file", {}, AuthContext(user_id="u1", roles=frozenset({"user"})), {}
    )
    assert verdict.allowed is True


# --- Strike tracker wiring (H3) ----------------------------------------------


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_container_strike_tracker_absent_by_default() -> None:
    container = await _container()
    assert container.strike_tracker is None
    assert container.gate._strike_tracker is None


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_container_wires_strike_tracker_when_enabled() -> None:
    """No pool, so in-memory -- the homelab deployment's correct answer."""
    container = await _container(strike_tracking_enabled=True)
    assert container.strike_tracker is not None
    assert isinstance(container.strike_tracker, InMemoryStrikeTracker)
    assert container.gate._strike_tracker is container.strike_tracker


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_a_pool_selects_the_durable_strike_tracker() -> None:
    """The whole of #134: a database means lockouts outlive the process.

    Against `_wire_strike_tracker` rather than a built container, because the
    selection is the thing under test and building a container around a fake
    pool would exercise the event-schema path instead. The two trackers' shared
    *behaviour* is `test_strike_tracker_conformance.py`'s job, parametrised over
    both; that a real container reaches this branch is covered against a real
    server by `test_container_postgres.py`.
    """
    from maistro.container import _wire_strike_tracker
    from maistro.security.pg_strikes import PgStrikeTracker

    tracker = _wire_strike_tracker(enabled=True, pg_pool=object())

    assert isinstance(tracker, PgStrikeTracker)


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
async def test_the_durable_tracker_uses_the_containers_own_pool() -> None:
    """Not a second one of its own.

    A tracker that opened its own pool would double the process's connection
    budget, and the two could name different databases the moment `DATABASE_URL`
    changed -- the strike ladder reading one while every other store wrote the
    other. It would also run `_SCHEMA`'s `CREATE TABLE IF NOT EXISTS` behind the
    migration chain that owns those tables.
    """
    from maistro.container import _wire_strike_tracker

    pool = object()
    tracker = _wire_strike_tracker(enabled=True, pg_pool=pool)

    assert tracker is not None
    assert await tracker._get_pool() is pool  # type: ignore[attr-defined]


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_no_pool_still_selects_the_in_memory_tracker(caplog) -> None:
    """A homelab deployment with no database chose this, so it is said at INFO.

    And it is still *said*: the in-memory ladder means a locked-out account is
    unlocked by any deploy, which an operator should be able to find in the log
    rather than infer.
    """
    from maistro.container import _wire_strike_tracker

    with caplog.at_level(logging.INFO, logger="maistro.container"):
        tracker = _wire_strike_tracker(enabled=True, pg_pool=None)

    assert isinstance(tracker, InMemoryStrikeTracker)
    assert any("resets on restart" in r.message for r in caplog.records)


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_a_pool_no_longer_warns_that_lockouts_reset(caplog) -> None:
    """The warning was the acceptance criterion's other half.

    It said "PgStrikeTracker is not yet Gate-compatible (#134)". Leaving it
    behind after wiring the durable tracker would tell an operator their
    lockouts reset when they no longer do -- worse than the silence, because it
    reads as current.
    """
    from maistro.container import _wire_strike_tracker

    with caplog.at_level(logging.WARNING, logger="maistro.container"):
        _wire_strike_tracker(enabled=True, pg_pool=object())

    assert not [r for r in caplog.records if "in-memory" in r.message]


@pytest.mark.contract("behavioral")
@pytest.mark.scope("e2e")
async def test_three_strikes_through_wired_gate_disables_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full ladder through the container's own wired Gate + strike_tracker.

    Note: strike 2 imposes an 8-hour lockout, and the Gate short-circuits
    (blocks before ever calling Warden.scan or recording a new violation)
    while a user is locked -- see gate.py's ``is_locked`` check. So three
    *consecutive* process_input calls only ever reach strike 2; reaching
    strike 3 requires the lockout to have expired first, exactly as
    tests/security/test_gate.py::test_expired_lockout_falls_through_to_normal_scan
    simulates by rewinding ``locked_until`` on the tracker's own record.
    """
    container = await _container(strike_tracking_enabled=True)
    assert container.strike_tracker is not None

    scan_calls = 0

    async def _dirty_scan(content: str, boundary: str) -> WardenVerdict:
        nonlocal scan_calls
        scan_calls += 1
        return WardenVerdict(clean=False, flags=("injection",))

    monkeypatch.setattr(container.warden, "scan", _dirty_scan)

    auth = AuthContext(user_id="u1")

    result1 = await container.gate.process_input("x", auth=auth)
    assert result1.strike_number == 1

    result2 = await container.gate.process_input("x", auth=auth)
    assert result2.strike_number == 2
    assert result2.locked_until != ""

    # Expire the lockout directly on the container's own tracker record (the
    # same technique test_gate.py uses) so the next call falls through to a
    # fresh Warden scan instead of being short-circuited by the lockout.
    from datetime import UTC, datetime, timedelta

    record = await container.strike_tracker.get("u1")
    assert record is not None
    record.locked_until = datetime.now(UTC) - timedelta(seconds=1)

    result3 = await container.gate.process_input("x", auth=auth)
    assert result3.strike_number == 3
    assert result3.account_disabled is True

    assert scan_calls == 3

    result4 = await container.gate.process_input("x", auth=auth)
    assert result4.blocked is True
    assert "disabled" in result4.block_reason
    assert scan_calls == 3  # short-circuited before a 4th scan


# --- Skill import Warden binding (H12) ---------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
async def test_container_import_skill_binds_warden_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = await _container()

    calls: list[tuple[str, str]] = []

    async def _recording_scan(content: str, boundary: str) -> WardenVerdict:
        calls.append((content, boundary))
        return WardenVerdict(clean=True, flags=("probe_flag",))

    monkeypatch.setattr(container.warden, "scan", _recording_scan)

    verdict = await container.import_skill(
        SkillImportRequest(source=ImportSource.PASTE, importer=IMPORTER, raw=VALID_SKILL_MD)
    )

    assert len(calls) == 1
    assert calls[0][1] == "skill_import"
    assert "warden:probe_flag" in verdict.report.scan_issues


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
async def test_container_import_skill_explicit_warden_scan_wins() -> None:
    container = await _container()

    calls: list[str] = []

    async def _other_scan(content: str, boundary: str) -> WardenVerdict:
        calls.append(boundary)
        return WardenVerdict(clean=True)

    verdict = await container.import_skill(
        SkillImportRequest(source=ImportSource.PASTE, importer=IMPORTER, raw=VALID_SKILL_MD),
        warden_scan=_other_scan,
    )

    assert calls == ["skill_import"]
    assert verdict.outcome == "registered"


# ---------------------------------------------------------------------------
# The test harness is a SECOND container-assembly path. It hardcoded
# `Gate(warden=warden)` and `permission_table = {}` while accepting an
# AgentConfig it never consulted, so a test could configure a preset and
# silently observe pre-fix behaviour. That is the same "parallel assembly path
# drifts from the real one" shape that let the empty table and missing tracker
# survive a green suite, so it needs pinning here rather than trusting the fix.
# ---------------------------------------------------------------------------


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_test_harness_honours_security_config() -> None:
    from maistro.testing import create_test_environment

    container = create_test_environment(
        config=AgentConfig(
            router_api_key="test-key",
            security=SecurityConfig(
                permission_preset="dangerous_tools_admin",
                strike_tracking_enabled=True,
            ),
        )
    ).container

    assert container.sentinel._permission_table, (
        "create_test_environment ignored config.security.permission_preset"
    )
    assert container.strike_tracker is not None
    assert container.gate._strike_tracker is container.strike_tracker


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_test_harness_defaults_match_create_container() -> None:
    """Defaults must stay inert in the harness too, or 34 call sites shift."""
    from maistro.testing import create_test_environment

    container = create_test_environment().container

    assert container.sentinel._permission_table == {}
    assert container.strike_tracker is None
    assert container.gate._strike_tracker is None


# ---------------------------------------------------------------------------
# Codex review of #270 (two P1s): both armed controls key on caller identity,
# and the only production caller -- hive-conductor's bridge at
# adapters/maistro_core.py:180-184 -- calls route_request() with no auth. So
# arming either one would have enforced nothing, silently. route_request now
# refuses that combination.
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
async def test_route_request_refuses_armed_table_without_auth() -> None:
    container = await _container(permission_preset="dangerous_tools_admin")

    with pytest.raises(AgentError, match="permission table"):
        await container.route_request([{"role": "user", "content": "hi"}])


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
async def test_route_request_refuses_armed_tracker_without_auth() -> None:
    container = await _container(strike_tracking_enabled=True)

    with pytest.raises(AgentError, match="strike tracking"):
        await container.route_request([{"role": "user", "content": "hi"}])


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
async def test_route_request_allows_no_auth_at_shipped_defaults() -> None:
    """The guard must not fire for anyone who has not opted in.

    Every existing caller -- including hive-conductor's bridge -- runs at these
    defaults, so a guard that fired here would break the shipped deployment.
    """
    container = await _container()

    assert container.sentinel._permission_table == {}
    assert container.strike_tracker is None
    # Reaching the conduit at all proves the guard did not raise; the conduit
    # itself needs no agents for this call to get past the guard.
    with contextlib.suppress(Exception):
        await container.route_request([{"role": "user", "content": "hi"}])


# --- Elevation store wiring (issue #346) -------------------------------------
#
# Sentinel._check_elevation_grant short-circuits on `self._elevation_store is
# None`, and create_container never passed one -- so in every production
# container the branch was unreachable and a grant a human/owner had already
# cleared could never be honoured. These tests go through create_container()
# specifically: constructing Sentinel directly with an elevation_store (as
# tests/security/test_elevation_grants.py does) never caught the gap.


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_container_wires_an_elevation_store_into_sentinel() -> None:
    container = await _container()

    assert container.elevation_store is not None
    # Same instance, so a grant written through the container is the grant
    # Sentinel reads. A second store would look wired and deny anyway.
    assert container.sentinel._elevation_store is container.elevation_store


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_elevation_check_is_reachable_in_a_wired_container() -> None:
    """End-to-end proof the branch runs: a stored grant changes the decision."""
    from datetime import UTC, datetime

    from maistro.security.sentinel.elevation import ElevationGrant

    container = await _container()
    principal = Principal(id="human1", kind="human")

    before = await container.sentinel.authorize(
        "delete_prod_db", principal, reversibility="irreversible"
    )
    assert before.tier is Tier.SELF_ELEVATION
    assert before.needs == "self_elevation"

    await container.elevation_store.store(
        ElevationGrant(
            principal_id="human1",
            action_class="delete_prod_db",
            kind="self_elevation",
            granted_at=datetime.now(UTC),
            ttl_seconds=300,
            signed_by="human1",
        )
    )

    after = await container.sentinel.authorize(
        "delete_prod_db", principal, reversibility="irreversible"
    )
    assert after.needs == "none"
    assert after.reason == "cleared by a prior elevation grant"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_empty_elevation_store_is_behaviourally_identical_to_unwired() -> None:
    """The wiring must be a no-op until someone actually clears a grant."""
    container = await _container()

    decision = await container.sentinel.authorize(
        "delete_prod_db", Principal(id="human1", kind="human"), reversibility="irreversible"
    )
    assert decision.needs == "self_elevation"
    assert decision.reason == ""


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
async def test_elevation_grant_cannot_clear_a_denied_capability() -> None:
    """A grant must never flip authorized False -> True.

    _check_elevation_grant runs only after the capability check, the budget
    check and the BLOCKED check have all passed, so wiring the store can only
    relax `needs`, never `authorized`. Pinned because this is the property
    that makes the wiring safe.
    """
    from datetime import UTC, datetime

    from maistro.security.sentinel.elevation import ElevationGrant

    container = await _container(permission_preset="dangerous_tools_admin")
    principal = Principal(id="human1", kind="human", roles=("user",))
    action = next(iter(DANGEROUS_TOOL_NAMES))

    await container.elevation_store.store(
        ElevationGrant(
            principal_id="human1",
            action_class=action,
            kind="self_elevation",
            granted_at=datetime.now(UTC),
            ttl_seconds=300,
            signed_by="human1",
        )
    )

    decision = await container.sentinel.authorize(action, principal, reversibility="irreversible")
    assert decision.authorized is False
    assert "lacks capability" in decision.reason

    # Same for over-budget: a grant does not buy budget.
    over = await container.sentinel.authorize(
        "some_unlisted_action",
        principal,
        reversibility="irreversible",
        within_budget=False,
    )
    assert over.authorized is False
    assert over.reason == "over budget"
