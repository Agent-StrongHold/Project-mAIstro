---
inventory-delta:
  formal/: +0
---

The develop merge carried the org-bound-global memory visibility rule from #1258,
while the formal isolation property still constructed GLOBAL memories without
passing the generated organization context. The property now exercises the same
organization-bound contract as `matches_scope`, preserving the security behavior
and preventing a false composition failure.
