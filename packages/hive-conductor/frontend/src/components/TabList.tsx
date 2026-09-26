import { useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

type Tab<T extends string> = { id: T; label: string };

const tabId = (idPrefix: string, id: string) => `${idPrefix}-tab-${id}`;
const panelId = (idPrefix: string, id: string) => `${idPrefix}-panel-${id}`;

const TAB_STYLE: CSSProperties = {
  padding: "7px 16px", fontFamily: "var(--mono)", fontSize: 12, cursor: "pointer",
  background: "none", border: "none", borderRadius: 0, boxShadow: "none", transform: "none",
  textTransform: "capitalize",
};

/**
 * WAI-ARIA tabs with automatic activation: only the selected tab is a tab
 * stop, and Arrow/Home/End move focus and selection together.
 */
export function TabList<T extends string>({ label, idPrefix, tabs, selected, onSelect, style }: {
  label: string;
  idPrefix: string;
  tabs: readonly Tab<T>[];
  selected: T;
  onSelect: (id: T) => void;
  style?: CSSProperties;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = tabs.length - 1;
    const next = { ArrowRight: index === last ? 0 : index + 1, ArrowLeft: index === 0 ? last : index - 1, Home: 0, End: last }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    onSelect(tabs[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--rule)", ...style }}>
      {tabs.map((t, i) => {
        const active = t.id === selected;
        return (
          <button
            key={t.id}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            role="tab"
            id={tabId(idPrefix, t.id)}
            aria-selected={active}
            aria-controls={panelId(idPrefix, t.id)}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(t.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            style={{ ...TAB_STYLE, borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent", color: active ? "var(--ink)" : "var(--pencil)" }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * The panel element always exists so every tab's aria-controls resolves; its
 * content mounts only while selected, as the pages rendered it before.
 */
export function TabPanel({ idPrefix, id, selected, children }: { idPrefix: string; id: string; selected: boolean; children: ReactNode }) {
  return (
    <div role="tabpanel" id={panelId(idPrefix, id)} aria-labelledby={tabId(idPrefix, id)} hidden={!selected}>
      {selected && children}
    </div>
  );
}
