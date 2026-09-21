"""Coverage for `bootstrap_model_bindings` (#1079/#1091).

Loading an operator-declared `model.chat` Binding is the only way a
Workspace/Project gains authority to call the governed model gateway -- these
tests pin both branch points the diff-coverage floor flagged:

- whether a declared Binding's `credential_refs` are widened to the
  deployment's default gateway credential (only when the operator named none
  *and* a physical `litellm_key` exists to register), and
- whether a reload preserves an already-registered Binding's `created_at`
  (idempotent operator config reload) versus minting a fresh one (first load).
"""

from __future__ import annotations

import pytest

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_CHAT_CAPABILITY,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
)
from maistro.types.config import AgentConfig, ModelBindingConfig


def _config(*, litellm_key: str = "", bindings: tuple[ModelBindingConfig, ...] = ()) -> AgentConfig:
    return AgentConfig(litellm_key=litellm_key, model_bindings=list(bindings), workspace_id="ws-1")


async def test_bootstrap_defaults_credential_refs_when_none_declared() -> None:
    """Arc 60 True: no operator-named refs, but a physical key exists -- the
    Binding is authorized for exactly the one default gateway credential id,
    never a blanket "everything this workspace holds"."""

    effects = new_in_memory_effect_context()
    config = _config(
        litellm_key="sk-gateway",
        bindings=(ModelBindingConfig(binding_id="b1", project_id="p1"),),
    )

    loaded = await bootstrap_model_bindings(config, effects)

    assert len(loaded) == 1
    assert loaded[0].credential_refs == (DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,)
    assert loaded[0].workspace_id == "ws-1"  # blank declared workspace_id inherits config's
    assert loaded[0].capability == MODEL_CHAT_CAPABILITY

    record = await effects.credentials.acquire(
        workspace_id="ws-1",
        project_id="p1",
        provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
        credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
    )
    assert record.key_id == DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF
    assert record.api_key == "sk-gateway"


async def test_bootstrap_preserves_explicit_credential_refs() -> None:
    """Arc 60 False: an operator who already named refs is never silently
    widened to the default just because a gateway key also exists."""

    effects = new_in_memory_effect_context()
    config = _config(
        litellm_key="sk-gateway",
        bindings=(
            ModelBindingConfig(binding_id="b1", project_id="p1", credential_refs=("custom-ref",)),
        ),
    )

    loaded = await bootstrap_model_bindings(config, effects)

    assert loaded[0].credential_refs == ("custom-ref",)


async def test_bootstrap_skips_credential_registration_without_a_gateway_key() -> None:
    """No `litellm_key` means nothing physical to register: the declared
    Binding still loads, but its refs (here, none) pass through untouched and
    no credential pool is created for it."""

    effects = new_in_memory_effect_context()
    config = _config(bindings=(ModelBindingConfig(binding_id="b1", project_id="p1"),))

    loaded = await bootstrap_model_bindings(config, effects)

    assert loaded[0].credential_refs == ()
    assert (
        effects.credentials.pool_for(
            workspace_id="ws-1", project_id="p1", provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER
        )
        is None
    )


async def test_bootstrap_first_load_creates_a_fresh_binding() -> None:
    """Arc 74 False: nothing registered yet, so no `created_at` is carried
    over -- the store mints its own on first `put`."""

    effects = new_in_memory_effect_context()
    config = _config(bindings=(ModelBindingConfig(binding_id="b1", project_id="p1"),))

    loaded = await bootstrap_model_bindings(config, effects)

    stored = await effects.bindings.get("b1")
    assert stored is not None
    assert stored.created_at == loaded[0].created_at


async def test_bootstrap_reload_is_idempotent_and_preserves_created_at() -> None:
    """Arc 74 True: reloading identical operator configuration on a later
    process start must not trip the store's immutability check -- the second
    pass has to carry forward the first pass's `created_at` exactly."""

    effects = new_in_memory_effect_context()
    config = _config(bindings=(ModelBindingConfig(binding_id="b1", project_id="p1"),))

    first = await bootstrap_model_bindings(config, effects)
    second = await bootstrap_model_bindings(config, effects)

    assert second[0].created_at == first[0].created_at
    assert second[0] == first[0]


async def test_bootstrap_loads_every_declared_binding() -> None:
    effects = new_in_memory_effect_context()
    config = _config(
        bindings=(
            ModelBindingConfig(binding_id="b1", project_id="p1"),
            ModelBindingConfig(binding_id="b2", project_id="p2", node_id="node-9"),
        )
    )

    loaded = await bootstrap_model_bindings(config, effects)

    assert [b.binding_id for b in loaded] == ["b1", "b2"]
    assert loaded[1].node_id == "node-9"


async def test_bootstrap_with_no_declared_bindings_returns_empty_and_stays_fail_closed() -> None:
    effects = new_in_memory_effect_context()
    config = _config()

    loaded = await bootstrap_model_bindings(config, effects)

    assert loaded == ()
    with pytest.raises(Exception):  # noqa: B017 - BindingNotFound, exact type not the point here
        await effects.bindings.resolve(
            "b1",
            workspace_id="ws-1",
            project_id="p1",
            node_id="",
            capability=MODEL_CHAT_CAPABILITY,
        )
