import { useState, type FormEvent } from "react";
import { apiDelete, apiPost } from "../lib/api";
import { useUser } from "../App";
import { useWorkspaces, type Workspace, type WorkspaceRole } from "../context/WorkspaceContext";

function myRole(workspace: Workspace, userId: string | undefined): WorkspaceRole | null {
  return workspace.members.find((m) => m.user_id === userId)?.role ?? null;
}

/** Share/invite panel for the active workspace, on top of the existing
 * POST/DELETE /v1/workspaces/{id}/members API (Phase G) -- that API has
 * always been reachable, just never had a control to click. Any member can
 * see who else is in a workspace; only an owner can invite; an owner may
 * remove anyone, any member may remove themself (mirrors the backend's own
 * policy exactly, including refusing to remove the last owner). */
export function WorkspaceShare() {
  const user = useUser();
  const { activeWorkspace, refresh, archiveWorkspace, deleteWorkspace } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const [inviteUserId, setInviteUserId] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (!activeWorkspace) return null;
  const role = myRole(activeWorkspace, user?.id);
  const isOwner = role === "owner";

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    const trimmed = inviteUserId.trim();
    if (!trimmed || busy || !activeWorkspace) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/v1/workspaces/${activeWorkspace.id}/members`, {
        user_id: trimmed,
        role: inviteRole,
      });
      setInviteUserId("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(memberId: string) {
    if (busy || !activeWorkspace) return;
    setBusy(true);
    setError(null);
    try {
      await apiDelete(`/v1/workspaces/${activeWorkspace.id}/members/${memberId}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove member");
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive() {
    if (busy || !activeWorkspace) return;
    setBusy(true);
    setError(null);
    try {
      await archiveWorkspace(activeWorkspace.id, false);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive workspace");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (busy || !activeWorkspace) return;
    setBusy(true);
    setError(null);
    try {
      await deleteWorkspace(activeWorkspace.id);
      setOpen(false);
      setConfirmingDelete(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete workspace");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace-share">
      <button
        type="button"
        className="workspace-tab workspace-share-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        Share ({activeWorkspace.members.length})
      </button>
      {open && (
        <div className="workspace-share-panel">
          <div className="workspace-share-title">{activeWorkspace.name} members</div>
          <ul className="workspace-share-members">
            {activeWorkspace.members.map((m) => (
              <li key={m.user_id}>
                <span className="workspace-share-member-id">{m.user_id}</span>
                <span className="workspace-share-role">{m.role}</span>
                {(isOwner || m.user_id === user?.id) && (
                  <button
                    type="button"
                    className="workspace-share-remove"
                    disabled={busy}
                    onClick={() => void handleRemove(m.user_id)}
                    aria-label={`Remove ${m.user_id}`}
                  >
                    &#x2715;
                  </button>
                )}
              </li>
            ))}
          </ul>
          {isOwner && (
            <form onSubmit={(e) => void handleInvite(e)} className="workspace-share-invite-form">
              <input
                value={inviteUserId}
                onChange={(e) => setInviteUserId(e.target.value)}
                placeholder="user_id"
                aria-label="Invite user id"
                disabled={busy}
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}
                aria-label="Invite role"
                disabled={busy}
              >
                <option value="viewer">viewer</option>
                <option value="editor">editor</option>
                <option value="owner">owner</option>
              </select>
              <button type="submit" disabled={busy || !inviteUserId.trim()}>
                Add
              </button>
            </form>
          )}
          {isOwner && (
            <div className="workspace-share-danger-zone">
              <button type="button" disabled={busy} onClick={() => void handleArchive()}>
                Archive workspace
              </button>
              {confirmingDelete ? (
                <>
                  <span className="workspace-share-confirm-text">Delete permanently?</span>
                  <button
                    type="button"
                    className="workspace-share-delete-confirm"
                    disabled={busy}
                    onClick={() => void handleDelete()}
                  >
                    Yes, delete
                  </button>
                  <button type="button" disabled={busy} onClick={() => setConfirmingDelete(false)}>
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="workspace-share-delete"
                  disabled={busy}
                  onClick={() => setConfirmingDelete(true)}
                >
                  Delete workspace
                </button>
              )}
            </div>
          )}
          {error && <div className="workspace-share-error">{error}</div>}
        </div>
      )}
    </div>
  );
}
