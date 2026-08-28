#!/usr/bin/env python3
"""Gate: no secret reaches an image build context, whichever builder runs (#308).

The defect
----------
`Dockerfile.rsi-runner` copies the repository root into an image that then
executes agent-authored code. There was no root `.dockerignore`, and the
`Dockerfile.rsi-runner.dockerignore` beside it did not mention `.env` at all —
so the database password, the LiteLLM gateway key and every provider key in
that file were one `docker build` away from an image a candidate runs inside.

The subtler half is which file applies. `<dockerfile>.dockerignore` is read by
**BuildKit only**; the classic builder ignores it and falls back to the root
`.dockerignore`. Two files that disagree mean the protection depends on
`DOCKER_BUILDKIT`, the daemon version, or whatever tool shelled out to
`docker build` — none of which is a property anyone can check by reading the
Dockerfile.

So this gate asserts three things:

1. Both ignore files exist and carry the **same rules**. Comments may differ;
   rules may not.
2. Those rules deny every pattern in `MUST_DENY` — the secret set. A rule that
   is merely present is not enough: it has to be there in both files, because
   either one may be the one that runs.
3. No rule denies a **tracked** path. `**/data/` is the natural rule to reach
   for and it would silently strip `packages/hive-conductor/backend/data/` and
   the BFCL benchmark corpus out of every image. A build context missing source
   files fails late, confusingly, and in the image rather than here.

Usage
-----
    python3 scripts/check-build-context.py
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_IGNORE = ROOT / ".dockerignore"
RUNNER_IGNORE = ROOT / "Dockerfile.rsi-runner.dockerignore"

#: Dockerfiles whose image ends up executing agent-authored code. A bare
#: `COPY . ` in one of these is the defect this gate is named for: it makes
#: the image's contents a claim about everything that exists rather than
#: about what the build needs.
CANDIDATE_IMAGES: tuple[str, ...] = ("Dockerfile.rsi-runner",)

#: Every one of these must be denied, in BOTH files. Each is something whose
#: presence in an image an operator would consider an incident, not a bug.
MUST_DENY: tuple[tuple[str, str], ...] = (
    (".env", "the database password, gateway key and every provider key"),
    ("**/.env", "the same file anywhere under the context"),
    ("/.git", "every secret ever committed and later removed"),
    ("*.pem", "private keys"),
    ("id_rsa*", "ssh private keys"),
    ("*.age", "age-encrypted vault material (SPEC-011)"),
    ("/secrets/", "anything an operator put somewhere named for what it is"),
    ("/.venv", "host-specific, and tooling caches credentials in it"),
    ("/rsi-reports/", "previous candidates' exported patches and scorecards"),
)

#: `.env.example` ships as documentation and holds no value, so the deny of
#: `.env.*` is re-allowed for it. A gate that demanded it be denied would be
#: demanding the docs be removed.
EXPECTED_NEGATIONS: frozenset[str] = frozenset({"!.env.example", "!**/.env.example"})


def rules(text: str) -> list[str]:
    """The ignore file's rules: every non-comment, non-blank line."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _tracked_paths() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return [line for line in listed.stdout.splitlines() if line]


def denies(rule: str, path: str) -> bool:
    """Whether `rule` excludes `path`, as Docker's matcher would.

    Docker matches relative to the context root, so a bare `vault/` denies the
    top-level directory only — unlike gitignore, where it denies one at any
    depth. The rules are written with a leading `/` where top-level is what is
    meant, so both readings agree and nobody has to know which applies.

    A deliberate approximation, and biased the safe way: it may claim a rule
    matches when Docker's would not, which produces a false failure a human
    reads, rather than the reverse.
    """
    pattern = rule.lstrip("/").rstrip("/")
    if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"{pattern}/*"):
        return True
    # `**/x` matches x at any depth, including the top.
    if pattern.startswith("**/"):
        bare = pattern[3:]
        parts = path.split("/")
        return any(fnmatch.fnmatch(part, bare) for part in parts)
    # A bare directory name denies everything beneath it.
    return path.startswith(f"{pattern}/")


def _divergence(root_rules: list[str], runner_rules: list[str]) -> list[str]:
    """The two files must carry the same rules; comments may differ."""
    if root_rules == runner_rules:
        return []
    only_root = [r for r in root_rules if r not in runner_rules]
    only_runner = [r for r in runner_rules if r not in root_rules]
    return [
        f"  {ROOT_IGNORE.name} and {RUNNER_IGNORE.name} carry different rules — "
        f"BuildKit reads one and the classic builder the other, so the protection "
        f"would depend on which ran.\n"
        f"      only in {ROOT_IGNORE.name}: {only_root or '(none)'}\n"
        f"      only in {RUNNER_IGNORE.name}: {only_runner or '(none)'}"
    ]


