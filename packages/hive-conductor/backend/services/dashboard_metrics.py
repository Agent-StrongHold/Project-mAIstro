"""Dashboard KPI envelopes — measured values, or an explicit reason there is none.

#380: the `/v1/dashboard/metrics` payload used to be hard-coded zeros
(``runs_today: 0``, ``ttft_ms: 0``) plus a literal ``9``-agent fallback, so a
deployment with real activity looked idle and a broken source looked healthy.
Missing telemetry was rendered as a measured zero, and only one of those is
visibly wrong.

Every KPI is now an envelope that names its authoritative query, scope, time
window, unit and freshness, and carries exactly one state:

- ``ok``          — measured, including a legitimate measured zero
- ``no_data``     — the source answered, and has never observed anything for
                    this principal (an average over an empty set is undefined,
                    not zero)
- ``stale``       — a value exists, but it is known to be incomplete or old
                    (in-memory history that restarted mid-window, or
                    observations older than the window)
- ``unavailable`` — no authoritative source exists in this deployment
- ``error``       — the source raised; the reason is public failure text

``loading``, ``unauthorized`` and the transport ``error`` are fetch-level
states the SPA renders from the HTTP exchange itself.

Scope: every envelope is computed for the authenticated principal from
``request.state.user`` — the same boundary the layout routes use. Nothing
pools another account's usage into this one's KPIs, and every query iterates a
bounded collection (``MAX_RUNS`` ring, 10_000-observation metric cap, agent
roster), so cardinality is bounded by construction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("hive.dashboard-metrics")

#: The state vocabulary the SPA's KPI renderer switches on. Loading and
#: unauthorized are deliberately absent: those belong to the fetch, not the
#: payload.
STATES = ("ok", "no_data", "stale", "unavailable", "error")

#: Trailing windows for the chat-telemetry KPIs. The source is the in-process
#: chat metric ring (bounded at 10_000 observations), so "process lifetime" is
#: part of what the window string has to say.
LATENCY_WINDOW_SECONDS = 3600
COST_WINDOW_SECONDS = 24 * 3600
INVOCATIONS_STALE_AFTER_SECONDS = 24 * 3600


def _public(exc: BaseException) -> str:
    """One safe sentence about a source failure, for the SPA to render."""
    return f"{type(exc).__name__}: {exc}"[:200]


def envelope(
    *,
    state: str,
    unit: str,
    query: str,
    scope: str,
    window: str,
    computed_at: datetime,
    value: float | int | None = None,
    last_update: datetime | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build one KPI envelope; the schema every renderer switches on."""
    if state not in STATES:
        raise ValueError(f"unknown KPI state {state!r}")
    if state == "ok" and value is None:
        raise ValueError("an `ok` envelope carries its measured value")
    if state in ("no_data", "unavailable", "error") and value is not None:
        raise ValueError(f"a `{state}` envelope has no value to show")
    return {
        "state": state,
        "value": value,
        "unit": unit,
        "query": query,
        "scope": scope,
        "window": window,
        "computed_at": computed_at.isoformat(),
        "last_update": last_update.isoformat() if last_update else None,
        "reason": reason,
    }


# ─── Sources ────────────────────────────────────────────────────────────────


def _active_agents(principal: str, computed_at: datetime) -> dict[str, Any]:
    """Agent-roster count, from the store `GET /v1/agents` itself reads.

    The route returns the workspaceless roster to any authenticated principal,
    so the KPI counts exactly what the Agents widget shows this principal. An
    empty roster is a measured zero, not missing data: the query ran and
    counted zero rows. The old code read a `data/agents.json` that does not
    exist and fell back to a literal `9`.
    """
    import stores

    scope = "workspaceless agents visible to GET /v1/agents (principal-authenticated)"
    try:
        visible = [a for a in stores.agents.values() if a.workspace_id is None]
    except Exception as exc:
        return envelope(
            state="error",
            unit="agents",
            query="stores.agents (workspaceless roster)",
            scope=scope,
            window="current roster",
            computed_at=computed_at,
            reason=_public(exc),
        )
    last = max((a.created_at for a in visible), default=None)
    return envelope(
        state="ok",
        value=len(visible),
        unit="agents",
        query="stores.agents (workspaceless roster), same query as GET /v1/agents",
        scope=scope,
        window="current roster",
        computed_at=computed_at,
        last_update=last,
    )


