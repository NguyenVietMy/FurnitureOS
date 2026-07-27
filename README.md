# AI Coding Starter

A fresh-project skeleton for the "software fundamentals + AI" workflow
(Matt Pocock / AI Hero). Everything before implementation is human-reviewed.

## Pipeline

    Idea -> Grill -> PRD -> Kanban (vertical-slice issues) -> Implement (AFK) -> QA / review

## Layout

    CLAUDE.md              push channel: tiny, always-on
    .claude/skills/        pull channel: process skills the agent fetches on demand
    docs/                  durable knowledge (curate; do not let it rot)
    issues/                active vertical-slice tickets
    issues/archive/        shipped tickets — out of the agent's default path
    scripts/ralph-once.sh  one AFK implementation pass (run repeatedly to tune)
    prompts/               prompts referenced by scripts (implement, review)

## First-feature loop

1. Clear context. Run the `grill-me` skill on your idea.
2. Run `write-a-prd` -> a destination doc in docs/ or issues/ (don't read it closely).
3. Run `prd-to-issues` -> vertical-slice tickets with blocking relationships.
4. `bash scripts/ralph-once.sh` a few times, human-in-the-loop, to tune.
5. Let it run AFK.
6. Review in a FRESH context, then manually QA (file new tickets as you go).
7. Archive the PRD/issue when shipped.

## Push vs. pull

- Push = always-on (CLAUDE.md, review-time standards).
- Pull = fetched on demand (skills).
- Standards the agent must obey -> push into review. How-tos it occasionally needs -> skills.
