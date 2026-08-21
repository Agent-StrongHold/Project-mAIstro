"""Notification protocol — push messages to a user-facing channel (ntfy, etc).

Sits alongside :mod:`maistro.tasks.progress_webhook` but is intended for
human-visible notifications (phone push, web) rather than machine-readable
progress feeds. Concrete implementations live under
:mod:`maistro.integrations` (e.g. ``NtfyClient``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Notification:
    """A single user-facing notification.

    Mirrors the common subset of ntfy's publish API but is provider-agnostic:
    fields a client cannot honor are simply dropped.
    """

    message: str
    title: str = ""
    priority: int = 3
    tags: tuple[str, ...] = ()
    click: str = ""
    topic: str = ""


@runtime_checkable
class NotificationClient(Protocol):
    """Send a :class:`Notification` to a user-facing channel."""

    async def send(self, notification: Notification) -> None: ...

    async def aclose(self) -> None: ...


__all__ = ["Notification", "NotificationClient"]
