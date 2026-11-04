// Workspace Home (#1048) — read-time projections over canonical services.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, apiGet } from "../lib/api";
import { useWorkspaces } from "../context/WorkspaceContext";
import { Card, EmptyState, LoadingSpinner, PageHeader } from "../components/shared";
import "./workspace-home.css";

type ProjectionItem = {
  resource_type: string;
  resource_id: string;
  title: string;
  href: string;
  updated_at: string | null;
};

type ProjectionSection = {
  kind: string;
  status: "ok" | "empty" | "unavailable";
  items: ProjectionItem[];
  reason?: string;
};

type HomeProjections = {
  workspace_id: string;
  generated_at: string;
  sections: ProjectionSection[];
};

type AdaptiveCandidate = {
  key: string;
  item_type: string;
  resource_id: string;
  title: string;
  explain: string;
  href: string;
};

type HomeAdaptive = {
  workspace_id: string;
  candidates: AdaptiveCandidate[];
};

type AttentionItem = {
  source_id: string;
  reason?: string;
  attention_class?: string;
  answer_href?: string;
};

type AttentionBody = {
  items: AttentionItem[];
};

const SECTION_VIEW_ALL: Partial<Record<string, { to: string; label: string }>> = {
  backlog: { to: "/backlog", label: "All backlog" },
  goals: { to: "/goals", label: "All goals" },
  runs: { to: "/dag-runs", label: "All runs" },
  chat: { to: "/chat", label: "Open chat" },
  design: { to: "/design-studio", label: "Design studio" },
  attention: { to: "/attention", label: "Attention inbox" },
};

const EMPTY_CTA: Partial<
  Record<string, { message: string; label: string; to: string }>
> = {
  backlog: { message: "No backlog items yet.", label: "Plan in Chat", to: "/chat" },
  goals: { message: "No goals recorded yet.", label: "Shape a goal in Chat", to: "/chat" },
  runs: { message: "No runs in this workspace yet.", label: "Build a workflow", to: "/dags" },
  chat: { message: "No conversations yet.", label: "Start chatting", to: "/chat" },
  design: { message: "Design studio is not ready yet.", label: "Open Design Studio", to: "/design-studio" },
};

function sectionByKind(sections: ProjectionSection[], kind: string): ProjectionSection | undefined {
  return sections.find((s) => s.kind === kind);
}

