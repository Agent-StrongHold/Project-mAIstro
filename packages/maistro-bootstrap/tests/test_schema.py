"""Schema validation for install answers."""

import pytest
from pydantic import ValidationError

from maistro_bootstrap.schema import (
    InstallAnswersV1,
    describe_validation_error,
    merge_session_payload,
    parse_answers_dict,
)


def test_merge_session_partial() -> None:
    out = merge_session_payload({"features": ["core_lib"], "llm_gateway": "direct"})
    assert out.features == ["core_lib"]
    assert out.llm_gateway == "direct"
    assert out.schema_version == "1"


def test_rejects_non_list_features() -> None:
    with pytest.raises(ValidationError):
        parse_answers_dict({"schema_version": "1", "features": "core_lib"})


def test_accepts_minimal_dict() -> None:
    a = parse_answers_dict({"schema_version": "1", "features": ["core_lib"]})
    assert a.stack_bringup == "none"


def _error_pairs(exc: ValidationError) -> list[tuple[str, str]]:
    return [(e["type"], ".".join(str(p) for p in e.get("loc", ()))) for e in exc.errors()]


# --- #810: unknown install-answer keys are errors, not silent defaults -------


@pytest.mark.parametrize("typo", ["sandbox_profle", "crypto_profil", "additonal_users"])
def test_misspelled_security_field_fails_naming_the_key(typo: str) -> None:
    """AC-3: a misspelled security field is a validation error that names the
    typo'd key, so the install cannot silently fall back to the field default."""
    with pytest.raises(ValidationError) as excinfo:
        parse_answers_dict({"schema_version": "1", typo: "x"})
    assert ("extra_forbidden", typo) in _error_pairs(excinfo.value)
    # The correctly-spelled key still validates — proving the typo, not the
    # field, is what fails.
    correct = {
        "sandbox_profle": "sandbox_profile",
        "crypto_profil": "crypto_profile",
        "additonal_users": "additional_users",
    }[typo]
    correct_value: dict[str, object] = {
        "sandbox_profile": "developer",
        "crypto_profile": "no_crypto",
        "additional_users": ["extra"],
    }
    assert parse_answers_dict({"schema_version": "1", correct: correct_value[correct]}) is not None


def test_arbitrary_unknown_key_is_forbidden_too() -> None:
    """AC-4: generic typos hit the same explicit extra=forbid rejection as
    security fields — one mechanism, not a field-by-field allowlist."""
    with pytest.raises(ValidationError) as excinfo:
        parse_answers_dict({"schema_version": "1", "frobnicate": True})
    assert ("extra_forbidden", "frobnicate") in _error_pairs(excinfo.value)


def test_extra_forbid_config_is_set() -> None:
    """AC-1: the strictness is schema-level, not caller-level."""
    assert InstallAnswersV1.model_config.get("extra") == "forbid"


def test_merge_session_payload_unknown_key_fails() -> None:
    """The Conductor install-session merge path rejects unknown keys by name
    instead of dropping them and returning defaults."""
    with pytest.raises(ValidationError) as excinfo:
        merge_session_payload({"sandbox_profle": "developer"})
    assert ("extra_forbidden", "sandbox_profle") in _error_pairs(excinfo.value)


def test_describe_validation_error_names_unknown_keys() -> None:
    """AC-2: the shared error formatter names each unknown key for CLI/API use."""
    with pytest.raises(ValidationError) as excinfo:
        parse_answers_dict({"schema_version": "1", "crypto_profil": "x", "zz": 1})
    msg = describe_validation_error(excinfo.value)
    assert "crypto_profil" in msg and "zz" in msg
    assert "unknown install-answer key" in msg


def test_describe_validation_error_keeps_typed_errors() -> None:
    with pytest.raises(ValidationError) as excinfo:
        parse_answers_dict({"schema_version": "1", "sandbox_profile": "yolo"})
    msg = describe_validation_error(excinfo.value)
    assert "sandbox_profile" in msg
    assert "unknown install-answer key" not in msg


def test_no_implicit_aliases_absorb_unknown_keys() -> None:
    """AC-5: no field declares an alias, so nothing can masquerade as a known
    key; any future alias must be added explicitly and versioned, not rely on
    generic extra-field acceptance."""
    for name, field in InstallAnswersV1.model_fields.items():
        assert field.alias is None, name
        assert field.validation_alias is None, name
        assert field.serialization_alias is None, name
