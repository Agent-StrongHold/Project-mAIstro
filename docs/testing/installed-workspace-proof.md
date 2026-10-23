# The installed-workspace proof (#86, M3-A4)

This document is the contract for the finite installed proof that issue #86
asks for: **one reviewed manifest drives one finite proof for one support
row**, and the proof produces an evidence bundle a reviewer can read.

It is deliberately thin. The harness does not re-implement admission,
authentication, binding bootstrap, or the executor; those belong to the
product. The harness launches the *supported* installer/lifecycle commands and
*public* product clients that the reviewed manifest names, and then asserts the
contract those observations have to satisfy.

## The three things this document separates

Most of the confusion in "we proved the clean install" comes from mixing three
different claims. The harness keeps them apart on purpose.

| Claim | What proves it | What it does **not** prove |
|---|---|---|
| **Structure** | `--verify` over a bundle: required files present, hashes match, every required key valid, `junit.xml` names the five families | That any command ran, or that the run was genuine |
| **Occurrence** | A `--manifest`/`--output` run whose families report `PASS` on observed evidence | That the evidence was produced on the machine it claims |
| **Authenticity** | A human/authority review of the manifest and the bundle it produced | — |

`--verify` prints its own limit verbatim: *"structural verification only: a
valid bundle proves structure and integrity, never run occurrence or
authenticity"*. A structurally valid bundle is **not** run occurrence, and the
harness never reports one as such.

## The entrypoint

```
uv run python scripts/prove-installed-workspace.py --help
```

Three modes:

```bash
# 1. Validate a reviewed manifest without executing anything.
uv run python scripts/prove-installed-workspace.py \
    --validate-manifest --manifest reviewed-manifest.json

# 2. Run the proof and write the evidence bundle.
uv run python scripts/prove-installed-workspace.py \
    --manifest reviewed-manifest.json --output evidence/2026-10-20-linux-x86

# 3. Verify a bundle that was produced elsewhere.
uv run python scripts/prove-installed-workspace.py --verify evidence/2026-10-20-linux-x86
```

Exit codes: `0` = the goal state, `1` = evidence was written but a family did
not pass (or the bundle failed its own self-verification), `2` = misuse, an
invalid manifest, or a bundle that could not be written.

The machine-readable contract is
[`installed-workspace-proof.schema.json`](installed-workspace-proof.schema.json).
The harness refuses to run against a schema file that uses a keyword it does
not implement, so the schema can never claim a validation that is not
happening.

The contract tests that pin all of this live in
[`tests/release/test_installed_workspace_contract.py`](../../tests/release/test_installed_workspace_contract.py).

## What a manifest must declare

The manifest is the *only* input that decides what runs. A reviewer reads it
and signs it; the harness then does exactly what it says.

| Section | What it fixes |
|---|---|
| `schema` | The manifest schema version (`1`). |
| `review` | `reviewed: true`, the reviewer's identity, and the UTC review timestamp. The harness refuses an unreviewed manifest — a manifest is executable evidence input only after human review. |
| `artifacts` | An **immutable** release ref (`v1.2.0-rc1`, never a branch), the installer entrypoint argv exactly as the shipped documentation resolves it, and at least one `sha256:` artifact digest. |
| `support_row` | One row of the owner-approved support matrix: id, browser (`ui`/`headless`), OS/arch/runtime/context/store profile. |
| `target` | The clean machine, the ordinary account, the target probe argv, and the clean-target contract (see below). |
| `credentials` | **References** to already-existing credentials (`vault://…`), never values. `present: false` means the credential is not supplied. |
| `provider` | The gateway and default model, and the **already-authorized** budget ceiling (`authorized`, `max_model_calls`, `authorization_ref`). |
| `scenarios` | The five families' commands (below). |

### The manifest is not a script

* Every command is argv, not a shell string. The harness launches it directly.
* A command that names a path inside the harness's own checkout is refused
  before anything runs: the developer checkout is not the artifact under test,
  and the published, digest-pinned release is.
* A secret-shaped literal anywhere in the manifest file (an OpenAI-style key,
  a GitHub token, an AWS key id, a Slack token, a PEM private key, a bearer
  literal) is refused before anything is parsed. Manifests carry references.
* The manifest cannot authorize an installation the issue did not: the harness
  refuses to create or import credentials, create grants, elevate privileges,
  change socket/group permissions, or perform unexpected paid provider setup
  (the *stop-before* rules, below).

## The clean-target contract

`target.requirements` is four `const: true` facts about the machine:

