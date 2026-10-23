import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../lib/api";
import type { AuditEntry, AuditPage, AuditRetention, AuditSeverity } from "../api/models";
import {
  Card,
  EmptyState,
  LoadingSpinner,
  Modal,
  PageHeader,
  SearchInput,
  useToast,
} from "../components/shared";

const PAGE_SIZE = 100;
// Keep a sliding client window, not the entire cursor walk. Virtualization
// bounds mounted DOM nodes; this cap also bounds JavaScript heap as a user
// reads an arbitrarily large audit corpus.
const MAX_LOADED_ENTRIES = PAGE_SIZE * 5;

// Windowed rendering: only the visible slice of rows (+overscan) is mounted.
const ROW_HEIGHT = 44;
const VIEWPORT_HEIGHT = 560;
const OVERSCAN_ROWS = 8;

const ACTION_OPTIONS = [
  { value: "", label: "All Actions" },
  { value: "login", label: "Login" },
  { value: "elevate", label: "Elevate" },
  { value: "revoke", label: "Revoke" },
  { value: "dag_run", label: "DAG Run" },
  { value: "agent_create", label: "Agent Create" },
  { value: "gate_block", label: "Gate Block" },
  { value: "scan", label: "Scan" },
  { value: "config_change", label: "Config Change" },
];

const SEVERITY_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "info", label: "Info" },
  { value: "warning", label: "Warning" },
  { value: "critical", label: "Critical" },
];

const SEVERITY_COLORS: Record<AuditSeverity, { bg: string; fg: string }> = {
  info: { bg: "rgba(120,120,120,0.15)", fg: "#888" },
  warning: { bg: "rgba(212,160,23,0.15)", fg: "#b8860b" },
  critical: { bg: "rgba(196,69,42,0.15)", fg: "#c4452a" },
};

const ACTION_ICONS: Record<string, string> = {
  login: "\uD83D\uDD11",
  elevate: "\u2B06\uFE0F",
  revoke: "\u2B07\uFE0F",
  dag_run: "\u26A1",
  agent_create: "\uD83E\uDD16",
  gate_block: "\uD83D\uDEE1\uFE0F",
  scan: "\uD83D\uDD0D",
  config_change: "\u2699\uFE0F",
};

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function severityBadge(s: AuditSeverity) {
  const c = SEVERITY_COLORS[s];
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 3, fontSize: 12,
      fontFamily: "var(--mono)", fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {s}
    </span>
  );
}

function truncateJson(obj: Record<string, unknown>, maxLen = 60): string {
  const s = JSON.stringify(obj);
  return s.length > maxLen ? s.slice(0, maxLen) + "..." : s;
}

const selectStyle: React.CSSProperties = {
  padding: "5px 10px", fontFamily: "var(--mono)", fontSize: 12,
  background: "var(--paper-2, #f5f5f0)", border: "1.3px solid var(--rule)",
  borderRadius: 4, color: "var(--ink)", cursor: "pointer",
};

const ghostButtonStyle: React.CSSProperties = {
  padding: "5px 14px", borderRadius: 4, cursor: "pointer",
  fontFamily: "var(--mono)", fontSize: 12,
  border: "1.3px solid var(--rule)",
  background: "var(--paper)", color: "var(--ink)",
  textDecoration: "none", display: "inline-block",
};

const COLUMN_WIDTHS = "150px 170px 160px 160px 110px 1fr";

