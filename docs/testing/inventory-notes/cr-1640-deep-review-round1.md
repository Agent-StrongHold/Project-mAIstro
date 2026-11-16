# CR-1640: deep-review round 1 evidence (head 8b4980250aa7)

Verification record, no suite delta. Base `f8a2df966a1d`; head `8b4980250aa7`.

## Container gate ("Container scan + SBOM + cosign")

- Both refreshed base pins re-verified against the live registry with
  `docker buildx imagetools inspect`: `python:3.13.18-slim-bookworm` resolves to
  `sha256:a5a7017efc59...` and `python:3.12-slim` to `sha256:5e2bdb1b0d54...`,
  each exactly as recorded in `quality/image-pins.json`. The recorded tag->digest
  mappings are real; a stale or fabricated digest would have failed every build.
- The historical scan-failure mechanism reproduced and explained: trivy 0.73.0
  (the CI-pinned version) scans pip's vendored tree
  (`pip/_vendor/vendor.txt`), which in the 3.13.18 base carries
  msgpack 1.1.2, urllib3 2.7.0 and setuptools 70.3.0 — five HIGH findings with
  fixed versions, so `--ignore-unfixed` does not suppress them and the base
  image alone fails the CI arguments (rc=1). This cannot reach a shipped image:
  every final stage strips `pip*` from both venv and base site-packages
  (Dockerfile:210-213, packages/hive-conductor/Dockerfile, Dockerfile.research,
  Dockerfile.rsi-runner — pre-existing doctrine on develop), and
  `.trivyignore.yaml` carries no entry for these findings and is unchanged from
  develop. Local scanners are at exact CI pins (trivy 0.73.0, grype 0.116.0,
  syft 1.49.0).
- Still UNVERIFIED pending CI at this head: the hive-conductor,
  maistro-engine-research and maistro-rsi-runner builds+scans, the SBOM legs,
  and cosign signing (requires GitHub OIDC; not reproducible locally).

## Mutation trigger widening — defense in depth verified

The rewritten `tests/test_mutation_targets.py` assertion
(`trigger.get("pull_request") is None`) cannot distinguish an unfiltered
trigger from a deleted one. Deletion is still caught: `check_entry_triggers`
(scripts/check-workflow-inventory.py:309-322) fails when a workflow's actual
`on:` events no longer match `quality/workflow-inventory.json`, and
check-required-checks' `collect()` enforces the REQUIRED-CHECKS.md scope row
("every PR") against the trigger block, so re-adding a paths filter fails both.
The blanket paths-filter test finds no other offender: no workflow in
`.github/workflows/` carries a `paths:` filter.

## Ratchets and suites re-run at head

Vulture CI-exact invocation (`packages/*/src --min-confidence 60 --exclude
'*/third_party/*'`): ledger matches exactly, 1238 == 1238. Radon, reachability,
suite inventory, `uv lock --check`, check-workflow-inventory, check-image-pins,
check-required-checks, ruff check/format, mypy (952 files): all rc=0.
`tests/test_plan_delivery.py`: 56 passed (54 + 2 reservation-scope repair).

## Known drift (record, not tree defect)

The PR description predates the container-gate repairs: it names head
`1c48ec7923`, base `20e6cd4a`, `scripts/plan_delivery.py`, 54 cases, and
claims no workflows or production dependency changes; the branch now touches
`.github/workflows/mutation.yml`, `.github/workflows/security.yml`,
`quality/image-pins.json`, `quality/workflow-inventory.json` and `uv.lock`.
The body must be refreshed before merge; the tree itself is consistent.
