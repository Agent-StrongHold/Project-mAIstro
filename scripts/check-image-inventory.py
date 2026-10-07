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
  jobs, and every one of them must exist in the workflow it names;
- a PUBLISHED entry that claims `published_digest_verified: true` must be
  wired so the claim is true: the publishing job must build once into a
  quarantine, scan the built digest with Trivy or Grype, apply the release
  tags to that same digest only after the scans, and cosign-sign that same
  digest (#611).

That last check is the one that makes the inventory more than a document.
"Add the image to the list" is cheap and would let coverage claims drift from
coverage; "add the image to the list *and* the jobs that build and scan it,
or CI fails" is the property #346 asks for.

The dispositions are deliberately four rather than a shipped/not-shipped
boolean, because the images differ in what can honestly be demanded of them:

- PUBLISHED  pushed to a registry by release.yml. Built once, scanned on
             the release path, SBOM'd and signed; the release tags are
             applied to the scanned digest, so the published artifact is
             exactly the artifact that was scanned (#611).
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

# The publish-wiring vocabulary (#611). A PUBLISHED entry may only claim
# `published_digest_verified: true` when the publishing job's steps show this
# shape: a build-push step that exports a digest, a blocking Trivy/Grype scan
# consuming that digest, a tag-application step consuming it after the scans,
# and a cosign step consuming it. Steps are read as text, not through a YAML
# load, for the same reason the job parser below avoids one.
BUILD_ACTION = "docker/build-push-action"

# A scan only gates when it is wired to fail: `trivy-action` with
# `exit-code: "1"`, or a `run:` line that invokes trivy/grype with
# `--exit-code 1` / `--fail-on <severity>` -- security.yml's policy. Merely
# naming a scanner (a `Report Trivy target` step echoing the digest) or
# configuring it not to fail (`exit-code: "0"`, no `--fail-on`,
# `continue-on-error: true`) is reporting, and admits anything.
SCAN_FAIL_FLAGS = re.compile(r"--exit-code[=\s]+[\"']?1(?!\d)|--fail-on\s+\S+", re.IGNORECASE)
TRIVY_ACTION = re.compile(r"^\s*uses:\s*aquasecurity/trivy-action\b", re.MULTILINE)
FAILING_EXIT_CODE = re.compile(r"^\s*exit-code:\s*[\"']?1[\"']?\s*(?:#.*)?$", re.MULTILINE)
RUN_PREFIX = re.compile(r"^run:\s*>?-?\s*")
SCANNER_COMMAND = re.compile(r"^(?:sudo\s+)?(?:trivy|grype)(?:\s|$)", re.IGNORECASE)


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


def _job_bounds(lines: list[str], job: str) -> tuple[int, int]:
    """Half-open line range of one job's block, or `(0, 0)` if absent."""
    job_re = re.compile(rf"^  {re.escape(job)}:\s*(?:#.*)?$")
    start = next((i + 1 for i, line in enumerate(lines) if job_re.match(line)), None)
    if start is None:
        return 0, 0
    for j in range(start, len(lines)):
        if lines[j] and not lines[j][0].isspace():
            return start, j
    return start, len(lines)


def steps_of_job(workflow: Path, job: str) -> list[tuple[int, str]]:
    """One job's step blocks as `(first line number, text)` chunks.

    Same line-anchor reasoning as `jobs_in`: no YAML dependency. A step is a
    `- ` item at exactly six spaces of indent inside the job's `steps:` block;
    everything up to the next step (or the end of the job) belongs to it. Line
    numbers are 1-indexed, so the ordering checks below read like the file.
    """
    lines = workflow.read_text(encoding="utf-8").splitlines()
    start, end = _job_bounds(lines, job)
    steps: list[tuple[int, str]] = []
    current: list[str] | None = None
    current_start = 0
    in_steps = False
    for i in range(start, end):
        line = lines[i]
        if not in_steps:
            if not re.match(r"^    steps:\s*$", line):
                continue
            in_steps = True
            continue
        if re.match(r"^      -(?:\s|$)", line):
            if current is not None:
                steps.append((current_start, "\n".join(current)))
            current = [line]
            current_start = i + 1
        elif current is not None:
            current.append(line)
    if current is not None:
        steps.append((current_start, "\n".join(current)))
    return steps


def _is_blocking_scan(step: str) -> bool:
    """A scanner invocation carrying the repository's blocking policy.

    The scanner vocabulary alone proves nothing: a step named `Report Trivy
    target` that only echoes the digest mentions trivy and gates nothing, and
    an invocation told not to fail (`exit-code: "0"`, no `--fail-on`,
    `continue-on-error: true`) scans and admits whatever it finds. The scan a
    `published_digest_verified: true` claim rests on must be trivy-action
    with `exit-code: "1"`, or a `run:` line invoking trivy/grype with the
    failing flag, and must not be permitted to fail.
    """
    if re.search(r"continue-on-error:\s*[\"']?true", step, re.IGNORECASE):
        return False
    if TRIVY_ACTION.search(step):
        return FAILING_EXIT_CODE.search(step) is not None
    invokes_scanner = any(
        SCANNER_COMMAND.match(RUN_PREFIX.sub("", line.strip())) for line in step.splitlines()
    )
    return invokes_scanner and SCAN_FAIL_FLAGS.search(step) is not None


def check_publish_wiring(workflow: Path, job: str, ident: str, failures: list[str]) -> None:
    """`published_digest_verified: true` must describe real wiring (#611).

    Reading job names cannot tell the release publishes the scanned digest —
    that gap is why #611 exists — so this reads the shape of the publishing
    job itself. For every `docker/build-push-action` step that pushes, the job
    must also contain, bound to that step's digest output:

    - a blocking Trivy or Grype scan consuming the digest — the scan that
      admits it (see `_is_blocking_scan`);
    - an `imagetools create` step consuming it — release tags applied to the
      scanned digest, never rebuilt — and positioned AFTER the scans, so a
      finding at the gating severity fails before any release tag exists;
    - a `cosign sign` step consuming it — the signature attests the published
      artifact, not a lookalike.

    And the build itself must not apply release tags: a step that pushed
    `:latest` (or the computed release tags) at build time would publish the
    digest before the scan had a chance to reject it.
    """
    rel = str(workflow.relative_to(ROOT))
    steps = steps_of_job(workflow, job)
    if not steps:
        failures.append(
            f"{ident}: {rel} declares no steps for job {job!r}; there is no publish wiring to read"
        )
        return

    builds = _pushed_build_steps(steps, ident, rel, job, failures)
    scans = [(n, c) for n, c in steps if _is_blocking_scan(c)]
    promotes = [(n, c) for n, c in steps if "imagetools create" in c]
    signs = [(n, c) for n, c in steps if re.search(r"\bcosign sign\b", c)]

    for _, build_id in builds:
        digest = f"steps.{build_id}.outputs.digest"
        if not any(digest in chunk for _, chunk in scans):
            failures.append(
                f"{ident}: {rel} job {job!r} never scans `{digest}` with trivy or grype "
                "wired to fail (exit-code 1 / --fail-on); a claim that the published "
                "digest was scanned has nothing behind it"
            )
        if not any(digest in chunk for _, chunk in promotes):
            failures.append(
                f"{ident}: {rel} job {job!r} never applies the release tags to `{digest}` "
                "via `imagetools create`; the tags would resolve to a different build"
            )
        if not any(digest in chunk for _, chunk in signs):
            failures.append(
                f"{ident}: {rel} job {job!r} has no `cosign sign` of `{digest}`; "
                "the signature would attest an artifact the release does not publish"
            )

    last_scan = max((n for n, _ in scans), default=0)
    first_promote = min((n for n, _ in promotes), default=len(steps) + 1)
    first_sign = min((n for n, _ in signs), default=len(steps) + 1)
    if scans and first_promote < last_scan:
        failures.append(
            f"{ident}: {rel} job {job!r} applies release tags before its scans; "
            "a finding at the gating severity must stop the publish, not correct it"
        )
    if scans and first_sign < last_scan:
        failures.append(
            f"{ident}: {rel} job {job!r} signs before its scans; "
            "a signature must not exist for an artifact the scan may still reject"
        )

    for lineno, _build_id in builds:
        chunk = next(c for n, c in steps if n == lineno)
        _build_must_not_publish(chunk, ident, rel, job, failures)


def _pushed_build_steps(
    steps: list[tuple[int, str]], ident: str, rel: str, job: str, failures: list[str]
) -> list[tuple[int, str]]:
    """The `(line, id)` of every `docker/build-push-action` step that pushes.

    A push with no `id:` exports no digest any scan, tag or signature could
    bind to, so it fails rather than silently dropping out of the check.
    """
    builds: list[tuple[int, str]] = []
    for lineno, chunk in steps:
        if BUILD_ACTION not in chunk or "uses:" not in chunk:
            continue
        if not re.search(r"^\s+push:\s*true\s*$", chunk, re.MULTILINE):
            continue
        found = re.search(r"^\s+id:\s*([A-Za-z0-9_-]+)", chunk, re.MULTILINE)
        if not found:
            failures.append(
                f"{ident}: {rel} job {job!r} pushes with {BUILD_ACTION} but the step "
                "declares no `id:`, so no scan, tag or signature can bind to its digest"
            )
            continue
        builds.append((lineno, found.group(1)))
    if not builds:
        failures.append(
            f"{ident}: {rel} job {job!r} pushes no {BUILD_ACTION} step; "
            "there is no build whose digest the release could publish"
        )
    return builds


def _build_must_not_publish(
    chunk: str, ident: str, rel: str, job: str, failures: list[str]
) -> None:
    """The build pushes to the quarantine only; the promote step publishes.

    A build step that named a mutable release tag — or consumed the computed
    release tags — would publish the digest before any scan had the chance to
    reject it, which is exactly what #611's AC-2 forbids.
    """
    if ":latest" in chunk:
        failures.append(
            f"{ident}: {rel} job {job!r} build step pushes `:latest` at build time; "
            "release tags are applied after the scan, by the promote step"
        )
    for line in chunk.splitlines():
        if re.match(r"^\s+(?:-\s+)?tags:\s*.*\bsteps\.", line):
            failures.append(
                f"{ident}: {rel} job {job!r} build step consumes computed release tags; "
                "the build must push to a quarantine, and the promote step applies "
                "the release tags to the scanned digest"
            )


def check_exception(entry: dict[str, object], ident: str, failures: list[str]) -> bool:
    """A shipped image may lack jobs only behind an owned, issue-scoped exception.

    #346's AC-4 asks for exceptions that are "version-scoped, owned, expiring".
    Owned and issue-scoped are what this can check from here; an exception with
    no owner and no issue is not an exception, it is an exemption, and it would
    let the cheapest thing to write -- nothing -- silently satisfy the gate.
    """
    raw = entry.get("coverage_exception")
    if not isinstance(raw, dict):
        return False
    for field in ("owner", "issue", "reason"):
        if not str(raw.get(field, "")).strip():
            failures.append(
                f"{ident}: `coverage_exception` needs `{field}`. "
                "An exception nobody owns is an exemption"
            )
    return True


def check_shipped(entry: dict[str, object], ident: str, failures: list[str]) -> None:
    """A PUBLISHED or DISTRIBUTED image names the jobs that build and scan it."""
    disposition = str(entry.get("disposition", ""))
    built = entry.get("built_by") or []
    scanned = entry.get("scanned_by") or []
    excepted = check_exception(entry, ident, failures)
    if not built and not excepted:
        failures.append(f"{ident}: {disposition} but no `built_by` job and no `coverage_exception`")
    if not scanned and not excepted:
        failures.append(
            f"{ident}: {disposition} but no `scanned_by` job and no `coverage_exception`"
        )
    for ref in [*built, *scanned]:  # type: ignore[misc]
        check_job_ref(str(ref), failures, ident)
    if disposition != "PUBLISHED":
        return
    published = entry.get("published_by")
    if not published:
        failures.append(f"{ident}: PUBLISHED but no `published_by` job")
    else:
        check_job_ref(str(published), failures, ident)
    # The flag is the claim; the wiring check is the proof. `false` is the
    # honest state of a release path whose scans and publish are not yet the
    # same digest (#346 AC-5, #593). `true` means the publishing job builds
    # once, scans the built digest, applies the release tags to that digest
    # after the scans and signs it — and `check_publish_wiring` holds the
    # workflow to every one of those clauses, so flipping the flag to `true`
    # without re-wiring the release fails here (#611).
    if "published_digest_verified" not in entry:
        failures.append(
            f"{ident}: PUBLISHED must state `published_digest_verified`. "
            "Whether the release publishes the digest that was scanned is the "
            "one thing this gate cannot infer from job names"
        )
    elif entry["published_digest_verified"] is True:
        if not isinstance(published, str) or ":" not in published:
            failures.append(
                f"{ident}: `published_digest_verified: true` needs a usable "
                "`published_by` `<workflow>:<job>` to read the wiring from"
            )
        else:
            rel, job = published.rsplit(":", 1)
            check_publish_wiring(ROOT / rel, job, ident, failures)
    elif entry["published_digest_verified"] is not False:
        failures.append(
            f"{ident}: `published_digest_verified` must be JSON true or false, "
            f"got {entry['published_digest_verified']!r}"
        )


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
            "from coverage. A PUBLISHED entry claiming `published_digest_verified: "
            "true`\nmust also show the wiring: build once, scan the built digest, "
            "apply the release tags\nto it after the scans, and sign it."
        )
        return 1

    print("\nOK: every Dockerfile is inventoried, and every shipped image names live jobs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
