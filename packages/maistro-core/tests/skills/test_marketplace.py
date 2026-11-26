"""Coverage for skills/marketplace.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.skills.marketplace import (
    HTTPResponse,
    SkillMarketplace,
    _block_ssrf,
)
from maistro.skills.registry import InMemorySkillRegistry
from maistro.types.skill import SkillDefinition

VALID_SKILL_MD = """---
name: my_skill
description: Does a thing
parameters:
  type: object
  properties: {}
---
Body text here.
"""

DANGEROUS_SKILL_MD = """---
name: bad_skill
description: Bad
parameters:
  type: object
  properties: {}
---
exec(user_input)
"""

UNPARSEABLE_SKILL_MD = "no frontmatter here"

# A community document that names its own trust tier. The tier belongs to the
# host: a document cannot promote itself.
SELF_DECLARING_SKILL_MD = """---
name: my_skill
description: Does a thing
trust_tier: t0
parameters:
  type: object
  properties: {}
---
Body text here.

A second line, so the salvaged document still has a meaningful body.
"""


class _FakeHttpClient:
    def __init__(
        self, response: HTTPResponse | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.urls: list[str] = []

    async def get(self, url: str) -> HTTPResponse:
        self.urls.append(url)
        if self._error:
            raise self._error
        assert self._response is not None
        return self._response


# The internals of the second SSRF implementation used to be unit-tested here:
# `_is_blocked_ip`, `_block_literal_ip`, `_block_resolved_ip`. That
# implementation is gone (#154) and `maistro.security.ssrf` is the only one
# left, so those cases live in `tests/security/test_ssrf.py` — which covers
# strictly more, including the DNS-failure case this file used to assert
# *passed*. What stays here is the boundary this module actually owns: that
# marketplace still refuses in `ValueError` terms, because `install()` documents
# that contract and `import_pipeline` turns one into a "blocked" verdict.


def test_block_ssrf_raises_for_malformed_url() -> None:
    with pytest.raises(ValueError, match="private/metadata network"):
        _block_ssrf("http://[::1")


def test_block_ssrf_raises_for_metadata_hostname() -> None:
    with pytest.raises(ValueError, match="private/metadata network"):
        _block_ssrf("http://metadata.google.internal/skill.md")


def test_block_ssrf_raises_for_localhost() -> None:
    with pytest.raises(ValueError, match="private/metadata network"):
        _block_ssrf("http://localhost/skill.md")


def test_block_ssrf_raises_for_literal_private_ip() -> None:
    with pytest.raises(ValueError, match="Blocked"):
        _block_ssrf("http://127.0.0.1/skill.md")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/skill.md",
        "ftp://example.com/skill.md",
        "//example.com/skill.md",
        "not-a-url",
    ],
)
def test_block_ssrf_rejects_unsupported_or_schemeless_urls(url: str) -> None:
    with pytest.raises(ValueError, match="private/metadata network"):
        _block_ssrf(url)


def test_block_ssrf_allows_literal_public_ip_url() -> None:
    _block_ssrf("https://8.8.8.8/skill.md")


def test_block_ssrf_allows_public_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 0))],
    )
    _block_ssrf("https://example.com/skill.md")


@pytest.fixture
def registry() -> InMemorySkillRegistry:
    return InMemorySkillRegistry()


@pytest.fixture
def marketplace(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> tuple[SkillMarketplace, _FakeHttpClient]:
    client = _FakeHttpClient()
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    return mp, client


async def test_search_returns_empty_list(
    marketplace: tuple[SkillMarketplace, _FakeHttpClient],
) -> None:
    mp, _ = marketplace
    assert await mp.search("anything") == []


async def test_install_raises_on_ssrf_blocked_url(
    marketplace: tuple[SkillMarketplace, _FakeHttpClient],
) -> None:
    mp, _ = marketplace
    with pytest.raises(ValueError, match="private/metadata network"):
        await mp.install("http://localhost/skill.md")


async def test_install_raises_on_fetch_exception(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(error=RuntimeError("connection refused"))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    with pytest.raises(ValueError, match="Failed to fetch skill"):
        await mp.install("https://example.com/skill.md")


async def test_install_raises_on_non_200_status(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(404, ""))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    with pytest.raises(ValueError, match="returned 404"):
        await mp.install("https://example.com/skill.md")


async def test_install_raises_on_security_scan_rejection(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, DANGEROUS_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    with pytest.raises(ValueError, match="rejected by security scan"):
        await mp.install("https://example.com/skill.md")


async def test_install_raises_on_parse_failure(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, UNPARSEABLE_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    with pytest.raises(ValueError, match="Failed to parse skill"):
        await mp.install("https://example.com/skill.md")


async def test_install_success_writes_file_and_registers_skill(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, VALID_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    skill = await mp.install("https://example.com/skill.md", trust_tier="t3")

    assert skill.name == "my_skill"
    assert skill.source == "https://example.com/skill.md"
    assert skill.trust_tier == "t3"

    filepath = tmp_path / "community" / "my_skill.md"
    assert filepath.exists()
    assert filepath.read_text(encoding="utf-8") == VALID_SKILL_MD

    assert registry.get("my_skill") is not None


def test_uninstall_raises_when_skill_not_found(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient()
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    with pytest.raises(ValueError, match="not found"):
        mp.uninstall("ghost")


@pytest.mark.parametrize("name", ["../victim", "/tmp/victim", "bad-name", "", "a" * 52])
def test_uninstall_rejects_path_like_or_invalid_skill_names(
    tmp_path: Path, registry: InMemorySkillRegistry, name: str
) -> None:
    community = tmp_path / "community"
    community.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("do not delete", encoding="utf-8")

    client = _FakeHttpClient()
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)

    with pytest.raises(ValueError, match="Invalid community skill name"):
        mp.uninstall(name)
    assert victim.read_text(encoding="utf-8") == "do not delete"


async def test_uninstall_removes_file_and_deletes_from_registry(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, VALID_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    await mp.install("https://example.com/skill.md")

    filepath = tmp_path / "community" / "my_skill.md"
    assert filepath.exists()

    mp.uninstall("my_skill")

    assert not filepath.exists()
    assert registry.get("my_skill") is None


# ------------------------------------------------- the governed install gate


async def test_install_honors_the_host_supplied_tier(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    # The tier is the host's decision about the installed skill; the fetched
    # document never names its own.
    client = _FakeHttpClient(response=HTTPResponse(200, VALID_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)

    skill = await mp.install("https://example.com/skill.md", trust_tier="t1")

    assert skill.trust_tier == "t1"
    stored = registry.get("my_skill")
    assert stored is not None
    assert stored.trust_tier == "t1"


async def test_install_of_a_tier_the_host_does_not_know_lands_on_the_unvetted_floor(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, VALID_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)

    skill = await mp.install("https://example.com/skill.md", trust_tier="t9")

    assert skill.trust_tier == "t3"


async def test_install_ignores_a_tier_the_document_claims_for_itself(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, SELF_DECLARING_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)

    skill = await mp.install("https://example.com/skill.md", trust_tier="t3")

    # The document asks for t0; only the host's tier counts.
    assert skill.trust_tier == "t3"
    stored = registry.get("my_skill")
    assert stored is not None
    assert stored.trust_tier == "t3"


async def test_install_refuses_to_overwrite_a_symlinked_skill_file(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    client = _FakeHttpClient(response=HTTPResponse(200, VALID_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)
    community = tmp_path / "community"
    community.mkdir(parents=True, exist_ok=True)
    (community / "my_skill.md").symlink_to(tmp_path / "elsewhere.md")

    with pytest.raises(ValueError, match="Refusing to overwrite symlink"):
        await mp.install("https://example.com/skill.md")
    assert registry.get("my_skill") is None


async def test_install_is_refused_when_the_registry_rejects_the_trust_change(
    tmp_path: Path, registry: InMemorySkillRegistry
) -> None:
    # The host already holds this skill at the unvetted floor. A community
    # install that claims a more trusted tier is a promotion nobody granted:
    # the registry refuses it and nothing reaches the disk.
    registry.register(
        SkillDefinition(
            name="my_skill",
            description="Already here",
            trust_tier="t3",
            source="host",
        )
    )
    client = _FakeHttpClient(response=HTTPResponse(200, VALID_SKILL_MD))
    mp = SkillMarketplace(http_client=client, skills_dir=tmp_path, registry=registry)

    with pytest.raises(ValueError, match="Skill trust policy rejected registration"):
        await mp.install("https://example.com/skill.md", trust_tier="t2")
    assert not (tmp_path / "community" / "my_skill.md").exists()
