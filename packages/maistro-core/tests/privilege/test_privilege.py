"""SPEC-012: Admin / user1 Privilege Separation — mandatory two-tier model.

These tests define the contract for the privilege system. All tests should
FAIL until the privilege module is implemented.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

_TRUSTED_SIGNING_KEY = "host-owned-users-integrity-key"


def _legacy_last_admin_wins_key(content: str) -> str:
    """Replicate the pre-fix (6c4aa4bb) ``_parse_users`` anchor selection.

    The vulnerable verifier signed/verified with the ``public_key`` of the
    LAST admin entry in the file. This helper exists only to prove that the
    forged constructions below carry a signature that is VALID under that
    file-chosen anchor — i.e. they would authenticate on the vulnerable code
    — so rejection by the external trust root is meaningful, not accidental.
    """
    admin_key = ""
    current: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if line == "[[users]]":
            if current and current.get("role") == "admin":
                admin_key = current["public_key"]
            current = {}
        elif "=" in line and current is not None:
            k, v = line.split("=", 1)
            current[k.strip()] = v.strip().strip('"')
    if current and current.get("role") == "admin":
        admin_key = current["public_key"]
    return admin_key


class TestUsersToml:
    """AC: users.toml authenticity depends on an external trust root."""

    def test_load_valid_users_toml(self, tmp_path: Path) -> None:
        from maistro.privilege import UsersStore

        store = UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        store.initialize(
            admin_name="alice",
            admin_public_key="pk_admin_001",
            user_name="bob",
            user_public_key="pk_user_001",
        )

        assert _TRUSTED_SIGNING_KEY not in (tmp_path / "users.toml").read_text()
        loaded = UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        assert loaded.admin().name == "alice"
        assert loaded.user_by_public_key("pk_user_001").name == "bob"

    def test_refuses_exact_forged_self_key_construction(self, tmp_path: Path) -> None:
        """The audit repro: a single-admin file naming the attacker's key.

        The attacker writes arbitrary users/roles/permissions, makes their own
        key the (only, therefore last-selected) admin key, and signs with that
        same key. On the pre-fix verifier this construction LOADED with
        ``admin=eve/attacker-controlled-key``; the external trust root must
        reject it.
        """
        from maistro.privilege import UsersStore, UsersTamperError, _verify

        attacker_key = "attacker-controlled-key"
        forged_content = """[[users]]
name = "eve"
public_key = "attacker-controlled-key"
role = "admin"
permissions = "*"
"""
        forged_signature = hmac.new(
            attacker_key.encode(), forged_content.encode(), hashlib.sha256
        ).hexdigest()
        (tmp_path / "users.toml").write_text(f"# sig: {forged_signature}\n{forged_content}")

        # The forgery is well-formed: it authenticates under the legacy
        # file-parsed anchor (last-admin-wins), so rejection below is due to
        # the external trust root, not a malformed signature.
        assert _legacy_last_admin_wins_key(forged_content) == attacker_key
        assert _verify(forged_content, attacker_key, forged_signature)

        with pytest.raises(UsersTamperError, match="Signature verification failed"):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)

    def test_refuses_forged_last_admin_anchor_construction(self, tmp_path: Path) -> None:
        """The audit repro against last-admin-wins: attacker controls the LAST admin.

        The pre-fix parser verified with the LAST admin entry's key. An
        attacker keeps a plausible first admin and appends their own admin
        entry, then signs the whole file with the attacker key — the exact
        construction the audit reproduced and the pre-fix verifier accepted
        (loading an entirely attacker-authored file, first admin included).
        """
        from maistro.privilege import UsersStore, UsersTamperError, _verify

        attacker_key = "attacker-controlled-key"
        forged_content = """[[users]]
name = "alice"
public_key = "pk_admin_001"
role = "admin"
permissions = "*"

