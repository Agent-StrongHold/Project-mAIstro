# M2 #448 — CI repair round: `security` / `Supply chain (pip-audit)` at 644b9c082

Lane L448 repair round for the two red required checks at
644b9c0829413e305f2aa04058cd9acf1c9a7a34. Both were reproduced locally from
real scanner output before anything was changed; evidence below.

## What the CI evidence actually was (read, not guessed)

Check-runs captured for head 644b9c082 (dispatch-context.json, source
`commits/644b9c0829413e305f2aa04058cd9acf1c9a7a34/check-runs`) show exactly two
`failure` conclusions out of 72:

| check | workflow run / job | conclusion |
|---|---|---|
| `security` | 39353957955 / 118404363221 (ci.yml, line 976) | failure |
| `Supply chain (pip-audit)` | 39353958148 / 118404363835 (security.yml) | failure |

`SAST (bandit + semgrep + gitleaks)` and all three leaf scanners were
**success**, and `Container scan + SBOM + cosign` was **skipped** (develop-base,
not main). So the whole `security` red is the pip-audit gate — one script,
`scripts/pip_audit_gate.py`, run by both jobs.

Local reproduction of ci.yml's `security` job sequence
(`uv sync --locked --extra dev` → `uv pip freeze --exclude-editable` →
`pip-audit --strict --format=json -r` → `scripts/pip_audit_gate.py`), BEFORE the
fix:

```
::error::pip-audit found advisories outside the triaged allowlist:
  aiohttp==3.14.3 CVE-2026-111064 -> upgrade to 3.14.4
  aiohttp==3.14.3 GHSA-2g87-pp6c-29x5 -> upgrade to 3.14.4
  aiohttp==3.14.3 CVE-2026-111063 -> upgrade to 3.14.4
GATE_EXIT=1
```

That BEFORE verdict is reproducible from two independent artifacts, both under
`/home/dev/maistro/jobs/f3bce9f5b795460c98580ef8cfe8dda6/repair-evidence/`:

- `deps-dev-before-reconstructed.txt` + `pip-audit-dev-before-reconstructed.json`
  → `GATE-before-dev-reconstructed.txt` (exit **1**). Built from the post-fix
  freeze with only `aiohttp==3.14.5→3.14.3` and `yarl==1.25.1→1.24.2`
  substituted (the sorted diff is exactly those two lines), then audited fresh
  into a uniquely-named file. `pip-audit` reports `Found 5 known
  vulnerabilities in 2 packages` — the same count as the original run.
- `pip-audit-dev-before-stripped.json` → `GATE-before-dev-stripped.txt`
  (exit **1**), the original run's report. Caveat, recorded rather than hidden:
  the original redirect target `/tmp/pip-audit.json` is a world-writable shared
  path and a concurrent process on this host prepended its own summary line and
  re-audited a 222-package set into it, so the salvaged file needed `tail -n +2`
  to parse. Its verdict is identical (same 3 aiohttp IDs, same `fix: 3.14.4`),
  which is why the reconstructed artifact above is the one to trust. Every
  AFTER report was written to a unique path and needed no salvage.

## Root cause: a newly published advisory, not this branch's diff

- `git diff fad17a87c..644b9c082` touches **no** `pyproject.toml`, no
  `uv.lock`, and no `quality/*.json` — 35 files, all sandbox/capture source,
  tests, notes and `deploy/scripts/verify-restore.sh`. The branch did not
  change the dependency set.
- `git show fad17a87c:uv.lock` already pins `aiohttp == 3.14.3`. The failing
  pin is inherited from the develop base.
- OSV publication timestamps for the three IDs:
  `CVE-2026-111063` 2026-10-19T16:44:31Z, `CVE-2026-111064` 2026-10-19T16:47:35Z,
  `GHSA-2g87-pp6c-29x5` 2026-10-19T17:07:23Z — i.e. hours before this head's CI
  run at 2026-10-20T01:32Z. Earlier heads on the same lane
  (3046a62c3c26, 644fe39462e6) passed both pip-audit jobs.

So this is the classic time-based supply-chain ratchet: an advisory landed
against an already-locked version. It is still this lane's to clear, because the
merge queue evaluates the candidate SHA and the gate is required.

`aiohttp` is reachable only through the dev toolchain —
`uv tree --package aiohttp --invert` gives
`aiohttp v3.14.3 └── cosmic-ray v8.7.0 └── maistro-workspace (extra: dev / group: dev)`.
It is not a runtime dependency of any shipped package.

## The fix, chosen by the gate's own documented policy

`scripts/pip_audit_gate.py` states: *"Fix by upgrading the dependency. Only add
a (package, advisory) pair to ALLOWED … when no fixed version exists."* All
three advisories report `fix_versions: ['3.14.4']`, so an ALLOWED entry would
have been the wrong repair. The lock was upgraded instead:

```
uv lock --upgrade-package aiohttp
  Updated aiohttp v3.14.3 -> v3.14.5
  Updated yarl    v1.24.2 -> v1.25.1   # aiohttp's own dependency, dragged along
```

