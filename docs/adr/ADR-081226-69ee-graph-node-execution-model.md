---
id: ADR-081226-69ee
title: Graph and Node Execution Model
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081426-1f7c
---

# ADR-081226-69ee: Graph and Node Execution Model

## Decision

Graph is the canonical editable composition object. Node is its universal executable position. A one-node Graph is valid.

Every persisted Graph is project-scoped and contains both `workspace_id` and `project_id`. The Project MUST belong to the same Workspace. GraphTemplate remains Workspace-wide; instantiation requires a destination Project and produces an independently mutable Graph filed in that Project with exact Template provenance.

A Run captures a stable Graph snapshot including graph identity, Workspace identity, Project identity, content hash, and serialized definition. Editing or moving the source Graph after Run creation cannot change that Run's captured scope or definition.

Selecting a Node creates a NodeRun; each physical try is an Attempt. GraphExecutionState owns traversal state. Run owns universal lifecycle and correlation.

Graph traversal remains domain logic. ExecutionRuntime owns bounded concurrency, cancellation, deadlines, task/process mechanics, and mechanics telemetry only.

Subgraph execution normally creates a child Run. The child defaults to the parent Run's Project. An explicitly requested child Run may target another Project in the same Workspace when the authorization layer approves creation/use in that destination. Child Runs never cross Workspace boundaries through ordinary execution.

`GraphRun`, `GraphConfig`, durable graph lifecycle records, and similar duplicate concepts are migration/deletion targets as callers move to Graph/Run/NodeRun/Attempt. Useful traversal behavior is preserved through parity tests, not through permanent competing lifecycle contracts.
