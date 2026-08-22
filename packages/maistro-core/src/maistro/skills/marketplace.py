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

_VALID_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,50}$")


def _block_ssrf(url: str) -> None:
    """Block SSRF targets, in `ValueError` terms.

    The check itself is `maistro.security.ssrf` — there used to be a second
    implementation here, which is how the two drifted apart (#154). What stays
    is the exception type: `install()` documents a `ValueError` contract and
    `import_pipeline` turns one into a "blocked" verdict rather than an
    exception, so translating at this boundary keeps both true without another
    copy of the logic.
    """
    from maistro.security.ssrf import SSRFBlockedError, validate_outbound_url

    try:
        validate_outbound_url(url)
    except SSRFBlockedError as exc:
        msg = f"Blocked: URL targets private/metadata network: {url}"
        raise ValueError(msg) from exc


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
