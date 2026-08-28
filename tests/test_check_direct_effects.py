from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_direct_effects.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_direct_effects", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_model_http_call_is_a_site(gate) -> None:
    sites = gate.analyze_source(
        """
async def ask(client):
    return await client.post(f"{base}/v1/chat/completions", json={})
"""
    )
    assert [(s.category, s.entry_point) for s in sites] == [
        ("MODEL_EFFECT", "openai-compatible-http"),
    ]


def test_endpoint_text_elsewhere_does_not_turn_unrelated_http_into_effect(gate) -> None:
    source = """
PUBLIC = "/v1/chat/completions"
async def send_webhook(client):
    await client.post("https://example.com/webhook", json={})
"""
    assert gate.analyze_source(source) == []


def test_sql_execute_is_not_an_effect(gate) -> None:
    assert gate.analyze_source("def save(conn):\n    conn.execute('select 1')\n") == []


def test_unrelated_http_client_code_is_not_an_effect(gate) -> None:
    source = """
import httpx
async def health(client: httpx.AsyncClient):
    return await client.get("https://example.com/health")
"""
    assert gate.analyze_source(source) == []


def test_importing_governed_service_is_not_usage(gate) -> None:
    source = (
        "from maistro.capabilities.governed_invocation import GovernedInvocationExecutionService\n"
    )
    assert gate.analyze_source(source) == []


def test_events_invocation_store_is_not_capability_invocation(gate) -> None:
    source = """
from maistro.events.invocations import InvocationStore
async def save(store: InvocationStore, item):
    await store.append(item)
"""
    assert gate.analyze_source(source) == []


def test_typed_browser_call_is_detected_but_construction_is_not(gate) -> None:
    source = """
async def search():
    try:
        from maistro.tools.browser import BrowserClient
        client = BrowserClient()
        return await client.search_web("query", max_results=3)
    finally:
        await client.aclose()
"""
    sites = gate.analyze_source(source)
    assert len(sites) == 1
    assert sites[0].category == "TOOL_EFFECT"
    assert sites[0].entry_point == "browser.search_web"


def test_imported_model_helper_call_is_detected(gate) -> None:
    source = """
from maistro.agents.pm_llm_call import maistro_llm_call
async def run(messages):
    return await maistro_llm_call(messages)
"""
    sites = gate.analyze_source(source)
    assert len(sites) == 1
    assert sites[0].category == "MODEL_EFFECT"
    assert sites[0].entry_point == "model-helper"


def test_stable_identity_ignores_line_number_churn(gate) -> None:
    first = gate.analyze_source(
        'async def ask(client):\n    await client.post("/v1/chat/completions")\n'
    )
    second = gate.analyze_source(
        '\n\nasync def ask(client):\n    await client.post("/v1/chat/completions")\n'
    )
    assert first[0].id == second[0].id
    assert first[0].line != second[0].line


def test_audit_rejects_new_stale_and_undocumented_sites(gate) -> None:
    found_site = gate.analyze_source(
        'async def ask(client):\n    await client.post("/v1/chat/completions")\n', "a.py"
    )[0]
    found = {found_site.id: found_site}
    recorded = {
        "gone": {
            "path": "gone.py",
            "qualname": "x",
            "category": "MODEL_EFFECT",
            "entry_point": "openai-compatible-http",
            "callee": "client.post",
            "disposition": "RETIRE",
            "owner": "#56",
            "rationale": "retire",
        }
    }
    failures = gate.audit(recorded, found)
    assert any(message.startswith("NEW ") for message in failures)
    assert any(message.startswith("STALE ") for message in failures)

    entry = {
        "path": found_site.path,
        "qualname": found_site.qualname,
        "category": found_site.category,
        "entry_point": found_site.entry_point,
        "callee": found_site.callee,
        "disposition": "",
        "owner": "",
        "rationale": "",
    }
    failures = gate.audit({found_site.id: entry}, found)
    assert any("disposition" in message for message in failures)
    assert any("owner is required" in message for message in failures)
    assert any("rationale is required" in message for message in failures)


def test_environment_default_model_endpoint_is_detected(gate) -> None:
    source = """
import os
import httpx
def ask():
    return httpx.post(f"{base}{os.environ.get('LLM_CHAT_PATH', '/v1/chat/completions')}")
"""
    sites = gate.analyze_source(source)
    assert [(site.category, site.entry_point) for site in sites] == [
        ("MODEL_EFFECT", "openai-compatible-http"),
    ]


def test_non_src_package_python_is_scanned_but_explicit_dev_utility_is_not(gate, tmp_path) -> None:
    shipped = tmp_path / "packages/demo/frontend/server/mcp/effect.py"
    shipped.parent.mkdir(parents=True)
    shipped.write_text("pass\n")
    test_file = tmp_path / "packages/demo/tests/test_effect.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("pass\n")
    excluded = tmp_path / "packages/hive-conductor/run_hill_climb.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text("pass\n")
    found = {
        item.relative_to(tmp_path).as_posix() for item in gate._production_python_files(tmp_path)
    }
    assert found == {"packages/demo/frontend/server/mcp/effect.py"}


def test_curated_image_provider_http_is_detected_without_generic_http_matching(gate) -> None:
    source = """
import httpx
def _generate_gemini(url):
    return httpx.post(url, json={})
"""
    sites = gate.analyze_source(
        source,
        "packages/maistro-canvas/frontend/server/mcp/image_provider.py",
    )
    assert [(site.category, site.entry_point) for site in sites] == [
        ("MODEL_EFFECT", "gemini-image-http"),
    ]
