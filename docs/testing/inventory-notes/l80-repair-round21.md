---
note: l80-repair-round21
issue: "#80"
head: 66fb808b14462a5c4046a45ffd953f41b8b8b7df
date: 2026-09-27
---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 round 21 — salvage resolution and independent re-proof at head `66fb808b1`

Round 20 ended with verdict NEEDS-REPAIR whose only residual was "remote-green
at/above `66fb808b1`", plus two untracked scratch files left by round 19.
This round performed the directed salvage review, then re-proved every local
claim independently instead of trusting round 20's note.

## Salvage resolution (the previous block's uncommitted work)

Round 20's note already reviewed the two scratch files and concluded
"preserved, not committed ... neither belongs in the tree". This round
confirmed that review and completed it by moving both files out of the
worktree into the job directory (byte-identical, sha256-verified), leaving the
worktree clean and unblocking the repo-root lint gate:

- `verify_sandbox.py` — sha256 `80aeafc79acc909989ebe80547edc94726a47976abc32b43830515d37a98d64c`
  (manual probe duplicating what `test_container_sandbox.py` proves live; no
  inventory entry; while it sat at the repo root it alone made
  `uv run ruff check .` exit 1 with 5 findings).
- `.env.test` — sha256 `c0c76f725d8272c4cc0eb14b482365754c6fc4e226b6d3019c5a009ededcc47b`
  (fake `SECRET_TOKEN=test-secret` fixture used only by that probe; committing
  it would trip the 27 secret patterns that `check-build-context.py` guards).

Both are archived under
`/home/dev/maistro/jobs/7dad3a2e8fdc43c3af297ee15910ce57/salvage/`. Nothing
was discarded; no tracked file was touched.

## Independent re-proof at this head (all commands run this round)

- **Escape suite, rootless daemon** (`DOCKER_HOST=unix:///run/user/1000/docker.sock`,
  `SecurityOptions` contain `rootless`):
  `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -v`
  → **16 passed, 1 skipped** (skip = the refusal test, correctly inverted on a
  qualifying daemon). Covers filesystem, process, namespace/kernel boundary
  (live uid_map), network, device, host sockets, host ports, credential
  default-deny, privilege, seed hygiene, timeout kill incl. detached
  descendants, cleanup, 3 GiB memory containment.
- **Fail-closed branch, rootful daemon** (no `rootless` marker):
  same file → **1 passed (test_sandbox_refuses_a_rootful_unmapped_daemon),
  16 skipped** — the sandbox refuses a rootful unmapped daemon where container
  uid 0 is host uid 0.
- **Full bootstrap suite, rootless daemon**:
  `uv run pytest packages/maistro-bootstrap/tests -q` → **262 passed,
  2 skipped** in 89s (vs round-20's rootful 247+17: the 16 escape tests now
  run instead of skipping; arithmetic consistent).
- **Ruff**: `uv run ruff check .` and `uv run ruff format --check .` both
  clean (only after the scratch-file salvage; before it, repo-root ruff was
  red on the untracked probe).
- **Vulture per-identity ledger gate** (exact argv):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  **1403 reviewed identities == 1403 findings**, no ledger amendment needed.
- **Other gates**: check-suite-inventory (14 suites ok), check-ac-state
  (exit 0), check-image-inventory (ok), check-workflow-write-safety
  (23 workflows ok), check-build-context (60 rules / 27 secret patterns ok),
  check-shell-execution (3 declared call sites ok) — all exit 0.
- **Workflow-lint gate at pinned tools** (actionlint 1.7.7 + shellcheck 0.10.0,
  the CI-pinned versions): `/tmp/actionlint -no-color -oneline -shellcheck
  /tmp/shellcheck-bin` → **exit 0**, so the round-20 rootless-lane bootstrap
  edit (`66fb808b1`) lints clean.
- **Meaningfulness spot-check**: the network test asserts the live container's
  `HostConfig.NetworkMode == "none"` via `docker inspect` and requires a
  per-host `DENIED` line for IPv4/IPv6/metadata/private plus DNS (a probe that
  tested nothing could not pass); the seed-hygiene test plants indexed dotenv
  files, split-index, a gitlink with nested repo contents, `server.pem`, and
  `secrets/` before asserting their absence in the container.

## Acceptance evidence status

All suite-level criteria are proven by executed commands above. Two items
remain documented rather than worker-executable:

- **Remote CI green at/above `66fb808b1`**: `git ls-remote` shows
  `origin/auto-80` at `8f714f20d` and `origin/develop` at `0c8370a8`; this
  head is unpushed, and pushing/dispatching is prohibited for this worker.
  The lane is designated (ci.yml:468-570), locally green on both daemon
  branches at this exact head, workflow-lint clean at the pinned tools, and
  instrumented to dump `dockerd.log` if the rootless daemon still fails.
  Obtaining the green remote run is the operational handoff item.
- **check-gates-ran.py** requires the CI checks payload; no local assertion
  exists (unchanged from round 20).

No code defect is known at this head; this round's only tree change is this
note.
