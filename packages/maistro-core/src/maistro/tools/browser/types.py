"""Frozen dataclasses for the browser tool's return shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass(frozen=True)
class BrowseResult:
    url: str
    title: str
    text: str = ""
    screenshot_b64: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text[:8000],  # cap inline text — full text goes in screenshot/raw
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class SearchResult:
    query: str
    summary: str
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    duration_ms: int = 0
    source: str = "browser-use"  # browser-use | duckduckgo-fallback | error

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "results_count": len(self.citations),
            "sources": [c.to_dict() for c in self.citations],
            "duration_ms": self.duration_ms,
            "source": self.source,
        }
