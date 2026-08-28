# Gates-ran live validation

This document records the live validation protocol for the repository's
`gates-ran` merge-boundary aggregate.

The aggregate is intentionally evaluated by trusted `workflow_run` code from the
protected default branch and publishes its verdict onto the exact pull-request
head SHA. It is stricter than GitHub's raw required-check semantics: a required
check that is absent, unfinished at final evaluation, `action_required`, stale,
skipped, or cancelled is not valid execution evidence.

## Positive probe

A normal pull request to `develop` must eventually receive a successful
`gates-ran` status on its exact head SHA after every required, non-base-coupled
check has actually executed. Branch protection must accept that status without
an administrative bypass.

## Negative probe

A deliberately non-mergeable validation pull request may force one otherwise
required check into a skipped state. The trusted aggregate must publish
`gates-ran: failure` on that exact head even though GitHub may consider the
individual skipped check acceptable for required-check purposes. The negative
probe must never be merged.

The pull-request and issue timelines are the durable evidence for individual
probe executions; this file defines the protocol rather than hard-coding a
single run ID or commit SHA that would become stale.
