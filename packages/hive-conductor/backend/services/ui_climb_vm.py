"""UI hill-climb via Hyperlight microVM.

Instead of trying to run playwright locally, we:
1. Request a Hyperlight sandbox from the broker
2. The microVM has chromium + playwright + node baked in
3. Run the edit→compile→build→restart→screenshot→score loop INSIDE the VM
4. Results come back via the sandbox API

This is the correct execution model. The hill-climb runs where the
tools actually work — inside the microVM, not on a dev laptop.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.ui_climb_vm")

BROKER_URL = os.environ.get("SANDBOX_BROKER_URL", "http://localhost:8090/api/v1")


async def request_hill_climb_vm(component: str = "Chat.tsx", passes: int = 5) -> dict[str, Any]:
    """Request a Hyperlight microVM to run the UI hill-climb loop.

    The VM gets:
    - The current frontend source
    - Chromium + playwright
    - Node.js for builds
    - The hill-climb script
    - Network access to LiteLLM gateway for scoring

    Returns results when the VM completes (or streams progress).
    """
    payload = {
        "type": "hyperlight",
        "isolation": "hyperlight",
        "access": "api_only",
        "ttl_minutes": 30,
        "litellm_virtual_key": os.environ.get("LITELLM_API_KEY", ""),
        "workload": {
            "script": "hill-climb-ui.sh",
            "args": [component, str(passes)],
            "env": {
                "BRAVE_SEARCH_API_KEY": os.environ.get("BRAVE_SEARCH_API_KEY", ""),
                "LITELLM_API_BASE": os.environ.get("LITELLM_API_BASE", ""),
                "LITELLM_API_KEY": os.environ.get("LITELLM_API_KEY", ""),
            },
        },
        "resources": {
            "cpu": "2",
            "memory_gi": "4",
        },
    }

    async with shared_client(timeout=300.0) as client:
        r = await client.post(
            f"{BROKER_URL}/sandboxes",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code == 201:
            return r.json()
        return {"error": f"Broker returned {r.status_code}: {r.text[:200]}"}


async def run_ui_hill_climb(component: str = "Chat.tsx", passes: int = 5) -> dict[str, Any]:
    """Full flow: request VM → run hill-climb → collect results."""
    logger.info(f"Requesting Hyperlight VM for UI hill-climb: {component}, {passes} passes")

    result = await request_hill_climb_vm(component, passes)

    if "error" in result:
        logger.error(f"VM request failed: {result['error']}")
        return result

    lease_id = result.get("lease_id", "")
    logger.info(f"VM provisioned: {lease_id}")

    # Poll for completion (the VM runs the script and reports back)
    async with shared_client(timeout=600.0) as client:
        for _ in range(120):  # poll for up to 10 minutes
            import asyncio

            await asyncio.sleep(5)
            r = await client.get(f"{BROKER_URL}/sandboxes/{lease_id}/status")
            if r.status_code != 200:
                continue
            status = r.json()
            if status.get("state") == "completed":
                return status.get("result", {})
            if status.get("state") == "failed":
                return {"error": status.get("error", "VM execution failed")}

    return {"error": "timeout waiting for VM completion"}
