// Backlog (#99) — board/list/detail editing over the canonical BacklogItem
// service (/v1/backlog). Every mutation carries the `expected_version` the
// UI last saw; a 409 means someone else moved first, and the conflict banner
// offers the current version to reload — the UI never force-overwrites.
//
// Non-authoritative until cutover (#102): this surface edits through the
// canonical service only, and says so in the banner below.

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPatch, fallbackMessage, ApiError } from "../lib/api";
import { Hex, PageHeader, Modal, useToast } from "../components/shared";

type AutonomyMode =
  | "autonomous"
  | "autonomous-with-promotion-approval"
  | "human-review-required"
  | "human-only";

type ProvenanceEntry = { actor: string; action: string; at: string; detail: Record<string, unknown> };

type BacklogItem = {
  id: string;
  title: string;
  description: string;
  status: "todo" | "in_progress" | "blocked" | "done";
  priority: number;
  rank: number;
  pinned: boolean;
  paused: boolean;
  paused_reason: string | null;
  archived: boolean;
  blocked_reason: string | null;
  parent_id: string | null;
  dependencies: string[];
  acceptance_evidence: string;
  source: string;
  risk: "low" | "medium" | "high";
  autonomy_mode: AutonomyMode;
  goal_id: string | null;
  goal_revision: number | null;
  owner_id: string;
  workspace_id: string | null;
  version: number;
  provenance: ProvenanceEntry[];
  created_at: string;
  updated_at: string;
};

type Authority = { canonical_service: string; ui_authoritative: boolean; cutover_issue: number };

type DetailRefs = { id: string; title: string; status: string; archived: boolean };

type BacklogDetail = {
  item: BacklogItem;
  dependencies: DetailRefs[];
  dependents: DetailRefs[];
  children: DetailRefs[];
  authority: Authority;
};

const STATUSES: BacklogItem["status"][] = ["todo", "in_progress", "blocked", "done"];
const AUTONOMY_MODES: AutonomyMode[] = [
  "autonomous",
  "autonomous-with-promotion-approval",
  "human-review-required",
  "human-only",
];
const RISKS: BacklogItem["risk"][] = ["low", "medium", "high"];

const monoStyle = { fontFamily: "var(--mono)", fontSize: 12 } as const;

type EditForm = {
  title: string;
  description: string;
  status: BacklogItem["status"];
  priority: number;
  risk: BacklogItem["risk"];
  autonomy_mode: AutonomyMode;
  acceptance_evidence: string;
  source: string;
  goal_id: string;
  goal_revision: string;
  dependencies: string[];
};

function toForm(item: BacklogItem): EditForm {
  return {
    title: item.title,
    description: item.description,
    status: item.status,
    priority: item.priority,
    risk: item.risk,
    autonomy_mode: item.autonomy_mode,
    acceptance_evidence: item.acceptance_evidence,
    source: item.source,
    goal_id: item.goal_id ?? "",
    goal_revision: item.goal_revision === null ? "" : String(item.goal_revision),
    dependencies: [...item.dependencies],
  };
}

