"""The one composition rule for Outcome read scope, shared by both durable stores (#844).

`SqliteOutcomeStore` accepted `org_id`/`project_id` on every read and bound
them into nothing, while `PgOutcomeStore` filtered — so the same call answered
"my tenant's outcomes" on one backend and "every tenant's" on the other, and
the cross-tenant text flowed straight into the prompts and rankings that
consume `get_experience_context` and `list_outcomes`. The fix is not two
matched copies of a predicate; it is one rule both stores render into their
own placeholder syntax (`$n` for PostgreSQL, `?` for SQLite).

The rule, in full:

- **Empty means unscoped.** An axis left as `''` is not filtered: a caller
  that names no org reads globally, exactly as
  `InMemoryOutcomeStore._org_matches` — the protocol's reference — has always
  defined it. That is a documented contract, not an oversight to "fix" here;
  narrowing it would break every legitimate global read (admin dashboards,
  single-tenant homelab deployments) in the name of parity.
- **Present axes compose with AND.** Naming an org *and* a project returns
  outcomes in that org *and* that project — never either's rows alone.
- **`None` is not `''`.** A scope that resolved to `None` (an org a caller
  failed to establish, not one it deliberately left unscoped) is ambiguous,
  and treating it as "unscoped" would widen visibility precisely when scope
  resolution failed. Both stores raise rather than guess: fail closed.

The predicates themselves stay in the SQL `WHERE` clause in both stores —
records are never fetched globally and filtered afterwards — so a `LIMIT`
bounds rows that could match the scope, not rows that are then discarded.
"""

from __future__ import annotations

#: The scope axes an Outcome read can filter on, in the order the clause
#: renders them. `user_id`/`team_id` are group-by dimensions, not read-scope
#: axes, which is why neither store's reads take them as filters.
_SCOPE_AXES = ("org_id", "project_id")


def scope_predicates(
    org_id: str | None = "",
    project_id: str | None = "",
) -> tuple[tuple[str, str], ...]:
    """The ``(column, value)`` pairs a scoped read must filter on.

    Returns only the axes that are present; rendering placeholders is the
    caller's job, because PostgreSQL numbers them (``$4``) and SQLite does not
    (``?``).

    Raises:
        ValueError: an axis is ``None``. The empty string is the one spelling
            of "unscoped"; ``None`` means a scope that failed to resolve, and
            the only safe reading of that is no reading at all.
    """
    for axis, value in zip(_SCOPE_AXES, (org_id, project_id), strict=False):
        if value is None:
            raise ValueError(
                f"outcome read scope is ambiguous: {axis} is None — "
                "pass '' for an unscoped read, or a real scope id"
            )
    return tuple(
        (axis, value)
        for axis, value in zip(_SCOPE_AXES, (org_id, project_id), strict=False)
        if value
    )
