"""SPEC-012: Admin / user1 Privilege Separation — mandatory two-tier model.

These tests define the contract for the privilege system. All tests should
FAIL until the privilege module is implemented.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestUsersToml:
    """AC: users.toml is admin-signed; conductor refuses to start with invalid sig."""

    def test_load_valid_users_toml(self, tmp_path: Path) -> None:
        from maistro.privilege import UsersStore

        store = UsersStore(data_dir=str(tmp_path))
        store.initialize(
            admin_name="alice",
            admin_public_key="pk_admin_001",
            user_name="bob",
            user_public_key="pk_user_001",
        )

        loaded = UsersStore(data_dir=str(tmp_path))
        assert loaded.admin().name == "alice"
        assert loaded.user_by_public_key("pk_user_001").name == "bob"

    def test_refuses_invalid_signature(self, tmp_path: Path) -> None:
        from maistro.privilege import UsersStore, UsersTamperError

        store = UsersStore(data_dir=str(tmp_path))
        store.initialize(
            admin_name="alice",
            admin_public_key="pk_admin",
            user_name="bob",
            user_public_key="pk_user",
        )

        toml_path = tmp_path / "users.toml"
        raw = toml_path.read_text()
        tampered = raw.replace("alice", "eve")
        toml_path.write_text(tampered)

        with pytest.raises(UsersTamperError):
            UsersStore(data_dir=str(tmp_path))


class TestMandatoryTwoUsers:
    """AC: Setup wizard cannot complete with fewer than two users."""

    def test_refuses_single_user_init(self, tmp_path: Path) -> None:
        from maistro.privilege import InsufficientUsersError, UsersStore

        store = UsersStore(data_dir=str(tmp_path))
        with pytest.raises(InsufficientUsersError):
            store.initialize(
                admin_name="alice",
                admin_public_key="pk_admin",
            )

    def test_no_single_user_env_override(self, tmp_path: Path) -> None:
        from maistro.privilege import InsufficientUsersError, UsersStore

        store = UsersStore(data_dir=str(tmp_path), allow_single_user=False)
        with pytest.raises(InsufficientUsersError):
            store.initialize(
                admin_name="alice",
                admin_public_key="pk_admin",
            )


class TestElevationFlow:
    """AC: User proposes -> admin signs -> operation proceeds; under 30s."""

    def test_elevation_grant_and_use(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="Need to run diagnostics",
        )
        token = guard.propose_elevation(request)
        grant = guard.admin_sign_elevation(token, admin_key="pk_admin")

        assert grant.is_valid
        assert grant.scope == "shell:execute"

    def test_elevation_rejected_by_wrong_admin(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationDeniedError, ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="sneaky",
        )
        token = guard.propose_elevation(request)
        with pytest.raises(ElevationDeniedError):
            guard.admin_sign_elevation(token, admin_key="pk_wrong_admin")


class TestTimeBoxedDelegation:
    """AC: Admin grants 15-min scope; auto-revokes at expiry."""

    def test_delegation_expires(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="Quick task",
        )
        token = guard.propose_elevation(request)
        grant = guard.admin_sign_elevation(
            token,
            admin_key="pk_admin",
            ttl_seconds=0,
        )

        assert not grant.is_valid
        assert grant.expiry_reason == "expired"


class TestAdminKeyRotation:
    """AC: Admin key rotation invalidates all active elevation grants."""

    def test_rotation_revokes_all_grants(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin_v1",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="test",
        )
        token = guard.propose_elevation(request)
        grant = guard.admin_sign_elevation(token, admin_key="pk_admin_v1")
        assert grant.is_valid

        guard.rotate_admin_key(
            old_key="pk_admin_v1",
            new_key="pk_admin_v2",
        )

        with pytest.raises(Exception, match="GRANT_KEY_MISMATCH"):
            grant.validate()


class TestPolicyVCs:
    """AC: Admin signs standing policy; auditable + revocable."""

    def test_create_and_check_policy(self, tmp_path: Path) -> None:
        from maistro.privilege import PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        policy_id = guard.create_policy(
            admin_key="pk_admin",
            user_public_key="pk_user",
            scope="file:read:/data/*",
            description="User can read data files",
        )

        assert guard.policy_allows(
            policy_id=policy_id,
            user_public_key="pk_user",
            action="file:read:/data/report.csv",
        )

    def test_revoke_policy(self, tmp_path: Path) -> None:
        from maistro.privilege import PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        policy_id = guard.create_policy(
            admin_key="pk_admin",
            user_public_key="pk_user",
            scope="file:read:/data/*",
            description="Temporary access",
        )

        guard.revoke_policy(policy_id, admin_key="pk_admin")
        assert not guard.policy_allows(
            policy_id=policy_id,
            user_public_key="pk_user",
            action="file:read:/data/report.csv",
        )


class TestAuditLog:
    """AC: Audit log records every elevation as signed VC."""

    def test_elevation_grant_recorded(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="test",
        )
        token = guard.propose_elevation(request)
        guard.admin_sign_elevation(token, admin_key="pk_admin")

        entries = guard.audit_log()
        assert len(entries) >= 1
        grant_entries = [e for e in entries if e["action"] == "elevation_granted"]
        assert len(grant_entries) >= 1
        assert grant_entries[0]["scope"] == "shell:execute"
        assert "signature" in grant_entries[0]


class TestAdminOnlyTools:
    """AC: Admin-only tools reject user-keyed envelopes."""

    def test_user_cannot_access_admin_tool(self, tmp_path: Path) -> None:
        from maistro.privilege import PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        assert guard.can_perform("pk_admin", "admin:settings:write")
        assert not guard.can_perform("pk_user", "admin:settings:write")

    def test_heartbeat_runs_as_user(self, tmp_path: Path) -> None:
        from maistro.privilege import PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        heartbeat_identity = guard.identity_for_subsystem("heartbeat")
        assert heartbeat_identity.role == "user"
        assert heartbeat_identity.public_key == "pk_user"


class TestAdminKeyConstantTimeCompare:
    """M1: admin-key comparisons must use secret_equal, not `!=`."""

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_admin_key_comparisons_are_constant_time(self) -> None:
        import inspect

        import maistro.privilege

        source = inspect.getsource(maistro.privilege)
        assert "!= self._admin_key" not in source
        assert source.count("secret_equal(") >= 4

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_elevation_grant_repr_hides_admin_key(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="test",
        )
        token = guard.propose_elevation(request)
        grant = guard.admin_sign_elevation(token, admin_key="pk_admin")

        rendered = repr(grant)
        assert "pk_admin" not in rendered
        assert grant.admin_key == "pk_admin"
        assert "shell:execute" in rendered
        assert "pk_user" in rendered

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_policy_repr_hides_admin_key(self, tmp_path: Path) -> None:
        from maistro.privilege import PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        policy_id = guard.create_policy(
            admin_key="pk_admin",
            user_public_key="pk_user",
            scope="file:read:/data/*",
            description="User can read data files",
        )

        policy = next(p for p in guard._policies if p.policy_id == policy_id)
        rendered = repr(policy)
        assert "pk_admin" not in rendered
        assert policy.admin_key == "pk_admin"
        assert "file:read:/data/*" in rendered
        assert "pk_user" in rendered

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_wrong_admin_key_still_denied_after_constant_time_swap(self, tmp_path: Path) -> None:
        from maistro.privilege import ElevationDeniedError, ElevationRequest, PrivilegeGuard

        guard = PrivilegeGuard(data_dir=str(tmp_path))
        guard.initialize(
            admin_public_key="pk_admin",
            user_public_key="pk_user",
        )

        request = ElevationRequest(
            user_public_key="pk_user",
            scope="shell:execute",
            justification="test",
        )
        token = guard.propose_elevation(request)

        with pytest.raises(ElevationDeniedError):
            guard.admin_sign_elevation(token, admin_key="pk_wrong")
        grant = guard.admin_sign_elevation(token, admin_key="pk_admin")
        assert grant.is_valid

        with pytest.raises(ElevationDeniedError):
            guard.rotate_admin_key(old_key="pk_wrong", new_key="pk_admin_v2")
        guard.rotate_admin_key(old_key="pk_admin", new_key="pk_admin_v2")

        with pytest.raises(ElevationDeniedError):
            guard.create_policy(
                admin_key="pk_wrong",
                user_public_key="pk_user",
                scope="file:read:/data/*",
                description="should be denied",
            )
        policy_id = guard.create_policy(
            admin_key="pk_admin_v2",
            user_public_key="pk_user",
            scope="file:read:/data/*",
            description="should succeed",
        )

        with pytest.raises(ElevationDeniedError):
            guard.revoke_policy(policy_id, admin_key="pk_wrong")
        guard.revoke_policy(policy_id, admin_key="pk_admin_v2")
        assert not guard.policy_allows(
            policy_id=policy_id,
            user_public_key="pk_user",
            action="file:read:/data/report.csv",
        )
