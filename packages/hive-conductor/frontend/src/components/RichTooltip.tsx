import { useState, useRef, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  content: ReactNode;
  side?: "top" | "bottom";
  align?: "left" | "center" | "right";
};

const SIDE: Record<string, string> = { top: "bottom: 100%; margin-bottom: 6px;", bottom: "top: 100%; margin-top: 6px;" };
const ALIGN: Record<string, string> = { left: "left: 0;", center: "left: 50%; transform: translateX(-50%);", right: "right: 0;" };

export function RichTooltip({ children, content, side = "top", align = "center" }: Props) {
  const [show, setShow] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const enter = () => { clearTimeout(timer.current); timer.current = setTimeout(() => setShow(true), 120); };
  const leave = () => { clearTimeout(timer.current); setShow(false); };

  return (
    <span style={{ position: "relative", display: "inline-block" }} onMouseEnter={enter} onMouseLeave={leave} onFocus={enter} onBlur={leave}>
      {children}
      {show && (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            zIndex: 50,
            ...Object.fromEntries(SIDE[side].split(";").filter(Boolean).map(s => { const [k, v] = s.split(":"); return [k.trim(), v.trim()]; })),
            ...Object.fromEntries(ALIGN[align].split(";").filter(Boolean).map(s => { const [k, v] = s.split(":"); return [k.trim(), v.trim()]; })),
            background: "var(--ink, #1a1a1a)",
            color: "var(--paper, #fafafa)",
            fontSize: "0.68rem",
            padding: "6px 10px",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
            whiteSpace: "nowrap",
            pointerEvents: "none",
            opacity: show ? 1 : 0,
            transition: "opacity 0.12s",
          }}
        >
          {content}
        </span>
      )}
    </span>
  );
}
