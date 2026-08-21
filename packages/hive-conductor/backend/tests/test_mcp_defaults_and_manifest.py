"""Boy Scout coverage: mcp_defaults (55%) + mcp_manifest_loader (55%)."""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# --- mcp_defaults --------------------------------------------------------


def test_is_atlassian_rovo_url_positive() -> None:
    from services.mcp_defaults import is_atlassian_rovo_url

    assert is_atlassian_rovo_url("https://mcp.atlassian.com/v1/mcp/authv2") is True
    assert is_atlassian_rovo_url("http://mcp.atlassian.com") is True


def test_is_atlassian_rovo_url_negative() -> None:
    from services.mcp_defaults import is_atlassian_rovo_url

    assert is_atlassian_rovo_url("") is False
    assert is_atlassian_rovo_url("https://example.com") is False
    assert is_atlassian_rovo_url(None) is False  # type: ignore[arg-type]


def test_atlassian_rovo_server_shape() -> None:
    from services.mcp_defaults import (
        ATLASSIAN_ROVO_SERVER_ID,
        ATLASSIAN_ROVO_TOOLS,
        atlassian_rovo_server,
    )

    s = atlassian_rovo_server()
    assert s.id == ATLASSIAN_ROVO_SERVER_ID
    assert s.tools_count == len(ATLASSIAN_ROVO_TOOLS)
    assert "jira" in s.capabilities


def test_filesystem_local_server_shape() -> None:
    from services.mcp_defaults import (
        FILESYSTEM_SERVER_ID,
        FILESYSTEM_TOOLS,
        filesystem_local_server,
    )

    s = filesystem_local_server()
    assert s.id == FILESYSTEM_SERVER_ID
    assert s.tools_count == len(FILESYSTEM_TOOLS)
    assert s.status == "disconnected"


def test_atlassian_rovo_tools_count_and_ids() -> None:
    from services.mcp_defaults import ATLASSIAN_ROVO_TOOLS, atlassian_rovo_tools

    tools = atlassian_rovo_tools()
    assert len(tools) == len(ATLASSIAN_ROVO_TOOLS)
    # Stable id pattern
    assert tools[0].id == "rovo-t-1"
    assert tools[-1].id == f"rovo-t-{len(tools)}"


def test_filesystem_local_tools_count_and_ids() -> None:
    from services.mcp_defaults import FILESYSTEM_TOOLS, filesystem_local_tools

    tools = filesystem_local_tools()
    assert len(tools) == len(FILESYSTEM_TOOLS)
    assert tools[0].id == "fs-t-1"


# --- merge_manifest_catalog --------------------------------------------


