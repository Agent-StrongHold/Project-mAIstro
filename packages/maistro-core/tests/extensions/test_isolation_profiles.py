"""Extension isolation profile selection (#970, M9-G2).

The profile is where declared authority becomes an enforced contract, so
these tests pin the selection rules that make undeclared access impossible:
the egress/filesystem intersection, the ceilings that overrides can only
tighten, the trust gate that leaves untrusted extensions without any profile
at all, and the explicit-only trusted in-process tier.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from maistro.extensions.isolation import (
    ExtensionIsolationError,
    ExtensionIsolationProfile,
    ExtensionIsolationRefused,
    ExtensionRiskTier,
    ExtensionSandboxPolicy,
    ExtensionSandboxStartFailure,
    build_sandbox_config,
    risk_tier_for,
    select_isolation_profile,
)
from maistro.extensions.manifest import inspect_manifest
from maistro.extensions.trust import TrustReport
from maistro.sandbox.network import DENY_ALL, EgressGrant, EgressMode
from maistro.sandbox.policy import ExecutionMode
from maistro.sandbox.protocol import SandboxConfig

PAYLOAD = b"isolation-profile-payload-v1"

TRUSTED = TrustReport(trusted=True)
UNTRUSTED = TrustReport(trusted=False, failures=("publisher not in the trusted allowlist",))


def _manifest(
    permissions: tuple[str, ...] = ("workspace.read",),
    publisher: str = "acme",
) -> object:
    """An inspected manifest whose declared permissions are ``permissions``."""
    document = {
        "manifest_version": 1,
        "id": f"{publisher}.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": publisher,
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            "size": len(PAYLOAD),
        },
    }
    return inspect_manifest(json.dumps(document).encode("utf-8"))


def scoped_policy(**overrides: object) -> ExtensionSandboxPolicy:
    """A policy whose ceilings are distinct so widening is observable."""
    defaults: dict[str, object] = {
        "min_tier": "bubblewrap",
        "max_memory_mb": 512,
        "max_cpu_cores": 2.0,
        "max_processes": 64,
        "max_timeout_s": 120,
        "max_file_mb": 64,
        "egress": EgressGrant(
            mode=EgressMode.SCOPED, allow=("api.example.com",), reason="operator grant"
        ),
        "writable_host_paths": ("/srv/exports",),
    }
    defaults.update(overrides)
    return ExtensionSandboxPolicy(**defaults)  # type: ignore[arg-type]


class TestRiskTier:
    def test_read_only_grants_are_standard_risk(self) -> None:
        assert risk_tier_for(("workspace.read", "memory.read")) is ExtensionRiskTier.STANDARD

    def test_network_outbound_is_elevated(self) -> None:
        assert risk_tier_for(("network.outbound",)) is ExtensionRiskTier.ELEVATED

    def test_filesystem_read_is_elevated(self) -> None:
        """Read authority is sandbox-enforced too: scoped paths need a boundary."""
        assert risk_tier_for(("filesystem.read",)) is ExtensionRiskTier.ELEVATED

    def test_filesystem_write_is_elevated(self) -> None:
        assert risk_tier_for(("filesystem.write",)) is ExtensionRiskTier.ELEVATED

    def test_an_empty_grant_is_standard(self) -> None:
        assert risk_tier_for(()) is ExtensionRiskTier.STANDARD


class TestTrustGate:
    def test_a_failed_trust_evaluation_has_no_profile_at_all(self) -> None:
        """Not a weaker profile — none. Untrusted extension code does not run."""
        with pytest.raises(ExtensionIsolationRefused, match=r"acme\.chart_tools"):
            select_isolation_profile(
                _manifest(),  # type: ignore[arg-type]
                granted=("workspace.read",),
                trust=UNTRUSTED,
                policy=scoped_policy(),
            )

    def test_refusal_names_why_trust_failed(self) -> None:
        with pytest.raises(ExtensionIsolationRefused, match="trusted allowlist"):
            select_isolation_profile(
                _manifest(),  # type: ignore[arg-type]
                granted=(),
                trust=UNTRUSTED,
                policy=scoped_policy(),
            )


class TestEgressIntersection:
    """Undeclared network access is denied even when policy would allow it."""

    def test_undeclared_network_is_deny_all_despite_a_scoped_policy(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=("workspace.read",),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert profile.egress.mode is EgressMode.DENY
        assert profile.egress.allow == ()

    @pytest.mark.parametrize("granted", [("network.outbound",), ("filesystem.write",)])
    def test_a_grant_past_the_declaration_is_dropped_not_honored(
        self, granted: tuple[str, ...]
    ) -> None:
        """A mismatched record granting authority the manifest never declared
        (preview vs. install divergence) cannot widen the profile: the grant
        is intersected with the declaration before any egress/path rule."""
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=granted,
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert profile.egress.mode is EgressMode.DENY
        assert profile.egress.allow == ()
        assert profile.writable_paths == ()

    def test_declared_network_gets_the_policy_allowlist_not_the_open_internet(self) -> None:
        profile = select_isolation_profile(
            _manifest(("network.outbound",)),  # type: ignore[arg-type]
            granted=("network.outbound",),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert profile.egress.mode is EgressMode.SCOPED
        assert profile.egress.allow == ("api.example.com",)

    def test_declared_network_with_a_denying_policy_stays_denied(self) -> None:
        policy = scoped_policy(egress=DENY_ALL)
        profile = select_isolation_profile(
            _manifest(("network.outbound",)),  # type: ignore[arg-type]
            granted=("network.outbound",),
            trust=TRUSTED,
            policy=policy,
        )
        assert profile.egress.mode is EgressMode.DENY

    def test_the_grant_is_not_taken_from_the_manifest_alone(self) -> None:
        """A manifest can declare anything; only the host's granted set counts."""
        profile = select_isolation_profile(
            _manifest(("network.outbound",)),  # type: ignore[arg-type]
            granted=("workspace.read",),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert profile.egress.mode is EgressMode.DENY

    def test_host_egress_is_refused_as_a_policy_shaped_like_a_hole(self) -> None:
        """Extensions never get the host namespace whole — that is the
        configuration ADR-093 deprecates, so the policy refuses to be built
        with it rather than letting a profile carry it."""
        with pytest.raises(ValueError, match="HOST egress"):
            scoped_policy(
                egress=EgressGrant(mode=EgressMode.HOST, reason="operator explicitly asked")
            )


class TestFilesystemIntersection:
    def test_undeclared_write_mounts_nothing_despite_policy_paths(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=("workspace.read",),
            trust=TRUSTED,
            policy=scoped_policy(writable_host_paths=("/srv/exports", "/var/data")),
        )
        assert profile.writable_paths == ()

    def test_declared_write_gets_exactly_the_policy_paths(self) -> None:
        profile = select_isolation_profile(
            _manifest(("filesystem.write",)),  # type: ignore[arg-type]
            granted=("filesystem.write",),
            trust=TRUSTED,
            policy=scoped_policy(writable_host_paths=("/srv/exports", "/var/data")),
        )
        assert profile.writable_paths == ("/srv/exports", "/var/data")

    def test_filesystem_read_does_not_widen_the_sandbox(self) -> None:
        """Reads never add writable mounts — they get the policy's read-only
        mounts instead, and only when declared."""
        profile = select_isolation_profile(
            _manifest(("filesystem.read",)),  # type: ignore[arg-type]
            granted=("filesystem.read",),
            trust=TRUSTED,
            policy=scoped_policy(
                writable_host_paths=("/srv/exports",),
                readable_host_paths=("/srv/exports", "/var/ro"),
            ),
        )
        assert profile.writable_paths == ()
        assert profile.readable_paths == ("/srv/exports", "/var/ro")

    def test_filesystem_read_without_the_grant_gets_no_read_mounts(self) -> None:
        profile = select_isolation_profile(
            _manifest(("workspace.read",)),  # type: ignore[arg-type]
            granted=("workspace.read",),
            trust=TRUSTED,
            policy=scoped_policy(readable_host_paths=("/srv/exports",)),
        )
        assert profile.readable_paths == ()


class TestInProcessTier:
    """The trusted in-process tier: explicit policy, never a fallback."""

    def _in_process_policy(self, **overrides: object) -> ExtensionSandboxPolicy:
        defaults: dict[str, object] = {
            "allow_in_process": True,
            "in_process_publishers": frozenset({"acme"}),
        }
        defaults.update(overrides)
        return scoped_policy(**defaults)

    def test_explicit_policy_trust_and_standard_risk_select_in_process(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=("workspace.read", "tool.invoke"),
            trust=TRUSTED,
            policy=self._in_process_policy(),
        )
        assert profile.in_process is True
        assert profile.min_tier is None
        assert "not a fallback" in profile.selection_reason

    @pytest.mark.parametrize(
        ("policy_overrides", "granted"),
        [
            ({"allow_in_process": False}, ("workspace.read",)),
            ({"in_process_publishers": frozenset({"other-pub"})}, ("workspace.read",)),
        ],
    )
    def test_each_missing_policy_condition_leaves_the_extension_sandboxed(
        self, policy_overrides: dict[str, object], granted: tuple[str, ...]
    ) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=granted,
            trust=TRUSTED,
            policy=self._in_process_policy(**policy_overrides),
        )
        assert profile.in_process is False

    def test_a_foreign_publisher_is_sandboxed_even_with_the_tier_enabled(self) -> None:
        profile = select_isolation_profile(
            _manifest(publisher="other_pub"),  # type: ignore[arg-type]
            granted=("workspace.read",),
            trust=TRUSTED,
            policy=self._in_process_policy(),
        )
        assert profile.in_process is False

    def test_elevated_risk_is_never_eligible_in_process(self) -> None:
        """Network and filesystem authority (read and write) is exactly what
        the sandbox exists to contain, so no policy combination runs it
        inside the host — in process there is no boundary to scope those
        paths or that egress with."""
        for granted in (
            ("network.outbound",),
            ("filesystem.write",),
            ("filesystem.read",),
        ):
            profile = select_isolation_profile(
                _manifest(granted),  # type: ignore[arg-type]
                granted=granted,
                trust=TRUSTED,
                policy=self._in_process_policy(),
            )
            assert profile.in_process is False, granted

    def test_an_in_process_profile_fails_dead_if_routed_at_a_sandbox(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=("workspace.read",),
            trust=TRUSTED,
            policy=self._in_process_policy(),
        )
        with pytest.raises(ExtensionIsolationError, match="runs in process"):
            build_sandbox_config(profile)

    def test_allowing_the_tier_without_naming_publishers_is_a_configuration_error(
        self,
    ) -> None:
        with pytest.raises(ValueError, match="in_process_publishers"):
            scoped_policy(allow_in_process=True)

    def test_workload_policy_is_meaningless_for_in_process(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=self._in_process_policy(),
        )
        with pytest.raises(ExtensionIsolationError, match="no sandbox workload policy"):
            profile.workload_policy()


