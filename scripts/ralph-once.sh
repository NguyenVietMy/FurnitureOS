#!/usr/bin/env bash
# Run ONE implementation pass, human-in-the-loop. Run repeatedly to tune the
# prompt before going fully AFK. Best run inside a Docker sandbox / git worktree.
set -euo pipefail

ISSUES=$(cat ./issues/*.md 2>/dev/null || echo "no issues")
RECENT_COMMITS=$(git log -5 --oneline 2>/dev/null || echo "no commits yet")
PROMPT=$(cat ./prompts/implement.md)

claude --permission-mode acceptEdits "$PROMPT

## Issues (backlog)
$ISSUES

## Recent commits
$RECENT_COMMITS
"
