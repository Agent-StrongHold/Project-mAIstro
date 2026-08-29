#!/usr/bin/env python3
"""Every shipped Docker image is built, scanned, and accounted for (#346).

Trivy and Grype covered two images. The repository has nine Dockerfiles, and
the one its own header calls "the single largest remaining CVE source" --
`Dockerfile.research` -- was not among the two. Nothing said so, because
nothing enumerated them: coverage was whatever `security.yml` happened to
name, and an image added tomorrow would inherit that silence.

This gate makes the set closed. `quality/image-inventory.json` names every
Dockerfile with a disposition and an owner, and this script holds the
inventory and the tree to each other in both directions:

- a Dockerfile on disk with no entry fails, so a new image cannot arrive
  unnoticed;
- an entry naming a Dockerfile that is gone fails, so the inventory cannot
  rot into a list of things that used to exist;
- a PUBLISHED or DISTRIBUTED entry must name `built_by` and `scanned_by`
  jobs, and every one of them must exist in the workflow it names.

That last check is the one that makes the inventory more than a document.
"Add the image to the list" is cheap and would let coverage claims drift from
coverage; "add the image to the list *and* the jobs that build and scan it,
or CI fails" is the property #346 asks for.

The dispositions are deliberately four rather than a shipped/not-shipped
boolean, because the images differ in what can honestly be demanded of them:

- PUBLISHED  pushed to a registry by release.yml. Built, scanned, SBOM'd and
             signed; the release consumes the tested digest.
- DISTRIBUTED built from this repository by an operator or a shipped script,
             never pushed. Built and scanned in CI -- but there is no
             published digest to sign, so demanding a signature would be
             demanding a fiction.
- INTERNAL   built only by this repository's own CI or test tooling and never
             run outside it. Must justify itself in prose, because "it's just
             a test image" is the excuse that would otherwise absorb
             everything.
- RETIRED    superseded. Names `replaced_by` and the issue that owns removal.
             A RETIRED entry is a decision, not permission to delete.

Run: `python scripts/check-image-inventory.py`
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "quality" / "image-inventory.json"
WORKFLOWS = ROOT / ".github" / "workflows"

# Directories that are not this repository's source.
_SKIP = ("/.git/", "/node_modules/", "/.venv/", "/site-packages/")

NEEDS_JOBS = ("PUBLISHED", "DISTRIBUTED")
DISPOSITIONS = ("PUBLISHED", "DISTRIBUTED", "INTERNAL", "RETIRED")


def dockerfiles_on_disk() -> set[str]:
    """Every Dockerfile in the tree, repo-relative.

    `Dockerfile*` rather than exactly `Dockerfile`: the variants are where the
    uncovered images were (`Dockerfile.research`, `Dockerfile.rsi-runner`), so
    a matcher that missed them would reproduce the gap it exists to close.
    `.dockerignore` files are excluded -- they configure a build, they are not
    one.
    """
    found: set[str] = set()
    for path in ROOT.rglob("Dockerfile*"):
        if not path.is_file():
            continue
        text = str(path)
        if any(part in text for part in _SKIP):
            continue
        if path.name.endswith(".dockerignore"):
            continue
        found.add(str(path.relative_to(ROOT)))
    return found


def jobs_in(workflow: Path) -> set[str]:
    """Job ids declared in one workflow file.

    Parsed with a line anchor rather than a YAML load so this gate has no
    dependency of its own: it runs in the same job as the other checks, and a
    gate that cannot run because its parser is missing is a gate that gets
    removed. A job id is a key at exactly two spaces of indent under `jobs:`.
    """
    if not workflow.exists():
        return set()
    jobs: set[str] = set()
    in_jobs = False
    for line in workflow.read_text(encoding="utf-8").splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if in_jobs:
            if line and not line[0].isspace():
                in_jobs = False
                continue
            found = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if found:
                jobs.add(found.group(1))
    return jobs


def check_job_ref(ref: str, failures: list[str], where: str) -> None:
    """`path/to/workflow.yml:job-id` must name a job that exists."""
    if ":" not in ref:
        failures.append(f"{where}: {ref!r} is not `<workflow path>:<job id>`")
        return
    rel, job = ref.rsplit(":", 1)
    workflow = ROOT / rel
    if not workflow.exists():
        failures.append(f"{where}: {rel} does not exist")
        return
    if job not in jobs_in(workflow):
        failures.append(f"{where}: {rel} declares no job {job!r}")


def check_shipped(entry: dict[str, object], ident: str, failures: list[str]) -> None:
    """A PUBLISHED or DISTRIBUTED image names the jobs that build and scan it."""
    disposition = str(entry.get("disposition", ""))
    built = entry.get("built_by") or []
    scanned = entry.get("scanned_by") or []
    if not built:
        failures.append(f"{ident}: {disposition} but no `built_by` job")
    if not scanned:
        failures.append(f"{ident}: {disposition} but no `scanned_by` job")
    for ref in [*built, *scanned]:  # type: ignore[misc]
        check_job_ref(str(ref), failures, ident)
    if disposition != "PUBLISHED":
        return
    published = entry.get("published_by")
    if not published:
        failures.append(f"{ident}: PUBLISHED but no `published_by` job")
    else:
        check_job_ref(str(published), failures, ident)


def check_unshipped(entry: dict[str, object], ident: str, failures: list[str]) -> None:
    """An INTERNAL or RETIRED image claims no build or scan, and RETIRED owns itself."""
    disposition = str(entry.get("disposition", ""))
    for field in ("built_by", "scanned_by"):
        if entry.get(field):
            failures.append(
                f"{ident}: {disposition} entries name no {field}; "
                "a scanned image is DISTRIBUTED or PUBLISHED, not INTERNAL or RETIRED"
            )
    if disposition != "RETIRED":
        return
    for field in ("replaced_by", "removal_owner"):
        if not str(entry.get(field, "")).strip():
            failures.append(
                f"{ident}: RETIRED needs `{field}`. A retirement with no successor "
                "and no owner is a shrug, not a decision"
            )


def check_entry(entry: dict[str, object], failures: list[str]) -> str | None:
    """One entry's own rules. Returns the Dockerfile it claims, or None."""
    dockerfile = str(entry.get("dockerfile", ""))
    ident = str(entry.get("id", dockerfile or "<no id>"))
    if not dockerfile:
        failures.append(f"{ident}: no `dockerfile`")
        return None

    disposition = str(entry.get("disposition", ""))
    if disposition not in DISPOSITIONS:
        failures.append(
            f"{ident}: disposition {disposition!r} is not one of {', '.join(DISPOSITIONS)}"
        )
        return dockerfile

    if not str(entry.get("rationale", "")).strip():
        failures.append(f"{ident}: no rationale. Every disposition is a claim someone must own")

    if disposition in NEEDS_JOBS:
        check_shipped(entry, ident, failures)
    else:
        check_unshipped(entry, ident, failures)
    return dockerfile


