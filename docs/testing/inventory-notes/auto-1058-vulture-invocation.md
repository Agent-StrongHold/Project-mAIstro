# Issue 1058 repair 4: the Vulture gate's CI invocation is green; default-args red is trunk drift

Documentation-only repair note. No tests were added or removed, and no
ledger, grant, or gate file was touched.

## The verifier finding

The post-merge verification lane for #1058 failed one local quality
command at head `50b29600e`:

```
uv run python scripts/check-vulture-baseline.py
```

which scans the script's default scope (`packages tests --exclude
*/.venv/*`) and reported ~960 unbanked and ~950 stale identities
(`fastapi-route-handler`, `pydantic-declarative-field`,
`pytest-discovered-test-surface`, hive-conductor backend routes, …).

## Why that invocation is not the gate

`.github/workflows/vulture-ratchet.yml` (job `exact-debt-ledger`) runs the
checker with an explicit, narrower contract:

```
uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

The recorded ledger matches that scope and only that scope: it banks
`pytest-discovered-test-surface: 0` (the default scan finds 443 test
identities) and zero hive-conductor `backend/` routes (hive-conductor has
no `src/` tree, so CI's glob never scans it). The default-scope
invocation was never banked green on any recent commit.

## Evidence (all executed on this lane's machine)

1. **CI invocation at this head** (`50b29600e`, trusted base resolved to
   `origin/develop` = `411a218568a2`): **exit 0** —
   `1415 reviewed identities -> 1415 findings`, zero NEW, zero pruned,
   zero unauthorized. This is exactly the comparison a PR from this
   branch into develop would run (`RATCHET_BASE_REV=origin/develop`,
   merge-base with the checked-out merge).
2. **Default invocation at the develop base itself** (`411a218568a2`,
   checked out read-only in a throwaway clone, trusted ledger at
   `622eaf7ca619`): **exit 1** with the same debt categories (205
   `fastapi-route-handler` NEW, 119 `pydantic-declarative-field` NEW, 65
   `hive-service-api-surface` NEW, …). The debt the verifier saw at this
   branch's head pre-exists byte-for-byte at the base develop commit the
   branch was cut from; this branch introduced none of it.
3. **Default invocation on the canonical clone at develop tip**
   (`622eaf7ca619`): **exit 1**, failing even earlier on 2
   `never_allowlist` unreachable-code findings in
   `packages/maistro-core/tests/runs/test_retention_scope_conformance.py`
   — trunk's own copy is redder than this branch.

The in-scope Vulture regressions this branch could have caused (three
unused evidence-seam factories in `packages/maistro-core/src`) were
already repaired in `auto-1058-repair-3.md` by deleting the dead code,
and the CI invocation has stayed green since.

## Why this lane must not "fix" the default-scope red

Re-banking ~960 identities (every FastAPI route in hive-conductor's
backend, every discovered test symbol, all `frontend/server` surfaces)
would be a trunk-wide ledger rewrite inside a HITL authorization PR.
The checker itself forbids the self-serving half of that: "Running
--update in this branch cannot authorize it; land a reviewed grant
first," and campaign rules prohibit ledger/grant edits in ordinary
implementation PRs. Precedent: `trunk-vulture-sweep.md` records the same
class of drift as "trunk's to bank properly". The correct owner is a
dedicated trunk reconciliation (bank the default scope or narrow the
script's default to the CI contract), not issue #1058.

## Reproduction

```bash
# CI contract — green at this head and at the base
uv run python scripts/check-vulture-baseline.py packages/*/src \
  --min-confidence 60 --exclude '*/third_party/*'

# Default scope — red at this head, at base 411a218568a2, and at
# develop tip 622eaf7ca619 (pre-existing trunk drift)
uv run python scripts/check-vulture-baseline.py
```
