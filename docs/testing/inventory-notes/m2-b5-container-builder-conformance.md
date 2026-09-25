---
inventory-delta:
  packages/maistro-bootstrap/tests: +6
---
# M2-B5 Container Builder Conformance

The live Docker-gated tests in `test_container_sandbox.py` now exercise the
same `ContainerBuilderSandbox` used by the Builder/RSI production path. They
cover the backend's real network namespace, non-root identity and capability
floor, host-seed Git-index allowlist plus credential exclusions (including
complete `.git` exclusion), read-only rootfs with explicit workspace/tmpfs
writes, process/device/socket surfaces, memory/resource configuration, timeout
kill, and context cleanup. The credential seed case includes environment-specific
dotenv files, `.envrc`, application-specific `secrets/` material, and an
unrelated host-secret filename, matching the previously observed leak paths.
Docker proxy configuration is also blanked explicitly before candidate code
runs, so client-side proxy credentials cannot cross the environment boundary.

Re-validated live against the real Docker backend (issue #80 repair pass,
2026-08-31): `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py`
= 11 passed; `uv run pytest packages/maistro-bootstrap/tests` = 245 passed,
1 skipped. The core Tier-3 lane skips only where the host kernel refuses
bubblewrap namespaces; CI installs bwrap and relaxes
`kernel.apparmor_restrict_unprivileged_userns` before running it.

The CI test job builds the small `Dockerfile.sandbox` image and runs this lane;
without Docker or the image, local runs skip the Docker-gated module rather than
claiming backend evidence. The timeout case also creates a detached session, proving
that cleanup handles descendants which escape the command's process group.

Repair-pass addendum (lane auto-80, no new tests): `Dockerfile.sandbox` now
provisions a passwd entry for the sandbox uid 65532 (`appuser`). This is
image-level defense in depth only — the enforced boundary remains the
container-create configuration
(`--user 65532:65532`, `--cap-drop=ALL`, `--read-only`, `--network=none`) which
works in any image via the numeric uid. Verified the image builds with the added
layer and that the full live lane still passes against it.

Re-validated live at head ab8c1713f (with the image change applied): image build
`docker build -f Dockerfile.sandbox` ok; `uv run pytest
packages/maistro-bootstrap/tests/test_container_sandbox.py -v` = 11 passed;
`uv run pytest packages/maistro-bootstrap/tests -q` = 245 passed, 1 skipped;
`uv run ruff check .` and `ruff format --check .` clean;
`scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests` ok.

Verifier record (lane auto-80, head 739b9e5d7): executed `uv run pytest
packages/maistro-bootstrap/tests/test_container_sandbox.py
packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -q`
= 25 passed (43.2s, live Docker 29.7.2 against maistro-builders:latest);
full `uv run pytest packages/maistro-bootstrap/tests -q` = 245 passed,
1 skipped; `uv run ruff check .` clean;
`scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests`
ok (246). The two maistro-core tests reported red in PR #1450 CI
(`runs/test_chat_execution.py::TestAPostDispatchRecordingFailureIsNeverRedispatched`,
`test_container_security_wiring.py::test_route_request_without_auth_is_evaluated_as_the_anonymous_principal`)
pass locally at this head both bare and under the CI job env
(`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`, 19 passed) — flaky or develop-wide,
not caused by this branch. Core Tier-3 lane on this host: 4 passed, 24 skipped
("this host cannot build a bubblewrap sandbox"), the documented fail-closed
skip CI works around. GitHub CI green remains UNVERIFIED from this lane.

Repair-round record (lane auto-80, head 596dcf80f; the prior worker round
committed nothing — this round re-proves the head and commits the record):
re-built `maistro-builders:latest` from the committed
`packages/maistro-bootstrap/tests/Dockerfile.sandbox` (Docker 29.7.2) so the
image under test provably matches the tree, then ran the live lane:
`uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -v`
= 11 passed (33.7s, real `ContainerBuilderSandbox` containers). Full
`uv run pytest packages/maistro-bootstrap/tests -q` = 245 passed, 1 skipped.
The previously-red PR #1450 required-job evidence was re-run in full, not spot
checked: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
packages/maistro-core/tests -q` = 10218 passed, 673 skipped, 1 xfailed —
including the two tests the prior rollup reported red, which pass at this head.
Gates re-run at this head: `uv run ruff check .` and `ruff format --check .`
clean; `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` = 1415 reviewed identities, unclassified 0,
never_allowlist 0; `scripts/check-integration-scope.py` (pull_request scope via
`ci_merge_group_scope.py --json`) ok. Production wiring confirmed: the RSI loop
(`packages/maistro-rsi/src/maistro_rsi/local_loop.py`) and
`contained_validation.py` instantiate this exact class, so the conformance lane
exercises the supported backend production uses. Gate C's canonical clean
install (`./install.sh` + compose bring-up) is a GitHub-runner aggregate and was
not reproduced locally this round. Local Core Tier-3 bwrap lane still fails-closed:
4 passed, 24 skipped, detection reporting `bwrap: Creating new namespace failed:
Resource temporarily unavailable` on this host; CI remains the designated lane.

Verifier record (lane auto-80, head aa153c739d — develop-sync merge of
b906cc577f into the branch): the merge committed cleanly, kept every branch
sandbox change intact (no sandbox file differs between b2d7aef26 and the merge
head), and the prior block "worker made no commit" is resolved by the merge
commit itself. Independent re-execution at this head, Docker 29.7.2 against
`maistro-builders:latest`: `uv run pytest
packages/maistro-bootstrap/tests/test_container_sandbox.py
packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -v`
= 25 passed (29.7s, live containers); full `uv run pytest
packages/maistro-bootstrap/tests -q` = 245 passed, 1 skipped;
`packages/maistro-core` bwrap Tier-3 lane still fails closed locally
(`test_escape_conformance.py` = 4 passed, 24 skipped). The two maistro-core
tests PR #1450 CI previously reported red pass at this head
(`runs/test_chat_execution.py::TestAPostDispatchRecordingFailureIsNeverRedispatched::test_a_spine_refusal_before_the_dispatch_still_falls_back_to_answering`,
`test_container_security_wiring.py::test_route_request_without_auth_is_evaluated_as_the_anonymous_principal`).
Driver gates green at this head: `uv sync --locked --extra dev`, `ruff check .`,
`ruff format --check .`, `scripts/check-suite-inventory.py --suite
packages/maistro-bootstrap/tests` (246 recorded, ok). Live `gh pr view 1450`
refresh at this head: not draft; previously-red required checks Gate C and
Vulture Ratchet now SUCCESS; `test`/`integration-scope`/`quality` IN_PROGRESS
with zero failed conclusions — GitHub-run completion remains the CI lane's
residual. No closure keywords in the PR body or any branch commit.
