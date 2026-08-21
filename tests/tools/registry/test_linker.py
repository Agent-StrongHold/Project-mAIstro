"""Cross-repo link checker tests.

Uses `FakeResolver` to avoid network calls; covers the resolver
protocol, multi-field traversal, and dangling-reference detection.
GitHubResolver is exercised by integration when CI runs `lint`
against the live repo set; no unit test mocks httpx here.
"""

from __future__ import annotations

from typing import Any

from maistro_registry.linker import (
    FakeResolver,
    LinkResult,
    check_links,
)
from maistro_registry.schema import FrontMatter


def _make_fm(
    item_id: str,
    *,
    repo: str = "maistro-engine",
    substrate: list[str] | None = None,
    related: list[str] | None = None,
    supersedes: list[str] | None = None,
) -> FrontMatter:
    payload: dict[str, Any] = {
        "id": item_id,
        "title": item_id,
        "repo": repo,
        "kind": "adr",
        "status": "Accepted",
        "created": "2026-05-07",
        "substrate": substrate or [],
        "implements": [],
        "related": related or [],
        "supersedes": supersedes or [],
        "blocks": [],
        "blocked-by": [],
        "contracts": [],
        "tests": [],
        "layer": "Foundation",
        "owners": ["@BlakeMatthews-dev"],
    }
    return FrontMatter.model_validate(payload)


def test_empty_input_returns_empty_results() -> None:
    resolver = FakeResolver()
    assert check_links([], resolver) == []


def test_single_resolved_ref() -> None:
    fm = _make_fm("ADR-030", substrate=["maistro-engine#ADR-019"])
    resolver = FakeResolver(known={"maistro-engine": {"ADR-019"}})
    results = check_links([fm], resolver)
    assert len(results) == 1
    assert results[0].resolved is True
    assert results[0].source == "maistro-engine#ADR-030"
    assert results[0].field_name == "substrate"
    assert results[0].target == "maistro-engine#ADR-019"


def test_dangling_ref_flagged() -> None:
    fm = _make_fm("ADR-030", substrate=["maistro-engine#ADR-999"])
    resolver = FakeResolver(known={"maistro-engine": {"ADR-019"}})
    results = check_links([fm], resolver)
    assert len(results) == 1
    assert results[0].resolved is False


def test_multiple_fields_each_checked() -> None:
    fm = _make_fm(
        "ADR-030",
        substrate=["maistro-engine#ADR-019"],
        related=["maistro-engine#ADR-020", "maistro-engine#ADR-021"],
        supersedes=["maistro-engine#ADR-022"],
    )
    resolver = FakeResolver(known={"maistro-engine": {"ADR-019", "ADR-020", "ADR-021", "ADR-022"}})
    results = check_links([fm], resolver)
    assert len(results) == 4
    assert all(r.resolved for r in results)


def test_unknown_repo_not_resolved() -> None:
    fm = _make_fm("ADR-030", substrate=["maistro-engine#ADR-019"])
    resolver = FakeResolver(known={})
    results = check_links([fm], resolver)
    assert len(results) == 1
    assert results[0].resolved is False


def test_link_result_render_resolved() -> None:
    lr = LinkResult(
        source="maistro-engine#ADR-030",
        field_name="substrate",
        target="maistro-engine#ADR-019",
        resolved=True,
    )
    rendered = lr.render()
    assert "OK" in rendered


def test_link_result_render_dangling() -> None:
    lr = LinkResult(
        source="maistro-engine#ADR-030",
        field_name="substrate",
        target="maistro-engine#ADR-999",
        resolved=False,
    )
    rendered = lr.render()
    assert "DANGLING" in rendered


def test_fake_resolver_is_isolated_per_repo() -> None:
    # ADR-001 exists in maistro-engine but not under some other repo key
    resolver = FakeResolver(known={"maistro-engine": {"ADR-001"}})
    assert resolver.resolve("maistro-engine", "ADR-001") is True
    assert resolver.resolve("other-repo", "ADR-001") is False
