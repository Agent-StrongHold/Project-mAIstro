"""Coverage for skills/marketplace.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.skills.marketplace import (
    HTTPResponse,
    SkillMarketplace,
    _block_literal_ip,
    _block_resolved_ip,
    _block_ssrf,
    _is_blocked_ip,
)
from maistro.skills.registry import InMemorySkillRegistry

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


def test_is_blocked_ip_flags_private_address() -> None:
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address("10.0.0.5")) is True


def test_is_blocked_ip_flags_loopback_address() -> None:
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address("127.0.0.1")) is True


def test_is_blocked_ip_allows_public_address() -> None:
    import ipaddress

    assert _is_blocked_ip(ipaddress.ip_address("8.8.8.8")) is False


def test_is_blocked_ip_returns_false_for_non_ip_object() -> None:
    assert _is_blocked_ip("not-an-ip") is False


def test_block_literal_ip_raises_for_blocked_ip() -> None:
    with pytest.raises(ValueError, match="Blocked"):
        _block_literal_ip("127.0.0.1", "http://127.0.0.1/skill.md")


def test_block_literal_ip_returns_true_for_allowed_public_ip() -> None:
    assert _block_literal_ip("8.8.8.8", "http://8.8.8.8/skill.md") is True


def test_block_literal_ip_returns_false_for_non_ip_hostname() -> None:
    assert _block_literal_ip("example.com", "http://example.com/skill.md") is False


def test_block_resolved_ip_returns_silently_on_dns_failure() -> None:
    _block_resolved_ip(
        "this-host-does-not-exist.invalid", "http://this-host-does-not-exist.invalid/x"
    )


def test_block_ssrf_raises_for_malformed_url() -> None:
    with pytest.raises(ValueError, match="malformed URL"):
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
    with pytest.raises(ValueError, match="unsupported marketplace URL"):
        _block_ssrf(url)


def test_block_ssrf_allows_literal_public_ip_url() -> None:
    _block_ssrf("https://8.8.8.8/skill.md")


def test_block_resolved_ip_raises_for_blocked_resolved_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="resolves to private/internal"):
        _block_resolved_ip("evil.example.com", "http://evil.example.com/x")


def test_block_resolved_ip_skips_unparseable_address(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("not-an-ip", 0))],
    )
    _block_resolved_ip("weird.example.com", "http://weird.example.com/x")


def test_block_resolved_ip_allows_public_resolved_address(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 0))],
    )
    _block_resolved_ip("example.com", "http://example.com/x")


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
