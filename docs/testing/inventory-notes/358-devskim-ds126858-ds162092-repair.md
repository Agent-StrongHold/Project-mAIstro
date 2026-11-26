---
inventory-delta:
  tests/: +1
---
# #358 CI repair — devskim code-scanning check-run at head 90fffc906253

Repair round for the failing `devskim` check (check-run 113741115061, PR
#1712): two new alerts on lines this PR's diff does not contain — 1 failure
(DS126858, "A weak or broken hash algorithm was detected") and 1 note
(DS162092, "Accessing localhost could indicate debug code"). Code scanning
re-attributed both pre-existing findings because the branch's diff is large;
the check-run summary says as much ("Alerts not introduced by this pull
request might have been detected because the code changes were too large").
Same failure mode as the #1420 repair, so the same evidence rules apply.

## The two annotations, rule IDs, and remedies

Rule IDs confirmed against DevSkim's default rules upstream
(`rules/default/security/cryptography/hash_algorithm.json` → DS126858, whose
language-agnostic regex matches `sha1` in `hashlib.sha1`;
`rules/default/security/hygiene/localhost.json` → DS162092) — the check-run
annotations carry only titles, not IDs.

1. `scripts/check-suite-inventory.py` (`default_note_slug`, the note-name
   digest): **DS126858**. The suffix is a non-cryptographic discriminator, so
   the finding is eliminated rather than suppressed: the derivation moved to
   `hashlib.sha256(...).hexdigest()[:4]`, keeping every property the ledger
   needs (readable slug, short digest, deterministic, distinct for branches
   that sanitize alike). Recorded note names are filename-independent —
   `load_deltas()` reads every note in the directory — so existing notes stay
   counted; only future `--update` runs derive the new digest.
2. `packages/hive-conductor/backend/stores.py` (`_seed_mcp_servers`, the
   fabricated "Filesystem" demo row): **DS162092**. Loopback is the truthful
   origin for a fabricated "Local workspace tools" seed row, and the health
   check that may dial it runs through the outbound-policy guard, so the
   pattern is irreducible. Same-line dated suppression in the
   #1420/#929/#817-verified syntax.

`tests/test_check_suite_inventory.py` gains one test pinning the slug digest
to sha256 derivation, so a revert to sha1 fails a named test instead of a red
scanner gate on the next large PR.

## Evidence

- `uv run pytest tests/test_check_suite_inventory.py -q`: 88 passed (one more
  than the 87 the file collected before this repair).
- The new digest test discriminates: sha1 and sha256 of `claude/x` disagree in
  the first four hex chars (`hashlib.sha1(b"claude/x").hexdigest()[:4]` ≠
  `hashlib.sha256(b"claude/x").hexdigest()[:4]`), so the pin fails against the
  regression it names.
- Local re-scan mirroring the two flagged rule patterns over the two changed
  files: no remaining match (`sha256` is outside DS126858's alternation; the
  seed row carries its matching same-line suppression).
- `uv run ruff check .` / `ruff format --check .` clean;
  `scripts/check-suite-inventory.py --suite tests/` matches the recorded
  inventory including this note's delta.
