# Restored: resource security floors (#75) and its review follow-up (#127)

These two paragraphs were recorded in `SUITE-INVENTORY.md` and then lost. They
are restored here rather than left dropped, per #208's fifth criterion.

## How they were lost

At the merge-base of #130 and `develop` this text was present. Both sides then
replaced it: #130's branch overwrote the block with canonical-Run prose, and
`develop` (via #176) overwrote it with older #68/#71/#70 security prose. Git
saw two edits to the same lines and reported a content conflict; whoever
resolved it kept one side's replacement, and this text was in neither. No one
decided to remove it — the shared-slot layout made losing it the default
outcome, which is exactly the failure #208 fixes.

---

Configurable resource security floors (#75) add fifteen maistro-core node IDs
and one maistro-server node ID. The core set is one per acceptance criterion —
defaults equal the baseline, tightening in every direction is accepted, each of
the six protected limits is refused when it crosses its floor the weak way,
the unsafe override admits a weaker dev policy, and the LLM circuit is built
from validated settings — plus three that guard the check itself: non-positive
values are rejected even in unsafe mode, every field of
`EffectiveResourcePolicy` has a declared floor, and the suite's own unsafe
override would hide the refusals if the fixture that clears it were removed —
and two on the `rate_limit_burst = 0` sentinel, which the limiter reads as "no
burst check" rather than "allow nothing", so it is accepted under a tight
per-minute limit and refused under a loose one, while a negative value stays
incoherent in every mode.
The maistro-server node ID covers the readiness diagnostic reporting the
effective values.

Six more maistro-core node IDs answer the Codex review on #127. Three cover
non-finite limits — `nan`, `+inf`, `-inf` — refused in every mode including
under the unsafe override, plus one asserting *why*: `100.0 >= nan` is False, so
a breaker with a `nan` recovery timeout opens and never becomes half-open. The
remaining two cover the burst cap: a nonzero burst above the per-minute limit is
capped rather than refused, because the limiter never consults the burst window
when the minute check already returned — and the cap is `min`, not "ignore the
burst", so a genuinely looser burst is still refused.
