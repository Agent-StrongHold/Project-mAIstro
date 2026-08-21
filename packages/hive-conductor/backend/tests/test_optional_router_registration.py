"""Regression tests for observable optional-route registration."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import main
import pytest
from fastapi import APIRouter, FastAPI


def test_optional_router_is_mounted_with_its_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    router = APIRouter()

    @router.get("/status")
    def status() -> dict[str, bool]:
        return {"ok": True}

    importer = Mock(return_value=SimpleNamespace(router=router))
    monkeypatch.setattr(main, "import_module", importer)
    app = FastAPI()

    main._include_optional_router(app, "routes.example", prefix="/v1/example")

    importer.assert_called_once_with("routes.example")
    # Assert the public contract rather than FastAPI's private route storage.
    # FastAPI 0.135+ keeps included routers as lazy ``_IncludedRouter`` objects
    # without a ``path`` attribute, while the version in the uv workspace
    # eagerly flattens them.  CI installs the conductor requirements directly,
    # so this test must be valid against both supported representations.
    assert "/v1/example/status" in app.openapi()["paths"]


def test_application_openapi_operation_ids_are_unique() -> None:
    paths = main.app.openapi()["paths"]
    operation_ids = [
        operation["operationId"]
        for path in paths.values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]

    assert len(operation_ids) == len(set(operation_ids))


@pytest.mark.parametrize("module_name", ["routes.canvas", "routes.pm_fleet_v2"])
def test_optional_router_failure_is_logged_with_module_and_error(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_import(imported_name: str) -> None:
        raise RuntimeError(f"broken dependency for {imported_name}")

    monkeypatch.setattr(main, "import_module", fail_import)

    with caplog.at_level(logging.WARNING, logger="hive.lifespan"):
        main._include_optional_router(FastAPI(), module_name)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert module_name in record.getMessage()
    assert f"broken dependency for {module_name}" in record.getMessage()
    assert record.exc_info is not None
