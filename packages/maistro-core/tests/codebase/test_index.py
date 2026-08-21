"""Behavioral tests for InMemoryCodeStructureIndex.build() against a real fixture tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.codebase.index import InMemoryCodeStructureIndex

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_build_discovers_all_fixture_modules() -> None:
    report = await InMemoryCodeStructureIndex().build(str(FIXTURES_ROOT))
    module_paths = {mod.module_path for mod in report.modules}
    assert module_paths == {
        "protocols.storage",
        "impls.concrete_store",
        "impls.good_impl",
        "impls.bad_impl",
    }


@pytest.mark.asyncio
async def test_build_marks_protocol_class() -> None:
    report = await InMemoryCodeStructureIndex().build(str(FIXTURES_ROOT))
    protocol_names = {cls.name for _, cls in report.protocol_classes()}
    assert protocol_names == {"Store"}


@pytest.mark.asyncio
async def test_build_captures_bad_impl_import_of_concrete_class() -> None:
    report = await InMemoryCodeStructureIndex().build(str(FIXTURES_ROOT))
    bad_impl = report.module("impls.bad_impl")
    assert bad_impl is not None
    assert any(
        imp.module == "impls.concrete_store" and "Store" in imp.names for imp in bad_impl.imports
    )


@pytest.mark.asyncio
async def test_modules_importing_finds_consumers_of_concrete_store() -> None:
    report = await InMemoryCodeStructureIndex().build(str(FIXTURES_ROOT))
    consumers = {mod.module_path for mod in report.modules_importing("impls.concrete_store")}
    assert consumers == {"impls.bad_impl"}
