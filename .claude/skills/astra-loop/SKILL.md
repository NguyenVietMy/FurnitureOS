---
name: astra-loop
description: "The FurnitureOS feature workflow, hosted in Codex. Grill the user into a plan, harden it through three rounds of independent Claude review, split it into GitHub issues, then build phase by phase with Claude as executor and a fresh inspector on every phase diff. Use for 'astra-loop', 'new feature', or 'let's build X'."
---

# Astra Loop

Astra hosts every stage. Claude reviews the plan, Claude builds, and a **fresh Codex session** inspects each phase diff. The orchestrator conversation owns requirements, arbitration and sequencing, and never becomes a reader of raw diffs.

## Roles

| Stage | Who | Session |
|---|---|---|
| Grill, plan, arbitrate | Astra | This conversation |
| Plan review | Claude | Fresh CLI session per round, resumed within a round |
| Build | Claude | Fresh CLI session per phase |
| Diff inspection | Codex | **Fresh** CLI session per phase, never this one |

Roles are fixed here; this skill is the `host=codex, builder=claude` configuration of [claudex-loop](../claudex-loop/SKILL.md). Do not swap them mid-run. Read [the runtime reference](../claudex-loop/references/runtime.md) before the first CLI launch and [the build reference](../claudex-loop/references/build.md) before the first build.

Resolve the runner as `../claudex-loop/scripts/runner.py` relative to **this installed SKILL.md**, not relative to FurnitureOS. Use its absolute path. `RUNNER` below is that path.

## Tunables

| Argument | Default | Meaning |
|---|---|---|
| `PLAN_FILE` | `<ARTIFACTS>/PLAN.md` | Feature plan. Lives **outside** the checkout. |
| `LOG_FILE` | `<ARTIFACTS>/ASTRA-LOG.md` | Append-only transcript of rounds and dispositions. |
| `ARTIFACTS` | `%TEMP%/astra-loop/<feature-slug>` | Run directory outside the repo. |
| `rounds` | `3` | Plan-review rounds before stopping. |
| `reviewer_model` | CLI default | Claude reviewer, e.g. `claude-fable-5-1`. |
| `MAX_FIX_ROUNDS` | `2` | Build-fix attempts per phase. |
| `MAX_INSPECTION_ROUNDS` | `2` | Inspections per phase: initial, plus one after fixes. |

Echo roles, paths, round limits and requested models before starting.

**Artifacts must live outside the checkout.** A delegated build requires a clean checkout, and a plan or log written into the repo makes it dirty and fails the gate.

## Stage 1 — Grill

Run the [grilling](../grilling/SKILL.md) skill against the feature. Work the design tree in rounds: ask the whole frontier at once, numbered, each with your recommended answer, then wait. Do not draft a plan while questions remain open.

Read `CONTEXT.md` and the ADRs under `docs/adr/` first, and use that vocabulary in your questions. Record a new ADR only for an expensive-to-reverse, non-obvious trade-off.

## Stage 2 — Draft the plan

Write `PLAN_FILE` with goal and observable acceptance criteria, the approach with its key decisions, trade-offs and non-goals, confirmed assumptions with sources, residual risks, and exact proof commands with expected results. Derive proof commands from the repo; ask only if what counts as success is genuinely unclear.

Start `LOG_FILE` with roles, model requests, scope, authorization and round limits.

## Stage 3 — Three rounds of Claude review

```text
python RUNNER review --host codex --repo . --plan PLAN_FILE --artifacts ARTIFACTS
```

Round 1 creates the session. Later rounds resume it:

```text
python RUNNER review --host codex --repo . --plan PLAN_FILE --artifacts ARTIFACTS --resume PREVIOUS_RESULT_JSON --feedback DISPOSITIONS_FILE
```

Repeat the same `--model`/`--effort` when resuming; the runner refuses mismatches. Never use `--last` or a guessed session id.

