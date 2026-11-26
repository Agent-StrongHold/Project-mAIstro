"""Discovery source Provider: governed read-only fetches of declared sources (#1051).

Proactive discovery fetches **only the sources a Workspace's Binding declares**.
The Binding config carries the source allowlist — ``sources`` is a list of
``{url, category}`` entries — and resolution refuses any request URL that is
not on it. There is no open-web crawl seam here: the Binding is the
allow/deny control the issue asks for, enforced at the governed egress
boundary before any HTTP happens, and every fetch files one canonical
Invocation with its source provenance.

Fetches are plain public GETs (RSS 2.0 / Atom / JSON feed shapes). Unlike the
PM polling providers, this provider consumes no credential pool: it declares
no ``credential_provider`` surface, so callers wire it with the raw resolver
and executor (credential-routing refuses providers without that surface by
design). A source that later needs authentication crosses
:class:`~maistro.capabilities.credential_routing.CredentialRouting` the way
``jira.poll`` does; that is a provider-declaration change, not a second
egress.

Deadlines: an entry's ``expires_at`` is read **only from the source's own
payload** (an explicit field). Nothing here invents time-sensitivity; that is
what keeps #1049 escalation evidence honest downstream.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET  # nosec: B405  # nosemgrep
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.types import Unavailable
from maistro.http import shared_client
from maistro.security.ssrf import SSRFBlockedError

DISCOVERY_SOURCE_CAPABILITY = "discovery.source"

#: Entry fields parsed from a feed item. ``expires_at`` is honoured only when
#: the source itself carries it — an explicit deal window, never a guess.
_ENTRY_TEXT_KEYS = ("title", "summary", "url", "id", "category")
_MAX_SUMMARY_CHARS = 600


class DiscoverySourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, description="One declared source URL (Binding allowlist)")
    max_entries: int = Field(default=20, ge=1, le=100)


class DiscoverySourceHttpError(RuntimeError):
    """An HTTP response that reached the declared source."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DeclaredSource:
    """One Binding-declared source: the allowlist entry, verbatim."""

    url: str
    category: str


@dataclass(frozen=True)
class DiscoverySourceProvider:
    """Read-only fetcher bound to the sources its Binding declares."""

    sources: tuple[DeclaredSource, ...]

    @property
    def name(self) -> str:
        return "discovery-source"

    @property
    def slot(self) -> str:
        return DISCOVERY_SOURCE_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return "t2"

    def declared(self, url: str) -> DeclaredSource | None:
        """The allowlist entry this URL names, or None (deny-by-default)."""
        wanted = url.strip()
        for source in self.sources:
            if source.url == wanted:
                return source
        return None


def _config_sources(config: dict[str, Any]) -> tuple[DeclaredSource, ...]:
    raw = config.get("sources")
    out: list[DeclaredSource] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            out.append(DeclaredSource(url=url, category=str(item.get("category") or "").strip()))
    return tuple(out)


async def resolve_discovery_source_provider(
    binding: Binding,
) -> ResolvedCapabilityProvider | Unavailable:
    if binding.provider_name and binding.provider_name != "discovery-source":
        return _unavailable(
            binding, f"Binding pins unsupported discovery provider {binding.provider_name!r}"
        )
    sources = _config_sources(binding.config)
    if not sources:
        return _unavailable(
            binding,
            "discovery.source Binding config requires a non-empty `sources` allowlist "
            "of {url, category} entries",
        )
    return DiscoverySourceProvider(sources=sources)


def _unavailable(binding: Binding, reason: str) -> Unavailable:
    return Unavailable(slot=binding.capability, reason=reason)


async def execute_discovery_source(
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    """Fetch one declared source and return its entries with provenance."""
    if not isinstance(provider, DiscoverySourceProvider):
        raise TypeError(f"discovery.source Invocation received foreign provider {type(provider)!r}")
    if not isinstance(request, DiscoverySourceRequest):
        raise TypeError(f"discovery.source Invocation received foreign request {type(request)!r}")
    declared = provider.declared(request.url)
    if declared is None:
        # The Binding is the allow/deny control; a URL it never declared is
        # refused before any connection, exactly like an out-of-scope Binding.
        raise PermissionError(
            f"source {request.url!r} is not on the Binding's declared sources allowlist"
        )

    try:
        async with shared_client(timeout=timeout_s) as client:
            response = await client.get(
                request.url,
                headers={"Accept": "application/rss+xml, application/atom+xml, application/json"},
                follow_redirects=True,
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"source unreachable, no effect occurred: {exc}") from exc
    except SSRFBlockedError as exc:
        # Redirects are followed (a feed that moved to https is still the
        # declared source), so a hostile hop is stopped by the outbound
        # policy at the transport — the shared client re-validates every
        # redirect hop, exactly like the browser tool's per-hop guard. A
        # refused hop means nothing was fetched into entries: read-only
        # GETs, no external effect, so the honest classification is the
        # same one an unreachable source gets, not an UNKNOWN failure.
        raise EffectNotApplied(
            f"source fetch refused by the outbound policy, no effect occurred: {exc}"
        ) from exc
    if response.status_code >= 400:
        raise DiscoverySourceHttpError(
            f"discovery_source_http_error status={response.status_code}", response.status_code
        )
    content_type = response.headers.get("content-type", "")
    body = response.text
    entries = _parse_feed(request.url, content_type, body, request.max_entries)
    return {
        "source_url": request.url,
        "category": declared.category,
        "fetched_at": datetime.now(UTC).isoformat(),
        "entries": entries,
        "count": len(entries),
    }


# ---------------------------------------------------------------------------
# Feed parsing — best-effort, honest: an unparseable entry is skipped, an
# unparseable feed is a loud error, and only explicit fields are trusted.
# ---------------------------------------------------------------------------


def _parse_feed(
    source_url: str, content_type: str, body: str, max_entries: int
) -> list[dict[str, str]]:
    stripped = body.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json_feed(source_url, body, max_entries)
    if "<feed" in body[:2000] or "atom" in content_type:
        return _parse_atom(source_url, body, max_entries)
    return _parse_rss(source_url, body, max_entries)


def _entry(
    source_url: str,
    *,
    entry_id: str,
    url: str,
    title: str,
    summary: str,
    published_at: str,
    expires_at: str = "",
    category: str = "",
) -> dict[str, str]:
    values: dict[str, str] = {
        "id": entry_id or url or title,
        "url": url,
        "title": title,
        "summary": summary[:_MAX_SUMMARY_CHARS],
        "published_at": published_at,
        "expires_at": expires_at,
        "category": category,
        "source_url": source_url,
    }
    return {key: value for key, value in values.items() if value}


def _local(tag: str) -> str:
    """An element's tag without its XML namespace, so Atom's default
    namespace cannot hide entries from the walk."""
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element.iter() if _local(child.tag) == name]


