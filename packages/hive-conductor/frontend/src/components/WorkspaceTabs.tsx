import { useEffect, useState, type FormEvent } from "react";
import { apiGet } from "../lib/api";
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
  const { workspaces, activeWorkspaceId, selectWorkspace, createWorkspace, ready } =
    useWorkspaces();
  const [creating, setCreating] = useState(false);
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
      await createWorkspace({ name: trimmed, persona_template_id: personaTemplateId });
      setName("");
      setCreating(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create workspace");
    } finally {
      setBusy(false);
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
      {error && <span className="workspace-tab-error">{error}</span>}
    </div>
  );
}
