"""PostgreSQL prompt manager.

A version lives in `prompts`, keyed `(name, version)`. A label lives in
`prompt_labels`, keyed `(name, label)`, and names the version it points at.
Each key is one of the two properties the store has to hold: a version is
unique for a name, and a label points at exactly one version (ADR-083026-427c).

Every write goes through one transaction holding an advisory lock on the prompt
name, so two writers to one name serialize and two writers to different names
do not contend.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

#: Namespace for `pg_advisory_xact_lock(key1, key2)`. The two-int form gives
#: every lock user a namespace of its own, so a prompt name cannot collide with
#: some other subsystem's lock over an unrelated string that happens to hash the
#: same. Picked once and stated here because an advisory lock space is
#: repository-wide and nothing else can see this choice.
_LOCK_NAMESPACE = 0x70726D74  # "prmt"

#: The label an unlabelled write takes. `production` is the read default, so a
#: prompt that has never been promoted still has to resolve.
_DEFAULT_LABEL = "latest"
_PRODUCTION_LABEL = "production"


def _lock_key(name: str) -> int:
    """A signed 32-bit key for one prompt name.

    `hashtext()` would do this in the database, but its output is not stable
    across PostgreSQL major versions, and this repository runs 17, 18 and
    (soon) 19 against the same rows. Hashing here keeps the key the same
    wherever the transaction runs.
    """
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big", signed=True)


class PgPromptManager:
    """PostgreSQL-backed versioned prompt store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, name: str, *, label: str = _PRODUCTION_LABEL) -> str:
        """Fetch prompt content by name and label."""
        content, _ = await self.get_with_config(name, label=label)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = _PRODUCTION_LABEL,
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata.

        Falls back to the highest version when the label does not resolve, which
        is the behaviour every caller has always had: an agent whose prompt was
        never promoted still gets its prompt rather than an empty string.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT p.content, p.config
                   FROM prompt_labels l
                   JOIN prompts p ON p.name = l.name AND p.version = l.version
                   WHERE l.name = $1 AND l.label = $2""",
                name,
                label,
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT content, config FROM prompts "
                    "WHERE name = $1 ORDER BY version DESC LIMIT 1",
                    name,
                )
            if row is not None:
                return str(row["content"]), _parse_config(row["config"])
        return "", {}

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Create a version of a prompt and point its labels at it.

        One transaction: the advisory lock, the version allocation, the insert
        and both label moves either all happen or none do. Nothing between them
        can leave a label pointing at a version that was never committed, which
        is what the previous `UPDATE ... SET label = NULL` then `INSERT` could
        do on any failure in between.
        """
        config_json = json.dumps(config or {})
        effective_label = label or _DEFAULT_LABEL

        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, $2)", _LOCK_NAMESPACE, _lock_key(name)
            )

            version = await self._version_for(conn, name, content, config_json)

            # `latest` always follows the write. The requested label follows it
            # too, and when it *is* `latest` the second upsert is the same row
            # written twice rather than a conflict -- harmless, and cheaper than
            # branching around it.
            for moving in {_DEFAULT_LABEL, effective_label}:
                await conn.execute(
                    """INSERT INTO prompt_labels (name, label, version)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (name, label) DO UPDATE SET version = EXCLUDED.version""",
                    name,
                    moving,
                    version,
                )

            # A prompt nobody has promoted still has to be readable at the read
            # default. Only the first version claims it, and only if it is not
            # already claimed -- `DO NOTHING`, so a later write cannot silently
            # roll production back to itself.
            await conn.execute(
                """INSERT INTO prompt_labels (name, label, version)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (name, label) DO NOTHING""",
                name,
                _PRODUCTION_LABEL,
                version,
            )

    async def _version_for(
        self,
        conn: asyncpg.Connection,
        name: str,
        content: str,
        config_json: str,
    ) -> int:
        """The version this write belongs to: the head, or a new one.

        Re-writing the head's exact content and config is a retry, not an
        edit -- a client that timed out and sent the request again must not
        double the version history. Anything else is a new version, because a
        change in content is what a version is for.
        """
        head = await conn.fetchrow(
            "SELECT version, content, config FROM prompts "
            "WHERE name = $1 ORDER BY version DESC LIMIT 1",
            name,
        )
        if (
            head is not None
            and str(head["content"]) == content
            and _parse_config(head["config"]) == json.loads(config_json)
        ):
            return int(head["version"])

        version = int(head["version"]) + 1 if head is not None else 1
        await conn.execute(
            """INSERT INTO prompts (name, version, content, config)
               VALUES ($1, $2, $3, $4::jsonb)""",
            name,
            version,
            content,
            config_json,
        )
        return version


def _parse_config(raw: Any) -> dict[str, Any]:
    """Parse config from DB row (may be str, dict, or None)."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        result: dict[str, Any] = json.loads(raw)
        return result
    if isinstance(raw, dict):
        return dict(raw)
    return {}
