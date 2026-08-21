from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time


class RateLimitCoordinator:
    def __init__(self, state_file: str | None = None) -> None:
        self._state_file = state_file
        self._in_memory: dict[str, float] = {}

    def record_rate_limit(self, provider: str, reset_at: float) -> None:
        if self._state_file is None:
            self._in_memory[provider] = reset_at
        else:
            self._write_state(provider, reset_at)

    def is_rate_limited(self, provider: str) -> bool:
        reset_time = self.get_reset_time(provider)
        if reset_time is None:
            return False
        return time.time() < reset_time

    def get_reset_time(self, provider: str) -> float | None:
        if self._state_file is None:
            return self._in_memory.get(provider)
        return self._read_state(provider)

    def clear(self, provider: str) -> None:
        if self._state_file is None:
            self._in_memory.pop(provider, None)
        else:
            self._clear_provider(provider)

    def clear_all(self) -> None:
        if self._state_file is None:
            self._in_memory.clear()
        else:
            self._save_file({})

    def _read_state(self, provider: str) -> float | None:
        data = self._load_file()
        return data.get(provider)

    def _write_state(self, provider: str, reset_at: float) -> None:
        data = self._load_file()
        data[provider] = reset_at
        self._save_file(data)

    def _clear_provider(self, provider: str) -> None:
        data = self._load_file()
        data.pop(provider, None)
        self._save_file(data)

    def _load_file(self) -> dict[str, float]:
        if self._state_file is None or not os.path.exists(self._state_file):
            return {}
        try:
            with open(self._state_file) as f:
                data: dict[str, float] = json.load(f)
                return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_file(self, data: dict[str, float]) -> None:
        state_file = self._state_file
        if state_file is None:
            return
        parent = os.path.dirname(state_file)
        tmp_dir = parent if parent else None
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=tmp_dir, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, state_file)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