export default function Backlog() {
  const toast = useToast();
  const [items, setItems] = useState<BacklogItem[]>([]);
  const [authority, setAuthority] = useState<Authority | null>(null);
  const [view, setView] = useState<"board" | "list">("board");
  const [showArchived, setShowArchived] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacklogDetail | null>(null);
  const [form, setForm] = useState<EditForm | null>(null);
  const [conflict, setConflict] = useState<BacklogItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({ title: "", description: "", source: "" });
  const [blocking, setBlocking] = useState<BacklogItem | null>(null);
  const [blockReason, setBlockReason] = useState("");
  const [decomposing, setDecomposing] = useState<BacklogItem | null>(null);
  const [decomposeTitles, setDecomposeTitles] = useState("");

  const load = useCallback(async () => {
    try {
      const body = await apiGet<{ items: BacklogItem[]; authority: Authority }>(
        "/v1/backlog?include_archived=true",
      );
      setItems(body.items);
      setAuthority(body.authority);
    } catch (err) {
      toast(fallbackMessage(err instanceof ApiError ? err.status : 0), "error");
    }
  }, [toast]);

  // Initial fetch. Inline IIFE (the WorkspaceContext idiom): async work in an
  // effect with an unmount guard, rather than calling the named `load`
  // directly, which react-hooks/set-state-in-effect flags — and this file is
  // not allowed to grow the held warning count.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = await apiGet<{ items: BacklogItem[]; authority: Authority }>(
          "/v1/backlog?include_archived=true",
        );
        if (cancelled) return;
        setItems(body.items);
        setAuthority(body.authority);
      } catch {
        // The banner-less empty board is the degraded state; a refresh via
        // the load path reports the transport error when the user acts.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const openDetail = useCallback(
    async (id: string) => {
      setConflict(null);
      setDetailId(id);
      try {
        const d = await apiGet<BacklogDetail>(`/v1/backlog/${id}`);
        setDetail(d);
        setForm(toForm(d.item));
      } catch {
        toast("Couldn't load that item", "error");
        setDetailId(null);
      }
    },
    [toast],
  );

  function isConflict(err: unknown): boolean {
    return err instanceof ApiError && err.status === 409;
  }

  async function saveEdits() {
    if (!detail || !form) return;
    const changes: Record<string, unknown> = {
      title: form.title.trim(),
      description: form.description,
      status: form.status,
      priority: Number(form.priority),
      risk: form.risk,
      autonomy_mode: form.autonomy_mode,
      acceptance_evidence: form.acceptance_evidence,
      source: form.source,
      dependencies: form.dependencies,
    };
    if (form.goal_id.trim()) {
      changes.goal_id = form.goal_id.trim();
      const rev = Number.parseInt(form.goal_revision, 10);
      changes.goal_revision = Number.isFinite(rev) ? rev : null;
    } else {
      changes.goal_id = null;
      changes.goal_revision = null;
    }
    try {
      const updated = await apiPatch<BacklogItem>(`/v1/backlog/${detail.item.id}`, {
        expected_version: detail.item.version,
        changes,
      });
      setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
      setConflict(null);
      toast("Saved", "ok");
      void openDetail(updated.id);
    } catch (err) {
      if (isConflict(err)) {
        await showConflict(detail.item.id);
        return;
      }
      toast(fallbackMessage(err instanceof ApiError ? err.status : 0), "error");
    }
  }

  // A 409 means someone else saved first. The current copy is refetched and
  // offered in the conflict banner — the editor can re-apply onto it or walk
  // away; the UI never force-overwrites.
  async function showConflict(id: string) {
    try {
      const d = await apiGet<BacklogDetail>(`/v1/backlog/${id}`);
      setDetail(d);
      setConflict(d.item);
      toast("This item changed while you were editing", "error");
    } catch {
      toast("This item changed while you were editing — reload the board", "error");
      void load();
    }
  }

  async function moveSibling(item: BacklogItem, dir: -1 | 1) {
    const peers = visible
      .filter((it) => it.status === item.status && !it.archived)
      .sort((a, b) => a.priority - b.priority || a.rank - b.rank);
    const at = peers.findIndex((it) => it.id === item.id);
    const target = at + dir;
    if (at === -1 || target < 0 || target >= peers.length) return;
    const neighbour = peers[target].rank;
    const beyond = peers[target + dir]?.rank ?? neighbour + dir * 2;
    const newRank = (neighbour + beyond) / 2;
    try {
      const updated = await apiPost<BacklogItem>(`/v1/backlog/${item.id}/reorder`, {
        expected_version: item.version,
        rank: newRank,
      });
      setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
    } catch (err) {
      if (isConflict(err)) {
        toast("That item moved elsewhere first — reloading the board", "error");
        void load();
        return;
      }
      toast(fallbackMessage(err instanceof ApiError ? err.status : 0), "error");
    }
  }

  async function createItem() {
    if (!createForm.title.trim()) return;
    try {
      const created = await apiPost<BacklogItem>("/v1/backlog", {
        title: createForm.title.trim(),
        description: createForm.description,
        source: createForm.source,
      });
      setItems((prev) => [...prev, created]);
      setCreating(false);
      setCreateForm({ title: "", description: "", source: "" });
      toast("Backlog item created", "ok");
    } catch (err) {
      toast(fallbackMessage(err instanceof ApiError ? err.status : 0), "error");
    }
  }

  async function decompose() {
    if (!decomposing) return;
    const children = decomposeTitles
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean)
      .map((title) => ({ title }));
    if (!children.length) return;
    try {
      await apiPost(`/v1/backlog/${decomposing.id}/decompose`, {
        expected_version: decomposing.version,
        children,
      });
      setDecomposing(null);
      setDecomposeTitles("");
      toast("Decomposed into " + children.length + " sub-items", "ok");
      void load();
    } catch (err) {
      if (isConflict(err)) {
        toast("That item moved elsewhere first — reloading", "error");
        void load();
        return;
      }
      toast(fallbackMessage(err instanceof ApiError ? err.status : 0), "error");
    }
  }

  const visible = items.filter((it) => (showArchived ? true : !it.archived));
  const byStatus = (status: BacklogItem["status"]) =>
    visible
      .filter((it) => it.status === status)
      .sort((a, b) => a.priority - b.priority || a.rank - b.rank);

  function cardMeta(it: BacklogItem) {
    return (
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
        <Hex variant={it.priority === 1 ? "danger" : it.priority <= 2 ? "warn" : "muted"}>P{it.priority}</Hex>
        <Hex variant={it.risk === "high" ? "danger" : it.risk === "medium" ? "warn" : "ok"}>{it.risk}</Hex>
        <Hex variant="purple">{it.autonomy_mode === "human-only" ? "human-only" : it.autonomy_mode.replace("autonomous", "auto")}</Hex>
        {it.pinned && <Hex variant="accent">pinned</Hex>}
        {it.paused && <Hex variant="warn">paused</Hex>}
        {it.dependencies.length > 0 && <Hex variant="muted">deps: {it.dependencies.length}</Hex>}
      </div>
    );
  }

  function cardActions(it: BacklogItem) {
    return (
      <div style={{ display: "flex", gap: 3, marginTop: 6, flexWrap: "wrap" }}>
        <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => void openDetail(it.id)}>
          inspect
        </button>
        {it.status === "blocked" ? (
          <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => void detailAct(it, "/unblock")}>
            unblock
          </button>
        ) : (
          <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => { setBlocking(it); setBlockReason(""); }}>
            block
          </button>
        )}
        <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => void detailAct(it, it.pinned ? "/unpin" : "/pin")}>
          {it.pinned ? "unpin" : "pin"}
        </button>
        <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => void detailAct(it, it.paused ? "/resume" : "/pause", it.paused ? undefined : "paused from the board")}>
          {it.paused ? "resume" : "pause"}
        </button>
        <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => { setDecomposing(it); setDecomposeTitles(""); }}>
          decompose
        </button>
        <button className="btn" style={{ fontSize: 11, padding: "1px 6px", borderColor: "var(--danger)", color: "var(--danger)" }} onClick={() => void detailAct(it, it.archived ? "/restore" : "/archive")}>
          {it.archived ? "restore" : "archive"}
        </button>
      </div>
    );
  }

  // Card actions run against the item's last-seen version; a 409 reloads the
  // board rather than overwriting whoever moved first.
  async function detailAct(it: BacklogItem, path: string, reason?: string) {
    try {
      const updated = await apiPost<BacklogItem>(`/v1/backlog/${it.id}${path}`, {
        expected_version: it.version,
        ...(reason !== undefined ? { reason } : {}),
      });
      setItems((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      if (detail?.item.id === it.id) void openDetail(it.id);
    } catch (err) {
      if (isConflict(err)) {
        toast("That item moved elsewhere first — reloading the board", "error");
        void load();
        if (detailId === it.id) void openDetail(it.id);
        return;
      }
      toast(fallbackMessage(err instanceof ApiError ? err.status : 0), "error");
    }
  }

  return (
    <div>
      <PageHeader
        title="Backlog"
        subtitle={`${visible.filter((i) => !i.archived).length} items — board, list and detail editing without touching Markdown or YAML`}
        actions={
          <button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 8px" }} onClick={() => setCreating(true)}>
            + item
          </button>
        }
      />

      {authority && !authority.ui_authoritative && (
        <div
          style={{
            border: "1px dashed var(--warn)",
            padding: "6px 10px",
            marginBottom: 10,
            fontFamily: "var(--mono)",
            fontSize: 12,
            color: "var(--warn)",
          }}
        >
          Preview surface — this board edits through the canonical backlog service
          ({authority.canonical_service}) and is not authoritative until cutover
          (#{authority.cutover_issue}).
        </div>
      )}

      {creating && (
        <div className="card" style={{ borderLeft: "3px solid var(--accent)", marginBottom: 10 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input className="input-field" placeholder="title" value={createForm.title} onChange={(e) => setCreateForm((f) => ({ ...f, title: e.target.value }))} autoFocus />
            <input className="input-field" placeholder="description" value={createForm.description} onChange={(e) => setCreateForm((f) => ({ ...f, description: e.target.value }))} />
            <input className="input-field" placeholder="source (where did this work come from?)" value={createForm.source} onChange={(e) => setCreateForm((f) => ({ ...f, source: e.target.value }))} />
            <div style={{ display: "flex", gap: 4 }}>
              <button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => void createItem()} disabled={!createForm.title.trim()}>
                create
              </button>
              <button className="btn" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => setCreating(false)}>
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--rule)", marginBottom: 10 }}>
        {(["board", "list"] as const).map((t) => (
          <div
            key={t}
            onClick={() => setView(t)}
            style={{ padding: "7px 16px", ...monoStyle, cursor: "pointer", borderBottom: view === t ? "2px solid var(--accent)" : "2px solid transparent", color: view === t ? "var(--ink)" : "var(--pencil)", textTransform: "capitalize" }}
          >
            {t}
          </div>
        ))}
        <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, ...monoStyle, color: "var(--pencil)", cursor: "pointer" }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          show archived
        </label>
      </div>

      {view === "board" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(160px, 1fr))", gap: 10 }}>
          {STATUSES.map((status) => (
            <div key={status}>
              <div style={{ ...monoStyle, color: "var(--pencil)", fontWeight: 600, marginBottom: 6, textTransform: "uppercase" }}>
                {status} <span style={{ opacity: 0.6 }}>({byStatus(status).length})</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {byStatus(status).map((it) => (
                  <div key={it.id} className="card" style={{ padding: 8, opacity: it.archived ? 0.55 : 1, borderLeft: it.pinned ? "3px solid var(--accent)" : undefined }}>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 14, fontWeight: 600, cursor: "pointer" }} onClick={() => void openDetail(it.id)}>
                      {it.title}
                    </div>
                    {it.blocked_reason && <div style={{ ...monoStyle, color: "var(--danger)", marginTop: 2 }}>blocked: {it.blocked_reason}</div>}
                    {it.paused && it.paused_reason && <div style={{ ...monoStyle, color: "var(--warn)", marginTop: 2 }}>paused: {it.paused_reason}</div>}
                    {cardMeta(it)}
                    {cardActions(it)}
                  </div>
                ))}
                {byStatus(status).length === 0 && (
                  <div style={{ ...monoStyle, color: "var(--pencil)", opacity: 0.6, padding: "8px 4px" }}>empty</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {view === "list" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {visible
            .slice()
            .sort((a, b) => a.priority - b.priority || a.rank - b.rank)
            .map((it) => (
              <div key={it.id} className="card" style={{ display: "flex", alignItems: "flex-start", gap: 10, opacity: it.archived ? 0.55 : 1 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <button className="btn" style={{ fontSize: 10, padding: "0 5px" }} title="move up" onClick={() => void moveSibling(it, -1)}>
                    ↑
                  </button>
                  <button className="btn" style={{ fontSize: 10, padding: "0 5px" }} title="move down" onClick={() => void moveSibling(it, 1)}>
                    ↓
                  </button>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 600, cursor: "pointer" }} onClick={() => void openDetail(it.id)}>
                      {it.title}
                    </span>
                    <span style={{ ...monoStyle, color: "var(--pencil)" }}>{it.status}</span>
                    <span style={{ ...monoStyle, color: "var(--pencil)", opacity: 0.7 }}>v{it.version}</span>
                  </div>
                  {it.description && <div style={{ fontFamily: "var(--hand)", fontSize: 12, color: "var(--pencil)", margin: "2px 0" }}>{it.description}</div>}
                  {cardMeta(it)}
                  {cardActions(it)}
                </div>
              </div>
            ))}
          {visible.length === 0 && !creating && (
            <div style={{ fontFamily: "var(--hand)", fontSize: 16, color: "var(--pencil)", padding: 20 }}>
              backlog is empty — create the first item
            </div>
          )}
        </div>
      )}

      <Modal open={detailId !== null} onClose={() => { setDetailId(null); setConflict(null); }} title={detail?.item.title ?? "Backlog item"} wide>
        {detail && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {conflict && (
              <div style={{ border: "1px solid var(--danger)", padding: 8, ...monoStyle, color: "var(--danger)" }}>
                Version conflict: someone saved v{conflict.version} while you were editing. Your change
                was not applied.{" "}
                <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => { setForm(toForm(conflict)); setConflict(null); toast("Loaded the current version — re-apply your edit", "ok"); }}>
                  load current version
                </button>
              </div>
            )}

            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Hex variant="accent">{detail.item.status}</Hex>
              <Hex variant="muted">v{detail.item.version}</Hex>
              <Hex variant="muted">owner: {detail.item.owner_id}</Hex>
              {detail.item.goal_id && <Hex variant="purple">goal: {detail.item.goal_id} @ r{detail.item.goal_revision ?? "?"}</Hex>}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div style={{ ...monoStyle, color: "var(--pencil)", marginBottom: 3 }}>SOURCE</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 13 }}>{detail.item.source || "—"}</div>
                <div style={{ ...monoStyle, color: "var(--pencil)", margin: "8px 0 3px" }}>ACCEPTANCE EVIDENCE</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 13, whiteSpace: "pre-wrap" }}>{detail.item.acceptance_evidence || "—"}</div>
                <div style={{ ...monoStyle, color: "var(--pencil)", margin: "8px 0 3px" }}>DEPENDS ON</div>
                {detail.dependencies.length === 0 && <div style={{ fontFamily: "var(--hand)", fontSize: 13 }}>—</div>}
                {detail.dependencies.map((d) => (
                  <div key={d.id} style={{ fontFamily: "var(--hand)", fontSize: 13 }}>
                    ↳ {d.title} <span style={{ color: "var(--pencil)" }}>({d.status})</span>
                  </div>
                ))}
                {detail.dependents.length > 0 && (
                  <>
                    <div style={{ ...monoStyle, color: "var(--pencil)", margin: "8px 0 3px" }}>BLOCKS</div>
                    {detail.dependents.map((d) => (
                      <div key={d.id} style={{ fontFamily: "var(--hand)", fontSize: 13 }}>
                        ⇗ {d.title}
                      </div>
                    ))}
                  </>
                )}
                {detail.children.length > 0 && (
                  <>
                    <div style={{ ...monoStyle, color: "var(--pencil)", margin: "8px 0 3px" }}>SUB-ITEMS</div>
                    {detail.children.map((d) => (
                      <div key={d.id} style={{ fontFamily: "var(--hand)", fontSize: 13 }}>
                        ⊞ {d.title} <span style={{ color: "var(--pencil)" }}>({d.status})</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
              <div>
                <div style={{ ...monoStyle, color: "var(--pencil)", marginBottom: 3 }}>PROVENANCE</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 220, overflowY: "auto" }}>
                  {detail.item.provenance
                    .slice()
                    .reverse()
                    .map((p, i) => (
                      <div key={i} style={{ ...monoStyle, color: "var(--pencil)" }}>
                        <span style={{ color: "var(--ink)" }}>{p.action}</span> — {p.actor} —{" "}
                        {new Date(p.at).toLocaleString()}
                      </div>
                    ))}
                </div>
              </div>
            </div>

            <div style={{ borderTop: "1px solid var(--rule)", paddingTop: 8 }}>
              <div style={{ ...monoStyle, color: "var(--pencil)", marginBottom: 6 }}>EDIT</div>
              {form && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <input className="input-field" value={form.title} onChange={(e) => setForm((f) => (f ? { ...f, title: e.target.value } : f))} />
                  <textarea className="input-field" rows={2} placeholder="description" value={form.description} onChange={(e) => setForm((f) => (f ? { ...f, description: e.target.value } : f))} />
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <select className="input-field" style={{ width: 140 }} value={form.status} onChange={(e) => setForm((f) => (f ? { ...f, status: e.target.value as BacklogItem["status"] } : f))}>
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                    <select className="input-field" style={{ width: 90 }} value={form.priority} onChange={(e) => setForm((f) => (f ? { ...f, priority: Number(e.target.value) } : f))}>
                      {[1, 2, 3, 4, 5].map((p) => (
                        <option key={p} value={p}>
                          P{p}
                        </option>
                      ))}
                    </select>
                    <select className="input-field" style={{ width: 100 }} value={form.risk} onChange={(e) => setForm((f) => (f ? { ...f, risk: e.target.value as BacklogItem["risk"] } : f))}>
                      {RISKS.map((r) => (
                        <option key={r} value={r}>
                          risk: {r}
                        </option>
                      ))}
                    </select>
                    <select className="input-field" style={{ width: 250 }} value={form.autonomy_mode} onChange={(e) => setForm((f) => (f ? { ...f, autonomy_mode: e.target.value as AutonomyMode } : f))}>
                      {AUTONOMY_MODES.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                  <input className="input-field" placeholder="source" value={form.source} onChange={(e) => setForm((f) => (f ? { ...f, source: e.target.value } : f))} />
                  <textarea className="input-field" rows={2} placeholder="acceptance evidence (how do we know this is done?)" value={form.acceptance_evidence} onChange={(e) => setForm((f) => (f ? { ...f, acceptance_evidence: e.target.value } : f))} />
                  <div style={{ display: "flex", gap: 6 }}>
                    <input className="input-field" style={{ flex: 1 }} placeholder="linked goal id (optional)" value={form.goal_id} onChange={(e) => setForm((f) => (f ? { ...f, goal_id: e.target.value } : f))} />
                    <input className="input-field" style={{ width: 90 }} placeholder="rev" value={form.goal_revision} onChange={(e) => setForm((f) => (f ? { ...f, goal_revision: e.target.value } : f))} />
                  </div>
                  {items.filter((it) => it.id !== detail.item.id && !it.archived).length > 0 && (
                    <div>
                      <div style={{ ...monoStyle, color: "var(--pencil)", marginBottom: 3 }}>DEPENDS ON</div>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {items
                          .filter((it) => it.id !== detail.item.id && !it.archived)
                          .map((it) => (
                            <span
                              key={it.id}
                              className={`hex-badge${form.dependencies.includes(it.id) ? " hex-badge-accent" : ""}`}
                              style={{ cursor: "pointer" }}
                              onClick={() =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        dependencies: f.dependencies.includes(it.id)
                                          ? f.dependencies.filter((d) => d !== it.id)
                                          : [...f.dependencies, it.id],
                                      }
                                    : f,
                                )
                              }
                            >
                              {it.title}
                            </span>
                          ))}
                      </div>
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 4 }}>
                    <button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => void saveEdits()}>
                      save (v{detail.item.version})
                    </button>
                    <button className="btn" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => { setDetailId(null); setConflict(null); }}>
                      close
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={blocking !== null} onClose={() => setBlocking(null)} title="Block item">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ ...monoStyle, color: "var(--pencil)" }}>
            Blocking parks this item with evidence. The reason is required.
          </div>
          <input className="input-field" placeholder="why is this blocked?" value={blockReason} onChange={(e) => setBlockReason(e.target.value)} autoFocus />
          <div style={{ display: "flex", gap: 4 }}>
            <button
              className="btn btn-accent"
              style={{ fontSize: 12, padding: "2px 10px" }}
              disabled={!blockReason.trim()}
              onClick={() => {
                const target = blocking;
                const reason = blockReason.trim();
                setBlocking(null);
                setBlockReason("");
                if (target) void detailAct(target, "/block", reason);
              }}
            >
              block
            </button>
            <button className="btn" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => setBlocking(null)}>
              cancel
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={decomposing !== null} onClose={() => setDecomposing(null)} title="Decompose item">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ ...monoStyle, color: "var(--pencil)" }}>One sub-item per line; the parent stays as the umbrella.</div>
          <textarea className="input-field" rows={4} placeholder={"first sub-item\nsecond sub-item"} value={decomposeTitles} onChange={(e) => setDecomposeTitles(e.target.value)} autoFocus />
          <div style={{ display: "flex", gap: 4 }}>
            <button className="btn btn-accent" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => void decompose()}>
              decompose
            </button>
            <button className="btn" style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => setDecomposing(null)}>
              cancel
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
