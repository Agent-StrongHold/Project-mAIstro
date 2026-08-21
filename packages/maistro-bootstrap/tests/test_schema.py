"""Schema validation for install answers."""

import pytest
from pydantic import ValidationError

from maistro_bootstrap.schema import merge_session_payload, parse_answers_dict


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
