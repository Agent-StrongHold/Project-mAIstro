"""Pydantic schema for ADR/spec front-matter, per `engine#ADR-031`.

Required fields:

- Identity: id, title, repo, kind
- Lifecycle: status, created (+ optional accepted, implemented)
- Relationships: substrate, implements, related, supersedes, blocks, blocked-by
- Contracts and tests: contracts, tests
- Classification: layer, owners

Cross-references use the form `<repo>#<id>` where `<repo>` is `maistro-engine`
and `<id>` matches `(ADR|SPEC)-NNN` or the date-based `(ADR|SPEC)-MMDDYY-xxxx`.

Design notes:

- All fields are required; empty lists are valid for relationship and
  contracts/tests fields.
- `extra = forbid` so unknown fields fail validation rather than silently
  passing through. This is the per-ADR-031 contract.
- `populate_by_name = True` so YAML can use either `blocked-by` (canonical)
  or `blocked_by` (Python-attr).
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

_Date = date


class Status(StrEnum):
    # `Blocked` and `Abandoned` were members here for months while appearing in
    # neither of tools/lint_lifecycle.py's transition tables and in zero
    # documents — vocabulary the machine could parse but never reach. Removed
    # rather than wired: nothing ever wanted them, and an enum member no
    # transition admits is exactly the built-but-never-wired shape this repo
    # keeps finding in itself.
    PROPOSED = "Proposed"
    ACCEPTED = "Accepted"
    IMPLEMENTED = "Implemented"
    SUPERSEDED = "Superseded"
    DEFERRED = "Deferred"
    # ADR-097 lifecycle machine. Which states apply to which kind (and the
    # forward-only transitions) is enforced by tools/lint_lifecycle.py.
    DENIED = "Denied"
    FULLY_SPECCED = "Fully Specced"
    DEPRECATED = "Deprecated"
    WILL_NOT_IMPLEMENT = "Will Not Implement"
    AC_DEFINED = "AC Defined"
    IN_PROGRESS = "In Progress"
    TESTS_PASSING = "Tests Passing"


class Kind(StrEnum):
    ADR = "adr"
    SPEC = "spec"


class Layer(StrEnum):
    FOUNDATION = "Foundation"
    ORCHESTRATION = "Orchestration"
    AGENTS = "Agents"
    TOOLS = "Tools"
    MEMORY = "Memory"
    OBSERVABILITY = "Observability"
    RELIABILITY = "Reliability"
    GOVERNANCE = "Governance"
    USER_CLIENT = "UserClient"
    # ADR-098 extension — see that ADR for scope definitions.
    EVOLVE = "Evolve"
    CRYPTO = "Crypto"
    CONNECTIVITY = "Connectivity"
    ABILITY = "Ability"
    IDENTITY = "Identity"


class Repo(StrEnum):
    ENGINE = "maistro-engine"


class Contract(StrEnum):
    BOUNDARY = "boundary"
    BEHAVIORAL = "behavioral"
    CROSS_SERVICE = "cross-service"


# Local id pattern: legacy sequential e.g. ADR-024, SPEC-138 (frozen — no new
# sequential IDs are assigned; see ADR-062026-9b30), or date-based MMDDYY + 4-hex
# disambiguator e.g. ADR-061526-f383, SPEC-061526-f383 (collision-safe across
# concurrent PRs, unlike sequential numbering — see ADR-062026-9b30).
_ID_PATTERN = re.compile(r"^(ADR|SPEC)-(\d{3}|\d{6}-[0-9a-f]{4})$")

# Reference pattern: e.g. maistro-engine#ADR-024, maistro-engine#ADR-061526-f383.
# This repo is self-contained; references resolve within it.
_REF_PATTERN = re.compile(r"^maistro-engine#((ADR|SPEC)-(\d{3}|\d{6}-[0-9a-f]{4}))$")


def _is_valid_id(value: str) -> bool:
    return bool(_ID_PATTERN.match(value))


def _is_valid_ref(value: str) -> bool:
    return bool(_REF_PATTERN.match(value))


class HistoryEntry(BaseModel):
    """One ADR-097 lifecycle transition: the status entered, when, and why.

    `date` is optional because backfilled entries (tools/backfill_history.py)
    omit it when the original transition date is unknown.

    `reason` is optional prose for transitions whose motivation is not obvious
    from the status alone — a rollback out of `Implemented`, a deprecation, a
    denial. It lives on the entry rather than the document because a document
    can be rolled back more than once, and a single document-level field would
    keep only the latest story.
    """

    model_config = ConfigDict(extra="forbid")

    status: Status
    # `_Date` alias: the field name `date` would shadow the type during
    # pydantic's annotation evaluation.
    date: _Date | None = None
    reason: str | None = None


class FrontMatter(BaseModel):
    """Canonical front-matter schema for ADRs and specs in this repo."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # Identity
    id: str
    title: str
    repo: Repo
    kind: Kind

    # Lifecycle
    status: Status
    created: date
    accepted: date | None = None
    implemented: date | None = None
    # ADR-097: append-only status history, oldest first.
    history: list[HistoryEntry] = Field(default_factory=list)

    # Relationships (each entry is `<repo>#<id>`)
    substrate: list[str] = Field(default_factory=list)
    implements: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list, alias="superseded-by")
    blocks: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list, alias="blocked-by")

    # Contracts and tests
    contracts: list[Contract] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)

    # Per-acceptance-criterion module map, keyed by AC id ("AC-3" -> "maistro.foo.bar").
    #
    # This is what lets a criterion's state be *measured* rather than asserted. A
    # marked test proves the code works; only the module it asserts about, checked
    # against the reachability graph, proves the capability actually runs. Without
    # this map the ladder would stop at "a test passed", which is exactly what
    # every module in quality/reachability-baseline.json already does.
    ac_modules: dict[str, str] = Field(default_factory=dict, alias="ac-modules")

    # Provenance: repo paths (packages/…, apps/…) this record governs/derives from.
    source: list[str] = Field(default_factory=list)

    # Classification
    layer: Layer
    owners: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _is_valid_id(v):
            raise ValueError(
                f"id must match ^(ADR|SPEC)-NNN$ (legacy) or ^(ADR|SPEC)-MMDDYY-[0-9a-f]{{4}}$ "
                f"(current), got {v!r}"
            )
        return v

    @field_validator(
        "substrate",
        "implements",
        "related",
        "supersedes",
        "superseded_by",
        "blocks",
        "blocked_by",
    )
    @classmethod
    def _validate_refs(cls, v: list[str]) -> list[str]:
        for ref in v:
            if not _is_valid_ref(ref):
                raise ValueError(
                    f"reference must match `<repo>#<ID>`, got {ref!r}. "
                    f"Repo: maistro-engine."
                )
        return v

    @field_validator("owners")
    @classmethod
    def _validate_owners(cls, v: list[str]) -> list[str]:
        for owner in v:
            if not owner.startswith("@"):
                raise ValueError(f"owner must start with @, got {owner!r}")
        return v
