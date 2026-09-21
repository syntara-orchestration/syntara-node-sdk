# Subworkflow Call Node

**Category:** `workflow`

**Execution type:** `in_process`

**Feature:** Reference-mode subworkflow invocation

The `subworkflow_call` is the parent-side composition step. It selects a child
workflow by `workflow_id`, reads the active child's required input-variable
schema, and exposes those variables as configurable form fields. At runtime it
revalidates child eligibility and the caller's execute permission, invokes the
child synchronously, and pauses the parent until the child reaches a terminal
state.

The child workflow is eligible only when it contains an active
[`subworkflow_trigger`](../subworkflow-trigger/). The trigger owns child entry
eligibility and the child input/output contract; this node owns parent
invocation and composition.

The terminal child output is mapped into `StandardOutputWrapper.Result`, making
it available to downstream templates such as `${call_child.Result.summary}`.
The descriptor is [manifest.yaml](manifest.yaml). This directory documents the
control-plane contract; production lifecycle and permission enforcement remain
platform responsibilities.
