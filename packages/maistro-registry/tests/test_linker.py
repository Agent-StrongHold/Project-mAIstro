from __future__ import annotations

from typing import Any

import pytest

from maistro_registry import linker


class _Response:
    status_code = 200

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.urls: list[str] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _Response:
        del kwargs
        self.urls.append(url)
        return self.response


def test_github_url_pins_https_origin_and_quotes_path_segments() -> None:
    url = linker._github_contents_url("owner/with-slash", "repo#name", "docs/adr")

    assert url == ("https://api.github.com/repos/owner%2Fwith-slash/repo%23name/contents/docs/adr")
    parsed = linker.urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.hostname == "api.github.com"


@pytest.mark.parametrize(
    ("origin",),
    [
        ("http://api.github.com",),
        ("https://evil.test",),
    ],
)
def test_github_url_builder_refuses_a_drifted_pin(monkeypatch, origin: str) -> None:
    """The scheme/host check is load-bearing, not decorative.

    If the pinned constant ever drifts — a downgraded scheme or a foreign
    host — the builder must refuse rather than emit the URL. The validator is
    what makes the pin a policy decision instead of a string.
    """
    monkeypatch.setattr(linker, "_GITHUB_API_ORIGIN", origin)
    with pytest.raises(ValueError, match="HTTPS origin"):
        linker._github_contents_url("owner", "repo", "docs/adr")


def test_github_resolver_uses_the_guarded_client_for_both_directories(
    monkeypatch,
) -> None:
    response = _Response([{"name": "ADR-102-central.md"}])
    client = _Client(response)
    monkeypatch.setattr(linker, "sync_client", lambda **kwargs: client)

    resolver = linker.GitHubResolver(repo_owners={"engine": "owner"})

    assert resolver.resolve("engine", "ADR-102") is True
    assert client.urls == [
        "https://api.github.com/repos/owner/engine/contents/docs/adr",
        "https://api.github.com/repos/owner/engine/contents/docs/specs",
    ]


def test_github_resolver_ignores_markdown_files_that_name_no_versioned_id(
    monkeypatch,
) -> None:
    """A directory listing is untrusted input: `.md` files whose stems carry no
    `ADR-NNN`/`SPEC-NNNNNN-hhhh` identity are skipped, not misparsed into ids."""
    response = _Response(
        [
            {"name": "README.md"},
            {"name": "ADR-102-central.md"},
            {"name": "notes.md"},
            {"name": "SPEC-177-hyperagent-graph-execution.md"},
            {"name": "ADR-not-an-id.md"},
        ]
    )
    client = _Client(response)
    monkeypatch.setattr(linker, "sync_client", lambda **kwargs: client)

    resolver = linker.GitHubResolver(repo_owners={"engine": "owner"})

    assert resolver.resolve("engine", "ADR-102") is True
    assert resolver.resolve("engine", "SPEC-177") is True
    assert resolver.resolve("engine", "README") is False
    assert resolver.resolve("engine", "notes") is False
    assert resolver.resolve("engine", "ADR-not-an-id") is False
