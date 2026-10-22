"""#443: the first-run question declaration, pinned at its home package.

``maistro.config.first_run`` is the one declaration of the first-run
questions that both provisioning paths read rather than restate: the
terminal wizard (``maistro_bootstrap.wizard``) prompts with the declared
labels and defaults, the server (``SetupCompleteBody`` and
``GET /v1/setup/questions``) serves it, and the SPA seeds its wizard state
from the served payload.

These tests pin the declaration contract where the module lives — this is
also the only suite the ``--source=packages/maistro-core/src/maistro``
coverage producer runs, so without them the declaration measures as
unexecuted code in the diff-coverage gate even while both consumer suites
pass. The end-to-end parity of the two wire payloads is asserted over the
real HTTP boundary in
``packages/hive-conductor/backend/tests/test_setup_first_run_questions.py``.
"""

from __future__ import annotations

from typing import get_args

from maistro.config.first_run import (
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_CONDUCTOR_NAME,
    DEFAULT_CRYPTO_PROFILE,
    DEFAULT_DAILY_DRIVER_USERNAME,
    DEFAULT_DEFAULT_MODEL,
    DEFAULT_HARDWARE_PRESET,
    FIRST_RUN_QUESTIONS,
    CryptoProfile,
    FirstRunQuestion,
    crypto_profile_to_modules,
)


def test_crypto_profile_mapping_is_total_over_the_declared_choices() -> None:
    """Every wizard choice maps; only ``no_crypto`` suppresses the module."""
    assert crypto_profile_to_modules("no_crypto") == []
    assert crypto_profile_to_modules("distributed_identity_root") == ["crypto_identity"]
    assert crypto_profile_to_modules("full_all_crypto") == ["crypto_identity"]
    # The mapping's domain is exactly the declared profile choices.
    assert set(get_args(CryptoProfile)) == {
        "distributed_identity_root",
        "no_crypto",
        "full_all_crypto",
    }


def test_the_mapping_is_total_beyond_the_literal_too() -> None:
    """An unknown profile still implies the identity module, never silence.

    The function's contract is "everything except an explicit no_crypto
    carries the identity module", so a profile added to the Literal later
    cannot silently provision a keyless module set.
    """
    assert crypto_profile_to_modules("some_future_profile") == ["crypto_identity"]


def test_the_seam_required_questions_are_exactly_the_two_passwords() -> None:
    """Only the passwords are refused when their key is absent.

    Everything else takes the declared default when omitted — that is the
    seam contract ``/v1/setup/complete`` enforces and both wizards rely on.
    """
    required = {key for key, question in FIRST_RUN_QUESTIONS.items() if question.required}
    assert required == {"admin_password", "user_password"}


def test_every_declared_default_is_the_constant_it_names() -> None:
    """Each question's default is the declared constant, not a restatement.

    A default restated here and in ``SetupCompleteBody`` would be two
    declarations again, which is the defect #443 exists to close.
    """
    expected = {
        "admin_username": DEFAULT_ADMIN_USERNAME,
        "user_username": DEFAULT_DAILY_DRIVER_USERNAME,
        "admin_password": None,
        "user_password": None,
        "hardware_preset": DEFAULT_HARDWARE_PRESET,
        "optional_modules": crypto_profile_to_modules(DEFAULT_CRYPTO_PROFILE),
        "conductor_name": DEFAULT_CONDUCTOR_NAME,
        "default_model": DEFAULT_DEFAULT_MODEL,
    }
    assert {key: q.default for key, q in FIRST_RUN_QUESTIONS.items()} == expected
    # No credential material is ever a declared default: a password default
    # would leak into both the questions endpoint and the SPA seed state.
    assert DEFAULT_ADMIN_USERNAME and DEFAULT_DAILY_DRIVER_USERNAME
    assert all(
        not key.endswith("_password") or FIRST_RUN_QUESTIONS[key].default is None
        for key in FIRST_RUN_QUESTIONS
    )


def test_declaration_keys_are_the_canonical_set_in_served_order() -> None:
    """The dict order is the served order, and no question is unnamed.

    The SPA renders its wizard steps from the served sequence, so a reorder
    or a renamed key is a contract change and must be visible here.
    """
    assert tuple(FIRST_RUN_QUESTIONS) == (
        "admin_username",
        "user_username",
        "admin_password",
        "user_password",
        "hardware_preset",
        "optional_modules",
        "conductor_name",
        "default_model",
    )
    for key, question in FIRST_RUN_QUESTIONS.items():
        assert question.key == key
        assert question.label
        assert isinstance(question, FirstRunQuestion)


def test_questions_round_trip_through_the_served_shape() -> None:
    """``model_dump`` → ``model_validate`` preserves every question.

    ``GET /v1/setup/questions`` serves ``q.model_dump()``; the SPA posts
    answers keyed by these field names, so the served shape is the wire
    contract and must round-trip losslessly.
    """
    for question in FIRST_RUN_QUESTIONS.values():
        assert FirstRunQuestion.model_validate(question.model_dump()) == question
