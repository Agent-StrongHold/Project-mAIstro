---
inventory-delta:
  tests/: +6
---

# Create private backup destinations

Six fixture-only tests run the backup script with a fake Docker executable and
permissive caller umask. New host-created dump files are private; existing
owner-only destinations work, while group/world-accessible destinations and
leaf symlinks fail before a dump without changing existing permissions.

Focused tests: six pass. The unchanged script fails five of the six cases.
Bash syntax and test ruff checks pass. Independent review reran all six tests.

The configured BACKUP_ROOT is trusted operator configuration. This does not
claim race resistance against attacker-controlled ancestors or sanitize
preexisting inner-file symlinks. Docker-copied files retain source permissions,
protected by the owner-only destination; no recursive chmod is performed.