class TestCeilings:
    """Policy ceilings are ceilings: selection and compilation never widen."""

    def test_profile_carries_the_policy_ceilings(self) -> None:
        policy = scoped_policy(
            max_memory_mb=768, max_processes=32, max_timeout_s=90, max_file_mb=16
        )
        profile = select_isolation_profile(
            _manifest(("network.outbound",)),  # type: ignore[arg-type]
            granted=("network.outbound",),
            trust=TRUSTED,
            policy=policy,
        )
        assert profile.memory_mb == 768
        assert profile.max_processes == 32
        assert profile.timeout_s == 90
        assert profile.max_file_mb == 16
        assert profile.cpu_cores == 2.0

    def test_overrides_may_only_tighten_memory(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(max_memory_mb=512),
        )
        assert build_sandbox_config(profile, memory_mb=128).memory_mb == 128
        assert build_sandbox_config(profile, memory_mb=4096).memory_mb == 512

    def test_overrides_may_only_tighten_pids_timeout_and_file_size(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(max_processes=64, max_timeout_s=120, max_file_mb=64),
        )
        config = build_sandbox_config(profile, max_processes=8, timeout_s=30, max_file_mb=4)
        assert config.max_processes == 8
        assert config.timeout_s == 30
        assert config.max_file_mb == 4
        widened = build_sandbox_config(profile, max_processes=999, timeout_s=999, max_file_mb=999)
        assert widened.max_processes == 64
        assert widened.timeout_s == 120
        assert widened.max_file_mb == 64

    def test_cpu_override_may_only_tighten(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(max_cpu_cores=2.0),
        )
        assert build_sandbox_config(profile, cpu_cores=0.25).cpu_cores == 0.25
        assert build_sandbox_config(profile, cpu_cores=8.0).cpu_cores == 2.0

    def test_the_egress_grant_is_not_overridable_at_compile_time(self) -> None:
        """The grant was decided at selection; there is no API that edits it."""
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        config = build_sandbox_config(profile)
        assert config.network is False
        assert config.egress.mode is EgressMode.DENY

    def test_writable_paths_flow_into_the_config(self) -> None:
        profile = select_isolation_profile(
            _manifest(("filesystem.write",)),  # type: ignore[arg-type]
            granted=("filesystem.write",),
            trust=TRUSTED,
            policy=scoped_policy(writable_host_paths=("/srv/exports",)),
        )
        assert build_sandbox_config(profile).writable_paths == ["/srv/exports"]

    def test_readable_paths_flow_into_the_config(self) -> None:
        profile = select_isolation_profile(
            _manifest(("filesystem.read",)),  # type: ignore[arg-type]
            granted=("filesystem.read",),
            trust=TRUSTED,
            policy=scoped_policy(readable_host_paths=("/srv/exports", "/var/ro")),
        )
        config = build_sandbox_config(profile)
        assert config.read_paths == ["/srv/exports", "/var/ro"]
        assert config.writable_paths == []


