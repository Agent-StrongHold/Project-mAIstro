"""The gallery model adapter's self-contract tests (#980, provider adapter).

Runs in the isolation fixture's fresh venv (this wheel + pytest, nothing
else). These tests pin the declaration-honesty rules the host's registration
conformance will enforce — failing here, in the publisher's own suite,
instead of at 3 a.m. inside someone's Run.
"""

from __future__ import annotations

import json

from gallery_model_adapter import plugin as adapter

#: The statuses the platform's resilience layer reads, and the kind the
#: canonical classifier infers from each. The adapter's taxonomy must agree
#: with this table on every exercised status.
PINNED_ERROR_STATUSES: tuple[tuple[int, str], ...] = (
    (400, "permanent"),
    (401, "auth"),
    (402, "permanent"),
    (403, "auth"),
    (404, "permanent"),
    (408, "permanent"),
    (409, "permanent"),
    (429, "rate_limited"),
    (500, "retryable"),
    (502, "retryable"),
    (503, "retryable"),
    (504, "retryable"),
)


class _Request:
    """A stand-in for the host's canonical chat request value."""

    def __init__(self, **kwargs: object) -> None:
        self.model = ""
        self.messages: list[dict[str, object]] = []
        self.temperature: float | None = 0.7
        self.max_tokens: int | None = None
        self.tools: list[dict[str, object]] | None = None
        self.tool_choice: str | None = None
        self.response_format: dict[str, object] | None = None
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_spec_declares_no_secret_surface() -> None:
    """The spec may declare *how* a credential is presented, never carry one."""
    forbidden = {"api_key", "secret", "password", "token", "credential_value"}
    assert not (set(adapter.SPEC) & forbidden)
    for key in adapter.SPEC:
        assert not key.lower().endswith(("_key", "_secret", "_password"))


def test_spec_transport_is_a_real_origin_without_userinfo() -> None:
    from urllib.parse import urlsplit

    parsed = urlsplit(str(adapter.SPEC["base_url"]))
    assert parsed.scheme in ("http", "https")
    assert bool(parsed.hostname)
    assert parsed.username is None and parsed.password is None


def test_spec_models_declare_honest_narrowing_capabilities() -> None:
    capabilities = adapter.SPEC["capabilities"]
    assert isinstance(capabilities, dict)
    models = adapter.SPEC["models"]
    assert isinstance(models, list) and models
    for model in models:
        assert isinstance(model, dict)
        # Flags may only narrow from adapter to model.
        for flag, allowed in capabilities.items():
            claimed = model.get("capabilities", {}).get(flag, False)  # type: ignore[union-attr]
            assert claimed is False or allowed is True, (
                f"model {model['name']} claims {flag} the adapter does not declare"
            )


def test_request_normalization_names_the_model_and_serializes() -> None:
    for model in adapter.SPEC["models"]:  # type: ignore[union-attr]
        name = str(model["name"])  # type: ignore[index]
        payload = adapter.normalize_request(
            name,
            _Request(messages=[{"role": "user", "content": "hi"}], max_tokens=64),
        )
        assert payload["model"] == name
        # The transport serializes with the standard encoder; anything a
        # plain json.dumps refuses must be refused here, at the source.
        json.dumps(payload)


def test_request_normalization_preserves_unset_sampling() -> None:
    payload = adapter.normalize_request(
        "gallery-chat-fast",
        _Request(messages=[{"role": "user", "content": "hi"}], temperature=None),
    )
    assert "temperature" not in payload
    assert payload["stream"] is False


def test_response_normalization_carries_choices() -> None:
    body = adapter.normalize_response({"choices": [{"message": {"role": "assistant"}}]})
    assert isinstance(body["choices"], list) and body["choices"]


def test_usage_reporting_is_honest_or_absent() -> None:
    assert adapter.usage_from({"usage": {"prompt_tokens": 3, "completion_tokens": 5}}) == (3, 5)
    assert adapter.usage_from({}) is None
    assert adapter.usage_from({"usage": "garbage"}) is None


def test_error_taxonomy_matches_the_pinned_table() -> None:
    for status, kind in PINNED_ERROR_STATUSES:
        assert adapter.error_kind_for(status) == kind, (
            f"status {status} must classify as {kind!r} to agree with canonical resilience"
        )


def test_health_normalization() -> None:
    assert adapter.health_from({"status": "ok"}) is True
    assert adapter.health_from({}) is True
    assert adapter.health_from({"status": "down"}) is False


def test_plugin_identity_matches_the_declared_spec() -> None:
    manifest_id = "gallery.model_adapter"
    assert adapter.PLUGIN["kind"] == "capability-provider"
    assert adapter.PLUGIN["name"] == manifest_id
    assert adapter.SPEC["adapter_id"] == "gallery-model-adapter"
    assert adapter.SPEC["protocol"] == "openai-chat-completions"


def test_declared_handlers_all_exist() -> None:
    handlers = adapter.PLUGIN["handlers"]
    assert isinstance(handlers, list)
    for name in handlers:
        assert callable(getattr(adapter, str(name), None)), f"missing handler {name!r}"
