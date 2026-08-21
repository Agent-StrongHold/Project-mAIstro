import { useState } from "react";

type Segment = { label: string; value: number; color: string };

export function SvgDonut({ segments, size = 120 }: { segments: Segment[]; size?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = segments.reduce((s, seg) => s + seg.value, 0);
  if (total === 0) return <div className="empty-state"><span className="empty-state-text">No data</span></div>;

  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  const strokeWidth = size * 0.18;

  let cumAngle = -90;
  const arcs = segments.map((seg, i) => {
    const angle = (seg.value / total) * 360;
    const start = cumAngle;
    cumAngle += angle;
    return { ...seg, i, start, angle, pct: Math.round((seg.value / total) * 100) };
  });

  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const arcPath = (startDeg: number, angleDeg: number) => {
    const s = toRad(startDeg);
    const e = toRad(startDeg + angleDeg);
    const x1 = cx + r * Math.cos(s), y1 = cy + r * Math.sin(s);
    const x2 = cx + r * Math.cos(e), y2 = cy + r * Math.sin(e);
    const large = angleDeg > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
  };

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label="Donut chart">
        {arcs.map(a => (
          <path
            key={a.i}
            d={arcPath(a.start, Math.max(a.angle - 0.5, 0.1))}
            fill="none"
            stroke={a.color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            opacity={hover === null || hover === a.i ? 1 : 0.3}
            style={{ transition: "opacity 0.15s", cursor: "pointer" }}
            onMouseEnter={() => setHover(a.i)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
        <text x={cx} y={cy - 4} textAnchor="middle" style={{ fontSize: size * 0.18, fontWeight: 700, fill: "var(--ink)" }}>
          {hover !== null ? arcs[hover].value : total}
        </text>
        <text x={cx} y={cy + size * 0.11} textAnchor="middle" style={{ fontSize: size * 0.09, fill: "var(--pencil)" }}>
          {hover !== null ? arcs[hover].label : "total"}
        </text>
      </svg>
      {hover !== null && (
        <div style={{ position: "absolute", bottom: -4, left: "50%", transform: "translateX(-50%)", background: "var(--ink)", color: "var(--paper)", fontSize: "0.65rem", padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap", pointerEvents: "none" }}>
          {arcs[hover].label}: {arcs[hover].value} ({arcs[hover].pct}%)
        </div>
      )}
    </div>
  );
}