function formatGeneratedAt(iso: string | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function InternalHref({ href, children }: { href: string; children: string }) {
  if (href.startsWith("/")) {
    return <Link to={href}>{children}</Link>;
  }
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

function HomeEmpty({ message, ctaLabel, ctaTo }: { message: string; ctaLabel: string; ctaTo: string }) {
  return (
    <div className="workspace-home-empty">
      <p className="workspace-home-empty-text">{message}</p>
      <Link to={ctaTo} className="workspace-home-empty-cta">
        {ctaLabel}
      </Link>
    </div>
  );
}

function SectionCard({
  title,
  viewAll,
  children,
  busy,
}: {
  title: string;
  viewAll?: { to: string; label: string };
  children: ReactNode;
  busy?: boolean;
}) {
  return (
    <Card className="workspace-home-section-card">
      <div className="workspace-home-section-head">
        <h2 className="workspace-home-section-title">{title}</h2>
        {viewAll ? (
          <Link to={viewAll.to} className="workspace-home-section-link">
            {viewAll.label}
          </Link>
        ) : null}
      </div>
      {busy ? (
        <div className="workspace-home-section-loading" aria-busy="true">
          <LoadingSpinner />
        </div>
      ) : (
        children
      )}
    </Card>
  );
}

function ProjectionList({
  section,
  kind,
}: {
  section: ProjectionSection | undefined;
  kind: keyof typeof EMPTY_CTA;
}) {
  const empty = EMPTY_CTA[kind];
  if (!section) {
    return <p className="workspace-home-unavailable">This section did not load.</p>;
  }
  if (section.status === "unavailable") {
    return (
      <p className="workspace-home-unavailable">{section.reason ?? "Unavailable in this deployment."}</p>
    );
  }
  if (section.items.length === 0) {
    if (empty) {
      return <HomeEmpty message={empty.message} ctaLabel={empty.label} ctaTo={empty.to} />;
    }
    return <EmptyState title="Nothing here yet." />;
  }
  return (
    <ul className="workspace-home-item-list">
      {section.items.map((item) => (
        <li key={`${item.resource_type}:${item.resource_id}`} className="workspace-home-item">
          <InternalHref href={item.href}>{item.title}</InternalHref>
        </li>
      ))}
    </ul>
  );
}

function AttentionList({ items, forbidden }: { items: AttentionItem[]; forbidden: boolean }) {
  if (forbidden) {
    return (
      <HomeEmpty
        message="Items that need you require DAG write permission, or you can inspect runs below."
        ctaLabel="View runs"
        ctaTo="/dag-runs"
      />
    );
  }
  if (items.length === 0) {
    return (
      <HomeEmpty
        message="Nothing needs you right now."
        ctaLabel="Open Chat"
        ctaTo="/chat"
      />
    );
  }
  return (
    <ul className="workspace-home-item-list">
      {items.map((item) => (
        <li key={item.source_id} className="workspace-home-item">
          {item.answer_href?.startsWith("/") ? (
            <Link to={item.answer_href}>{item.reason ?? item.attention_class ?? "Needs attention"}</Link>
          ) : (
            <span className="workspace-home-item-plain">
              {item.reason ?? item.attention_class ?? "Needs attention"}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function SuggestedList({ candidates }: { candidates: AdaptiveCandidate[] }) {
  if (candidates.length === 0) {
    return (
      <HomeEmpty
        message="No suggestions right now — check back after you add backlog or runs."
        ctaLabel="Open Chat"
        ctaTo="/chat"
      />
    );
  }
  return (
    <ul className="workspace-home-item-list">
      {candidates.map((c) => (
        <li key={c.key} className="workspace-home-item">
          <InternalHref href={c.href}>{c.title}</InternalHref>
          <span className="workspace-home-item-meta">{c.explain}</span>
        </li>
      ))}
    </ul>
  );
}

export default function WorkspaceHome() {
  const navigate = useNavigate();
  const { activeWorkspaceId, activeWorkspace, ready: workspacesReady } = useWorkspaces();
  const [projections, setProjections] = useState<HomeProjections | null>(null);
  const [adaptive, setAdaptive] = useState<HomeAdaptive | null>(null);
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [attentionForbidden, setAttentionForbidden] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const workspaceTitle = activeWorkspace?.name ?? "Workspace";
  const generatedLabel = formatGeneratedAt(projections?.generated_at);

  const refresh = useCallback(async () => {
    if (!activeWorkspaceId) {
      setProjections(null);
      setAdaptive(null);
      setAttentionItems([]);
      setAttentionForbidden(false);
      setLoadError(null);
      return;
    }
    setLoading(true);
    setLoadError(null);
    setAttentionForbidden(false);
    const base = `/v1/workspaces/${activeWorkspaceId}/home`;
    try {
      const [proj, adapt] = await Promise.all([
        apiGet<HomeProjections>(`${base}/projections`),
        apiGet<HomeAdaptive>(`${base}/adaptive`),
      ]);
      setProjections(proj);
      setAdaptive(adapt);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not load Home.";
      setLoadError(message);
      setProjections(null);
      setAdaptive(null);
    }
    try {
      const attn = await apiGet<AttentionBody>(`/v1/workspaces/${activeWorkspaceId}/attention`);
      setAttentionItems(attn.items ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setAttentionForbidden(true);
        setAttentionItems([]);
      } else if (!(err instanceof ApiError && err.status === 404)) {
        setAttentionItems([]);
      }
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (!workspacesReady) return;
    void refresh();
  }, [workspacesReady, refresh]);

  const sections = useMemo(() => projections?.sections ?? [], [projections]);
  const initialLoad = loading && !projections;

  if (!workspacesReady) {
    return (
      <div className="workspace-home">
        <PageHeader title="Home" subtitle="Loading workspaces…" />
        <LoadingSpinner />
      </div>
    );
  }

  if (!activeWorkspaceId) {
    return (
      <div className="workspace-home">
        <PageHeader title="Home" subtitle="Pick or create a workspace tab to see its Home." />
        <Card>
          <EmptyState title="No active workspace." action="Open Chat" onAction={() => navigate("/chat")} />
        </Card>
      </div>
    );
  }

  return (
    <div className="workspace-home">
      <PageHeader
        title={workspaceTitle}
        subtitle="Your workspace at a glance — what needs you, what is planned, and where work is running."
        actions={
          <div className="workspace-home-actions">
            <Link to="/chat" className="btn-primary workspace-home-btn">
              Chat
            </Link>
            <Link to="/goals" className="workspace-home-btn workspace-home-btn-secondary">
              Goals
            </Link>
            <button
              type="button"
              className="workspace-home-btn workspace-home-btn-secondary"
              onClick={() => void refresh()}
              disabled={loading}
              aria-busy={loading}
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        }
      />

      <div className="workspace-home-lede">
        <p className="workspace-home-notice">
          Read-only snapshot from your workspace services. Use Chat to plan work and record goals; Home never starts
          runs or changes data on its own.
        </p>
        {generatedLabel ? (
          <p className="workspace-home-meta">Updated {generatedLabel}</p>
        ) : null}
      </div>

      <nav className="workspace-home-quick" aria-label="Quick actions">
        <Link to="/chat" className="workspace-home-quick-link workspace-home-quick-link--primary">
          Chat
        </Link>
        <Link to="/goals" className="workspace-home-quick-link">
          Goals
        </Link>
        <Link to="/backlog" className="workspace-home-quick-link">
          Backlog
        </Link>
        <Link to="/attention" className="workspace-home-quick-link">
          Attention
        </Link>
      </nav>

      {loadError ? (
        <Card className="workspace-home-error">
          <p className="workspace-home-unavailable">{loadError}</p>
          <button type="button" className="workspace-home-empty-cta" onClick={() => void refresh()}>
            Try again
          </button>
        </Card>
      ) : null}

      <div className={`workspace-home-grid${initialLoad ? " workspace-home-grid--loading" : ""}`}>
        <div className="workspace-home-column">
          <SectionCard title="Needs you" viewAll={SECTION_VIEW_ALL.attention} busy={initialLoad}>
            <AttentionList items={attentionItems} forbidden={attentionForbidden} />
          </SectionCard>
          <SectionCard title="Suggested" busy={initialLoad}>
            <SuggestedList candidates={adaptive?.candidates ?? []} />
          </SectionCard>
        </div>

        <div className="workspace-home-column">
          <SectionCard title="Backlog" viewAll={SECTION_VIEW_ALL.backlog} busy={initialLoad}>
            <ProjectionList section={sectionByKind(sections, "backlog")} kind="backlog" />
          </SectionCard>
          <SectionCard title="Goals" viewAll={SECTION_VIEW_ALL.goals} busy={initialLoad}>
            <ProjectionList section={sectionByKind(sections, "goals")} kind="goals" />
          </SectionCard>
          <SectionCard title="Runs" viewAll={SECTION_VIEW_ALL.runs} busy={initialLoad}>
            <ProjectionList section={sectionByKind(sections, "runs")} kind="runs" />
          </SectionCard>
          <SectionCard title="Recent chat" viewAll={SECTION_VIEW_ALL.chat} busy={initialLoad}>
            <ProjectionList section={sectionByKind(sections, "chat")} kind="chat" />
          </SectionCard>
          <SectionCard title="Design" viewAll={SECTION_VIEW_ALL.design} busy={initialLoad}>
            <ProjectionList section={sectionByKind(sections, "design")} kind="design" />
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
