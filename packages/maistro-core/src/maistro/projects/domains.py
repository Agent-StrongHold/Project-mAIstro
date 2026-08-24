"""Well-known domains (Project.use_case values) shipped with maistro.

This is intentionally NOT an enum — `use_case` stays a free string on the
Project record so users + ops can mint their own (a brand team
could create `use_case='brand_compliance'` without a code change). The
list below is the curated set the standard frontends recognize and ship
a default page set + nav config for. Anything else falls back to the
"generic" shell.

The User → Domain → many Projects hierarchy is enforced by the store +
the frontend mount paths, not by this enum.
"""

from __future__ import annotations

from typing import TypedDict


class DomainConfig(TypedDict, total=False):
    """Per-domain frontend hint shipped to the UI shell."""

    use_case: str  # the value stored on Project.use_case
    mount_path: str  # URL prefix the SPA mounts at (gateway proxy key)
    display_name: str  # human-readable label for nav + project picker
    icon: str  # one-char emoji / icon hint
    description: str  # tooltip / onboarding helper text
    default_dag_seeds: list[str]  # default DAG ids seeded on first project create


# Curated set the standard maistro frontends know how to render.
#
# `pm_fleet` **stays**, and #129 asked for that call to be recorded rather than
# left implicit. The POC *mode* is what was retired — the global flag that
# changed routing, navigation and setup defaults — not the domain. A domain is
# a curated config an integration can declare it targets; `pm_fleet` is one of
# six such configs and reads no differently from `canvas_creative` beside it,
# and `personas/templates/pm_fleet.yaml` remains a persona template for exactly
# the same reason. Removing it would delete a working configuration to make a
# point about a flag that no longer exists.
#
# Order = priority for the v0.2/v0.3 shipping plan:
#   1. pm_fleet         — first shipped domain; heaviest investment
#   2. canvas_creative  — SECOND priority. The maistro-canvas substrate
#                         (image-gen + composite + Lulu print-on-demand) is
#                         already nearly complete; ship it as the second
#                         frontend to prove the DAG executor handles non-
#                         text domains end-to-end.
#   3. engineering_rfc  — token seat; full UI deferred to v0.4.
#   4-6. support_triage, marketing_campaign, product_discovery — token
#         seats; curated configs ship now so external integrations can
#         declare which domain they target, but no dedicated UI yet.
KNOWN_DOMAINS: tuple[DomainConfig, ...] = (
    {
        "use_case": "pm_fleet",
        "mount_path": "/pm/",
        "display_name": "PM Fleet",
        "icon": "🐝",
        "description": (
            "Program-management hyperagent. Intake, Program Manager, "
            "Research, Risk, Delivery, Reporting. Real Claude via MAISTRO "
            "gateway; real Jira + Confluence + Airtable + browser-use."
        ),
        "default_dag_seeds": ["daily-status", "fleet-pulse"],
    },
    {
        "use_case": "canvas_creative",
        "mount_path": "/art/",
        "display_name": "Canvas Studio",
        "icon": "🎨",
        "description": (
            "Creative teams composing ad art. Brief → image generate → "
            "composite → art-director review → asset board. Rides on the "
            "same DAG executor as PM Fleet; different node catalog."
        ),
        "default_dag_seeds": ["ad-art-shot", "campaign-asset-board"],
    },
    {
        "use_case": "engineering_rfc",
        "mount_path": "/eng/",
        "display_name": "Engineering Reviews",
        "icon": "⚙",
        "description": (
            "RFC drafting + code review hyperagent. Planner → coder → "
            "reviewer → tests. Reuses CONDUCTOR/PLANNER/CODER/REVIEWER "
            "engineering roles + the same DAG executor."
        ),
        "default_dag_seeds": ["rfc-review", "code-review"],
    },
    {
        "use_case": "support_triage",
        "mount_path": "/support/",
        "display_name": "Support Triage",
        "icon": "🎧",
        "description": (
            "Customer-support inbox triage. Classify → route → draft "
            "reply → human approve. Uses Jira/ServiceNow integrations."
        ),
        "default_dag_seeds": ["incident-triage", "ticket-classify"],
    },
    {
        "use_case": "marketing_campaign",
        "mount_path": "/marketing/",
        "display_name": "Campaign Studio",
        "icon": "📣",
        "description": (
            "Marketing-campaign planning. Brief → audience research → "
            "creative directions → channel mix → KPI tracker."
        ),
        "default_dag_seeds": ["campaign-brief"],
    },
    {
        "use_case": "product_discovery",
        "mount_path": "/product/",
        "display_name": "Product Discovery",
        "icon": "🧪",
        "description": (
            "Product-discovery hyperagent. Customer interview synthesis, "
            "feature triage, opportunity mapping, hypothesis tests."
        ),
        "default_dag_seeds": ["discovery-synth"],
    },
)


def domain_for(use_case: str) -> DomainConfig | None:
    """Look up a curated domain by use_case value. Returns None for
    user-minted custom use cases — those fall back to the generic shell."""
    for d in KNOWN_DOMAINS:
        if d.get("use_case") == use_case:
            return d
    return None


def domain_use_cases() -> list[str]:
    """List of curated domain use_case values."""
    return [d["use_case"] for d in KNOWN_DOMAINS if "use_case" in d]
