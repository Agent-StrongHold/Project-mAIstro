---
inventory-delta:
  tests/: +0
---
# claude-ac-state-shim-surface-4d1c

No test was added, moved or deleted. Two fixtures and one patch site now name
the module whose behaviour they are testing.

`develop` was red: five tests of the AC-state gate's own suite failed, and the
root `test` job carries them into every PR. The cause is that
`scripts/check-ac-state.py` became a thin entry point over
`scripts/check_ac_state_impl.py` and re-exports by copying names into its own
globals — so a re-exported function still closes over the *implementation's*
globals, and `monkeypatch.setattr(check_ac_state, "SPEC_DIR", tmp_path)` rebound
a name nothing reads. `_spec_files()` walked the real corpus instead of the
fixture; `passing_ac_ids` called the real `_passing_in_root` instead of the fake.

**The first attempt made the entry point proxy those writes to the
implementation, and that was wrong.** The same file is loaded under four module
names across this suite — `check_ac_state`, `check_ac_state_public`,
`check_ac_state_for_notes`, and the entry point itself — and the copy gives each
load an independent namespace. Routing writes to one shared implementation turns
any test's patch into every other load's problem, which showed up as an
order-dependent failure in the merge queue that the same tests passed through
locally.

So the seam moves instead of the production code, and nothing under `scripts/`
changes. `test_check_ac_state.py` loads `check_ac_state_impl` — every name it
touches is the implementation's, and it uses nothing the entry point adds — and
the one ratchet test that patches `_NOTES_SOURCE` patches it where
`_load_notes_module` reads it. `test_ac_state_merge_guard.py` still loads the
entry point, because the merge guard is what it tests.
