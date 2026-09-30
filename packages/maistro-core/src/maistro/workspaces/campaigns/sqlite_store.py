"""Durable campaign records over the deployment's SQLite database (AC-5).

Same convention as `quota/sqlite_usage_log.py`: an injected `aiosqlite`
connection, plain typed columns for everything that filters or orders, a JSON
payload column the model round-trips through, and an `ensure_schema()` that
runs through the shared `serialized_schema_upgrade` discipline so concurrent
initializations sharing one database cannot interleave. One connection, one
operation lock: selection, insert and commit stay one operation for ordinary
callers.

The tables hold **operator policy and decisions only** — campaigns, controls,
per-item records, parks, audit. No work state, no leases, no Goal fields: the
canonical spine and `maistro.goals` own those, and a campaign that duplicated
them would be the second owner the M1 freeze forbids.

Retention: every row here is bounded by its campaign
(`quality/durable-table-retention.json`); `delete_campaign` is the driven
deletion path that purges all of a campaign's rows when an operator deletes
the campaign.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.sqlite_schema import serialized_schema_upgrade
from maistro.workspaces.campaigns.model import (
    Actor,
    AuditKind,
    AutonomyMode,
    BudgetUsage,
    CampaignAuditRecord,
    CampaignDefinition,
    CampaignPolicy,
    ControlKind,
    ControlRecord,
    ItemPolicyRecord,
    ParkEvidence,
    ParkRecord,
    ParkUnpark,
)
from maistro.workspaces.campaigns.store import (
    CampaignNotFound,
    ControlNotFound,
    ParkNotFound,
)

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (campaign_id, policy_version)
)
"""

_CONTROLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_controls (
    control_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    item_id TEXT,
    set_at TEXT NOT NULL,
    cleared_at TEXT,
    policy_version INTEGER NOT NULL,
    payload TEXT NOT NULL
)
"""

_ITEM_RECORDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_item_records (
    campaign_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (campaign_id, item_id)
)
"""

_PARKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_parks (
    park_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    parked_at TEXT NOT NULL,
    unparked_at TEXT,
    payload TEXT NOT NULL
)
"""

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    campaign_id TEXT,
    item_id TEXT,
    kind TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    payload TEXT NOT NULL
)
"""

_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_usage (
    campaign_id TEXT PRIMARY KEY,
    cost_usd REAL NOT NULL DEFAULT 0,
    minutes REAL NOT NULL DEFAULT 0,
    completions INTEGER NOT NULL DEFAULT 0
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_campaign_controls_campaign ON campaign_controls (campaign_id, set_at)",
    "CREATE INDEX IF NOT EXISTS idx_campaign_parks_campaign ON campaign_parks (campaign_id, parked_at)",
    "CREATE INDEX IF NOT EXISTS idx_campaign_audit_campaign ON campaign_audit (campaign_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_campaigns_workspace ON campaigns (workspace_id)",
]


def _iso(moment: datetime) -> str:
    value = moment if moment.utcoffset() is not None else moment.replace(tzinfo=UTC)
    return value.isoformat()


