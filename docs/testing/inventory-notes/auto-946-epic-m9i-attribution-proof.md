---
inventory-delta:
  packages/maistro-core/tests: +5
---

# auto-946-epic-m9i-attribution-proof

Epic-level composition proof for M9-I (#946): extension usage, cost, quotas,
health, and operational evidence. The children's per-criterion suites existed
(identity/provenance #950, metering/quotas #977), but nothing demonstrated
they compose into the epic's operator story at one seam. New file
`packages/maistro-core/tests/extensions/test_epic_m9i_attribution_proof.py`
(+5, collect+pass verified on this head) drives one extension invocation
through the canonical `Graph → Run → NodeRun → Attempt` spine with a governed
effect route and a wired canonical `SqliteInvocationQuota`, using only
exported surfaces:

- **Attribution (AC1)** — effect provenance `{extension_id, extension_version}`
  on the canonical event stream correlated to Run/NodeRun/Attempt/Invocation;
  meter row attributes extension/version/publisher/caller/Workspace and
  references the canonical Invocation id; the undeclared host secret reaches
  neither surface.
- **No double counting (AC2)** — one provider call charges the canonical
  Invocation quota once and is attributed once at the extension seam; an
  alias re-report of the same Invocation conflicts; canonical re-observation
  is idempotent.
- **Server-side quota composition (AC3)** — admission precedes dispatch: a
  denied reservation produces no Invocation, no event, no usage row, and can
  never settle afterwards.
- **Top cost contributor (AC5, cost half)** — per-extension/publisher cost
  breakdowns rank contributors and partition the parent total. Error/latency
  taxonomy and health views are child issue #978, whose implementation is not
  an ancestor of this head — deliberately not duplicated here.
- **Historical evidence (AC6)** — rows keep exact per-version identity after
  an upgrade and after removal; history is never reattributed or dropped.

Fail-before evidence on this head: dropping the host's effect provenance
(`host.py` → `provenance={}`) fails AC1; dropping the meter's
`UNIQUE(invocation_id)` fails AC2 (alias charges twice). Both mutations were
reverted and the tree is clean (`git diff` empty on `packages/*/src`).

Validation: extensions suite 792 passed (787 + 5); `ruff check` / `format
--check` clean (3174 files); `check-suite-inventory.py` green with this note.
