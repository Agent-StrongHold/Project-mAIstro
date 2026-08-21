"""In-memory prompt library with versioning and labels.

System/agent prompts use raw names. User-scoped prompts use "user:name" keys.
"""

from __future__ import annotations

from typing import Any


class InMemoryPromptManager:
    """In-memory prompt manager for testing and local dev."""

    def __init__(self) -> None:
        self._versions: dict[str, dict[int, tuple[str, dict[str, Any]]]] = {}
        self._labels: dict[str, dict[str, int]] = {}
        self._next_version: dict[str, int] = {}

    @staticmethod
    def _scoped_name(name: str, user_id: str = "") -> str:
        is_shared = name.startswith("agent.") or name.startswith("system.")
        if not user_id or is_shared:
            return name
        return f"{user_id}:{name}"

    async def get(self, name: str, *, label: str = "production", user_id: str = "") -> str:
        content, _ = await self.get_with_config(name, label=label, user_id=user_id)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
        user_id: str = "",
    ) -> tuple[str, dict[str, Any]]:
        key = self._scoped_name(name, user_id)
        labels = self._labels.get(key, {})
        version = labels.get(label)
        if version is None:
            versions = self._versions.get(key, {})
            if not versions:
                return ("", {})
            version = max(versions)

        versions = self._versions.get(key, {})
        entry = versions.get(version)
        if entry is None:
            return ("", {})
        return entry

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
        user_id: str = "",
    ) -> None:
        key = self._scoped_name(name, user_id)
        if key not in self._versions:
            self._versions[key] = {}
            self._labels[key] = {}
            self._next_version[key] = 1

        version = self._next_version[key]
        self._next_version[key] = version + 1
        self._versions[key][version] = (content, config or {})

        if label:
            self._labels[key][label] = version
        self._labels[key]["latest"] = version
        if version == 1 and "production" not in self._labels[key]:
            self._labels[key]["production"] = version