[[users]]
name = "eve"
public_key = "attacker-controlled-key"
role = "admin"
permissions = "*"
"""
        forged_signature = hmac.new(
            attacker_key.encode(), forged_content.encode(), hashlib.sha256
        ).hexdigest()
        (tmp_path / "users.toml").write_text(f"# sig: {forged_signature}\n{forged_content}")

        # Valid under the legacy last-admin-wins anchor; a verifier anchored
        # to any file-parsed value would accept this file wholesale.
        assert _legacy_last_admin_wins_key(forged_content) == attacker_key
        assert _verify(forged_content, attacker_key, forged_signature)

        with pytest.raises(UsersTamperError, match="Signature verification failed"):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)

    def test_authenticated_trust_root_migration_via_public_api(self, tmp_path: Path) -> None:
        """The documented rotation path: authenticate under the CURRENT external
        secret, then re-sign the verified roster under the NEW one.

        Every step uses the shipped public API. An attacker-nominated "current
        key" does not authenticate the artifact (it was signed with the real
        current root), aborting the migration before anything is written, and
        after a completed migration only the new external root is authoritative.
        """
        from maistro.privilege import UsersStore, UsersTamperError

        store = UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        store.initialize("alice", "pk_admin", "lilly", "pk_lilly")

        # Migration step 1: authenticate the artifact under the current root.
        with pytest.raises(UsersTamperError):
            UsersStore(
                data_dir=str(tmp_path),
                trusted_signing_key="attacker-nominated-current-key",
            )
        assert "attacker-nominated-current-key" not in (tmp_path / "users.toml").read_text()

        verified = UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        roster = (verified.admin(), verified.user_by_public_key("pk_lilly"))
        # Move the authenticated artifact aside (rollback backup); the new
        # store re-signs from scratch under the new external root.
        (tmp_path / "users.toml").rename(tmp_path / "users.toml.pre-rotation")
        replacement = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key="host-owned-users-integrity-key-v2",
        )
        # Migration step 2: re-sign the roster the verified store just
        # authenticated, under the new external root.
        replacement.initialize(
            roster[0].name,
            roster[0].public_key,
            roster[1].name,
            roster[1].public_key,
        )

        # Only the new external root is authoritative afterwards.
        with pytest.raises(UsersTamperError):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        reloaded = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key="host-owned-users-integrity-key-v2",
        )
        assert reloaded.admin().name == "alice"
        assert reloaded.user_by_public_key("pk_lilly").name == "lilly"
        on_disk = (tmp_path / "users.toml").read_text()
        assert _TRUSTED_SIGNING_KEY not in on_disk
        assert "host-owned-users-integrity-key-v2" not in on_disk

    def test_file_cannot_initiate_or_authorize_rotation(self, tmp_path: Path) -> None:
        """The file cannot choose, replace, or trigger its own authority.

        An attacker-authored users.toml that names a new signing key (or any
        other directive) and carries a matching attacker HMAC is rejected
        outright, and the deprecated store exposes no file-triggerable
        migration entry point at all.
        """
        from maistro.privilege import UsersStore, UsersTamperError, _verify

        store = UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        store.initialize("alice", "pk_admin", "bob", "pk_user")

        attacker_key = "attacker-controlled-key"
        forged_content = """trusted_signing_key = "attacker-controlled-key"

