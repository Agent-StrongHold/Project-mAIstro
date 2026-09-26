---
inventory-delta:
  packages/maistro-bootstrap/tests: +1
---
# M2-B5 container sandbox repair

One regression test was added to prove the host-side seed allowlist reads Git split indexes with shared index files. The live conformance test was strengthened to stage dotenv files before seeding, so credential exclusion is exercised for indexed `.env`, `.env.production`, and `.envrc` inputs. It now also creates a real parent-repository gitlink with untracked child checkout content, proving the seed never recurses into a tracked submodule directory.

Independent verifier record (lane auto-80, head `64668d095ee8` — the prior round
committed nothing; this round re-proves the head from scratch and commits the
record): no sandbox-relevant file differs from the last committed verification
head `74b247e62` (empty `git diff` over `packages/maistro-bootstrap`,
`packages/maistro-core/src/maistro/sandbox`, `packages/maistro-rsi`,
`SECURITY.md`, `ci.yml`, the two inventory check scripts), and the reopened
regression claims were re-verified against reachable behavior rather than prior
assertions. `maistro-builders:latest` was re-built from the committed
`packages/maistro-bootstrap/tests/Dockerfile.sandbox` (Docker 29.7.2) so the
image under test provably matches the tree, then the live lane ran against it:
`uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -v` =
**25 passed (34.0s, live containers)** — network default-deny (`NetworkMode=none`
asserted on the live container plus the seven-class egress probe all DENIED and
DNS DENIED), credential default-deny (no credential env vars, all ten proxy
spellings blank), seed exclusion (indexed `.env`/`.env.production`/`.envrc`,
untracked host secret, `server.pem`, `secrets/`, nested `.git`, gitlink child
contents all absent while `hello.py` arrives), non-root execution
(`id -u` = 65532; `/etc` write and workspace `chown` fail; the only root exec is
the pre-seed chown), read-only rootfs with explicit workspace/tmp tmpfs
(`docker inspect` = `true 2147483648 512`; `/usr` write fails),
namespace/process/device/host-socket surfaces (mount/chroot/mknod fail, no
`/dev/kvm`, no Docker socket, `CapEff` empty, `NoNewPrivs=1`), detached-descendant
timeout kill, context cleanup, and contained memory exhaustion. Full
`uv run pytest packages/maistro-bootstrap/tests -q` = 245 passed, 1 skipped.
Gates at this head: `ruff check .` and `ruff format --check .` clean;
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` exit 0 (1412/1412 identities banked — no ledger
amendment needed); `check-suite-inventory.py --suite
packages/maistro-bootstrap/tests` ok (246); `check-security-inventory.py` ok
(SECURITY.md limitation #8 citation resolves); `check-doc-links.py` ok.
Core Tier-3 bwrap lane fails closed locally as documented (4 passed, 24 skipped).
Production parity: the suite instantiates the same `ContainerBuilderSandbox`
production uses (`maistro_rsi/local_loop.py:723-726`,
`maistro_rsi/contained_validation.py:78-80`). GitHub CI at this exact head is
green (read-only `gh`): run 36219874931 — "Build the real Builder sandbox image"
and "Run the real Builder sandbox conformance lane" both succeeded, all 10
workflows completed success. No production change was required this round; this
commit is the verification record itself.
