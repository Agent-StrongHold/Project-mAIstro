---
inventory-delta:
  packages/maistro-core/tests: +16
---
# claude-issue-729-canonical-checkpoint-has-no-consumer-4541

One new file, no removals and no renames — the +16 is all addition.

`tests/events/test_checkpoint_contract_states_its_reach.py` proves the six
criteria of SPEC-083026-7297: that the superseded checkpoint contract states its
reach and names `DurableRunRecord` as its successor; that `maistro.events` no
longer publishes it and no keep-alive tuple remains; that the reachability
baseline and dispositions ledger now classify it with an owner and a successor;
that the two same-named `CheckpointStore` protocols name each other and say
which is the reached one; that the absences the module claims are true; and that
the container wires no second checkpoint store.

Four of them are guards on claims rather than on behaviour, and each is paired
with a check that the guard can actually fail: the migration scan asserts it has
a corpus, the import scan asserts it finds an import when shown one, and the
protocol test asserts the two really do share a name and no methods — the
premise the disambiguation rests on.