[[users]]
name = "eve"
public_key = "attacker-controlled-key"
role = "admin"
permissions = "*"
"""
        forged_signature = hmac.new(
            attacker_key.encode(), forged_content.encode(), hashlib.sha256
        ).hexdigest()
        (tmp_path / "users.toml").write_text(f"# sig: {forged_signature}\n{forged_content}")
        # The forgery is internally consistent; it is the trust root that
        # rejects it, not a malformed signature.
        assert _verify(forged_content, attacker_key, forged_signature)

        with pytest.raises(UsersTamperError, match="Signature verification failed"):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)

        # No migration/rotation entry point exists on the public surface: the
        # only mutating API is initialize(), which takes its trust root from
        # the host-supplied constructor argument, never from the file.
        # users() is a read-only view over already-authenticated data.
        public_api = {name for name in vars(UsersStore) if not name.startswith("_")}
        assert public_api == {"initialize", "admin", "user_by_public_key", "users"}

    def test_single_user_roster_rotation_follows_documented_path(self, tmp_path: Path) -> None:
        """The documented rotation also works for single-user rosters.

        A valid ``UsersStore(..., allow_single_user=True)`` roster contains
        no secondary user, so the naive two-user sample step
        ``verified.user_by_public_key(expected_user_public_key)`` fails there
        (LookupError), and re-initializing single-user mode without the
        ``allow_single_user=True`` constructor flag fails closed
        (InsufficientUsersError) instead of silently rewriting the roster.
        The documented procedure therefore derives the roster shape from the
        authenticated artifact via ``users()`` before re-signing.
        """
        from maistro.privilege import InsufficientUsersError, UsersStore, UsersTamperError

        store = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key=_TRUSTED_SIGNING_KEY,
            allow_single_user=True,
        )
        store.initialize("solo-admin", "pk_admin_solo")

        # Step 1: authenticate the artifact under the CURRENT root and
        # derive the roster shape from authenticated data: exactly one user.
        verified = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key=_TRUSTED_SIGNING_KEY,
            allow_single_user=True,
        )
        assert verified.users() == (verified.admin(),)
        single_user_roster = len(verified.users()) == 1
        assert single_user_roster
        verified_admin = verified.admin()
        assert verified_admin.name == "solo-admin"
        # The naive two-user migration step cannot work on this roster: no
        # secondary user exists to look up.
        with pytest.raises(LookupError):
            verified.user_by_public_key("pk_secondary")

        # Step 2: move the authenticated artifact aside, then re-sign under
        # the NEW root. Forgetting the allow_single_user flag fails closed
        # without writing anything rather than silently upgrading the roster.
        (tmp_path / "users.toml").rename(tmp_path / "users.toml.pre-rotation")
        with pytest.raises(InsufficientUsersError):
            UsersStore(
                data_dir=str(tmp_path),
                trusted_signing_key="host-owned-users-integrity-key-v2",
            ).initialize(verified_admin.name, verified_admin.public_key)
        assert not (tmp_path / "users.toml").exists()

        replacement = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key="host-owned-users-integrity-key-v2",
            allow_single_user=True,
        )
        replacement.initialize(verified_admin.name, verified_admin.public_key)

        # Only the new external root is authoritative afterwards, and the
        # single-user shape plus admin identity survived the rotation.
        with pytest.raises(UsersTamperError):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        reloaded = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key="host-owned-users-integrity-key-v2",
        )
        assert reloaded.admin().name == "solo-admin"
        assert len(reloaded.users()) == 1
        on_disk = (tmp_path / "users.toml").read_text()
        assert _TRUSTED_SIGNING_KEY not in on_disk
        assert "host-owned-users-integrity-key-v2" not in on_disk

    def test_unsigned_single_line_fails_closed(self, tmp_path: Path) -> None:
        from maistro.privilege import UsersStore, UsersTamperError

        (tmp_path / "users.toml").write_text('[[users]] name = "eve"')

        with pytest.raises(UsersTamperError, match="Missing content"):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)

    def test_empty_external_trust_root_is_rejected(self, tmp_path: Path) -> None:
        from maistro.privilege import UsersStore, UsersTrustRootError

        with pytest.raises(UsersTrustRootError, match="external"):
            UsersStore(data_dir=str(tmp_path), trusted_signing_key="")


class TestMandatoryTwoUsers:
    """AC: Setup wizard cannot complete with fewer than two users."""

    def test_refuses_single_user_init(self, tmp_path: Path) -> None:
        from maistro.privilege import InsufficientUsersError, UsersStore

        store = UsersStore(data_dir=str(tmp_path), trusted_signing_key=_TRUSTED_SIGNING_KEY)
        with pytest.raises(InsufficientUsersError):
            store.initialize(
                admin_name="alice",
                admin_public_key="pk_admin",
            )

    def test_no_single_user_env_override(self, tmp_path: Path) -> None:
        from maistro.privilege import InsufficientUsersError, UsersStore

        store = UsersStore(
            data_dir=str(tmp_path),
            trusted_signing_key=_TRUSTED_SIGNING_KEY,
            allow_single_user=False,
        )
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