Each round, **you arbitrate**: judge every finding, implement the ones you accept, and reject the rest with reasons. Then **stop and show the user** a table of finding, severity, your disposition and rationale before sending the revised plan back. Their sign-off gates the next round. Write dispositions to `DISPOSITIONS_FILE` yourself from the logged findings.

Exit code zero means a completed turn, **not APPROVED**. Read `result.json`:

- **APPROVED** — bound to that exact plan path and SHA256. Any later edit voids it.
- **REVISE** — arbitrate, revise, resend.
- **BLOCKED or malformed** — never approval. Report the missing evidence. Do not burn rounds on blind retries or silently switch provider or model.

Stop at `rounds`. If findings remain unresolved, present them with your position rather than manufacturing convergence. Before building, run the approval check on the final plan:

```text
python RUNNER check --host codex --repo . --plan PLAN_FILE --approval APPROVED_RESULT_JSON
```

## Stage 4 — Split into phases

Run [phase-split](../phase-split/SKILL.md) against the approved plan. Each phase is a **tracer bullet**: a narrow but complete path through every layer, demoable on its own, sized to fit one fresh context window, declaring the phases that block it. Prefactoring goes first. A wide refactor is the exception and is sequenced expand–contract instead.

Present the numbered breakdown and iterate until the user approves it, then publish one GitHub issue per phase in dependency order via `gh`, per `docs/agents/issue-tracker.md`, labelled `ready-for-agent`.

Skip this stage only if the plan already carries an approved phase breakdown.

## Stage 5 — Build and inspect, phase by phase

Work the **frontier**: any phase whose blockers are all closed. For each phase, in order:

**1. Materialise the phase spec.** Write `<ARTIFACTS>/phase-<N>.md` from the issue body — outside the checkout. Never pass the whole feature plan as a phase spec.

**2. Record the pre-build commit.** That SHA is the inspection baseline.

**3. Build with Claude.**

```text
python RUNNER build --host codex --builder claude --repo . --plan ARTIFACTS/phase-N.md --approval APPROVED_RESULT_JSON --proof "EXACT_PROOF_COMMAND" --artifacts ARTIFACTS
```

The checkout must be clean first. Use a worktree for isolation rather than stashing live work. Do not create commits merely to pass the gate without authorization.

**4. Run the proof commands yourself.** A builder's own success report is not verification.

**5. Inspect in a fresh Codex session.**

```text
python RUNNER inspect --host codex --builder claude --repo . --plan ARTIFACTS/phase-N.md --base PRE_BUILD_COMMIT --artifacts ARTIFACTS
```

The runner supplies the diff plus a manifest of changed and untracked files, and refuses approval if code changes mid-inspection.

**6. Disposition findings.** Fix accepted ones via `--resume PREVIOUS_BUILD_RESULT --feedback FIX_LIST` against the same baseline, rerun affected proofs, then re-inspect in another fresh session. Stop at `MAX_FIX_ROUNDS` and `MAX_INSPECTION_ROUNDS`; report what remains rather than claiming approval.

**7. Close the issue** only after its acceptance criteria are met and its inspection is clean. Then take the next frontier phase.

## Context hygiene

This is a hard constraint, not a preference.

- **Never read a raw diff into this conversation.** `git diff`, `git show` and reading changed files wholesale are all off-limits here. The inspector reads the diff; you read its `result.json`.
- From an inspection, take only verdict, findings, coverage and limitations. Leave evidence bodies in the artifact directory and cite them by path.
- Each phase's build and inspection are separate processes. Do not carry one phase's file-level detail into the next; the phase spec and the issue are the interface.
- If you take over coding yourself, you have become a builder. A fresh Claude session must then inspect your changes, and the earlier inspection does not cover them.
- Artifact directories may contain private code and plans. Keep them outside the checkout and never commit them.

## Reporting

Close the run with: phases delivered, proof results per phase, inspection coverage, unresolved findings, deviations from the plan, and rounds used against budget. Commits, pushes and releases follow existing authorization; running this loop does not imply any of them.