`git diff --stat` for the repair is **1 file, `uv.lock`**, and the only version
lines that change are those two (`git diff uv.lock | grep '^[+-]version'`).
No `ALLOWED` entry was added, no `quality/*.json` ledger was touched, and no
gate was weakened.

## Validation (local, this round)

pip-audit gate — both CI variants, AFTER the fix:

| job | sync | report | gate exit |
|---|---|---|---|
| ci.yml `security` | `uv sync --locked --extra dev` (218 pkgs) | 208 frozen deps | **0** — `pip-audit OK (1 known, all triaged in ALLOWED)` |
| security.yml `Supply chain` | `uv sync --locked --all-extras` (221 pkgs) | 210 frozen deps | **0** — same verdict |

AFTER artifacts: `deps-dev-after.txt` / `pip-audit-dev-after.json` /
`GATE-after-dev.txt` and `deps-allextras-after.txt` /
`pip-audit-allextras-after.json` / `GATE-after-allextras.txt`, same directory.

The only surviving finding is the pre-existing, already-triaged
`ecdsa==0.19.2 PYSEC-2026-1325` (no upstream fix exists; P-256 Minerva timing
side channel; `maistro.identity` uses Ed25519/secp256k1 only). `aiohttp` no
longer appears as vulnerable at 3.14.5.

Everything else re-run after the lock change, all green:

- `uv lock --check` → Resolved 260 packages, exit 0 (lock is consistent).
- `uv sync --locked --extra dev` → 218 packages; environment restored to its
  pre-repair shape after the `--all-extras` probe (verified by re-running
  `check-dependency-namespaces.py`, which reports the same 218 distributions
  and the same two reviewed namespaces).
- `scripts/check-dependency-namespaces.py` (the other step in ci.yml's
  `security` job) → `no unreviewed top-level namespaces`, exit 0 — in **both**
  the dev env (218) and the all-extras env (221).
- `uv run ruff check .` → All checks passed. `ruff format --check .` → 3366
  files already formatted.
- Vulture per-identity ledger, with CI's exact argv
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  `1321 reviewed identities -> 1321 findings`, `unclassified: 0`,
  `never_allowlist: 0`, exit 0. **No unbanked identities, so
  `quality/vulture-baseline.json` was deliberately left unamended** — the
  lane brief authorizes a ledger edit only for retained dead code, and there
  is none. CI's `exact-debt-ledger` was already `success` at this head.
- Manifest pytest battery (9 sandbox/capture test files) → 120 passed.
- `scripts/check-suite-inventory.py` for `maistro-bootstrap` (247),
  `maistro-core` (16733), `maistro-evolve` (1004), `maistro-rsi` (1729) → all
  `ok: 1 suite(s) match the recorded inventory`.
- `tests/test_workspace_lock_authority.py`, `tests/test_ci_merge_group_scope.py`,
  `tests/test_check_autonomous_merge.py` → 55 passed (these are the tests that
  read `uv.lock`, so they are the regression surface for this change).
- Runtime smoke of the bumped toolchain:
  `import aiohttp, yarl, cosmic_ray` → `aiohttp 3.14.5`, `yarl 1.25.1`,
  `cosmic_ray OK`. `mutation.yml` is `mutation-deferred` (no cosmic-ray
  workload runs on GitHub-hosted runners), so no mutation job depends on this.
- No other pin exists to drift: grep for `aiohttp|yarl` across
  `Dockerfile*`, `*.in`, `*.yaml/*.yml`, `*.sh`, `*.toml`, `*.txt`, `*.json`
  finds nothing outside `uv.lock` (and the installed `.venv` metadata).

## Prior block: develop sync conflict — verified resolved, not assumed

```
git fetch origin
git rev-parse origin/develop            -> fad17a87c34193a91c568eb8b0a910e8e6384ccd
git merge-base HEAD origin/develop      -> fad17a87c34193a91c568eb8b0a910e8e6384ccd
git merge-base --is-ancestor origin/develop HEAD -> YES
git rev-list --count origin/develop ^HEAD       -> 0
```

`origin/develop` is an ancestor of the branch head, the merge base equals
develop's tip, and zero develop commits are missing. The conflict was already
resolved by `131b845da Merge remote-tracking branch 'origin/develop' into
auto-448`; `git status --short` is clean apart from this round's `uv.lock`.
No re-merge was needed and none was performed.

## Residual risks

- The pip-audit gate is time-dependent by construction: another advisory
  published against any locked version re-redds both jobs on every open branch
  at once, with no code change. This repair clears the three that exist at
  2026-10-20T02:5xZ; it is not a permanent immunity.
- `yarl` moved 1.24.2 → 1.25.1 as a consequence of the aiohttp bump. It is
  aiohttp's own dependency and dev-only here, and the lock resolves cleanly
  (`uv lock --check`), but it is a second package in the diff that the issue
  text never named.
- `Container scan + SBOM + cosign` (Trivy/Grype over four images) was `skipped`
  at this head because the PR base is develop, so it was not exercised here and
  is **UNVERIFIED** locally — no image builds were run in this round.
