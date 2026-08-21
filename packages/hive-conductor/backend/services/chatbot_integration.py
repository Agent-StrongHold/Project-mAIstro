"""Chatbot integration — create and manage chatbots via the external Chatbot API.

Exposes the Chatbot platform as tools the PM chat can use:
- Create a new chatbot team
- Configure its prompt
- Connect knowledge sources
- Test it
- Optimize it
"""

from __future__ import annotations

import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.chatbot_integration")

CHATBOT_BASE = os.environ.get("CHATBOT_URL", "")


def _headers() -> dict[str, str]:
    token = os.environ.get("CHATBOT_TOKEN", os.environ.get("LITELLM_API_KEY", ""))
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def create_team(team_id: str) -> dict[str, Any]:
    """Create a new chatbot team."""
    async with shared_client(timeout=30.0) as client:
        r = await client.post(f"{CHATBOT_BASE}/teams", json={"teamID": team_id}, headers=_headers())
        if r.status_code in (200, 201):
            return {"created": True, "team_id": team_id}
        return {"error": f"Failed to create team: {r.status_code} {r.text[:200]}"}


async def set_prompt(team_id: str, prompt: str) -> dict[str, Any]:
    """Set/update the chatbot's system prompt."""
    async with shared_client(timeout=30.0) as client:
        r = await client.put(
            f"{CHATBOT_BASE}/teams/{team_id}/prompt",
            json={"content": prompt},
            headers=_headers(),
        )
        if r.status_code == 200:
            return {"updated": True, "team_id": team_id}
        return {"error": f"Failed to set prompt: {r.status_code} {r.text[:200]}"}


async def get_prompt(team_id: str) -> dict[str, Any]:
    """Get the current prompt for a team."""
    async with shared_client(timeout=30.0) as client:
        r = await client.get(f"{CHATBOT_BASE}/teams/{team_id}/prompt", headers=_headers())
        if r.status_code == 200:
            return r.json()
        return {"error": f"Failed to get prompt: {r.status_code}"}


async def list_knowledge_bases(team_id: str = "") -> dict[str, Any]:
    """List available knowledge bases."""
    params = {"team_id": team_id} if team_id else {}
    async with shared_client(timeout=30.0) as client:
        r = await client.get(f"{CHATBOT_BASE}/knowledgebases", params=params, headers=_headers())
        if r.status_code == 200:
            return r.json()
        return {"error": f"Failed to list KBs: {r.status_code}"}


async def create_knowledge_base(name: str, owner_email: str, team_id: str = "") -> dict[str, Any]:
    """Create a new knowledge base."""
    body: dict[str, Any] = {"name": name, "owner_email": owner_email}
    if team_id:
        body["team_id"] = team_id
    async with shared_client(timeout=30.0) as client:
        r = await client.post(f"{CHATBOT_BASE}/knowledgebases", json=body, headers=_headers())
        if r.status_code == 200:
            return r.json()
        return {"error": f"Failed to create KB: {r.status_code} {r.text[:200]}"}


async def add_confluence_source(kb_id: str, source_url: str) -> dict[str, Any]:
    """Add a Confluence space as a knowledge source."""
    async with shared_client(timeout=30.0) as client:
        r = await client.post(
            f"{CHATBOT_BASE}/knowledgebases/{kb_id}/sources",
            json={"source_url": source_url, "source_type": "confluence"},
            headers=_headers(),
        )
        if r.status_code == 200:
            return r.json()
        return {"error": f"Failed to add source: {r.status_code} {r.text[:200]}"}


async def chat(message: str, team_id: str = "", conversation_id: str = "") -> dict[str, Any]:
    """Send a message to a Chatbot team and get the response."""
    body: dict[str, Any] = {"message": message}
    if team_id:
        body["team_id"] = team_id
    if conversation_id:
        body["conversation_id"] = conversation_id

    async with shared_client(timeout=60.0) as client:
        # Start job
        r = await client.post(f"{CHATBOT_BASE}/chatbot/chat", json=body, headers=_headers())
        if r.status_code != 200:
            return {"error": f"Chat failed: {r.status_code} {r.text[:200]}"}
        data = r.json()
        job_id = data.get("job_id")
        if not job_id:
            return {"error": "No job_id returned"}

        # Poll for completion
        import asyncio

        for _ in range(30):  # max 30 polls x 2s = 60s
            await asyncio.sleep(2)
            r = await client.get(f"{CHATBOT_BASE}/chatbot/chat/{job_id}", headers=_headers())
            if r.status_code != 200:
                continue
            result = r.json()
            if result.get("status") == "COMPLETED":
                return {
                    "response": result.get("response", ""),
                    "conversation_id": result.get("conversation_id"),
                }
            if result.get("status") == "FAILED":
                return {"error": result.get("error", "Job failed")}

        return {"error": "Timeout waiting for response"}


async def get_team_config(team_id: str) -> dict[str, Any]:
    """Get full team configuration (model, tools, etc)."""
    async with shared_client(timeout=30.0) as client:
        r = await client.get(f"{CHATBOT_BASE}/ops-agent/teams/{team_id}/config", headers=_headers())
        if r.status_code == 200:
            return r.json()
        return {"error": f"Failed to get config: {r.status_code}"}


async def update_team_config(team_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Update team configuration (model, tools, etc)."""
    async with shared_client(timeout=30.0) as client:
        r = await client.put(
            f"{CHATBOT_BASE}/ops-agent/teams/{team_id}/config",
            json=config,
            headers=_headers(),
        )
        if r.status_code == 200:
            return r.json()
        return {"error": f"Failed to update config: {r.status_code} {r.text[:200]}"}
