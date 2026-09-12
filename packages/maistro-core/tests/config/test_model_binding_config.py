"""Config-boundary behavior for declared model.chat authorizations (#1079).

The YAML layer carries raw declaration maps (`MaistroYamlConfig`), and the
`AgentConfig` boundary is where they are validated into `ModelBindingConfig` —
so a malformed declaration is a startup failure, not a Binding the node later
cannot resolve. These tests pin both ends of that seam.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.config.settings import MaistroYamlConfig
from maistro.types.config import AgentConfig


class TestYamlDeclarationsPassThrough:
    def test_declared_bindings_are_carried_as_raw_maps(self) -> None:
        config = MaistroYamlConfig(
            model_bindings=[
                {
                    "binding_id": "model-default",
                    "project_id": "project-a",
                    "provider_name": "yaml-model",
                }
            ]
        )

        assert config.model_bindings[0]["binding_id"] == "model-default"

    def test_a_deployment_without_declarations_authorizes_nothing(self) -> None:
        assert MaistroYamlConfig().model_bindings == []


class TestAgentConfigBoundaryValidation:
    def test_raw_maps_are_coerced_into_model_binding_configs(self) -> None:
        config = AgentConfig(
            router_api_key="test-key",
            model_bindings=[
                {
                    "binding_id": "model-default",
                    "project_id": "project-a",
                    "provider_name": "yaml-model",
                }
            ],
        )

        binding = config.model_bindings[0]
        assert binding.binding_id == "model-default"
        assert binding.project_id == "project-a"
        assert binding.provider_name == "yaml-model"

    def test_a_blank_binding_identity_is_a_startup_failure(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(
                router_api_key="test-key",
                model_bindings=[{"binding_id": " ", "project_id": "project-a"}],
            )

    def test_a_blank_scope_identity_is_a_startup_failure(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(
                router_api_key="test-key",
                model_bindings=[{"binding_id": "model-default", "project_id": ""}],
            )

    def test_an_empty_credential_ref_is_a_startup_failure(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(
                router_api_key="test-key",
                model_bindings=[
                    {
                        "binding_id": "model-default",
                        "project_id": "project-a",
                        "credential_refs": ("  ",),
                    }
                ],
            )


class TestUnknownFieldsAreRefused:
    """A misspelled restriction must refuse the declaration (#1079 review).

    With Pydantic's default `extra="ignore"`, `provider_nam` or `nodeid` was
    discarded and the field fell back to "", producing an unpinned or
    project-wide Binding: a typo silently *widened* what was authorized.
    """

    @pytest.mark.parametrize("typo", ["provider_nam", "nodeid", "credential_ref"])
    def test_a_misspelled_restriction_is_refused_directly(self, typo: str) -> None:
        from pydantic import ValidationError

        from maistro.types.config import ModelBindingConfig

        with pytest.raises(ValidationError, match=typo):
            ModelBindingConfig.model_validate(
                {"binding_id": "b", "project_id": "p", typo: "model-a"}
            )

    def test_a_misspelled_restriction_is_refused_at_the_agent_config_boundary(self) -> None:
        from pydantic import ValidationError

        from maistro.types.config import AgentConfig

        with pytest.raises(ValidationError, match="provider_nam"):
            AgentConfig(
                router_api_key="k",
                model_bindings=[{"binding_id": "b", "project_id": "p", "provider_nam": "x"}],
            )
