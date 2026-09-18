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

  return (
    <div className="workspace-tabs" role="tablist" aria-label="Workspaces">
      {workspaces
        .filter((w) => w.active !== false)
        .map((w) => (
        <button
          key={w.id}
          type="button"
          role="tab"
          aria-selected={w.id === activeWorkspaceId}
          className={`workspace-tab${w.id === activeWorkspaceId ? " active" : ""}`}
          onClick={() => selectWorkspace(w.id)}
          title={w.persona_template_id}
        >
          {w.name}
        </button>
      ))}

      {creating ? (
        <form onSubmit={(e) => void handleCreate(e)} className="workspace-tab-new-form">
          <input
            autoFocus
            value={name}
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workspace name"
            aria-label="New workspace name"
          />
          <select
            value={personaTemplateId}
            disabled={busy || personaTemplates.length === 0}
            onChange={(e) => setPersonaTemplateId(e.target.value)}
            aria-label="Persona"
            title={personaTemplates.find((p) => p.id === personaTemplateId)?.tagline}
          >
            {personaTemplates.length === 0 && <option value="">No personas available</option>}
            {personaTemplates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
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
        </form>
      ) : (
        <button
          type="button"
          className="workspace-tab workspace-tab-add"
          onClick={() => setCreating(true)}
          aria-label="New workspace"
          title="New workspace"
        >
          +
        </button>
      )}
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
