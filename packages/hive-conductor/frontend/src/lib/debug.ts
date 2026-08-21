/** Dev-only console logging for API debugging. */

const ENABLED =
  import.meta.env.DEV && import.meta.env.VITE_DEBUG_API !== "false";

export function debugApi(
  method: string,
  path: string,
  status: number,
  ms: number,
  extra?: unknown,
): void {
  if (!ENABLED) return;
  const tag = status >= 400 ? "error" : "debug";
  const msg = `[hive] ${method} ${path} → ${status} (${ms.toFixed(0)}ms)`;
  if (extra !== undefined) {
    console[tag](msg, extra);
  } else {
    console[tag](msg);
  }
}

export function debugLog(scope: string, message: string, detail?: unknown): void {
  if (!ENABLED) return;
  if (detail !== undefined) {
    console.debug(`[hive:${scope}] ${message}`, detail);
  } else {
    console.debug(`[hive:${scope}] ${message}`);
  }
}
