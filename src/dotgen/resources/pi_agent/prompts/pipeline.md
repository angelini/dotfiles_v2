---
description: Run the claude-pipeline scout → planner → architect → editor → reviewer workflow with a plan gate
argument-hint: <task description>
---

Orchestrate the five Pi subagents (`claude-pipeline.scout`, `claude-pipeline.planner`, `claude-pipeline.architect`, `claude-pipeline.editor`, `claude-pipeline.reviewer`) end-to-end for this task. The Pi pipeline mirrors the Claude split with GPT-5.6 variants: `scout` and `editor` use `openai-codex/gpt-5.6-terra` for cheaper high-throughput reading/editing, while `planner`, `architect`, and `reviewer` use `openai-codex/gpt-5.6-sol` for the reasoning-heavy stages.

**$ARGUMENTS**

Use the `subagent` tool directly. You are the orchestrator in the main thread. Pipeline subagents must not spawn each other; orchestration stays in this main thread. Pass the shared workspace path forward. The artifact chain is the source of truth — every stage reads the upstream file directly.

## Setup

Derive a kebab-case `<slug>` from the task and use workspace dir `docs/plans/<slug>/`. Pass this exact path to every stage. State it before beginning.

## Runtime defaults

Every `subagent` tool call in this pipeline must include `maxRuntimeMs: 600000` unless a longer budget is clearly needed. Do not use the 120000ms foreground default for pipeline stages; scout, planner, reviewer, architect, and editor often need several minutes to read, write artifacts, and validate. If a stage is expected to exceed 10 minutes, launch it with `async: true` instead of a short foreground timeout.

## Stages

1. **Scout.** Launch `claude-pipeline.scout` on the task; tell it to write `docs/plans/<slug>/scout.md`. If it reports the task is a one-sentence diff, stop the pipeline and do it directly.

2. **Plan.** Launch `claude-pipeline.planner`; tell it to read `scout.md` and write `plan.md` or serial `plan-1.md`, `plan-2.md`, etc.

3. **Review the plan, then gate with specific questions.** Launch `claude-pipeline.reviewer` to review the plan(s) against the scout findings and write `plan-review.md` (or `plan-N-review.md` for linked plans) in the workspace dir. Then collect every genuine open decision from three sources: the scout's **Open questions**, the planner's **Risks & decisions**, and the plan review's **blocking findings**. **Then stop and show the user** a tight summary: plan, blocking findings, workspace path.
   - If there are genuine unknowns or choices a human should make, ask them as **specific, concrete questions** — each with options and a recommended default — using `ask_user_question` where it fits. Do not ask a vague "look good?"; ask the actual decisions.
   - If nothing is genuinely ambiguous, say so and ask only for go-ahead-or-edits.
   - If the user chooses to revise the plan instead of proceeding, or their gate answers change a decision, re-launch `claude-pipeline.planner`; tell it to read the relevant `plan-review.md` / `plan-N-review.md` plus the user's answers and update the corresponding `plan.md` / `plan-N.md` in place. Then re-launch `claude-pipeline.reviewer` and return to this gate. Do this at most twice before proceeding with the best available plan or stopping to ask how to continue.
   - Skip this gate only if the arguments include `--auto`. In `--auto` mode, have the planner pick the recommended default for each open question and record the choice in the plan. If the plan review has blocking findings, run the same bounded re-plan and re-review loop before proceeding.

4. **Spec the edits (architect).** After the user approves, or immediately in `--auto` mode, launch `claude-pipeline.architect` for each plan in order. Tell it to read the plan + `scout.md` + the relevant `plan-review.md` / `plan-N-review.md`, read the actual current code, and write the matching edit-level spec: `edit-plan.md` for `plan.md`, or `edit-plan-N.md` for `plan-N.md`. The edit-plan must be precise enough that editing needs no decisions. If the architect stops because a step can't be made mechanical without a decision the plan didn't make (ambiguity, out-of-scope, plan contradicts code), treat it like a blocking plan finding: re-launch the planner to resolve it, bounded as in step 3, then re-run the architect.

5. **Apply the edits (editor).** Launch `claude-pipeline.editor` for each edit-plan in order. Tell it to read the edit-plan + `scout.md`, apply the edits exactly, run the edit-plan's verification, and write the matching implementation artifact: `implementation.md` for `edit-plan.md`, or `implementation-N.md` for `edit-plan-N.md` (commands run + output, files changed, and any escalations). If the editor escalates because an edit needs reasoning it must not do, re-launch `claude-pipeline.architect` to re-spec only the affected edits in the same edit-plan file, then re-launch the editor.

6. **Review the implementation.** Launch `claude-pipeline.reviewer` to review the code against the plan and edit-plan; it runs the verification suite itself where practical and writes `implementation-review.md` for `implementation.md`, or `implementation-N-review.md` for `implementation-N.md`.

7. **Fix loop, bounded and routed by finding kind.** If the implementation review has blocking findings, route each by kind: reasoning findings go to `claude-pipeline.architect` to update the relevant edit-plan, then `claude-pipeline.editor` applies it; purely mechanical findings go directly to `claude-pipeline.editor` with the relevant review, edit-plan, and `scout.md`. Then launch `claude-pipeline.reviewer` again. Repeat at most twice. If blockers remain after that, stop and report the wall rather than thrashing.

## Rules

- Pass the same workspace path to every stage; never let a stage re-summarize instead of reading the upstream artifact.
- Run stages serially — each depends on the previous artifact.
- Respect each subagent's contract: only `claude-pipeline.editor` edits code; the others are read-only except for their artifacts. The architect reasons and specs but never edits; the editor applies and verifies but never re-decides — it escalates to the architect instead.
- Use `context: "fresh"` for scout, planner, architect, and reviewer. Use one writer at a time for editor.
- At the end, report: workspace path, the artifact set (`scout.md`, plan(s), plan review(s), edit-plan(s), implementation artifact(s), implementation review(s)), what changed, verification results, and unresolved review findings.
