from __future__ import annotations

import pytest
from services.entra_entitlements import (
    EntraEntitlementPolicyError,
    EntraGroupGrant,
    EntraGroupMembership,
    EntraJitPolicy,
    IncompleteGroupMembershipError,
)

GROUP_USER = "11111111-1111-1111-1111-111111111111"
GROUP_OPERATOR = "22222222-2222-2222-2222-222222222222"
GROUP_ADMIN = "33333333-3333-3333-3333-333333333333"
GROUP_UNKNOWN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _policy(*, enabled: bool = True, **kwargs: object) -> EntraJitPolicy:
    defaults: dict[str, object] = {
        "eligible_groups": {
            GROUP_USER: EntraGroupGrant("user", frozenset({"runs:read"})),
            GROUP_OPERATOR: EntraGroupGrant(
                "operator", frozenset({"runs:create", "runs:cancel"})
            ),
        },
        "role_precedence": ("user", "operator", "admin"),
        "policy_version": "test-v1",
    }
    defaults.update(kwargs)
    return EntraJitPolicy(enabled=enabled, **defaults)  # type: ignore[arg-type]


def test_jit_is_denied_when_policy_is_disabled() -> None:
    decision = _policy(enabled=False).evaluate(
        EntraGroupMembership.complete_token([GROUP_USER])
    )

    assert decision.eligible is False
    assert decision.managed is None


def test_no_configured_eligible_group_denies_admission() -> None:
    decision = _policy().evaluate(EntraGroupMembership.complete_token([GROUP_UNKNOWN]))

    assert decision.eligible is False
    assert decision.managed is None


def test_one_group_produces_only_its_managed_role_and_permissions() -> None:
    decision = _policy().evaluate(EntraGroupMembership.complete_token([GROUP_USER]))

    assert decision.eligible is True
    assert decision.managed is not None
    assert decision.managed.role == "user"
    assert decision.managed.permissions == frozenset({"runs:read"})
    assert decision.managed.matched_group_ids == (GROUP_USER,)
    assert decision.managed.policy_version == "test-v1"
    assert decision.managed.membership_source == "token"


def test_multiple_groups_union_permissions_and_choose_role_by_explicit_precedence() -> None:
    policy = _policy()

    forward = policy.evaluate(
        EntraGroupMembership.complete_token([GROUP_USER, GROUP_OPERATOR])
    )
    reverse = policy.evaluate(
        EntraGroupMembership.complete_token([GROUP_OPERATOR, GROUP_USER])
    )

    assert forward == reverse
    assert forward.managed is not None
    assert forward.managed.role == "operator"
    assert forward.managed.permissions == frozenset(
        {"runs:read", "runs:create", "runs:cancel"}
    )
    assert forward.managed.matched_group_ids == (GROUP_USER, GROUP_OPERATOR)


def test_incomplete_or_overage_token_evidence_never_becomes_empty_membership() -> None:
    with pytest.raises(IncompleteGroupMembershipError, match="authoritative resolution"):
        _policy().evaluate(EntraGroupMembership.incomplete_token([GROUP_USER]))


def test_authoritative_resolver_membership_is_accepted_after_overage_resolution() -> None:
    decision = _policy().evaluate(
        EntraGroupMembership.complete_resolver([GROUP_OPERATOR])
    )

    assert decision.eligible is True
    assert decision.managed is not None
    assert decision.managed.membership_source == "resolver"


def test_group_removal_revokes_the_derived_managed_entitlement_on_next_evaluation() -> None:
    policy = _policy()
    admitted = policy.evaluate(EntraGroupMembership.complete_token([GROUP_OPERATOR]))
    removed = policy.evaluate(EntraGroupMembership.complete_token([GROUP_UNKNOWN]))

    assert admitted.eligible is True
    assert admitted.managed is not None
    assert removed.eligible is False
    assert removed.managed is None


def test_group_display_names_cannot_be_used_as_mapping_keys() -> None:
    with pytest.raises(EntraEntitlementPolicyError, match="group object UUIDs"):
        _policy(eligible_groups={"MAIstro Operators": EntraGroupGrant("operator")})


def test_case_variant_duplicate_group_ids_are_rejected_after_canonicalization() -> None:
    # GROUP_USER is all digits, so .upper() is a no-op; use a lettered UUID so
    # the two spellings are genuinely different before canonicalization.
    lower = "abcdefab-1111-1111-1111-111111111111"
    with pytest.raises(EntraEntitlementPolicyError, match="duplicate Entra group"):
        _policy(
            eligible_groups={
                lower: EntraGroupGrant("user"),
                lower.upper(): EntraGroupGrant("operator"),
            }
        )


def test_role_mapping_must_be_declared_in_precedence() -> None:
    with pytest.raises(EntraEntitlementPolicyError, match="absent from role_precedence"):
        _policy(eligible_groups={GROUP_ADMIN: EntraGroupGrant("superadmin")})


def test_configured_role_ceiling_rejects_admin_mapping_before_activation() -> None:
    with pytest.raises(EntraEntitlementPolicyError, match="above the configured SSO ceiling"):
        _policy(
            eligible_groups={GROUP_ADMIN: EntraGroupGrant("admin")},
            max_role="operator",
        )


def test_permission_ceiling_rejects_unknown_managed_permission_before_activation() -> None:
    with pytest.raises(
        EntraEntitlementPolicyError,
        match="outside the configured SSO ceiling",
    ):
        _policy(
            allowed_permissions=frozenset({"runs:read"}),
            eligible_groups={
                GROUP_OPERATOR: EntraGroupGrant(
                    "operator", frozenset({"runs:read", "approvals:admin"})
                )
            },
        )


def test_managed_result_is_separate_from_manual_local_grants() -> None:
    manual_permissions = frozenset({"workspace:owner"})
    decision = _policy().evaluate(EntraGroupMembership.complete_token([GROUP_USER]))

    assert decision.managed is not None
    assert manual_permissions.isdisjoint(decision.managed.permissions)
    assert manual_permissions | decision.managed.permissions == frozenset(
        {"workspace:owner", "runs:read"}
    )
