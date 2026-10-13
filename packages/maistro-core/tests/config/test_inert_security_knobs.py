"""Security config fields that read as off-switches but are not wired up.

`warden_enabled` and `sentinel_enabled` are declared on both SecurityConfig
classes — including `maistro.types.config.SecurityConfig`, the one
`create_container` actually receives — and read by nothing. Setting either to
False therefore leaves the subsystem fully on.

That silence is the hazard: an operator sets `warden_enabled: false`, gets no
error, and concludes scanning is off while every trust boundary still scans.
Until the knob is implemented, the weakening value is refused.
"""

from __future__ import annotations

import pytest

from maistro.config.settings import SecurityConfig as SettingsSecurityConfig
from maistro.types.config import SecurityConfig as TypesSecurityConfig


class TestSettingsSecurityConfig:
    @pytest.mark.parametrize("field", ["warden_enabled", "sentinel_enabled"])
    def test_disabling_is_refused(self, field: str) -> None:
        with pytest.raises(ValueError, match="not implemented"):
            SettingsSecurityConfig(**{field: False})

    def test_the_error_names_the_field(self) -> None:
        with pytest.raises(ValueError, match="sentinel_enabled"):
            SettingsSecurityConfig(sentinel_enabled=False)

    def test_defaults_construct(self) -> None:
        cfg = SettingsSecurityConfig()
        assert cfg.warden_enabled is True
        assert cfg.sentinel_enabled is True

    def test_explicitly_enabling_is_fine(self) -> None:
        assert SettingsSecurityConfig(warden_enabled=True).warden_enabled is True


class TestTypesSecurityConfig:
    """This is the class on the config object `create_container` receives, so
    its inert knob is the more misleading of the two."""

    def test_disabling_warden_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not implemented"):
            TypesSecurityConfig(warden_enabled=False)

    def test_defaults_construct(self) -> None:
        assert TypesSecurityConfig().warden_enabled is True


class TestPermissionGrantsAreConfigurable:
    """The two security knobs that *are* read (#1165 review).

    The Sentinel table is fail-closed, so a deployment that configures nothing
    denies every tool. `maistro-server` copies these two onto
    `AgentConfig.security`; without them here no YAML deployment could ever
    grant tool authority.
    """

    def test_defaults_are_the_empty_fail_closed_table(self) -> None:
        cfg = SettingsSecurityConfig()
        assert cfg.permission_preset == "none"
        assert cfg.permissions == {}

    def test_a_preset_and_explicit_grants_are_accepted(self) -> None:
        cfg = SettingsSecurityConfig(
            permission_preset="dangerous_tools_admin", permissions={"shell": ["admin"]}
        )
        assert cfg.permission_preset == "dangerous_tools_admin"
        assert cfg.permissions == {"shell": ["admin"]}

    def test_an_unknown_preset_is_refused_at_load(self) -> None:
        with pytest.raises(ValueError, match="Unknown permission preset 'typo'"):
            SettingsSecurityConfig(permission_preset="typo")