class TestExecutionModeFloors:
    """ADR-093 decision 6: the mode decides whether execution is permitted."""

    def test_an_unstated_mode_gets_the_autonomous_floor(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(min_tier="bubblewrap"),
            mode=None,
        )
        assert profile.mode is None
        assert profile.workload_policy().effective_min_tier == "gvisor"

    def test_an_explicit_autonomous_mode_keeps_the_tier_two_floor(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(min_tier="bubblewrap"),
            mode=ExecutionMode.AUTONOMOUS,
        )
        assert profile.workload_policy().effective_min_tier == "gvisor"

    def test_interactive_execution_may_run_on_tier_three(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(min_tier="bubblewrap"),
            mode=ExecutionMode.INTERACTIVE,
        )
        assert profile.workload_policy().effective_min_tier == "bubblewrap"

    def test_a_stronger_policy_tier_is_kept_under_interactive(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(min_tier="gvisor"),
            mode=ExecutionMode.INTERACTIVE,
        )
        assert profile.workload_policy().effective_min_tier == "gvisor"

    def test_the_fake_tier_is_not_a_selectable_policy(self) -> None:
        with pytest.raises(ValueError, match="never carry extension code"):
            scoped_policy(min_tier="fake")  # type: ignore[arg-type]


class TestConfigCompilation:
    def test_config_is_tightened_by_the_profile_not_just_labeled(self) -> None:
        profile = select_isolation_profile(
            _manifest(("network.outbound",)),  # type: ignore[arg-type]
            granted=("network.outbound",),
            trust=TRUSTED,
            policy=scoped_policy(
                max_memory_mb=256, max_processes=16, max_timeout_s=45, max_file_mb=8
            ),
        )
        config = build_sandbox_config(profile)
        assert isinstance(config, SandboxConfig)
        assert config.memory_mb == 256
        assert config.max_processes == 16
        assert config.timeout_s == 45
        assert config.max_file_mb == 8
        assert config.network is True
        assert config.min_isolation == "bubblewrap"
        assert config.egress.mode is EgressMode.SCOPED

    def test_profile_demands_its_tier_from_the_substrate(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(min_tier="gvisor"),
        )
        assert build_sandbox_config(profile).min_isolation == "gvisor"

    def test_selection_reason_records_the_intersection_as_evidence(self) -> None:
        profile = select_isolation_profile(
            _manifest(("network.outbound", "filesystem.write")),  # type: ignore[arg-type]
            granted=("network.outbound", "filesystem.write"),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert "risk=elevated" in profile.selection_reason
        assert "policy allowlist" in profile.selection_reason
        assert "filesystem.write granted" in profile.selection_reason

    def test_undeclared_authority_is_named_as_denied_in_the_evidence(self) -> None:
        profile = select_isolation_profile(
            _manifest(),  # type: ignore[arg-type]
            granted=(),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert "undeclared — denied" in profile.selection_reason


class TestFailureTypes:
    def test_start_failure_carries_the_extension_identity(self) -> None:
        failure = ExtensionSandboxStartFailure("acme.chart_tools", "1.4.0", "no backend")
        assert failure.extension_id == "acme.chart_tools"
        assert failure.version == "1.4.0"
        assert "did not run" in str(failure)

    def test_profile_is_frozen(self) -> None:
        profile = select_isolation_profile(
            _manifest(("network.outbound",)),  # type: ignore[arg-type]
            granted=("network.outbound",),
            trust=TRUSTED,
            policy=scoped_policy(),
        )
        assert isinstance(profile, ExtensionIsolationProfile)
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.memory_mb = 99999  # type: ignore[misc]
