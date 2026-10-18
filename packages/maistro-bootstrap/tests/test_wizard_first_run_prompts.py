"""#443: the terminal wizard's prompts read the shared declaration.

``collect_answers_interactive`` is the terminal path's collector: its
account-name prompts and the crypto-profile select must take their labels,
defaults and choices from ``maistro.config.first_run`` rather than
restating them — the SPA seeds the identical values from
``GET /v1/setup/questions``, so accepting defaults provisions the same
accounts whichever path collected the answers.

Before this suite existed the wizard's prompt lines measured unexecuted in
the diff-coverage gate while every downstream consumer of the staged
payload was tested — the collector itself had no test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_args

import pytest

from maistro.config.first_run import (
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_CRYPTO_PROFILE,
    DEFAULT_DAILY_DRIVER_USERNAME,
    FIRST_RUN_QUESTIONS,
    CryptoProfile,
)
from maistro_bootstrap import wizard

_STACK_BRINGUP_QUESTION = (
    "Request compose build from monorepo root (`docker compose build --pull never` on apply)?"
)
_FEATURES_QUESTION = (
    "Select feature slices (commands are printed unless you use --apply for stack only):"
)
_COMPOSE_ADDONS_QUESTION = "Optional compose add-ons (validate / Podman merge):"


@dataclass
class _Prompt:
    """One recorded questionary interaction, with an ``ask()`` answer."""

    method: str
    message: str
    kwargs: dict[str, Any]
    answer: Any

    def ask(self) -> Any:
        return self.answer


@dataclass
class StubQuestionary:
    """Records every prompt; each answer is scripted by exact message.

    A prompt with no scripted answer fails the test rather than returning
    ``None`` (which the wizard treats as abort) — an unscripted prompt must
    be a loud contract change, not a silent early exit.
    """

    select_answers: dict[str, Any] = field(default_factory=dict)
    text_answers: dict[str, Any] = field(default_factory=dict)
    confirm_answers: dict[str, Any] = field(default_factory=dict)
    checkbox_answers: dict[str, Any] = field(default_factory=dict)
    prompts: list[_Prompt] = field(default_factory=list)

    def _prompt(self, method: str, answers: dict[str, Any], message: str, **kwargs: Any) -> _Prompt:
        assert message in answers, f"unscripted {method} prompt: {message!r}"
        prompt = _Prompt(method=method, message=message, kwargs=kwargs, answer=answers[message])
        self.prompts.append(prompt)
        return prompt

    def select(self, message: str, choices: Any = None, **kwargs: Any) -> _Prompt:
        return self._prompt("select", self.select_answers, message, choices=choices, **kwargs)

    def text(self, message: str, **kwargs: Any) -> _Prompt:
        return self._prompt("text", self.text_answers, message, **kwargs)

    def confirm(self, message: str, **kwargs: Any) -> _Prompt:
        return self._prompt("confirm", self.confirm_answers, message, **kwargs)

    def checkbox(self, message: str, **kwargs: Any) -> _Prompt:
        return self._prompt("checkbox", self.checkbox_answers, message, **kwargs)


def _baseline_script(crypto_profile: str, admin: str, daily: str) -> StubQuestionary:
    """A full script through the wizard with one decision varied per test."""
    return StubQuestionary(
        select_answers={
            "Scaffold a product with Copier? (optional)": "(none)",
            "LLM gateway preference:": "litellm",
            "Observability backend (compose / manifest intent):": "none",
            "Deployment tier:": "local_docker",
            "Container runtime for stack bring-up:": "docker",
            "User / tenancy intent:": "skip",
            "Install delivery (same runtime behavior; source build takes longer):": "image_pull",
            "Sandbox profile (safe is default; unsupported options require building from source):": "safe",
            "Crypto / identity profile:": crypto_profile,
        },
        text_answers={
            f"{FIRST_RUN_QUESTIONS['admin_username'].label}:": admin,
            f"{FIRST_RUN_QUESTIONS['user_username'].label}:": daily,
        },
        confirm_answers={
            _STACK_BRINGUP_QUESTION: False,
            "Will you use an OpenAI API account?": False,
            "Will you use an Anthropic API account?": False,
        },
        checkbox_answers={
            _FEATURES_QUESTION: [],
            _COMPOSE_ADDONS_QUESTION: [],
        },
    )


def _run_collect(stub: StubQuestionary, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(wizard, "questionary", stub)
    monkeypatch.setattr(
        wizard, "detect_container_runtime", lambda: ("docker", "docker runtime present")
    )
    return wizard.collect_answers_interactive()


def test_the_prompts_read_the_declaration_not_restatements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Labels, defaults and crypto choices come from the declaration.

    The SPA seeds identical values from ``GET /v1/setup/questions``, so an
    operator who accepts these prompts provisions the same accounts and
    modules as one who accepts the SPA's defaults (#443 AC-1/AC-2).
    """
    stub = _baseline_script(
        crypto_profile=DEFAULT_CRYPTO_PROFILE,
        admin=FIRST_RUN_QUESTIONS["admin_username"].default,
        daily=FIRST_RUN_QUESTIONS["user_username"].default,
    )

    answers = _run_collect(stub, monkeypatch)

    crypto = next(p for p in stub.prompts if p.message == "Crypto / identity profile:")
    assert crypto.kwargs["choices"] == list(get_args(CryptoProfile))
    assert crypto.kwargs["default"] == DEFAULT_CRYPTO_PROFILE

    admin_prompt = next(
        p for p in stub.prompts if p.message == f"{FIRST_RUN_QUESTIONS['admin_username'].label}:"
    )
    assert admin_prompt.kwargs["default"] == str(DEFAULT_ADMIN_USERNAME)
    daily_prompt = next(
        p for p in stub.prompts if p.message == f"{FIRST_RUN_QUESTIONS['user_username'].label}:"
    )
    assert daily_prompt.kwargs["default"] == str(DEFAULT_DAILY_DRIVER_USERNAME)

    assert answers.crypto_profile == DEFAULT_CRYPTO_PROFILE
    assert answers.admin_user == DEFAULT_ADMIN_USERNAME
    assert answers.daily_driver_user == DEFAULT_DAILY_DRIVER_USERNAME


def test_operator_answers_override_the_declared_prompt_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed answers win over the declared prompt defaults.

    The defaults seed the prompts; they must not override what the operator
    actually answered — including the ``no_crypto`` choice that suppresses
    the identity module on the terminal path.
    """
    stub = _baseline_script(crypto_profile="no_crypto", admin="ada", daily="charles")

    answers = _run_collect(stub, monkeypatch)

    assert answers.crypto_profile == "no_crypto"
    assert answers.admin_user == "ada"
    assert answers.daily_driver_user == "charles"
