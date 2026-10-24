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

# One `python_full_version <op> '<version>'` clause inside a PEP 508 marker.
# Only python-version clauses are evaluated; every other variable (platform,
# implementation) is irrelevant to choosing between two pins of the same
# distribution, which is the only case this gate needs to disambiguate.
_PYFULL_CLAUSE = re.compile(r"python_full_version\s*(==|!=|<=|>=|<|>)\s*['\"]([^'\"]+)['\"]")

#: The first line `_DUMP` prints, before the distribution pins: the image
#: interpreter's own `python_full_version`. The marker-variant disambiguation
#: below needs it — `uv export` lists a marker-split dependency (e.g.
#: `beartype==0.22.9 ; python_full_version < '3.15'` beside
#: `beartype==0.23.1 ; python_full_version >= '3.15'`) as two rows, and the
#: image carries exactly one of them.
_PYFULL_LINE = "python-full-version "

_DUMP = (
    "import sys, importlib.metadata as m; "
    "print('python-full-version', '.'.join(str(p) for p in sys.version_info[:3])); "
    "print(*sorted(f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions()), "
    "sep='\\n')"
)


def _version_tuple(text: str) -> tuple[int, ...] | None:
    """`'3.13.16'` -> `(3, 13, 16)`, or `None` for anything else."""
    parts = text.strip().split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _python_full_version_clause_holds(op: str, bound: str, image_version: str) -> bool | None:
    """Whether `image_version <op> bound` holds, compared the way PEP 508 says
    `python_full_version` compares (release tuples, zero-padded). `None` for a
    bound this stdlib-only comparison cannot represent."""
    left, right = _version_tuple(image_version), _version_tuple(bound)
    if left is None or right is None:
        return None
    width = max(len(left), len(right))
    left, right = left + (0,) * (width - len(left)), right + (0,) * (width - len(right))
    return {
        "==": left == right,
        "!=": left != right,
        "<=": left <= right,
        ">=": left >= right,
        "<": left < right,
        ">": left > right,
    }[op]


def _marker_selects_version(marker: str | None, image_version: str | None) -> bool | None:
    """Whether `marker` applies on the image interpreter, or `None` when this
    gate cannot tell (no image version dumped, or clauses it cannot evaluate).
    Clauses other than `python_full_version` are ignored, not failed: a
    `sys_platform` split carries one version per platform, and the image IS on
    its own platform."""
    if marker is None:
        return True
    if image_version is None:
        return None
    result = True
    for op, bound in _PYFULL_CLAUSE.findall(marker):
        holds = _python_full_version_clause_holds(op, bound, image_version)
        if holds is None:
            return None
        result = result and holds
    return result