def _runs_today(principal: str, computed_at: datetime) -> dict[str, Any]:
    """Runs started since local midnight, from the DAG run store.

    ``today`` is honest about two things the old hard-coded ``0`` hid: the
    store's bounded working set, and — when history is in-memory — that a
    process restart mid-day makes the count partial, which is `stale`, not a
    healthy zero.
    """
    from services import dag_run_store as drs

    store = _run_store()
    local_now = computed_at.astimezone()
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    scope = f"user:{principal}"
    query = "DagRunStore.count_since(user_id, started_after=local midnight)"

    try:
        stats = store.count_since(user_id=principal, started_after=midnight.timestamp())
    except Exception as exc:
        return envelope(
            state="error",
            unit="runs",
            query=query,
            scope=scope,
            window=f"today, since {midnight.isoformat()}",
            computed_at=computed_at,
            reason=_public(exc),
        )

    last = stats.get("last_started_at")
    last_dt = datetime.fromtimestamp(last, tz=UTC) if last else None
    reason: str | None = None
    state = "ok"
    if not stats["is_durable"] and midnight.timestamp() < drs._PROCESS_BOOT_TS:
        boot = datetime.fromtimestamp(drs._PROCESS_BOOT_TS, tz=UTC).astimezone()
        state = "stale"
        reason = (
            "run history is in-memory and the process booted "
            f"{boot.isoformat()}, after local midnight — runs from earlier "
            "today are not counted"
        )
    elif stats["count"] >= stats["bound"] > 0:
        state = "stale"
        reason = (
            f"the run working set is at its bound of {stats['bound']}; "
            "older runs today were evicted, so the count is a floor"
        )
    return envelope(
        state=state,
        value=stats["count"],
        unit="runs",
        query=query,
        scope=scope,
        window=f"today, since {midnight.isoformat()}",
        computed_at=computed_at,
        last_update=last_dt,
        reason=reason,
    )


def _run_store() -> Any:
    """The process run store, behind a seam tests can patch."""
    from services.dag_run_store import get_dag_run_store

    return get_dag_run_store()


