"""Tests for the OpenAPI dump that `frontend/src/api/types.gen.ts` is generated from (#1048).

CI regenerates the types and fails on any diff, so the dump has two ways to be
wrong. Output that varies with anything but the app's schema makes the drift
check red on a clean tree, and gets the check deleted. Output that quietly
drops part of the schema makes it green while deleting types the frontend uses.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dump-hive-openapi.py"


@pytest.fixture(scope="module")
def dump():
    spec = importlib.util.spec_from_file_location("dump_hive_openapi", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestReproducibleBytes:
    def test_key_order_does_not_reach_the_output(self, dump):
        a = {"paths": {"/b": {}, "/a": {}}, "info": {"version": "1", "title": "t"}}
        b = {"info": {"title": "t", "version": "1"}, "paths": {"/a": {}, "/b": {}}}
        assert dump.render(a) == dump.render(b)

    def test_output_is_newline_terminated_json_of_the_same_document(self, dump):
        document = {"paths": {"/x": {"get": {"summary": "café"}}}}
        text = dump.render(document)
        assert text.endswith("}\n")
        assert json.loads(text) == document
        assert "café" in text


class TestRefusesAPartialSchema:
    def test_a_failed_optional_router_writes_nothing(self, dump, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            dump,
            "build_document",
            lambda: ({"paths": {"/health": {}}}, ["routes.design: No module named 'x'"]),
        )
        out = tmp_path / "openapi.json"
        assert dump.main(["dump", str(out)]) == 1
        assert not out.exists()
        assert "routes.design" in capsys.readouterr().out

    def test_a_document_with_no_paths_writes_nothing(self, dump, monkeypatch, tmp_path):
        monkeypatch.setattr(dump, "build_document", lambda: ({"paths": {}}, []))
        out = tmp_path / "openapi.json"
        assert dump.main(["dump", str(out)]) == 1
        assert not out.exists()


@pytest.fixture(scope="module")
def built(dump):
    """Built, not mocked: the schema is what the generated types claim to mirror."""
    return dump.build_document()


class TestTheRealApp:
    def test_every_optional_router_loads_here(self, built):
        _, degraded = built
        assert degraded == []

    def test_the_schema_carries_entity_components(self, built):
        document, _ = built
        assert document["paths"]
        assert document["components"]["schemas"]

    def test_a_built_frontend_does_not_change_the_schema(self, built, monkeypatch, tmp_path):
        """`spa_fallback` is registered only when `frontend/dist` exists. In the
        schema it would make the generated types depend on whether someone ran
        `npm run build` first, which CI does and a fresh checkout does not."""
        main = importlib.import_module("main")
        static_root = tmp_path / "dist"
        static_root.mkdir()
        monkeypatch.setattr(main, "STATIC_DIR", static_root)
        app = main.create_app()

        assert any(getattr(r, "name", None) == "spa_fallback" for r in app.routes)
        assert sorted(app.openapi()["paths"]) == sorted(built[0]["paths"])
