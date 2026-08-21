"""Tests for the User → Domain → Projects hierarchy.

Each user can own one or many projects per domain (use_case). The store
filters list_for_user(user_id, use_case=…) so the frontend at /{domain}/
only sees the projects in that domain.

The curated KNOWN_DOMAINS shipped today: pm_fleet, canvas_creative,
engineering_rfc, support_triage, marketing_campaign, product_discovery.
Custom user-minted use_case strings also work — they fall back to the
generic UI shell.
"""

from __future__ import annotations

from maistro.projects import (
    KNOWN_DOMAINS,
    InMemoryProjectStore,
    domain_for,
    domain_use_cases,
)

# --- Curated domain catalog ----------------------------------------------


def test_known_domains_include_pm_canvas_engineering() -> None:
    """The substrate ships token seats for the use cases we explicitly
    promised to support; PM is the heavy POC, the rest are skeletal."""
    use_cases = domain_use_cases()
    for required in ("pm_fleet", "canvas_creative", "engineering_rfc"):
        assert required in use_cases, f"missing curated use_case: {required}"


def test_each_domain_has_a_distinct_mount_path() -> None:
    """The frontend mounts each domain at its own URL prefix
    (/pm/, /art/, /eng/, /support/, /marketing/, /product/)."""
    paths = [d.get("mount_path") for d in KNOWN_DOMAINS]
    assert len(paths) == len(set(paths)), f"duplicate mount_path: {paths}"
    # Concrete checks for the three the user named.
    by_use = {d["use_case"]: d for d in KNOWN_DOMAINS if "use_case" in d}
    assert by_use["pm_fleet"]["mount_path"] == "/pm/"
    assert by_use["canvas_creative"]["mount_path"] == "/art/"
    assert by_use["engineering_rfc"]["mount_path"] == "/eng/"


def test_domain_for_returns_config_or_none_for_custom() -> None:
    """Standard use_case → config; custom user-minted → None (generic fallback)."""
    assert domain_for("pm_fleet") is not None
    assert domain_for("pm_fleet")["display_name"] == "PM Fleet"
    assert domain_for("brand_compliance") is None  # user-minted; fine


# --- User → Domain → many Projects filtering -----------------------------


async def test_user_with_projects_in_three_domains_filters_correctly() -> None:
    """One user, three domains, multiple projects each. The store's
    list_for_user(user_id, use_case=…) filter drives the frontend's
    /pm/ vs /art/ vs /eng/ project pickers."""
    store = InMemoryProjectStore()

    # PM: 2 projects.
    pm1 = await store.create(owner_user_id="alice", name="Payments Q3")
    pm1 = await store.update(pm1.model_copy(update={"use_case": "pm_fleet"}))
    pm2 = await store.create(owner_user_id="alice", name="Streaming infra")
    pm2 = await store.update(pm2.model_copy(update={"use_case": "pm_fleet"}))

    # Art: 1 project.
    art1 = await store.create(owner_user_id="alice", name="HHN 2026 hero art")
    art1 = await store.update(art1.model_copy(update={"use_case": "canvas_creative"}))

    # Eng: 1 project.
    eng1 = await store.create(owner_user_id="alice", name="MAISTRO v0.3 RFCs")
    eng1 = await store.update(eng1.model_copy(update={"use_case": "engineering_rfc"}))

    # Without filter: all 4 visible.
    all_alice = await store.list_for_user("alice")
    assert len(all_alice) == 4
    assert {p.id for p in all_alice} == {pm1.id, pm2.id, art1.id, eng1.id}

    # /pm/ filter: only the two PM projects.
    pm_only = await store.list_for_user("alice", use_case="pm_fleet")
    assert {p.id for p in pm_only} == {pm1.id, pm2.id}
    for p in pm_only:
        assert p.use_case == "pm_fleet"

    # /art/ filter.
    art_only = await store.list_for_user("alice", use_case="canvas_creative")
    assert {p.id for p in art_only} == {art1.id}

    # /eng/ filter.
    eng_only = await store.list_for_user("alice", use_case="engineering_rfc")
    assert {p.id for p in eng_only} == {eng1.id}


async def test_custom_use_case_is_allowed_and_filterable() -> None:
    """User can mint a domain we don't ship a curated config for; the
    record persists and list_for_user filters by it. The frontend falls
    back to the generic UI shell for these."""
    store = InMemoryProjectStore()
    custom = await store.create(owner_user_id="alice", name="Brand compliance Q4")
    custom = await store.update(custom.model_copy(update={"use_case": "brand_compliance"}))

    found = await store.list_for_user("alice", use_case="brand_compliance")
    assert [p.id for p in found] == [custom.id]
    # Curated config lookup returns None — the UI knows to fall back.
    from maistro.projects import domain_for

    assert domain_for("brand_compliance") is None


async def test_other_users_projects_not_returned_even_in_same_domain() -> None:
    """Domain isolation is per-user. Alice's PM project is invisible to Bob
    even though Bob has his own PM project too."""
    store = InMemoryProjectStore()
    alice_pm = await store.create(owner_user_id="alice", name="Alice's PM")
    alice_pm = await store.update(alice_pm.model_copy(update={"use_case": "pm_fleet"}))
    bob_pm = await store.create(owner_user_id="bob", name="Bob's PM")
    bob_pm = await store.update(bob_pm.model_copy(update={"use_case": "pm_fleet"}))

    alice_visible = await store.list_for_user("alice", use_case="pm_fleet")
    bob_visible = await store.list_for_user("bob", use_case="pm_fleet")
    assert [p.id for p in alice_visible] == [alice_pm.id]
    assert [p.id for p in bob_visible] == [bob_pm.id]
