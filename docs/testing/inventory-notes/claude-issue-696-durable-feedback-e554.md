---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
  packages/maistro-core/tests: +43
---
# claude-issue-696-durable-feedback-e554

All 52 are added; nothing was removed, so the net is the gross. Nine of them
answer the Codex review of this PR and are described at the end. A number of
existing Conductor tests changed shape without changing count — `run_optimizer`
and `compare_variants` became async, so their callers did too — and those are
the same assertions on the same behaviour.

**`packages/maistro-core/tests/persistence/test_thumbs_conformance.py` (+43)**
— 11 cases parametrized over in-memory / SQLite / PostgreSQL (33), plus four
that are not.

The 11 cover the claim `OutcomeStore.list_thumbs` makes: a thumb round-trips;
its comment round-trips (the half the prompt rewriter consumes, which a
count-only assertion would lose); an outcome with no thumb is not feedback;
another DAG's thumb is excluded; an *unattributed* thumb belongs to every DAG;
naming no DAG returns all; the retention window excludes what is outside it and
keeps what is inside; a bound read keeps the most recent; another org's thumb is
not returned; naming no org sees every org.

Both halves of the window and both directions of the scoping are deliberate: a
window that excluded everything, or a filter that returned nothing, would each
satisfy one half alone.

The four unparametrized cases are about the schema gap this change closes. Every
attribution field round-tripping is asserted per store (3), and one case builds
a SQLite table shaped as it was *before* the feedback columns existed, then
checks `ensure_schema` adds them while the rows already there survive.

**`packages/hive-conductor/backend/tests/test_thumbs_read_through_the_protocol.py`
(+9)** — the guard and its own guards.

Two assert the rule: no production module reads the store's private `_outcomes`
list, and the two modules that used to are inside the scanned set. A scan with
an empty corpus would pass while looking at nothing.

One pins the predicate itself, because both earlier versions of it were wrong.
A substring test flagged `list_outcomes`, `pg_outcomes` and `sqlite_outcomes` —
sixteen files, none of them the defect. A word-boundary test fixed those and
then flagged the docstrings that *explain* the defect. It parses the AST now,
and the case asserts both false-positive classes alongside the true positives.

Three cover the wiring `set_outcome_store` never had: that the engine's source
makes the call, that `_wire_outcome_store` binds a container's store when there
is one, and that it leaves the Hive-local store alone when there is not —
binding `None` there would turn every feedback write into an AttributeError in
exactly the dev and test modes the default exists to serve.

**Mutation-checked**, four mutations:

| mutation | kills |
|---|---|
| restore `getattr(store, "_outcomes", [])` in `optimizer.py` | the guard, by name |
| drop `created_at` from the PostgreSQL insert | the retention window, on `[postgres]` alone — which is the divergence that made it worth fixing |
| stop adding the late columns to an existing SQLite table | the upgrade-path case |
| write `''` instead of `outcome.thumb` on SQLite | 9, every `[sqlite]` case that reads a thumb back |


## The Codex review of this PR (+9)

Four findings, all verified against the code before acting; the first would
have made this PR's headline claim false.

**P1 — the bridge never told the container which database.**
`MaistroCoreBridge` builds `AgentConfig` directly rather than through
`config.loader`, and left `database_url` at its empty default, so
`create_container` took the ephemeral branch and built an
`InMemoryOutcomeStore` however the deployment was configured — and this change
would have bound *that* as the durable store. Two cases (+2 in the Conductor
suite): the config carries a `database_url` resolved from the shared
`resolve_database_url`, and an unconfigured deployment still gets an in-memory
store, which is the documented fallback rather than a downgrade.

**P2 — the in-memory `list_thumbs` reversed insertion order** instead of
sorting by `created_at`. Equivalent only while every write is "now"; a
backfill, an import or a delayed event makes the three stores disagree about
which thumbs are recent. One parametrized case (+3): recorded newest-first, a
`limit=1` read must still return the newest.

**P2 — SQLite compared ISO text**, so an offset-bearing timestamp sorted by its
spelling rather than its instant. One parametrized case (+3). **The first
version of this test was vacuous**: a timestamp five days past the window
cannot be moved across the boundary by any offset, so it passed against the
un-normalised write. Mutation-checking caught that, not reading it. It now
sits an hour past the cutoff spelled at +14:00, where the text lands thirteen
hours *inside* the window.

**P2 — `_wire_outcome_store` returned early with no container**, leaving the
module global pointing at a previous container's store across a same-process
restart. One case (+1), and one existing case reworded from "leaves the store
alone" to "installs a fresh Hive-local store", which is what the fallback has
to mean.

Mutation-checked, three more:

| mutation | kills |
|---|---|
| restore `list(reversed(matched))[:limit]` | the out-of-order case, on `[memory]` alone |
| restore the un-normalised `isoformat()` write | the offset case, on `[sqlite]` alone |
| drop `database_url` from the bridge's `AgentConfig` | the P1 guard, by name |