* `developer_checkout_absent` — no developer checkout of this repository;
* `inherited_credentials_absent` — no inherited credential material;
* `inherited_python_uv_absent` — no inherited Python/uv toolchain;
* `inherited_app_data_absent` — no inherited application state.

`target.probe` is a command whose stdout must report those facts as JSON. A
false report **BLOCKS** the run: the install is not launched, and the bundle
records the missing prerequisite. This is the difference between "the proof
runs somewhere" and "the proof runs on a clean machine".

The commands the harness launches see a **minimal inherited environment** —
`PATH`, `HOME`, `LC_ALL`, and nothing else. No `VIRTUAL_ENV`, no `PYTHONPATH`,
no controller credentials, no controller `HOME`. The harness's own checkout is
never the working directory.

## The five families

All five are mandatory. Each family records `PASS`, `FAIL`, `BLOCKED`, or
`NOT_RUN`, and each carries named subchecks that point at the payload that
backs them.

### INSTALL

The published-artifact install (`FIRST_RUN`), the post-install health and
readiness checks, the first-run/login step, workspace availability, and the
**effective** runtime configuration.

* `login.mode` must be `browser` for a `ui` row and `authenticated_equivalent`
  for a `headless` row. On a `headless` row, `BROWSER_LOGIN` is recorded
  `NOT_APPLICABLE` — and only there, and only with an independently reviewed
  profile (`support_row.headless_review` plus `support_row.profile_path`).
* The effective configuration must match the declared gateway and model. A
  mismatch is a `FAIL`, not a note.
* A mocked login or a break-glass principal fails INSTALL.

### EXECUTE

One authorized Workspace Agent request through the public product client, using
the same-request oracle.

* The response must carry the canonical ids — `run_id`, `node_run_id`,
  `attempt_id` — matching the canonical `Goal -> Graph -> Run -> NodeRun ->
  Attempt` model. A missing id is a `FAIL`; the harness never accepts a
  response that does not name the attempt it claims to have made.
* The response must report the **effective** gateway and model and a
  `response_digest`. An effective value that differs from the declared one is a
  `FAIL`: the issue requires the effective runtime values, not the generated
  plan metadata, to be checked.
* `provider_calls` must be reported as a non-negative count and is counted
  against the authorized budget. An unreported count leaves the budget
  unbounded, so it is a `FAIL` rather than an assumed zero.
* The response's user and workspace become the correlation scope for RESTART.

### RESTART

Graceful stop, start, then a fresh client session.

* The stop must report `drained: true` and `sandboxes_remaining: 0` — lifespan
  cleanup ran and no MAIstro sandbox resource was orphaned. Leftover sandboxes
  are a `FAIL`.
* The persistence check must show the same user/workspace/session and a
  `correlated_run_id` equal to the EXECUTE run's `run_id`. Absent correlation
  is a `FAIL`: the release proof is blocked until the ids actually correlate.
* One new valid request after the restart, without reseeding credentials. It
  must report its `provider_calls` count and is counted against the budget.

### ISOLATE

Two distinct ordinary users and two explicitly distinct workspaces, with no
cross-grants, and at least four probes (`foreign_session`,
`foreign_run_detail`, `foreign_events`, `foreign_artifact`, …).

* A positive control proves the probe works: own-scope access must succeed, so
  a denial is a denial and not a broken probe. A failing positive control is a
  `FAIL`.
* Every cross-scope probe must be denied with nothing leaked and nothing
  dispatched. A probe that is not denied is a `FAIL`.

### FAIL_CLOSED

The four mandatory cases, all required by name:

* `absent_credential`
* `unavailable_model`
* `inaccessible_runtime`
* `missing_sandbox_capability`

Each case arranges its precondition, runs the public client, and the client
must report a **blocked** outcome that names a recovery pointer. A case that
reports success, or that blocks without saying how to recover, is a `FAIL`:
"fail closed" is a claim about behaviour, and a failure that hides itself is
the failure mode this family exists to catch.

## Stop-before policy

Some commands are refused before they run, whatever the manifest says. The
harness scans every command the manifest could ask for and blocks the owning
family when it finds one:

| Category | Refused |
|---|---|
| `elevation` | `sudo`, `doas`, `pkexec`, `su` |
| `socket-or-group-permission-change` | `usermod`, `groupadd`, `groupmod`, `chgrp`, `setfacl`, `chmod` on a socket/group |
| `credential-generation-or-import` | `ssh-keygen`, `age-keygen`, `docker login`, `openssl gen*`, `gpg --gen-key`, credential/mnemonic generation |
| `new-grants` | creating a grant or a binding |
| `unexpected-paid-provider-setup` | account sign-up, API-key creation, billing |

