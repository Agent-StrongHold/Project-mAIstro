from __future__ import annotations

from typing import Any

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
