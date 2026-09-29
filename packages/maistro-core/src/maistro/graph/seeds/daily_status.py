"""`daily-status` — the PM Fleet's first user-modifiable default DAG.

Replaces the hard-coded polling logic that lived in
`hive-conductor/backend/routes/daily_report.py`. The same Jira + Airtable
+ research + suggested-actions composition expressed as a DAG of registered
nodes — so the user can edit it in DagBuilder, optimizer can mutate it
under the 5-signal aggregator, and topology_compare can A/B it against
alternative shapes.

Shape (sequential except where noted):

    [entry] pm_jira_filter_input
                 │  static inputs: jql + base_url + flavor + max_results
                 ▼
            jira.poll  (skipped if no PAT — handled by the Hive route
                        wrapper that checks credentials before invoking
                        this DAG; the node itself fails closed with a
                        PermissionError → the executor records it as
                        node_record.failed and downstream nodes still run
                        in parallel branches that don't depend on Jira)
                 │
                 ▼
            jira_epic_filter (transform.filter_by_type)
                 │
                 ▼
            jira_summary_format (transform.format_markdown)
                 │
                 ▼
            jira_dash_append   (dashboard.append_section, order_hint=1)

Parallel branches share `entry` via the executor's BFS walk; the daily-
status DAG uses sequential composition for clarity. Fan-out + fan-in
remain reachable by editing the saved DAG in DagBuilder (the substrate
already supports `edge.parallel = True`).

Phase 4 deliverable: this seed + a Hive route wrapper that converts the
durable run result into the response shape DailyReport.tsx expects.
Phase 6 (optimizer) starts mutating this DAG; Phase 7 (topology compare)
starts A/B-testing alternative shapes.
"""

from __future__ import annotations

from typing import Any


def daily_status_seed() -> dict[str, Any]:
    """Return a fresh daily-status DAG spec ready to feed to validate_dag()
    + run_durable_dag() + register().

    Returns a NEW dict every call so callers can mutate without shared
    state. All credential-bearing inputs (PAT, base_id) are intentionally
    omitted — the Hive route wrapper injects them per-request from the
    encrypted credentials store + project settings.
    """
    return {
        "id": "daily-status",
        "name": "Daily Status",
        "description": (
            "PM Fleet daily-status hyperagent: poll Jira for updated Epics "
            "in the last 24h, format them as a Markdown section, append "
            "to the daily-status dashboard. Edit in DagBuilder to extend "
            "with Airtable + research + suggested-actions branches."
        ),
        "use_case": "pm_fleet",
        "max_cycles": 1,
        "nodes": [
            {
                "id": "jira_poll",
                "kind": "jira.poll",
                # Static defaults; PAT + base_url + flavor injected at
                # runtime by the Hive wrapper using the active project's
                # credentials.
                "inputs": {
                    "base_url": "",
                    "jql": "updated >= -24h AND assignee = currentUser() ORDER BY updated DESC",
                    "pat": "",
                    "flavor": "server",
                    "max_results": 20,
                },
            },
            {
                # Bridge node: jira.poll outputs `issues` but the filter
                # wants `items`. Static mapping renames the upstream key.
                "id": "jira_items_alias",
                "kind": "transform.alias_keys",
                "config": {"mapping": {"items": "issues"}},
            },
            {
                "id": "jira_epic_filter",
                "kind": "transform.filter_by_type",
                "config": {
                    "types": ["Epic"],
                    "type_path": "issuetype",
                },
            },
            {
                "id": "jira_summary_format",
                "kind": "transform.format_markdown",
                "config": {
                    "template": "- {key}: {summary} ({status})",
                    "header": "## Jira Epics updated (last 24h)",
                    "empty_fallback": "_No Epics updated in the last 24h._",
                },
            },
            {
                "id": "jira_dash_append",
                "kind": "dashboard.append_section",
                "config": {
                    "dashboard_id": "daily-status",
                    "section_title": "Jira Epics (last 24h)",
                    "order_hint": 1,
                },
            },
        ],
        "edges": [
            {"from_node": "jira_poll", "to_node": "jira_items_alias"},
            {"from_node": "jira_items_alias", "to_node": "jira_epic_filter"},
            {"from_node": "jira_epic_filter", "to_node": "jira_summary_format"},
            {"from_node": "jira_summary_format", "to_node": "jira_dash_append"},
        ],
        "entry_node": "jira_poll",
    }
