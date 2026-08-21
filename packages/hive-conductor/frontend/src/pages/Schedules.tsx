import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import { Hex, PageHeader, StatCard, ConfirmDialog, useToast } from "../components/shared";

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

export default function Schedules() {
  const toast = useToast();
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
    try {
      await apiPost<Schedule>("/v1/schedules", { name: form.name.trim(), description: form.description.trim(), cron_expression: form.cron_expression, mission_template_id: form.mission_template_id || null, enabled: true });
      setCreating(false);
      setForm({ name: "", description: "", cron_expression: "0 * * * *", mission_template_id: "" });
      await load();
      toast("Schedule created", "ok");
    } catch { toast("Failed to create schedule", "error"); }
  }

  async function updateSchedule() {
    if (!editing) return;
    try {
      await apiPut<Schedule>(`/v1/schedules/${editing.id}`, editForm);
      setEditing(null);
      await load();
      toast("Schedule updated", "ok");
    } catch { toast("Failed to update schedule", "error"); }
  }

  async function toggleSchedule(s: Schedule) {
    try {
      await apiPut<Schedule>(`/v1/schedules/${s.id}`, { enabled: !s.enabled });
      await load();
      toast(s.enabled ? "Disabled" : "Enabled", "ok");
    } catch { toast("Failed to toggle", "error"); }
  }

  async function deleteSchedule(id: string) {
    try {
      await apiDelete(`/v1/schedules/${id}`);
      await load();
      toast("Schedule deleted", "ok");
    } catch { toast("Failed to delete", "error"); }
    setDeleteTarget(null);
  }

  async function runNow(s: Schedule) {
    try {
      await apiPost<Schedule>(`/v1/schedules/${s.id}/run`);
      await load();
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
        actions={<button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => setCreating(true)}>+ new</button>}
      />
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--rule)", marginBottom: -8 }}>
        {(["schedules", "history"] as const).map((t) => (
          <div key={t} onClick={() => setTab(t)} style={{ padding: "7px 16px", fontFamily: "var(--mono)", fontSize: 10, cursor: "pointer", borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent", color: tab === t ? "var(--ink)" : "var(--pencil)", textTransform: "capitalize" }}>{t}</div>
        ))}
      </div>

      {tab === "schedules" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
          {creating && (
            <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <input className="input-field" placeholder="schedule name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} autoFocus />
                <input className="input-field" placeholder="description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
                <div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 3 }}>PRESETS</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {CRON_PRESETS.map((p) => (
                      <span key={p.cron} className={`hex-badge${form.cron_expression === p.cron ? " hex-badge-accent" : ""}`} style={{ cursor: "pointer" }} onClick={() => setForm((f) => ({ ...f, cron_expression: p.cron }))}>{p.label}</span>
                    ))}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>CRON</span>
                  <input className="input-field" style={{ flex: 1, fontFamily: "var(--mono)" }} value={form.cron_expression} onChange={(e) => setForm((f) => ({ ...f, cron_expression: e.target.value }))} />
                </div>
                <input className="input-field" placeholder="mission template ID (optional)" value={form.mission_template_id} onChange={(e) => setForm((f) => ({ ...f, mission_template_id: e.target.value }))} />
                <div style={{ display: "flex", gap: 4 }}>
                  <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => void createSchedule()} disabled={!form.name.trim()}>create</button>
                  <button className="btn" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => setCreating(false)}>cancel</button>
                </div>
              </div>
            </div>
          )}

          {editing && (
            <div className="card" style={{ borderLeft: "3px solid var(--warn)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--warn)", marginBottom: 6, fontWeight: 600 }}>EDITING: {editing.name}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <input className="input-field" value={editForm.name} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
                <input className="input-field" value={editForm.description} onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))} />
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>CRON</span>
                  <input className="input-field" style={{ flex: 1, fontFamily: "var(--mono)" }} value={editForm.cron_expression} onChange={(e) => setEditForm((f) => ({ ...f, cron_expression: e.target.value }))} />
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => void updateSchedule()}>save</button>
                  <button className="btn" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => setEditing(null)}>cancel</button>
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
                  <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--accent)", fontWeight: 600 }}>{s.cron_expression}</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 6, marginTop: 8 }}>
                    <StatCard label="Last Run" value={s.last_run ? new Date(s.last_run).toLocaleString() : "never"} />
                    <StatCard label="Next Run" value={s.next_run ? new Date(s.next_run).toLocaleString() : "pending"} />
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, marginLeft: 12 }}>
                  <div className={`toggle${s.enabled ? " on" : ""}`} onClick={() => void toggleSchedule(s)} style={{ cursor: "pointer" }} />
                  <Hex variant={s.enabled ? "ok" : "muted"}>{s.enabled ? "active" : "off"}</Hex>
                  <div style={{ display: "flex", gap: 3 }}>
                    <button className="btn" style={{ fontSize: 8, padding: "1px 6px" }} onClick={() => void runNow(s)}>run now</button>
                    <button className="btn" style={{ fontSize: 8, padding: "1px 6px" }} onClick={() => startEdit(s)}>edit</button>
                    <button className="btn" style={{ fontSize: 8, padding: "1px 6px", borderColor: "var(--danger)", color: "var(--danger)", opacity: 0.5 }} onClick={() => setDeleteTarget(s)}>delete</button>
                  </div>
                </div>
              </div>
            </div>
          ))}
          {schedules.length === 0 && !creating && <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>no schedules configured</div>}
        </div>
      )}

      {tab === "history" && (
        <div style={{ marginTop: 14, fontFamily: "var(--hand)", fontSize: 14, color: "var(--pencil)", padding: 20 }}>
          execution history will appear here when runs complete
        </div>
      )}
    </div>
  );
}
