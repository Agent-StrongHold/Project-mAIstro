"""`transform.alias_keys` — bridge node that renames upstream dict keys.

The executor's default input resolver flows the previous node's output
forward as a dict. When the downstream node expects different key names
(e.g. `transform.filter_by_type` wants `items`, but `jira.poll` produces
`issues`), this node sits between them with a static `mapping` config:

    {"mapping": {"items": "issues"}}   # downstream key ← upstream key

Pure data, no I/O. Idempotent. Cheap.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from . import register_node
from .base import BaseNode, NodeContext


class AliasKeysIn(BaseModel):
    """Generic dict in, generic dict out — the renamer doesn't care about
    schemas. `mapping` maps NEW key → OLD key."""

    # Accept arbitrary upstream keys.
    model_config = ConfigDict(extra="allow")

    mapping: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-key rename: {new_key: old_key}. Each new_key in the "
            "output gets the value from old_key in the input. Keys not in "
            "the mapping pass through unchanged unless `drop_unmapped=True`."
        ),
    )
    drop_unmapped: bool = Field(
        default=False,
        description="If True, only the mapped keys appear in the output.",
    )


class AliasKeysOut(BaseModel):
    """Generic dict out — extra keys allowed since the rename is dynamic."""

    model_config = ConfigDict(extra="allow")


@register_node
class TransformAliasKeysNode(BaseNode[AliasKeysIn, AliasKeysOut]):
    kind: ClassVar[str] = "transform.alias_keys"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = AliasKeysIn
    output_schema: ClassVar[type[BaseModel]] = AliasKeysOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Rename keys"
    description: ClassVar[str] = (
        "Rename upstream dict keys via a static {new_key: old_key} mapping. "
        "Bridge node between schema-incompatible neighbors; e.g. jira.poll → "
        "transform.filter_by_type needs items=issues."
    )

    async def _execute(self, inputs: AliasKeysIn, ctx: NodeContext) -> AliasKeysOut:
        # Pydantic with extra="allow" stashes extra fields in __pydantic_extra__.
        raw = dict(inputs.model_dump())
        mapping = raw.pop("mapping", {}) or {}
        drop = raw.pop("drop_unmapped", False)

        out: dict[str, Any] = {}
        for new_key, old_key in mapping.items():
            if old_key in raw:
                out[new_key] = raw[old_key]
        if not drop:
            # Pass through any keys not used as a source.
            sources = set(mapping.values())
            for k, v in raw.items():
                if k not in sources and k not in out:
                    out[k] = v
        return AliasKeysOut.model_validate(out)
