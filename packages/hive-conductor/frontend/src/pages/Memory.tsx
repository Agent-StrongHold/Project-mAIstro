import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import { Hex, PageHeader, StatCard, ConfirmDialog, useToast } from "../components/shared";

type Entry = {
  id: string; key: string; value: string; namespace: string;
  tags: string[]; embedding: string | null;
  created_at: string; updated_at: string;
  accessed_count: number; ttl_seconds: number | null;
};

export default function Memory() {
  const toast = useToast();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [sel, setSel] = useState<Entry | null>(null);
  const [nsFilter, setNsFilter] = useState("");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Entry | null>(null);
  const [form, setForm] = useState({ key: "", value: "", namespace: "general", tags: "" });
  const [editForm, setEditForm] = useState({ key: "", value: "", tags: "" });

  const load = useCallback(async () => {
    try { setEntries(await apiGet<Entry[]>("/v1/memory/entries")); } catch { /* */ }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function createEntry() {
    if (!form.key.trim()) return;
    try {
      await apiPost("/v1/memory/entries", { key: form.key.trim(), value: form.value, namespace: form.namespace, tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean) });
      setCreating(false);
      setForm({ key: "", value: "", namespace: "general", tags: "" });
      await load();
      toast("Entry created", "ok");
    } catch { toast("Failed to create", "error"); }
  }

  async function updateEntry() {
    if (!sel) return;
    try {
      const updated = await apiPut<Entry>(`/v1/memory/entries/${sel.id}`, { key: editForm.key || undefined, value: editForm.value || undefined, tags: editForm.tags ? editForm.tags.split(",").map((t) => t.trim()).filter(Boolean) : undefined });
      setSel(updated);
      setEditing(false);
      await load();
      toast("Entry updated", "ok");
    } catch { toast("Failed to update", "error"); }
  }

  async function deleteEntry(id: string) {
    try {
      await apiDelete(`/v1/memory/entries/${id}`);
      if (sel?.id === id) setSel(null);
      await load();
      toast("Entry deleted", "ok");
    } catch { toast("Failed to delete", "error"); }
    setDeleteTarget(null);
  }

  function startEdit(e: Entry) {
    setEditForm({ key: e.key, value: e.value, tags: e.tags.join(", ") });
    setEditing(true);
  }

  const namespaces = [...new Set(entries.map((e) => e.namespace))];
  const filtered = entries.filter((e) => {
    if (nsFilter && e.namespace !== nsFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return e.key.toLowerCase().includes(q) || e.value.toLowerCase().includes(q) || e.tags.some((t) => t.toLowerCase().includes(q));
    }
    return true;
  });

  return (
    <div style={{ display: "grid", gridTemplateColumns: sel ? "1fr 340px" : "1fr", gap: 0, minHeight: "calc(100vh - 60px)" }}>
      <ConfirmDialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} onConfirm={() => { if (deleteTarget) void deleteEntry(deleteTarget.id); }} title="Delete Entry" message={`Delete "${deleteTarget?.key ?? ""}"?`} />

      <div>
        <PageHeader
          title="Memory"
          subtitle={`${entries.length} entries — how the AI remembers things across conversations`}
          helpHref="/docs#memory"
          actions={<button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => setCreating(true)}>+ new</button>}
        />

        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <input className="input-field" placeholder="search keys, values, tags..." value={search} onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, maxWidth: 280 }} />
        </div>

        {creating && (
          <div className="card" style={{ borderLeft: "3px solid var(--accent)", marginBottom: 10 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
              <input className="input-field" placeholder="key" value={form.key} onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))} autoFocus style={{ flex: 1 }} />
              <input className="input-field" placeholder="namespace" value={form.namespace} onChange={(e) => setForm((f) => ({ ...f, namespace: e.target.value }))} style={{ width: 100 }} />
            </div>
            <textarea className="input-field" placeholder="value" value={form.value} onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} rows={2} style={{ resize: "vertical" }} />
            <input className="input-field" placeholder="tags (comma separated)" value={form.tags} onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))} style={{ marginTop: 4 }} />
            <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
              <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => void createEntry()} disabled={!form.key.trim()}>save</button>
              <button className="btn" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => setCreating(false)}>cancel</button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 4, marginBottom: 10, flexWrap: "wrap" }}>
          <span className={`hex-badge${!nsFilter ? " hex-badge-ok" : ""}`} style={{ cursor: "pointer" }} onClick={() => setNsFilter("")}>all ({entries.length})</span>
          {namespaces.map((ns) => (
            <span key={ns} className={`hex-badge${nsFilter === ns ? " hex-badge-ok" : ""}`} style={{ cursor: "pointer" }} onClick={() => setNsFilter(ns)}>
              {ns} ({entries.filter((e) => e.namespace === ns).length})
            </span>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {filtered.map((e) => (
            <div key={e.id} className="card" onClick={() => { setSel(e); setEditing(false); }} style={{ cursor: "pointer", borderColor: sel?.id === e.id ? "var(--accent)" : undefined }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center" }}>
                <div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--accent)" }}>{e.key}</div>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.value}</div>
                </div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  <Hex variant="muted">{e.namespace}</Hex>
                  {e.embedding ? <Hex variant="ok">embedded</Hex> : null}
                </div>
              </div>
              {e.tags.length > 0 && (
                <div style={{ display: "flex", gap: 3, marginTop: 4 }}>
                  {e.tags.map((t) => <Hex key={t} variant="">{t}</Hex>)}
                </div>
              )}
            </div>
          ))}
          {filtered.length === 0 && <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>no entries{search || nsFilter ? " match filter" : ""}</div>}
        </div>
      </div>

      {sel && (
        <div style={{ padding: "0 0 0 14px", borderLeft: "1.5px dashed var(--honey)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2 style={{ fontFamily: "var(--hand)", fontSize: 20, fontWeight: 700, margin: 0, wordBreak: "break-all" }}>{sel.key}</h2>
            <div style={{ display: "flex", gap: 4 }}>
              {!editing && <button className="btn" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => startEdit(sel)}>edit</button>}
              <button className="btn" style={{ fontSize: 9, padding: "2px 8px", borderColor: "var(--danger)", color: "var(--danger)" }} onClick={() => setDeleteTarget(sel)}>delete</button>
              <span className="btn" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => { setSel(null); setEditing(false); }}>close</span>
            </div>
          </div>

          {editing ? (
            <div style={{ marginTop: 10 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>KEY</label>
                <input className="input-field" value={editForm.key} onChange={(e) => setEditForm((f) => ({ ...f, key: e.target.value }))} />
                <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>VALUE</label>
                <textarea className="input-field" rows={4} value={editForm.value} onChange={(e) => setEditForm((f) => ({ ...f, value: e.target.value }))} />
                <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>TAGS (comma separated)</label>
                <input className="input-field" value={editForm.tags} onChange={(e) => setEditForm((f) => ({ ...f, tags: e.target.value }))} />
                <div style={{ display: "flex", gap: 4 }}>
                  <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => void updateEntry()}>save</button>
                  <button className="btn" style={{ fontSize: 9, padding: "2px 10px" }} onClick={() => setEditing(false)}>cancel</button>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, margin: "10px 0" }}>
                <StatCard label="Namespace" value={sel.namespace} />
                <StatCard label="Accessed" value={`${sel.accessed_count}x`} />
                <StatCard label="TTL" value={sel.ttl_seconds ? `${sel.ttl_seconds}s` : "none"} />
                <StatCard label="Embedding" value={sel.embedding ? "yes" : "no"} />
                <StatCard label="Created" value={new Date(sel.created_at).toLocaleDateString()} />
                <StatCard label="Updated" value={new Date(sel.updated_at).toLocaleDateString()} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 4, textTransform: "uppercase" }}>Value</div>
                <div style={{ padding: "8px 10px", background: "rgba(0,0,0,0.03)", borderRadius: 4, border: "1px solid var(--rule)", fontFamily: "var(--mono)", fontSize: 10, whiteSpace: "pre-wrap", wordBreak: "break-all", maxHeight: 200, overflow: "auto" }}>
                  {sel.value}
                </div>
              </div>
              {sel.tags.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginBottom: 4, textTransform: "uppercase" }}>Tags</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {sel.tags.map((t) => <Hex key={t}>{t}</Hex>)}
                  </div>
                </div>
              )}
            </>
          )}
          <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)" }}>id: {sel.id}</div>
        </div>
      )}
    </div>
  );
}
