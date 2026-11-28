/** Task-scoped elevation wire contract (#336). Under `lib/` for
 * typed-client: the canonical elevate call goes through the shared HTTP
 * client, and the elevation dialog's context shapes live here so
 * `components/` stays free of local declarations. */

import { apiPost } from "./api";

export type ElevationRequest = {
  permission: string;
  resolve: () => void;
  reject: (error: Error) => void;
};

export type ElevationContextValue = {
  requestElevation: (permission: string) => Promise<void>;
};

/** POST /v1/auth/elevate's response (backend/routes/auth.py::elevate). */
export type ElevateResponse = {
  ok: boolean;
  task_id: string;
  elevated_permissions: string[];
  elevated_until: string;
  message: string;
};

/** Confirm a permission for this task with the account password. A refusal
 * (401 wrong password, 403 permission not assigned to the account) throws
 * `ApiError` whose message is the backend's verbatim `detail` — the
 * elevation dialog shows that copy and stays open for retry (#336). */
export async function elevateTask(
  password: string,
  permission: string,
  taskId: string,
): Promise<ElevateResponse> {
  return apiPost<ElevateResponse>("/v1/auth/elevate", {
    password,
    permissions: [permission],
    task_id: taskId,
  });
}
