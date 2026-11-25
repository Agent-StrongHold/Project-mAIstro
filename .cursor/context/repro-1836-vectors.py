"""Re-execute SPEC-101826 golden vectors V-1..V-18 (read-only probe; digests are content-derived, head-independent)."""

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

sys.path.insert(0, "packages/maistro-core/src")
from maistro.capabilities.approval_store import DurableApproval, approval_request_digest
from maistro.capabilities.slots.approval import ApprovalRequest

V2_PREFIX = b"maistro.approval-payload/v2\n"


def canonical_json(payload):
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def v2_digest(payload):
    return "v2:" + hashlib.sha256(V2_PREFIX + canonical_json(payload).encode("utf-8")).hexdigest()


UNSUPPORTED = (datetime, bytes, UUID, Decimal, set, object, float)  # NaN float handled below


def _reject_non_finite_float(value, path):
    if value != value or value in (float("inf"), float("-inf")):
        raise TypeError(f"non-finite float at {path}")


def strict_walk(value, path):
    # bool is an int subclass but is checked (and returned) first, so the int
    # branch below never sees one.
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        _reject_non_finite_float(value, path)
        return
    if isinstance(value, str):
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            strict_walk(v, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"non-string mapping key at {path} (got {type(k).__name__})")
            strict_walk(v, f"{path}.{k}" if path else k)
        return
    raise TypeError(f"unsupported value type {type(value).__name__} at {path}")


golden = {
    "action": "invoke:sql.execute",
    "delegate_principal": "node-run-41f3",
    "effect": {
        "capability": "sql.execute",
        "params": ["acct-7", 10],
        "statement": "UPDATE balances SET amount = amount - ? WHERE id = ?",
        "table": "balances",
    },
    "expires_at": None,
    "human_principal": None,
    "issued_at": "2026-10-18T00:00:00Z",
    "nonce": "9f1c3a7e5b2d4c8a9f1c3a7e5b2d4c8a",
    "policy_version": "capability-policy@2026-10-01",
    "resource_scope": "ws-7/prj-3/binding-9/effect:sql.execute",
    "revocation_ref": None,
}

SPEC_BYTES = b'maistro.approval-payload/v2\n{"action":"invoke:sql.execute","delegate_principal":"node-run-41f3","effect":{"capability":"sql.execute","params":["acct-7",10],"statement":"UPDATE balances SET amount = amount - ? WHERE id = ?","table":"balances"},"expires_at":null,"human_principal":null,"issued_at":"2026-10-18T00:00:00Z","nonce":"9f1c3a7e5b2d4c8a9f1c3a7e5b2d4c8a","policy_version":"capability-policy@2026-10-01","resource_scope":"ws-7/prj-3/binding-9/effect:sql.execute","revocation_ref":null}'
SPEC_V1_DIGEST = "v2:8db816aa84b6955686037e02814fdf89dd6e9253418cf4c6e6ef85a5608ca82c"

fails = []


def check(name, cond, detail=""):
    print(
        ("PASS " if cond else "FAIL ")
        + name
        + ((" :: " + str(detail)[:120]) if detail and not cond else "")
    )
    if not cond:
        fails.append(name)


# V-1
b1 = V2_PREFIX + canonical_json(golden).encode()
d1 = "v2:" + hashlib.sha256(b1).hexdigest()
check("V-1 bytes", b1 == SPEC_BYTES)
check("V-1 digest", d1 == SPEC_V1_DIGEST, d1)

# V-2 reordered maps
g2 = dict(reversed(list(golden.items())))
g2["effect"] = dict(reversed(list(golden["effect"].items())))
b2 = V2_PREFIX + canonical_json(g2).encode()
d2 = "v2:" + hashlib.sha256(b2).hexdigest()
check("V-2 reordered byte-identical", b2 == b1)
check("V-2 reordered digest == V-1", d2 == SPEC_V1_DIGEST)

