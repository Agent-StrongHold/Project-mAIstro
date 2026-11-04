#!/usr/bin/env python3
"""Gate the JavaScript supply chain against reviewed vulnerability and policy state.

Single source of truth for the JS dependency audit (#344), the role
``scripts/pip_audit_gate.py`` plays for Python: the workflow runs the
scanners (``npm audit`` and GuardDog), this script reads their reports and
owns the verdict, so two jobs can never disagree about whether an advisory
is triaged.

What it checks, per tracked surface (a directory with ``package.json`` and a
lockfile):

* **Inventory, fail-closed.** Every ``package.json`` outside ignored trees
  must be a registered surface below; every registered surface must have its
  lockfile. A new workspace or lockfile without coverage fails CI (#344's
  definition of done).
* **Lock drift.** The lockfile's root entry must restate exactly what
  ``package.json`` declares (name -> specifier, per dependency kind). npm
  itself refuses ``npm ci`` on drift; this catches it before the build.
* **Provenance/integrity.** Every resolved lockfile entry must carry a
  sha512 ``integrity`` and an ``https://`` registry URL. http/git/file
  sources and integrity-less entries are findings.
* **License.** Every license the lockfile declares must be on the approved
  list (permissive, font, or documentation licenses) or carry an owned,
  expiring exception. npm omits the field for entries whose cached packument
  lacked it; those are counted and reported, not failed — the policy's teeth
  are against a copyleft or UNLICENSED value arriving in a resolved tree.
* **Malicious package, deterministic half.** Typosquat detection (edit
  distance 1 to a popular-package corpus for names of 5+ characters, 2 for
  9+; hyphen/underscore-insensitive; scoped packages exempt — the scope is
  the defense) and an install-script review list: a package whose lockfile
  entry sets ``hasInstallScript`` must be on the reviewed, expiring list.
* **Vulnerability (report).** Every ``npm audit`` finding, at any severity,
  must carry an owned, expiring, package/advisory/version-specific exception.
* **Malicious package, scanner half (report).** GuardDog findings on
  ``threat-*`` and metadata rules (typosquatting, deceptive author,
  compromised maintainer domain, ...) are findings; ``capability-*`` rules
  are reported informationally — every package that opens a socket or spawns
  a process trips them (measured: ``express`` trips
  ``capability-network-outbound``), so failing on them would be a verdict
  about npm itself, not about this tree.

Exceptions are owned, expiring, and package/version specific: each records
the versions the triage actually reviewed, and the same advisory on a
different version fails until someone re-reads it.

Exit codes: 0 = pass; 1 = real finding (unclassified surface, missing
lockfile, drift, policy violation, or scanner finding outside the
exceptions); 2 = usage error; 3 = a scanner report is missing or unparseable
— an infrastructure failure to retry, not a verdict.

Usage (security.yml ``js-supply-chain``):

    (cd <surface> && npm audit --package-lock-only --json > audit.json) || true
    guarddog npm scan <direct-dep> --no-sandbox --output-format json  # merged per surface
    python scripts/js_dependency_gate.py \\
        --audit-report packages/hive-conductor/frontend=audit.json \\
        --guarddog-report packages/hive-conductor/frontend=guarddog.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Directories whose package.json/lockfiles are someone else's install tree
#: or generated output, never a dependency surface this repo ships.
_IGNORED_PARTS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "coverage",
        ".maistro-install",
        "potential-dead-code",
    }
)

_LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")


@dataclass(frozen=True)
class Surface:
    """One tracked JavaScript dependency surface (#344's inventory)."""

    directory: str
    #: Shipped in an image / product vs test tooling. The classification is
    #: the review decision: a new surface fails until it is added here with
    #: an honest answer.
    shipped: bool
    description: str


#: The inventory. Adding a workspace or lockfile without an entry here fails
#: the gate — that is the acceptance criterion, not an inconvenience.
SURFACES: dict[str, Surface] = {
    "packages/hive-conductor/frontend": Surface(
        directory="packages/hive-conductor/frontend",
        shipped=True,
        description="Conductor SPA, built into the hive-conductor image",
    ),
    "packages/maistro-canvas/frontend": Surface(
        directory="packages/maistro-canvas/frontend",
        shipped=True,
        description="Canvas deck-builder frontend, built in CI and shipped with the canvas package",
    ),
    "packages/hive-conductor/tests/e2e": Surface(
        directory="packages/hive-conductor/tests/e2e",
        shipped=False,
        description="Playwright end-to-end tooling; never shipped, still inventoried and audited",
    ),
}


@dataclass(frozen=True)
class Exception:
    """An owned, expiring, package/version-specific exception.

    ``expires`` is an ISO date; the gate fails once it passes, so every
    exception is re-read on a cadence instead of accreting forever.
    ``versions`` are the installed versions the triage reviewed: the same
    advisory or rule on a different version is a NEW finding.
    """

    reason: str
    expires: str
    versions: tuple[str, ...] = ()


def _not_expired(exception: Exception) -> bool:
    return date.today().isoformat() <= exception.expires


#: (package, advisory id) -> why it is accepted. Keyed by the PAIR, never the
#: package: exempting a package would silently pass every future advisory on
#: it. Advisory ids are the GHSA/npm id extracted from the audit report's
#: advisory URL.
VULNERABILITY_EXCEPTIONS: dict[tuple[str, str], Exception] = {
    ("minimatch", "GHSA-g3hv-75wg-m249"): Exception(
        reason=(
            "Moderate ReDoS-class advisory on minimatch, reached only through "
            "the dev-only eslint toolchain (eslint -> @eslint/config-array -> "
            "minimatch; typescript-eslint and openapi-typescript carry the same "
            "chain). No in-range fix exists: every fix npm proposes is a SemVer "
            "major of the toolchain (typescript-eslint 8.14.0, @eslint/js "
            "9.39.5, openapi-typescript 6.7.6), which is exactly the reviewed "
            "update PR the new Dependabot npm configuration raises. Dev "
            "dependencies never ship in an image; the lint toolchain parsing "
            "untrusted repo files is the exposure, accepted until the major "
            "bumps land. Re-triage on expiry."
        ),
        expires="2027-02-04",
        versions=("3.1.5", "5.1.9", "10.2.5"),
    ),
}

#: (package, guarddog rule) -> why it is accepted. Every entry below is a
#: measured false-positive shape on a first-party toolchain package, triaged
#: against the locked version recorded in ``versions``; the same rule on a
#: new version re-fails until re-read.
GUARDDOG_EXCEPTIONS: dict[tuple[str, str], Exception] = {
    ("@types/react", "threat-npm-http-dependency"): Exception(
        reason=(
            "The DefinitelyTyped stub's package.json carries the types "
            "repository URL (a documentation link in the publisher's "
            "template), which the http-dependency heuristic reads as an "
            "installable source. No dependency is fetched from it."
        ),
        expires="2027-11-04",
        versions=("19.2.14",),
    ),
    ("@types/react-dom", "threat-npm-http-dependency"): Exception(
        reason=(
            "Same DefinitelyTyped publisher template as @types/react: the "
            "URL is the types repository, not a fetched dependency."
        ),
        expires="2027-11-04",
        versions=("19.2.3",),
    ),
    ("react-dom", "metadata_mismatch"): Exception(
        reason=(
            "The React team's publish pipeline rewrites the tarball's "
            "package.json (scripts trimmed for the published artifact); the "
            "registry manifest and the tarball therefore disagree by "
            "construction. Verified against the react-dom publish process, "
            "not a tampering signal on its own."
        ),
        expires="2027-11-04",
        versions=("19.2.0", "19.2.5", "19.2.6"),
    ),
    ("pg", "metadata_mismatch"): Exception(
        reason=(
            "node-pg's publish pipeline rewrites the pg-cloudflare optional "
            "dependency range between manifest and tarball. First-party "
            "maintainer artifact, not a tampering signal."
        ),
        expires="2027-11-04",
        versions=("8.20.0",),
    ),
    ("esbuild", "threat-process-hooks"): Exception(
        reason=(
            "esbuild's install hook invoking its own binary is the same "
            "reviewed behavior as its INSTALL_SCRIPT_EXCEPTIONS entry, seen "
            "from the LOLBAS heuristic's side."
        ),
        expires="2027-11-04",
        versions=("0.28.1",),
    ),
    ("eslint", "threat-filesystem-read"): Exception(
        reason=(
            "A linter's job is reading the source tree it lints; the "
            "sensitive-file heuristic fires on config/source traversal. "
            "Dev-only tool, never shipped."
        ),
        expires="2027-11-04",
        versions=("9.39.4",),
    ),
    ("vitest", "threat-filesystem-read"): Exception(
        reason=(
            "A test runner's job is reading the source tree it tests; the "
            "sensitive-file heuristic fires on test-file traversal. Dev-only "
            "dependency, never shipped."
        ),
        expires="2027-11-04",
        versions=("5.0.5",),
    ),
    ("vite", "threat-filesystem-read"): Exception(
        reason=(
            "The bundler reads the module graph it bundles; the "
            "sensitive-file heuristic fires on config/module traversal. "
            "Dev-only build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7", "8.3.4"),
    ),
    ("vite", "threat-runtime-enumeration"): Exception(
        reason=(
            "Vite probes platform/architecture to pick build paths — the "
            "enumeration heuristic reads that as reconnaissance. Dev-only "
            "build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7", "8.3.4"),
    ),
    ("vite", "threat-runtime-environment-read"): Exception(
        reason=(
            "Vite reads environment (platform, arch, NODE_ENV) for build "
            "decisions. Dev-only build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7", "8.3.4"),
    ),
    ("vite", "threat-runtime-obfuscation-base64exec"): Exception(
        reason=(
            "Vite decodes base64 sourcemap/license payloads while "
            "transforming modules; the decode-then-eval heuristic fires on "
            "the transform pipeline. Dev-only build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7", "8.3.4"),
    ),
    ("vite", "threat-runtime-obfuscation-steganography"): Exception(
        reason=(
            "Same transform-pipeline decode as the base64 rule; the "
            "steganography heuristic fires on the same code path. Dev-only "
            "build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7", "8.3.4"),
    ),
    ("vite", "threat-runtime-obfuscation-unicode"): Exception(
        reason=(
            "Vite's minified dist contains unicode escapes the obfuscation "
            "heuristic flags. Dev-only build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7",),
    ),
    ("vite", "threat-runtime-system-info"): Exception(
        reason=(
            "Vite collects hostname/platform/architecture for build "
            "targeting and debugging output. Dev-only build tool."
        ),
        expires="2027-11-04",
        versions=("7.3.7", "8.3.4"),
    ),
    ("vite", "risky_new_dependency"): Exception(
        reason=(
            "The rule flags young dependencies in vite@7's optional chain "
            "(rolldown/oxc artifacts); vite is the pinned build tool and "
            "the flagged deps are its own first-party rollout. Dev-only."
        ),
        expires="2027-11-04",
        versions=("7.3.7",),
    ),
}

#: (package, license) -> why a non-approved license is accepted.
LICENSE_EXCEPTIONS: dict[tuple[str, str], Exception] = {}

#: (package,) -> why its install script is accepted. Install scripts run
#: arbitrary code at ``npm ci`` time; each one is reviewed and expires.
INSTALL_SCRIPT_EXCEPTIONS: dict[str, Exception] = {
    "esbuild": Exception(
        reason=(
            "esbuild's postinstall downloads or verifies the platform binary "
            "when the optionalDependencies platform package did not match; "
            "the binary is the package's entire purpose."
        ),
        expires="2027-11-04",
        versions=("0.28.1",),
    ),
    "fsevents": Exception(
        reason=(
            "macOS file-watching native module; its install script builds or "
            "fetches the optional binding. Dev-only (vite/chokidar chain), "
            "never installed on the linux images this repo ships."
        ),
        expires="2027-11-04",
        versions=("2.3.2", "2.3.3"),
    ),
}

#: Permissive and documentation licenses a resolved tree may carry. Anything
#: else — copyleft, UNLICENSED, "SEE LICENSE IN ..." — is a finding until an
#: owned exception says otherwise.
APPROVED_LICENSES = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "ISC",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "0BSD",
        "BlueOak-1.0.0",
        "Python-2.0",
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "Unlicense",
        "Zlib",
        "OFL-1.1",
        "(MIT OR CC0-1.0)",
        "(MIT OR Apache-2.0)",
        "(BSD-2-Clause OR MIT OR Apache-2.0)",
    }
)

