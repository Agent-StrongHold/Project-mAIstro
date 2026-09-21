---
inventory-delta:
  packages/maistro-core/tests: +17
---
# m2-67-mapped-ipv6 — the reopened finding: mapped-IPv6 spellings

Issue #67 was reopened from post-merge review of #1105 with one live P1:
`http://[::ffff:100.64.0.1]/` reached the guard as an `IPv6Address`, and
neither the stdlib predicates (which do not classify the embedded CGNAT
address) nor the IPv4-only `100.64.0.0/10` entry in `_BLOCKED_NETWORKS`
(whose membership check is version-checked to `False` for an IPv6 address)
refused it. `_is_blocked_address` now normalizes an IPv4-mapped IPv6 address
to the IPv4 address it embeds before **both** policy checks, so any
IPv4-only network entry added later is enforced against the mapped spelling
by construction.

All 17 node IDs are in `packages/maistro-core/tests`:

- `tests/security/test_ssrf.py` (+17, `TestIPv4MappedSpelling`):
  - `test_mapped_cgnat_is_blocked` (4 params) — `::ffff:100.64.0.0`,
    `::ffff:100.64.0.1`, `::ffff:100.100.5.5`, `::ffff:100.127.255.255`;
    both /10 boundaries and the finding's own spelling.
  - `test_mapped_public_space_just_outside_the_prefix_is_allowed` (2) —
    `::ffff:100.63.255.255`, `::ffff:100.128.0.0`: the mask refuses, not
    the mapping.
  - `test_mapped_rfc1918_loopback_and_metadata_stay_blocked` (6) — mapped
    loopback/RFC1918/metadata/unspecified pinned so predicate drift cannot
    quietly un-refuse what the stdlib happened to catch.
  - `test_a_hostname_resolving_to_a_mapped_cgnat_aaaa_is_blocked` (1) — a
    DNS answer in the mapped spelling is refused, reported in the
    resolver's own spelling.
  - `test_every_network_entry_is_enforced_in_both_spellings_by_construction`
    (1) — standing re-audit: feeds the mapped form of every
    `_BLOCKED_NETWORKS` entry's first address through the check, fails if
    normalization ever stops running ahead of the block loop.
  - `test_embeddings_with_no_ipv4_form_are_still_refused` (3) — 6to4, NAT64,
    IPv4-compatible embeddings ride on the stdlib predicates; pinned so a
    Python upgrade that moves either is loud here.

Mutation evidence (run in the lane, not committed): deleting the two
normalization lines makes 6 of these fail — all four mapped-CGNAT URL
cases, the AAAA-answer case, and the by-construction audit — and nothing
else; restoring them returns the file to 86/86 green.

No suite lost or moved counts; the whole delta is additive in maistro-core.
