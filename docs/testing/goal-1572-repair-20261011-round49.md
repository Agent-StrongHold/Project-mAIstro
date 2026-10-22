# #1572 round-49 independent verification at b0946acb9ffa (2026-10-11)

Verifier/writer round. Base 3c761d14db944a727fa0744444bc67cfe36d49f7
(origin/develop, re-fetched + `git ls-remote` — unchanged, no sync conflict to
merge), head b0946acb9ffa0d4f545be38ca3e330a26a57e731, tree clean at start.
No code, test, ledger or workflow edits made; no inventory delta (no suites
changed). This note is the round's only artifact, committed per the writer
rule.

Every load-bearing claim below was re-executed first-hand this round; no prior
round's output was trusted without re-running it.

## Driver checks (job 0dfa3900a47947ada1e1327fda21f331) — all green

- `uv sync --locked --extra dev` ok; `uv run ruff check .` ok; `uv run ruff
  format --check .` — 3288 files formatted.
- Driver 9-file pytest set: **161 passed, 28 skipped** (skips are the PG legs,
  executed separately below).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` — ok, 16334 unique identities.

## Acceptance re-executed first-hand

- Fresh database `r49g18` on the lane's pg18 server (port 55712), migrated
  empty -> `063` via `uv run alembic upgrade head` (`DATABASE_URL`); final
  line `062 -> 063, The canonical Goal store: canonical_goals and its
  append-only children`. Catalog: `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` present;
  `alembic_version` = `063`; `alembic heads` = single head `063`.
- Goals + durable-events suite with PG legs enforced
  (`MAISTRO_REQUIRE_PG_LEGS=1`, both DSN vars plain `postgresql://` —
  `MAISTRO_TEST_DATABASE_URL` for schema-agreement/asyncpg and
  `MAISTRO_TEST_PG_DSN` for the run-binding leg; omitting the second is the
  recorded env trap and errors 14 postgres params): **77 passed, 0 skipped**.
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db94...` (CI argv per formal-conformance.yml:77) — exit 0.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0, 1323 = 1323, no
  amendment needed (the vulture-ledger repair clause does not apply; the red
  gate is execution-lifecycles, a different ratchet).
- Code byte-identical to the fully-batteryied head e7e4d341b6b71
  (`git diff e7e4d341b..HEAD` non-docs files: **0**), so rounds 37–48's
  installed-base legs (056/057-stamped snapshot upgrades) carry unchanged.
  The alembic diff vs develop is 063 added plus the reviewed 043
  docstring/ancestry correction from the earlier develop-sync merge (round-2
  evidence); 056/057 meanings preserved (this round's fresh migration and
  prior installed-base legs).

## Sole blocker — re-proven external, first-hand this round

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) — **exit 1**, sole finding: `maistro.goals.model::
  GoalStatus: NEW work-state vocabulary is absent from the trusted base and
  has no already-landed authorization` (19 classified -> 20 discovered;
  baseline printed by the gate itself: `base 3c761d14db94`).
- Ledger facts (read via `git show` on both refs): branch
  `quality/execution-lifecycles.json` banks
  `maistro.goals.model::GoalStatus` (DOMAIN, with rationale naming #1572);
  base has 19 rows, no GoalStatus. `quality/ratchet-authorizations.json` on
  **both** branch and base contains only the #1136 RunStatus/DelegationStatus
  grants — no execution-lifecycles GoalStatus grant anywhere.
- Two-merge rule re-read in source this round:
  `scripts/ratchet_provenance.py:477-505` — `load_authorizations` resolves the
  authorizations file **from the base revision** ("a new grant does not take
  effect in the change that introduces it... two merges");
  `scripts/check-execution-lifecycles.py:763,783-784` — `authorized` is
  loaded with `base=trusted_ref.base_sha` and `_unauthorized_additions`
  requires a base-side grant or `visible_at_base`
  (`_discover_at_revision` shows GoalStatus does not exist at base).
- CI `test` red reproduced first-hand: `uv run pytest
  tests/test_check_execution_lifecycles.py -q` -> **1 failed / 28 passed**,
  `test_the_shipped_ledger_matches_the_shipped_code`
  (tests/test_check_execution_lifecycles.py:374, `assert gate.main() == 0`)
  with the identical GoalStatus stdout — this is also the Coverage gate's
  pytest producer, explaining both CI reds.
- Dispatch context (capture 2026-10-11T22:20:20Z, same capture round 48
  scanned): issue #1572 open, PR #1938/#1855 open, no new instruction, no
  closure keyword; nothing new to act on.

## Why this is not resolvable in-lane

An in-branch `ratchet-authorizations.json` grant is structurally unread
(base-resolved provenance above) and would be exactly the self-authorization
the provenance module exists to prevent. Removing the GoalStatus row from the
candidate ledger fails `audit` (candidate must classify what the scanner
found). Re-expressing the Goal's desired-state lifecycle as RunStatus would
misrepresent the model the issue mandates (a Goal never drives a scheduler;
DOMAIN is the honest classification). Landing the grant on develop requires a
GitHub mutation, which this lane is prohibited from performing.

**Unblock (external, one merge):** land on develop a
`quality/ratchet-authorizations.json` grant for
`execution-lifecycles: maistro.goals.model::GoalStatus` (owner/issue #1572/
reason — the DOMAIN rationale above is ready to reuse). After that lands,
this branch merges green with **zero further changes** (mechanically: the
gate's `load_authorizations` will then find the grant at the new base; prior
rounds additionally proved this by loading the real provenance module
unmodified with only an in-memory grant added — gate `main()` exit 0,
20/20 classified, tree untouched).
