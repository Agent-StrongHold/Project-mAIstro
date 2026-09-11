from __future__ import annotations

import json
import time

from maistro_bootstrap.builders import model_selector


def test_operator_probe_requires_explicit_disposition() -> None:
    try:
        model_selector.run_benchmark(verbose=False)
    except RuntimeError as exc:
        assert "operator-only" in str(exc)
    else:
        raise AssertionError("implicit model probes must be rejected")


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
