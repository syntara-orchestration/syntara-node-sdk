# Subworkflow Trigger Node

**Category:** `trigger`

**Execution type:** `in_process`

**Feature:** Reference-mode subworkflow invocation

The `subworkflow_trigger` is the child-side entry point that makes a workflow
eligible to be invoked by a parent workflow in Reference mode. It is an
eligibility marker and child input/output contract; it is not the parent-side
step that selects or invokes a child workflow.

## Responsibilities

The child-side trigger:

- declares the child workflow's required input-variable schema;
- defines the child workflow's terminal output contract;
- identifies the workflow as eligible for Reference-mode invocation when the
  trigger is active; and
- runs as an in-process control-plane activity with no container image.

The parent-side `subworkflow_call` node owns workflow selection, dynamic form
construction, permission checks, synchronous invocation, and mapping the child
terminal output into `StandardOutputWrapper.Result`. See the architecture guide
for the parent/child split and the Reference-mode sequence.

## Descriptor

The node descriptor is [manifest.yaml](manifest.yaml). Its input schema carries
the child workflow's required variables under `input_variables`; the platform
uses that schema to populate the parent caller's configurable form fields.

```yaml
spec:
  category: trigger
  execution:
    type: in_process
    image: null
  inputs:
    type: object
    properties:
      input_variables:
        type: object
        additionalProperties: true
    required: [input_variables]
  outputs:
    allOf:
      - $ref: ../../schemas/common-definitions.json#/definitions/StandardOutputWrapper
```

The descriptor does not contain a `workflow_id`, caller execution ID, or
invocation timeout. Those belong to the parent `subworkflow_call` invocation
and are not child-entry eligibility fields.

## Runtime eligibility

At registration and again before a Reference-mode call, the platform verifies
that the target workflow has an active `subworkflow_trigger`. A workflow that
does not expose this trigger is not eligible for Reference-mode invocation,
even if the workflow exists and the caller has execute permission.

The platform also rechecks the caller's execute permission at invocation time.
The parent execution pauses while the child runs synchronously. When the child
reaches a terminal state, its output is returned through the parent's
`subworkflow_call` result and is available to downstream templates such as
`${call_child.Result.summary}`.

## Production execution path

`in_process` nodes are implemented as built-in control-plane activities. The
SDK manifest supplies metadata and contracts; it does not start a container or
invoke a child workflow itself. The production orchestration layer owns
workflow registration, eligibility checks, permission checks, and the child
workflow lifecycle.

The Python files in this directory are conceptual references for the contract.
They are not a second execution path for the production orchestrator.
