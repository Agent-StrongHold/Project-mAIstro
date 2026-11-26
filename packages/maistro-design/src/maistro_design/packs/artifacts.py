"""Pack artifact kinds and payload schemas (M7-A9, #985).

#793 made a pack's `artifact_kinds` free-form names. This module gives the
three shipped packs payload schemas thick enough to be *judged*: the
`product` pack's judged artifact is a `ProductSpec` (`job`, `metrics[]`,
`surfaces[]`, `nonGoals[]`), the `game` pack's is a `GameLoop` (`verb`,
`loop`, `session`, `fail`, `feel[]`), and the `book` pack's is `BookPages`
(ordered spreads `{n, text, art, turn?}`).

What these are, and deliberately are not:

- **Payload schemas on canonical artifacts, not execution identities.** A
  payload model validates what a thesis or refine emission *says*; it never
  mints a Goal, Run, NodeRun, Attempt, or store. The persisted form is
  `PackArtifactRecord` — a frozen provenance-stamped value object whose
  `payload_json` is the canonical bytes any canonical carrier (an Attempt's
  result, the pack's bound artifact-tree backend) stores.
- **Fail closed on missing fields.** Every field a schema names is required;
  a payload missing one fails validation instead of producing a
  success-shaped artifact. Extra fields are forbidden for the same reason.
- **A pack cannot emit a foreign artifact kind.** Emission goes through
  `parse_pack_artifact` / `persist_thesis_artifact`, which anchor on the
  *emitting pack*: a kind the pack does not declare is foreign and is
  rejected before any schema is consulted, so `book_pages` can never travel
  on the `product` pack.

Canvas stays a backend binding: `ProductSpec.surfaces` names the surfaces
visuals may ship through, `BookSpread.art` is prose the Canvas binding may
render — neither makes any pack "the Canvas pack", and no kind id here is or
names a `PackId`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro_design.packs.types import DomainPack, PackId

__all__ = [
    "BookPages",
    "BookSpread",
    "ForeignArtifactKindError",
    "GameLoop",
    "PackArtifactError",
    "PackArtifactKind",
    "PackArtifactRecord",
    "ProductSpec",
    "parse_pack_artifact",
    "parse_thesis_artifact",
    "payload_model",
    "persist_thesis_artifact",
]


class PackArtifactKind(StrEnum):
    """The payload-schema artifact kinds the shipped packs judge on.

    Closed like `PackId` (the extension rule is the same: one member plus one
    manifest declaration), and disjoint from it by construction — these name
    *what was produced*, never *who produced it*.
    """

    PRODUCT_SPEC = "product_spec"
    GAME_LOOP = "game_loop"
    BOOK_PAGES = "book_pages"


class ProductSpec(BaseModel):
    """The `product` pack's judged artifact: the product job-to-be-done spec.

    `job` names the job the product is hired for; `metrics`, `surfaces` and
    `non_goals` are the falsifiable success metrics, the surfaces it ships
    through, and the hard fences on scope. Visuals, if any, bind Canvas —
    the spec is the judged object, so the schema has no image fields.
    """

    model_config = ConfigDict(extra="forbid")

    job: str = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    surfaces: tuple[str, ...] = Field(min_length=1)
    non_goals: tuple[str, ...] = Field(min_length=1)


class GameLoop(BaseModel):
    """The `game` pack's judged artifact: one readable loop, not an engine.

    `verb` is the one clean player verb; `loop`, `session` and `fail` are the
    moment-to-moment loop, the closed session arc, and what failing feels
    like; `feel` enumerates the tactile qualities the loop must have.
    """

    model_config = ConfigDict(extra="forbid")

    verb: str = Field(min_length=1)
    loop: str = Field(min_length=1)
    session: str = Field(min_length=1)
    fail: str = Field(min_length=1)
    feel: tuple[str, ...] = Field(min_length=1)


class BookSpread(BaseModel):
    """One picture-book spread: page number, read-aloud text, and art note.

    `turn` optionally marks a page-turn beat — where the read-aloud cadence
    wants the page to flip.
    """

    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=1)
    text: str = Field(min_length=1)
    art: str = Field(min_length=1)
    turn: bool = False


class BookPages(BaseModel):
    """The `book` pack's judged artifact: ordered spreads, first page first.

    "Ordered" is validated, not hoped for: `n` must run 1..N with no gaps,
    repeats, or reordering, so a read-aloud cannot silently lose a page or
    shuffle the arc.
    """

    model_config = ConfigDict(extra="forbid")

    spreads: tuple[BookSpread, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered_from_one(self) -> BookPages:
        expected = range(1, len(self.spreads) + 1)
        actual = [spread.n for spread in self.spreads]
        if actual != list(expected):
            raise ValueError(
                "book pages must be ordered spreads numbered 1..N without gaps or repeats "
                f"(got {actual})"
            )
        return self


#: The one payload schema per artifact kind. A manifest may *declare* the
#: kind; only a registered schema can validate its payloads — a kind declared
#: here without a model fails closed at emission, never silently.
_PAYLOAD_MODELS: Mapping[PackArtifactKind, type[BaseModel]] = {
    PackArtifactKind.PRODUCT_SPEC: ProductSpec,
    PackArtifactKind.GAME_LOOP: GameLoop,
    PackArtifactKind.BOOK_PAGES: BookPages,
}


class PackArtifactError(ValueError):
    """A pack artifact emission failed the pack-anchored contract."""


class ForeignArtifactKindError(PackArtifactError):
    """A pack was asked to emit an artifact kind it does not declare.

    The kind is foreign to the emitting pack — including another pack's
    payload kind — which is exactly the cross-pack leak the contract refuses.
    """


def payload_model(artifact_kind: str) -> type[BaseModel] | None:
    """The registered payload schema for `artifact_kind`, or `None`."""
    try:
        return _PAYLOAD_MODELS[PackArtifactKind(artifact_kind)]
    except ValueError:
        return None


def parse_pack_artifact(
    pack: DomainPack,
    *,
    artifact_kind: str,
    payload: Mapping[str, Any],
) -> BaseModel:
    """Validate one emission against the emitting pack's own payload schema.

    Fail closed, in order:

    1. the kind must be one the pack declares — otherwise it is foreign
       (`ForeignArtifactKindError`) and no schema is consulted;
    2. the kind must be the pack's judged payload kind — declared kinds
       without a schema are opaque, and guessing one would judge an
       unstructured payload (`PackArtifactError`);
    3. the kind must have a registered payload schema (`PackArtifactError`);
    4. the payload itself must satisfy the schema — missing required fields,
       empty strings/lists, and extra fields all fail validation.

    The pydantic `ValidationError` from step 4 is the fail-closed signal and
    propagates as-is.
    """
    if artifact_kind not in pack.artifact_kinds:
        raise ForeignArtifactKindError(
            f"pack {pack.pack_id.value!r} cannot emit artifact kind {artifact_kind!r}: "
            "it is not one of the pack's declared artifact_kinds"
        )
    if artifact_kind != pack.artifact_payload_kind:
        raise PackArtifactError(
            f"artifact kind {artifact_kind!r} is declared by pack {pack.pack_id.value!r} "
            f"but carries no payload schema; the pack's judged artifact kind is "
            f"{pack.artifact_payload_kind!r}"
        )
    model = payload_model(artifact_kind)
    if model is None:
        raise PackArtifactError(
            f"artifact kind {artifact_kind!r} has no registered payload schema; "
            "a declared payload kind without a schema cannot be judged"
        )
    return model.model_validate(dict(payload))


def parse_thesis_artifact(pack: DomainPack, *, artifact_kind: str, body: str) -> BaseModel:
    """Parse a thesis slot's JSON body as the pack's judged artifact.

    The thesis `body` is the strict-JSON payload the slot produced; a body
    that is not a JSON object fails closed before schema validation.
    """
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PackArtifactError(
            f"thesis payload for artifact kind {artifact_kind!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise PackArtifactError(
            f"thesis payload for artifact kind {artifact_kind!r} must be a JSON object, "
            f"got {type(decoded).__name__}"
        )
    return parse_pack_artifact(pack, artifact_kind=artifact_kind, payload=decoded)


class PackArtifactRecord(BaseModel):
    """A validated pack artifact, persisted with its provenance.

    This is the "canonical artifact" a pack-emitted payload schema lands on:
    a frozen value object carrying *only* references — the emitting pack id
    and release, the Goal identity the emission serves, and the artifact
    kind — plus `payload_json`, the canonical bytes of the schema-validated
    payload. It mints no identity of its own: any id it is stored under
    belongs to the canonical carrier that persists it (an Attempt's result, a
    bound artifact-tree row), and reading one back re-validates against the
    same schema (`read_record`), so a tampered payload cannot masquerade as
    a judged artifact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: PackId
    pack_version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+$")
    artifact_kind: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    goal_revision: int = Field(ge=1)
    payload_json: str = Field(min_length=1)

    @classmethod
    def persist(
        cls,
        pack: DomainPack,
        *,
        artifact_kind: str,
        payload: Mapping[str, Any],
        goal_id: str,
        goal_revision: int,
    ) -> PackArtifactRecord:
        """Validate a payload through the pack's schema and freeze the record.

        A foreign kind or a missing required field fails closed here —
        nothing unschemaed is ever persisted.
        """
        model = parse_pack_artifact(pack, artifact_kind=artifact_kind, payload=payload)
        return cls(
            pack_id=pack.pack_id,
            pack_version=pack.version,
            artifact_kind=artifact_kind,
            goal_id=goal_id,
            goal_revision=goal_revision,
            payload_json=model.model_dump_json(),
        )

    def read(self) -> BaseModel:
        """The typed payload, re-validated from the persisted bytes."""
        model = payload_model(self.artifact_kind)
        if model is None:
            raise PackArtifactError(
                f"recorded artifact kind {self.artifact_kind!r} has no registered payload schema"
            )
        return model.model_validate_json(self.payload_json)


def persist_thesis_artifact(
    pack: DomainPack,
    *,
    artifact_kind: str,
    body: str,
    goal_id: str,
    goal_revision: int,
) -> PackArtifactRecord:
    """Persist one thesis slot's JSON body as the pack's judged artifact.

    The M7 explore thesis (`design.thesis`) produces `artifact_kind` + a
    strict-JSON `body`; this is the pack-side persist seam that validates the
    body against the emitting pack's own payload schema and freezes the
    provenance-stamped record. A book thesis persists `BookPages`, a game
    thesis `GameLoop`, a product thesis `ProductSpec` — each through its own
    pack, never across.
    """
    payload_model_ = parse_thesis_artifact(pack, artifact_kind=artifact_kind, body=body)
    return PackArtifactRecord(
        pack_id=pack.pack_id,
        pack_version=pack.version,
        artifact_kind=artifact_kind,
        goal_id=goal_id,
        goal_revision=goal_revision,
        payload_json=payload_model_.model_dump_json(),
    )
