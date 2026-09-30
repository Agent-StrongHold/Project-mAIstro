#!/usr/bin/env python3
"""Release base/tool images are pinned by immutable digest (#349).

Before this gate, build stages floated on mutable tags and the uv installer was
copied from a `:latest` image, so a registry tag move could change the code that
installs every dependency without a repository diff -- the same drift that fed
the Python/coincurve break. quality/image-inventory.json said it outright: the
released artifact can differ from the scanned one because "mutable bases ...
can make the released artifact differ" (#346's open AC-5, Codex #593).

This gate closes that, in both directions:

- every external image reference (`FROM` / `COPY --from=`) must be pinned
  `name:tag@sha256:<digest>` -- the digest is the resolution authority, the tag
  is the human-readable version annotation;
- `:latest` is rejected everywhere, explicit or implicit (a bare image name
  resolves to `:latest`);
- every pin must be registered in `quality/image-pins.json` with the exact
  image, tag and digest, and every registration must still be used by the
  Dockerfiles its `used_by` names -- so a base update is always a reviewable
  change to this registry plus the Dockerfiles, never a silent tag move;
- a reference without a digest survives only through an owned, issue-numbered
  exemption in `quality/image-pins.json` -- same rule as the image inventory's
  coverage exceptions, because an unowned exemption is just permission.

All digests are manifest-list (index) digests, so one pin fixes every
architecture/platform variant: for a fixed target platform the same index
always resolves to the same per-arch artifact.

Subcommands:
    (none)                          run the gate
    --base-digests DOCKERFILE...    print the pinned base refs, one per line
                                    (release.yml feeds these to the
                                    provenance-attestation check)
    --verify-attestation FILE --dockerfile F
                                    assert every pinned base digest of F
                                    appears in the cosign-downloaded SLSA
                                    provenance attestations in FILE (NDJSON of
                                    base64 DSSE payloads), proving the release
                                    attestation names every base digest

Run: `python scripts/check-image-pins.py`
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "quality" / "image-pins.json"
INVENTORY = ROOT / "quality" / "image-inventory.json"

# Directories that are not this repository's source (mirrors the inventory gate).
_SKIP = ("/.git/", "/node_modules/", "/.venv/", "/site-packages/")

#: `FROM [--flag ...] ref [AS alias]` -- flags and the alias are optional.
FROM_RE = re.compile(
    r"^\s*FROM\s+(?:(?:--\S+)\s+)*(?P<ref>\S+)(?:\s+AS\s+(?P<alias>\S+))?",
    re.IGNORECASE,
)
#: `COPY ... --from=ref ...` -- the source image is one contiguous token.
COPY_FROM_RE = re.compile(r"--from=(?P<ref>\S+)")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Images with no registry existence at all, or not images: build stages are
#: tracked separately; `scratch` is the empty base.
SCRATCH = "scratch"


class Violation:
    """One gate failure, located well enough to fix without re-deriving."""

    def __init__(self, where: str, message: str) -> None:
        self.where = where
        self.message = message

    def render(self) -> str:
        return f"::error::{self.where}: {self.message}"


def split_ref(ref: str) -> tuple[str, str | None, str | None]:
    """Split an image reference into (image, tag, digest).

    The tag is the segment after the last `:` only when that segment contains no
    `/` (otherwise the colon belongs to a registry port). The digest is whatever
    follows the last `@`.
    """
    digest: str | None = None
    name = ref
    if "@" in ref:
        name, _, digest = ref.rpartition("@")
    image, tag = name, None
    if ":" in name:
        head, tail = name.rsplit(":", 1)
        if "/" not in tail:
            image, tag = head, tail
    return image, tag, digest


def is_implicit_latest(tag: str | None) -> bool:
    """No tag at all means the registry's default pointer: `latest`."""
    return tag is None or tag.lower() == "latest"


