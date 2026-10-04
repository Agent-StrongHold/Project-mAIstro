#!/usr/bin/env python3
"""Prune reviewed dependency payloads out of a production environment (#406).

Why this exists
---------------
``pytoniq-core-fork`` — the locked identity stack's transitive dependency,
pulled in by ``bip-utils`` — ships a generic top-level ``examples`` namespace
package in every release it has ever published. bip-utils pins
``pytoniq-core-fork<0.2.0``, pip and uv cannot exclude a subpath of a wheel at
install time, and the shipped images resolve their dependency set with pip at
build time rather than reading uv.lock, so no lock-level override can reach
them. Removing the payload from the environments that ship is therefore a
post-install prune, executed inside the image build and asserted in the same
layer (see ``scripts/check-dependency-namespaces.py --production``).

This is a patch to the installed payload, and it is recorded as one:

- the distribution itself (``pytoniq-core-fork``) stays installed and stays
  named, so SBOM tooling (syft catalogs from ``dist-info``) keeps recording
  the *fork* provenance — ``pkg:pypi/pytoniq-core-fork@0.1.48``;
- ``RECORD`` is rewritten without the pruned rows, so the SBOM's file
  inventory reflects the shipped payload rather than the upstream wheel's, and
  the diff between the two IS the patch record;
- nothing else about the distribution is touched — the prune is keyed to
  (distribution, top-level name) pairs from
  ``PRUNED_IN_PRODUCTION`` in the check script, loaded live so the two gates
  cannot drift apart. A second distribution shipping the same name is NOT
  pruned and will fail the production scan instead: an unreviewed namespace
  must never be silently removed, it must be looked at.

What it does NOT do
-------------------
It does not uninstall the distribution (``bip-utils`` needs ``pytoniq_core``
at import time), does not rewrite code, and does not guess: a target whose
distribution is absent is a no-op with a printed note, not an error — the
image builds that do not install the identity stack (Dockerfile.research) run
the same step and pass through.

Usage
-----
    python scripts/prune-dependency-namespaces.py              # this env's purelib
    python scripts/prune-dependency-namespaces.py \
        --site-packages /app/venv/lib/python3.13/site-packages
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path

_CHECK_SCRIPT = Path(__file__).resolve().parent / "check-dependency-namespaces.py"


def _load_check_module():
    """Load the check script live, so the prune list cannot drift from the gate.

    Same pattern ``tests/test_verify_wheel_imports.py`` uses for its script:
    these are standalone entry points, not a package.
    """
    spec = importlib.util.spec_from_file_location("check_dependency_namespaces", _CHECK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_CHECK_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prune_site_packages(site: Path) -> list[tuple[str, str, int]]:
    """Prune every PRUNED_IN_PRODUCTION payload found under `site`.

    Returns one (top_level, distribution, removed_rows) row per target, so the
    caller prints what actually happened instead of a bare exit code.
    """
    check = _load_check_module()

    results: list[tuple[str, str, int]] = []
    for top, dist_name in sorted(check.PRUNED_IN_PRODUCTION.items()):
        target = check.normalize(dist_name)
        dist_info = _find_dist_info_for(site, target, check.normalize)
        if dist_info is None:
            print(f"prune: {dist_name} not installed under {site}; nothing to prune for {top!r}")
            results.append((top, dist_name, 0))
            continue

        rows = _read_rows(dist_info)
        if rows is None:
            print(
                f"prune: {dist_info.name} has no RECORD; cannot inventory the payload",
                file=sys.stderr,
            )
            results.append((top, dist_name, -1))
            continue

        kept = [row for row in rows if row[0].split("/", 1)[0] != top]
        removed = len(rows) - len(kept)
        if removed:
            _delete_payload(site, top, rows)
            _write_rows(dist_info, kept)
        print(
            f"prune: {top!r} from {dist_name} ({dist_info.name}): {removed} RECORD row(s) removed"
        )
        results.append((top, dist_name, removed))
    return results


def _find_dist_info_for(
    site: Path,
    normalized_name: str,
    normalize: Callable[[str], str],
) -> Path | None:
    """The *.dist-info directory whose METADATA name matches, normalized."""
    for dist_info in sorted(site.glob("*.dist-info")):
        if not dist_info.is_dir():
            continue
        meta = dist_info / "METADATA"
        if not meta.is_file():
            continue
        for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name:"):
                if normalize(line.split(":", 1)[1].strip()) == normalized_name:
                    return dist_info
                break
        else:
            # No Name: header before the first blank line — fall back to the
            # directory stem, which installers keep in sync.
            stem = dist_info.name.split("-")[0]
            if normalize(stem) == normalized_name:
                return dist_info
    return None


def _read_rows(dist_info: Path) -> list[list[str]] | None:
    record = dist_info / "RECORD"
    if not record.is_file():
        return None
    with record.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.reader(fh) if row and row[0]]


def _write_rows(dist_info: Path, rows: list[list[str]]) -> None:
    with (dist_info / "RECORD").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)


def _delete_payload(site: Path, top: str, rows: list[list[str]]) -> None:
    """Delete exactly the paths the pruned RECORD rows described.

    File-by-file, never ``rmtree`` of ``site/<top>``: two distributions can
    legitimately install payloads into the SAME top-level directory (a
    namespace split, or a collision the production gate will then flag), and
    removing the directory would destroy a co-owner's files behind its own
    RECORD's back. Directories are removed only once empty, walked upward.
    """
    touched: list[Path] = []
    site_resolved = site.resolve()
    for row in rows:
        first = row[0].split("/", 1)[0]
        if first != top:
            continue
        try:
            # Resolve before containment: ``relative_to`` compares parts
            # lexically, so ``<top>/../../victim`` slips past it. A RECORD row
            # that resolves outside the scanned environment is not payload we
            # can prove we installed — the scanner skips the same row as an
            # escape, and deletion must be at least as careful as inventory.
            resolved = (site / row[0]).resolve()
            resolved.relative_to(site_resolved)
        except (OSError, ValueError):
            continue
        touched.append(site / row[0])
    for target in touched:
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
    # Prune directories the deletion emptied, from the deepest upward, so the
    # namespace portion disappears cleanly when this distribution owned all
    # of it — and stays for whatever a co-owner still holds.
    parents = {t.parent for t in touched}
    for directory in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        walker = directory
        while walker != site and walker.is_dir() and not any(walker.iterdir()):
            walker.rmdir()
            walker = walker.parent


def assert_not_importable(top: str) -> bool:
    """True when `top` no longer resolves from a fresh interpreter.

    A fresh subprocess, not this process: the interpreter that did the pruning
    may hold the namespace in ``sys.modules`` or a warmed import cache, and a
    check that can pass on stale state is not a check.
    """
    probe = (
        "import importlib.util, sys; "
        f"sys.exit(0 if importlib.util.find_spec({top!r}) is None else 1)"
    )
    return (
        subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--site-packages",
        type=Path,
        default=None,
        help="site-packages to prune (default: this interpreter's purelib)",
    )
    parser.add_argument(
        "--no-import-check",
        action="store_true",
        help="skip the fresh-interpreter find_spec assertion (use when pruning a foreign site)",
    )
    args = parser.parse_args(argv)

    site = args.site_packages or Path(sysconfig.get_paths()["purelib"])
    if not site.is_dir():
        print(f"error: site-packages directory not found: {site}", file=sys.stderr)
        return 2

    results = prune_site_packages(site)

    failures = [r for r in results if r[2] < 0]
    if failures:
        print(f"error: could not inventory {failures}", file=sys.stderr)
        return 1

    if not args.no_import_check:
        for top, dist_name, _ in results:
            if not assert_not_importable(top):
                print(
                    f"error: {top!r} (from {dist_name}) is still importable after the prune — "
                    "a payload this script does not know about is on sys.path",
                    file=sys.stderr,
                )
                return 1
        print(f"verified: {len(results)} pruned namespace(s) no longer importable")

    return 0


if __name__ == "__main__":
    sys.exit(main())
