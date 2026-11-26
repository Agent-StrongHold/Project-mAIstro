# #1790 round 7 — two hosted reds repaired: pip-audit (pillow/certifi) and canvas `npm audit` (vite)

Incoming state: clean worktree at `89e892aab0c2`; `origin/develop ==
c2d7209f1 == merge-base(HEAD, origin/develop)`, so there was no develop sync
conflict to resolve. The dispatch's "CI GATE FAILURES: green" was not usable
evidence; both reds were re-derived from scratch by running CI's own recipes on
this tree. No GitHub mutations.

## Red 1 — Supply chain (pip-audit) + the `security` aggregate

Reproduced before touching anything, using ci.yml:990's exact recipe
(`uv pip freeze --exclude-editable > /tmp/deps.txt`, then
`uv pip-audit --strict --format=json -r /tmp/deps.txt`, then the single gate
script):

```
$ uv run python scripts/pip_audit_gate.py /tmp/pip-audit-before.json
::error::pip-audit found advisories outside the triaged allowlist:
  certifi==2026.4.22 PYSEC-2026-4320 -> upgrade to 2026.10.19
  pillow==12.3.0 CVE-2026-112895 -> upgrade to 13.0.0
  ... (8 pillow advisories total)
exit 1
```

Both are inherited from develop's lockfile (`git diff origin/develop --
uv.lock` was empty at the incoming head), i.e. not branch-caused, but this lane
has fixed inherited lockfile debt in-branch before (`aiohttp`, round 6), and a
red supply-chain job blocks the merge queue regardless of who introduced it.

**Repair:** `packages/maistro-canvas/pyproject.toml` moves the declared floor
`pillow>=12.3.0,<13` -> `pillow>=13.0.0,<14`; the lock was then re-resolved
with `uv lock --upgrade-package pillow --upgrade-package certifi`. The lock
diff is exactly two version lines (`certifi 2026.4.22 -> 2026.10.19`,
`pillow 12.3.0 -> 13.0.0`) plus the corresponding wheel/sdist hash blocks — no
other package moved. No advisory was allowlisted; both have fixed versions, so
the gate's rule ("only allowlist a pair with no fixed version") forbids that
route.

A 13.x floor is safe for the one consumer: `canvas/compositor.py:30-31` reads
`getattr(Image, "Resampling", Image).LANCZOS/_BICUBIC`, which is the
forward-compatible spelling. Proven, not assumed:

| check | result |
| --- | --- |
| `pip_audit_gate.py` on the re-frozen environment | **exit 0** — "pip-audit OK (1 known, all triaged in ALLOWED)" (the remaining `ecdsa PYSEC-2026-1325` pair has no fixed version and is the pre-existing ALLOWED row) |
| `pytest packages/maistro-canvas/tests -x -q` (compositor + pptx export on pillow 13) | 465 passed, 75 skipped |
| `uv sync --locked --extra dev` | exit 0 |
| `scripts/check-dependency-namespaces.py` | exit 0 |
| pillow 13.0.0 wheels in the lock for cp312–cp315 manylinux | present, so the pinned `python:3.13.15-slim` Dockerfile still gets a wheel |

`packages/maistro-canvas/CLAUDE.md` said "Pillow ≥11 required"; it now states
the ≥13 floor and why (12.x carries five CVEs). A stale floor note next to a
security-driven bump is exactly the drift this repo gates on elsewhere.

## Red 2 — `test` job: canvas frontend `npm audit --audit-level=high`

Reproduced in `packages/maistro-canvas/frontend` after `npm ci`:

```
vite  8.0.0 - 8.1.5   Severity: high
launch-editor: escapeCmdArgs() omits % escaping on Windows — GHSA-698v-4r3x-3vcv
launch-editor: Editor CLI flag misinterpretation … — GHSA-r825-w8mm-5pxw
launch-editor: `fs.existsSync()` existence check can be bypassed … — GHSA-587h-7wmj-h5pm
1 high severity vulnerability
```

Also inherited (`git diff c2d7209f1..89e892aa` touches nothing under
`packages/maistro-canvas/frontend`), and also repaired in branch, since the
`test` job runs this step on every PR. `npm audit fix` was the remedy; it
resolved `vite 8.1.5 -> 8.3.4` (inside the already-declared `^8.0.10` range, so
`package.json` is untouched) and pulled the matching `rolldown 1.1.5 -> 1.2.14`,
`lightningcss 1.32.0 -> 1.33.0`, `postcss`, `nanoid` and dropped the
`binding-wasm32-wasi` optional path. Only `package-lock.json` changed.

CI's canvas-frontend steps re-run from a clean `npm ci` against the new lock:

| step | result |
| --- | --- |
| `npm ci` | 0 vulnerabilities |
| `npm run test:ci` | 5 files / 79 tests passed |
| `npm run lint` | 0 errors (13 pre-existing warnings, `--max-warnings 13`) |
| `npm run build` | built in 603ms (same pre-existing chunk-size warning) |
| `npm audit --audit-level=high` | found 0 vulnerabilities, exit 0 |

`dist/` and `node_modules/` are gitignored (`packages/maistro-canvas/frontend/.gitignore:11`).

## No vulture-ledger amendment was needed

The dispatch's CI-repair clause permits editing `quality/vulture-baseline.json`.
With CI's exact arguments
(`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`) the scan banks
**1326 reviewed identities -> 1326 findings, exit 0** — there is no unbanked
dead identity to fix or bank, so the ledger is left untouched.

## Re-verified the five #1790 corrections still hold at this head

Nothing in this round's diff touches them, but a green claim is cheap, so each
gate was re-executed on this tree:

| gate (quality.yml / vulture-ratchet.yml step) | result |
| --- | --- |
| `check-route-permissions.py` (corrections 1, 3) | exit 0 — 41 declared, 0 tolerated undeclared |
| `check-principal-identity.py` (corrections 3, 5) | exit 0 — 4 tolerated, none new |
| `check-radon-baseline.py` (correction 2) | exit 0 — 134 = 134 |
| `check-ratchet-provenance.py` (correction 3) | exit 0 — 53 quality JSON consumers carry provenance |
| `check-reachability.py` / `-dispositions.py` | exit 0 — 168 unreachable, all 48 groups disposed |
| `check-shipped-surface-truth.py` | exit 0 |
| `check-doc-links.py` | exit 0 — 0 broken relative links |
| `check-backlog-consistency.py` | exit 0 |
| `pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py` | 39 passed (the reachability self-checks that used to red the `test` job and abort the Coverage producer) |
| branch suites (`test_principal_legacy_dict`, `test_chat_voice_gates`, `test_backup_restore_oracle`, `test_check_principal_identity`, `test_restore_oracle_characterization`, `test_restore_oracle_readiness_gate`) | 86 passed |
| `ruff check .` / `ruff format --check .` | clean / 3370 files already formatted |
| `check-suite-inventory.py --suite packages/maistro-canvas/tests` | ok, 0 duplicates |

Correction-4 surfaces re-read (not assumed): `quality/branch-independence.json`
surfaces[37..39] = `principal-identity-baseline` (base_derived),
`route-permissions-baseline` (base_derived), `route-permissions-registry`
(specification). Correction 1: quality.yml:1084 `run: uv run python
scripts/check-route-permissions.py`. Correction 5: `_is_state_getter` /
`_is_state_attr_call` in `scripts/check-principal-identity.py:139-181` see
through `getattr(getattr(x, "state", None), "user", ...)`.

## Residual

No tests added this round (a dependency-floor test would restate `pyproject.toml`
and duplicate the guard that already exists — `pip_audit_gate.py` for Python,
`npm audit --audit-level=high` for the frontend — both demonstrated red before
and green after), so no inventory delta and no inventory-note file.

Hosted-only legs remain unproven locally: Coverage gate publish-set floor,
`integration-scope`, `docker-build`, and the durable-events leg (path-filter
skipped). The two reds this round existed to fix are now green by their CI
recipes on this tree.
