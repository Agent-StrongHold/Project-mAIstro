---
inventory-delta:
  packages/maistro-core/tests: +88
---
# 970-extension-sandbox-profiles

Lands the M9-G2 sandbox isolation layer for extensions
(`packages/maistro-core/src/maistro/extensions/isolation.py`): selection of a
host-enforced isolation profile from an extension's granted authority and
trust evidence, compilation onto the `maistro.sandbox` substrate, a
fail-closed runner, and attributable violation evidence. Seventy node IDs in
`packages/maistro-core/tests/extensions/`, three files:

- `test_isolation_profiles.py` (39) — the selection rules that make
  undeclared access impossible: egress exists only when the grant declares
  `network.outbound` *and* the policy ceiling allows it (the HOST egress mode
  is refused at policy construction — the ADR-093-deprecated configuration
  cannot be expressed); writable host paths exist only under
  `filesystem.write`, and then exactly the policy's list; a failed trust
  evaluation leaves no profile at all; every resource ceiling is a ceiling
  (compile-time overrides may only tighten, the egress grant is not
  overridable at all); the execution-mode floors (ADR-093 decision 6) apply
  with unstated modes read as autonomous; and the trusted in-process tier is
  reachable only through explicit policy + named publishers + verified trust +
  standard risk — each condition removed leaves the extension sandboxed, and
  an in-process profile fails dead if routed at a sandbox.
- `test_sandbox_runner.py` (27) — the fail-closed path: no qualifying backend
  and a failing spawn are typed `ExtensionSandboxStartFailure` with the
  violation recorded against the extension id/version and logged; a policy
  that *would* allow this publisher in process still fails closed on sandbox
  startup (no fallback — the tier is a selection outcome); an unfilterable
  backend refuses a scoped egress grant instead of approximating it with the
  host network whole; kernel kill signals (SIGKILL/SIGXCPU/SIGXFSZ) and
  timeouts become attributed `RESOURCE_LIMIT_EXCEEDED` violations while a
  workload's ordinary nonzero exit does not; destroy runs even when exec
  fails; the in-process tier executes sync/async callables, logged, and
  refuses sandboxed profiles; the `InProcessExtensionLoader` adapter runs
  install-time activation through the governed `ExtensionCodeLoader` seam
  with the same evidence path (refusing sandboxed profiles and mismatched
  records at wiring/load time); and a third boundary event for one
  extension/version escalates to a named candidate-for-quarantine warning —
  the health evidence M9-G4's disable/quarantine flow consumes.
- `test_sandbox_conformance.py` (10, all conditional on a real backend) — the
  issue's "real isolation backends, not mocked policy calls" criterion, asked
  of the actual bubblewrap boundary through the extension profile →
  `SandboxConfig` → `SandboxSelector` path: the profile's memory/PID/CPU/
  file-size ceilings are read back from *inside* the sandbox as the rlimits
  the kernel enforces; a memory hog dies of `MemoryError`, a CPU busy-loop is
  stopped by the budget before the wall clock, a 64 MB write dies on SIGXFSZ
  at the 8 MB ceiling; undeclared egress means no connectivity; a scoped
  grant on the unfilterable backend fails closed at startup; host paths
  outside the profile are absent, runtime binds are read-only, writes land in
  the sandbox's own ephemeral workdir. Detection is budgeted with the exact
  execution config (#1328), so on hosts that cannot reproduce the profile's
  PID ceiling the tier is honestly evidenced as unavailable and the suite
  skips with a module-import log line — never silent cover.

Follow-up increment (+7), same issue — closing the read-path and grant-source
holes found while re-verifying the layer:

- `filesystem.read` is sandbox-scoped authority, not host-mediated: a new
  `FILESYSTEM_READ_PERMISSION` elevates the risk tier (never eligible for the
  trusted in-process tier — in process there is no boundary to scope a host
  read with), and a granted read mounts exactly the policy's
  `readable_host_paths` via `SandboxConfig.read_paths` → bwrap `--ro-bind`
  (read in place, never writable). Three selection tests pin the grant↔mount
  intersection plus the config plumbing; one bubblewrap argv test pins the
  ro-bind without needing a namespace on this host.
- Grant-source intersection: `select_isolation_profile` now intersects
  `granted` with the manifest's declared permissions before any rule fires —
  a grant token the manifest never declared (mismatched preview/record, a
  replayed install record against a newer manifest) is dropped with a
  warning, so an install record can never widen authority past the
  declaration. Two parametrized cases pin undeclared `network.outbound` and
  `filesystem.write` grants collapsing to deny/no-paths.
- Runner teardown is cancellation-safe: the `finally` destroy is shielded,
  because `CancelledError` is a `BaseException` the old `except Exception`
  path skipped, leaking the sandbox child and its selector registration —
  proven by a hanging backend plus `task.cancel()`.
- `ExtensionSandboxExecutionFailure` is deliberately no longer a subclass of
  `ExtensionSandboxStartFailure`: the sandbox was up, so extension code may
  have had side effects, and the message says so — a caller retrying on a
  start-failure contract would double-execute them.

Review increments (+3, same issue), closing holes found while re-verifying:

- a destroy that raises after a clean exec is not a silent success — the
  outcome carries a `SANDBOX_TEARDOWN_FAILURE` violation attributed to the
  extension id/version with the backend's error, and `succeeded` is false
  (`test_a_failed_teardown_fails_the_outcome`);
- the repeated-violation escalation counter lives outside the bounded
  violation deque, so a small `capacity` can no longer silently suppress the
  quarantine-candidate warning and one extension's eviction cannot re-arm
  or disarm another's count (`test_escalation_count_is_independent_of_log_capacity`,
  `test_one_extensions_eviction_does_not_re_escalate_another`).

Repair increment (+2, same issue), closing findings that survived independent
re-verification of the review round:

- the teardown await is now actually shielded (`asyncio.shield`), making the
documented cancellation contract true rather than aspirational: a second
cancel delivered while the destroy itself is running surfaces at the shield
but cannot abandon the destroy — it finishes out-of-band and nothing leaks
(`test_a_second_cancel_cannot_abandon_teardown`, proven to fail against the
unshielded form);
- `InProcessExtensionLoader.load` now binds the record's manifest publisher,
not just the extension id and version: the trusted tier's authorization is
keyed on the publisher (`in_process_publishers`), and the manifest format
validates id and publisher independently, so a record sharing only the id
and version must not activate under another publisher's trust decision
(`test_a_foreign_publisher_record_is_refused_before_activation`). The
binding is identity-level; byte-level artifact identity stays the governed
install flow's contract, stated in the loader's docstring;
- `ExtensionSandboxPolicy.max_file_mb` no longer claims to keep a workload
"from filling the host disk": `RLIMIT_FSIZE` is a per-file ceiling, not an
aggregate quota, and the docstring plus the module's honesty notes now say
exactly that.
- the second-cancel teardown path pre-binds `teardown_violation` to `None`
  before the shielded destroy: the binding sat inside a `CancelledError`
  suppression, so pyright (correctly) read the violations tuple as touching a
  possibly-unbound name — the one new finding that put the tree at 22 against
  the pyright ratchet's 21. On CPython 3.12 asyncio re-delivers the pending
  cancellation before the read is reached (proven by instrumentation), so no
  runtime behavior changes and no test can distinguish the two forms — the
  evidence is the pyright report returning to exactly 21, and `None` is the
  semantically correct value when teardown was interrupted without a result.
