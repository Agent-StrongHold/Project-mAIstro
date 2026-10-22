# Issue #860 current-job validation checkpoint

## Scope and starting state

This run is limited to issue #860 on `auto-860`, starting at
`8a57fa9acc1aa40e2ded983d52f43c7ac683cf03` (supplied base
`a9fdec4cb40a62ada3e897448eabc81f2410135a`). The worktree was clean on entry.
No `check-*.log` files were present in the supplied job directory. The supplied
prior result is `fa14555c7ab24e53a4e8c9c3a1d90374/result.json`, verdict BLOCKED.

## Findings / acceptance

The acceptance asks for a production-release claim backed by an exact RC Compose
artifact and a >=4-hour soak, not merely a harness or test pass. The current
profile explicitly describes `run_soak.py` as a host-process preflight and says
its `exact_rc_artifact` gate is unconditionally false. The inspected driver
implements that invariant in `scripts/soak/run_soak.py::preflight_artifact_check`.
The published profile also marks user/Workspace population, Graph/node fan-out,
provider/tool calls, Design/Canvas, worker/fencing, sustained Goal
reconciliation, and application event-loop measurements as remaining gaps
(`docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile
gaps” and “Round-2 amendments”). Therefore changing the gate to pass or
relabeling preflight evidence would violate the acceptance contract rather than
repair it.

The supplied prior result records the latest shakedown at 420.05 seconds versus
the documented 14,400-second minimum, and no qualifying exact-RC evidence. These
are concrete blockers; this run does not claim they were freshly re-executed.

The initial quoted-glob vulture invocation failed before scanning because the glob was passed literally. Re-running with shell expansion,
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, passed: base `a9fdec4cb40a` and candidate `70e9b7918553` both measured 1,314 identities/findings, with zero unclassified and zero never-allowlist. No quality ledger was edited.

Fresh validation on the assigned head `70e9b79185537a01cd645b7c26a79d7540cd668f`:
`uv run pytest tests/test_soak_promotion_gates.py -x -q` passed (84 tests), and the correctly expanded vulture-baseline command above passed. These validate unit gates and the ledger only, not production topology or soak acceptance. `git diff --check` passed. The assigned job directory contained no `check-*.log` files.

Direct inspection reconfirmed `scripts/soak/run_soak.py:744-755` hard-codes `ok: false` for `host-uvicorn-preflight`. The recorded round-109 evidence states `sustain_seconds=420.05`, versus the profile minimum of 14,400 seconds (`docs/testing/soak/evidence/m3a-round109-shakedown.json:221`; profile duration requirement in `docs/testing/soak/m3a-load-profile.md`). This worker did not rerun a soak; the exact-RC Compose artifact/config and four-hour window are not supplied. The profile's remaining-coverage gaps remain blockers, including concurrent population, Graph/node fan-out, successful tool/model calls, Design/Canvas, Goal/background-worker reconciliation, and worker fencing.

## ADR reconciliation

ADR-095 defines `develop` as integration and `main` as release/promotion; it
provides no authority to substitute host-process evidence for release evidence.
ADR-032 requires behavioral criteria to be tested against behavior. Neither ADR
permits weakening the #860 evidence gates. The canonical execution model
remains unchanged.

## Validation disposition

No product or gate edit is justified by the inspected evidence in this worker
round. A real qualifying Compose run requires the production artifact/config and
at least four hours of execution, as well as closure/reclassification of the
observed SIGTERM drain failure. A follow-up must also run the vulture command
with the repository's actual source directory expansion and inspect its output.
This note records a blocked validation outcome; it does not satisfy acceptance
or authorize promotion.
