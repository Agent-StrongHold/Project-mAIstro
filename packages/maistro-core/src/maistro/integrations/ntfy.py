"""ntfy.sh client — push notifications to a self-hosted or hosted ntfy server.

Publishes a :class:`~maistro.protocols.notification.Notification` via
``POST {base_url}/{topic}`` with optional bearer-token auth. Failures are
logged at debug and never propagate to callers, matching the convention used
by :mod:`maistro.tasks.progress_webhook`.

ntfy publish API reference: https://docs.ntfy.sh/publish/
"""

from __future__ import annotations

import logging

import httpx

from maistro.http import get_shared_client
from maistro.protocols.notification import Notification

logger = logging.getLogger("maistro.integrations.ntfy")


class NtfyClient:
    """POST notifications to an ntfy server.

    Args:
        base_url: Base URL of the ntfy server (e.g. ``https://ntfy.example.com``).
        default_topic: Topic used when a :class:`Notification` does not specify one.
        access_token: Optional bearer token for servers with ``deny-all`` ACLs.
        client: Pre-built ``httpx.AsyncClient`` (for tests). When omitted, a
            new client is constructed and owned by this instance.
        timeout: Request timeout in seconds when constructing the default client.
    """

    def __init__(
        self,
        *,
        base_url: str,
        default_topic: str = "",
        access_token: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_topic = default_topic
        self._access_token = access_token
        # Never: the pool owns the shared client, and closing it here would
        # close it for every other caller on this loop.
        self._owns_client = False
        # The shared pool, so this integration is covered by the outbound
        # policy at its transport (#155) rather than opting itself out by
        # building a private client.
        self._client = client or get_shared_client(timeout=timeout)

    async def send(self, notification: Notification) -> None:
        if not self._base_url:
            return
        topic = notification.topic or self._default_topic
        if not topic:
            await self._adebug("ntfy_send_skipped_no_topic")
            return

        headers: dict[str, str] = {}
        if notification.title:
            headers["Title"] = notification.title
        if notification.priority and notification.priority != 3:
            headers["Priority"] = str(notification.priority)
        if notification.tags:
            headers["Tags"] = ",".join(notification.tags)
        if notification.click:
            headers["Click"] = notification.click
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        url = f"{self._base_url}/{topic}"
        try:
            await self._client.post(
                url,
                content=notification.message.encode("utf-8"),
                headers=headers,
            )
        except Exception:
            await self._adebug("ntfy_send_failed", url=url)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _adebug(self, event: str, **kw: object) -> None:
        logger.debug("%s %s", event, kw, exc_info=True)


__all__ = ["NtfyClient"]