def _chat_envelope(
    principal: str,
    computed_at: datetime,
    *,
    unit: str,
    query: str,
    window_seconds: int | None,
    window_label: str,
    stale_after_seconds: int,
    pick: Callable[[dict[str, Any], int], float],
) -> dict[str, Any]:
    """Shared shape for the KPIs sourced from the chat metric ring.

    `pick` extracts the number from a (summary, count) pair. An empty ring is
    `no_data` — a mean over zero observations is undefined — and a KPI whose
    newest observation predates its window is `stale`: the last-known value is
    still shown, labelled with how old it is, never as a fresh looking zero.
    `window_seconds=None` means the whole in-process ring.
    """
    from services.chat_completion import get_chat_metrics_summary

    scope = f"user:{principal}"
    window = window_label
    try:
        summary = get_chat_metrics_summary(
            user_id=principal,
            window_seconds=window_seconds,
        )
        # The windowed set is what `ok` is computed from; the full ring tells
        # an empty window apart from a principal this process has never seen.
        full = summary if window_seconds is None else get_chat_metrics_summary(user_id=principal)
    except Exception as exc:
        return envelope(
            state="error",
            unit=unit,
            query=query,
            scope=scope,
            window=window,
            computed_at=computed_at,
            reason=_public(exc),
        )
    count = summary["count"]
    last_ts = summary.get("last_observation_ts")
    if count == 0:
        if full["count"] == 0:
            return envelope(
                state="no_data",
                unit=unit,
                query=query,
                scope=scope,
                window=window,
                computed_at=computed_at,
                reason="no chat activity observed for this principal yet",
            )
        # Observations exist but none in the window: show the last-known
        # value, explicitly stale, with the age it carries.
        last_full = full.get("last_observation_ts")
        age_h = max(1, int((computed_at.timestamp() - (last_full or 0)) // 3600))
        return envelope(
            state="stale",
            value=pick(full, full["count"]),
            unit=unit,
            query=query,
            scope=scope,
            window=window,
            computed_at=computed_at,
            last_update=datetime.fromtimestamp(last_full, tz=UTC) if last_full else None,
            reason=(
                f"nothing measured in the window; newest observation is ~{age_h}h old "
                "(shown value is the last-known one)"
            ),
        )
    if last_ts and (computed_at.timestamp() - last_ts) > stale_after_seconds:
        age_h = max(1, int((computed_at.timestamp() - last_ts) // 3600))
        state = "stale"
        reason = f"newest observation is ~{age_h}h old ({window_label})"
        value = pick(summary, count)
        last_dt = datetime.fromtimestamp(last_ts, tz=UTC)
    else:
        state = "ok"
        reason = None
        value = pick(summary, count)
        last_dt = datetime.fromtimestamp(last_ts, tz=UTC) if last_ts else None
    return envelope(
        state=state,
        value=value,
        unit=unit,
        query=query,
        scope=scope,
        window=window,
        computed_at=computed_at,
        last_update=last_dt,
        reason=reason,
    )


def _avg_latency(principal: str, computed_at: datetime) -> dict[str, Any]:
    return _chat_envelope(
        principal,
        computed_at,
        unit="ms",
        query="chat metric ring: mean latency_ms over the windowed set",
        window_seconds=LATENCY_WINDOW_SECONDS,
        window_label=f"trailing {LATENCY_WINDOW_SECONDS // 3600}h of in-process chat observations (bounded at 10,000)",
        stale_after_seconds=LATENCY_WINDOW_SECONDS,
        pick=lambda s, _n: round(s["latency_ms_mean"], 1),
    )


def _total_cost(principal: str, computed_at: datetime) -> dict[str, Any]:
    return _chat_envelope(
        principal,
        computed_at,
        unit="USD",
        query=(
            "chat metric ring: sum(tokens_out x $3/M + tokens_in x $1/M) "
            "over the windowed set (token-price estimate, not invoiced cost)"
        ),
        window_seconds=COST_WINDOW_SECONDS,
        window_label=f"trailing {COST_WINDOW_SECONDS // 3600}h of in-process chat observations (bounded at 10,000)",
        stale_after_seconds=COST_WINDOW_SECONDS,
        pick=lambda s, _n: round(s["cost_usd_total"], 4),
    )


def _invocations(principal: str, computed_at: datetime) -> dict[str, Any]:
    """Total invocation count plus the percentiles/tokens the widget shows."""

    def pick(s: dict[str, Any], _n: int) -> float:
        return s["count"]

    env = _chat_envelope(
        principal,
        computed_at,
        unit="invocations",
        query="chat metric ring: count of observations for this principal (process lifetime)",
        window_seconds=None,
        window_label="process lifetime of in-process chat observations (bounded at 10,000)",
        stale_after_seconds=INVOCATIONS_STALE_AFTER_SECONDS,
        pick=pick,
    )
    if env["state"] in ("ok", "stale"):
        from services.chat_completion import get_chat_metrics_summary

        summary = get_chat_metrics_summary(user_id=principal)
        env["latency_ms_p50"] = summary["latency_ms_p50"]
        env["latency_ms_p95"] = summary["latency_ms_p95"]
        env["tokens_in_total"] = summary["tokens_in_total"]
        env["tokens_out_total"] = summary["tokens_out_total"]
    return env


# ─── Unsupported KPIs say so ────────────────────────────────────────────────


def _ttft(principal: str, computed_at: datetime) -> dict[str, Any]:
    """TTFT: nothing measures it, so the KPI says so instead of showing 0ms.

    The chat ring records end-to-end latency only. The old payload shipped
    ``ttft_ms: 0`` (and `/v1/widgets/metrics?metric=ttft` invented an
    ``avg_ttft_ms`` key to read 0 from), which rendered every deployment as a
    0 ms time-to-first-token.
    """
    return envelope(
        state="unavailable",
        unit="ms",
        query="none — no source in this deployment records time-to-first-token",
        scope=f"user:{principal}",
        window="n/a",
        computed_at=computed_at,
        reason="TTFT telemetry is not recorded by this deployment",
    )


def _approval_rate(principal: str, computed_at: datetime) -> dict[str, Any]:
    """Approval rate: no measured approvals, so the KPI is explicitly N/A."""
    return envelope(
        state="unavailable",
        unit="ratio",
        query="none — no source in this deployment records approval decisions as countable events",
        scope=f"user:{principal}",
        window="n/a",
        computed_at=computed_at,
        reason="approval decisions are not recorded, so no rate can be computed",
    )


# ─── Assembler ──────────────────────────────────────────────────────────────

_KPI_BUILDERS: tuple[tuple[str, Callable[[str, datetime], dict[str, Any]]], ...] = (
    ("active_agents", _active_agents),
    ("runs_today", _runs_today),
    ("avg_latency", _avg_latency),
    ("total_cost", _total_cost),
    ("invocations", _invocations),
    ("ttft", _ttft),
    ("approval_rate", _approval_rate),
)


def build_dashboard_metrics(principal: str) -> dict[str, Any]:
    """One envelope per KPI, computed at one instant for one principal.

    A builder that raises becomes an `error` envelope rather than poisoning
    the whole payload: one broken source must not blank every widget.
    """
    computed_at = datetime.now(UTC)
    kpis: dict[str, Any] = {}
    for name, builder in _KPI_BUILDERS:
        try:
            kpis[name] = builder(principal, computed_at)
        except Exception as exc:
            logger.warning("dashboard KPI %s failed for %s: %s", name, principal, exc)
            kpis[name] = envelope(
                state="error",
                unit="",
                query=f"{builder.__name__} raised",
                scope=f"user:{principal}",
                window="n/a",
                computed_at=computed_at,
                reason=_public(exc),
            )
    return kpis
