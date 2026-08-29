---
inventory-delta:
  tests/: +14
---
# claude-m2-379-adr-index-d0be

`ADR-INDEX.md` sat outside registry validation entirely, and 32 of its 82 rows
carried a status the ADR's own front matter contradicted — every one of them
saying `Proposed` about a decision that had since been Accepted, Deferred,
Deprecated or Superseded, plus 15 rows showing `—` for Accepted where the front
matter held a real date. That inverts the signal the index exists to carry: a
reader scanning it for what has been ratified was being told the opposite.

**`tests/test_check_adr_index.py` (+14)** covers `scripts/check-adr-index.py`:

- the committed index agrees with the committed corpus, and every indexed id
  resolves to a real ADR file — the two assertions that make this a ratchet
  rather than a one-off cleanup;
- **both directions are driven independently**, which is the point the issue
  makes and the reason the count is what it is. Four tests mutate the index (a
  stale status, a stale accepted date, a duplicated row, a row for an ADR that
  does not exist) and two mutate the front matter (a status change, a created
  date change) with the index untouched. A checker that only ever saw index
  edits could be comparing the index to itself and every test would still pass;
- `--fix` reconciles a drifted index, is idempotent, and — the requirement that
  constrains the implementation — leaves `Ver`, `Last Modified` and `Summary`
  byte-identical across all 82 rows. Those are reviewed prose and git-derived
  facts that front matter does not hold, so a regenerator that rewrote the file
  wholesale would destroy them. That is why this rewrites cells rather than
  emitting a new table;
- the legend's `†` proxy is pinned in both directions: a ratified ADR with no
  `accepted:` field shows its created date marked as a proxy, and an unratified
  one shows no date at all. Dropping the proxy would make an Accepted ADR look
  unratified; inventing a date would be worse;
- and the gate runs as a script, not only as an import, because that is how
  `registry.yml` invokes it.

The fixture is a `copytree` of the real `docs/adr`, not a synthetic corpus. The
thing under test is agreement with the *actual* front matter; a hand-built
corpus would prove only that the parser agrees with itself.