# The stdlib ET import is suppressed inline (nosec/nosemgrep on its line) because it
# supplies only the ET.Element alias and the ParseError type; every parse runs through
# defusedxml's SafeET.fromstring, which refuses entity expansion instead of resolving it
# (python.lang.security.use-defused-xml fires on the import statement itself).


def _parse_rss(source_url: str, body: str, max_entries: int) -> list[dict[str, str]]:
    try:
        root = SafeET.fromstring(body)
    except (ET.ParseError, DefusedXmlException) as exc:
        # A defused refusal (entity/DTD declarations, remote references) is
        # the parser doing its job on remote content — refused loudly, never
        # expanded, and classified exactly like an unparseable feed.
        raise RuntimeError(f"source returned unparseable RSS: {exc}") from exc
    out: list[dict[str, str]] = []
    for item in _children(root, "item"):
        if len(out) >= max_entries:
            break
        link = _direct_text(item, "link")
        out.append(
            _entry(
                source_url,
                entry_id=_direct_text(item, "guid"),
                url=link,
                title=_direct_text(item, "title"),
                summary=_direct_text(item, "description"),
                published_at=_direct_text(item, "pubDate", "date"),
                category=_direct_text(item, "category"),
            )
        )
    return out


def _direct_text(element: ET.Element, *paths: str) -> str:
    """Text of the element's own children named ``path`` (not descendants).

    RSS ``item`` shapes nest flat, but a ``description`` can wrap HTML whose
    tags reuse item names — reading only direct children keeps one entry's
    fields from bleeding into another's.
    """
    for path in paths:
        for child in element:
            if _local(child.tag) == path and child.text and child.text.strip():
                return child.text.strip()
    return ""


def _parse_atom(source_url: str, body: str, max_entries: int) -> list[dict[str, str]]:
    try:
        root = SafeET.fromstring(body)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise RuntimeError(f"source returned unparseable Atom: {exc}") from exc
    out: list[dict[str, str]] = []
    for item in _children(root, "entry"):
        if len(out) >= max_entries:
            break
        link = ""
        for child in item:
            if _local(child.tag) == "link":
                link = str(child.get("href") or "").strip()
                break
        out.append(
            _entry(
                source_url,
                entry_id=_direct_text(item, "id"),
                url=link,
                title=_direct_text(item, "title"),
                summary=_direct_text(item, "summary", "content"),
                published_at=_direct_text(item, "published", "updated"),
            )
        )
    return out


def _json_items(payload: Any) -> list[Any]:
    """The feed's entry list, or the honest refusal of an unknown shape."""
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return list(payload["items"])
    raise RuntimeError("source JSON is neither a list nor an object with `items`")


# Each JSON entry field: output key, source keys tried in order (first
# truthy value wins, exactly the `or`-chain this table replaces), and
# whether the value is stripped.
_JSON_FIELD_SOURCES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("entry_id", ("id", "guid"), False),
    ("url", ("url", "link"), True),
    ("title", ("title",), True),
    ("summary", ("summary", "description"), True),
    ("published_at", ("published_at", "published"), True),
    ("expires_at", ("expires_at", "deadline"), True),
    ("category", ("category",), True),
)


def _json_field(item: dict[str, Any], sources: tuple[str, ...], *, strip: bool) -> str:
    value: Any = ""
    for key in sources:
        value = item.get(key)
        if value:
            break
    text = str(value or "")
    return text.strip() if strip else text


def _json_entry(source_url: str, item: Any) -> dict[str, str] | None:
    """One JSON-feed entry; non-dict rows are skipped, not fatal.

    An expiry is honoured only as explicit source data; a JSON feed that
    declares one per item may pass it, nothing synthesizes it.
    """
    if not isinstance(item, dict):
        return None
    fields = {
        key: _json_field(item, sources, strip=strip) for key, sources, strip in _JSON_FIELD_SOURCES
    }
    return _entry(source_url, **fields)


def _parse_json_feed(source_url: str, body: str, max_entries: int) -> list[dict[str, str]]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"source returned unparseable JSON: {exc}") from exc
    out: list[dict[str, str]] = []
    for item in _json_items(payload):
        if len(out) >= max_entries:
            break
        row = _json_entry(source_url, item)
        if row is not None:
            out.append(row)
    return out


__all__ = [
    "DISCOVERY_SOURCE_CAPABILITY",
    "DeclaredSource",
    "DiscoverySourceHttpError",
    "DiscoverySourceProvider",
    "DiscoverySourceRequest",
    "execute_discovery_source",
    "resolve_discovery_source_provider",
]