#: The most-impersonated npm package names, hyphen/underscore-insensitive.
#: A dependency within edit distance 1 of one of these (2 for names of 9+
#: characters) that is not itself on this list is the classic typosquat
#: shape. Legitimate near-misses (``source-map-js`` vs ``source-map``) are
#: corpus members, not exceptions: they are popular too.
TYPOSQUAT_CORPUS = frozenset(
    {
        "react",
        "reactdom",
        "reactnative",
        "vue",
        "angular",
        "svelte",
        "next",
        "gatsby",
        "express",
        "koa",
        "fastify",
        "hapi",
        "socketio",
        "axios",
        "request",
        "superagent",
        "nodefetch",
        "got",
        "lodash",
        "underscore",
        "jquery",
        "moment",
        "dayjs",
        "datefns",
        "luxon",
        "rxjs",
        "chalk",
        "colors",
        "ansicolors",
        "kleur",
        "picocolors",
        "ora",
        "commander",
        "yargs",
        "minimist",
        "inquirer",
        "prompts",
        "enquirer",
        "meow",
        "webpack",
        "rollup",
        "parcel",
        "esbuild",
        "vite",
        "swc",
        "babelcore",
        "typescript",
        "tsnode",
        "tslib",
        "eslint",
        "prettier",
        "jshint",
        "stylelint",
        "jest",
        "mocha",
        "chai",
        "ava",
        "vitest",
        "karma",
        "jasmine",
        "cypress",
        "playwright",
        "gulp",
        "grunt",
        "browserify",
        "npm",
        "yarn",
        "pnpm",
        "npx",
        "fsextra",
        "glob",
        "minimatch",
        "mkdirp",
        "rimraf",
        "del",
        "dotenv",
        "config",
        "json5",
        "jsonfile",
        "writefileatomic",
        "mongoose",
        "mongodb",
        "redis",
        "mysql",
        "mysql2",
        "pg",
        "sequelize",
        "knex",
        "typeorm",
        "prisma",
        "passport",
        "jsonwebtoken",
        "bcrypt",
        "bcryptjs",
        "uuid",
        "nanoid",
        "shortid",
        "cuid",
        "bodyparser",
        "cookieparser",
        "cors",
        "helmet",
        "compression",
        "servestatic",
        "morgan",
        "winston",
        "pino",
        "debug",
        "crossenv",
        "npmrunall",
        "concurrently",
        "nodemon",
        "pm2",
        "postcss",
        "sass",
        "nodesass",
        "less",
        "stylus",
        "tailwindcss",
        "autoprefixer",
        "corejs",
        "regeneratorruntime",
        "async",
        "bluebird",
        "pmap",
        "plimit",
        "cheerio",
        "jsdom",
        "puppeteer",
        "electron",
        "nodegyp",
        "nodeprebuild",
        "prebuildinstall",
        "nodeaddonapi",
        "bindings",
        "tar",
        "zip",
        "unzip",
        "archiver",
        "decompress",
        "admzip",
        "yauzl",
        "yazl",
        "shelljs",
        "execa",
        "childprocess",
        "crossspawn",
        "nodecmd",
        "querystring",
        "qs",
        "urijs",
        "normalizeurl",
        "parseurl",
        "ws",
        "httpproxyagent",
        "httpsproxyagent",
        "babelloader",
        "cssloader",
        "styleloader",
        "fileloader",
        "urlloader",
        "sourcemap",
        "sourcemapjs",
        "sourcemapsupport",
        "leftpad",
        "isarray",
        "isobject",
        "kindof",
        "typeis",
        "extend",
        "xtend",
        "deepextend",
        "merge",
        "deepmerge",
        "crossfetch",
        "nodecache",
        "memorycache",
        "lrucache",
        "grpc",
        "protobufjs",
        "msgpack",
        "xml2js",
        "fastxmlparser",
        "zod",
    }
)


