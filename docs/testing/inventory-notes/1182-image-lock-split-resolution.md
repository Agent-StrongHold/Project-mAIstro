---
inventory-delta:
  tests/: +5
---

# Issue #1182 repair round: the image-lock gate vs split lock resolutions

Merge-queue run 40085096483 (job 120846297676, head `ecbc36f4d`) failed the
`Container scan + SBOM + cosign` job at its final reconciliation step, not at
any scan: the round-4 `.trivyignore.yaml` entry worked, and the only
`##[error]` in the job log is

```
image maistro-engine:pr-2285 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

Root cause — the checker, not the image. The fastmcp/setuptools re-lock in
`eaf3d9830` legitimately split beartype across environment markers
(`uv.lock` now carries `0.22.9` under `python_full_version < '3.15'` and
`0.23.1` under `>= '3.15'`), so `uv export` emits BOTH pins for the name.
`parse_expected` keyed its pins dict by name alone, so the `>= '3.15'` line
silently overwrote the `< '3.15'` line — and `main`'s `expected_by_name`
comprehension collapsed the pair a second time. The Python 3.13.16 engine
image correctly shipped `beartype==0.22.9` (its own build log line:
`+ beartype==0.22.9`), and the gate failed a correct artifact on the version
its environment never selects. The same split exists in the research and
rsi-runner exports, so those legs would have failed identically after the
engine leg was fixed.

Fix: `parse_expected` keeps every version of every name (a name is
conditional if any of its lines carries a marker), and `main` compares the
image's installed pin against the NAME'S FULL accepted set. Single-pin
semantics and report formats are unchanged; a multi-pin mismatch reports
`!= one of beartype==0.22.9, beartype==0.23.1` so the accepted set stays
visible. The workflow invocation is untouched.

## tests/test_check_image_lock_reconciliation.py (+5)

- `test_parse_expected_keeps_every_version_of_a_split_resolution` — the
  run-40085096483 shape: both pins survive (the old code demonstrably kept
  only `beartype==0.23.1`).
- `test_split_resolution_reconciles_with_whichever_branch_the_image_resolved`
  — parametrized over `0.22.9` and `0.23.1`: a full `main()` pass with a
  faked `docker run` for either resolved branch.
- `test_split_resolution_still_fails_on_a_version_neither_branch_pins` —
  the gate stays alive: `beartype==0.20.0` mismatches against the named
  accepted set, once, with no confusing missing/extra pair.
- `test_split_resolution_leaves_single_pin_skews_and_requirements_alone` —
  adding a split package loosens nothing: an unconditional pin still must
  ship at its exact version, with the historical single-pin report format.

## Independent evidence (2026-10-24, real gate binary, real Docker)

With the actual `uv export --locked` fragment from this branch (both
beartype lines, hash continuations included) and fixture images built on the
exact CI engine base `python:3.13.16-slim-bookworm` (pip removed, so the
dump is exactly the beartype pin — every other package's reconciliation was
already proven green by the CI run, whose only mismatch was beartype):

- OLD gate (from git `HEAD`, `/tmp` copy — tree untouched) vs the image that
  resolved the `< '3.15'` branch → **exit 1**, reproducing byte-identically
  CI's `version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1`.
- FIXED gate vs the same image → **exit 0** (`2 marker-conditional pin(s)
  evaluated leniently`).
- FIXED gate vs a `beartype==0.20.0` image → **exit 1** with
  `!= one of beartype==0.22.9, beartype==0.23.1` (positive control: the gate
  still catches a genuinely unlocked version).

Fail-before for the pure logic is the same observation: the old
`parse_expected` returns `{'beartype==0.23.1'}` for the split export, which
is exactly what the new parse-level test asserts against.
