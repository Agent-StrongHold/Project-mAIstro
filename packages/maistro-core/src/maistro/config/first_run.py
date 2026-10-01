"""First-run setup defaults — one declaration, both provisioning paths (#443).

Both the terminal wizard (``maistro_bootstrap.wizard`` →
``build_bootstrap_credentials``) and the SPA wizard
(``hive-conductor`` frontend ``Setup.tsx``) read the defaults and
required-flags from here, rather than restating them independently.  The
``SetupCompleteBody`` API contract in ``routes/setup.py`` uses the same
declarations, so an operator who provisions from the terminal gets the same
account names, hardware preset, conductor name, and module mapping as one
who provisions from the browser.

The seam itself (`/v1/setup/complete`) is NOT duplicated — that endpoint is
one place.  This module is the *questions* seam: what is asked, its default,
and which are required — so neither wizard restates them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

#: The crypto / identity profile choices — declared here because both the
#: terminal wizard's question and the answers schema type their value from
#: it (#443: one declaration, no restatement).
CryptoProfile = Literal["distributed_identity_root", "no_crypto", "full_all_crypto"]

#: Admin account (break-glass superuser; blocked from chat by design).
DEFAULT_ADMIN_USERNAME: str = "maistro-admin"
#: Daily-driver account for normal use.
DEFAULT_DAILY_DRIVER_USERNAME: str = "maistro-user"
#: Hardware preset.  The terminal wizard deliberately does **not** prompt for
#: this: the server auto-resolves it from available resources at bring-up
#: time (SPEC-072726-3439 does not require a terminal hardware selection).
#: The SPA offers the choice but defaults to the same value, so the default is
#: one declaration rather than two silent restatements (#443 AC-2/DOD-2).
DEFAULT_HARDWARE_PRESET: str = "auto"
#: Human-readable conductor display name.
DEFAULT_CONDUCTOR_NAME: str = "Hive Conductor"
#: Default crypto profile — the terminal wizard's default and the SPA's mapping
#: seed both come from here (#443 AC-6: crypto-profile mapping).
DEFAULT_CRYPTO_PROFILE: CryptoProfile = "distributed_identity_root"
#: Default router model.  ``None`` means "use the server's configured
#: ``default_model`` setting" — the terminal path does not ask, so it sends
#: ``None`` (omitted), and the server picks its own default.  The SPA lets the
#: operator pick; the default is ``None`` so both paths agree when the
#: operator declines to choose.
DEFAULT_DEFAULT_MODEL: str | None = None


def crypto_profile_to_modules(crypto_profile: str) -> list[str]:
    """Map a crypto_profile choice to the ``optional_modules`` it implies.

    ``distributed_identity_root`` and ``full_all_crypto`` both imply
    ``crypto_identity``; only ``no_crypto`` suppresses it (#443 AC-6).
    """
    if crypto_profile == "no_crypto":
        return []
    return ["crypto_identity"]


class FirstRunQuestion(BaseModel):
    """Metadata for a single first-run question.

    ``default`` is the value a path uses when the operator does not give an
    explicit answer. ``required`` is the seam contract: a ``required`` field
    is refused by ``/v1/setup/complete`` when its key is absent; anything
    else may be omitted and the declared default applies (a present-but-blank
    username is still refused — omit the key instead of sending "").
    """

    model_config = {"populate_by_name": True}

    key: str
    label: str
    default: Any = None
    required: bool = False
    description: str = ""


#: Canonical ordering and metadata for every first-run question that feeds
#: the ``/v1/setup/complete`` payload.  The terminal wizard reads ``default``
#: for the fields it does not prompt for; the SPA reads the whole list (via
#: ``GET /v1/setup/questions``) to seed its wizard state.
FIRST_RUN_QUESTIONS: dict[str, FirstRunQuestion] = {
    "admin_username": FirstRunQuestion(
        key="admin_username",
        label="Admin user name",
        default=DEFAULT_ADMIN_USERNAME,
        # Not seam-required: an omitted key takes the declared default, and a
        # present-but-blank value is refused. Both wizards still surface the
        # question, prefilled with the default (#443 AC-1).
        required=False,
        description=(
            "Break-glass superuser account. Blocked from chat by design; "
            "use only when something is broken."
        ),
    ),
    "user_username": FirstRunQuestion(
        key="user_username",
        label="Daily driver user name",
        default=DEFAULT_DAILY_DRIVER_USERNAME,
        required=False,
        description=(
            "Your daily-driver account for chat, agents, missions, and everything you actually use."
        ),
    ),
    "admin_password": FirstRunQuestion(
        key="admin_password",
        label="Admin password",
        default=None,
        required=True,
        description="Collected once and never stored in the answers YAML.",
    ),
    "user_password": FirstRunQuestion(
        key="user_password",
        label="Daily driver password",
        default=None,
        required=True,
        description="Collected once and never stored in the answers YAML.",
    ),
    "hardware_preset": FirstRunQuestion(
        key="hardware_preset",
        label="Hardware preset",
        default=DEFAULT_HARDWARE_PRESET,
        required=False,
        description=(
            "Resource envelope for the conductor. 'auto' resolves from "
            "available host resources at bring-up; the operator may pick a "
            "named tier instead."
        ),
    ),
    "optional_modules": FirstRunQuestion(
        key="optional_modules",
        label="Optional modules",
        # The declared default is the module set the default crypto profile
        # implies — the SPA seeds its module toggles from this exact value, so
        # an operator who accepts defaults provisions the same modules on both
        # paths (#443 AC-2/AC-6).
        default=crypto_profile_to_modules(DEFAULT_CRYPTO_PROFILE),
        required=False,
        description=(
            "Derived from crypto_profile on the terminal path "
            "(crypto_identity unless no_crypto); selectable on the SPA path."
        ),
    ),
    "conductor_name": FirstRunQuestion(
        key="conductor_name",
        label="Conductor name",
        default=DEFAULT_CONDUCTOR_NAME,
        required=False,
        description="Display name shown in the UI.",
    ),
    "default_model": FirstRunQuestion(
        key="default_model",
        label="Default model",
        default=DEFAULT_DEFAULT_MODEL,
        required=False,
        description=(
            "Router model for intent classification. None = use the server's "
            "configured default; pick a model to override."
        ),
    ),
}
