---
inventory-delta:
  packages/maistro-core/tests: +24
---
# 954 post-install extension lifecycle

The post-install extension lifecycle (#954, under epic #939 / initiative #937)
lands in `packages/maistro-core/src/maistro/extensions/`: disable, enable,
rollback, terminal removal and operator pins, plus SUPERSEDED-on-activation.
The proof harness `scripts/extension_lifecycle_proof.py` gains a
`post-install-lifecycle` stage (7 checks), and its `update-fence` stage's
superseded-record check now accounts for the explicit SUPERSEDED audit row.

## New file

`packages/maistro-core/tests/extensions/test_post_install_lifecycle.py` adds
24 maistro-core node IDs:

- disable stops serving (pointer dropped, `installed_versions` no longer
  lists the extension) while the frozen grant and the append-only trail stay
  intact, requires an ACTIVE record, and is scope-contained;
- enable re-serves without a loader run (the only code-execution seam never
  re-fires), refuses to move a version silently over a live one (the
  reachable path: a DISABLED record under a live pointer), and requires a
  DISABLED record;
- remove is terminal — no lifecycle op resurrects it, a rollback to a removed
  version is refused, a fresh install of the same version is a new
  authorization track, only served records can be removed, and the record
  plus trail stay queryable;
- rollback restores a SUPERSEDED or DISABLED prior version under its frozen
  grant without executing code, refuses unknown/removed/same-version/cross-
  scope targets and a scope with nothing active;
- pins fence activating another version (the fenced candidate stays
  AUTHORIZED, nothing runs) and rolling back away, are audited same-state
  decisions, are idempotent, require a served record, and never fence
  disable/remove so incident response is never blocked;
- activation supersedes the prior ACTIVE record (exactly one ACTIVE per
  scope+extension, explicit audit row) and a superseded record returns only
  via explicit decisions;
- every lifecycle op requires an accountable actor and a recorded reason;
- the store's `clear_active` drops only its own pointer, so disable/remove
  cannot clobber a pointer a concurrent activation already moved.

## Changed file

`packages/maistro-core/tests/extensions/test_lifecycle_proof.py` pins the new
proof stage in `EXPECTED_STAGES` and the boundary note that stays honest
about what remains unproven (restart durability of activation state). No
count change beyond what the new stage adds to the proof run the tests
execute.
