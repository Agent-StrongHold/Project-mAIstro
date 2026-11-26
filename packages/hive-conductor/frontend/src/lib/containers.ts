/** Container page wire shapes (GET /v1/containers*, services/containers.py).
 * Under `lib/` for typed-client. */

export type Container = {
  id: string; name: string; image: string; status: string;
  ports: { host?: number; container: number }[];
  cpu_usage: number; memory_usage_mb: number; memory_limit_mb: number;
  network_rx_mb: number; network_tx_mb: number;
  created_at: string; started_at: string | null;
  labels: Record<string, string>;
};

export type LogData = { id: string; logs: string };
