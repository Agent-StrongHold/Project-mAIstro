"""Skill marketplace: search, install, uninstall community skills.

Fetches SKILL.md files from URLs, runs security scanning, and installs
to the community directory with T2 trust tier by default.

Uses an injectable HTTP client protocol for testability.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.skills.fixer import fix_content
from maistro.skills.parser import parse_skill_file, security_scan
from maistro.types.skill import SkillDefinition, SkillMetadata

if TYPE_CHECKING:
    from maistro.skills.registry import InMemorySkillRegistry

logger = logging.getLogger("maistro.skills.marketplace")

_BLOCKED_HOSTNAME_PREFIXES = (
    "metadata.",
    "localhost",
)
_VALID_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,50}$")


def _is_blocked_ip(addr: object) -> bool:
    """Check if an IP address object targets a private/internal network."""
    import ipaddress

    if not isinstance(addr, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return False
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )


def _block_literal_ip(hostname: str, url: str) -> bool:
    """Block ``hostname`` if it is a literal blocked IP. Returns True if it was a
    literal IP (blocked or allowed) so the caller can stop; False if not an IP."""
    import ipaddress

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    if _is_blocked_ip(addr):
        msg = f"Blocked: URL targets private/metadata network ({addr}): {url}"
        raise ValueError(msg)
    return True


def _block_resolved_ip(hostname: str, url: str) -> None:
    """Resolve ``hostname`` via DNS and block if any address is private/internal."""
    import ipaddress
    import socket

    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return

    for *_meta, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            resolved_addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(resolved_addr):
            msg = (
                f"Blocked: hostname '{hostname}' resolves to private/internal "
                f"address ({resolved_addr}): {url}"
            )
            raise ValueError(msg)


def _block_ssrf(url: str) -> None:
    """Block server-side request forgery via private/metadata URLs."""
    from urllib.parse import urlparse

    url_lower = url.lower()

    try:
        parsed = urlparse(url_lower)
    except Exception:
        msg = f"Blocked: malformed URL: {url}"
        raise ValueError(msg) from None

    hostname = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        msg = f"Blocked: unsupported marketplace URL: {url}"
        raise ValueError(msg)

    for prefix in _BLOCKED_HOSTNAME_PREFIXES:
        if hostname.startswith(prefix) or hostname == prefix:
            msg = f"Blocked: URL targets private/metadata network: {url}"
            raise ValueError(msg)

    if _block_literal_ip(hostname, url):
        return

    _block_resolved_ip(hostname, url)


@runtime_checkable
class HTTPClient(Protocol):
    """Minimal HTTP client for marketplace fetches."""

    async def get(self, url: str) -> HTTPResponse: ...


class HTTPResponse:
    """Simple HTTP response wrapper."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class SkillMarketplace:
    """Community skill search and installation."""

    def __init__(
        self,
        http_client: HTTPClient,
        skills_dir: Path,
        registry: InMemorySkillRegistry,
    ) -> None:
        self._http = http_client
        self._skills_dir = skills_dir / "community"
        self._registry = registry

    async def search(self, query: str, max_results: int = 10) -> list[SkillMetadata]:
        """Search for skills. Currently returns empty — marketplace integration TBD."""
        return []

    async def install(
        self,
        url: str,
        trust_tier: str = "t2",
    ) -> SkillDefinition:
        """Install a skill from a URL.

        Raises ValueError on fetch failure, parse failure, or security rejection.
        """
        _block_ssrf(url)

        try:
            resp = await self._http.get(url)
        except Exception as e:
            msg = f"Failed to fetch skill from {url}: {e}"
            raise ValueError(msg) from e

        if resp.status_code != 200:
            msg = f"Skill fetch returned {resp.status_code} from {url}"
            raise ValueError(msg)

        content = resp.text

        safe, findings = security_scan(content)
        if not safe:
            msg = f"Skill rejected by security scan: {', '.join(findings)}"
            raise ValueError(msg)

        # Salvage pass (same primitive the ADR-083 import pipeline composes):
        # even content that clears the raw scan can carry fixable issues
        # (hidden unicode markers, shell commands, a self-declared trust tier
        # claim). Re-scan the salvaged output before trusting it, and persist
        # *that* content -- never the untouched fetched text.
        fixed, fixes, unfixable = fix_content(content)
        if unfixable:
            msg = f"Skill rejected after security repair: {', '.join(unfixable)}"
            raise ValueError(msg)

        safe_after, residual = security_scan(fixed)
        if not safe_after:
            critical = [f for f in residual if f.startswith("CRITICAL:")]
            msg = f"Skill rejected by security scan after repair: {', '.join(critical)}"
            raise ValueError(msg)

        skill = parse_skill_file(fixed, source=url)
        if skill is None:
            msg = f"Failed to parse skill from {url}"
            raise ValueError(msg)

        skill = SkillDefinition(
            name=skill.name,
            description=skill.description,
            groups=skill.groups,
            parameters=skill.parameters,
            endpoint=skill.endpoint,
            auth_key_env=skill.auth_key_env,
            system_prompt=skill.system_prompt,
            source=url,
            trust_tier=trust_tier,
        )

        self._skills_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._skills_dir / f"{skill.name}.md"
        filepath.write_text(fixed, encoding="utf-8")

        self._registry.register(skill)

        logger.info(
            "Installed skill '%s' from %s (tier=%s, warnings=%d, fixes=%d)",
            skill.name,
            url,
            trust_tier,
            len([f for f in findings if f.startswith("WARNING:")]),
            len(fixes),
        )

        return skill

    def uninstall(self, name: str) -> None:
        """Uninstall a community skill by name."""
        if not _VALID_SKILL_NAME_RE.fullmatch(name):
            msg = f"Invalid community skill name: {name!r}"
            raise ValueError(msg)
        root = self._skills_dir.resolve()
        filepath = (root / f"{name}.md").resolve()
        try:
            filepath.relative_to(root)
        except ValueError:
            msg = f"Invalid community skill path for name: {name!r}"
            raise ValueError(msg) from None
        if not filepath.exists():
            msg = f"Community skill '{name}' not found"
            raise ValueError(msg)

        filepath.unlink()
        self._registry.delete(name)
        logger.info("Uninstalled skill: %s", name)
