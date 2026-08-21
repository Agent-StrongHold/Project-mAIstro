"""Contract tests for the Hive install-session shapes (SPEC-180 / SPEC-072726-3439)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro_bootstrap.session import get_session_defaults


def test_template_shape_without_partial() -> None:
    tmpl = get_session_defaults()
    assert tmpl["kind"] == "maistro_install_session_template"
    assert tmpl["defaults"]["schema_version"] == "1"
    assert tmpl["defaults"]["sandbox_profile"] == "safe"
    assert "secrets_policy" in tmpl


def test_session_merges_partial_over_defaults() -> None:
    sess = get_session_defaults(partial={"features": ["server"], "llm_gateway": "direct"})
    assert sess["kind"] == "maistro_install_session"
    assert sess["answers"]["llm_gateway"] == "direct"
    assert "server" in sess["answers"]["features"]
    # untouched fields keep defaults
    assert sess["answers"]["crypto_profile"] == "distributed_identity_root"


def test_empty_partial_is_a_session_not_a_template() -> None:
    sess = get_session_defaults(partial={})
    assert sess["kind"] == "maistro_install_session"
    assert sess["answers"]["sandbox_profile"] == "safe"


def test_invalid_partial_rejected() -> None:
    with pytest.raises(ValidationError):
        get_session_defaults(partial={"sandbox_profile": "unsafe_host"})