# V-3..V-13 mutation table (mutated key, mutation value, expected digest)
mutations = [
    (
        "human_principal",
        "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        "v2:a09475b36bfd28decaccea8d062f59e9ca9970e48b54aea0b861f46162bef487",
    ),
    (
        "delegate_principal",
        "node-run-9999",
        "v2:f1639e5fea36bdb29ecd2f59bf20e11efd1390212d5af1b704afd8b83f618625",
    ),
    (
        "action",
        "invoke:sql.dropTable",
        "v2:bba2adb9c2edf842bbd937703f6cdee0676a1711533208d6e354fe9166c5be12",
    ),
    (
        "resource_scope",
        "ws-7/prj-3/binding-9/effect:sql.select",
        "v2:3ce73595398b5f74a915eb1cfe6be23c184695bfa1e01b8b855e00e6053744f3",
    ),
    ("effect.params[1]", 11, "v2:48594a25299245092b93ba7ec5bb49a87ee7e21eb3d426e04a2e825bf92f4961"),
    (
        "effect.statement",
        "UPDATE balances SET amount = amount + ? WHERE id = ?",
        "v2:c10eeeedf28a0f03e13515043e4b6223a5e7590c9e652c8f2c6a643e012169a9",
    ),
    (
        "policy_version",
        "capability-policy@2026-10-02",
        "v2:efbe13c28188b4c4ea4a5178554770377c64661b196175fc2ea770fbce7cd8ad",
    ),
    (
        "nonce",
        "8f1c3a7e5b2d4c8a9f1c3a7e5b2d4c8a",
        "v2:3bb2cadcbdcba6a9075e5a5bb33b547680bd7f4b2d9b53ea65cff3e62eaad0fc",
    ),
    (
        "issued_at",
        "2026-10-18T00:00:01Z",
        "v2:57d23c6044357ea5cbc66f3c9125313351d3c6a67b024763175d3cabb93342f6",
    ),
    (
        "expires_at",
        "2026-10-18T01:00:00Z",
        "v2:d81bf827a08941b71b2765f67a5d0751f1fc275ed3dc5e70d616ed90af347189",
    ),
    (
        "revocation_ref",
        "chain:ws-7#entry-42",
        "v2:b0632e0f6dd44598605d04e1d47ebefc68ed8c72a11e91e83a77b01f24350bf3",
    ),
]


def apply_mutation(mut_path, value):
    g = copy.deepcopy(golden)
    if mut_path == "effect.params[1]":
        g["effect"]["params"][1] = value
    elif mut_path == "effect.statement":
        g["effect"]["statement"] = value
    else:
        g[mut_path] = value
    return g


digests = [SPEC_V1_DIGEST]
for i, (key, val, expected) in enumerate(mutations, start=3):
    d = v2_digest(apply_mutation(key, val))
    check(f"V-{i} {key}", d == expected, d)
    digests.append(d)
check("V-3..V-13 all distinct from V-1 and each other", len(set(digests)) == len(digests))

# V-14
b_true = V2_PREFIX + canonical_json({"flag": True}).encode()
b_one = V2_PREFIX + canonical_json({"flag": 1}).encode()
b_10 = V2_PREFIX + canonical_json({"n": 10}).encode()
b_10f = V2_PREFIX + canonical_json({"n": 10.0}).encode()
check(
    "V-14 true != 1 bytes",
    b_true == b'...{"flag":true}'.replace(b"...", V2_PREFIX)
    and b_one == V2_PREFIX + b'{"flag":1}'
    and b_true != b_one,
)
check(
    "V-14 10 != 10.0 bytes",
    b_10 == V2_PREFIX + b'{"n":10}' and b_10f == V2_PREFIX + b'{"n":10.0}' and b_10 != b_10f,
)


# V-15 rejection table (v2 recipe via strict walk; production v1 helper shows the hazard)
def v2_strict(payload):
    strict_walk(payload, "")
    return hashlib.sha256((V2_PREFIX + canonical_json(payload)).encode()).hexdigest()


