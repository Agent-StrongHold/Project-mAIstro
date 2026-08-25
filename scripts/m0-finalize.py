#!/usr/bin/env python3
"""One-time strict M0 closeout migration.

This script is intentionally removed by the workflow after it succeeds. It performs
three evidence-driven corrections that are too broad/error-prone to hand-edit:

* #31: demote every currently contradicted/unverifiable completion claim to
  Accepted. The implementation history remains in the document; only the current
  lifecycle claim is narrowed to what the acceptance evidence actually proves.
* #30: distinguish BACKLOG work status from ADR/spec decision lifecycle status.
* #122: make prompt/audit persistence follow the selected Container backend.

It then derives reachability/disposition/matrix counts from the changed code.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def reconcile_completion_claims() -> None:
    report = json.loads(read("quality/ac-state.json"))
    rows = [
        *report["completion_claims_contradicted"],
        *report["completion_claims_unverifiable"],
    ]
    if len(rows) != 77:
        raise RuntimeError(f"#31 baseline moved unexpectedly: expected 77 claims, found {len(rows)}")

    changed = 0
    for row in rows:
        rel = str(row["file"])
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise RuntimeError(f"{rel}: expected YAML front matter")
        end = text.find("\n---\n", 4)
        if end < 0:
            raise RuntimeError(f"{rel}: unterminated YAML front matter")
        front = text[: end + 1]
        corrected, n = re.subn(
            r"(?m)^status:\s*(Implemented|Tests Passing)\s*$",
            "status: Accepted",
            front,
            count=1,
        )
        if n == 0:
            # Idempotence for a rerun after a failed later gate.
            if re.search(r"(?m)^status:\s*Accepted\s*$", front):
                continue
            raise RuntimeError(f"{rel}: ledger names a completion claim but status is not one")
        path.write_text(corrected + text[end + 1 :], encoding="utf-8")
        changed += 1

    if changed not in (0, 77):
        raise RuntimeError(f"#31 correction was partial: changed {changed}/77")
    print(f"#31: reconciled {changed or 77} legacy completion claims to Accepted")


def clarify_backlog_work_status() -> None:
    path = "BACKLOG.md"
    text = read(path)
    old = (
        "Maintained per [`ADR-019`](docs/adr/ADR-019-canonical-source-split.md). Status follows the\n"
        "[`ADR-031`](docs/adr/ADR-031-front-matter-and-registry.md) lifecycle, and where an item names an\n"
        "ADR or spec, **that document's front matter is authoritative** — this file records the work, not\n"
        "the decision's status. External-library adoption per [`engine#ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md)."
    )
    new = (
        "Maintained per [`ADR-019`](docs/adr/ADR-019-canonical-source-split.md). Each backlog header carries\n"
        "a **work status**, which describes the state of the backlog item only. It is deliberately separate\n"
        "from ADR/spec decision lifecycle. When an item names an ADR or spec, **that document's front matter\n"
        "is the sole authoritative decision status**; this file does not duplicate or reinterpret it.\n"
        "External-library adoption per [`engine#ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md)."
    )
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("BACKLOG.md: authority paragraph has changed unexpectedly")
    text = text.replace("## Status legend", "## Work status legend", 1)
    text = text.replace("| Proposed | Open for discussion; not yet binding |", "| Proposed | Work proposed; not yet committed for implementation |", 1)
    text = text.replace("| Accepted | Decision binding; implementation may follow |", "| Accepted | Work accepted into the backlog; implementation may follow |", 1)
    text = text.replace("| Implemented | Decision shipped; production code matches |", "| Implemented | Backlog work completed; any referenced ADR/spec keeps its own lifecycle status |", 1)
    write(path, text)

    checker = "scripts/check-backlog-consistency.py"
    ctext = read(checker)
    ctext = ctext.replace("## Status legend", "## Work status legend")
    ctext = ctext.replace(
        "BACKLOG status is deliberately NOT checked against ADR/spec `status:`. The backlog records work",
        "BACKLOG work status is deliberately NOT checked against ADR/spec `status:`. The backlog records work",
    )
    ctext = ctext.replace(
        "The ledger above is therefore the canonical backlog-status vocabulary",
        "The ledger above is therefore the canonical backlog work-status vocabulary",
    )
    write(checker, ctext)

    test = "tests/test_check_backlog_consistency.py"
    if (ROOT / test).exists():
        write(test, read(test).replace("## Status legend", "## Work status legend"))
    print("#30: separated backlog work status from ADR/spec decision lifecycle")


def wire_prompt_and_sqlite_audit() -> None:
    path = "packages/maistro-core/src/maistro/container.py"
    text = read(path)

    text = text.replace(
        "    from maistro.protocols.quota import QuotaTracker\n",
        "    from maistro.protocols.prompts import PromptManager\n    from maistro.protocols.quota import QuotaTracker\n",
        1,
    )
    text = text.replace(
        "    intent_registry: IntentRegistry\n    capabilities: CapabilityRegistry = None",
        "    intent_registry: IntentRegistry\n    # Versioned prompt persistence follows the selected relational backend (#122).\n"
        "    prompt_manager: PromptManager = None  # type: ignore[assignment]\n"
        "    capabilities: CapabilityRegistry = None",
        1,
    )
    text = text.replace(
        "    pg_pool = _resolve_pg_pool(supplied=supplied_pg_pool, from_url=pg_pool)\n    episodic_store = InMemoryEpisodicStore()",
        "    pg_pool = _resolve_pg_pool(supplied=supplied_pg_pool, from_url=pg_pool)\n\n"
        "    # Prompts are part of the same persistence decision as the agent definitions\n"
        "    # that reference them. Hive used to construct an InMemoryPromptManager after\n"
        "    # the Container had already selected PostgreSQL, which made agent souls the\n"
        "    # last pg_* surface silently lost on restart (#122).\n"
        "    if pg_pool is not None:\n"
        "        from maistro.persistence.pg_prompts import PgPromptManager\n\n"
        "        prompt_manager = PgPromptManager(pg_pool)\n"
        "    elif db_pool is not None:\n"
        "        from maistro.persistence.sqlite_prompts import SqlitePromptManager\n\n"
        "        prompt_manager = SqlitePromptManager(db_pool)\n"
        "        await prompt_manager.ensure_schema()\n"
        "    else:\n"
        "        from maistro.prompts.store import InMemoryPromptManager\n\n"
        "        prompt_manager = InMemoryPromptManager()\n\n"
        "    episodic_store = InMemoryEpisodicStore()",
        1,
    )
    text = text.replace(
        "    audit_log = _wire_audit_log(pg_pool)\n",
        "    audit_log = await _wire_audit_log(pg_pool=pg_pool, db_pool=db_pool)\n",
        1,
    )
    text = text.replace(
        "        session_store=session_store,\n        warden=warden,",
        "        session_store=session_store,\n        prompt_manager=prompt_manager,\n        warden=warden,",
        1,
    )
    text = text.replace(
        '    "sessions",\n    # The canonical execution spine',
        '    "sessions",\n    "prompts",\n    # The canonical execution spine',
        1,
    )

    helper = re.compile(
        r"def _wire_audit_log\(pg_pool: Any\) -> Any:\n.*?\n\n\ndef _wire_strike_tracker",
        re.DOTALL,
    )
    replacement = '''async def _wire_audit_log(*, pg_pool: Any, db_pool: Any) -> Any:\n    """Audit persistence follows the selected relational backend (#122).\n\n    PostgreSQL remains the canonical durable system of record. SQLite is the\n    supported single-instance/homelab backend, so choosing it must not leave the\n    audit log as the one relational store that silently resets on restart.\n    """\n    if pg_pool is not None:\n        from maistro.persistence.pg_audit import PgAuditLog\n\n        return PgAuditLog(pg_pool)\n    if db_pool is not None:\n        from maistro.persistence.sqlite_audit import SqliteAuditLog\n\n        audit = SqliteAuditLog(db_pool)\n        await audit.ensure_schema()\n        return audit\n\n    from maistro.security.sentinel.audit import InMemoryAuditLog\n\n    return InMemoryAuditLog()\n\n\ndef _wire_strike_tracker'''
    text, n = helper.subn(replacement, text, count=1)
    if n != 1:
        raise RuntimeError("container.py: _wire_audit_log shape changed unexpectedly")
    write(path, text)

    hive = "packages/hive-conductor/backend/adapters/maistro_core.py"
    htext = read(hive)
    htext = htext.replace("        from maistro.prompts.store import InMemoryPromptManager\n", "", 1)
    htext = htext.replace(
        "        prompt_manager = InMemoryPromptManager()\n",
        "        prompt_manager = self._container.prompt_manager\n",
        1,
    )
    write(hive, htext)

    pg_test = "packages/maistro-core/tests/test_container_postgres.py"
    ptext = read(pg_test)
    ptext = ptext.replace(
        '        assert "learnings" in message\n',
        '        assert "learnings" in message\n        assert "prompts" in message\n',
        1,
    )
    ptext = ptext.replace(
        '    assert type(container.audit_log).__name__ == "PgAuditLog"\n',
        '    assert type(container.audit_log).__name__ == "PgAuditLog"\n'
        '    assert type(container.prompt_manager).__name__ == "PgPromptManager"\n',
        1,
    )
    write(pg_test, ptext)

    sqlite_test = "packages/maistro-core/tests/test_container_sqlite_backend.py"
    stext = read(sqlite_test)
    stext = stext.replace(
        "    assert container.db_pool is not None\n",
        "    assert container.db_pool is not None\n"
        "    assert type(container.prompt_manager).__name__ == \"SqlitePromptManager\"\n"
        "    assert type(container.audit_log).__name__ == \"SqliteAuditLog\"\n",
        1,
    )
    stext = stext.replace(
        "    assert container.db_pool is None\n",
        "    assert container.db_pool is None\n"
        "    assert type(container.prompt_manager).__name__ == \"InMemoryPromptManager\"\n",
        1,
    )
    write(sqlite_test, stext)
    print("#122: wired PostgreSQL/SQLite prompt managers and SQLite audit persistence")


def import_script(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def refresh_reachability() -> None:
    reach = import_script("_m0_reachability", "scripts/check-reachability.py")
    unreachable, total = reach.unreachable_modules()
    baseline_path = ROOT / "quality/reachability-baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    old = set(baseline["unreachable"])
    new = set(unreachable)
    added = sorted(new - old)
    if added:
        raise RuntimeError(f"M0 introduced newly unreachable modules: {added}")
    removed = sorted(old - new)
    baseline["_generated_from"] = f"{total} production modules"
    baseline["unreachable"] = unreachable
    baseline_path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    disp_path = ROOT / "quality/reachability-dispositions.json"
    dispositions = json.loads(disp_path.read_text(encoding="utf-8"))
    kept_groups = []
    for group in dispositions["groups"]:
        group["modules"] = [module for module in group.get("modules", []) if module in new]
        if group["modules"]:
            kept_groups.append(group)
    dispositions["groups"] = kept_groups
    disp_path.write_text(json.dumps(dispositions, indent=2) + "\n", encoding="utf-8")

    expected = {
        "maistro.persistence.pg_prompts",
        "maistro.persistence.sqlite_prompts",
        "maistro.persistence.sqlite_audit",
    }
    if not expected.issubset(set(removed)):
        raise RuntimeError(f"#122 did not make all three expected modules reachable; removed={removed}")
    print(f"reachability: pruned {len(removed)} newly reachable module(s): {', '.join(removed)}")


def refresh_matrix() -> None:
    matrix = import_script("_m0_matrix", "scripts/check-convergence-matrix.py")
    path = ROOT / "docs/architecture/CONVERGENCE-MATRIX.md"
    text = path.read_text(encoding="utf-8")
    modules = matrix.production_modules()
    unreachable = set(json.loads(read("quality/reachability-baseline.json"))["unreachable"])
    ownership = matrix.parse_table(text, matrix.OWNERSHIP_MARKER)
    header, rows = ownership[0], ownership[1:]
    prefixes, failures = matrix._prefixes(rows, header.index("Modules"))
    if failures:
        raise RuntimeError("matrix ownership is invalid before refresh: " + "; ".join(failures))
    owners = matrix._assign(modules, prefixes)
    totals: dict[str, int] = {}
    misses: dict[str, int] = {}
    for module, subsystem in owners.items():
        totals[subsystem] = totals.get(subsystem, 0) + 1
        misses[subsystem] = misses.get(subsystem, 0) + int(module in unreachable)

    lines = text.splitlines()
    in_disposition = False
    header_cells: list[str] | None = None
    for index, line in enumerate(lines):
        if line.strip() == matrix.DISPOSITION_MARKER:
            in_disposition = True
            header_cells = None
            continue
        if not in_disposition or not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header_cells is None:
            header_cells = cells
            continue
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue
        key = cells[0]
        if key not in totals:
            continue
        ucol = header_cells.index("Unreachable")
        cells[ucol] = f"`{misses.get(key, 0)}/{totals[key]}`"
        if key == "Relational persistence":
            dcol = header_cells.index("Disposition")
            ecol = header_cells.index("Acceptance evidence")
            depcol = header_cells.index("Dependencies")
            cells[dcol] = "KEEP — PostgreSQL canonical stores and SQLite homelab adapters are wired"
            cells[ecol] = "container selects durable prompt/audit stores with backend conformance; zero relational modules unreachable"
            cells[depcol] = "—"
        lines[index] = "| " + " | ".join(cells) + " |"

    text = "\n".join(lines) + "\n"
    text = text.replace(
        "- PostgreSQL is no longer an unwired advertised backend: the core `pg_*` path and migrations are live. Remaining relational reachability is itemized rather than described as a silent all-in-memory fallback.",
        "- Relational persistence is fully reached: PostgreSQL is the canonical durable backend, while SQLite remains the explicit single-instance/homelab backend; prompt and audit persistence now follow the selected backend rather than silently falling back to memory.",
    )
    path.write_text(text, encoding="utf-8")
    print("matrix: regenerated unreachable counts and closed Relational persistence CONNECT")


def main() -> int:
    reconcile_completion_claims()
    clarify_backlog_work_status()
    wire_prompt_and_sqlite_audit()
    refresh_reachability()
    refresh_matrix()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
