from __future__ import annotations

import threading


class SteeringQueue:
    def __init__(self) -> None:
        self._entries: list[str] = []
        self._lock = threading.Lock()

    def steer(self, guidance: str) -> None:
        with self._lock:
            self._entries.append(guidance)

    def drain(self) -> list[str]:
        with self._lock:
            entries = list(self._entries)
            self._entries.clear()
            return entries

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def get_all(self) -> list[str]:
        with self._lock:
            return list(self._entries)