rej = [
    (
        "datetime",
        {"issued_at": datetime(2026, 10, 18, tzinfo=UTC)},
        "unsupported value type datetime at issued_at",
    ),
    ("bytes", {"issued_at": b"raw-bytes"}, "unsupported value type bytes at issued_at"),
    (
        "UUID",
        {"issued_at": UUID("12345678-1234-5678-1234-567812345678")},
        "unsupported value type UUID at issued_at",
    ),
    ("Decimal", {"issued_at": Decimal("10.00")}, "unsupported value type Decimal at issued_at"),
    ("set", {"issued_at": {"a", "b"}}, "unsupported value type set at issued_at"),
    ("object", {"issued_at": object()}, "unsupported value type object at issued_at"),
    ("non-str key", {"effect": {1: "one"}}, "non-string mapping key at effect (got int)"),
    ("NaN", {"issued_at": float("nan")}, "non-finite float at issued_at"),
]
for name, payload, expected_msg in rej:
    try:
        v2_strict(payload)
        check(f"V-15 {name} raises TypeError", False, "no raise")
    except TypeError as e:
        check(f"V-15 {name}", str(e) == expected_msg, str(e))

# v1 hazard column spot-checks (production helper silently digests)
h1 = approval_request_digest({"issued_at": Decimal("10.00")})
check(
    "V-15 v1 hazard Decimal coerced",
    json.dumps({"issued_at": "10.00"}, sort_keys=True, separators=(",", ":"), default=str)
    == '{"issued_at":"10.00"}'
    and len(h1) == 64,
)

# V-16 v1 collision via production helper
c1 = approval_request_digest({"1": "a"})
c2 = approval_request_digest({1: "a"})
check("V-16 v1 {'1':a} == {1:a} digest", c1 == c2)
try:
    approval_request_digest({1: "a", "1": "b"})
    check("V-16 v1 mixed keys raise", False, "no raise")
except TypeError as e:
    check(
        "V-16 v1 mixed keys raise",
        "'<' not supported between instances of 'str' and 'int'" in str(e),
        str(e),
    )

# V-17 ensure_ascii pin
v1b = json.dumps({"name": "café"}, sort_keys=True, separators=(",", ":"), default=str).encode()
check("V-17 v1 bytes", v1b == b'{"name":"caf\\u00e9"}', v1b)
check(
    "V-17 v1 digest",
    approval_request_digest({"name": "café"})
    == "9db11f5f5dc2b3898bb358a2e545b3c96e9052c61e2b4f4de41acded22ef5128",
)
v2b = canonical_json({"name": "café"}).encode()
check("V-17 v2 bytes same escape", v2b == b'{"name":"caf\\u00e9"}', v2b)

# V-18 legacy row via production helper + DurableApproval fallback
inner = {"amount": 10, "currency": "USD"}
check(
    "V-18 v1 bytes",
    json.dumps(inner, sort_keys=True, separators=(",", ":"), default=str).encode()
    == b'{"amount":10,"currency":"USD"}',
)
check(
    "V-18 v1 digest",
    approval_request_digest(inner)
    == "1748e5b562237637f7af0d4e3d15d118c268e47a60ed8f248142dc1c978dc6c9",
    approval_request_digest(inner),
)
legacy_req = ApprovalRequest(
    action="invoke:ledger.credit",
    params={"amount": 10, "currency": "USD"},
    tier="standard",
    requester="node-run-41f3",
)
da = DurableApproval(
    request=legacy_req,
    workspace_id="ws-7",
    project_id="prj-3",
    run_id="run-1",
    node_run_id="node-run-41f3",
    attempt_id="att-1",
    binding_id="binding-9",
    effect_key="effect:sql.execute",
    request_digest="",
)
check(
    "V-18 DurableApproval fallback digest",
    da.request_digest == "1748e5b562237637f7af0d4e3d15d118c268e47a60ed8f248142dc1c978dc6c9",
    da.request_digest,
)

print()
print("RESULT:", "ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
