"""self_repair end-to-end with the real infra_action + approval inbox (SPEC-188).

Proves the loop composes with SPEC-187's actual gate: a destructive remediation
is parked pending approval and only hits the host once approved.
"""

from __future__ import annotations

import asyncio

import httpx

from maistro.capabilities.http_client import HttpxAsyncHttp
from maistro.capabilities.providers.approval_inbox import InboxApproval
from maistro.capabilities.providers.host_health import HostHealthAction
from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.slots.infra import InfraHealth, ResourceHealth
from maistro.capabilities.slots.self_repair import RepairDecision
from maistro.capabilities.types import ProviderHealth


class _Monitor:
    name = "m"
    slot = "infra_monitor"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    async def snapshot(self) -> InfraHealth:
        return InfraHealth(
            ts="t",
            resources={
                "docker": ResourceHealth(
                    "degraded", {"containers": [{"name": "litellm", "state": "unhealthy"}]}
                )
            },
        )


async def test_remediation_blocks_until_approved_then_hits_host() -> None:
    # Under approve_all even a reversible restart is gated; it parks pending
    # approval and only hits the host once resolved.
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json={"status": "ok", "detail": "restarted"})

    http = HttpxAsyncHttp("http://h:8150", transport=httpx.MockTransport(handler))
    inbox = InboxApproval()
    action = HostHealthAction(http, autonomy="approve_all", approval=inbox)
    repair = RuleBasedRepair(infra_monitor=_Monitor(), infra_action=action, autonomy="approve_all")

    cycle = await repair.run_once()
    (r,) = cycle.results
    assert r.decision is RepairDecision.PENDING_APPROVAL
    await asyncio.sleep(0)  # let the dispatch task reach approval.request()

    # Parked: nothing sent to the host yet, one pending approval.
    assert sent == []
    pending = inbox.pending()
    assert len(pending) == 1
    assert pending[0].action == "restart_container"

    # Approve through the inbox → the host action now fires.
    assert inbox.resolve(pending[0].request_id, approved=True, actor="tester") is True
    await asyncio.gather(*list(repair._tasks))
    assert sent == ["/action/restart_container"]


async def test_denied_remediation_never_hits_host() -> None:
    sent: list[str] = []
    http = HttpxAsyncHttp(
        "http://h:8150",
        transport=httpx.MockTransport(
            lambda r: (sent.append(r.url.path), httpx.Response(200, json={}))[1]
        ),
    )
    inbox = InboxApproval()
    action = HostHealthAction(http, autonomy="approve_all", approval=inbox)
    repair = RuleBasedRepair(infra_monitor=_Monitor(), infra_action=action, autonomy="approve_all")

    await repair.run_once()
    await asyncio.sleep(0)
    pending = inbox.pending()
    inbox.resolve(pending[0].request_id, approved=False)
    await asyncio.gather(*list(repair._tasks))
    assert sent == []
