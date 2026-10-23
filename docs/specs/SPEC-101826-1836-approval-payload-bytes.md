---
id: SPEC-101826-1836
title: "Exact-effect approval payload bytes — versioned canonical serialization contract"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-10-18
substrate:
  - maistro-engine#ADR-090726-9a4e
  - maistro-engine#ADR-032
implements:
  - maistro-engine#ADR-090726-9a4e
related:
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-083026-6c72
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/capabilities/test_durable_approval.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-18
    reason: >-
      Draft contract for decision gate #1836 ("Freeze exact-effect payload bytes"),
      prepared for the named ADR owner's review. Nothing here is accepted, and no
      implementation is authorized or claimed by this document.
  - status: Proposed
    date: 2026-10-18
    revision: 2
    reason: >-
      Corrected the V-17 DurableApproval legacy-fallback digest to the
      reproducible value after independent re-execution against the production
      model (erratum recorded inline at V-17). No other section changed.
  - status: Proposed
    date: 2026-10-20
    revision: 4
    reason: >-
      Corrected the V-15 `set` row's "v1 would have digested" column: the
      frozen v1 recipe digests a set silently through `default=str`
      (rendering `{"issued_at":"{'a', 'b'}"}` with arbitrary element order),
      it does not raise `TypeError`; re-executed against the production
      helper. No other row, vector, byte, or digest value changed.
  - status: Proposed
    date: 2026-10-20
    revision: 3
    reason: >-
      Renumbered the golden vectors so every vector has exactly one number.
      The mutation table holds eleven rows (one mutation per protected field
      plus a second, nested effect mutation) but was labeled "V-3 … V-12",
      which spans only ten numbers; it is now V-3 … V-13, and the subsequent
      vectors shift by one (distinct values V-14, unsupported types V-15, key
      collision V-16, ensure_ascii pin V-17, legacy row V-18 — the erratum
      location of revision 2). All cross-references updated; no input, byte,
      or digest value changed.
---

# SPEC-101826-1836: Exact-effect approval payload bytes — versioned canonical serialization contract

- **Status:** Proposed

## Decision boundary — read this first