def test_merge_manifest_catalog_adds_new_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest with a NEW server id appears in the merged output."""
    from services.mcp_defaults import (
        merge_manifest_catalog,
        platform_mcp_catalog,
    )

    manifest = {
        "id": "mcp-test-extra",
        "name": "Test Extra",
        "description": "synthetic",
        "url": "http://x.example",
        "version": "1.0",
        "capabilities": ["test"],
        "tools": [
            {"name": "do_thing", "description": "does", "category": "test"},
        ],
    }
    (tmp_path / "extra.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))

    servers, tools = platform_mcp_catalog()
    merged_servers, merged_tools = merge_manifest_catalog(servers, tools)
    ids = {s.id for s in merged_servers}
    assert "mcp-test-extra" in ids
    tool_ids = {t.id for t in merged_tools}
    assert "mcp-test-extra-m-1" in tool_ids


def test_merge_manifest_overrides_existing_server_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a manifest's id matches a built-in server, fields are overlaid."""
    from services.mcp_defaults import (
        ATLASSIAN_ROVO_SERVER_ID,
        merge_manifest_catalog,
        platform_mcp_catalog,
    )

    manifest = {
        "id": ATLASSIAN_ROVO_SERVER_ID,
        "name": "Atlassian Rovo (override)",
        "url": "https://manifest-url.example",
        "version": "manifest-1.0",
        "capabilities": ["jira", "compass", "override-cap"],
        "tools": [],
    }
    (tmp_path / "rovo.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))

    servers, tools = platform_mcp_catalog()
    merged_servers, _ = merge_manifest_catalog(servers, tools)
    rovo = next(s for s in merged_servers if s.id == ATLASSIAN_ROVO_SERVER_ID)
    assert rovo.name == "Atlassian Rovo (override)"
    assert "override-cap" in rovo.capabilities


def test_merge_manifest_skips_entries_without_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest with no id field is skipped silently."""
    from services.mcp_defaults import (
        merge_manifest_catalog,
        platform_mcp_catalog,
    )

    (tmp_path / "no-id.json").write_text(json.dumps({"name": "no id"}))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))

    servers, tools = platform_mcp_catalog()
    out_servers, _ = merge_manifest_catalog(servers, tools)
    # Same count as before (no new server added)
    assert len(out_servers) == len(servers)


def test_merge_manifest_skips_non_dict_tool_specs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tools list with a non-dict entry is silently skipped."""
    from services.mcp_defaults import (
        merge_manifest_catalog,
        platform_mcp_catalog,
    )

    manifest = {
        "id": "mcp-with-bad-tools",
        "name": "Bad tools",
        "tools": [
            "this is not a dict",
            {"name": "good_tool", "description": "real", "category": "test"},
        ],
    }
    (tmp_path / "m.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))

    servers, tools = platform_mcp_catalog()
    _, merged_tools = merge_manifest_catalog(servers, tools)
    tool_ids = {t.id for t in merged_tools}
    # The valid tool was added (index 2 because the non-dict counted as 1)
    assert "mcp-with-bad-tools-m-2" in tool_ids
    # The invalid one was skipped
    assert "mcp-with-bad-tools-m-1" not in tool_ids


def test_merge_manifest_dedups_tool_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a manifest reuses an existing tool id, it's NOT duplicated."""
    from services.mcp_defaults import (
        merge_manifest_catalog,
        platform_mcp_catalog,
    )

    manifest = {
        "id": "mcp-dup",
        "name": "dup",
        "tools": [{"name": "t1", "description": "first", "category": "test"}],
    }
    (tmp_path / "m.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))

    servers, tools = platform_mcp_catalog()
    # Run twice in a row; the second pass must NOT add the same tool again
    first_servers, first_tools = merge_manifest_catalog(servers, tools)
    _, second_tools = merge_manifest_catalog(first_servers, first_tools)
    # Tool count stable
    assert len(second_tools) == len(first_tools)


# --- mcp_manifest_loader ------------------------------------------------


def test_load_manifest_files_returns_empty_with_no_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No override dir + repo MCP dir absent → returns []."""
    monkeypatch.delenv("MAISTRO_MCP_OVERRIDE_DIR", raising=False)
    # Patch _PARENT_MCP_DIR + _FALLBACK_MCP_DIR to nonexistent paths
    import services.mcp_manifest_loader as ml

    monkeypatch.setattr(ml, "_PARENT_MCP_DIR", tmp_path / "nope1")
    monkeypatch.setattr(ml, "_FALLBACK_MCP_DIR", tmp_path / "nope2")
    assert ml.load_manifest_files() == []


def test_load_manifest_files_reads_override_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_manifest_loader as ml

    (tmp_path / "good.json").write_text(json.dumps({"id": "a", "name": "A"}))
    (tmp_path / "no_id.json").write_text(json.dumps({"name": "skip"}))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))
    out = ml.load_manifest_files()
    ids = {item["id"] for item in out}
    assert "a" in ids


def test_load_manifest_files_skips_broken_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid JSON files don't crash; just logged + skipped."""
    from services import mcp_manifest_loader as ml

    (tmp_path / "bad.json").write_text("{this is not json")
    (tmp_path / "good.json").write_text(json.dumps({"id": "ok"}))
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(tmp_path))
    out = ml.load_manifest_files()
    ids = {item["id"] for item in out}
    assert "ok" in ids


def test_safe_parent_returns_none_when_out_of_parents() -> None:
    from services.mcp_manifest_loader import _safe_parent

    # Use a relative single-segment path → no parents beyond 0
    assert _safe_parent(Path("a.txt"), 5) is None


def test_safe_parent_returns_parent_at_depth() -> None:
    from services.mcp_manifest_loader import _safe_parent

    p = Path("/a/b/c/d.txt")
    # parents[0]=/a/b/c, [1]=/a/b, [2]=/a
    out = _safe_parent(p, 2)
    assert out == Path("/a")


def test_mcp_manifest_dirs_includes_all_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When override + MAISTRO+ fallback are all valid dirs, all three appear."""
    from services import mcp_manifest_loader as ml

    o = tmp_path / "override"
    o.mkdir()
    j = tmp_path / "testdir"
    j.mkdir()
    f = tmp_path / "fallback"
    f.mkdir()
    monkeypatch.setenv("MAISTRO_MCP_OVERRIDE_DIR", str(o))
    monkeypatch.setattr(ml, "_PARENT_MCP_DIR", j)
    monkeypatch.setattr(ml, "_FALLBACK_MCP_DIR", f)
    dirs = ml.mcp_manifest_dirs()
    assert o in dirs and j in dirs and f in dirs
