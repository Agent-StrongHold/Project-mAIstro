"""#443: one declaration of the first-run questions; both collection paths agree.

Two wizards collect the same first-run answers: the terminal wizard
(``maistro-install`` -> ``build_bootstrap_credentials``) and the SPA wizard
(``Setup.tsx``, seeded from ``GET /v1/setup/questions``). The acceptance bar is
that identical answers produce an identical ``/v1/setup/complete`` payload —
defaults included — so the parity is asserted here *directly*, by comparing
the two wire payloads, instead of asserting each path against its own
literals. The served declaration, the server model's field defaults, and the
terminal builder all trace back to ``maistro.config.first_run``.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from maistro.config.first_run import (  # noqa: E402
    FIRST_RUN_QUESTIONS,
    crypto_profile_to_modules,
)
from maistro_bootstrap.credentials import build_bootstrap_credentials  # noqa: E402
from maistro_bootstrap.schema import InstallAnswersV1  # noqa: E402

# The only answers an operator must type on either path; identical on both
# sides so the payloads are comparable.
ADMIN_PW = "s3cret-admin-pw"
USER_PW = "s3cret-user-pw"


def _served_questions() -> dict[str, dict]:
    """The SPA's view of the declaration, over the real HTTP boundary."""
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get("/v1/setup/questions")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "first_run_questions"
    return body["questions"]


def _spa_payload(questions: dict[str, dict], **operator_answers: object) -> dict:
    """What the SPA wizard would POST after seeding from the declaration.

    Every field starts at the served default; the operator's explicit answers
    (passwords, a preset, toggled modules...) overlay them — exactly the body
    ``Setup.tsx`` assembles.
    """
    body: dict = {key: q["default"] for key, q in questions.items()}
    body.update(operator_answers)
    return body


def test_identical_answers_produce_identical_payloads_whichever_path_collected_them() -> None:
    """THE #443 parity assertion: terminal wire payload == SPA wire payload.

    Both sides carry the same two explicit answers (the passwords). Every
    other field is a default on both sides — the terminal builder's from the
    declaration, the SPA's from the served declaration — so the payloads must
    be equal wholesale, not field-by-field per path.
    """
    from routes.setup import SetupCompleteBody

    terminal = build_bootstrap_credentials(
        InstallAnswersV1(), admin_password=ADMIN_PW, user_password=USER_PW
    )
    spa = _spa_payload(_served_questions(), admin_password=ADMIN_PW, user_password=USER_PW)

    assert terminal == spa

    # And the seam parses both to the same provisioned state.
    assert SetupCompleteBody.model_validate(terminal) == SetupCompleteBody.model_validate(spa)


def test_crypto_profile_mapping_keeps_both_paths_in_agreement() -> None:
    """#443 AC-6: the operator declines crypto on both paths.

    The terminal derives ``optional_modules`` from its crypto-profile answer;
    the SPA deselects the seeded module. The mapped sets agree, so the
    payloads still match.
    """
    terminal = build_bootstrap_credentials(
        InstallAnswersV1.model_validate({"crypto_profile": "no_crypto"}),
        admin_password=ADMIN_PW,
        user_password=USER_PW,
    )
    spa = _spa_payload(
        _served_questions(),
        admin_password=ADMIN_PW,
        user_password=USER_PW,
        optional_modules=[],
    )
    assert terminal == spa


def test_crypto_profile_mapping_is_total_over_the_wizard_choices() -> None:
    """Every profile except no_crypto implies the identity module; no_crypto
    implies none. The SPA toggle seed is the same mapping evaluated at the
    declared default profile."""
    assert crypto_profile_to_modules("distributed_identity_root") == ["crypto_identity"]
    assert crypto_profile_to_modules("full_all_crypto") == ["crypto_identity"]
    assert crypto_profile_to_modules("no_crypto") == []
    assert (
        crypto_profile_to_modules("distributed_identity_root")
        == FIRST_RUN_QUESTIONS["optional_modules"].default
    )


def test_questions_endpoint_serves_the_declaration() -> None:
    """The SPA reads the declaration, not a server-side restatement of it."""
    served = _served_questions()
    assert set(served) == set(FIRST_RUN_QUESTIONS)
    for key, declared in FIRST_RUN_QUESTIONS.items():
        entry = served[key]
        assert set(entry) == {"key", "label", "default", "required", "description"}
        assert entry["key"] == declared.key
        assert entry["label"] == declared.label
        assert entry["default"] == declared.default
        assert entry["required"] == declared.required
        # Question metadata only — a default that carried credential material
        # would make this public endpoint an enumerator.
        assert not isinstance(entry["default"], str) or "password" not in entry["key"]