This document is the review artifact for decision gate
[#1836](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1836) under the
accepted Hybrid ADR
([ADR-090726-9a4e](../adr/ADR-090726-9a4e-crypto-bound-approvals-hybrid-webauthn-biscuit-hash-chain.md)).
Per that gate, only the ADR owner (`@BlakeMatthews-dev`) or an explicitly
designated architecture/security reviewer can accept this one contract and its
vectors, recording the reviewed section, exact revision, reviewer, and decision
link on the gate issue. **This document has not been accepted.** The gate stays
open until that explicit acceptance exists, and downstream leaves (#1837 WebAuthn
adapter, #1838 Biscuit adapter, and the payload-consuming implementation work)
stay blocked by the gate, not by this file. No code, test, or schema in this
repository implements this contract yet, and completing this document claims no
implementation and no test pass.

What the deterministic hygiene command proves is exactly what the gate says it
proves: prospective document hygiene. It cannot ratify a security contract.

## Context

`approval_request_digest` in `maistro.capabilities.approval_store` binds a
durable human approval to the exact requested effect. Today (verification head
`31d891a561dffd6db1312ea4a85c4835c8048440`) its input bytes are:

```python
json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
```

Three properties of those bytes are unfit for the cryptographic binding
ADR-090726-9a4e Leg 1 requires (WebAuthn challenge = `request_digest` of the
exact effect):

1. **Unversioned.** Nothing in the bytes says what digest recipe, field set, or
   serialization profile produced them. The bytes cannot evolve (adding the
   #329 expiry or identity fields changes every digest) without silently
   invalidating — or silently re-binding — every stored approval.
2. **`default=str` swallows arbitrary objects.** A `datetime`, `bytes`, `UUID`,
   or any object enters the digest through its `str()` rendering, which is a
   library-version- and timezone-dependent transformation the security boundary
   does not control and cannot audit (V-15/V-17 below show the exact
   renderings). A digest over silently-coerced bytes is not an
   exact-effect binding.
3. **Silent key coercion.** `json.dumps` stringifies non-string mapping keys,
   so `{"1": …}` and `{1: …}` produce identical digests, while mixed keys fail
   mid-serialization (V-16).

The parent (#329) requires the canonical approval payload to cover ten field
classes: human identity, agent/delegate identity, action/capability, resource
scope, artifact/diff/config digest, policy version, nonce, issued-at,
expires-at, and revocation reference. This contract freezes the bytes that
carry them.

## Payload contract

### The canonical payload mapping

The canonical payload is a mapping with **exactly these ten keys, always all
present**, plus nothing else. An unknown key is a contract violation, not an
extension point (unknown keys would change the digest of every other payload
once a producer upgrades). A field whose value is not yet known is `null` —
never omitted, never `""`, so absence is distinguishable from the empty string
and the key set is fixed.

| # | Key | Type (exact) | Covered value | Source at the seam today |
|---|-----|--------------|---------------|--------------------------|
| 1 | `human_principal` | `str` \| `null` | Verified human approver principal. `null` in a request-stage payload; filled only in a settled-stage payload. | `DurableApproval.actor` after `ApprovalStore.resolve` (ADR-090726-9a4e AC-1) |
| 2 | `delegate_principal` | `str` | The requesting agent/delegate identity. | `ApprovalRequest.requester` (the `node_run_id` today; a DID once #302 lands) |
| 3 | `action` | `str` | Action/capability requested. | `ApprovalRequest.action` (`invoke:<capability>`) |
| 4 | `resource_scope` | `str` | The exact resource scope string the effect is scoped to. | workspace/project/binding/effect composite (`binding_id` + `effect_key` + workspace/project IDs) |
| 5 | `effect` | `dict` | The exact effect payload, covered recursively. Artifact, diff, and config digests are fields **inside** this mapping; they are covered because the whole mapping is covered. | the invocation `request` argument of `approval_request_digest` |
| 6 | `policy_version` | `str` | Identity/version of the policy (verdict) that demanded approval. | `PolicyVerdict` identity at the `GovernedInvocation` boundary (ADR-081226-6b46) |
| 7 | `nonce` | `str` | Single-use value making the payload unique. | `ApprovalRequest.request_id` (`uuid4().hex`) |
| 8 | `issued_at` | `str` | Issued-at timestamp, ISO-8601 UTC (`…Z`). | `DurableApproval.created_at` |
| 9 | `expires_at` | `str` \| `null` | Expiry timestamp, ISO-8601 UTC (`…Z`); `null` until the expiry owner contract fixes lifetime semantics. | none today (#329 gap) — **wire presence is fixed here; value policy is not** |
| 10 | `revocation_ref` | `str` \| `null` | Reference to the revocation record; `null` unless revoked. | none today; revocation records live in the hash chain and cite the payload digest |

Exactness rules for every value, at every depth:

- Only exact JSON-native types are covered: `None`, `bool`, `int`, finite
  `float`, `str`, `list`, and `dict`. Exact type, not subclass: an enum member,
  `IntEnum`, or any other subclass is unsupported, because a subclass's JSON
  rendering is an implementation detail of its class, not of this contract.
- Mapping keys must be exactly `str`. Non-string keys are rejected, never
  coerced (v1 coerced them; V-16).
- `bool` is checked before `int` (`true` and `1` are different payloads;
  V-14), and `10` and `10.0` are different payloads (V-14).
- Floats must be finite. `NaN`/`Infinity` are rejected: they have no JSON
  representation and their `str()`/`repr()` round-trip is a serialization
  accident, not a canonical form.
- Timestamps enter as ISO-8601 UTC strings. A `datetime` object is unsupported
  and must be converted by the producer before the payload enters the digest —
  the conversion choice (UTC, `Z` suffix) is part of the producer's obligation,
  so a timezone-library upgrade can never silently change covered bytes.

### Canonical bytes — recipe `v2`

The version-2 digest input is:

```
v2_bytes = b"maistro.approval-payload/v2\n" + canonical_json(canonical_payload)
digest   = "v2:" + sha256(v2_bytes).hexdigest()   # lowercase hex, ASCII
```

- The **domain-separation prefix** is part of the covered bytes. A `v2` digest
  can never equal a `v1` digest or a digest from any other subsystem, and the
  version is self-describing in the bytes a verifier hashes.
- `canonical_json` is `json.dumps(payload, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True, allow_nan=False)` applied **after** the strict walk above
  (which is what makes `allow_nan` unreachable in practice and `default`
  unnecessary).
- `ensure_ascii=True` is an explicit decision, inherited from the frozen v1
  profile: covered bytes are pure ASCII, so no UTF-8 normalization, BOM, or
  encoding negotiation can make two verifiers disagree about the bytes. All
  strings (including non-ASCII, e.g. `"café"` → `caf\u00e9`) are escaped.
- Object keys are sorted lexicographically by code point, recursively —
  reordering any mapping never changes the bytes (V-2).

### Digest values and version detection

- `DurableApproval.request_digest` carries either a bare 64-char hex string
  (a legacy v1 row) or a `v2:`-prefixed string (this contract). The prefix is
  the version tag; string equality remains the only comparison, so no store
  schema change is implied.
- Every **newly minted** approval digests with `v2:`. Minting a v1 digest for a
  new approval violates this contract once it is accepted.

### Digest stages — one schema, two instances

The stage is a value of `human_principal`/`revocation_ref`, not a format
version:

- **Request stage** — `human_principal = null`, `revocation_ref = null`. This
  digest exists before any human acts; it is what `GovernedInvocation` stores
  in `DurableApproval.request_digest`, what the resume path recomputes and
  compares, and what a WebAuthn challenge is derived from (the challenge must
  exist before the authenticator responds, so it cannot cover a principal that
  is only known after verification).
- **Settled stage** — `human_principal` set to the verified approver. This
  digest is the identity-to-payload binding that settlement evidence carries
  into the ADR-090726-9a4e Leg 3 hash chain (V-3 shows the settled-stage
  digest for the golden payload). It is additional evidence; it never replaces
  the request-stage digest in `DurableApproval.request_digest`, so resume-time
  re-verification keeps comparing like against like.

### Redacted display versus integrity-covered data

The digest covers the **unredacted** integrity payload. The redacted copy that
`redact_approval_value` produces (`ApprovalRequest.params["request"]`) is
display data for the human reviewing the approval; it is not a digest input
and must never become one. Consequences, all intentional:

- A verifier holding only the redacted display row cannot recompute the
  digest — verification compares digests (live request → recomputed digest vs.
  stored `request_digest`; settlement evidence → settled digest vs. chain
  record), it never re-derives them from display data.
- Redaction-policy changes (`is_secret_key_name` classification gains a
  pattern) change what humans see, never what was approved. The reverse —
  making the digest redaction-stable — would force either weakening display
  redaction or approving over redacted bytes, and is rejected.
- Integrity data (the unredacted payload) must therefore be available at every
  verification point: it is the live request at the `GovernedInvocation`
  boundary, and it is the producer's input at settlement. Storing integrity
  bytes durably alongside the display copy is an implementation decision for
  the downstream leaves, bounded by the retention/PII rules that govern those
  stores.

### Wire representation versus lifetime policy

This contract freezes **representation**: the key set, types, absent encoding,
byte recipe, and digest values. It does not decide **lifetime**: TTL values,
whether/when `expires_at` must be non-null, revocation flow, quorum, or
recovery behavior. Those remain with their separate owner contracts (#329
expiry semantics; the revocation owner). The wire carries `expires_at` and
`revocation_ref` as required keys precisely so the lifetime decisions can land
without a second bytes freeze.

## Legacy digest compatibility — the explicit decision

**v1 is frozen, not deleted.** The v1 bytes are exactly the production bytes
at verification head `31d891a56`: `json.dumps(payload, sort_keys=True,
separators=(",", ":"), default=str).encode("utf-8")`, digest =
`sha256` lowercase hex, no prefix, no envelope. The compatibility decision
this contract asks the owner to accept is narrow and explicit:

- `default=str` **continues to exist in v1, for verification of pre-existing
  rows only**, because old rows were minted over `str()`-coerced bytes and a
  verifier that refuses them strands every durable approval written before
  this contract. v1 verification is best-effort by construction: it is only
  sound for payloads that never contained a coerced object, which old rows
  cannot prove after the fact.
- v1 **must not mint new approval digests** once this contract is accepted.
  The only legitimate v1 computations are: re-verification of a stored bare-hex
  row, and the `DurableApproval` legacy fallback (below).
- The `DurableApproval` resolution order (verified against production at the
  head above) stays: explicit `request_digest` field → `params["request_digest"]`
  stamped copy → v1 recompute over `params["request"]` (else `params`). New
  rows enter at step one with a `v2:`-prefixed value; the fallback exists
  solely so legacy rows keep resolving (V-18).

## Helper module path — the selection

The contract selects the **existing** module path; no new package:

- `packages/maistro-core/src/maistro/capabilities/approval_store.py`
  (`maistro.capabilities.approval_store`):
  - `approval_request_digest(request)` — unchanged name and signature;
    documented as the frozen v1 verifier for legacy rows.
  - `canonical_approval_payload_bytes(payload) -> bytes` — **new**; the strict
    walk + `v2` envelope exactly as specified above. Raises `TypeError` naming
    the offending path for every unsupported value.
  - `approval_request_digest_v2(payload) -> str` — **new**; returns the
    `v2:`-prefixed digest.
- `GovernedInvocation` (`packages/maistro-core/src/maistro/capabilities/governed_invocation.py`)
  mints the request-stage payload per the inventory table and stores
  `approval_request_digest_v2(...)`; the resume comparison is unchanged string
  equality.

## Golden vectors

All digests below were computed by executing the recipes of this document
(v1 values with the unmodified production helper, v2 values with the recipe
exactly as written) at verification head `31d891a56`. The golden payload is the
request-stage canonical payload:

```json
{"action": "invoke:sql.execute", "delegate_principal": "node-run-41f3",
 "effect": {"capability": "sql.execute", "params": ["acct-7", 10],
            "statement": "UPDATE balances SET amount = amount - ? WHERE id = ?",
            "table": "balances"},
 "expires_at": null, "human_principal": null, "issued_at": "2026-10-18T00:00:00Z",
 "nonce": "9f1c3a7e5b2d4c8a9f1c3a7e5b2d4c8a",
 "policy_version": "capability-policy@2026-10-01",
 "resource_scope": "ws-7/prj-3/binding-9/effect:sql.execute",
 "revocation_ref": null}
```

**V-1 — canonical bytes and digest (request stage).**

```
bytes  = b'maistro.approval-payload/v2\n{"action":"invoke:sql.execute","delegate_principal":"node-run-41f3","effect":{"capability":"sql.execute","params":["acct-7",10],"statement":"UPDATE balances SET amount = amount - ? WHERE id = ?","table":"balances"},"expires_at":null,"human_principal":null,"issued_at":"2026-10-18T00:00:00Z","nonce":"9f1c3a7e5b2d4c8a9f1c3a7e5b2d4c8a","policy_version":"capability-policy@2026-10-01","resource_scope":"ws-7/prj-3/binding-9/effect:sql.execute","revocation_ref":null}'
digest = v2:8db816aa84b6955686037e02814fdf89dd6e9253418cf4c6e6ef85a5608ca82c
```

**V-2 — reordered maps.** Reversing the top-level key order **and** the nested
`effect` key order produces byte-identical output and the V-1 digest.

**V-3 … V-13 — one mutation per protected field.** Each row changes exactly
the named key and must produce a digest different from V-1 (all shown digests
differ from V-1 and from each other). The `effect` key carries two rows — a
list element (V-7) and a nested string (V-8) — to show that coverage is
recursive, not top-level-only; every other key carries exactly one row:

| Mutated key | Mutation | Digest |
|---|---|---|
| `human_principal` (settled stage) | `"did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"` | `v2:a09475b36bfd28decaccea8d062f59e9ca9970e48b54aea0b861f46162bef487` |
| `delegate_principal` | `"node-run-9999"` | `v2:f1639e5fea36bdb29ecd2f59bf20e11efd1390212d5af1b704afd8b83f618625` |
| `action` | `"invoke:sql.dropTable"` | `v2:bba2adb9c2edf842bbd937703f6cdee0676a1711533208d6e354fe9166c5be12` |
| `resource_scope` | `"ws-7/prj-3/binding-9/effect:sql.select"` | `v2:3ce73595398b5f74a915eb1cfe6be23c184695bfa1e01b8b855e00e6053744f3` |
| `effect` (`params[1]`) | `10` → `11` | `v2:48594a25299245092b93ba7ec5bb49a87ee7e21eb3d426e04a2e825bf92f4961` |
| `effect.statement` (sign flip) | `amount - ?` → `amount + ?` | `v2:c10eeeedf28a0f03e13515043e4b6223a5e7590c9e652c8f2c6a643e012169a9` |
| `policy_version` | `"capability-policy@2026-10-02"` | `v2:efbe13c28188b4c4ea4a5178554770377c64661b196175fc2ea770fbce7cd8ad` |
| `nonce` | leading `9` → `8` | `v2:3bb2cadcbdcba6a9075e5a5bb33b547680bd7f4b2d9b53ea65cff3e62eaad0fc` |
| `issued_at` | `"2026-10-18T00:00:01Z"` | `v2:57d23c6044357ea5cbc66f3c9125313351d3c6a67b024763175d3cabb93342f6` |
| `expires_at` | `"2026-10-18T01:00:00Z"` | `v2:d81bf827a08941b71b2765f67a5d0751f1fc275ed3dc5e70d616ed90af347189` |
| `revocation_ref` | `"chain:ws-7#entry-42"` | `v2:b0632e0f6dd44598605d04e1d47ebefc68ed8c72a11e91e83a77b01f24350bf3` |

**V-14 — distinct values that naive canonicalization collapses.**

```
{"flag": true}  ≠ {"flag": 1}      # b'...{"flag":true}' vs b'...{"flag":1}'
{"n": 10}       ≠ {"n": 10.0}      # b'...{"n":10}'     vs b'...{"n":10.0}'
```

**V-15 — unsupported value types are rejected, never coerced.** Each input, at
`issued_at` (the mapping-key case at `effect`), raises `TypeError` with the
path-naming message; the "v1 would have produced" column is what the frozen
legacy recipe silently digests for the same input, i.e. the hazard:

| Unsupported value | v2 behavior | v1 would have digested |
|---|---|---|
| `datetime(2026, 10, 18, tzinfo=utc)` | `TypeError: unsupported value type datetime at issued_at` | `{"issued_at":"2026-10-18 00:00:00+00:00"}` |
| `b"raw-bytes"` | `TypeError: unsupported value type bytes at issued_at` | `{"issued_at":"b'raw-bytes'"}` |
| `UUID("12345678-…")` | `TypeError: unsupported value type UUID at issued_at` | `{"issued_at":"12345678-1234-5678-1234-567812345678"}` |
| `Decimal("10.00")` | `TypeError: unsupported value type Decimal at issued_at` | `{"issued_at":"10.00"}` |
| `{"a", "b"}` (set) | `TypeError: unsupported value type set at issued_at` | `{"issued_at":"{'a', 'b'}"}` (silent `str()`, element order unsorted) |
| `object()` | `TypeError: unsupported value type object at issued_at` | `{"issued_at":"<object object at 0x…>"}` (address varies!) |
| `{1: "one"}` (non-str key) | `TypeError: non-string mapping key at effect (got int)` | silent: `{"effect":{"1":"one"}}` |
| `float("nan")` | `TypeError: non-finite float at issued_at` | `{"issued_at":NaN}` (invalid JSON) |

The `object()` row is the point of the whole table: v1's digest depended on a
memory address; v2 refuses to guess.

**V-16 — non-string key collision in v1 (why v2 rejects).** With the frozen
v1 recipe, `{"1": "a"}` and `{1: "a"}` both produce bytes `{"1":"a"}` —
distinct payloads, identical digests — while `{1: "a", "1": "b"}` raises
`TypeError: '<' not supported between instances of 'str' and 'int'`
mid-serialization. v2 rejects every non-`str` key up front.

**V-17 — `ensure_ascii` pin.** v1 (frozen) and v2 both digest
`{"name": "café"}` as `{"name":"caf\u00e9"}` — bytes
`b'{"name":"caf\\u00e9"}'`, v1 digest
`9db11f5f5dc2b3898bb358a2e545b3c96e9052c61e2b4f4de41acded22ef5128`.

**V-18 — legacy row.** For inner payload `{"amount": 10, "currency": "USD"}`:
v1 bytes `b'{"amount":10,"currency":"USD"}'`, digest
`1748e5b562237637f7af0d4e3d15d118c268e47a60ed8f248142dc1c978dc6c9`
(production helper and inline recipe agree). Verified end-to-end on the
production model: a `DurableApproval` built with an empty `request_digest` and
`params` lacking `request_digest` (and lacking `request`) resolves its digest
to the same
`1748e5b562237637f7af0d4e3d15d118c268e47a60ed8f248142dc1c978dc6c9` —
byte-for-byte the v1 digest of its inner `params` payload, because the
fallback re-digests exactly those bytes (`params.get("request", params)`) —
the fallback path this contract preserves for legacy rows only. *(Erratum,
revision 2: the first draft of this section printed
`b88e7bbbb4ba4dea8a5e2d055a664d69143d6295cf0a4c003f36b597eccdf095` here; that
hex is not reproducible from any construction this document defines and was
wrong. Corrected after independent re-execution of the exact construction
described above; the commit message of the first draft unfortunately repeats
the wrong value.)*

## Implementation mapping (proposal — not authorized by this document)

- Wire + helpers: `maistro.capabilities.approval_store` as selected above.
- Minting: `GovernedInvocation` builds the request-stage payload (inventory
  table) and stores the `v2:` digest; `chat_gate._workflow_request_digest`
  (hive-conductor chat workflow gates) is a separate v1-style consumer
  discovered during review — reconciling it is downstream work, in its own
  change, not part of this gate.
- Vectors: V-1 … V-18 become literal assertions in
  `packages/maistro-core/tests/capabilities/test_durable_approval.py`
  (parametrized over the V-15 rejection table and the V-3 … V-13 mutation
  table), per [`engine#ADR-032`](../adr/ADR-032-contracts-as-acceptance-criteria.md).
  Those tests do not exist yet and this document claims no pass for them.

## What the owner is asked to accept

1. The ten-key inventory, absent-encoding, and exactness rules (the table and
   bullets under "The canonical payload mapping").
2. The `v2` byte recipe: prefix, sort/compact/`ensure_ascii` profile, strict
   walk, `sha256`, `v2:` value prefix, version detection rule.
3. The two-stage scheme (request-stage binding for challenge/resume;
   settled-stage identity binding for chain evidence) and which digest
   `DurableApproval.request_digest` stores.
4. Redacted-display vs. integrity-covered split, including that display rows
   never re-derive digests.
5. The legacy decision: v1 frozen with `default=str` retained for verification
   of old rows only; v1 never mints new approvals; the `DurableApproval`
   fallback preserved for legacy rows.
6. The helper module path and the downstream mapping section.
7. The golden vectors V-1 … V-18 as the transition and regression contract.

## Out of scope

- Any TTL/expiry/revocation **value or flow** decision (separate owner
  contracts; the wire keys here only fix representation).
- WebAuthn adapter selection (#1837) and Biscuit adapter selection (#1838) —
  both consume this contract and stay gated on it.
- Durable storage of integrity bytes, retention, and PII handling for the
  integrity copies (governed by the stores' own contracts).
- The chat-gate digest seam named in the mapping section (own change).
