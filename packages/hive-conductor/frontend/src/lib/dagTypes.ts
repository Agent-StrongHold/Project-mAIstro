/** DAG editor domain shapes (pages/DagBuilder's wire contracts against
 * /v1/dags and its run socket). Under `lib/` for typed-client. */

export type Role = "queen" | "worker" | "scout" | "drone" | "guard";
export type Strategy = "react" | "plan_execute" | "direct" | "delegate";
export type DagStatus = "draft" | "active" | "archived";

export type DAGNode = {
  id: string;
  role: string;
  name: string;
  agent_id: string | null;
  model: string | null;
  strategy: Strategy;
  prompt: string | null;
  config: Record<string, unknown>;
};

export type DAGEdge = {
  id: string;
  from_node: string;
  to_node: string | null;
  condition: string | null;
};

export type DAGFile = {
  id: string;
  name: string;
  description: string;
  nodes: DAGNode[];
  edges: DAGEdge[];
  entry_node: string | null;
  max_cycles: number;
  run_scout: boolean;
  status: DagStatus;
  created_at: string;
  updated_at: string;
};

export type Agent = {
  id: string;
  name: string;
  model: string;
  status: string;
};

/** One in-flight Run socket plus the flags the unmount cleanup reads (#355).
 * `started` mirrors the backend `started` frame — the point after which
 * `execute_dag` runs (and the projection is recorded) regardless of this
 * socket; `settled` marks a terminal/parked/error frame; `detach` asks the
 * handlers to close the socket at the next safe point. */
export type LiveRun = { ws: WebSocket; started: boolean; settled: boolean; detach: boolean };
