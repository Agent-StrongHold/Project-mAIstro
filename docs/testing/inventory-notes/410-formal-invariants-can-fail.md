---
inventory-delta:
  formal/: +0
---
# Issue 410 formal invariants that can fail

Replaced the always-true formal invariants (#410) across 14 model files under
`formal/models/`: monotonic-counter `>= 0` checks, literally-empty `pass`
invariants, bookkeeping-implied inequalities, and two self-referential
assertions (impl-vs-impl). Each replacement is an independent state
transition, bounds, safety, or liveness property with a documented
counterexample class, and each was shown to fail a realistic mutant.

**Suite delta is +0**: invariant bodies are not collected pytest nodes;
`pytest formal/models --collect-only -q` collects 664 nodes before and after
(baseline `docs/testing/inventory/baseline.json` formal/ = 664 unchanged).
`uv run python scripts/check-suite-inventory.py` → 14 suites match, exit 0.

Full record of counted invariants, rejected tautologies, informational keeps,
counterexample classes, and the mutant battery lives in `formal/INVARIANTS.md`.

## Validation executed at this head

- Full required-CI equivalent against a dedicated `pgvector:pg18` container
  (127.0.0.1:55499) after `alembic upgrade head`, `maistro_evolve` installed
  as the workflow does, both DSN env vars set:
  `pytest formal/models/ -q --timeout=300 --hypothesis-seed=0` → **664 passed
  in 59.76s** (unchanged from the pre-change baseline count).
- `uv run ruff check formal/ packages/maistro-design/` → clean;
  `uv run ruff format --check formal/` → 38 files already formatted.
- `uv run python scripts/check-formal-oracle-independence.py --base
  45cc963267a157a9530ea4f0f688f27fdb83f3ae` → OK (this PR changes
  `formal/models/` but not the governed oracle, so no co-change).
- `tests/` untouched; no other suite deltas.

## Mutation battery (each counted invariant fails its mutant)

Mutants applied to a PYTHONPATH-shadowed copy of `packages/maistro-core/src`
under `/tmp/mut410` (precedence proven via `maistro.security.strikes.__file__`
→ `/tmp/...`); worktree untouched except the two design mutants below, which
were applied in-tree under the backup → `cp` restore pattern and verified with
`git diff --quiet` (the design model bootstraps `packages/maistro-design/src`
to `sys.path[0]`, outranking PYTHONPATH). Each run is the targeted model file
with `--hypothesis-seed=0`; every unmutated baseline is green.

| Mutant | File | Change | Result |
|--------|------|--------|--------|
| M1 lockout shifted 2→3 | `security/strikes.py` | `strike_count == 2` → `== 3` | **3 failed** |
| M2 unlock ignores strikes | `security/strikes.py` | unlock sets `scrutiny = NORMAL` | **3 failed** |
| M3 enable keeps the lock | `security/strikes.py` | drop `locked_until = None` | **3 failed** |
| M4 gate strikes clean input | `security/gate.py` | `if not verdict.clean:` → `if True:` | **7 failed** |
| M5 T0 delete protection lost | `maistro_design/skills/registry.py` | protection `if` → `if False` | **1 failed** |
| M6 `list_by_mode` inverted | `maistro_design/skills/registry.py` | `s.mode == mode` → `!=` | **1 failed** |
| M7 banner dropped | `security/warden/flag_response.py` | `return original_content` | **6 failed** |
| M8 reject path fails open | `security/warden/detector.py` | reject returns `clean=True` | **6 failed** |
| M9 zero-width not stripped | `security/warden/sanitizer.py` | regex never-matches | **3 failed** |
| M10 non-idempotent collapse | `security/warden/sanitizer.py` | `\s+` → `\s\s` | **4 failed** |
| M11 prescriptive req dropped | `security/warden/semantic.py` | `if has_actions:` | **1 failed** |
| M12 overzealous vocabulary | `security/warden/heuristics.py` | `window` added to tokens | **1 failed** |
| M13a wildcard drops a scope | `auth/_types.py` | category set minus last | **3 failed** |
| M13b `has_scope` fail-open | `auth/_types.py` | `return True` | **4 failed** |
| M14 token buckets swapped | `quota/tracker.py` | `input_tokens += output_tokens` | **3 failed** |
| M15 prefix key match | `auth/provider.py` | `key.startswith(candidate_key) or ...` | **1 failed** |
| M16 PII span off-by-one | `security/sentinel/pii_filter.py` | `match.end() + 1` | **1 failed** |
| M17 boundary markers swapped | `security/external_content.py` | START/END swapped in parts | **2 failed** |
| M18 prefix-of-secret accepted | `security/secret_equal.py` | `b.startswith(a) or ...` | **5 failed** |

19 mutants, 19 caught, 0 survived.

## Notable findings made while strengthening the models

- `PIIMatch` spans index the **canonical** (`normalize_for_scan`) string, not
  the raw input (documented in `pii_filter.py`); an earlier draft of the new
  bounds property asserted raw-text bounds and failed on NFKD-expanding
  prefixes — the property was corrected to the documented coordinate system,
  and the redaction-shred property (no 8-char fragment of an embedded
  credential survives) was added instead.
- The email detector does not match an address immediately followed by a
  digit (`alice@example.com9` → no match, trailing `\b` cannot hold); the
  embedded-credential rule therefore space-separates the generated context.
  Detector change deliberately out of scope for #410.
- Detector-precedence absorption is real: a `ghp_` token can be absorbed by
  the overlapping AWS-secret-pattern span, so the localization property
  asserts overlap rather than exact span coverage.

## Residual risks

- Mutant battery is documented and re-runnable (scripts inline in the job
  record) but not a CI gate; keeping it out of CI follows #341's precedent
  (mutation evidence recorded in inventory notes, not executed per-PR).
- Live GitHub CI for the eventual PR is unverifiable from this lane (push
  prohibited); local full required-command run is the operative evidence.
