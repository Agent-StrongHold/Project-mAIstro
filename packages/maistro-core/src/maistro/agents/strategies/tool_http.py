"""HTTP tool executor: calls dev-tools-mcp and other HTTP-based tool servers."""

from __future__ import annotations

import json
from typing import Any

from maistro.http import shared_client


class HTTPToolExecutor:
    """Calls tools on HTTP servers like dev-tools-mcp."""

    def __init__(self, base_url: str = "http://dev-tools-mcp:8300") -> None:
        self._base_url = base_url.rstrip("/")

    async def call(self, tool_name: str, args: dict[str, Any]) -> str:
        url = f"{self._base_url}/tools/{tool_name}"
        try:
            async with shared_client(timeout=120.0) as client:
                resp = await client.post(url, json=args)
                if resp.status_code != 200:
                    return f"Error: HTTP {resp.status_code} - {resp.text[:200]}"
                data = resp.json()

                if "passed" in data:
                    if data["passed"]:
                        return f'"passed": true, "summary": "{data.get("summary", "OK")}"'
                    raw = data.get("raw_output", "")[:2000]
                    return f'"passed": false, "summary": "{data.get("summary", "")}"\n{raw}'

                if "error" in data and data.get("status") == "failed":
                    return f'"status": "failed", "error": "{data["error"]}"'

                return json.dumps(data, indent=None)[:3000]
        except Exception as e:
            return f"Error: {e}"

    async def list_tools(self) -> list[dict[str, str]]:
        try:
            async with shared_client(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/tools")
                if resp.status_code == 200:
                    data: dict[str, Any] = resp.json()
                    tools: list[dict[str, str]] = data.get("tools", [])
                    return tools
        except Exception as _exc:
            __import__("logging").getLogger("maistro.agents.strategies.tool_htt").warning(
                "error_swallowed file=%s line=%d: %s",
                "packages/maistro-core/src/maistro/agents/strategies/tool_http.py",
                47,
                _exc,
            )
            pass
        return []
