"""The degraded Agent port must never manufacture a successful completion (#840)."""

from __future__ import annotations

import pytest
from adapters.maistro_core import StubAgentPort


@pytest.mark.asyncio
async def test_stub_agent_port_reports_unavailable() -> None:
    port = StubAgentPort()
    with pytest.raises(RuntimeError, match="Agent runtime is unavailable"):
        await port.route([{"role": "user", "content": "hello"}])
