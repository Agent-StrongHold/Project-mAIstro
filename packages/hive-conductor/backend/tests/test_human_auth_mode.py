from services.human_auth_mode import HumanAuthModePolicy


def test_local_mode_allows_password_and_disables_entra() -> None:
    policy = HumanAuthModePolicy(mode="local")

    assert policy.ordinary_password_login_enabled is True
    assert policy.entra_login_enabled is False


def test_entra_mode_disables_ordinary_password_and_enables_entra() -> None:
    policy = HumanAuthModePolicy(mode="entra")

    assert policy.ordinary_password_login_enabled is False
    assert policy.password_login_enabled() is False
    assert policy.entra_login_enabled is True


def test_hybrid_mode_allows_both_login_front_doors() -> None:
    policy = HumanAuthModePolicy(mode="hybrid")

    assert policy.ordinary_password_login_enabled is True
    assert policy.password_login_enabled() is True
    assert policy.entra_login_enabled is True


def test_entra_mode_does_not_gain_break_glass_from_caller_intent_alone() -> None:
    policy = HumanAuthModePolicy(mode="entra", allow_break_glass_password=False)

    assert policy.password_login_enabled(break_glass=True) is False


def test_explicit_operator_break_glass_can_enable_distinct_password_path() -> None:
    policy = HumanAuthModePolicy(mode="entra", allow_break_glass_password=True)

    assert policy.password_login_enabled() is False
    assert policy.password_login_enabled(break_glass=True) is True


def test_hybrid_does_not_depend_on_break_glass_configuration() -> None:
    policy = HumanAuthModePolicy(mode="hybrid", allow_break_glass_password=False)

    assert policy.password_login_enabled() is True
    assert policy.password_login_enabled(break_glass=True) is True


def test_local_mode_disables_all_oauth_provider_front_doors() -> None:
    policy = HumanAuthModePolicy(mode="local")

    assert policy.oauth_provider_enabled("entra") is False
    assert policy.oauth_provider_enabled("oidc") is False


def test_entra_only_mode_exposes_only_the_entra_provider() -> None:
    policy = HumanAuthModePolicy(mode="entra")

    assert policy.oauth_provider_enabled("entra") is True
    assert policy.oauth_provider_enabled("oidc") is False


def test_hybrid_mode_preserves_configured_oauth_provider_support() -> None:
    policy = HumanAuthModePolicy(mode="hybrid")

    assert policy.oauth_provider_enabled("entra") is True
    assert policy.oauth_provider_enabled("oidc") is True