def canon(name: str) -> str:
    """PEP 503 normalized name: the lock says `bip-utils`, the wheel metadata
    says `bip_utils` (or `PyJWT` vs `pyjwt`) — same distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_expected(text: str) -> tuple[set[str], set[str]]:
    """Returns (unconditional pins, marker-conditional pins).

    uv export lists every environment's entries: `pywin32 ; sys_platform ==
    'win32'` is in the export but correctly absent from a linux image, while
    `secretstorage ; sys_platform == 'linux'` is correctly present. A
    conditional pin matches either way — it gates nothing; its version is
    still checked when it does ship.

    Every marker-carrying row lands in the conditional set — a name the export
    splits across markers (one distribution, several python-version rows)
    keeps all of its rows here, so the image's one build is never mistaken for
    an un-locked extra just because a name-keyed dict could hold only the
    last row.
    """
    unconditional: dict[str, str] = {}
    conditional: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        m = _REQ.match(stripped)
        if m:
            name = canon(m.group(1))
            pin = f"{name}=={m.group(2)}"
            if ";" in stripped:
                conditional.add(pin)
            else:
                unconditional[name] = pin
    if not unconditional and not conditional:
        raise SystemExit(
            "error: expected-file contains no `name==version` pins — is it "
            "a `uv export --format requirements-txt` output?"
        )
    required = set(unconditional.values()) - {
        pin for pin in conditional if pin.partition("==")[0] in unconditional
    }
    return required, conditional


def parse_marker_variants(text: str) -> dict[str, list[tuple[str, str | None]]]:
    """Names the export pins under MORE THAN ONE version, with their markers.

    A python-version split (`beartype==0.22.9 ; < '3.15'` beside
    `beartype==0.23.1 ; >= '3.15'`) is one distribution the image carries
    exactly one build of, not a skew: the lenient conditional treatment cannot
    disambiguate which pin the image should carry. Each entry lists
    `(pin, marker)` per version — `marker` is `None` for an unconditioned row
    — so the skew check can select the pin whose marker applies to the image's
    own interpreter instead of an arbitrary one of the set.
    """
    by_name: dict[str, dict[str, str | None]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        m = _REQ.match(stripped)
        if not m:
            continue
        marker = stripped.split(";", 1)[1].strip() if ";" in stripped else None
        name = canon(m.group(1))
        by_name.setdefault(name, {})[m.group(2)] = marker
    return {
        name: [(f"{name}=={version}", marker) for version, marker in versions.items()]
        for name, versions in by_name.items()
        if len(versions) > 1
    }


def image_python_version(dump_text: str) -> str | None:
    """The `python-full-version` line `_DUMP` prints first, or `None`."""
    for line in dump_text.splitlines():
        if line.startswith(_PYFULL_LINE):
            return line[len(_PYFULL_LINE) :].strip()
    return None


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


def _applicable_variant_pins(expected_text: str, py_version: str | None) -> dict[str, str]:
    """For every marker-split name this gate can disambiguate: the one pin
    whose marker applies on the image interpreter. Names whose applicable pin
    cannot be determined are absent — their caller must gate nothing."""
    applicable: dict[str, str] = {}
    for name, rows in parse_marker_variants(expected_text).items():
        selected = {
            pin for pin, marker in rows if _marker_selects_version(marker, py_version) is True
        }
        if len(selected) == 1:
            applicable[name] = next(iter(selected))
    return applicable


def _skewed(
    actual_by_name: dict[str, str],
    expected_by_name: dict[str, str],
    applicable: dict[str, str],
    variant_names: set[str],
) -> dict[str, str]:
    """Map each name whose installed pin is not the expected one to the pin
    it should have carried.

    A marker-split dependency is pinned under two versions whose markers
    partition the python versions; the image carries the one its interpreter
    selects. Compare against that pin — not an arbitrary member of the set,
    which reported the correct image as skewed whenever the set happened to
    surface the other row. When the applicable pin cannot be determined (no
    dumped interpreter version, markers this gate cannot evaluate), the name
    falls back to the lenient treatment and gates nothing: excluding it is an
    explicit fallback, not a coin-flip between the two rows — which is exactly
    what comparing against the set-arbitrary `expected_by_name` entry would be.
    """

    def _expected_pin(name: str) -> str | None:
        if name in applicable:
            return applicable[name]
        if name in variant_names:
            return None
        return expected_by_name[name]

    skewed: dict[str, str] = {}
    for name in actual_by_name.keys() & expected_by_name.keys():
        expected = _expected_pin(name)
        if expected is not None and expected != actual_by_name[name]:
            skewed[name] = expected
    return skewed


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
    # Comparing by canonical NAME (not by pin string) is what makes a version
    # skew nameable: `foo==1.0` expected and `foo==2.0` installed shares no
    # exact string, so a set difference alone would report it as a confusing
    # missing+extra pair — and the original string-keyed `skewed` comprehension
    # (`for pin in actual & everything_expected ... .pop() != pin`) compared
    # each pin against itself and could never fire at all.
    everything_expected = required | conditional
    actual_by_name = {p.partition("==")[0]: p for p in actual}
    expected_by_name = {p.partition("==")[0]: p for p in everything_expected}
    skewed = _skewed(
        actual_by_name,
        expected_by_name,
        _applicable_variant_pins(expected_text, image_python_version(proc.stdout)),
        set(parse_marker_variants(expected_text)),
    )
    skewed_names = set(skewed)
    missing = sorted(p for p in required - actual if p.partition("==")[0] not in skewed_names)
    extra = sorted(
        p for p in actual - everything_expected if p.partition("==")[0] not in skewed_names
    )
    skewed_lines = sorted(
        f"{actual_by_name[name]} (image) != {expected}" for name, expected in skewed.items()
    )
    if missing or extra or skewed_lines:
        print(f"image {args.image} does NOT reconcile to the lock:")
        for p in missing:
            print(f"  locked, not in image : {p}")
        for p in extra:
            print(f"  in image, not locked : {p}")
        for p in skewed_lines:
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
