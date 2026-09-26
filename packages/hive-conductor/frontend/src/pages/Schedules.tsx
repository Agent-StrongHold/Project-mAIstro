import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import { Hex, PageHeader, StatCard, ConfirmDialog, useToast } from "../components/shared";
import { useWorkspaces } from "../context/WorkspaceContext";
import { Switch } from "../components/Switch";
import { TabList, TabPanel } from "../components/TabList";

type Schedule = {
  id: string; name: string; description: string; cron_expression: string;
  mission_template_id: string | null; enabled: boolean;
  last_run: string | null; next_run: string | null;
  created_at: string; updated_at: string;
};

const CRON_PRESETS = [
  { label: "Every hour", cron: "0 * * * *" },
  { label: "Every 6 hours", cron: "0 */6 * * *" },
  { label: "Daily midnight", cron: "0 0 * * *" },
  { label: "Daily 3am", cron: "0 3 * * *" },
  { label: "Weekly Sunday", cron: "0 0 * * 0" },
  { label: "Monthly 1st", cron: "0 0 1 * *" },
];

const TABS = [{ id: "schedules", label: "Schedules" }, { id: "history", label: "History" }] as const;

export default function Schedules() {
  const toast = useToast();
  const { activeWorkspaceId, ready: workspacesReady } = useWorkspaces();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [tab, setTab] = useState<"schedules" | "history">("schedules");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Schedule | null>(null);
  const [form, setForm] = useState({ name: "", description: "", cron_expression: "0 * * * *", mission_template_id: "" });
  const [editForm, setEditForm] = useState({ name: "", description: "", cron_expression: "" });

  const load = useCallback(async () => { try { setSchedules(await apiGet<Schedule[]>("/v1/schedules")); } catch { /* */ } }, []);
  useEffect(() => { void load(); }, [load]);

  async function createSchedule() {
    if (!form.name.trim()) return;
    if (!workspacesReady || !activeWorkspaceId) {
      toast("Select a Workspace before creating a schedule", "error");
      return;
    }
    try {
      const created = await apiPost<Schedule>("/v1/schedules", { workspace_id: activeWorkspaceId, name: form.name.trim(), description: form.description.trim(), cron_expression: form.cron_expression, mission_template_id: form.mission_template_id || null, enabled: true });
      setSchedules((prev) => [...prev, created]);
      setCreating(false);
      setForm({ name: "", description: "", cron_expression: "0 * * * *", mission_template_id: "" });
      toast("Schedule created", "ok");
    } catch { toast("Failed to create schedule", "error"); }
  }

  // One mutation, one request (matches WorkspaceContext.tsx's #1422 fix): the
  // response is the changed record, so it is patched into local state rather
  // than followed by a refetch of the whole collection.
  async function updateSchedule() {
    if (!editing) return;
    try {
      const updated = await apiPut<Schedule>(`/v1/schedules/${editing.id}`, editForm);
      setSchedules((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      setEditing(null);
      toast("Schedule updated", "ok");
    } catch { toast("Failed to update schedule", "error"); }
  }

  async function toggleSchedule(s: Schedule) {
    try {
      const updated = await apiPut<Schedule>(`/v1/schedules/${s.id}`, { enabled: !s.enabled });
      setSchedules((prev) => prev.map((sc) => (sc.id === updated.id ? updated : sc)));
      toast(s.enabled ? "Disabled" : "Enabled", "ok");
    } catch { toast("Failed to toggle", "error"); }
  }

  async function deleteSchedule(id: string) {
    try {
      await apiDelete(`/v1/schedules/${id}`);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
      toast("Schedule deleted", "ok");
    } catch { toast("Failed to delete", "error"); }
    setDeleteTarget(null);
  }

  async function runNow(s: Schedule) {
    try {
      const updated = await apiPost<Schedule>(`/v1/schedules/${s.id}/run`);
      setSchedules((prev) => prev.map((sc) => (sc.id === updated.id ? updated : sc)));
      toast("Schedule triggered", "ok");
    } catch { toast("Failed to trigger", "error"); }
  }

  function startEdit(s: Schedule) {
    setEditForm({ name: s.name, description: s.description, cron_expression: s.cron_expression });
    setEditing(s);
  }

  return (
    <div>
      <ConfirmDialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} onConfirm={() => { if (deleteTarget) void deleteSchedule(deleteTarget.id); }} title="Delete Schedule" message={`Delete "${deleteTarget?.name ?? ""}"?`} />

      <PageHeader
        title="Schedules"
        subtitle={`${schedules.filter((s) => s.enabled).length}/${schedules.length} active — run tasks automatically on a timer`}
        helpHref="/docs#schedules"
        actions={<button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 8px" }} onClick={() => setCreating(true)}>+ new</button>}
      />
      <TabList label="Schedule views" idPrefix="schedules" tabs={TABS} selected={tab} onSelect={setTab} style={{ marginBottom: -8 }} />

      <TabPanel idPrefix="schedules" id="schedules" selected={tab === "schedules"}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
          {creating && (
            <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <input className="input-field" placeholder="schedule name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} autoFocus />
                <input className="input-field" placeholder="description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
                <div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)", marginBottom: 3 }}>PRESETS</div>
                  <div role="group" aria-label="Cron presets" style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {CRON_PRESETS.map((p) => (
                      <button key={p.cron} type="button" aria-pressed={form.cron_expression === p.cron} className={`hex-badge${form.cron_expression === p.cron ? " hex-badge-accent" : ""}`} style={{ cursor: "pointer", boxShadow: "none", transform: "none" }} onClick={() => setForm((f) => ({ ...f, cron_expression: p.cron }))}>{p.label}</button>
                    ))}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>CRON</span>
                  <input className="input-field" aria-label="Cron expression" style={{ flex: 1, fontFamily: "var(--mono)" }} value={form.cron_expression} onChange={(e) => setForm((f) => ({ ...f, cron_expression: e.target.value }))} />
                </div>
                <input className="input-field" placeholder="mission template ID (optional)" value={form.mission_template_id} onChange={(e) => setForm((f) => ({ ...f, mission_template_id: e.target.value }))} />
                <div style={{ display: "flex", gap: 4 }}>
                  <button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => void createSchedule()} disabled={!form.name.trim()}>create</button>
                  <button className="btn" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => setCreating(false)}>cancel</button>
                </div>
              </div>
            </div>
          )}

          {editing && (
            <div className="card" style={{ borderLeft: "3px solid var(--warn)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--warn)", marginBottom: 6, fontWeight: 600 }}>EDITING: {editing.name}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <input className="input-field" value={editForm.name} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
                <input className="input-field" value={editForm.description} onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))} />
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--pencil)" }}>CRON</span>
                  <input className="input-field" aria-label="Cron expression" style={{ flex: 1, fontFamily: "var(--mono)" }} value={editForm.cron_expression} onChange={(e) => setEditForm((f) => ({ ...f, cron_expression: e.target.value }))} />
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  <button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => void updateSchedule()}>save</button>
                  <button className="btn" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => setEditing(null)}>cancel</button>
                </div>
              </div>
            </div>
          )}

          {schedules.map((s) => (
            <div key={s.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 17, fontWeight: 600 }}>{s.name}</div>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "2px 0 4px" }}>{s.description}</div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>{s.cron_expression}</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 6, marginTop: 8 }}>
                    <StatCard label="Last Run" value={s.last_run ? new Date(s.last_run).toLocaleString() : "never"} />
                    <StatCard label="Next Run" value={s.next_run ? new Date(s.next_run).toLocaleString() : "pending"} />
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, marginLeft: 12 }}>
                  <Switch checked={s.enabled} onChange={() => void toggleSchedule(s)} label={`Enable schedule ${s.name}`} />
                  <Hex variant={s.enabled ? "ok" : "muted"}>{s.enabled ? "active" : "off"}</Hex>
                  <div style={{ display: "flex", gap: 3 }}>
                    <button className="btn" style={{ fontSize: 12, padding: "1px 6px" }} onClick={() => void runNow(s)}>run now</button>
                    <button className="btn" style={{ fontSize: 12, padding: "1px 6px" }} onClick={() => startEdit(s)}>edit</button>
                    <button className="btn" style={{ fontSize: 12, padding: "1px 6px", borderColor: "var(--danger)", color: "var(--danger)", opacity: 0.5 }} onClick={() => setDeleteTarget(s)}>delete</button>
                  </div>
                </div>
              </div>
            </div>
          ))}
          {schedules.length === 0 && !creating && <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>no schedules configured</div>}
        </div>
      </TabPanel>

      <TabPanel idPrefix="schedules" id="history" selected={tab === "history"}>
        <div style={{ marginTop: 14, fontFamily: "var(--hand)", fontSize: 14, color: "var(--pencil)", padding: 20 }}>
          execution history will appear here when runs complete
        </div>
      </TabPanel>
    </div>
  );
}
