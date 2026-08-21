"""Boundary contracts for the front-matter schema (per `engine#ADR-032`)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maistro_registry.schema import FrontMatter, Status


def _valid_dict() -> dict[str, Any]:
    return {
        "id": "ADR-030",
        "title": "Four-Repo Governance",
        "repo": "maistro-engine",
        "kind": "adr",
        "status": "Accepted",
        "created": "2026-05-07",
        "accepted": "2026-05-07",
        "substrate": ["maistro-engine#ADR-019"],
        "implements": [],
        "related": ["maistro-engine#ADR-031"],
        "supersedes": [],
        "blocks": [],
        "blocked-by": [],
        "contracts": [],
        "tests": [],
        "layer": "Foundation",
        "owners": ["@BlakeMatthews-dev"],
    }


def test_valid_front_matter_parses() -> None:
    fm = FrontMatter.model_validate(_valid_dict())
    assert fm.id == "ADR-030"
    assert fm.status is Status.ACCEPTED
    assert fm.substrate == ["maistro-engine#ADR-019"]


def test_id_must_match_pattern() -> None:
    bad = _valid_dict() | {"id": "BAD-NAME"}
    with pytest.raises(ValidationError) as exc:
        FrontMatter.model_validate(bad)
    assert "id must match" in str(exc.value)


def test_id_pattern_lowercase_rejected() -> None:
    bad = _valid_dict() | {"id": "adr-030"}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_unknown_repo_rejected() -> None:
    bad = _valid_dict() | {"repo": "unknown-repo"}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_invalid_reference_rejected() -> None:
    bad = _valid_dict() | {"substrate": ["bogus-repo#ADR-001"]}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_reference_with_lowercase_id_rejected() -> None:
    bad = _valid_dict() | {"substrate": ["maistro-engine#adr-001"]}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_owner_must_start_with_at() -> None:
    bad = _valid_dict() | {"owners": ["BlakeMatthews-dev"]}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_extra_fields_forbidden() -> None:
    bad = _valid_dict() | {"unknown_field": "value"}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_blocked_by_alias_works() -> None:
    """YAML key `blocked-by` populates the `blocked_by` Python attribute."""
    fm = FrontMatter.model_validate(_valid_dict() | {"blocked-by": ["maistro-engine#ADR-019"]})
    assert fm.blocked_by == ["maistro-engine#ADR-019"]


def test_invalid_status_rejected() -> None:
    bad = _valid_dict() | {"status": "NotAStatus"}
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(bad)


def test_optional_dates_default_to_none() -> None:
    minimal = _valid_dict()
    minimal.pop("accepted")
    fm = FrontMatter.model_validate(minimal)
    assert fm.accepted is None
    assert fm.implemented is None


def test_adr_097_lifecycle_statuses_accepted() -> None:
    for status in (
        "Denied",
        "Fully Specced",
        "Deprecated",
        "Will Not Implement",
        "AC Defined",
        "In Progress",
        "Tests Passing",
    ):
        fm = FrontMatter.model_validate(_valid_dict() | {"status": status})
        assert fm.status == status


def test_history_entries_parse_and_validate() -> None:
    fm = FrontMatter.model_validate(
        _valid_dict()
        | {
            "history": [
                {"status": "Proposed", "date": "2026-06-09"},
                {"status": "Accepted", "date": "2026-06-10"},
            ]
        }
    )
    assert [entry.status for entry in fm.history] == [Status.PROPOSED, Status.ACCEPTED]


def test_history_rejects_unknown_status_and_extra_keys() -> None:
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(
            _valid_dict() | {"history": [{"status": "Wishful", "date": "2026-06-09"}]}
        )
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(
            _valid_dict()
            | {"history": [{"status": "Proposed", "date": "2026-06-09", "note": "hi"}]}
        )


def test_history_entry_reason_is_optional_and_survives_roundtrip() -> None:
    """A transition may say why it happened; entries without a reason stay valid.

    The reason lives on the entry rather than the document because a document
    can be rolled back more than once — a single document-level field would
    keep only the latest story.
    """
    fm = FrontMatter.model_validate(
        _valid_dict()
        | {
            "history": [
                {"status": "Implemented", "date": "2026-06-09"},
                {
                    "status": "Deprecated",
                    "date": "2026-06-10",
                    "reason": "rolled back: broke replay determinism",
                },
            ]
        }
    )
    assert fm.history[0].reason is None
    assert fm.history[1].reason == "rolled back: broke replay determinism"


def test_history_entry_reason_does_not_relax_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(
            _valid_dict()
            | {
                "history": [
                    {"status": "Deprecated", "reason": "why", "rationale": "duplicate field"}
                ]
            }
        )


def test_vestigial_statuses_are_gone() -> None:
    """`Blocked` and `Abandoned` sat in the enum with no transition admitting
    them and no document using them — vocabulary the machine could parse but
    never reach. Removed; a document claiming one must now fail validation
    instead of parsing into a state the lifecycle linter cannot evaluate."""
    for ghost in ("Blocked", "Abandoned"):
        with pytest.raises(ValidationError):
            FrontMatter.model_validate(_valid_dict() | {"status": ghost})


def test_superseded_by_alias_and_ref_validation() -> None:
    fm = FrontMatter.model_validate(_valid_dict() | {"superseded-by": ["maistro-engine#ADR-095"]})
    assert fm.superseded_by == ["maistro-engine#ADR-095"]
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(_valid_dict() | {"superseded-by": ["ADR-095"]})


def test_adr_098_extension_layers_accepted() -> None:
    """Evolve/Crypto/Connectivity/Ability are valid layers per ADR-098."""
    for layer in ("Evolve", "Crypto", "Connectivity", "Ability", "Identity"):
        fm = FrontMatter.model_validate(_valid_dict() | {"layer": layer})
        assert fm.layer == layer


def test_invalid_layer_rejected() -> None:
    with pytest.raises(ValidationError):
        FrontMatter.model_validate(_valid_dict() | {"layer": "Optimization"})
