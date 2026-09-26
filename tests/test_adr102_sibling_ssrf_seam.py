"""ADR-102 acceptance proofs: the sibling SSRF guard's two non-census criteria.

The census halves of ADR-102 (AC-1, AC-4) are proven inside the
`tests/test_check_security_inventory.py` gate suite they belong to. The two
criteria that census cannot express live here:

- **AC-2** — the registry linker's caller-influenced fetch is restricted to the
  pinned `https://api.github.com` origin before any client exists, and the
  fetch itself rides `maistro.http.sync_client`'s guarded transports. This is
  the highest-risk site the ticket names: repository and artifact metadata
  influence the requested path, so the origin must be a fixed policy decision.
- **AC-3** — the dependency decision is declared in package metadata: registry,
  bootstrap and evolve name `maistro-core>=0.9.0` instead of vendoring a second
  guard. ADR text alone cannot prove the packaging half of that decision.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest

from maistro.http import sync_client as real_sync_client
from maistro_registry import linker as linker_module
from maistro_registry.linker import GitHubResolver, _github_contents_url

ROOT = Path(__file__).resolve().parents[1]

#: The three packages ADR-102 moved onto the central seam as an explicit
#: dependency decision. `maistro-rsi` and `maistro-design` already declared
#: core, so they are not part of this criterion.
DEPENDENCY_PACKAGES = (
    "maistro-registry",
    "maistro-bootstrap",
    "maistro-evolve",
)


@pytest.mark.ac("ADR-102/AC-2")
class TestRegistryLinkerOriginPin:
    def test_hostile_metadata_cannot_move_scheme_or_origin(self) -> None:
        """Owner/repo values only ever become quoted path segments.

        Every hostile spelling a caller could inject — separators, scheme
        prefixes, credentials, whitespace — must leave the URL on the pinned
        HTTPS origin, because the scheme and host are constants, not inputs.
        """
        for owner, repo in (
            ("../../etc", "passwd"),
            ("https://evil.test", "repo"),
            ("x@evil.test", "repo"),
            ("owner", "//evil.test/path"),
            ("owner", "repo#frag"),
            ("..%2F..", "repo"),
        ):
            url = _github_contents_url(owner, repo, "docs/adr")
            assert url.startswith("https://api.github.com/repos/"), (owner, repo, url)
            parsed = httpx.URL(url)
            assert parsed.scheme == "https"
            assert parsed.host == "api.github.com"

    def test_path_segments_are_quoted(self) -> None:
        url = _github_contents_url("octocat/../evil", "hello world", "docs/adr")
        assert "/repos/octocat%2F..%2Fevil/hello%20world/contents/" in url

    def test_resolver_fetches_through_the_guarded_sync_seam(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`GitHubResolver` borrows the central guarded client, not its own.

        The module-level `sync_client` name is rebound to the REAL seam with a
        mock transport injected, so the code under test builds the guarded
        client exactly as production does and the observed request is the one
        the pinned-URL builder produced.
        """
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200,
                json=[
                    {"name": "ADR-030-link-checking.md"},
                    {"name": "SPEC-177.md"},
                    {"name": "README.txt"},
                ],
            )

        def guarded_mock(**kwargs: object) -> httpx.Client:
            return real_sync_client(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(linker_module, "sync_client", guarded_mock)

        resolver = GitHubResolver(repo_owners={"some-repo": "some-owner"})
        assert resolver.resolve("some-repo", "ADR-030") is True
        assert resolver.resolve("some-repo", "SPEC-177") is True
        assert resolver.resolve("some-repo", "ADR-999") is False

        assert seen, "the resolver never issued the directory lookup"
        for url in seen:
            assert url.startswith("https://api.github.com/"), url


@pytest.mark.ac("ADR-102/AC-3")
class TestDependencyDeclaredInMetadata:
    @pytest.mark.parametrize("package", DEPENDENCY_PACKAGES)
    def test_package_declares_the_core_guard_as_a_dependency(self, package: str) -> None:
        pyproject = ROOT / "packages" / package / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dependencies = " ".join(data["project"]["dependencies"])
        assert "maistro-core>=" in dependencies, f"{package} must declare maistro-core"
