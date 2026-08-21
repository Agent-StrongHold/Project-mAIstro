#!/usr/bin/env python3
"""Gate a pip-audit JSON report against a triaged allowlist.

Single source of truth for both pip-audit jobs (ci.yml `security` and
security.yml `Supply chain (pip-audit)`). Those two used to disagree: ci.yml ran
bare `pip-audit --strict` with no allowlist while security.yml carried an inline
allowlist, so a CVE could be simultaneously "triaged and accepted" and "hard
failure" in the same run. One list, one verdict.

Every entry below is a TRIAGED advisory on a transitive dependency with no
upgrade available. An advisory that HAS a fix does not belong here — bump the
dependency instead. Re-check entries whenever the dep tree moves.

Usage:  pip-audit --strict --format=json -r deps.txt > audit.json || true
        python scripts/pip_audit_gate.py audit.json
"""

from __future__ import annotations

import json
import sys

# (package, advisory id) -> why it is accepted. Keyed by the PAIR, not the
# package: exempting a whole package would silently pass every FUTURE advisory
# on it — including one with a fix, or one reachable on a code path the
# triage below never considered. Each new advisory blocks until someone reads
# it and adds its ID here with reasoning specific enough to re-audit.
ALLOWED: dict[tuple[str, str], str] = {
    ("ecdsa", "PYSEC-2026-1325"): (
        "Minerva timing side channel on the P-256 curve via "
        "SigningKey.sign_digest(). Upstream considers side-channel attacks out "
        "of scope and has stated there is no planned fix, so there is no "
        "version to upgrade to. Transitive via bip-utils (the `identity` "
        "extra). maistro.identity derives on Ed25519 and secp256k1 only — it "
        "never touches P-256 — and the attack additionally requires local "
        "timing measurement of signing operations. Not reachable as used."
    ),
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <pip-audit.json>", file=sys.stderr)
        return 2

    with open(argv[1]) as fh:
        data = json.load(fh)

    vulnerable = [d for d in data.get("dependencies", []) if d.get("vulns")]
    blocking: list[tuple[dict, dict]] = [
        (d, v) for d in vulnerable for v in d["vulns"] if (d["name"], v["id"]) not in ALLOWED
    ]

    if blocking:
        print("::error::pip-audit found advisories outside the triaged allowlist:")
        for d, v in blocking:
            fix = v.get("fix_versions") or []
            hint = f"upgrade to {fix[-1]}" if fix else "NO FIX AVAILABLE — needs triage"
            print(f"  {d['name']}=={d['version']} {v['id']} -> {hint}")
        print(
            "\nFix by upgrading the dependency. Only add a (package, advisory) "
            "pair to ALLOWED in scripts/pip_audit_gate.py when no fixed version "
            "exists, and say why."
        )
        return 1

    # Surface accepted-but-still-present advisories so they stay visible rather
    # than silently permanent.
    for d in vulnerable:
        for v in d["vulns"]:
            print(f"allowed: {d['name']}=={d['version']} {v['id']}")
    print(f"pip-audit OK ({len(vulnerable)} known, all triaged in ALLOWED)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