A blocked command is **not executed** — the family reports `BLOCKED`, the
bundle records the category and the owning policy, and the proof does not pass.
The harness never "tries anyway with a different spelling".

### Absent credentials are not permission to create them

If the manifest's referenced credential is not present on the target, or the
provider budget is not authorized, the provider-touching scenarios are
`NOT_RUN` — and the reason is recorded. The harness never creates, imports, or
substitutes a credential to get past that, and it never spends a provider call
it was not authorized to spend.

The budget is a ceiling, not a target. `max_model_calls` bounds the observed
provider calls; when the ceiling is reached, the remaining provider-touching
steps become `NOT_RUN` and the proof does not pass.

## The evidence bundle

A bundle is a directory containing:

| File | What it is |
|---|---|
| `manifest.json` | The index: the SHA-256 of every listed payload, plus the input manifest's digest and the bundle digest. |
| `results.json` | The machine-readable result: every family, every subcheck, the environment, the budget, the profile echo, and the closeout. |
| `install.log` | The sanitized installer output. |
| `effective-config.json` | The effective runtime configuration the installed product reported. |
| `execution.json` | The EXECUTE observation. |
| `restart.json` | The RESTART observation. |
| `isolation.json` | The ISOLATE observations. |
| `fail-closed.json` | The FAIL_CLOSED observations. |
| `junit.xml` | One `testcase` per family, so the bundle drops into an existing JUnit reporter. |
| `reviewed-manifest.json` | A copy of the manifest that was run (provenance; excluded from the hash list). |
| `profile.json` | A copy of the reviewed support-row profile, when the manifest names one. |

Every payload is sanitized on the way in: authorization headers, cookies, and
sensitive assignments (`api_key`, `token`, `secret`, `password`, `mnemonic`,
`session_id`, …) are replaced with `<redacted>`. The installer log is capped at
1 MiB.

`manifest.json` cannot hash itself, and the reviewed inputs are provenance
rather than run output, so `manifest.json`, `reviewed-manifest.json`, and
`profile.json` are excluded from the recursive hash list. Everything else is
hashed, and `--verify` recomputes those hashes: a tampered payload is detected.

### What `results.json` records

The issue requires the bundle to record the facts a later reader cannot
reconstruct. `results.json` carries:

* `generated_at` — the UTC timestamp of the run (every step also carries its
  own UTC start/end stamps and duration).
* `artifacts` — the exact tested release ref, its immutability flag, the
  artifact digests, and the installer entrypoint that was used.
* `harness` — the controller's own digest and commit, so a bundle names the
  exact controller that produced it, separately from the tested product.
* `environment` — the declared target and the **observed** clean-target probe:
  OS, architecture, host UID, and each clean-target requirement.
* `profile_echo` — the support row under test: id, browser mode, OS,
  architecture, runtime, context, store profile, and the headless review
  record.
* `scenarios` — per family, the outcome, the reason, every named subcheck with
  its evidence reference, and — for EXECUTE and RESTART — the ordinary
  application principal ids. EXECUTE additionally records the canonical
  `run_id` / `node_run_id` / `attempt_id` and the effective gateway, model, and
  response digest.
* `budget` — the authorized ceiling, the observed provider calls, and the
  remainder.

No environment dump, no secret, no authorization header, no cookie, no
recovery material, and no raw private conversation content is written.

## What this does not do

* It does not perform a live installation on its own. The issue clarification
  does not authorize live installation or provider calls; a real run needs a
  reviewed manifest **and** a pre-authorized provider budget. Without both,
  the harness refuses to run, and the refusal is the evidence.
* It does not replace the clean-install smoke in
  [`.github/workflows/gate-c.yml`](../../.github/workflows/gate-c.yml). Gate C
  remains the fast, always-on smoke (fresh checkout → documented install path
  → health/readiness → migration chain → teardown). This proof is the stronger,
  separately authorized evidence: one reviewed manifest, one support row, one
  finite run, one bundle.
* It does not claim the installer supports every profile in
  [`DEPLOYMENT-STANCE.md`](../product/DEPLOYMENT-STANCE.md). The manifest's
  `support_row` names exactly one row, and the bundle proves that row.

## Related

* [`inventory-notes/86-clean-install-proof-round.md`](inventory-notes/86-clean-install-proof-round.md)
  — the testing-inventory note for this change, with the executed evidence.
* [`../install/default-installer.md`](../install/default-installer.md) — the
  documented installer entrypoint a manifest's `artifacts.entrypoint` must
  resolve to.
* [`../product/DEPLOYMENT-STANCE.md`](../product/DEPLOYMENT-STANCE.md) — the
  supported profiles, and what the installer does not support.