class SqliteCampaignStore:
    """The durable twin of :class:`InMemoryCampaignStore` (AC-5: controls,
    parks and audit survive a restart because they live in the database, not
    in process memory)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._operation_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        async with self._operation_lock, serialized_schema_upgrade(self._conn):
            for script in (
                _SCHEMA,
                _CONTROLS_SCHEMA,
                _ITEM_RECORDS_SCHEMA,
                _PARKS_SCHEMA,
                _AUDIT_SCHEMA,
                _USAGE_SCHEMA,
            ):
                await self._conn.execute(script)
            for index in _INDEXES:
                await self._conn.execute(index)
            await self._conn.commit()

    # -- campaigns ---------------------------------------------------------

    async def create_campaign(
        self,
        *,
        workspace_id: str,
        name: str,
        actor: Actor,
        policy: CampaignPolicy | None = None,
        project_id: str | None = None,
        campaign_id: str | None = None,
        created_at: datetime | None = None,
    ) -> CampaignDefinition:
        fields: dict[str, Any] = {
            "workspace_id": workspace_id,
            "name": name,
            "policy": policy or CampaignPolicy(),
            "project_id": project_id,
            "created_by": actor,
        }
        if campaign_id is not None:
            fields["campaign_id"] = campaign_id
        if created_at is not None:
            fields["created_at"] = created_at
        campaign = CampaignDefinition.model_validate(fields)
        await self._insert_campaign(campaign)
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.CAMPAIGN_CREATED,
                policy_version=campaign.policy_version,
                campaign_id=campaign.campaign_id,
                payload={"name": campaign.name, "workspace_id": workspace_id},
            )
        )
        return campaign

    async def _insert_campaign(self, campaign: CampaignDefinition) -> None:
        async with self._operation_lock:
            await self._conn.execute(
                "INSERT INTO campaigns (campaign_id, policy_version, workspace_id, project_id,"
                " created_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    campaign.campaign_id,
                    campaign.policy_version,
                    campaign.workspace_id,
                    campaign.project_id,
                    _iso(campaign.created_at),
                    campaign.model_dump_json(),
                ),
            )
            await self._conn.commit()

    async def get_campaign(self, campaign_id: str) -> CampaignDefinition | None:
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM campaigns WHERE campaign_id = ?"
                " ORDER BY policy_version DESC LIMIT 1",
                (campaign_id,),
            )
            row = await cursor.fetchone()
        return CampaignDefinition.model_validate_json(row[0]) if row else None

    async def require_campaign(self, campaign_id: str) -> CampaignDefinition:
        campaign = await self.get_campaign(campaign_id)
        if campaign is None:
            raise CampaignNotFound(campaign_id)
        return campaign

    async def list_campaigns(
        self, workspace_id: str | None = None, *, latest_only: bool = True
    ) -> list[CampaignDefinition]:
        async with self._operation_lock:
            if workspace_id is None:
                cursor = await self._conn.execute(
                    "SELECT payload FROM campaigns ORDER BY campaign_id, policy_version"
                )
            else:
                cursor = await self._conn.execute(
                    "SELECT payload FROM campaigns WHERE workspace_id = ?"
                    " ORDER BY campaign_id, policy_version",
                    (workspace_id,),
                )
            rows = await cursor.fetchall()
        campaigns = [CampaignDefinition.model_validate_json(row[0]) for row in rows]
        if not latest_only:
            return campaigns
        latest: dict[str, CampaignDefinition] = {}
        for campaign in campaigns:
            current = latest.get(campaign.campaign_id)
            if current is None or campaign.policy_version > current.policy_version:
                latest[campaign.campaign_id] = campaign
        return sorted(latest.values(), key=lambda c: (c.campaign_id, c.policy_version))

    async def update_policy(
        self, campaign_id: str, policy: CampaignPolicy, *, actor: Actor
    ) -> CampaignDefinition:
        campaign = await self.require_campaign(campaign_id)
        updated = campaign.model_copy(
            update={
                "policy": policy,
                "policy_version": campaign.policy_version + 1,
                "superseded_version": campaign.policy_version,
            }
        )
        await self._insert_campaign(updated)
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.POLICY_UPDATED,
                policy_version=updated.policy_version,
                campaign_id=campaign_id,
                payload={"superseded_version": updated.superseded_version},
            )
        )
        return updated

    # -- controls ----------------------------------------------------------

    async def set_control(
        self,
        campaign_id: str,
        kind: ControlKind,
        *,
        actor: Actor,
        item_id: str | None = None,
        set_at: datetime | None = None,
    ) -> ControlRecord:
        campaign = await self.require_campaign(campaign_id)
        fields: dict[str, Any] = {
            "campaign_id": campaign_id,
            "kind": kind,
            "item_id": item_id,
            "set_by": actor,
            "policy_version": campaign.policy_version,
        }
        if set_at is not None:
            fields["set_at"] = set_at
        control = ControlRecord.model_validate(fields)
        async with self._operation_lock:
            await self._conn.execute(
                "INSERT INTO campaign_controls (control_id, campaign_id, kind, item_id, set_at,"
                " cleared_at, policy_version, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    control.control_id,
                    campaign_id,
                    kind.value,
                    item_id,
                    _iso(control.set_at),
                    None,
                    control.policy_version,
                    control.model_dump_json(),
                ),
            )
            await self._conn.commit()
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.CONTROL_SET,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                item_id=item_id,
                payload={"kind": kind.value, "control_id": control.control_id},
            )
        )
        return control

    async def clear_control(self, control_id: str, *, actor: Actor) -> ControlRecord:
        control = await self.get_control(control_id)
        if control is None:
            raise ControlNotFound(control_id)
        if not control.active:
            return control
        cleared = control.model_copy(update={"cleared_at": datetime.now(UTC), "cleared_by": actor})
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "UPDATE campaign_controls SET cleared_at = ?, payload = ?"
                " WHERE control_id = ? AND cleared_at IS NULL",
                (
                    _iso(cleared.cleared_at or datetime.now(UTC)),
                    cleared.model_dump_json(),
                    control_id,
                ),
            )
            await self._conn.commit()
            if cursor.rowcount == 0:
                # Another writer cleared it between the read and the write;
                # the database is the authority, so read what it holds.
                return await self.require_control(control_id)
        campaign = await self.get_campaign(control.campaign_id)
        payload: dict[str, object] = {"kind": control.kind.value, "control_id": control_id}
        record = await self._get_item_record(control.campaign_id, control.item_id or "")
        if control.kind is ControlKind.HUMAN_ONLY and campaign is not None:
            payload["restored_mode"] = (
                campaign.policy.default_autonomy_mode.value
                if record is None or record.mode_override is AutonomyMode.HUMAN_ONLY
                else (record.mode_override.value if record.mode_override else None)
            )
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.CONTROL_CLEARED,
                policy_version=campaign.policy_version if campaign else control.policy_version,
                campaign_id=control.campaign_id,
                item_id=control.item_id,
                payload=payload,
            )
        )
        return cleared

    async def require_control(self, control_id: str) -> ControlRecord:
        control = await self.get_control(control_id)
        if control is None:
            raise ControlNotFound(control_id)
        return control

    async def get_control(self, control_id: str) -> ControlRecord | None:
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM campaign_controls WHERE control_id = ?",
                (control_id,),
            )
            row = await cursor.fetchone()
        return ControlRecord.model_validate_json(row[0]) if row else None

    async def list_controls(
        self, campaign_id: str, *, active_only: bool = False
    ) -> list[ControlRecord]:
        async with self._operation_lock:
            # Each branch is a complete constant query: campaign_id is the
            # only bound parameter (via ?), and the optional filter is a
            # constant fragment rather than concatenated user data. Written as
            # two literals (not ``+`` concatenation) to stay clear of bandit
            # B608's string-construction heuristic while being behavior-identical.
            if active_only:
                query = (
                    "SELECT payload FROM campaign_controls WHERE campaign_id = ? AND cleared_at IS NULL "
                    "ORDER BY set_at, control_id"
                )
            else:
                query = (
                    "SELECT payload FROM campaign_controls WHERE campaign_id = ? "
                    "ORDER BY set_at, control_id"
                )
            cursor = await self._conn.execute(query, (campaign_id,))
            rows = await cursor.fetchall()
        return [ControlRecord.model_validate_json(row[0]) for row in rows]

    # -- per-item records --------------------------------------------------

    async def set_item_record(
        self,
        campaign_id: str,
        item_id: str,
        *,
        actor: Actor,
        mode_override: AutonomyMode | None = None,
        human_priority: float | None = None,
    ) -> ItemPolicyRecord:
        campaign = await self.require_campaign(campaign_id)
        record = ItemPolicyRecord(
            campaign_id=campaign_id,
            item_id=item_id,
            mode_override=mode_override,
            human_priority=human_priority,
            updated_by=actor,
            policy_version=campaign.policy_version,
        )
        async with self._operation_lock:
            await self._conn.execute(
                "INSERT INTO campaign_item_records (campaign_id, item_id, updated_at, payload)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (campaign_id, item_id) DO UPDATE SET"
                " updated_at = excluded.updated_at, payload = excluded.payload",
                (
                    campaign_id,
                    item_id,
                    _iso(record.updated_at),
                    record.model_dump_json(),
                ),
            )
            await self._conn.commit()
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.ITEM_RECORD_SET,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                item_id=item_id,
                payload={
                    "mode_override": record.mode_override.value if record.mode_override else None,
                    "human_priority": record.human_priority,
                },
            )
        )
        return record

    async def _get_item_record(self, campaign_id: str, item_id: str) -> ItemPolicyRecord | None:
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM campaign_item_records WHERE campaign_id = ? AND item_id = ?",
                (campaign_id, item_id),
            )
            row = await cursor.fetchone()
        return ItemPolicyRecord.model_validate_json(row[0]) if row else None

    async def list_item_records(self, campaign_id: str) -> list[ItemPolicyRecord]:
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM campaign_item_records WHERE campaign_id = ? ORDER BY item_id",
                (campaign_id,),
            )
            rows = await cursor.fetchall()
        return [ItemPolicyRecord.model_validate_json(row[0]) for row in rows]

    # -- parks -------------------------------------------------------------

    async def park_item(
        self,
        campaign_id: str,
        item_id: str,
        evidence: ParkEvidence,
        *,
        actor: Actor,
    ) -> ParkRecord:
        campaign = await self.require_campaign(campaign_id)
        park = ParkRecord(
            campaign_id=campaign_id,
            item_id=item_id,
            evidence=evidence,
            parked_by=actor,
            policy_version=campaign.policy_version,
        )
        async with self._operation_lock:
            await self._conn.execute(
                "INSERT INTO campaign_parks (park_id, campaign_id, item_id, parked_at,"
                " unparked_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    park.park_id,
                    campaign_id,
                    item_id,
                    _iso(park.parked_at),
                    None,
                    park.model_dump_json(),
                ),
            )
            await self._conn.commit()
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.ITEM_PARKED,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                item_id=item_id,
                payload={
                    "park_id": park.park_id,
                    "reason": evidence.reason,
                    "blocking_dependency": evidence.blocking_dependency,
                    "failing_check": evidence.failing_check,
                    "run_reference": evidence.run_reference,
                    "artifact_references": list(evidence.artifact_references),
                },
            )
        )
        return park

    async def unpark_item(self, park_id: str, *, actor: Actor) -> ParkRecord:
        park = await self.get_park(park_id)
        if park is None:
            raise ParkNotFound(park_id)
        if not park.active:
            return park
        campaign = await self.get_campaign(park.campaign_id)
        policy_version = campaign.policy_version if campaign else park.policy_version
        unpark_decision = ParkUnpark(unparked_by=actor, policy_version=policy_version)
        unparked = park.model_copy(update={"unparked": unpark_decision})
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "UPDATE campaign_parks SET unparked_at = ?, payload = ?"
                " WHERE park_id = ? AND unparked_at IS NULL",
                (
                    _iso(unpark_decision.unparked_at),
                    unparked.model_dump_json(),
                    park_id,
                ),
            )
            await self._conn.commit()
            if cursor.rowcount == 0:
                return await self.require_park(park_id)
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.ITEM_UNPARKED,
                policy_version=policy_version,
                campaign_id=park.campaign_id,
                item_id=park.item_id,
                payload={"park_id": park_id},
            )
        )
        return unparked

    async def require_park(self, park_id: str) -> ParkRecord:
        park = await self.get_park(park_id)
        if park is None:
            raise ParkNotFound(park_id)
        return park

    async def get_park(self, park_id: str) -> ParkRecord | None:
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM campaign_parks WHERE park_id = ?",
                (park_id,),
            )
            row = await cursor.fetchone()
        return ParkRecord.model_validate_json(row[0]) if row else None

    async def list_parks(self, campaign_id: str, *, active_only: bool = False) -> list[ParkRecord]:
        async with self._operation_lock:
            # Constant queries per branch (see list_controls): campaign_id is
            # the only bound parameter; the optional filter is a constant
            # fragment, not concatenated user data - clears bandit B608.
            if active_only:
                query = (
                    "SELECT payload FROM campaign_parks WHERE campaign_id = ? AND unparked_at IS NULL "
                    "ORDER BY parked_at, park_id"
                )
            else:
                query = (
                    "SELECT payload FROM campaign_parks WHERE campaign_id = ? "
                    "ORDER BY parked_at, park_id"
                )
            cursor = await self._conn.execute(query, (campaign_id,))
            rows = await cursor.fetchall()
        return [ParkRecord.model_validate_json(row[0]) for row in rows]

    # -- usage -------------------------------------------------------------

    async def record_usage(
        self,
        campaign_id: str,
        *,
        actor: Actor,
        cost_usd: float = 0.0,
        minutes: float = 0.0,
        completions: int = 0,
    ) -> BudgetUsage:
        campaign = await self.require_campaign(campaign_id)
        previous = await self.get_usage(campaign_id)
        updated = BudgetUsage(
            cost_usd=previous.cost_usd + cost_usd,
            minutes=previous.minutes + minutes,
            completions=previous.completions + completions,
        )
        async with self._operation_lock:
            await self._conn.execute(
                "INSERT INTO campaign_usage (campaign_id, cost_usd, minutes, completions)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (campaign_id) DO UPDATE SET"
                " cost_usd = excluded.cost_usd, minutes = excluded.minutes,"
                " completions = excluded.completions",
                (campaign_id, updated.cost_usd, updated.minutes, updated.completions),
            )
            await self._conn.commit()
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.USAGE_RECORDED,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                payload={"cost_usd": cost_usd, "minutes": minutes, "completions": completions},
            )
        )
        return updated

    async def get_usage(self, campaign_id: str) -> BudgetUsage:
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT cost_usd, minutes, completions FROM campaign_usage WHERE campaign_id = ?",
                (campaign_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return BudgetUsage()
        return BudgetUsage(cost_usd=row[0], minutes=row[1], completions=row[2])

    # -- audit -------------------------------------------------------------

    async def append_audit(self, *records: CampaignAuditRecord) -> None:
        if not records:
            return
        async with self._operation_lock:
            for record in records:
                await self._conn.execute(
                    "INSERT INTO campaign_audit (at, campaign_id, item_id, kind, policy_version,"
                    " payload) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        _iso(record.at),
                        record.campaign_id,
                        record.item_id,
                        record.kind.value,
                        record.policy_version,
                        record.model_dump_json(exclude={"seq"}),
                    ),
                )
            await self._conn.commit()

    async def audit_trail(
        self, campaign_id: str | None = None, *, limit: int | None = None
    ) -> list[CampaignAuditRecord]:
        async with self._operation_lock:
            if campaign_id is None:
                cursor = await self._conn.execute("SELECT payload FROM campaign_audit ORDER BY seq")
            else:
                cursor = await self._conn.execute(
                    "SELECT payload FROM campaign_audit WHERE campaign_id = ? ORDER BY seq",
                    (campaign_id,),
                )
            rows = await cursor.fetchall()
        records = [CampaignAuditRecord.model_validate_json(row[0]) for row in rows]
        if limit is not None:
            records = records[-limit:]
        return records

    # -- retention ---------------------------------------------------------

    async def delete_campaign(self, campaign_id: str) -> int:
        """Purge every row bounded by this campaign (retention deletion path).

        The campaign row and its controls, per-item records, parks and audit
        entries are one bounded family: an operator deleting the campaign
        deletes its decisions with it. Returns the number of rows removed."""
        async with self._operation_lock:
            total = 0
            for statement, parameters in (
                ("DELETE FROM campaigns WHERE campaign_id = ?", (campaign_id,)),
                ("DELETE FROM campaign_controls WHERE campaign_id = ?", (campaign_id,)),
                ("DELETE FROM campaign_item_records WHERE campaign_id = ?", (campaign_id,)),
                ("DELETE FROM campaign_parks WHERE campaign_id = ?", (campaign_id,)),
                ("DELETE FROM campaign_audit WHERE campaign_id = ?", (campaign_id,)),
                ("DELETE FROM campaign_usage WHERE campaign_id = ?", (campaign_id,)),
            ):
                cursor = await self._conn.execute(statement, parameters)
                total += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            await self._conn.commit()
        return total
