---
inventory-delta:
  tests/: +1
---

# #860 — preserve both production proxy policies on develop merge

`tests/test_prod_stack_boot_contract.py` adds one regression pinning the actual
`deploy/nginx.conf` retry directive: transport/502/504 retries remain enabled,
but application 503s do not count toward passive upstream ejection (#860 F10).
The existing dead-replica test also requires two upstream tries, alongside its
shared failure zone and bounded connect-timeout checks. These are deployment
configuration regressions, not live nginx failover or exact-RC soak evidence.

The merge keeps develop's 2-second connect timeout and two tries, and #860's
no-retry-on-503 policy. It adds no execution or authorization path; accepted
ADR-081426-1f7c, ADR-081626-f383 and ADR-082126-f69c remain authoritative for
Attempt mechanics/fencing and recurrence admission. Admission deduplication is
not physical-work uniqueness; neither these tests nor the merge prove recovery.
