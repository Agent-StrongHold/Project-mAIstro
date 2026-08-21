from __future__ import annotations

PROBE_SIZES: list[int] = [4096, 16384, 65536, 131072, 204800]


class ContextProbe:
    def __init__(self) -> None:
        self._cache: dict[str, int] = {}
        self._probe_index: dict[str, int] = {}

    def get_context_length(self, model: str) -> int | None:
        return self._cache.get(model)

    def set_known_length(self, model: str, length: int) -> None:
        self._cache[model] = length
        self._probe_index.pop(model, None)

    def probe_next_size(self, model: str) -> int | None:
        if model in self._cache:
            return None
        idx = self._probe_index.get(model, 0)
        if idx >= len(PROBE_SIZES):
            return None
        return PROBE_SIZES[idx]

    def record_overflow(self, model: str, requested_tokens: int) -> int:
        limit = requested_tokens - 1
        self._cache[model] = limit
        self._probe_index.pop(model, None)
        return limit

    def record_success(self, model: str, used_tokens: int) -> None:
        if model in self._cache:
            return
        idx = self._probe_index.get(model, 0)
        if idx < len(PROBE_SIZES) and used_tokens >= PROBE_SIZES[idx]:
            next_idx = idx + 1
            if next_idx >= len(PROBE_SIZES):
                self._cache[model] = PROBE_SIZES[-1]
            else:
                self._probe_index[model] = next_idx