class DockerfileRefs:
    """The external image references of one Dockerfile, with their locations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        #: (line number, ref, kind) for every external reference found.
        self.refs: list[tuple[int, str, str]] = []
        #: Parse failures that could not be attributed to one ref.
        self.parse_errors: list[str] = []

    def _is_stage(self, ref: str, stages: set[str], stage_count: int) -> bool:
        """`FROM builder` / `COPY --from=0` name a build stage, not an image."""
        return ref.lower() in stages or (ref.isdigit() and int(ref) < stage_count)

    def parse(self) -> DockerfileRefs:
        stages: set[str] = set()
        stage_count = 0
        for lineno, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            from_match = FROM_RE.match(line)
            if from_match:
                stage_count += 1
                ref = from_match.group("ref")
                alias = from_match.group("alias")
                if alias:
                    stages.add(alias.lower())
                if (
                    ref.lower() == SCRATCH
                    or ref.startswith("$")
                    or self._is_stage(ref, stages, stage_count)
                ):
                    continue
                self.refs.append((lineno, ref, "FROM"))
                continue
            if not re.match(r"^\s*COPY\b", line, re.IGNORECASE):
                continue
            source = COPY_FROM_RE.search(line)
            if not source:
                continue
            ref = source.group("ref")
            if self._is_stage(ref, stages, stage_count):
                continue
            if ref.startswith("$"):
                self.parse_errors.append(
                    f"line {lineno}: cannot resolve build-arg reference {ref!r}"
                )
                continue
            self.refs.append((lineno, ref, "COPY --from"))
        return self


def dockerfiles_on_disk() -> list[Path]:
    found = [
        path
        for path in ROOT.rglob("Dockerfile*")
        if path.is_file()
        and not path.name.endswith(".dockerignore")
        and not any(part in str(path) for part in _SKIP)
    ]
    return sorted(found)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc


def release_dispositions() -> dict[str, str]:
    """dockerfile -> disposition, from the image inventory (#346).

    A Dockerfile missing from the inventory is treated as release scope so a
    gate bypass cannot be manufactured by forgetting an entry; the inventory
    gate fails that same tree anyway.
    """
    data = load_json(INVENTORY)
    out: dict[str, str] = {}
    for image in data.get("images", []):
        out[str(image.get("dockerfile"))] = str(image.get("disposition"))
    return out


def check_ref(
    violations: list[Violation],
    usage: dict[tuple[str, str, str], set[str]],
    rel: str,
    lineno: int,
    ref: str,
    kind: str,
    disposition: str,
    exempt: set[tuple[str, str]],
) -> None:
    """Apply the pin rules to one external reference."""
    image, tag, digest = split_ref(ref)
    where = f"{rel}:{lineno} ({kind} {ref})"
    if digest is None and is_implicit_latest(tag):
        violations.append(
            Violation(
                where,
                "mutable image reference: no digest and no tag, this resolves to `:latest`",
            )
        )
        return
    if digest is None:
        if (rel, ref) in exempt:
            return
        if disposition in ("PUBLISHED", "DISTRIBUTED"):
            violations.append(
                Violation(
                    where,
                    f"release Dockerfile ({disposition}) must pin {image} by "
                    "`@sha256:<digest>`; version tags are mutable (#349)",
                )
            )
        else:
            violations.append(
                Violation(
                    where,
                    f"unpinned base {ref!r} needs an owned, issue-numbered "
                    "exemption in quality/image-pins.json",
                )
            )
        return
    if not DIGEST_RE.match(digest):
        violations.append(Violation(where, f"malformed digest {digest!r} (want sha256:<64 hex>)"))
        return
    if tag is None or is_implicit_latest(tag):
        violations.append(
            Violation(
                where,
                "digest-pinned but the tag annotation is missing or `latest`; "
                "name the concrete version so the pin is reviewable (#349)",
            )
        )
        return
    usage.setdefault((image, tag, digest), set()).add(rel)


def check_registration(
    pins: list[dict], usage: dict[tuple[str, str, str], set[str]]
) -> list[Violation]:
    """Hold the registry and the tree to each other, in both directions."""
    violations: list[Violation] = []
    # Every used pin must be registered, with the exact same coordinates.
    for (image, tag, digest), users in sorted(usage.items()):
        rows = [p for p in pins if p.get("image") == image and p.get("digest") == digest]
        if not rows:
            violations.append(
                Violation(
                    f"{image}:{tag}@{digest}",
                    f"pinned digest is not registered in quality/image-pins.json "
                    f"(used by {', '.join(sorted(users))})",
                )
            )
            continue
        if len(rows) > 1:
            violations.append(
                Violation(f"{image}@{digest}", "duplicate pin rows in image-pins.json")
            )
            continue
        row = rows[0]
        if row.get("tag") != tag:
            violations.append(
                Violation(
                    f"{image}:{tag}@{digest}",
                    f"annotation drift: registry records tag {row.get('tag')!r}",
                )
            )
        recorded_users = set(row.get("used_by") or [])
        if recorded_users != users:
            violations.append(
                Violation(
                    f"{image}:{tag}@{digest}",
                    f"used_by drift: registry names {sorted(recorded_users)}, "
                    f"the tree uses {sorted(users)}",
                )
            )

    # ...and every registration must still be used: the registry cannot rot
    # into a list of pins nothing builds anymore.
    used_keys = {(image, digest) for (image, _tag, digest) in usage}
    for row in pins:
        key = (str(row.get("image")), str(row.get("digest")))
        if key not in used_keys:
            violations.append(
                Violation(
                    "quality/image-pins.json",
                    f"pin {row.get('image')}:{row.get('tag')}@{row.get('digest')} "
                    "is not referenced by any Dockerfile",
                )
            )
        if str(row.get("tag")).lower() == "latest":
            violations.append(
                Violation(
                    "quality/image-pins.json",
                    f"pin for {row.get('image')} records a `latest` tag; pins must "
                    "name the concrete release",
                )
            )
        if not DIGEST_RE.match(str(row.get("digest") or "")):
            violations.append(
                Violation(
                    "quality/image-pins.json",
                    f"pin for {row.get('image')}:{row.get('tag')} has a malformed "
                    f"digest {row.get('digest')!r}",
                )
            )
    return violations


def run_gate() -> int:
    pins_doc = load_json(PINS)
    dispositions = release_dispositions()

    violations: list[Violation] = []
    files = dockerfiles_on_disk()
    usage: dict[tuple[str, str, str], set[str]] = {}

    exempt = {
        (str(e.get("file")), str(e.get("ref")))
        for e in pins_doc.get("exemptions", [])
        if e.get("file") and e.get("ref")
    }

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        doc = DockerfileRefs(path).parse()
        for message in doc.parse_errors:
            violations.append(Violation(f"{rel}: {message}", "unparseable reference"))
        disposition = dispositions.get(rel, "PUBLISHED")
        for lineno, ref, kind in doc.refs:
            check_ref(violations, usage, rel, lineno, ref, kind, disposition, exempt)

    violations.extend(check_registration(pins_doc.get("pins", []), usage))

    for violation in violations:
        print(violation.render(), file=sys.stderr)
    if violations:
        print(
            f"check-image-pins: {len(violations)} violation(s)",
            file=sys.stderr,
        )
        return 1
    print(
        f"check-image-pins: {len(usage)} pinned base/tool image(s) across "
        f"{len(files)} Dockerfile(s), all registered in image-pins.json"
    )
    return 0


def base_digests(dockerfiles: list[str]) -> list[str]:
    """Pinned external refs of the given Dockerfiles, `name:tag@sha256:...`."""
    refs: set[str] = set()
    for name in dockerfiles:
        path = ROOT / name
        if not path.is_file():
            raise SystemExit(f"no such Dockerfile: {name}")
        for _lineno, ref, _kind in DockerfileRefs(path).parse().refs:
            _image, tag, digest = split_ref(ref)
            if digest is None or tag is None:
                raise SystemExit(
                    f"{name}: {ref!r} is not digest-pinned with a version tag; "
                    "the release path cannot enumerate it"
                )
            name_part = ref.rpartition("@")[0]
            refs.add(f"{name_part}@{digest}")
    return sorted(refs)


def verify_attestation(attestation_file: str, dockerfile: str) -> int:
    """Every pinned base digest of `dockerfile` must appear in the attestations.

    `attestation_file` holds the NDJSON output of
    `cosign download attestation <image>@<digest>`: one record per line, each
    carrying a base64 DSSE payload whose inner payload is the in-toto statement.
    buildx's SLSA provenance (mode=max) names every base image it resolved under
    `resolvedDependencies`, so each digest appearing there is what proves the
    release attestation covers every base (#349's last acceptance criterion).
    """
    wanted = base_digests([dockerfile])
    if not wanted:
        raise SystemExit(f"{dockerfile}: no pinned base references found")
    try:
        raw = Path(attestation_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read {attestation_file}: {exc}") from exc

    blob_parts: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            envelope = json.loads(base64.b64decode(record["payload"]))
            statement = json.loads(base64.b64decode(envelope["payload"]))
        except Exception as exc:
            raise SystemExit(
                f"{attestation_file}: line {lineno} is not a cosign attestation "
                f"record ({exc}); run `cosign download attestation` afresh"
            ) from exc
        blob_parts.append(json.dumps(statement))
    blob = "\n".join(blob_parts)

    missing = [ref for ref in wanted if ref.rpartition("@")[2] not in blob]
    if missing:
        for ref in missing:
            print(
                f"::error::provenance attestation for {dockerfile} does not name "
                f"base digest {ref} -- rebuild with provenance mode=max (#349)",
                file=sys.stderr,
            )
        return 1
    print(
        f"check-image-pins: provenance attestation names all {len(wanted)} base "
        f"digest(s) of {dockerfile}"
    )
    return 0


def main() -> int:
    """The gate itself; tests call this directly (never the CLI wrapper)."""
    return run_gate()


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-digests",
        nargs="+",
        metavar="DOCKERFILE",
        help="print the pinned base refs of the given Dockerfiles",
    )
    parser.add_argument(
        "--verify-attestation",
        metavar="FILE",
        help="verify these cosign-downloaded attestations (with --dockerfile)",
    )
    parser.add_argument(
        "--dockerfile",
        metavar="DOCKERFILE",
        help="Dockerfile whose base digests the attestation must name",
    )
    args = parser.parse_args(argv)

    if args.base_digests:
        for ref in base_digests(args.base_digests):
            print(ref)
        return 0
    if args.verify_attestation:
        if not args.dockerfile:
            parser.error("--verify-attestation requires --dockerfile")
        return verify_attestation(args.verify_attestation, args.dockerfile)
    return main()


if __name__ == "__main__":
    sys.exit(cli())
