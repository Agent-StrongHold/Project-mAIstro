"""Container-level timezone verification for the shipped scheduler (#290).

This file runs inside the api-tests container (tests/Dockerfile) against the
LIVE shipped hive image — the point is to verify what the image actually
ships, not what the developer environment resolves:

  - a `UTC` schedule and a real IANA zone (`Europe/Berlin`) are accepted,
    persisted, and their `next_run` is computed against the image's zone
    database (the api-tests container computes the expected instant from its
    own deliberately pinned `tzdata` wheel — see tests/Dockerfile);
  - the Berlin `next_run` keeps its wall time (04:30) and the season-correct
    offset (CET +1 / CEST +2), which is exactly the DST property that breaks
    when a zone resolves through UTC by accident — whether the next
    occurrence crosses a transition is calendar luck, and the deterministic
    transition-crossing behaviour is pinned by maistro-core's
    `test_cron.py` spring-forward and fall-back tests;
  - an invalid zone is refused 422 at the boundary;
  - /health reports `tz_database` and `scheduler` independently of process
    liveness, with an actionable diagnostic when the zone database is broken;
  - after a container restart (CI: hive is stopped and started again before
    the restart-marked selection runs), schedules and their cursors survive
    and the UTC schedule recomputes `next_run` from the persisted zone.

The schedules target `daily-status`, the graph template the shipped image
registers in its own process at boot: the scheduler's fallback admission
path refuses to fire a template that is not registered, so an arbitrary
DAG id would leave the cursor — and with it `next_run` — untouched forever.
The Berlin schedule is fired manually (its natural 04:30 fire is up to a
day away) through the same admission path the tick uses.

The restart-marked test is skipped unless `SCHED_TZ_AFTER_RESTART=1` is set
in its environment — the pre-restart phase must not fail for not having
restarted yet.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

BASE = os.environ.get("HIVE_BASE_URL", "http://localhost:8101")
_POLL_BUDGET = timedelta(seconds=90)  # the tick loop sleeps 30s between sweeps
# The template the shipped image registers at boot; see module docstring.
MISSION_TEMPLATE = "daily-status"
UTC_NAME = "tz-verify UTC"
BERLIN_NAME = "tz-verify Berlin"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def setup_done(client: httpx.Client):
    """Run the setup wizard if not already done (same harness as the PM suite)."""
    r = client.get("/v1/setup/status")
    assert r.status_code == 200
    if r.json().get("setup_complete"):
        return True
    r = client.post(
        "/v1/setup/complete",
        json={
            "hardware_preset": "beast",
            "conductor_name": "PM Test Hive",
            "admin_username": "admin",
            "admin_password": "adminpass123",
            "user_username": "pmuser",
            "user_password": "pmpass1234",
            "optional_modules": [],
        },
    )
    assert r.status_code == 200, f"Setup failed: {r.text}"
    return True


@pytest.fixture(scope="module")
def admin_session(client: httpx.Client, setup_done):
    """The setup wizard's admin — passes protected-op permission checks."""
    r = client.post("/v1/auth/login", json={"username": "admin", "password": "adminpass123"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    cookie = r.cookies.get("hive_session")
    assert cookie, "No session cookie returned"
    client.cookies.set("hive_session", cookie)
    return cookie


@pytest.fixture(scope="module")
def workspace(client: httpx.Client, admin_session) -> str:
    """A workspace the admin owns, so schedule writes are authorized.

    `POST /v1/schedules` admits the body's `workspace_id` through the
    canonical Workspace authority and then requires the actor to be a
    writer member (#1201) — a schedule create without a membership-backed
    selection is a 403, which is the shipped boundary behaving correctly.
    """
    r = client.get("/v1/workspaces/persona-templates")
    assert r.status_code == 200, f"List persona templates failed: {r.text}"
    templates = r.json()
    assert templates, "no persona templates available to create a workspace"
    r = client.post(
        "/v1/workspaces",
        json={"persona_template_id": templates[0]["id"], "name": "Schedule TZ Workspace"},
    )
    assert r.status_code == 201, f"Workspace create failed: {r.status_code} {r.text}"
    return str(r.json()["id"])


def _create_schedule(client: httpx.Client, name: str, cron: str, timezone: str, workspace_id: str):
    return client.post(
        "/v1/schedules",
        json={
            "name": name,
            "cron_expression": cron,
            "mission_template_id": MISSION_TEMPLATE,
            "timezone": timezone,
            "workspace_id": workspace_id,
        },
    )


def _next_run(client: httpx.Client, schedule_id: str) -> dict:
    """Poll until the schedule's `next_run` exists; the tick loop sweeps at 30s."""
    deadline = datetime.now(UTC) + _POLL_BUDGET
    while datetime.now(UTC) < deadline:
        r = client.get(f"/v1/schedules/{schedule_id}")
        assert r.status_code == 200, f"GET schedule failed: {r.text}"
        body = r.json()
        if body.get("next_run"):
            return body
        time.sleep(5)
    pytest.fail(f"schedule {schedule_id} computed no next_run within {_POLL_BUDGET}")


def test_utc_schedule_persists_and_computes_next_run(
    client: httpx.Client, admin_session, workspace
) -> None:
    r = _create_schedule(client, UTC_NAME, "* * * * *", "UTC", workspace)
    assert r.status_code == 201, f"UTC schedule create failed: {r.text}"
    body = r.json()
    sid = body["id"]
    assert body["timezone"] == "UTC"
    assert body["enabled"] is True

    projected = _next_run(client, sid)
    assert projected["timezone"] == "UTC"
    next_run = datetime.fromisoformat(projected["next_run"])
    assert next_run.tzinfo is not None
    now = datetime.now(UTC)
    assert now <= next_run <= now + timedelta(minutes=2), (now, next_run)


def test_berlin_schedule_keeps_wall_time_and_season_offset(
    client: httpx.Client, admin_session, workspace
) -> None:
    """04:30 Europe/Berlin must fire at the zone-correct UTC instant.

    Fired manually through the same admission path the tick uses (the
    natural fire is up to a day away), then the cursor's `next_run` is the
    zone-correct *next* 04:30. The api-tests container resolves the expected
    instant from its own pinned `tzdata` wheel, so this compares two
    independent zone databases' worth of arithmetic: the shipped image's
    answer against the test image's.
    """
    r = _create_schedule(client, BERLIN_NAME, "30 4 * * *", "Europe/Berlin", workspace)
    assert r.status_code == 201, f"Berlin schedule create failed: {r.text}"
    sid = r.json()["id"]

    fired = client.post(f"/v1/schedules/{sid}/run", json={})
    assert fired.status_code == 200, f"Manual fire failed: {fired.status_code} {fired.text}"

    projected = _next_run(client, sid)
    next_run = datetime.fromisoformat(projected["next_run"])
    berlin = ZoneInfo("Europe/Berlin")

    # Wall time survives: it is 04:30 *in Berlin*, not in UTC.
    local = next_run.astimezone(berlin)
    assert (local.hour, local.minute) == (4, 30), local

    # Season-correct offset: CET (+1) in winter, CEST (+2) in summer — the
    # DST property a zoneless or UTC-collapsed resolution cannot satisfy.
    expected_offset = local.utcoffset()
    assert expected_offset in (timedelta(hours=1), timedelta(hours=2)), expected_offset
    if local.month in (1, 12):
        assert expected_offset == timedelta(hours=1), expected_offset
    if local.month == 7:
        assert expected_offset == timedelta(hours=2), expected_offset

    # And it is the *next* 04:30 Berlin from the fire, as an exact UTC instant.
    now_berlin = datetime.now(UTC).astimezone(berlin)
    candidate = now_berlin.replace(hour=4, minute=30, second=0, microsecond=0)
    if candidate <= now_berlin:
        candidate += timedelta(days=1)
    delta = abs((next_run - candidate.astimezone(UTC)).total_seconds())
    assert delta <= 60, (next_run, candidate.astimezone(UTC))


def test_invalid_timezone_is_refused_at_the_boundary(
    client: httpx.Client, admin_session, workspace
) -> None:
    for zone in ("Mars/Olympus_Mons", "Not/AZone"):
        r = _create_schedule(client, f"bad zone {zone}", "* * * * *", zone, workspace)
        assert r.status_code == 422, f"{zone} was accepted: {r.status_code} {r.text}"


def test_health_reports_tz_database_and_scheduler(client: httpx.Client) -> None:
    """The shipped image's zone source is visible, and the scheduler runs."""
    data = client.get("/health").json()
    assert data["tz_database"]["status"] == "available", data["tz_database"]
    assert data["tz_database"]["source"], "tz source must be recorded"
    assert data["scheduler"]["running"] is True, data["scheduler"]


@pytest.mark.skipif(
    os.environ.get("SCHED_TZ_AFTER_RESTART") != "1",
    reason="runs only in the post-restart phase (CI starts hive again first)",
)
def test_restart_recovery_preserves_schedules_and_recomputes_next_run(
    client: httpx.Client, admin_session
) -> None:
    """After the container restart, persisted schedules are intact and due.

    In CI the hive container is stopped and started again before this
    selection runs (same durable state dir, fresh process): persistence is
    the state dir's, the UTC schedule's recomputed cursor proves the boot
    reconciliation and the tick are live again, and the Berlin cursor —
    persisted before the restart — still names a future 04:30 Berlin.
    """
    r = client.get("/v1/schedules")
    assert r.status_code == 200, r.text
    by_name: dict[str, dict] = {}
    for s in r.json():
        if s.get("name") in (UTC_NAME, BERLIN_NAME) and s.get("enabled"):
            kept = by_name.get(s["name"])
            if kept is None or str(s.get("created_at")) > str(kept.get("created_at")):
                by_name[s["name"]] = s
    assert UTC_NAME in by_name, f"UTC schedule lost across restart: {sorted(by_name)}"
    assert BERLIN_NAME in by_name, f"Berlin schedule lost across restart: {sorted(by_name)}"

    now = datetime.now(UTC)

    # The UTC schedule fires within a tick of coming back up, so its cursor
    # is recomputed from the persisted zone by the new process.
    utc_row = by_name[UTC_NAME]
    if not utc_row.get("next_run"):
        utc_row = _next_run(client, utc_row["id"])
    utc_next = datetime.fromisoformat(utc_row["next_run"])
    assert utc_next.tzinfo is not None
    assert utc_next > now - timedelta(minutes=5), utc_row["next_run"]

    # The Berlin cursor persisted across the restart and still names the
    # zone-correct next occurrence: 04:30 wall time, season offset, future.
    berlin_row = by_name[BERLIN_NAME]
    if not berlin_row.get("next_run"):
        berlin_row = _next_run(client, berlin_row["id"])
    berlin_next = datetime.fromisoformat(berlin_row["next_run"])
    berlin = ZoneInfo("Europe/Berlin")
    local = berlin_next.astimezone(berlin)
    assert (local.hour, local.minute) == (4, 30), local
    assert local.utcoffset() in (timedelta(hours=1), timedelta(hours=2)), local
    assert berlin_next > now - timedelta(minutes=5), berlin_row["next_run"]

    # Scheduler is live again on the health surface, not merely up.
    health = client.get("/health").json()
    assert health["scheduler"]["running"] is True, health["scheduler"]
    assert health["tz_database"]["status"] == "available", health["tz_database"]
