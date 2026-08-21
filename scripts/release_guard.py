#!/usr/bin/env python3
"""Release-tag guard (E3, #296) — the check `release.yml` runs before it builds.

Implements the version half of ADR-073126-c4e1 §2/§3. The *branch* half (the
tag commit must be an ancestor of `main`, or of `integration` for a release
candidate) needs git and stays in the workflow; this script tells the workflow
which branch to check against via its `target_branch` output.

What it enforces
----------------
1. **Tag shape.** Only `vX.Y.Z` (final) and `vX.Y.Z-rcN` (candidate, N >= 1)
   are releasable. `rc0` is rejected on purpose — ADR §6 starts candidates at
   `rc1`. Anything else (`v1.0`, `v1.0.0-beta`, `1.0.0`, `v1.0.0-rc01`) is a
   typo or a scheme this repo has not decided on, and a typo must not publish.

2. **Base version == root `VERSION`.** The rc suffix is stripped before the
   comparison, because ADR §2 puts the candidate-ness *only* in the tag:
   at `v1.0.0-rc1` every package still reads `1.0.0`, which is what makes rc
   artifacts byte-comparable with the final ones they become.

3. **Every version site agrees with `VERSION`.** Delegated wholesale to
   `scripts/bump_version.py --check`, which already enumerates all 32 sites
   (pyprojects, `__version__` fallbacks, inter-package bounds, app literals).
   Re-implementing that list here would give it a second copy to drift from.

4. **`CHANGELOG.md` has a `## [X.Y.Z]` heading** for the base version. E4's
   acceptance criterion is literally "release.yml guard finds the heading" —
   a release whose notes do not exist should fail before it builds, not after
   it publishes.

Outputs
-------
With `--github-output PATH` it writes the values the rest of the workflow
needs:

    tag=v1.0.0-rc1        the tag as pushed
    version=1.0.0         base version, rc suffix stripped
    prerelease=true       'true' | 'false'
    rc=1                  rc number, empty for a final tag
    minor=1.0             the `X.Y` moving image tag (final releases only)
    target_branch=integration   branch the tag commit must descend from

Usage
-----
    scripts/release_guard.py --tag v1.0.0
    scripts/release_guard.py --tag "$GITHUB_REF_NAME" --github-output "$GITHUB_OUTPUT"

Exit status is 0 only when every check passes; failures print `::error::`
annotations so they surface on the run summary.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# vX.Y.Z or vX.Y.Z-rcN. No leading zeros in the rc number (`-rc01` is a typo,
# not a synonym for `-rc1`), and no other pre-release forms.
TAG_RE = re.compile(
    r"^v(?P<base>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+))(?:-rc(?P<rc>[1-9]\d*))?$"
)


def _load_bump_version():
    """Import scripts/bump_version.py as a module.

    It is not a package and its filename is not importable as `bump_version`
    from an arbitrary cwd, so load it by path rather than mutating sys.path.
    """
    path = ROOT / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("_maistro_bump_version", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SystemExit(f"::error::cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: bump_version defines a @dataclass, and
    # dataclasses resolves the owning module out of sys.modules while
    # processing the class (AttributeError on None otherwise).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _changelog_has_heading(changelog: Path, version: str) -> bool:
    """True when CHANGELOG.md carries a Keep-a-Changelog heading for `version`.

    Matches `## [1.0.0]` with or without a trailing date/`- TBD`, and tolerates
    a bare `## 1.0.0` — the repo uses the bracketed form, but a guard that
    rejects a correct-but-unbracketed heading would block a release over
    punctuation.
    """
    if not changelog.exists():
        return False
    pattern = re.compile(rf"^##\s+\[?{re.escape(version)}\]?(\s|$)", re.MULTILINE)
    return bool(pattern.search(changelog.read_text(encoding="utf-8")))


def guard(tag: str, changelog: Path) -> tuple[int, dict[str, str]]:
    errors: list[str] = []

    match = TAG_RE.match(tag)
    if match is None:
        print(
            f"::error::tag {tag!r} is not a releasable tag. Expected vX.Y.Z "
            f"(final) or vX.Y.Z-rcN with N >= 1 (release candidate) — "
            f"see ADR-073126-c4e1 §2/§6.",
            file=sys.stderr,
        )
        return 1, {}

    base = match.group("base")
    rc = match.group("rc")
    is_prerelease = rc is not None

    version_file = ROOT / "VERSION"
    if not version_file.exists():
        print(f"::error::{version_file} does not exist", file=sys.stderr)
        return 1, {}
    root_version = version_file.read_text(encoding="utf-8").strip()

    if base != root_version:
        errors.append(
            f"tag {tag!r} has base version {base!r} but VERSION says {root_version!r}. "
            f"Package versions never carry the rc suffix (ADR §2), so both a final "
            f"and an rc tag must match VERSION exactly after stripping '-rcN'."
        )

    # Every pyproject / __version__ fallback / inter-package bound / app literal.
    bump_version = _load_bump_version()
    if bump_version.check() != 0:
        errors.append(
            "version sites disagree with VERSION (see the annotations above). "
            "Run `scripts/bump_version.py <version>` and commit before tagging."
        )

    if not _changelog_has_heading(changelog, base):
        errors.append(
            f"{changelog} has no '## [{base}]' heading. Every release ships notes "
            f"(E4/#297); the GitHub release body is extracted from that section."
        )

    if errors:
        print(
            f"::error::release guard FAILED for tag {tag} ({len(errors)} problem(s)):",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1, {}

    outputs = {
        "tag": tag,
        "version": base,
        "prerelease": "true" if is_prerelease else "false",
        "rc": rc or "",
        "minor": f"{match.group('major')}.{match.group('minor')}",
        # ADR §2: a final tag may only point at main; an rc is the sole
        # exception and may point at integration so it can soak there.
        "target_branch": "integration" if is_prerelease else "main",
    }
    kind = f"release candidate rc{rc}" if is_prerelease else "final release"
    print(f"release guard passed: {tag} is a {kind} of {base}")
    print(f"  VERSION, every package version and every app literal agree on {base}")
    print(f"  {changelog.name} has a heading for {base}")
    print(f"  tag commit must descend from '{outputs['target_branch']}' (checked by the workflow)")
    return 0, outputs


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tag", required=True, help="the pushed tag, e.g. v1.0.0 or v1.0.0-rc1")
    parser.add_argument(
        "--changelog", type=Path, default=ROOT / "CHANGELOG.md", help="path to CHANGELOG.md"
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="append key=value outputs here (pass $GITHUB_OUTPUT in CI)",
    )
    args = parser.parse_args(argv)

    status, outputs = guard(args.tag, args.changelog)
    if status == 0 and args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={value}\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
