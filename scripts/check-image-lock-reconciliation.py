#!/usr/bin/env python3
"""Reconcile a built image's installed Python distributions against uv.lock.

Issue #348: the scans must audit the same dependency set the image ships.
The Dockerfiles install from `uv export --locked` + `--require-hashes`, so the
shipped set IS the locked set by construction — this gate proves it from the
outside, on the built image, by dumping every installed distribution from the
image's own interpreter and comparing it, name==version for name==version,
against the export of the same lock the image was built from.

Expected side: the `uv export --locked ...` invocation the Dockerfile itself
uses, piped in or passed as a file. Workspace members are excluded from the
export (`--no-emit-workspace`) but ARE installed (non-editable, real
versions), so pass each member pin explicitly:

    --member maistro-core==0.9.0 --member maistro-server==0.9.0

Actual side: `docker run --rm --entrypoint <image-python> <image>`, dumping
`name==version` for every distribution importlib.metadata can see.

Any difference — a package in the image the lock does not name, or a locked
pin the image does not carry — is a red exit with the diff on stdout.

Usage:
    uv export --locked --package maistro-server \
      --extra image --no-dev --no-emit-workspace \
      --format requirements-txt --output-file /tmp/expected.txt
    python scripts/check-image-lock-reconciliation.py \
      --image maistro-engine:pr-123 \
      --python /app/venv/bin/python \
      --expected-file /tmp/expected.txt \
      --member maistro-core==0.9.0 --member maistro-server==0.9.0 \
      --member maistro-canvas==0.9.0

The engine image's contract is maistro-server's `image` extra: the core
surfaces the API server ships (identity, llm, sandbox, observability), the
Canvas package (#1825) and the openai pin the image has always carried. The
export above is the same invocation the root Dockerfile's builder runs, and
the `--member` pins are the workspace members the image installs from the
copied sources with `--no-deps` — the export names their third-party
dependencies, not the members themselves.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# A requirement line in a uv-export requirements.txt: `name==version` at the
# start of a line, optionally followed by markers and hash continuations
# (which are separate lines and never match this prefix pattern).
_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")


def canon(name: str) -> str:
    """PEP 503 normalized name: the lock says `bip-utils`, the wheel metadata
    says `bip_utils` (or `PyJWT` vs `pyjwt`) — same distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


_DUMP = (
    "import importlib.metadata as m; "
    "print(*sorted(f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions()), "
    "sep='\\n')"
)


def parse_expected(text: str) -> tuple[set[str], set[str]]:
    """Returns (unconditional pins, marker-conditional pins).

    uv export lists every environment's entries: `pywin32 ; sys_platform ==
    'win32'` is in the export but correctly absent from a linux image, while
    `secretstorage ; sys_platform == 'linux'` is correctly present. A
    conditional pin matches either way — it gates nothing; its version is
    still checked when it does ship.
    """
    pins: dict[str, str] = {}
    conditional: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        m = _REQ.match(stripped)
        if m:
            name = canon(m.group(1))
            pins[name] = f"{name}=={m.group(2)}"
            if ";" in stripped:
                conditional.add(name)
    if not pins:
        raise SystemExit(
            "error: expected-file contains no `name==version` pins — is it "
            "a `uv export --format requirements-txt` output?"
        )
    return {pins[n] for n in pins} - {pins[n] for n in conditional}, {pins[n] for n in conditional}


def parse_actual(text: str) -> set[str]:
    pins: set[str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("+", "*", "-", "WARN", "Using", "Checked")):
            continue
        m = _REQ.match(line)
        if m:
            pins[canon(m.group(1))] = f"{canon(m.group(1))}=={m.group(2)}"
    if not pins:
        raise SystemExit(f"error: no distributions dumped from the image:\n{text}")
    return set(pins.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", required=True, help="image tag, e.g. maistro-engine:pr-123")
    ap.add_argument(
        "--python",
        default="/app/venv/bin/python",
        help="python interpreter path inside the image (docker --entrypoint)",
    )
    expected_group = ap.add_mutually_exclusive_group(required=True)
    expected_group.add_argument(
        "--expected-file", help="uv export requirements-txt output to reconcile against"
    )
    expected_group.add_argument(
        "--expected-stdin",
        action="store_true",
        help="read the uv export output from stdin",
    )
    ap.add_argument(
        "--member",
        action="append",
        default=[],
        help="workspace member pin installed but not in the export, e.g. "
        "`maistro-core==0.9.0`; repeatable",
    )
    args = ap.parse_args()

    expected_text = (
        sys.stdin.read() if args.expected_stdin else Path(args.expected_file).read_text()
    )
    required, conditional = parse_expected(expected_text)
    for m in args.member:
        name, _, version = m.partition("==")
        if not version:
            raise SystemExit(f"error: --member expects name==version, got: {m}")
        required.add(f"{canon(name)}=={version}")

    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            args.python,
            args.image,
            "-c",
            _DUMP,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return 1
    actual = parse_actual(proc.stdout)

    # Conditional pins gate nothing: their marker may or may not apply on the
    # image's platform. Every pin in the image must be expected (with the
    # expected version); every unconditional expected pin must be in the image.
    everything_expected = required | conditional
    missing = sorted(required - actual)
    extra = sorted(actual - everything_expected)
    skewed = sorted(
        f"{pin} (image) != {everything_expected.intersection({pin}).pop()}"
        for pin in actual & everything_expected
        if everything_expected.intersection({pin}).pop() != pin
    )
    if missing or extra or skewed:
        print(f"image {args.image} does NOT reconcile to the lock:")
        for p in missing:
            print(f"  locked, not in image : {p}")
        for p in extra:
            print(f"  in image, not locked : {p}")
        for p in skewed:
            print(f"  version mismatch     : {p}")
        return 1
    print(
        f"OK: {args.image} ships exactly the locked set "
        f"({len(actual)} distributions, incl. {len(args.member)} workspace member(s); "
        f"{len(conditional)} marker-conditional pin(s) evaluated leniently)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
