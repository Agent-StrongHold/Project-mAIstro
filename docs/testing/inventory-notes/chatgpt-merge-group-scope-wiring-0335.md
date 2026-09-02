---
inventory-delta:
  tests/: +5
---
# chatgpt-merge-group-scope-wiring-0335

A correction to this branch's own count, not new tests. Recorded as a
companion note so `chatgpt-merge-group-scope-wiring.md` keeps its author's
prose intact; the two fold together to the true +21.

That note records +16 and describes "thirteen" scope-contract cases plus three
`gates-ran` cases. Thirteen is the number of *behaviours*; the collector counts
node IDs, and `test_check_integration_scope.py` parametrizes several of them,
so it collects 18 rather than 13. With `test_gates_ran_merge_group_scope.py`'s
3, the two new files contribute 21.

Measured on this branch after merging develop at `20cbf35`:

```
18  tests/test_check_integration_scope.py      (new)
 3  tests/test_gates_ran_merge_group_scope.py  (new)
40  tests/test_check_branch_protection.py      (modified, count unchanged)
26  tests/test_check_gates_ran.py              (modified, count unchanged)
```

The two modified files change assertions and formatting without adding or
removing a node, which is why the whole delta is the two new files.

This is the drift the inventory gate exists to surface: a prose count of
scenarios and a collected count of node IDs diverge the moment `parametrize`
appears, and only the collected number gates.
