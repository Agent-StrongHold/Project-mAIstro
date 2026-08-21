"""Channel registry for outbound delivery (SPEC-251 / ADR-047)."""

from __future__ import annotations

from maistro.delivery.protocols import Channel


class ChannelRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        self._channels[channel.name] = channel

    def get(self, name: str) -> Channel:
        return self._channels[name]

    def list_channels(self) -> list[str]:
        return list(self._channels)
