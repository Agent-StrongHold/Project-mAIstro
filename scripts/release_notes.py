#!/usr/bin/env python3
"""Build the GitHub release body from CHANGELOG.md (E3, #296).

The release plan specifies the body as "CHANGELOG section + the ADR-076 API
statement". The curated `## [X.Y.Z]` section written for E4 already carries an
`### API compatibility` block, so this script *extracts* that section and only
appends the canonical statement when the section does not already contain one —
appending unconditionally would print the API stance twice on every release,
which is exactly the kind of thing nobody notices until a user does.

A release candidate gets an extra banner at the top: it publishes the same
notes as the final release it is a candidate for (the section is keyed on the
base version), and a reader landing on a `-rcN` release needs to know that
before they read notes written in the present tense.

Usage
-----
    scripts/release_notes.py --tag v1.0.0-rc1 --version 1.0.0 --output notes.md

`--version` is the base version the guard already resolved; passing it rather
than re-deriving it keeps one parser for the tag grammar.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REPO_URL = "https://github.com/Agent-StrongHold/Project-mAIstro"

# Fallback only. The maintained wording lives in CHANGELOG.md's
# "### API compatibility" block (E4); this exists so a release cut before that
# block is written still states the API stance rather than silently omitting it.
API_STATEMENT = """### API compatibility

**The stable HTTP surface in this release is the `/v1` route mount.** Clients
should address `/v1/...` paths directly.

[ADR-076](docs/adr/ADR-076-http-api-versioning.md) specifies version selection
by **content negotiation** (`Accept: application/vnd.maistro.vN+json`). **That
scheme is not implemented** in this release — do not write clients against it.

The API version axis is independent of the package version: a `1.x` package
release does not imply a `/v2` HTTP surface.
"""


def extract_section(changelog_text: str, version: str) -> str | None:
    """Return the body of the `## [version]` section, without its heading.

    Stops at the next level-2 heading. Tolerates the unbracketed `## 1.0.0`
    form for the same reason release_guard.py does.
    """
    start = re.compile(rf"^##\s+\[?{re.escape(version)}\]?(?:\s|$).*$", re.MULTILINE)
    match = start.search(changelog_text)
    if match is None:
        return None
    rest = changelog_text[match.end() :]
    nxt = re.compile(r"^##\s", re.MULTILINE).search(rest)
    body = rest[: nxt.start()] if nxt else rest
    return _drop_trailing_link_defs(body.strip("\n"))


def _drop_trailing_link_defs(body: str) -> str:
    """Trim the Keep-a-Changelog link-reference block off the tail.

    The oldest section in the file is followed by `[1.0.0]: https://...`
    definitions with no further `##` heading to stop at, so they land inside
    the extracted body. They resolve nothing on a GitHub release page (there
    are no `[1.0.0]` references in the section) and read as stray URLs.
    """
    lines = body.split("\n")
    link_def = re.compile(r"^\[[^\]]+\]:\s")
    while lines and (not lines[-1].strip() or link_def.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)


def build(tag: str, version: str, changelog: Path) -> str:
    text = changelog.read_text(encoding="utf-8")
    section = extract_section(text, version)
    if section is None:
        raise SystemExit(
            f"::error::{changelog} has no '## [{version}]' section — "
            f"the release guard should have caught this before the build."
        )

    parts: list[str] = []
    if "-rc" in tag:
        parts.append(
            f"> **Release candidate.** `{tag}` is a candidate for **{version}** and is "
            f"published as a prerelease. Package artifacts carry the version `{version}` "
            f"(the rc suffix lives only in the git tag — see "
            f"[ADR-073126-c4e1]({REPO_URL}/blob/{tag}/docs/adr/"
            f"ADR-073126-c4e1-release-and-versioning-process.md)), so an rc artifact is "
            f"byte-comparable with the final release it becomes. Python packages for a "
            f"candidate go to **TestPyPI**, not PyPI, and no `latest` image tag moves."
        )
        parts.append("")

    parts.append(section)

    # Only when the curated section does not already make the statement.
    if not re.search(r"^###\s+API compatibility\s*$", section, re.MULTILINE):
        parts.append("")
        parts.append(API_STATEMENT.strip())

    parts.append("")
    parts.append(_verification_block(tag))
    return "\n".join(parts).rstrip() + "\n"


def _verification_block(tag: str) -> str:
    """Tell a consumer how to check what they just downloaded.

    Artifacts that ship signatures and checksums nobody is told how to use are
    decoration; the commands belong next to the download links.
    """
    return f"""---

## Verifying this release

**Artifacts.** Wheels and sdists for `maistro-core`, `maistro-canvas`,
`maistro-evolve`, `maistro-rsi` and `maistro-bootstrap`; `SHA256SUMS` over all
of them plus the installers; CycloneDX SBOMs (syft) for the source tree and
both container images; and the `get.sh` / `get.ps1` / `install.sh` installers.

**Checksums.**

```bash
sha256sum --check --ignore-missing SHA256SUMS
```

**Container images.** Published to `ghcr.io` and signed keylessly with cosign
(no long-lived key; the signature is bound to this workflow and this tag):

```bash
cosign verify \\
  --certificate-identity-regexp \\
    '^https://github.com/Agent-StrongHold/Project-mAIstro/\\.github/workflows/release\\.yml@refs/tags/{re.escape(tag)}$' \\
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \\
  ghcr.io/agent-stronghold/maistro-engine:{tag}
```

**Provenance.** The tag is annotated and, per
[ADR-073126-c4e1]({REPO_URL}/blob/{tag}/docs/adr/ADR-073126-c4e1-release-and-versioning-process.md),
points at a commit on `main` (or `integration` for a release candidate).
`release.yml` is the only path that publishes these artifacts."""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tag", required=True, help="the pushed tag, e.g. v1.0.0-rc1")
    parser.add_argument("--version", required=True, help="base version, e.g. 1.0.0")
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    parser.add_argument("--output", type=Path, default=None, help="write here instead of stdout")
    args = parser.parse_args(argv)

    body = build(args.tag, args.version, args.changelog)
    if args.output is not None:
        args.output.write_text(body, encoding="utf-8")
        print(f"wrote {len(body)} bytes of release notes to {args.output}")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
