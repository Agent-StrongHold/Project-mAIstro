import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../lib/api";
import {
  EmptyState,
  Hex,
  LoadingSpinner,
  PageHeader,
  useToast,
} from "../components/shared";

type Decision = "pending" | "accepted" | "rejected";
type ProposalClass = "auto_apply" | "propose";

type Proposal = {
  id: string;
  dag_id: string;
  target_node_id: string;
  class: ProposalClass;
  kind: string;
  field_path: string;
  rationale: string;
  priority_score: number;
  blocked_by_edit_lock: boolean;
  applied: boolean;
  decision: Decision;
  created_at: string;
  decided_by?: string;
  decided_at?: string;
  topology_proposal?: {
    kind?: string;
    target_node_id?: string;
    from_value?: string;
    to_value?: string;
    expected_improvement?: string;
  } | null;
};

const DECISION_LABELS: Record<Decision, string> = {
  pending: "Pending",
  accepted: "Accepted",
  rejected: "Rejected",
};

const KIND_LABELS: Record<string, string> = {
  model_swap: "Model swap",
  edge_weight_tune: "Edge weight tune",
  retry_count_tune: "Retry count tune",
  topology_mutation: "Topology mutation",
  prompt_rewrite: "Prompt rewrite",
};

export default function OptimizationInbox() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Decision | "">("");
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const toast = useToast();

  const loadProposals = useCallback(async () => {
    setLoading(true);
    try {
      const query = filter ? `?decision=${filter}` : "";
      const res = await apiGet<Proposal[]>(`/v1/optimizer/proposals${query}`);
      setProposals(res ?? []);
    } catch (e: unknown) {
      toast(`Failed to load proposals: ${(e as Error).message}`, "error");
    } finally {
      setLoading(false);
    }
  }, [filter, toast]);

  useEffect(() => {
    void loadProposals();
  }, [loadProposals]);

  const decide = useCallback(
    async (id: string, decision: "accept" | "reject") => {
      setDecidingId(id);
      try {
        await apiPost(`/v1/optimizer/proposals/${id}/${decision}`, {});
        toast(
          `Proposal ${decision}ed`,
          decision === "accept" ? "ok" : "warn",
        );
        await loadProposals();
      } catch (e: unknown) {
        toast(`Failed: ${(e as Error).message}`, "error");
      } finally {
        setDecidingId(null);
      }
    },
    [loadProposals, toast],
  );

  const grouped = useMemo(() => {
    const out: Record<string, Proposal[]> = {};
    for (const p of proposals) {
      out[p.dag_id] = out[p.dag_id] ?? [];
      out[p.dag_id].push(p);
    }
    return Object.entries(out).map(([dagId, items]) => ({
      dagId,
      items: items.sort((a, b) => b.priority_score - a.priority_score),
    }));
  }, [proposals]);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        title="Optimization Inbox"
        subtitle="The optimizer's proposed changes — accept to apply, reject to teach it what to avoid"
        helpHref="/docs#optimizer"
        actions={
          <div className="flex gap-2 text-sm">
            <button
              className={`px-2 py-1 rounded ${filter === "" ? "bg-blue-600 text-white" : "bg-gray-200"}`}
              onClick={() => setFilter("")}
            >
              All
            </button>
            <button
              className={`px-2 py-1 rounded ${filter === "pending" ? "bg-blue-600 text-white" : "bg-gray-200"}`}
              onClick={() => setFilter("pending")}
            >
              Pending
            </button>
            <button
              className={`px-2 py-1 rounded ${filter === "accepted" ? "bg-blue-600 text-white" : "bg-gray-200"}`}
              onClick={() => setFilter("accepted")}
            >
              Accepted
            </button>
            <button
              className={`px-2 py-1 rounded ${filter === "rejected" ? "bg-blue-600 text-white" : "bg-gray-200"}`}
              onClick={() => setFilter("rejected")}
            >
              Rejected
            </button>
          </div>
        }
      />

      {loading && <LoadingSpinner />}

      {!loading && proposals.length === 0 && (
        <EmptyState
          icon=""
          title={
            filter
              ? `No ${filter} proposals — try a different filter or run the optimizer`
              : "No optimizer proposals yet. Run a few DAGs, give thumbs, then trigger the optimizer."
          }
        />
      )}

      {!loading && grouped.length > 0 && (
        <div className="space-y-6 mt-4">
          {grouped.map((group) => (
            <section
              key={group.dagId}
              className="rounded-lg border border-gray-200"
            >
              <header className="flex items-center justify-between px-4 py-3 border-b bg-gray-50">
                <div>
                  <div className="text-xs text-gray-500">DAG</div>
                  <div className="font-mono text-sm">{group.dagId}</div>
                </div>
                <div className="text-xs text-gray-500">
                  {group.items.length} proposal
                  {group.items.length > 1 ? "s" : ""}
                </div>
              </header>
              <ul className="divide-y">
                {group.items.map((p) => (
                  <li key={p.id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <Hex
                            variant={
                              p.class === "auto_apply" ? "warn" : "purple"
                            }
                          >
                            {p.class === "auto_apply"
                              ? "Auto-apply"
                              : "Propose"}
                          </Hex>
                          <Hex variant="muted">
                            {KIND_LABELS[p.kind] ?? p.kind}
                          </Hex>
                          {p.blocked_by_edit_lock && (
                            <Hex variant="danger">Edit-locked</Hex>
                          )}
                          {p.applied && <Hex variant="ok">Applied</Hex>}
                          <Hex
                            variant={
                              p.decision === "accepted"
                                ? "ok"
                                : p.decision === "rejected"
                                  ? "danger"
                                  : "muted"
                            }
                          >
                            {DECISION_LABELS[p.decision]}
                          </Hex>
                          <span className="text-xs text-gray-500">
                            score {p.priority_score.toFixed(3)}
                          </span>
                        </div>
                        <div className="text-xs text-gray-500 font-mono mb-1">
                          target: {p.field_path}
                        </div>
                        <p className="text-sm text-gray-800">{p.rationale}</p>
                        {p.topology_proposal && (
                          <div className="mt-2 text-xs bg-purple-50 rounded p-2 border border-purple-200">
                            <strong>Topology mutation:</strong>{" "}
                            {p.topology_proposal.from_value} →{" "}
                            {p.topology_proposal.to_value}
                            {p.topology_proposal.expected_improvement && (
                              <div className="text-gray-600 mt-1">
                                {p.topology_proposal.expected_improvement}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      {p.decision === "pending" && (
                        <div className="flex flex-col gap-1 shrink-0">
                          <button
                            className="px-3 py-1 rounded bg-green-600 text-white text-xs hover:bg-green-700 disabled:opacity-50"
                            disabled={decidingId === p.id}
                            onClick={() => decide(p.id, "accept")}
                          >
                            Accept
                          </button>
                          <button
                            className="px-3 py-1 rounded bg-gray-300 text-gray-800 text-xs hover:bg-gray-400 disabled:opacity-50"
                            disabled={decidingId === p.id}
                            onClick={() => decide(p.id, "reject")}
                          >
                            Reject
                          </button>
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

    </div>
  );
}