def _normalize_name(name: str) -> str:
    return name.replace("-", "").replace("_", "").replace(".", "")


def _levenshtein(a: str, b: str) -> int:
    """Damerau-Levenshtein distance: substitutions, insertions, deletions,
    and TRANSPOSITIONS — the last being the classic typosquat (``reqeust``).
    Early-exits once the bound is hopeless.
    """
    if abs(len(a) - len(b)) > 2:
        return 3
    rows = len(a) + 1
    cols = len(b) + 1
    previous2: list[int] | None = None
    previous = list(range(cols))
    for i in range(1, rows):
        current = [i] + [0] * (cols - 1)
        for j in range(1, cols):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(
                previous[j] + 1,  # deletion
                current[j - 1] + 1,  # insertion
                previous[j - 1] + cost,  # substitution
            )
            if (
                previous2 is not None
                and i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                current[j] = min(current[j], previous2[j - 2] + 1)  # transposition
        previous2, previous = previous, current
    return previous[-1]


def typosquat_hits(name: str) -> list[str]:
    """Corpus names this dependency is a near-miss of, if it is a typosquat shape."""
    if name.startswith("@"):
        # Scoped: the scope is owned namespace, the classic defense.
        return []
    normalized = _normalize_name(name)
    if normalized in TYPOSQUAT_CORPUS or len(normalized) < 5:
        return []
    hits = []
    for corpus in TYPOSQUAT_CORPUS:
        distance = _levenshtein(normalized, corpus)
        if distance == 1 or (distance == 2 and len(normalized) >= 9):
            hits.append(corpus)
    return hits


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_package_jsons(root: Path) -> set[str]:
    """Every package.json in the repo that could be a dependency surface."""
    found: set[str] = set()
    for path in root.rglob("package.json"):
        relative = path.relative_to(root).parent
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        found.add(str(relative))
    return found


def _lockfile(directory: Path) -> Path | None:
    for name in _LOCKFILES:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _entry_name(key: str) -> str:
    return key.split("node_modules/")[-1]


def check_inventory(root: Path) -> list[str]:
    """Fail-closed inventory: every surface registered, every lockfile present."""
    findings: list[str] = []
    discovered = discover_package_jsons(root)
    for directory in sorted(discovered - set(SURFACES)):
        findings.append(
            f"unclassified dependency surface {directory!r}: a package.json exists "
            "there but the surface is not in js_dependency_gate.SURFACES — "
            "classify it (shipped vs tooling) to add it to the audit (#344)"
        )
    for name, surface in SURFACES.items():
        surface_directory = root / name
        if not (surface_directory / "package.json").exists():
            findings.append(f"registered surface {name!r} has no package.json")
        if _lockfile(surface_directory) is None:
            findings.append(
                f"registered surface {name!r} ({surface.description}) has no lockfile "
                f"(expected one of {_LOCKFILES})"
            )
    return findings


def check_lock_drift(
    surface_name: str, package_json: dict[str, Any], lock: dict[str, Any]
) -> list[str]:
    """The lockfile's root entry must restate package.json exactly."""
    findings: list[str] = []
    root_entry = (lock.get("packages") or {}).get("") or {}
    for kind in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        declared = package_json.get(kind) or {}
        locked = root_entry.get(kind) or {}
        for name, specifier in declared.items():
            if name not in locked:
                findings.append(
                    f"{surface_name}: {kind} {name!r} ({specifier!r}) "
                    "is not in the lockfile root — regenerate the lockfile"
                )
            elif locked[name] != specifier:
                findings.append(
                    f"{surface_name}: {kind} {name!r} drifted: package.json "
                    f"says {specifier!r}, lockfile says {locked[name]!r}"
                )
        for name in locked:
            if name not in declared:
                findings.append(
                    f"{surface_name}: lockfile root carries {kind} "
                    f"{name!r} that package.json does not declare"
                )
    return findings


def check_provenance(surface_name: str, lock: dict[str, Any]) -> list[str]:
    """Every resolved entry: sha512 integrity and an https registry URL."""
    findings: list[str] = []
    for key, entry in (lock.get("packages") or {}).items():
        if not key or not isinstance(entry, dict):
            continue
        if entry.get("link"):
            continue
        name = _entry_name(key)
        resolved = entry.get("resolved")
        if resolved is not None and not str(resolved).startswith("https://"):
            findings.append(
                f"{surface_name}: {name!r} resolves from a non-https source "
                f"({resolved!r}) — registry https and a pinned digest are required"
            )
        integrity = entry.get("integrity")
        if resolved is not None and not integrity:
            findings.append(
                f"{surface_name}: {name!r} has no integrity hash — npm ci cannot "
                "verify what it installs"
            )
        elif integrity is not None and not str(integrity).startswith("sha512-"):
            findings.append(f"{surface_name}: {name!r} integrity is not sha512 ({integrity!r})")
    return findings


def check_licenses(surface_name: str, lock: dict[str, Any]) -> tuple[list[str], int]:
    """Declared licenses must be approved; missing data is counted, not failed."""
    findings: list[str] = []
    missing = 0
    for key, entry in (lock.get("packages") or {}).items():
        if not key or not isinstance(entry, dict) or entry.get("link"):
            continue
        name = _entry_name(key)
        license_value = entry.get("license")
        if not license_value:
            missing += 1
            continue
        if license_value in APPROVED_LICENSES:
            continue
        exception = LICENSE_EXCEPTIONS.get((name, license_value))
        if exception is not None and _not_expired(exception):
            continue
        findings.append(
            f"{surface_name}: {name!r} carries license {license_value!r}, which is "
            "not on the approved list"
        )
    return findings, missing


def check_typosquats(surface_name: str, lock: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for key in lock.get("packages") or {}:
        if not key:
            continue
        name = _entry_name(key)
        for corpus in typosquat_hits(name):
            findings.append(
                f"{surface_name}: {name!r} is edit-distance-close to popular package "
                f"{corpus!r} without being on the corpus — typosquat shape, review it"
            )
    return findings


def check_install_scripts(surface_name: str, lock: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for key, entry in (lock.get("packages") or {}).items():
        if not key or not isinstance(entry, dict) or not entry.get("hasInstallScript"):
            continue
        name = _entry_name(key)
        version = str(entry.get("version") or "?")
        exception = INSTALL_SCRIPT_EXCEPTIONS.get(name)
        if exception is None:
            findings.append(
                f"{surface_name}: {name!r}@{version} runs an install script but is "
                "not on the reviewed INSTALL_SCRIPT_EXCEPTIONS list"
            )
        elif not _not_expired(exception):
            findings.append(
                f"{surface_name}: install-script exception for {name!r} expired "
                f"on {exception.expires} — re-review or remove the dependency"
            )
        elif exception.versions and version not in exception.versions:
            findings.append(
                f"{surface_name}: install-script exception for {name!r} covers "
                f"{exception.versions} but the lockfile resolved {version} — "
                "a new version needs a new review"
            )
    return findings


_ADVISORY_ID = re.compile(r"/(?:advisories|vulns|vulnerability)/([A-Za-z0-9-]+)")


def _advisory_ids(vulnerability: dict[str, Any]) -> list[str]:
    """Stable ids for one npm-audit vulnerability entry."""
    ids: list[str] = []
    for via in vulnerability.get("via") or []:
        if isinstance(via, dict):
            url = str(via.get("url") or "")
            match = _ADVISORY_ID.search(url)
            if match:
                ids.append(match.group(1))
            elif via.get("name"):
                ids.append(str(via["name"]))
    return ids


def check_audit_report(
    surface_name: str,
    report: dict[str, Any],
    locked_versions: dict[str, set[str]],
) -> list[str]:
    """Every npm-audit finding must carry an owned, unexpired exception.

    ``npm audit --package-lock-only`` does not report installed versions, so
    version-specificity binds through the lockfile the gate already read:
    an exception lists the versions the triage reviewed, and a resolved
    version outside that list is a new finding. Via-chain entries (vulnerable
    only through the package that carries the advisory) produce no finding of
    their own — the root advisory is the verdict, and the chains resolve with
    it.
    """
    findings: list[str] = []
    for name, vulnerability in (report.get("vulnerabilities") or {}).items():
        versions = locked_versions.get(name) or {"?"}
        severity = vulnerability.get("severity") or "unknown"
        for advisory in _advisory_ids(vulnerability):
            exception = VULNERABILITY_EXCEPTIONS.get((name, advisory))
            if exception is None:
                findings.append(
                    f"{surface_name}: {name!r} ({sorted(versions)}) has {severity} "
                    f"advisory {advisory!r} with no exception — upgrade or triage"
                )
            elif not _not_expired(exception):
                findings.append(
                    f"{surface_name}: exception for {name!r} / {advisory!r} expired "
                    f"on {exception.expires} — re-triage"
                )
            elif exception.versions and not versions <= set(exception.versions):
                findings.append(
                    f"{surface_name}: exception for {name!r} / {advisory!r} covers "
                    f"{exception.versions} but the lockfile resolves {sorted(versions)} "
                    "— a new version is a new finding"
                )
    return findings


#: GuardDog rules that are verdicts. ``capability-*`` rules are descriptive:
#: they fire on any package that touches the network, filesystem, or process
#: APIs (measured: ``express`` trips capability-network-outbound), so they
#: are reported as counts, never failed on.
_GUARDDOG_VERDICT_RULES = frozenset(
    {
        "typosquatting",
        "deceptive_author",
        "unclaimed_maintainer_email_domain",
        "potentially_compromised_email_domain",
        "risky_new_dependency",
        "metadata_mismatch",
        "provenance_regression",
        "direct_url_dependency",
        "bundled_binary",
    }
)


def check_guarddog_report(
    surface_name: str,
    report: dict[str, Any],
    locked_versions: dict[str, set[str]],
) -> list[str]:
    """GuardDog threat/metadata findings must carry an owned exception.

    Version-specificity binds through the lockfile's direct-dependency
    versions (GuardDog scans the locked version; its JSON does not echo it).
    """
    findings: list[str] = []
    for package, scan in report.items():
        if not isinstance(scan, dict):
            findings.append(
                f"{surface_name}: GuardDog produced no usable scan for {package!r} "
                "— unavailable scanner is non-passing"
            )
            continue
        errors = scan.get("errors") or {}
        if errors:
            findings.append(
                f"{surface_name}: GuardDog could not scan {package!r} "
                f"({json.dumps(errors)[:200]}) — unavailable scanner is non-passing"
            )
            continue
        versions = locked_versions.get(package) or {"?"}
        results = scan.get("results") or {}
        for rule, hits in results.items():
            if not hits:
                continue
            if rule.startswith("threat-") or rule in _GUARDDOG_VERDICT_RULES:
                exception = GUARDDOG_EXCEPTIONS.get((package, rule))
                if exception is None:
                    findings.append(
                        f"{surface_name}: GuardDog rule {rule!r} fired on "
                        f"{package!r} ({sorted(versions)}) with no exception — "
                        "review the package"
                    )
                elif not _not_expired(exception):
                    findings.append(
                        f"{surface_name}: GuardDog exception for {package!r} / "
                        f"{rule!r} expired on {exception.expires} — re-review"
                    )
                elif exception.versions and not versions <= set(exception.versions):
                    findings.append(
                        f"{surface_name}: GuardDog exception for {package!r} / "
                        f"{rule!r} covers {exception.versions} but the lockfile "
                        f"resolves {sorted(versions)} — a new version is a new finding"
                    )
    return findings


def _locked_versions(lock: dict[str, Any]) -> dict[str, set[str]]:
    """name -> every version the lockfile resolves (nested copies included)."""
    versions: dict[str, set[str]] = {}
    for key, entry in (lock.get("packages") or {}).items():
        if not key or not isinstance(entry, dict) or entry.get("link"):
            continue
        version = entry.get("version")
        if version:
            versions.setdefault(_entry_name(key), set()).add(str(version))
    return versions


def direct_dependencies(root: Path) -> dict[str, dict[str, str]]:
    """surface -> {direct dependency -> locked version}, for GuardDog scans.

    The workflow consumes this via ``--direct-deps`` so the scan list and the
    gate's version binding come from one place: the lockfiles.
    """
    result: dict[str, dict[str, str]] = {}
    for surface_name in SURFACES:
        directory = root / surface_name
        lockfile = _lockfile(directory)
        package_json_path = directory / "package.json"
        if lockfile is None or not package_json_path.exists():
            continue
        package_json = _load_json(package_json_path)
        lock = _load_json(lockfile)
        root_entry = lock.get("packages") or {}
        deps: dict[str, str] = {}
        for kind in ("dependencies", "devDependencies"):
            for name in package_json.get(kind) or {}:
                entry = root_entry.get(f"node_modules/{name}")
                if isinstance(entry, dict) and entry.get("version"):
                    deps[name] = str(entry["version"])
        result[surface_name] = deps
    return result


def _parse_report_args(values: list[str]) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    for value in values:
        surface, separator, path = value.partition("=")
        if not separator or not surface or not path:
            raise SystemExit(
                f"usage: --report SURFACE=PATH (got {value!r}); known surfaces: {sorted(SURFACES)}"
            )
        reports[surface] = Path(path)
    return reports


def _audit_check(
    locked_versions: dict[str, set[str]],
) -> Callable[[str, dict[str, Any]], list[str]]:
    return lambda surface, data: check_audit_report(surface, data, locked_versions)


def _guarddog_check(
    locked_versions: dict[str, set[str]],
) -> Callable[[str, dict[str, Any]], list[str]]:
    return lambda surface, data: check_guarddog_report(surface, data, locked_versions)


def _read_scanner_report(
    surface_name: str,
    *,
    reports: dict[str, Path],
    kind: str,
    missing_hint: str,
    check: Callable[[str, dict[str, Any]], list[str]],
    findings: list[str],
) -> list[str]:
    """Read one scanner report for one surface; findings or a scanner failure.

    A missing or unparseable report is a scanner failure (exit 3), never a
    silent pass — the unavailable-scanner half of #344's non-passing rule.
    """
    path = reports.get(surface_name)
    if path is None:
        return [f"{surface_name}: no {kind} report supplied — {missing_hint}"]
    if not path.exists():
        return [f"{surface_name}: {kind} report {path} does not exist"]
    try:
        findings.extend(check(surface_name, _load_json(path)))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{surface_name}: {kind} report {path} is not usable ({exc})"]
    return []


def _check_surface(
    root: Path,
    *,
    surface_name: str,
    surface: Surface,
    audit_reports: dict[str, Path],
    guarddog_reports: dict[str, Path],
) -> tuple[list[str], list[str]]:
    """Every policy and scanner check for one surface.

    Returns (findings, scanner_failures): the first are verdicts (exit 1),
    the second are infrastructure (exit 3). A surface the inventory already
    reported (no lockfile, no package.json) checks nothing further.
    """
    directory = root / surface_name
    lockfile = _lockfile(directory)
    package_json_path = directory / "package.json"
    if lockfile is None or not package_json_path.exists():
        return [], []  # inventory already reported it

    package_json = _load_json(package_json_path)
    lock = _load_json(lockfile)
    locked_versions = _locked_versions(lock)

    findings: list[str] = []
    findings.extend(check_lock_drift(surface_name, package_json, lock))
    findings.extend(check_provenance(surface_name, lock))
    license_findings, missing_licenses = check_licenses(surface_name, lock)
    findings.extend(license_findings)
    findings.extend(check_typosquats(surface_name, lock))
    findings.extend(check_install_scripts(surface_name, lock))

    print(
        f"[{surface_name}] entries={len(lock.get('packages') or {})} "
        f"licenses-missing-data={missing_licenses} "
        f"shipped={surface.shipped}"
    )

    scanner_failures: list[str] = []
    scanner_failures.extend(
        _read_scanner_report(
            surface_name,
            reports=audit_reports,
            kind="npm audit",
            missing_hint="run `npm audit --package-lock-only --json` in the surface directory",
            check=_audit_check(locked_versions),
            findings=findings,
        )
    )
    scanner_failures.extend(
        _read_scanner_report(
            surface_name,
            reports=guarddog_reports,
            kind="GuardDog",
            missing_hint="scan every direct dependency (see the docstring)",
            check=_guarddog_check(locked_versions),
            findings=findings,
        )
    )
    return findings, scanner_failures


def _report_verdict(findings: list[str], scanner_failures: list[str]) -> int:
    """Exit code + output: scanner failures (3) outrank findings (1)."""
    if scanner_failures:
        for failure in scanner_failures:
            print(f"::error::{failure}")
        return 3
    if findings:
        print("::error::js dependency gate found policy violations:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("ok: every tracked JS surface passes inventory, lock, license, provenance,")
    print("typosquat, install-script, vulnerability, and malicious-package policy")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root (defaults to the script's repo)",
    )
    parser.add_argument(
        "--audit-report",
        action="append",
        default=[],
        metavar="SURFACE=PATH",
        help="npm audit --package-lock-only --json report for a surface",
    )
    parser.add_argument(
        "--guarddog-report",
        action="append",
        default=[],
        metavar="SURFACE=PATH",
        help="merged GuardDog per-direct-dependency report for a surface",
    )
    parser.add_argument(
        "--direct-deps",
        action="store_true",
        help=(
            "print 'SURFACE name version' for every direct dependency of every "
            "surface (the GuardDog scan list) and exit 0"
        ),
    )
    args = parser.parse_args(argv)
    root: Path = args.root

    if args.direct_deps:
        for surface_name, deps in direct_dependencies(root).items():
            for name, version in sorted(deps.items()):
                print(f"{surface_name} {name} {version}")
        return 0

    findings: list[str] = []
    scanner_failures: list[str] = []

    findings.extend(check_inventory(root))

    try:
        audit_reports = _parse_report_args(args.audit_report)
        guarddog_reports = _parse_report_args(args.guarddog_report)
    except SystemExit:
        return 2
    for reports in (audit_reports, guarddog_reports):
        if any(surface_name not in SURFACES for surface_name in reports):
            return 2

    for surface_name, surface in SURFACES.items():
        surface_findings, surface_failures = _check_surface(
            root,
            surface_name=surface_name,
            surface=surface,
            audit_reports=audit_reports,
            guarddog_reports=guarddog_reports,
        )
        findings.extend(surface_findings)
        scanner_failures.extend(surface_failures)

    return _report_verdict(findings, scanner_failures)


if __name__ == "__main__":
    sys.exit(main())
