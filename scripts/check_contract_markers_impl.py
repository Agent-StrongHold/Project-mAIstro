"""Make `@pytest.mark.contract` mean what ADR-032 says it means (#345).

ADR-032 promises a specific cross-check:

    The registry CI cross-checks that an ADR claiming `contracts: [behavioral]`
    has at least one `pytest.mark.contract("behavioral")` test in its `tests:`
    list.

Nothing consumed the marker. It was registered in `pyproject.toml`, so it never
even warned -- 228 uses conveying an enforcement that did not exist, which is
the shape ADR-031 exists to remove: a claim a reader would reasonably believe
and no measurement behind it.

Three findings shaped this gate rather than a plain assertion:

* 202 of the 327 docs declaring `contracts:` list no `tests:` at all, so the
  cross-check as written is *vacuous* for 62% of its subjects.
* `cross-service` is declared 15 times and marked zero times, while ADR-032
  calls it mandatory on every A2A boundary and every published MCP server.
* Two marker kinds are in live use that ADR-032 does not define, and
  `pyproject.toml` spells the axis `cross_service` where the ADR and every
  front-matter entry use `cross-service`.

Turning the full check on today would fail on 202 documents at once, so this
is a ledger like the repo's others: every existing gap is recorded with a
disposition, a *new* gap fails, and a fixed one must shrink the ledger in the
same change. What the ledger buys is that the number cannot grow quietly.

**What this proves, and what it does not.** A marker is evidence only if the
test carrying it can run, so a statically declared `@pytest.mark.skip` or
`skipif` on the same test does not count. A test that skips at *runtime* -- a
missing service, an environment probe -- is not visible to a static reader and
is not claimed to be caught here; `check-ac-state.py` owns the "did it actually
pass" question by running the suite, and this gate deliberately does not
duplicate that at a fraction of the fidelity.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "quality" / "contract-markers-baseline.json"
DOC_DIRS = ("docs/adr", "docs/specs")

#: The contract axis ADR-032 defines. Hyphenated, matching the ADR's own
#: example and every front-matter entry; `pyproject.toml` spelled the third
#: `cross_service`, and one spelling has to win for a validator to exist at all.
DEFINED_KINDS = ("boundary", "behavioral", "cross-service")

#: Directories whose tests are vendored and not ours to mark.
SKIP_PARTS = ("third_party", ".venv", "node_modules")

CATEGORY_DISPOSITIONS = {
    "declares-contracts-without-tests": (
        "The document names contract kinds but lists no `tests:`, so ADR-032's "
        "cross-check has nothing to check. Vacuous rather than false: the claim "
        "is unevidenced, not contradicted. Retrofitting the test lists is "
        "follow-up work; the ledger stops the count growing."
    ),
    "declared-kind-unproven": (
        "The document lists tests, and none of them carries this kind's marker. "
        "This is the case ADR-032 actually describes, and the one worth fixing "
        "first, because the document names the evidence it wants."
    ),
    "undefined-marker-kind": (
        "A marker argument ADR-032 does not define. Either the axis adopts it "
        "or the test renames it -- silently accepting it would let the marker's "
        "vocabulary drift further from the decision that gives it meaning."
    ),
}


@dataclass(frozen=True)
class Finding:
    category: str
    identity: str

    def as_line(self) -> str:
        return f"{self.category}::{self.identity}"


@dataclass
class Corpus:
    """What the tree says about contracts, read once."""

    #: test path -> {kind marked on a test that can run}
    marks_by_path: dict[str, set[str]] = field(default_factory=dict)
    #: every marker argument seen, with one example location
    kinds_seen: dict[str, str] = field(default_factory=dict)


def _skipped(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A statically declared skip means the marker proves nothing."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in {"skip", "skipif"}:
            return True
    return False


def _marker_kinds(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Every `pytest.mark.contract(...)` argument on this test, "" when bare."""
    kinds: list[str] = []
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call is not None else decorator
        if not isinstance(target, ast.Attribute) or target.attr != "contract":
            continue
        if call is None or not call.args:
            kinds.append("")
            continue
        first = call.args[0]
        kinds.append(first.value if isinstance(first, ast.Constant) else "")
    return kinds


def read_corpus(root: Path) -> Corpus:
    corpus = Corpus()
    for path in sorted(root.rglob("test_*.py")):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for kind in _marker_kinds(node):
                corpus.kinds_seen.setdefault(kind, f"{rel}::{node.name}")
                if not _skipped(node):
                    corpus.marks_by_path.setdefault(rel, set()).add(kind)
    return corpus


def _front_matter(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    try:
        parsed = yaml.safe_load(text.split("---", 2)[1])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def collect(root: Path) -> list[Finding]:
    """Every place the marker's promise is not kept, as stable identities."""
    corpus = read_corpus(root)
    findings: list[Finding] = []

    for kind, where in sorted(corpus.kinds_seen.items()):
        if kind not in DEFINED_KINDS:
            shown = kind or "<no argument>"
            findings.append(Finding("undefined-marker-kind", f"{shown} ({where})"))

    for directory in DOC_DIRS:
        for doc in sorted((root / directory).glob("*.md")):
            findings.extend(_doc_findings(doc, directory, corpus))
    return findings


def _doc_findings(doc: Path, directory: str, corpus: Corpus) -> list[Finding]:
    """What one document claims that its own listed tests do not carry."""
    front = _front_matter(doc)
    if front is None:
        return []
    kinds = front.get("contracts") or []
    if not kinds:
        return []
    identity = f"{directory}/{doc.name}"
    tests = front.get("tests") or []
    if not tests:
        return [Finding("declares-contracts-without-tests", identity)]
    proven: set[str] = set()
    for listed in tests:
        proven |= corpus.marks_by_path.get(str(listed), set())
    return [
        Finding("declared-kind-unproven", f"{identity} [{kind}]")
        for kind in kinds
        if kind not in proven
    ]


def load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    categories = payload.get("categories")
    return categories if isinstance(categories, dict) else {}


def write_baseline(path: Path, findings: list[Finding]) -> None:
    categories: dict[str, dict[str, Any]] = {}
    for finding in findings:
        entry = categories.setdefault(
            finding.category,
            {"disposition": CATEGORY_DISPOSITIONS.get(finding.category, ""), "entries": []},
        )
        entry["entries"].append(finding.identity)
    for entry in categories.values():
        entry["entries"] = sorted(set(entry["entries"]))
    payload = {
        "metric_definition_version": "1",
        "defined_kinds": list(DEFINED_KINDS),
        "categories": dict(sorted(categories.items())),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def compare(
    findings: list[Finding], baseline: dict[str, dict[str, Any]]
) -> tuple[list[Finding], list[str], list[str]]:
    """New findings, stale baseline entries, and categories banked unexplained."""
    recorded = {
        f"{name}::{identity}"
        for name, entry in baseline.items()
        for identity in entry.get("entries", [])
    }
    current = {finding.as_line() for finding in findings}
    new = [finding for finding in findings if finding.as_line() not in recorded]
    stale = sorted(recorded - current)
    unexplained = sorted(
        name for name, entry in baseline.items() if not str(entry.get("disposition", "")).strip()
    )
    return new, stale, unexplained
