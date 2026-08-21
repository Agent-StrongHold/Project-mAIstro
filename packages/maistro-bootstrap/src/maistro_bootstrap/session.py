"""Session defaults for the Hive install wizard API (SPEC-180).

`routes/install.py` in hive-conductor imports `get_session_defaults` and serves
it as `GET`/`POST /v1/install/session`. `POST /v1/install/plan` is retired —
the session shape is the single wizard contract (see test_api.py's
`test_install_plan_endpoint_retired`).
"""

from __future__ import annotations

from typing import Any

from maistro_bootstrap.schema import InstallAnswersV1, merge_session_payload

SECRETS_POLICY = (
    "Answers carry names and intent flags only — never API keys, passwords, or mnemonics. "
    "See docs/install/default-installer.md."
)


def get_session_defaults(partial: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the wizard template (no partial) or a merged, validated session.

    GET /v1/install/session  -> kind=maistro_install_session_template + defaults
    POST /v1/install/session -> kind=maistro_install_session + normalized answers
    """
    if partial is None:
        return {
            "kind": "maistro_install_session_template",
            "defaults": InstallAnswersV1().model_dump(mode="json"),
            "secrets_policy": SECRETS_POLICY,
        }
    answers = merge_session_payload(partial)
    return {
        "kind": "maistro_install_session",
        "answers": answers.model_dump(mode="json"),
        "secrets_policy": SECRETS_POLICY,
    }