def test_server_field_defaults_come_from_the_declaration() -> None:
    """The hinge of the parity test: when a collector omits a field, the
    server fills it with the *declared* default, so an omission can never
    diverge from what the other path states explicitly."""
    from routes.setup import SetupCompleteBody

    served = _served_questions()
    # Fields the server accepts that are NOT operator questions (#287):
    # wizard-internal control metadata attached to the completion payload,
    # documented here so a new field cannot silently dodge the parity check
    # below. model_availability carries the SPA's final gateway-preflight
    # verdict ("verified"/"unverified") — the server never defaults it to a
    # question answer, and the terminal collector does not state it.
    non_question_fields = {"model_availability"}
    for name, field in SetupCompleteBody.model_fields.items():
        if name in non_question_fields:
            assert name not in served
            continue
        declared = served[name]
        if field.is_required():
            assert declared["required"] is True
            continue
        if name == "optional_modules":
            # An ABSENT module list defaults to "none" at the seam: silently
            # provisioning an identity root on a missing key would be a
            # side-effectful default. The declared default is the collector
            # seed (the SPA toggle pre-fill), parity-asserted above.
            assert declared["required"] is False
            continue
        assert declared["required"] is False
        assert field.default == declared["default"]
    # And the declaration covers every question-bearing field: no orphan
    # question, no undeclared accepted field beyond the documented control
    # metadata.
    assert set(served) | non_question_fields == set(SetupCompleteBody.model_fields)


def test_omitted_hardware_preset_takes_the_declared_default() -> None:
    """#443 AC-3: the terminal path states the documented default and the
    SPA states its pick or the same default, so an omitted preset resolves to
    the declared value rather than an error or a second default."""
    from routes.setup import SetupCompleteBody

    body = SetupCompleteBody.model_validate(
        {
            "admin_username": "some-admin",
            "admin_password": ADMIN_PW,
            "user_username": "some-user",
            "user_password": USER_PW,
        }
    )
    assert body.hardware_preset == FIRST_RUN_QUESTIONS["hardware_preset"].default


def test_blank_usernames_are_refused_not_defaulted() -> None:
    """#443 DOD-1: a collector that drops a name must omit the key (default
    applies) — an empty string is refused instead of provisioning a blank
    account name."""
    from fastapi import HTTPException
    from routes.setup import _validate_direct_setup_body

    for field in ("admin_username", "user_username"):
        body: dict = {
            "hardware_preset": "auto",
            "admin_username": "admin-x",
            "admin_password": ADMIN_PW,
            "user_username": "user-x",
            "user_password": USER_PW,
        }
        body[field] = "   "
        with pytest.raises(HTTPException) as exc_info:
            _validate_direct_setup_body(body)
        assert exc_info.value.status_code == 422


def test_terminal_staged_defaults_provision_the_declaration_named_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#443 DOD-1 end to end: the staged file the terminal installer POSTs,
    accepted defaults and all, provisions accounts named by the shared
    declaration — the same payload the SPA path posts (parity-asserted
    above), so neither path can produce a differently-named admin."""
    import stores
    from fastapi.testclient import TestClient
    from main import app
    from models.schemas import HiveUser
    from routes import setup as setup_routes
    from services import registration_policy as rp
    from services.model_store import JsonStore, ModelStore

    from maistro.config.first_run import (
        DEFAULT_ADMIN_USERNAME,
        DEFAULT_CONDUCTOR_NAME,
        DEFAULT_DAILY_DRIVER_USERNAME,
        DEFAULT_HARDWARE_PRESET,
    )

    monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))
    monkeypatch.setattr(stores, "username_claims", JsonStore("username_claims"))
    monkeypatch.setattr(setup_routes, "_get_kv", lambda: None)

    staged = build_bootstrap_credentials(
        InstallAnswersV1.model_validate({"crypto_profile": "no_crypto"}),
        admin_password=ADMIN_PW,
        user_password=USER_PW,
    )
    response = TestClient(app).post("/v1/setup/complete", json=staged)

    assert response.status_code == 200
    body = response.json()
    config = body["config"]
    assert stores.users["admin"].username == DEFAULT_ADMIN_USERNAME
    assert stores.users["user"].username == DEFAULT_DAILY_DRIVER_USERNAME
    assert config["optional_modules"] == staged["optional_modules"] == []
    assert config["hardware_preset"] == staged["hardware_preset"] == DEFAULT_HARDWARE_PRESET
    assert config["conductor_name"] == DEFAULT_CONDUCTOR_NAME
    # The SPA path posts the byte-identical payload (asserted above), so this
    # provisioned state is the one both paths reach.
    assert body["setup_complete"] is True
    assert rp.describe()["mode"] == "closed"
