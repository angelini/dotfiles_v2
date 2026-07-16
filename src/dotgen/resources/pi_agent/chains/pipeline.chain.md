---
name: pipeline
description: Run the claude-pipeline scout → planner → reviewer → architect → editor → reviewer workflow non-interactively
argument-hint: <task description>
---

The Pi pipeline mirrors the Claude Sonnet/Opus split with GPT-5.6 variants: `claude-pipeline.scout` and `claude-pipeline.editor` use `openai-codex/gpt-5.6-terra`; `claude-pipeline.planner`, `claude-pipeline.architect`, and `claude-pipeline.reviewer` use `openai-codex/gpt-5.6-sol`.

## claude-pipeline.scout

phase: Scout
label: Map territory
as: scout
output: responses/scout-response.md
outputMode: file-only

Task: {task}

Use this exact workspace directory for artifacts: `{chain_dir}/workspace`.
Create it if needed and write `{chain_dir}/workspace/scout.md`.
If this is a one-sentence diff that should skip the pipeline, write that recommendation in `scout.md` and make it unmistakable in your final response.

## claude-pipeline.planner

phase: Plan
label: Write implementation plan
as: plan
output: responses/plan-response.md
outputMode: file-only

Task: {task}

Read `{chain_dir}/workspace/scout.md` first. Write the plan artifact(s) in `{chain_dir}/workspace` as `plan.md` or serial `plan-1.md`, `plan-2.md`, etc.
Stay at design altitude: decide approach, reuse, scope, behaviors, and verification, but leave exact signatures, symbol/line locations, and bodies to the architect.
If the scout recommended skipping the pipeline, write a minimal plan that says why and stop without expanding scope.

Scout response:
{outputs.scout}

## claude-pipeline.reviewer

phase: Plan review
label: Review plan before edit spec
as: planReview
output: responses/plan-review-response.md
outputMode: file-only

Task: {task}

Review the plan before implementation. Read `{chain_dir}/workspace/scout.md` and the plan artifact(s) in `{chain_dir}/workspace` directly. Write `{chain_dir}/workspace/plan-review.md`.

Because this saved Pi chain is non-interactive, do not ask broad approval questions. Instead, record every blocker or human-owned decision clearly in the review. If there are no genuine blockers, say the plan is ready for the architect.

Plan response:
{outputs.plan}

## claude-pipeline.architect

phase: Architect
label: Write mechanical edit plan
as: editPlan
output: responses/edit-plan-response.md
outputMode: file-only

Task: {task}

Read `{chain_dir}/workspace/scout.md`, the plan artifact(s), and `{chain_dir}/workspace/plan-review.md` before writing any edit-plan. Then read the actual current code at every touched location.
If the plan review surfaced a human-owned decision or blocking ambiguity, or if a plan step cannot be made mechanical without an approach/reuse/scope decision the plan did not make, stop and report it instead of guessing. Otherwise, resolve the approved plan into mechanical edit-plan artifact(s) in `{chain_dir}/workspace`: `edit-plan.md` for `plan.md`, or `edit-plan-N.md` for `plan-N.md`.
You resolve file/symbol-level edit details; you do not redesign the planner's approach.

Plan review response:
{outputs.planReview}

## claude-pipeline.editor

phase: Implement
label: Apply edit plan
as: implementation
output: responses/implementation-response.md
outputMode: file-only
progress: true

Task: {task}

Read `{chain_dir}/workspace/scout.md` and the edit-plan artifact(s) before editing.
Apply only the approved edit-plan. Do not re-decide the approach, introduce abstractions, or reason around gaps. If an edit is ambiguous or requires reasoning, stop and report an architect escalation instead of guessing.
Write the matching implementation artifact in `{chain_dir}/workspace`: `implementation.md` for `edit-plan.md`, or `implementation-N.md` for `edit-plan-N.md`. Do not append evidence to the plan or edit-plan file.

Edit-plan response:
{outputs.editPlan}

## claude-pipeline.reviewer

phase: Implementation review
label: Review final implementation
as: implementationReview
output: responses/implementation-review-response.md
outputMode: file-only

Task: {task}

Review the implementation against the scout findings, plan artifact(s), plan review, edit-plan artifact(s), and implementation artifact(s) in `{chain_dir}/workspace`.
Inspect the actual code/diff directly and run the verification suite yourself where practical rather than relying only on editor output. Write `{chain_dir}/workspace/implementation-review.md` (or `implementation-N-review.md` for numbered plans) with verdict, blocking findings, plan adherence, optional findings, and what's good.

Implementation response:
{outputs.implementation}
