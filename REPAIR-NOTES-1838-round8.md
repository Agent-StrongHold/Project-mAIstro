# REPAIR-NOTES-1838 round 8 — containers gate: reconcile step vs the beartype interpreter split

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; starting head `08dfd6f25b0fec7e50f40e1176c1cd96ece61a11`
(round-7 notes commit, same `uv.lock` as round 6/7 — round 7 was notes-only).

## Incoming evidence (CI run 40097563262, job 120882902208, at `08dfd6f25b0f`)

`Container scan + SBOM + cosign` failed with exit 1. Round 7's Trivy libbrotli
row is resolved (mirror caught up; rebuild proven green in round 7). This
round reproduces the step that now fails instead: **"Reconcile installed
packages to uv.lock"**.

## Reproduction (real gate, real image, CI-exact argv — executed this round)

The round-7 image `maistro-rsi-runner:pr-2269-r7` was built from this exact
`uv.lock`. The committed (HEAD) gate script against the CI-exact export:

```
$ uv export --locked --extra rsi-fitness --no-emit-workspace --format requirements-txt
$ python scripts/check-image-lock-reconciliation.py \
    --image maistro-rsi-runner:pr-2269-r7 --python /workspace/.venv/bin/python \
    --expected-file /tmp/expected-rsi.txt \
    --member maistro-workspace==0.9.0 --member maistro-core==0.9.0 \
    --member maistro-canvas==0.9.0 --member maistro-registry==0.9.0
image maistro-rsi-runner:pr-2269-r7 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
exit 1
```

In-image ground truth: python 3.12.15, `beartype==0.22.9`. The image is right
and the gate is wrong.

## Root cause (evidence, not guesswork)

The round-5 lock change upgraded `fastmcp` 4.0.11→4.1.3; its resolution now
splits `beartype` by interpreter via `py-key-value-aio` → beartype
(`uv.lock`: `0.22.9` for `python_full_version < '3.15'`, `0.23.1` for
`>= '3.15'`). `uv export` lists BOTH entries, each with its marker. But
`parse_expected` keyed its expected pins by canonical name — the later export
line (`0.23.1 ; >= '3.15'`) overwrote the earlier (`0.22.9 ; < '3.15'`) — so
any image on the `< 3.15` side (every shipped image: python 3.12/3.13) was
compared against `0.23.1` only and red-exited on a version the lock itself
prescribes for it.

`beartype` is the only multi-version name in the engine, research, and
rsi-runner exports on this tree; the hive-conductor export has none (checked
all four CI-exact invocations). Fixing the parser covers every invocation of
the step.

## Repair (carried over from the previous run's uncommitted work, validated and committed)

- `parse_expected` now returns conditional pins **grouped by name** — every
  alternative survives the parse (hash continuations are separate lines and
  never match the pin pattern).
- The reconcile step accepts a shipped split name against ANY of its locked
  alternatives: the image's interpreter decides which marker applies, and each
  alternative is a version the lock prescribes for some environment the
  scanners audit. A version the lock never named still skews, now reporting
  every alternative it was measured against (`!= A or B`).
- The gate's documented lenient-conditional contract is unchanged in strength
  for single-version names; the defect was the last-line-wins collapse.

## Post-repair evidence (all commands executed this round)

- **Fail-before / pass-after on the real gate** (commands above): committed
  script → **exit 1**; patched script, identical invocation → **exit 0**
  (`OK: maistro-rsi-runner:pr-2269-r7 ships exactly the locked set
  (220 distributions, incl. 4 workspace member(s); 14 marker-conditional
  pin(s) evaluated leniently)`).
- Unit suite: `uv run pytest tests/test_check_image_lock_reconciliation.py -q`
  → **30 passed** (3 new + 1 updated-in-place; see the inventory note).
- Structural regression proof: the 4 split tests run against the committed
  (pre-fix) script in an isolated copy → **4 failed, 26 deselected** — they
  fail for the defect they name, pass against the fix.
- Split-name audit across the four CI exports → `beartype` only (hive: none).
- Suite inventory gate: `uv run python scripts/check-suite-inventory.py
  --suite tests/` → **ok: 1 suite(s) match the recorded inventory** (baseline
  4117 + note delta +3).
- Driver checks re-run on the final tree: `uv run ruff check .` → all checks
  passed; `uv run ruff format --check .` → 3484 files already formatted;
  `uv sync --locked --extra dev` green (job check-0..2 logs, this head).
- Vulture per-identity ledger unchanged — no source identity moved (gate script
  is under `scripts/`, not scanned by the `packages/*/src` scan); no amendment
  made or required.

## Scope notes

- This round repairs the CI gate only. Issue #1838's actual decision gate
  (Biscuit verification-adapter owner acceptance, ADR-101826-2a63) remains
  open to the named owner; unresolved decisions stay visibly open.
- Residual risk: a future lock state with >2 alternatives per name, or a name
  split across an unconditional AND conditional pin simultaneously, reconciles
  per the same rule (unconditional pin required verbatim; conditional
  alternatives lenient) — covered by the parse/reconcile unit tests.
