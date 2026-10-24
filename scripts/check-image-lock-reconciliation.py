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


def parse_expected(text: str) -> tuple[set[str], set[str], dict[str, set[str]]]:
    """Returns (unconditional pins, marker-conditional pins, forked versions).

    uv export lists every environment's entries: `pywin32 ; sys_platform ==
    'win32'` is in the export but correctly absent from a linux image, while
    `secretstorage ; sys_platform == 'linux'` is correctly present. A
    conditional pin matches either way — it gates nothing; its version is
    still checked when it does ship.

    A lock may also resolve one NAME to several VERSIONS across marker
    environments (uv "forks" the resolution): beartype==0.22.9 for
    `python_full_version < '3.15'` and beartype==0.23.1 for `>= '3.15'`
    ship in the same universal export. The export text alone cannot say
    which fork a given image's interpreter takes — that is the install's
    marker evaluation, invisible to this gate — so the third return value
    maps every such name to ALL its locked versions. `main` accepts any of
    them on the actual side (still red for a version the lock never
    shipped) instead of comparing the image against whichever fork the
    last-wins pins dict happened to keep.
    """
    pins: dict[str, str] = {}
    conditional: set[str] = set()
    versions: dict[str, set[str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        m = _REQ.match(stripped)
        if m:
            name = canon(m.group(1))
            pins[name] = f"{name}=={m.group(2)}"
            versions.setdefault(name, set()).add(m.group(2))
            if ";" in stripped:
                conditional.add(name)
    if not pins:
        raise SystemExit(
            "error: expected-file contains no `name==version` pins — is it "
            "a `uv export --format requirements-txt` output?"
        )
    forked = {n: v for n, v in versions.items() if len(v) > 1}
    return (
        {pins[n] for n in pins} - {pins[n] for n in conditional},
        {pins[n] for n in conditional},
        forked,
    )


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
    required, conditional, forked = parse_expected(expected_text)
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
    # expected version, or — for a forked name — one of the lock's versions);
    # every unconditional expected pin must be in the image.
    # Comparing by canonical NAME (not by pin string) is what makes a version
    # skew nameable: `foo==1.0` expected and `foo==2.0` installed shares no
    # exact string, so a set difference alone would report it as a confusing
    # missing+extra pair — and the original string-keyed `skewed` comprehension
    # (`for pin in actual & everything_expected ... .pop() != pin`) compared
    # each pin against itself and could never fire at all.
    #
    # A forked name's expected_by_name holds only whichever fork the set
    # iteration happened to keep, so a name-wise pin equality would red-flag
    # the image for shipping the OTHER fork's version (beartype 0.22.9 on the
    # py3.13 images vs the >=3.15 fork) — a false positive that broke this
    # gate for every image once the lock first forked a version (2026-10-24,
    # CI run 40098994490). A forked name therefore reconciles when the image
    # ships ANY version the lock resolves for it: every locked fork joins the
    # expected set (so the other fork is not an "extra"), and the skew check
    # tests membership in the fork's version set (a version outside every
    # fork is still a skew, named against all of them).
    all_locked_versions = {f"{name}=={version}" for name, vs in forked.items() for version in vs}
    everything_expected = required | conditional | all_locked_versions
    actual_by_name = {p.partition("==")[0]: p for p in actual}
    expected_by_name = {p.partition("==")[0]: p for p in everything_expected}
    skewed_names = {
        name
        for name in actual_by_name.keys() & expected_by_name.keys()
        if actual_by_name[name] != expected_by_name[name]
        and actual_by_name[name].partition("==")[2] not in forked.get(name, set())
    }
    missing = sorted(p for p in required - actual if p.partition("==")[0] not in skewed_names)
    extra = sorted(
        p for p in actual - everything_expected if p.partition("==")[0] not in skewed_names
    )
    skewed = sorted(
        f"{actual_by_name[name]} (image) != {expected_by_name[name]}"
        if name not in forked
        else f"{actual_by_name[name]} (image) is none of the lock's versions "
        f"for this name: {', '.join(sorted(forked[name]))}"
        for name in skewed_names
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
