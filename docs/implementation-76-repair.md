# Issue 76 repair checkpoint

Snapshot: issue #76 only; assigned worktree `/home/dev/Git/wt/auto-76`, branch `auto-76`, starting HEAD `a9282fd3c3b67162ede7b3f8b016c08d1173979d`, develop base `9417bb2f4ac84447278639c9d8b747f6c8371970`. Initial worktree clean. No supplied check-*.log files in current job directory.

Scope: verify and repair supplied Kata file-access race, canonical network/memory forwarding, bounded output/cancellation, launcher policy ceilings, selector authority tests, and actual vulture findings. No GitHub mutations. Live VM isolation acceptance remains unproven until executed on a supported host.

Initial inspection confirms the reported Kata resolved-path/open race, unbounded communicate, missing cancellation cleanup, TRUSTED_TOOL selection in the generic compatibility adapter, and launcher resource widening. Existing fd-relative `maistro.sandbox.paths` and bounded `capture_process` are reusable canonical primitives. Exact vulture command executed successfully: 1325 findings, no unclassified/unbanked identities; no ledger amendment justified at this point.

Ambiguity: assigned writer repair, so writer instructions apply (tree edits and local commit required). Prior closure-keyword history is evidence only; do not rewrite history or close the issue.

Architecture reconciliation: ADR-093 requires untrusted/model-generated work to retain VM admission and deny-by-default egress. The generic command facade currently mislabels this work TRUSTED_TOOL; change its default to UNTRUSTED_CODE, allow explicit standard policy selection for benchmark/RSI callers, and clamp requested settings through selector.build_config. Reuse canonical descriptor-relative file access and bounded capture; do not introduce another scheduler or authority. Launcher seam cannot prove live VM containment; its fake tests prove only forwarding, never isolation.

Regression evidence: `uv run pytest packages/maistro-core/tests/sandbox/test_kata_backend.py packages/maistro-core/tests/tools/test_canonical_sandbox.py packages/maistro-core/tests/sandbox/test_launcher_vm_backend.py -q --tb=short` => 8 failed, 16 passed before implementation. Both swap cases accessed host data; both overflow cases returned exit 0; cancellation left the real child alive (test finally reaped it); canonical adapter granted HOST/1024 MiB; launcher forwarded 4096 MiB/60s despite 64 MiB/1s ceiling.

After initial repair, the same focused command passes: 24 passed. Kata now retains a workspace fd, serializes operations with teardown, uses canonical bounded capture with a new host session, and removes the guest on overflow/timeout/cancellation. Generic facade defaults to UNTRUSTED_CODE and forwards clamped resource requests; network settings cannot manufacture a grant. Launcher memory/time configuration is clamped to canonical ceilings.

Expanded sandbox validation: 205 passed, 48 skipped, 1 failure. Stronger constructor convergence scan now detects launcher construction in three foreign harness providers (each registers behind a selector) and fake construction in CLI eval workspace. These are real construction sites, not scanner guesses; inspect and reconcile their authority rather than allowlisting the entire product tree. Added 10 live selected-Kata tests; all explicitly skip on this host, so live acceptance is still UNVERIFIED.

Moved three existing launcher registrations into `maistro.sandbox.wiring.build_launcher_selector`; they retain canonical admission/config and no longer construct backend classes in product modules. CLI eval fake-only mode now also selects via canonical wiring (still explicit dev-only). Expanded tests now pass: 252 passed, 48 skipped. Ruff found one new regex-literal issue and six formatting differences; repaired before final validation.

Latest focused validation: 255 passed, 48 skipped; repository ruff check and format --check both pass (3370 files). Added timeout/reap and teardown retry/error evidence; removal failure now surfaces instead of being silently claimed as success. Inventory delta is +42 core test cases. Stop expanding implementation scope: finalize gates and downstream compatibility validation, then commit with outstanding live-isolation and launcher-seam risks explicitly recorded.

Exact vulture rerun found one eliminated identity: `maistro/tools/sandbox/microvm.py::unused variable 'memory_mib'` is now consumed by launcher clamping. Pruned precisely that one ledger row under the explicit CI-repair exception; no new retained identities or grants added. Other ledger content and multiset duplicates preserved.

Gate results: core suite inventory passes (16825 collected, exact +42 delta); vulture passes after pruning; convergence matrix, execution lifecycles, reachability and doc links pass. Radon reports new C(11) spawn complexity, requiring a focused lifecycle helper refactor (no grant/ledger edits permitted). Eval CLI tests exposed a fixture patching the retired direct FakeSandboxBackend import; update it to inject through canonical wiring. Evolve focused suite passes (44 passed, 6 skipped); RSI contained validation passes (12 passed).

Final focused reruns after fixes: eval-workspace + fitness + bootstrap sandbox suites 110 passed / 4 skipped; Kata + facade regression cases 15 passed. Radon passes (134 reviewed blocks, no new or regressed complexity); vulture passes (1324 findings, no unclassified identities); ruff lint/format and git diff --check pass. Scoped mypy passes on 23 source files. Explicit live Kata run: 10 skipped because `/dev/kvm exists but is not readable/writable by this process`.

## Acceptance and residual handoff

1. Real backend registered and launches supported deployment workloads: registration covered by selector tests; actual VM launch **UNVERIFIED**, live profile inaccessible here.
2. Four standard policy dispositions: support matrix and selection tests cover all four; live four-policy launch cases explicitly skipped, so actual supported operation **UNVERIFIED**.
3. One authority for retained paths: expanded constructor convergence and provider/adapter tests pass, including 21 injected direct/aliased/qualified bypasses. This is not exhaustive dynamic reachability proof.
4. Exact profile and fail closed: support matrix, detection/selection tests pass; host refusing unusable KVM observed directly.
5. Single egress authority: network compatibility rejection tests pass; facade defaults to UNTRUSTED_CODE, settings can tighten but cannot grant network; deny/resource forwarding regression passes.
6. Lifecycle safety: real host-child overflow, timeout and cancellation, descriptor swap tests, surfaced removal errors and retryable teardown pass; no preexec_fn in Kata; actual guest removal under live VMM remains **UNVERIFIED**.
7. Selected-backend conformance: added real canonical-selector VM lane (10 cases), all skipped here. Full #77/#78/#79/#80 live VM conformance remains **UNVERIFIED**, including resource exhaustion and fencing against an actual VM.
8. Workspace/Agent/RSI/Turing/Builders substrate convergence: targeted core providers, bootstrap builders, Evolve and RSI suites pass plus static convergence gate; no complete live product end-to-end proof (**UNVERIFIED**).
9. Regression check: constructor convergence now rejects Kata and other concrete classes including import aliases and qualified calls; 21 injected mutations pass their rejection checks.

Residual launcher-seam limitations: only configuration memory/time forwarding is proven; no shipped real VMM launcher exists. The legacy tuple-output launcher interface cannot prove bounded streaming or remote teardown, and launcher host file access still uses resolved path/open (separate from the repaired production Kata transfer). Do not promote this custom-injected seam as a supported deployment or infer VM security from fake-launcher tests. These need further disposition under #76, not a new authority.

No check-*.log artifacts were supplied in this job directory. No GitHub actions, pushes, issue closures, history rewrites, or grant edits performed. Prior premature closure-keyword commit remains historical evidence; local repair commit must not contain closure keywords.

Progress: checked 1 assigned issue, partial repair done 1, skipped items 0; live acceptance and launcher-seam equivalence outstanding. Handoff is NOT integration approval.
