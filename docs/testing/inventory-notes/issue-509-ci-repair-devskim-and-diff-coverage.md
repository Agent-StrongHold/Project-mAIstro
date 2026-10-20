---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
  packages/maistro-rsi/tests: +6
---

# issue-509 CI repair — devskim DS137138 on `rsi_gateway_url` + the diff-coverage floor

Repair round at head `8d91445e1`. The merge-queue evaluation recorded two CI
failures against this content: the `devskim` check-run (1 new alert) and the
`Coverage gate (publish-set floor + diff coverage)` job. The publish-set floor
had already passed in that run — the job went red at the diff-coverage step.

## devskim: the suppression marker was on the wrong line

GHAS annotated exactly one new alert:
`packages/hive-conductor/backend/config.py:387` — DS137138 (Insecure URL) on
the `rsi_gateway_url` in-compose default. The salvage commit had added a
suppression marker as the first line of a comment block ABOVE the field; this
is the #817 trap restated in that note's own bisect results: a standalone
suppression comment on the line above the finding does not suppress it — only
a same-line suffix comment does. The sibling disposition
(`DEFAULT_GATEWAY_URL` in `services/rsi_container_dispatch.py:101`, marker on
the string's own line) was never flagged, which is the CI-side proof.

Fix: the marker moved onto the flagged line itself. Ruff's format re-flow
wraps the value in parentheses; the comment stays a suffix of the physical
line carrying the string, which is what the engine reads.

Verified with DevSkim 1.0.90 locally (the action's engine, per #817's method):
pre-change it reproduced the annotation at line 387; post-change `devskim
analyze` on `config.py` reports zero DS137138 (the six remaining findings are
DS162092 on lines this branch does not change, so they raise no new alert).

## diff-coverage floor: five files under 90% lines

CI run 36911350316 / job 110538242512, gate
`scripts/check-diff-coverage.py --base 51c0e1188`. Every named uncovered line
is now driven by a test; none was waived:

- `routes/rsi.py:159` — a greenfield run is refused with 503 when
  `maistro_rsi` is not importable in this process. Only cleanup mode is
  dispatched into the container (#509); the greenfield tournament still needs
  the package here, and that gate must say so.
- `services/rsi.py:132-138, 140-143` — `stop_run`'s container stop failing
  (daemon gone mid-request) and reporting already-gone: the record still
  settles `stopped` and the task is still cancelled.
- `services/rsi.py:268-284` — the two exception legs of the mid-launch
  cancellation cleanup: a launch that FAILS after cancellation stops nothing
  (no container is invented), and a cancellation stop that fails is logged
  without masking the cancellation.
- `rsi_container_dispatch.py:200` — `_run_docker`, the seam every other test
  fakes, executes the docker CLI as an argument vector (a `docker` shim on
  PATH records the argv it receives).
- `:329-330` — `_container_user` degrades to no `--user` flag where there is
  no uid model.
- `:463, 513-517` — only the named LITELLM_* credentials cross the boundary,
  as `-e KEY=VALUE` entries.
- `:499` — a gateway container that answers nothing to `inspect` leaves the
  run launchable on the default bridge (the published host-loopback route).
- `:533-542` — launch failure modes: a timed-out run request, a refused
  request carrying the CLI's stderr, and an exit-0 with no container id are
  each `DispatchError`, never a bare subprocess exception.
- `:568-574` — `stop_container`: exactly one bounded
  `docker stop --time 20`, already-gone is `False`, a wedged stop is
  stop-issued (`True`), never raises.
- `:593-606` — `wait`'s fallback to `inspect` when the CLI prints no exit
  code, the `DispatchError` when neither wait nor inspect can see the
  container any more, and `_inspect_exit_code` answering `None` on a
  non-code state.
- `:619-632` — `poll_reports` against everything a container can write into
  the report mount: a missing directory, a half-written newest checkpoint
  falling back to the newest readable one, a JSON array where an object
  belongs, and older or shapeless checkpoints never rolling progress back.
- `rsi_execution_policy.py:316-317` — a backend probe that RAISES (OSError:
  the CLI vanished between `which` and `run`) is folded into the same
  operator-facing refusal text, so the route's 400 keeps its meaning.
- `maistro_rsi/__main__.py:830-838` — `_test_argv` accepts the resolved
  vector and refuses a malformed vector, a non-array, non-string entries and
  empty entries at exit 2 — before any cycle starts, rather than quietly
  falling back to the shell string the dispatching caller promised not to use.

## Validation

- `scripts/check-diff-coverage.py coverage.xml --base 51c0e1188…`: ok — every
  measured file this change touches is at or above 90% lines / 80% branch
  arcs (8 changed files measured). Coverage produced the way the gate's
  producers do: the full `packages/hive-conductor/backend/tests` suite
  (3143 passed, 6 skipped), `packages/maistro-core/tests`, and
  `packages/maistro-rsi/tests` (798 passed).
- DevSkim 1.0.90: DS137138 eliminated on `config.py`.
- `uv run ruff check .` / `uv run ruff format --check .`: pass.
- exact-debt-ledger vulture step (`check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`): 1374 reviewed
  identities → 1374 findings, 0 unclassified, 0 never-allowlist — this round
  eliminates none and adds none.
