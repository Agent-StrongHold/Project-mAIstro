import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";

// frontend-typed-client: allow /health returns a plain dict (no response_model), so no generated OpenAPI type exists yet for degraded services (#1048 cutover).
type DegradedService = { service: string; reason: string };

/** M3-B7 (#97): the user-facing half of Conductor degraded mode.

 * `/health` computes `degraded_services` — the same facts its liveness
 * probe reports, named and with a reason each. This banner renders that list
 * app-wide, so an operator using the product sees which optional
 * capabilities are diminished without reading container logs. Recovery needs
 * no dismissal flow: `/health` recomputes on every load, so when a service
 * returns the banner disappears on the next navigation/refresh by itself.
 *
 * The fetch is deliberately silent on failure: the banner's job is to report
 * a degraded Conductor, and a banner that noisily reports its own network
 * error would be a third problem on a bad day.
 *
 * Announced with `aria-live="polite"` but deliberately NOT `role="status"`:
 * the app's toasts (components/shared.tsx) own that role, and several e2e
 * specs select the toast as `getByRole("status")` — a second app-wide
 * role=status would make every one of those strict-mode assertions resolve
 * two elements whenever the Conductor is actually degraded (observed live:
 * api-error-copy and api-timeout failed exactly that way under the e2e-ui
 * compose harness, where no LLM gateway is configured).
 */
export function DegradedBanner() {
  const [services, setServices] = useState<DegradedService[]>([]);

  useEffect(() => {
    let cancelled = false;
    // Shared client (frontend-typed-client ratchet): still deliberately silent
    // on failure — apiGet throws ApiError and the .catch keeps the banner
    // (whose job is to report a degraded Conductor) out of a bad day's noise.
    apiGet<{ degraded_services?: unknown }>("/health")
      .then((h) => {
        if (!cancelled && h && Array.isArray(h.degraded_services)) {
          setServices(h.degraded_services as DegradedService[]);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (services.length === 0) return null;

  return (
    <div className="degraded-banner" aria-live="polite" data-testid="degraded-banner">
      <div className="degraded-banner-title">Degraded mode — some optional capabilities are unavailable:</div>
      <ul>
        {services.map((s) => (
          <li key={s.service}>
            <code>{s.service}</code>
            {s.reason ? <span className="degraded-banner-reason"> — {s.reason}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