def _missing_denials(root_rules: list[str], runner_rules: list[str]) -> list[str]:
    """Every secret pattern, in BOTH files: either one may be the one that runs."""
    failures: list[str] = []
    for pattern, why in MUST_DENY:
        for name, ruleset in ((ROOT_IGNORE.name, root_rules), (RUNNER_IGNORE.name, runner_rules)):
            if pattern not in ruleset:
                failures.append(f"  {name} does not deny {pattern!r} — {why}")
    for negation in sorted(EXPECTED_NEGATIONS):
        if negation not in root_rules:
            failures.append(
                f"  {ROOT_IGNORE.name} lost {negation!r}; `.env.example` is documentation "
                f"with no value in it and belongs in the context"
            )
    return failures


def _over_broad(root_rules: list[str]) -> list[str]:
    """A rule that denies a tracked file empties the image of source."""
    negated = {r.lstrip("!") for r in root_rules if r.startswith("!")}
    tracked = _tracked_paths()
    failures: list[str] = []
    for rule in root_rules:
        if rule.startswith("!"):
            continue
        for path in tracked:
            if denies(rule, path) and not any(denies(n, path) for n in negated):
                failures.append(
                    f"  rule {rule!r} denies the TRACKED file {path!r} — a build "
                    f"context missing source fails late and inside the image"
                )
                break
    return failures


def _bare_copy(dockerfile: Path) -> list[str]:
    """`COPY . ` into an image that runs candidate code."""
    failures: list[str] = []
    for number, raw in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.upper().startswith("COPY "):
            continue
        sources = [t for t in line.split()[1:] if not t.startswith("--")]
        if len(sources) >= 2 and sources[0] in {".", "./"}:
            failures.append(
                f"  {dockerfile.name}:{number}: `{line}` copies the whole context into an "
                f"image that runs agent-authored code — name what the build needs instead, "
                f"so a new top-level directory has to be added deliberately"
            )
    return failures


def _missing_copy_sources(dockerfile: Path) -> list[str]:
    """A COPY naming something that is not there fails the build late.

    Late meaning: after the base image is pulled and the apt layer is built, in
    CI, with the reason buried in a build log — rather than here, in a second.
    """
    failures: list[str] = []
    for number, raw in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.upper().startswith("COPY ") or "--from=" in line:
            continue
        tokens = [t for t in line.split()[1:] if not t.startswith("--")]
        for source in tokens[:-1]:
            if source in {".", "./"} or "*" in source:
                continue
            if not (ROOT / source).exists():
                failures.append(
                    f"  {dockerfile.name}:{number}: COPY source {source!r} does not exist"
                )
    return failures


def audit() -> list[str]:
    """One message per divergence, missing denial, or over-broad rule."""
    missing = [
        f"  {p.name} does not exist" for p in (ROOT_IGNORE, RUNNER_IGNORE) if not p.is_file()
    ]
    if missing:
        return missing

    root_rules = rules(ROOT_IGNORE.read_text(encoding="utf-8"))
    runner_rules = rules(RUNNER_IGNORE.read_text(encoding="utf-8"))

    failures = (
        _divergence(root_rules, runner_rules)
        + _missing_denials(root_rules, runner_rules)
        + _over_broad(root_rules)
    )
    for name in CANDIDATE_IMAGES:
        dockerfile = ROOT / name
        if not dockerfile.is_file():
            failures.append(f"  {name} does not exist")
            continue
        failures += _bare_copy(dockerfile) + _missing_copy_sources(dockerfile)
    return failures


def main() -> int:
    failures = audit()
    if failures:
        print(f"FAIL: {len(failures)} problem(s) with the image build context:\n")
        print("\n".join(failures))
        print(
            "\n`Dockerfile.rsi-runner` copies this context into an image that runs "
            "\nagent-authored code. `.env` reaching it is an incident, not a bug."
        )
        return 1

    print(
        f"ok: both ignore files carry the same {len(rules(ROOT_IGNORE.read_text(encoding='utf-8')))} "
        f"rule(s), deny all {len(MUST_DENY)} secret pattern(s), and exclude nothing tracked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
