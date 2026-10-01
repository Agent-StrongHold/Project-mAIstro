import { useEffect, useState } from "react";

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
 */
export function DegradedBanner() {
  const [services, setServices] = useState<DegradedService[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch("/health")
      .then((r) => (r.ok ? r.json() : null))
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
    <div className="degraded-banner" role="status" aria-live="polite" data-testid="degraded-banner">
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
