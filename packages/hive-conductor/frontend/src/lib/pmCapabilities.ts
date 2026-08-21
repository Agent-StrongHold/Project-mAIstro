/** Mirror of maistro.agents.pm_capabilities for UI routing. */

export type WorkItemType = "initiative" | "epic" | "user_story" | "dev_task" | "subtask";

const GATED = new Set([
  "create_initiative",
  "create_epic",
  "create_story",
  "create_user_story",
  "create_dev_task",
  "create_subtask",
  "create_jira_ticket",
  "create_raid_entry",
  "decompose_initiative",
  "link_dependency",
  "escalate_issue",
  "publish_dashboard",
]);

const CAP_TO_WORK: Record<string, WorkItemType> = {
  create_initiative: "initiative",
  create_epic: "epic",
  create_story: "user_story",
  create_user_story: "user_story",
  create_dev_task: "dev_task",
  create_subtask: "subtask",
};

const WORK_LABELS: Record<WorkItemType, string> = {
  initiative: "Initiative",
  epic: "Epic",
  user_story: "User Story",
  dev_task: "Development Task",
  subtask: "Sub-task",
};

export function isGatedCapability(capability: string): boolean {
  return GATED.has(capability) || capability in CAP_TO_WORK;
}

export function workTypeForCapability(capability: string): WorkItemType | null {
  return CAP_TO_WORK[capability] ?? null;
}

export function labelForWorkType(workType: WorkItemType): string {
  return WORK_LABELS[workType];
}
