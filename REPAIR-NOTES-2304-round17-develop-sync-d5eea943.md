# Repair notes: #2304 round 17 — develop sync (d5eea94329) resolved in place

Starting state: the worktree preserved an **uncommitted, mid-merge** develop sync
(`MERGE_HEAD = d5eea943294b`, the `actions/download-artifact v7 -> v8` (#2372) bump
develop landed 2026-11-25 08:17Z) with exactly one unmerged path:
`quality/public-routes.json`. The prior attempt's round-16 head `9357615fff` was intact
on top of the earlier `221dc3d517` sync.

## The one conflict, resolved against production behavior (not against text)

#2372 on develop re-justified both `#313` temporary exemptions to `2027-02-22`; this
branch's round-14 repair had re-shaped them. The entire HEAD<->develop delta on the
file is exactly those two entries (verified: `git diff HEAD MERGE_HEAD` = 10 changed
lines, both entries only).

Resolution — **keep the branch's entries**, because they are the ones the shared tree
supports:

- `/v1/auth/register` stays **permanent** (branch side). Fact-checked against the code
  both sides carry: `routes/auth.py:850-857` evaluates the durable registration policy
  and **fails closed** (missing/unreadable/mid-bootstrap record = closed), invitations
  are single-use conflict-safe redemptions, writes are admin-only
  (`PUT /v1/auth/registration/policy`), and the route is throttled (#366) — identical
  bytes on `d5eea94329` (verified via `git show d5eea94329:...`) and HEAD. An admin
  opens registration precisely so session-less strangers can reach the endpoint, so a
  session can never be required here. Develop's fresh reason ("no invite-gating
  replacement has shipped") is factually false against develop's own tree —
  `services/registration_policy.py` **is** the shipped invite-gating replacement.
  Route identity (exact match) unchanged, so the identity ratchet is untouched.
- `/v1/setup/` stays **temporary, expires 2026-12-24** (branch side) — strictly shorter
  than develop's 2027-02-22 — with the concrete removal path (narrow the prefix to the
  pre-setup window via the `_setup_complete` conditional; the shipped pattern lives at
  `middleware/auth.py:172` for `/v1/install/`, and the narrowing is indeed not enforced
  for `/v1/setup/` on either side).

Absorbed unchanged from #2372 (already reviewed on develop): the 3
`download-artifact@v8` refs in `mutation-nightly.yml`, the 4th `.gitleaksignore`
fingerprint (78b3244fc6 re-presentation), the #2372 context note.

Merge committed as `b87e9e4fac`.

## Validation at the merge result (all executed live, 2026-11-25)

| Gate / evidence | Command (CI-exact where applicable) | Result |
| --- | --- | --- |
| public-routes | `uv run python scripts/check-public-routes.py` | rc 0, 12 -> 12 identities, all base-authorized |
| image pins | `uv run python scripts/check-image-pins.py` | rc 0, 11 pins / 11 Dockerfiles, all registered |
| ruff | `uv run ruff check .` / `ruff format --check .` | clean / 3658 files formatted |
| suite inventory | `uv run python scripts/check-suite-inventory.py` | rc 0, 21 suites match (no test added/removed this round) |
| vulture ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc 0, 1221 = 1221 vs base d5eea943294b |
| CI test job core | `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=tests/tools/registry -q` | **5980 passed / 140 skipped / 0 failed** (6:59) |
| CI cross-suite step | `... pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60` | **11267 passed / 222 skipped / 0 failed** (11:51) |
| previously-red test files | `tests/test_research_image_playwright_runtime.py`, `tests/test_dockercli_vendored_cve_patch.py`, `tests/test_check_public_routes.py`, `tests/test_mutation_targets.py` | 81 passed |
| image-pins + interpreter guard suites | `tests/test_check_image_pins.py`, `tests/test_root_image_interpreter_lines.py` | 43 passed |
| npm audit gate | `npm audit --json` + `python scripts/npm_audit_gate.py` (canvas frontend) | rc 0, 0 advisories, ALLOWED empty |
| check scripts (test job) | durable-table-inventory, promotion-surface, connection-credentials, owned-store-access, api-route-contracts, route-permissions | all rc 0 |
| **conductor image build** | `docker buildx build -f packages/hive-conductor/Dockerfile -t hive-conductor:ci --load .` | **succeeds**; in-image tz smoke + DST cron smoke pass on the grafted interpreter |
| in-image probes | `docker run --rm --entrypoint python hive-conductor:ci -c ...` | CI's examples-namespace probe ok; `sys.version_info[:3] == (3, 13, 18)` asserted in-image; coincurve/bip_utils/nacl import |

The conductor build is the direct answer to the PR's docker-build/e2e/Gate C class of
reds: the shipped image runs the contract CPython **3.13.18** (grafted from `pybuild`)
on the `python:3.15.2-slim-bookworm` OS layer, so the dependabot 3.15 OS surface lands
without the documented dangling-venv failure mode.

## Attribution of the remaining hosted-CI reds

- `coverage (no services)` cancelled run at `ebe02132a151`: "could not pull
  python:3.12-slim after 3 attempts" (registry/runner pull failure) plus
  `RuntimeError: Event loop is closed` teardown noise during cancellation —
  infra, not this diff (this round changes no Python source; the PR diff is
  Dockerfiles + ledger/doc files). UNVERIFIED on hosted CI this round; locally the
  coverage-relevant suites execute green (above).
- Gates not runnable locally (SBOM/cosign, Gate C clean install, e2e-ui) are
  unchanged by this round's delta beyond what the image build proves above.
