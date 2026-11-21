"""Every `.gitleaksignore` fingerprint must stay verifiable against this tree.

A fingerprint gitleaks cannot resolve decays *silently*: the scan re-reports
the finding, nothing points at the edit that rotted the entry, and the next
SAST run is red for a reason no one can connect to the change that caused it.
A malformed line is worse still — gitleaks skips it without failing, so the
entry protects nothing from the moment it is written.

`security.yml` runs two scan arms through this file: the PR/merge-group range
(`BASE..HEAD`) and the history-wide `--all` arm on pushes to the protected
branches, so an entry that only *looks* keyed correctly shows up as a
cross-branch failure later. The contract pinned here:

* a fingerprint line is `<40-hex commit>:<repo-relative path>:<rule>:<line>`;
* when the commit exists in THIS repository, the path must exist in that
  commit's tree (`git cat-file -e <sha>:<path>`) and the blob must have at
  least `<line>` lines — a typo in any component can then never hide;
* commits that do not resolve here are the documented inherited entries
  (the file's own header explains them: pre-snapshot blobs whose SHAs never
  existed in this repository, retained as documentation of the pattern).
  They are grammar-checked only — there is no tree to verify them against.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE_FILE = REPO_ROOT / ".gitleaksignore"

#: <40-hex commit>:<repo-relative path>:<rule id>:<1-based line>
FINGERPRINT = re.compile(
    r"^(?P<sha>[0-9a-f]{40})"
    r":(?P<path>\S+?)"
    r":(?P<rule>[a-z][a-z0-9-]+)"
    r":(?P<line>[1-9][0-9]*)$"
)


def _fingerprints() -> list[tuple[str, str, str, int, int]]:
    """Parse the file into (sha, path, rule, line, source lineno) tuples."""
    entries: list[tuple[str, str, str, int, int]] = []
    for lineno, raw in enumerate(IGNORE_FILE.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = FINGERPRINT.match(line)
        assert match is not None, (
            f"{IGNORE_FILE.relative_to(REPO_ROOT)}:{lineno} is not a "
            f"fingerprint (expected <40-hex-sha>:<path>:<rule>:<line>): {line!r}"
        )
        entries.append(
            (
                match.group("sha"),
                match.group("path"),
                match.group("rule"),
                int(match.group("line")),
                lineno,
            )
        )
    assert entries, "no fingerprints found — the ignore file lost its entries?"
    return entries


def _git(*args: str) -> bool:
    """Run git, returning success (used for pure existence probes)."""
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True).returncode == 0


def test_fingerprints_are_unique() -> None:
    entries = _fingerprints()
    keys = [(sha, path, rule, line) for sha, path, rule, line, _ in entries]
    duplicates = {key for key in keys if keys.count(key) > 1}
    assert not duplicates, (
        "duplicate fingerprints never add suppression coverage and usually "
        f"mean one of the copies was hand-copied wrong: {sorted(duplicates)}"
    )


def test_paths_are_repo_relative() -> None:
    for _sha, path, _rule, _line, lineno in _fingerprints():
        assert not path.startswith(("/", "~")), (
            f"line {lineno}: fingerprint paths must be repo-relative "
            f"(gitleaks reports git-scan paths without a leading slash): {path}"
        )
        assert ".." not in Path(path).parts, (
            f"line {lineno}: fingerprint path escapes the tree: {path}"
        )


def test_resolvable_commits_reference_real_blobs() -> None:
    entries = _fingerprints()
    resolvable = 0
    for sha, path, _rule, line, lineno in entries:
        if not _git("cat-file", "-e", f"{sha}^{{commit}}"):
            # Inherited documentation entry: its commit only exists in the
            # repository this one was snapshotted from. Nothing to verify.
            continue
        resolvable += 1
        assert _git("cat-file", "-e", f"{sha}:{path}"), (
            f"line {lineno}: {path} does not exist in commit {sha[:12]} — "
            "the fingerprint can never match; re-key it to the commit that "
            "now introduces the finding (or delete it if the finding is gone)"
        )
        blob = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{sha}:{path}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert len(blob.splitlines()) >= line, (
            f"line {lineno}: {path} in {sha[:12]} has fewer than {line} "
            "lines — the fingerprint's line component cannot match"
        )
    assert resolvable, (
        "no fingerprint resolved to a commit in this repository; the "
        "verifiable half of the contract checked nothing"
    )


def test_contract_covers_the_current_lane_repair() -> None:
    """The #860 evidence-pack entry must be present and correctly keyed.

    Written against the regression this repair fixed: the round-7 evidence
    pack's idempotency_key re-reports under every `BASE..HEAD` scan that
    contains commit 88edcc7e, and a mis-keyed entry would fail SAST again on
    the next PR that touches the range.
    """
    wanted = (
        "88edcc7ea03baf4257a9edfb47e56a5493d6d329",
        "docs/testing/soak/evidence/m3a-round7-prodstack-quick-probes.json",
        "generic-api-key",
        13,
    )
    keys = [(sha, path, rule, line) for sha, path, rule, line, _ in _fingerprints()]
    assert wanted in keys, (
        "the #860 evidence-pack fingerprint is missing or mis-keyed; "
        f"expected {wanted} in .gitleaksignore"
    )
    assert _git("cat-file", "-e", f"{wanted[0]}:{wanted[1]}"), (
        "the fingerprinted blob vanished from history — re-key the entry "
        "rather than deleting it blind"
    )


@pytest.mark.parametrize(
    ("line", "why"),
    [
        (
            "88edcc7e:docs/x.json:generic-api-key:13",
            "abbreviated commit SHA — gitleaks fingerprints carry 40 hex chars",
        ),
        (
            "88edcc7ea03baf4257a9edfb47e56a5493d6d329:docs/x.json:Generic API Key:13",
            "display name instead of the rule id gitleaks matches on",
        ),
        (
            "88edcc7ea03baf4257a9edfb47e56a5493d6d329:docs/x.json:generic-api-key:0",
            "line numbers are 1-based; 0 can never match",
        ),
        (
            "/abs/docs/x.json:generic-api-key:13",
            "absolute path — missing the commit component entirely",
        ),
    ],
)
def test_parser_rejects_malformed_fingerprints(line: str, why: str) -> None:
    """The grammar must refuse each shape that would decay silently."""
    assert FINGERPRINT.match(line) is None, f"malformed fingerprint accepted ({why}): {line!r}"