def collect(entries: list[dict[str, object]], failures: list[str]) -> dict[str, dict[str, object]]:
    """Validate each entry and index the valid ones by the Dockerfile they claim."""
    listed: dict[str, dict[str, object]] = {}
    for entry in entries:
        dockerfile = check_entry(entry, failures)
        if dockerfile is None:
            continue
        if dockerfile in listed:
            failures.append(f"{dockerfile}: listed twice")
            continue
        listed[dockerfile] = entry
    return listed


def report(on_disk: set[str], listed: dict[str, dict[str, object]]) -> None:
    """Print the disposition census, pass or fail.

    Printed even on success: the point of the inventory is that the numbers
    are visible, and a gate that only speaks when it is angry lets a shipped
    image quietly become an INTERNAL one.
    """
    counts: dict[str, int] = {}
    for entry in listed.values():
        key = str(entry.get("disposition", "?"))
        counts[key] = counts.get(key, 0) + 1
    print(f"image inventory: {len(on_disk)} Dockerfile(s)")
    for key in DISPOSITIONS:
        print(f"  {key:<12}: {counts.get(key, 0)}")


def main() -> int:
    if not INVENTORY.exists():
        print(f"FAIL: {INVENTORY.relative_to(ROOT)} is missing")
        return 1

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    failures: list[str] = []

    listed = collect(inventory.get("images", []), failures)

    on_disk = dockerfiles_on_disk()
    for missing in sorted(on_disk - set(listed)):
        failures.append(
            f"{missing}: on disk, not in the inventory. Add it with a disposition — "
            "and, if it ships, the jobs that build and scan it"
        )
    for gone in sorted(set(listed) - on_disk):
        failures.append(f"{gone}: in the inventory, not on disk. Prune the entry")

    report(on_disk, listed)

    if failures:
        print("\nFAIL: the image inventory does not match the repository\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nEvery Dockerfile carries one disposition and one owner. A shipped image "
            "must name the jobs that build and scan it, and those jobs must exist —\n"
            "adding an image to the list without them is how coverage claims drift "
            "from coverage."
        )
        return 1

    print("\nOK: every Dockerfile is inventoried, and every shipped image names live jobs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
