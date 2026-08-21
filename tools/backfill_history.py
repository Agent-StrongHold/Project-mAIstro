#!/usr/bin/env python3
"""Backfill `history` fields into ADR/Spec frontmatter from existing date fields + git log."""

import re
import subprocess
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)\n(---)", re.DOTALL)

# Date fields that map to statuses
ADR_DATE_MAP = {
    "created": "Proposed",
    "accepted": "Accepted",
    "fully-specced": "Fully Specced",
    "implemented": "Implemented",
    "deferred": "Deferred",
    "denied": "Denied",
    "deprecated": "Deprecated",
    "superseded": "Superseded",
}

SPEC_DATE_MAP = {
    "created": "Proposed",
    "accepted": "Accepted",
    "ac-defined": "AC Defined",
    "in-progress": "In Progress",
    "tests-passing": "Tests Passing",
    "implemented": "Implemented",
    "deferred": "Deferred",
    "rejected": "Will Not Implement",
    "superseded": "Superseded",
}


def git_first_date(path: Path) -> str | None:
    """Get the earliest commit date for a file."""
    try:
        result = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%as", "--", str(path)],
            capture_output=True,
            text=True,
            cwd=path.parent,
        )
        dates = result.stdout.strip().split("\n")
        return dates[-1] if dates and dates[-1] else None
    except Exception:
        return None


def build_history(fm: dict, kind: str) -> list[dict]:
    """Build history list from existing frontmatter date fields."""
    date_map = ADR_DATE_MAP if kind == "adr" else SPEC_DATE_MAP
    entries = []
    for field, status in date_map.items():
        val = fm.get(field)
        if val:
            date_str = str(val)[:10]  # Handle datetime objects
            entries.append({"status": status, "date": date_str})

    # If we only have 'created' and the status is beyond Proposed, infer
    status = fm.get("status", "Proposed")
    dates_found = {e["status"] for e in entries}

    # Ensure current status is represented
    if status not in dates_found and status != "Proposed":
        # Use created date as fallback
        created = fm.get("created")
        if created:
            entries.append({"status": status, "date": str(created)[:10]})

    # Sort by date, then by lifecycle order for same-date entries
    order = list(date_map.values())
    entries.sort(
        key=lambda e: (str(e["date"]), order.index(e["status"]) if e["status"] in order else 99)
    )

    # Deduplicate
    seen = set()
    unique = []
    for e in entries:
        if e["status"] not in seen:
            seen.add(e["status"])
            unique.append(e)

    return unique


def format_history(history: list[dict]) -> str:
    """Format history as YAML list."""
    lines = ["history:"]
    for entry in history:
        lines.append(f"  - status: {entry['status']}")
        lines.append(f"    date: {entry['date']}")
    return "\n".join(lines)


def inject_history(path: Path) -> bool:
    """Add history field to a file's frontmatter. Returns True if modified."""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return False

    import yaml

    fm = yaml.safe_load(m.group(2))
    if not fm or "kind" not in fm:
        return False
    if fm.get("history"):
        return False  # Already has history

    kind = fm["kind"]
    if kind not in ("adr", "spec"):
        return False

    history = build_history(fm, kind)
    if not history:
        return False

    # Insert history before the closing ---
    fm_text = m.group(2)
    history_yaml = format_history(history)
    new_fm = fm_text.rstrip() + "\n" + history_yaml
    new_text = f"---\n{new_fm}\n---" + text[m.end() :]
    path.write_text(new_text, encoding="utf-8")
    return True


def main():
    roots = sys.argv[1:] or ["docs/adr", "docs/specs"]
    modified = 0
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in sorted(root_path.glob("*.md")):
            if not re.match(r"^(ADR|SPEC)-\d+", path.name):
                continue
            if inject_history(path):
                modified += 1
                print(f"  ✓ {path.name}")

    print(f"\n{modified} file(s) updated with history.")


if __name__ == "__main__":
    main()
