from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import ModuleType

from maistro_bootstrap.builders import model_selector


def test_run_benchmark_refuses_library_callers() -> None:
    try:
        model_selector.run_benchmark(verbose=False)
    except RuntimeError as exc:
        assert "operator-only" in str(exc)
    else:
        raise AssertionError("implicit model probes must be rejected")


def test_run_benchmark_has_no_self_attested_operator_flag() -> None:
    """The retired operator_probe keyword must not be an importer escape.

    A boolean the caller could set let any library importer authorize
    ambient-credential model probes (#1088); passing it now is an error, not
    an authorization.
    """

    try:
        model_selector.run_benchmark(verbose=False, operator_probe=True)  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("operator_probe must not be an authorizing keyword")


def test_run_benchmark_allows_only_the_module_cli(monkeypatch, capsys) -> None:
    """A process running this module as __main__ is the operator CLI."""

    calls: list[dict] = []

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            del url, kwargs

            class _Resp:
                status_code = 200

                @staticmethod
                def json():
                    return {"data": []}

                def raise_for_status(self):
                    return None

            return _Resp()

        def post(self, url, **kwargs):
            calls.append({"url": url, "json": kwargs.get("json", {})})
            raise AssertionError("no sweep expected for an empty model list")

    monkeypatch.setattr(model_selector.httpx, "Client", _Client)
    fake_main = ModuleType("__main__")
    fake_main.__file__ = str(Path(model_selector.__file__).resolve())
    monkeypatch.setitem(sys.modules, "__main__", fake_main)

    results = model_selector.run_benchmark(models=[], verbose=False)
    assert results["fast_all"] == []
    assert results["capable_all"] == []


def test_run_benchmark_refuses_a_faked_different_main(monkeypatch) -> None:
    fake_main = ModuleType("__main__")
    fake_main.__file__ = "/somewhere/else.py"
    monkeypatch.setitem(sys.modules, "__main__", fake_main)

    try:
        model_selector.run_benchmark(models=[], verbose=False)
    except RuntimeError as exc:
        assert "operator-only" in str(exc)
    else:
        raise AssertionError("a non-CLI __main__ must not authorize probes")


def test_best_model_reads_persisted_operator_choice(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "model_cache.json"
    cache_path.write_text(json.dumps({"timestamp": time.time(), "capable_model": "cached-capable"}))
    monkeypatch.setattr(model_selector, "CACHE_PATH", cache_path)

    assert model_selector.best_model("capable") == "cached-capable"


def test_best_model_never_refreshes_operator_probe_implicitly(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "model_cache.json"
    cache_path.write_text(json.dumps({"timestamp": 0, "capable_model": "stale-capable"}))
    monkeypatch.setattr(model_selector, "CACHE_PATH", cache_path)
    monkeypatch.setenv("LITELLM_URL", "http://gateway")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "operator-key")
    monkeypatch.setenv("DEFAULT_MODEL", "configured-default")

    def _must_not_probe(*args, **kwargs):
        raise AssertionError("ordinary product selection must not run the operator probe")

    monkeypatch.setattr(model_selector, "run_benchmark", _must_not_probe)

    assert model_selector.best_model("capable") == "configured-default"
