---
inventory-delta:
  packages/maistro-core/tests: +14
  packages/maistro-evolve/tests: +5
  packages/maistro-rsi/tests: +9
  packages/maistro-bootstrap/tests: +1
---
# m2-78-ambient-credential-boundary — no ambient credentials in candidate environments

#78 (M2-B3) removes ambient host credentials from unattended/candidate
execution environments. Every host-backed seam that executes
candidate-importing code now starts from a fixed minimal environment built by
`maistro.sandbox.credential_boundary` (never read from `os.environ` on POSIX)
instead of inheriting the harness's.

The +27 node IDs are four files, one per seam:

- `packages/maistro-core/tests/sandbox/test_credential_boundary.py` (new, 14)
  pins the boundary as a construction property: ambient secrets (the live
  case is `LITELLM_MASTER_KEY`, which `maistro_rsi.gateway` reads from the
  RSI process's own environment) are not inherited; PATH is a literal, not
  the host's; explicit grants pass through but cannot shadow base names;
  `grant_from_credential` type-gates provenance on `CredentialRecord` (the
  #58/#1041 router seam) and refuses reserved names; `redact_env` masks
  values entirely for logs; Windows forwarding is by-name only.
- `packages/maistro-rsi/tests/test_ambient_credentials.py` (new, 9) proves it
  with real subprocesses at the wired seams: the sbx `LocalSandbox` exec sees
  exactly the boundary env (plus shell-provided SHLVL/PWD/_) and none of the
  harness's secrets; explicit grants are the only extras; a candidate's own
  `export` in one exec cannot widen the next (#78 AC); the local loop's host
  test paths (argv and shell) and `candidate_fitness._run` pass the boundary
  env; the host-backed worktree sandbox likewise.
- `packages/maistro-evolve/tests/test_candidate_env_boundary.py` (new, 5)
  pins `run_test_selection` (tdd evidence and the mutation probe's executor)
  and `measure_coverage_detailed` behind the boundary, and pins the
  `maistro_evolve._candidate_env` seam exactly equal to the canonical
  `maistro.sandbox.credential_boundary` module (base, grants channel, and
  reserved-name refusal, imported side by side in test code) so the two
  runtimes cannot drift. The seam cannot import the canonical module — the
  promotion-surface gate walks imports from the promotion roots, and
  `maistro/sandbox/__init__.py` re-exports the whole sandbox subsystem — so
  parity is a tested property, not a delegation; the seam's own POSIX
  minimal posture and Windows by-name forwarding are exercised directly.
- `packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py`
  (+1) pins the container sandbox's env minimality: `HOME=/tmp` is the only
  env assignment in any `docker run`/`exec` argv, so no future edit can add
  an `-e`/`--env`/`--env-file` ambient passthrough.

One existing node changed shape rather than count:
`test_no_host_shell_execution.py`'s failing-command test now invokes
`sys.executable` instead of bare `python`, because the boundary's fixed PATH
deliberately withholds the ambient PATH that used to resolve it.
