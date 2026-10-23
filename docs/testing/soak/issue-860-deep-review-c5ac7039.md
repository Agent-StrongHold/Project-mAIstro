# #860 deep-review round (job c5ac70395ee54b26ab077f467695370d)

Adversarial re-examination of the round findings at exact head
`45a309dd28800aef9cdaee785195d4505231eb2f` (develop base `91996e192`).
Scope: refute or confirm each prior finding against reachable behavior.
Result: **all five findings CONFIRMED; zero refutations.**

## Adjudication

| Finding | Verdict | Evidence |
|---|---|---|
| No >=4h RC-artifact soak exists; max observed sustain 90.43s | CONFIRMED | Full sweep of `docs/testing/soak/evidence/*.json`: only `m3a-round5-final.json` (90.17s, `sustain_duration.ok=false`) and `m3a-round6-shakedown.json:221-224` (90.43s vs `minimum_seconds: 14400`, `ok=false`) carry sustain checks; `m3a-soak-evidence.json` (historical aggregate) carries none. `sustain_seconds` is the *observed* elapsed time, not the requested value (`scripts/soak/run_soak.py:1521-1522`, "observed elapsed time is the promotion contract" `:1393-1394`), so 90.43s is measured, not asserted |
| Gate enforces 14400s + exact_rc_artifact; no in-tree pack can sign promotion | CONFIRMED | `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` is a module constant (`run_soak.py:67`), not env-overridable (`os.environ` uses at `:197,:221` are subprocess env inheritance only). `preflight_artifact_check()` (`run_soak.py:635-647`) hardcodes `ok=false`, topology `host-uvicorn-preflight`, "deliberately no CLI override". `failed_promotion_checks` (`run_soak.py:649-685`) requires every gate incl. `exact_rc_artifact` and hard-fails a missing/null drain record (anti-hand-edit hardening, regression-locked `tests/test_soak_promotion_gates.py:82-99`). Both in-tree packs record `sustain_duration.ok=false` |
| Rate limiter deliberately process-local; #860 non-bypass NOT MET; filed engine-116 | CONFIRMED | `packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30` states N x configured limit, "deliberately NOT advertised as cluster-wide". No Redis-backed request limiter exists at this head (`auth_throttle.py:128` is a Protocol mention for deployers, different mechanism). `BACKLOG.md:267` engine-116 (Accepted; gap-spec; v1.0) cites the soak finding. Regression lock `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:433-489`) boots two **production** `RateLimitMiddleware` instances and proves replica 2 mints fresh allowance `[200,200,429]` after replica 1 exhausts, for both identity classes — passed in this round's run |
| m3a-soak-evidence.md is honest (H3 PARTIAL, no silent reinterpretation) | CONFIRMED | `docs/testing/soak/m3a-soak-evidence.md:171-175`: H3 "PARTIAL ... Limiter state is process-local; switching replicas increases aggregate allowance. No cluster-wide budget or replica-selection non-bypass proof"; H2 "PASS at admission only"; sustain "FAIL (by design)". `:201-205` "What still separates this from a promotion signature". Repo-wide grep: every "promotion-ready" hit is a "BLOCKED, not promotion-ready" statement — no readiness drift |
| Deterministic checks green; develop-sync block resolved; no closure keywords | RE-EXECUTED, CONFIRMED | This round at `45a309dd2`: pytest soak-gates+backpressure+pg-learnings 80 passed/5 skipped; `check-backlog-consistency.py` OK (168 items); `check-suite-inventory.py` ok (14 suites); driver check-0..5 logs green; worktree clean at exact head; sync block resolved (merge `9885ad8f` committed as `45a309dd2`); 140 branch commits since base, zero `(fixes\|closes\|resolves) #860` |

## Hardening observation (SUSPECTED, non-binding — recorded, not filed)

No CI job or test binds the checked-in evidence packs under
`docs/testing/soak/evidence/` to `failed_promotion_checks`; the gate is
exercised via synthetic fixtures. A *fully fabricated* pack (every key
present, every `ok=true`) would not be caught by CI. Not filed as an issue:
the gate's own contract (`run_soak.py:650-652`) scopes it to *accidental*
success, `exact_rc_artifact` is only ever produced as `ok=false` by the
driver, and a forged pack would additionally have to fabricate the raw
replica logs and `metrics.jsonl` that the human-readable pack cites. No
non-deliberate failing scenario could be constructed.

## Conclusion

The remaining #860 acceptance gaps — a >=4h soak of the exact RC Compose
artifact (identity contract: `m3a-load-profile.md:26-45`, none designated
in-tree) and cluster-wide rate-limit budget (engine-116, v1.0) — are runtime
evidence and a v1.0 implementation item. The in-tree gate refuses to sign
them exactly as designed; no evidence-backed in-tree repair remains. The
prior round's BLOCKED (develop-sync conflict) is resolved and verified.
Decision escalates to #89 milestone governance / engine-116 implementation.
