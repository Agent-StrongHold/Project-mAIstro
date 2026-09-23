import { useEffect, useState, type FormEvent } from "react";
import { apiGet } from "../lib/api";
import { useToast } from "./shared";
import { useWorkspaces } from "../context/WorkspaceContext";

type PersonaTemplateOption = {
  id: string;
  display_name: string;
  tagline: string;
};

/** Persona/Workspace system: the live tab strip a user switches between.
 * Each tab is one adopted persona's Workspace; switching applies that
 * workspace's theme. The create form's persona picker is backed by
 * GET /v1/workspaces/persona-templates -- "unlimited personas" means
 * whatever YAML files exist on disk, not a hardcoded list here. */
export function WorkspaceTabs() {
  const toast = useToast();
  const {
    workspaces,
    activeWorkspaceId,
    selectWorkspace,
    createWorkspace,
    archiveWorkspace,
    ready,
  } = useWorkspaces();
  const [creating, setCreating] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [personaTemplates, setPersonaTemplates] = useState<PersonaTemplateOption[]>([]);
  const [personaTemplateId, setPersonaTemplateId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!creating) return;
    let cancelled = false;
    (async () => {
      try {
        const options = await apiGet<PersonaTemplateOption[]>("/v1/workspaces/persona-templates");
        if (cancelled) return;
        setPersonaTemplates(options);
        setPersonaTemplateId((current) => current || options[0]?.id || "");
      } catch {
        // Picker degrades to empty; the create form still works if the
        // caller falls back to a known id, but there's nothing to select.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [creating]);

  if (!ready) return null;

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || !personaTemplateId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createWorkspace({
        name: trimmed,
        persona_template_id: personaTemplateId,
      });
      setName("");
      setCreating(false);
      toast(`Created workspace "${created.name}"`, "ok");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create workspace");
    } finally {
      setBusy(false);
    }
  }

  // Archiving is reversible (#1428): the backend has always accepted
  // `PATCH {active: true}`, but nothing in the UI listed an archived workspace
  // once its tab was gone. They live behind a disclosure so the strip stays
  // about the live ones.
  const archived = workspaces.filter((w) => w.active === false);

  async function handleRestore(id: string, wsName: string) {
    if (restoring) return;
    setRestoring(id);
    setError(null);
    try {
      await archiveWorkspace(id, true);
      selectWorkspace(id);
      toast(`Restored workspace "${wsName}"`, "ok");
      if (archived.length === 1) setShowArchived(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore workspace");
    } finally {
      setRestoring(null);
    }
  }

  const live = workspaces.filter((w) => w.active !== false);

  const createForm = (
    <form onSubmit={(e) => void handleCreate(e)} className="workspace-tab-new-form">
      <input
        autoFocus
        value={name}
        disabled={busy}
        onChange={(e) => setName(e.target.value)}
        placeholder="Workspace name"
        aria-label="New workspace name"
      />
      {/* The persona is a choice, so its name and tagline are on screen
          rather than behind a <select>'s title tooltip (#1437). Radios keep
          it one keyboard-operable group. */}
      <fieldset className="workspace-persona-picker" disabled={busy}>
        <legend>Persona</legend>
        {personaTemplates.length === 0 && (
          <span className="workspace-persona-none">No personas available</span>
        )}
        {personaTemplates.map((p) => (
          <label
            key={p.id}
            className={`workspace-persona-option${p.id === personaTemplateId ? " selected" : ""}`}
          >
            <input
              type="radio"
              name="persona_template"
              value={p.id}
              checked={p.id === personaTemplateId}
              onChange={() => setPersonaTemplateId(p.id)}
            />
            <span className="workspace-persona-name">{p.display_name}</span>
            <span className="workspace-persona-tagline">{p.tagline}</span>
          </label>
        ))}
      </fieldset>
      <div className="workspace-tab-new-actions">
        <button type="submit" disabled={busy || !name.trim() || !personaTemplateId}>
          Create
        </button>
        <button
          type="button"
          onClick={() => {
            setCreating(false);
            setName("");
          }}
          aria-label="Cancel"
        >
          &#x2715;
        </button>
      </div>
    </form>
  );

  return (
    <div className="workspace-tabs-wrap">
      {/* The tablist holds only tabs and scrolls sideways in one row: a long
          name truncates with its full text in the tooltip, and the strip
          never stacks into a column on a phone (#1424). */}
      {live.length > 0 && (
        <div className="workspace-tabs" role="tablist" aria-label="Workspaces">
          {live.map((w) => (
            <button
              key={w.id}
              type="button"
              role="tab"
              aria-selected={w.id === activeWorkspaceId}
              className={`workspace-tab${w.id === activeWorkspaceId ? " active" : ""}`}
              onClick={() => selectWorkspace(w.id)}
              title={`${w.name} (${w.persona_template_id})`}
            >
              {w.name}
            </button>
          ))}
        </div>
      )}
      {/* A first run says what a workspace is instead of showing a bare "+"
          (#1426, #1431). */}
      {live.length === 0 && !creating && (
        <div className="workspace-empty" role="status">
          <span>
            No workspaces yet. A workspace is one persona&apos;s home: its agents, memory,
            checklist and look, kept apart from every other.
          </span>
          <button
            type="button"
            className="workspace-empty-create"
            onClick={() => setCreating(true)}
          >
            Create workspace
          </button>
        </div>
      )}
      <span className="workspace-tab-new">
        <button
          type="button"
          className="workspace-tab workspace-tab-add"
          onClick={() => setCreating((v) => !v)}
          aria-label="New workspace"
          aria-expanded={creating}
          title="New workspace"
        >
          +
        </button>
        {creating && createForm}
      </span>
      {archived.length > 0 && (
        <span className="workspace-tabs-archived">
          <button
            type="button"
            className="workspace-tab workspace-tabs-archived-toggle"
            onClick={() => setShowArchived((v) => !v)}
            aria-expanded={showArchived}
          >
            Archived ({archived.length})
          </button>
          {showArchived && (
            <ul className="workspace-tabs-archived-list" aria-label="Archived workspaces">
              {archived.map((w) => (
                <li key={w.id}>
                  <span className="workspace-tabs-archived-name" title={w.name}>
                    {w.name}
                  </span>
                  <button
                    type="button"
                    disabled={restoring !== null}
                    onClick={() => void handleRestore(w.id, w.name)}
                    aria-label={`Restore ${w.name}`}
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          )}
        </span>
      )}
      {error && (
        <span role="alert" className="workspace-tab-error">
          {error}
        </span>
      )}
    </div>
  );
}
