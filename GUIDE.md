# FurnitureOS — how we build here

Read this first. It describes the intended workflow, where the skills live, and the traps that will bite you.

## Where the project stands

The repo was reset on 2026-09-07. One commit, no application code yet — domain docs and the skill set only. The old `main` (walking skeleton, unit gallery, catalogue panel, collisions) was force-pushed away deliberately and is gone.

So: **there is no test runner and no proof command yet.** The first phase you build has to create one. See [Traps](#traps).

## The short version

Start in **Codex with GPT-6 Astra**, in this directory. Say what you want to build, or invoke `astra-loop`. Astra runs the whole thing; you answer questions and sign off at gates.

```
Astra grills you  →  Astra drafts PLAN.md  →  Claude reviews it ×3
  →  plan splits into GitHub issues  →  per phase: Claude builds, fresh Codex inspects
```

Every delegated agent runs in its own **labelled Herdr tab**, so you can watch the
conversation and step in without anything resizing your layout. Astra is the orchestrator the whole way. Claude never plans;
Astra never reads a diff.

## Roles

Verified live — both `claude` and `codex` start cleanly as Herdr agents:

| Role | Who | Session |
|---|---|---|
| Planner / orchestrator / arbitrator | **Astra** | Your conversation |
| Plan reviewer | **Claude** | One `reviewer` tab, reprompted across the 3 rounds |
| Builder | **Claude** | Fresh `builder-p<N>` tab per phase |
| Diff inspector | **Codex** | **Fresh** `inspector-p<N>` tab every inspection — never your conversation |

The inspector is Codex because the *builder* is Claude, and the rule is that whoever built cannot certify their own work.

## How they actually talk

Astra doesn't call Claude's API. It **opens a Herdr tab** and starts a real interactive
Claude in it, then talks to it over the Herdr CLI:

```bash
herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$PWD" --label reviewer --no-focus
herdr agent start reviewer --kind claude --pane <root_pane.pane_id> -- <flags>
herdr agent prompt reviewer "<task> ... write your result to <path>" --wait --timeout 600000
```

The reply comes back **as a file**, not as terminal text. Astra reads the file. That split
is the whole trick: the tab is your window, the file is the data channel.

Reading the terminal instead would break two things at once — it drags raw content into
Astra's context, and it isn't even reliable, because rows lost to an agent's alternate
screen never reach scrollback. So `herdr agent read` is for diagnosing a stuck agent only.

Session continuity is just the tab: reprompting the same named agent continues its session,
so there's no `--resume` UUID to juggle. Herdr reports the underlying session id anyway, as
`agent_session.value`.

One quirk worth knowing when you're debugging: a background tab settles on **`done`**, not
`idle`. Herdr reserves `idle` for a tab you've actually looked at, and a delegate tab created
with `--no-focus` never has been. `done` is success.

## The five stages

### 1. Grill

Astra runs the `grilling` skill: works the design tree in rounds, asks the whole frontier at once with a recommendation for each, waits for you. It reads `CONTEXT.md` and `docs/adr/` first so the questions use the right vocabulary.

Don't let it skip to a plan while questions are open. That is the failure mode this stage exists to prevent.

### 2. Draft the plan

Astra writes `PLAN.md` **outside the repo**, under `%TEMP%/astra-loop/<feature-slug>/`. Goal, acceptance criteria, approach, trade-offs, non-goals, assumptions with sources, and exact proof commands.

### 3. Three rounds of Claude review

Astra sends the plan to Claude in a separate read-only session and gets back a structured verdict: `APPROVED`, `REVISE`, or `BLOCKED`, with evidence-backed findings.

**Each round Astra arbitrates and then stops for you.** You see a table of every finding, its severity, Astra's disposition and its reasoning. Your sign-off gates the next round. Three rounds max, then it reports what's unresolved rather than pretending to converge.

`APPROVED` is bound to that exact plan file and its SHA256. Edit the plan afterwards and the approval is void.

### 4. Split into phases

Astra runs `phase-split` against the approved plan and proposes **tracer bullets**: each phase a narrow but complete path through every layer, demoable on its own, sized for one fresh context window, declaring what blocks it.

You approve the breakdown, then it publishes one GitHub issue per phase in dependency order, labelled `ready-for-agent`, per `docs/agents/issue-tracker.md`.

A phase is *not* "set up the database layer" — that's a horizontal slice and `phase-split` rejects it.

### 5. Build and inspect, phase by phase

Working the frontier (any phase whose blockers are closed), for each one:

1. Astra writes `phase-N.md` from the issue body, outside the repo
2. Records the pre-build commit — the inspection baseline
3. **Claude builds** it in a fresh session
4. **Astra runs the proof commands itself** — a builder's own success report is not verification
5. **A fresh Codex session inspects** the diff against the baseline
6. Accepted findings get fixed and re-inspected in another fresh session (up to 3 fix rounds and 3 total inspections per phase; the inspection count includes the initial review)
7. Issue closes only when criteria are met and inspection is clean

## Context hygiene — the point of the whole design

**Astra never reads a raw diff.** No `git diff`, no `git show`, no reading changed files wholesale in the orchestrator conversation. The inspector process reads the diff; Astra reads only its `result.json` — verdict, findings, coverage, limitations.

This is why the orchestrator can carry a 6-phase feature without its context filling with code it doesn't need. If Astra starts quoting diffs at you, something has gone wrong; tell it to stop and re-read this section.

## Where things live

```
.claude/skills/              30 skills — the editable source of truth
  astra-loop/                the workflow above
  claudex-loop/              shared machinery
    scripts/runner.py        the executable that launches the other CLI
    references/{build,runtime}.md
  grilling/  phase-split/  tdd/  ...
.claude-plugin/              marketplace manifest → points at ./.claude
.claude/.claude-plugin/      plugin manifest → skills ./skills/
scripts/sync-codex-skills.ps1
```

**I read `.claude/skills/` automatically** (Claude project skills). **Astra reads a snapshot** installed as the `furnitureos-skills` plugin from the local `furnitureos` marketplace.

## After you tweak a skill

Claude picks up edits immediately, on the next session. **Astra does not.**

Codex snapshots a local marketplace at install time, and `codex plugin marketplace upgrade` only refreshes *Git* marketplaces. So after editing any skill:

```powershell
.\scripts\sync-codex-skills.ps1
```

That does a `codex plugin remove` + `add` cycle and prints the skill count. Forget it and Astra silently runs yesterday's version of your skill.

## Traps

**No proof command exists yet.** Make phase 1 a tracer bullet that *carries its own test*, so building it establishes the test runner as a side effect. Phases 2+ then have something real to derive from. Don't create a "set up tooling" phase with no behaviour in it.

**Delegated builds require a clean checkout.** Uncommitted work fails the gate before Claude writes a line. Commit or use a worktree — don't stash another session's work.

**Keep artifacts out of the repo.** Plans and logs written into the checkout make it dirty and fail that same gate. They live under `%TEMP%/astra-loop/`. They may contain private code; never commit them.

**Exit code 0 ≠ APPROVED.** A zero exit means the CLI turn completed. The verdict inside `result.json` may still be `REVISE` or `BLOCKED`.

**Two skills are renamed, deliberately.**
- `code-review` → **`mp-code-review`**, so it stops shadowing Claude Code's built-in `/code-review`.
- `to-tickets` → **`phase-split`**, because Codex silently refuses to register a local skill whose name collides with an entry in its remote plugin catalog — and mattpocock's `to-tickets` is in that catalog. The skill was invisible to Astra under the old name with no error.

That second one generalises: **if you flip a slash-only skill to model-invocable and Astra can't see it, the name is probably colliding with the catalog.** Rename it.

**Astra must actually be Astra.** `~/.codex/config.toml` sets `model = "gpt-5.6-terra"`, so a session you don't switch is not Astra. Check the model before you start planning.

**Start Codex inside Herdr, not in a bare terminal.** The workflow opens tabs, so Astra must be running as a Herdr agent itself — `echo $HERDR_ENV` has to print `1`. Launched outside Herdr it cannot create a tab, and the skill will stop rather than silently fall back to headless.

**The reviewer has no shell.** Its `--tools Read,Glob,Grep,Write` allowlist is what keeps it from touching the repo — not the permission prompt, which we bypass. If you ever hand a reviewer `Bash`, it stops being a reviewer.

## Command reference

Astra runs these itself; they're here for when you need to debug.

```bash
# am I even inside Herdr?  (must print 1)
echo "$HERDR_ENV"; echo "$HERDR_WORKSPACE_ID $HERDR_TAB_ID $HERDR_PANE_ID"

# what's running right now
herdr agent list
herdr tab list --workspace "$HERDR_WORKSPACE_ID"

# look at a delegate that seems stuck  (diagnosis only, never to collect findings)
herdr agent get reviewer
herdr agent read reviewer --source recent-unwrapped --lines 120
herdr agent wait reviewer --until blocked --timeout 120000

# take it over by hand
herdr agent focus reviewer
herdr agent attach reviewer

# tidy up a delegate you're done with
herdr tab close <tab-id>
```

Delegate flags, as verified on this machine:

| Delegate | Kind | Flags after `--` |
|---|---|---|
| Reviewer | `claude` | `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools Read,Glob,Grep,Write --allowedTools Read,Glob,Grep,Write --dangerously-skip-permissions` |
| Builder | `claude` | `--dangerously-skip-permissions` |
| Inspector | `codex` | `--dangerously-bypass-approvals-and-sandbox` |

`runner.py` is no longer the transport, but it still documents the gates Astra now enforces
by hand — approval binding, clean checkout, baseline commit, diff manifest. Read
`.claude/skills/claudex-loop/scripts/runner.py` if you need to know what a gate was meant to do.

## If you only remember one thing

Open Herdr, start Codex, switch it to Astra, `cd` here, and say what you want to build.
Let it drive: answer the grilling honestly, sign off each review round, approve the phase
breakdown. Flip through the delegate tabs as they work — that's what they're for. Don't let
the orchestrator read diffs, and run the sync script after you edit a skill.