function AuditRow({
  entry,
  onOpenDetail,
}: {
  entry: AuditEntry;
  onOpenDetail: (entry: AuditEntry) => void;
}) {
  const icon = ACTION_ICONS[entry.action] || "\uD83D\uDCCB";
  return (
    <div
      role="row"
      style={{
        display: "grid",
        gridTemplateColumns: COLUMN_WIDTHS,
        alignItems: "center",
        height: ROW_HEIGHT,
        borderBottom: "1px solid var(--rule)",
        fontFamily: "var(--mono)", fontSize: 12,
      }}
    >
      <span role="cell" style={{ padding: "0 12px", whiteSpace: "nowrap" }} title={new Date(entry.created_at).toLocaleString()}>
        {relativeTime(entry.created_at)}
      </span>
      <span role="cell" style={{ padding: "0 12px", whiteSpace: "nowrap" }}>
        {icon} {entry.action}
      </span>
      <span role="cell" style={{ padding: "0 12px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {entry.actor}
      </span>
      <span role="cell" style={{ padding: "0 12px", whiteSpace: "nowrap", color: entry.target ? "var(--ink)" : "var(--pencil)", overflow: "hidden", textOverflow: "ellipsis" }}>
        {entry.target || "\u2014"}
      </span>
      <span role="cell" style={{ padding: "0 12px" }}>
        {severityBadge(entry.severity)}
      </span>
      <span role="cell" style={{ padding: "0 12px" }}>
        <button
          onClick={() => onOpenDetail(entry)}
          style={{
            background: "none", border: "none", cursor: "pointer",
            fontFamily: "var(--mono)", fontSize: 12,
            color: "var(--accent)", padding: 0, textAlign: "left",
            maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
        >
          {truncateJson(entry.detail)}
        </button>
      </span>
    </div>
  );
}

export default function AuditLog() {
  const toast = useToast();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  // Number of newer rows discarded from the front of the bounded client
  // window. It preserves the scroll coordinate while later pages arrive.
  const [discardedRows, setDiscardedRows] = useState(0);
  const entriesRef = useRef<AuditEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [actionFilter, setActionFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [retention, setRetention] = useState<AuditRetention | null>(null);
  const [detailEntry, setDetailEntry] = useState<AuditEntry | null>(null);

  // Window state: scrollTop drives which slice of rows is mounted.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const scrollRaf = useRef<number | null>(null);

  // Latest-writer refs let the IntersectionObserver read current load state
  // without re-observing on every render.
  const nextCursorRef = useRef<string | null>(null);
  const loadingMoreRef = useRef(false);
  // Every filter change/refresh starts a new cursor walk. Responses from an
  // abandoned walk must not replace rows, append rows, or reset its load lock.
  const generationRef = useRef(0);

  const buildParams = useCallback(
    (cursor: string | null) => {
      const params = new URLSearchParams();
      if (actionFilter) params.set("action", actionFilter);
      if (severityFilter) params.set("severity", severityFilter);
      if (actorFilter) params.set("actor", actorFilter);
      params.set("limit", String(PAGE_SIZE));
      if (cursor) params.set("cursor", cursor);
      return params.toString();
    },
    [actionFilter, severityFilter, actorFilter],
  );

  const loadFirstPage = useCallback(async () => {
    const generation = ++generationRef.current;
    nextCursorRef.current = null;
    loadingMoreRef.current = false;
    entriesRef.current = [];
    setEntries([]);
    setNextCursor(null);
    setLoadingMore(false);
    setDetailEntry(null);
    try {
      setLoading(true);
      const page = await apiGet<AuditPage>(`/v1/audit?${buildParams(null)}`);
      if (generation !== generationRef.current) return;
      entriesRef.current = page.entries;
      setEntries(page.entries);
      setDiscardedRows(0);
      setNextCursor(page.next_cursor);
      nextCursorRef.current = page.next_cursor;
      if (scrollRef.current) scrollRef.current.scrollTop = 0;
      setScrollTop(0);
    } catch {
      if (generation === generationRef.current) toast("Failed to load audit log", "error");
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [buildParams, toast]);

  const loadMore = useCallback(async () => {
    const cursor = nextCursorRef.current;
    if (cursor === null || loadingMoreRef.current) return;
    const generation = generationRef.current;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await apiGet<AuditPage>(`/v1/audit?${buildParams(cursor)}`);
      if (generation !== generationRef.current) return;
      // Keyset pages are strictly contiguous: append, never merge. Retain a
      // sliding window so a long-lived tab cannot accumulate the whole corpus.
      const combined = [...entriesRef.current, ...page.entries];
      const dropCount = Math.max(0, combined.length - MAX_LOADED_ENTRIES);
      const retained = dropCount === 0 ? combined : combined.slice(dropCount);
      entriesRef.current = retained;
      setEntries(retained);
      if (dropCount > 0) setDiscardedRows((count) => count + dropCount);
      setNextCursor(page.next_cursor);
      nextCursorRef.current = page.next_cursor;
    } catch {
      if (generation === generationRef.current) toast("Failed to load more audit entries", "error");
    } finally {
      if (generation === generationRef.current) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [buildParams, toast]);

  useEffect(() => {
    void loadFirstPage();
    return () => {
      generationRef.current += 1;
      nextCursorRef.current = null;
    };
  }, [loadFirstPage]);

  useEffect(() => {
    apiGet<AuditRetention>("/v1/audit/retention")
      .then(setRetention)
      .catch(() => setRetention(null));
  }, []);

  // Incremental loading on scroll: re-arm for each new cursor. A short page
  // (or a fast scroll after appending) can keep the sentinel intersecting,
  // so waiting for a leave/re-enter edge would stall the walk. A fresh
  // observer samples visibility again; the ref lock still prevents overlap.
  // The button below covers keyboard/AT and observer-less paths.
  // The sentinel mounts only after the first page renders (loading=false),
  // so it is held in state: setting it re-runs this effect and attaches the
  // observer at that point (a plain ref would stay null here forever).
  const [sentinel, setSentinel] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (observed) => {
        if (observed.some((o) => o.isIntersecting) && nextCursorRef.current !== null) {
          void loadMore();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore, sentinel, nextCursor]);

  const onScroll = useCallback(() => {
    if (scrollRaf.current !== null) return;
    scrollRaf.current = requestAnimationFrame(() => {
      scrollRaf.current = null;
      if (scrollRef.current) setScrollTop(scrollRef.current.scrollTop);
    });
  }, []);

  useEffect(() => () => {
    if (scrollRaf.current !== null) cancelAnimationFrame(scrollRaf.current);
  }, []);

  const totalCount = entries.length;
  const hasMore = nextCursor !== null;
  // The server answers what this caller may see; the page repeats it rather
  // than implying a wider (or narrower) trail than the query enforces.
  const scopeNote =
    retention?.scope === "own"
      ? "the actions this account took"
      : "a record of every action taken in the system";

  // Window math: mount only [start, end) of the retained rows. `discardedRows`
  // is represented by a spacer, so appending/trimming pages does not make the
  // scrollbar jump while the client heap remains capped.
  const viewportStart = Math.floor(scrollTop / ROW_HEIGHT);
  const viewportEnd = Math.ceil((scrollTop + VIEWPORT_HEIGHT) / ROW_HEIGHT);
  const start = Math.max(0, viewportStart - discardedRows - OVERSCAN_ROWS);
  const end = Math.max(
    start,
    Math.min(totalCount, viewportEnd - discardedRows + OVERSCAN_ROWS),
  );
  const windowRows = entries.slice(start, end);

  const exportQuery = buildParams(null).replace(/&?limit=\d+/, "").replace(/^&/, "");

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader
        title="Audit Log"
        subtitle={`${totalCount} retained locally, newest first — ${scopeNote}`}
        helpHref="/docs#audit"
        actions={[
          <a
            key="export"
            href={`/v1/audit/export${exportQuery ? `?${exportQuery}` : ""}`}
            download="audit-log.ndjson"
            style={{ ...ghostButtonStyle, color: "var(--accent)" }}
            title="Stream the filtered trail as NDJSON (capped by the deployment's export bound)"
          >
            Export
          </a>,
          <button
            key="refresh"
            onClick={() => { void loadFirstPage(); }}
            style={ghostButtonStyle}
          >
            Refresh
          </button>,
        ]}
      />

      <Card>
        <div style={{
          display: "flex", gap: 8, alignItems: "center",
          padding: "10px 12px", borderBottom: "1.3px solid var(--rule)",
          flexWrap: "wrap",
        }}>
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={selectStyle}
          >
            {ACTION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            style={selectStyle}
          >
            {SEVERITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <div style={{ width: 180 }}>
            <SearchInput
              value={actorFilter}
              onChange={setActorFilter}
              placeholder="Filter actor..."
            />
          </div>

          <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>
            {retention
              ? `page ≤ ${retention.max_page_size} · export ≤ ${retention.export_max_entries} · ${retention.durable ? "durable" : "in-memory"}`
              : ""}
          </span>
        </div>

        {loading ? (
          <LoadingSpinner />
        ) : entries.length === 0 ? (
          <EmptyState icon="📜" title="No audit entries" />
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: COLUMN_WIDTHS, borderBottom: "1.3px solid var(--rule)", padding: `8px 0` }}>
              {["Time", "Action", "Actor", "Target", "Severity", "Detail"].map((h) => (
                <span key={h} role="columnheader" style={{ padding: "0 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 12, textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</span>
              ))}
            </div>
            <div
              ref={scrollRef}
              onScroll={onScroll}
              role="rowgroup"
              // The spacer already preserves scroll coordinates when rows
              // are evicted. Native anchoring would adjust them again and can
              // pull the sentinel back into view, draining unsolicited pages.
              style={{ height: VIEWPORT_HEIGHT, overflowY: "auto", overflowAnchor: "none" }}
            >
              <div style={{ height: (discardedRows + start) * ROW_HEIGHT }} aria-hidden="true" />
              {windowRows.map((entry) => (
                <AuditRow key={entry.id} entry={entry} onOpenDetail={setDetailEntry} />
              ))}
              <div style={{ height: Math.max(0, (totalCount - end) * ROW_HEIGHT) }} aria-hidden="true" />
              {/* Load-more sentinel + fallback: observation usually fires
                  first; the button covers keyboard/AT and observer-less paths. */}
              <div ref={setSentinel} style={{ height: 1 }} />
              {hasMore && (
                <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
                  <button onClick={() => { void loadMore(); }} disabled={loadingMore} style={ghostButtonStyle}>
                    {loadingMore ? "Loading…" : "Load older entries"}
                  </button>
                </div>
              )}
              {!hasMore && (
                <div style={{ textAlign: "center", padding: "12px 0", fontFamily: "var(--mono)", fontSize: 11, color: "var(--pencil)" }}>
                  {retention?.scope === "own"
                    ? "Beginning of this account's (filtered) trail"
                    : "Beginning of the (filtered) trail"}
                </div>
              )}
            </div>
          </>
        )}
      </Card>

      <Modal
        open={detailEntry !== null}
        onClose={() => setDetailEntry(null)}
        title="Audit Detail"
        wide
      >
        {detailEntry && (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px", marginBottom: 12, fontFamily: "var(--mono)", fontSize: 12 }}>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 12 }}>Action</span>
              <span style={{ fontWeight: 600 }}>{ACTION_ICONS[detailEntry.action] || ""} {detailEntry.action}</span>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 12 }}>Actor</span>
              <span>{detailEntry.actor}</span>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 12 }}>Target</span>
              <span>{detailEntry.target || "\u2014"}</span>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 12 }}>Severity</span>
              <div>{severityBadge(detailEntry.severity)}</div>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 12 }}>Time</span>
              <span>{new Date(detailEntry.created_at).toLocaleString()}</span>
            </div>
            <div style={{
              background: "var(--paper-2, #f5f5f0)", border: "1.3px solid var(--rule)",
              borderRadius: 4, padding: 12, fontFamily: "var(--mono)", fontSize: 12,
              whiteSpace: "pre-wrap" as const, overflow: "auto", maxHeight: 400,
            }}>
              {JSON.stringify(detailEntry.detail, null, 2)}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
