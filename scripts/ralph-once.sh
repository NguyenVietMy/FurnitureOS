#!/usr/bin/env bash
# Run ONE implementation pass. Run repeatedly to tune the prompt before going
# fully AFK.
#
# --dangerously-skip-permissions means no prompt for anything: every edit, every
# shell command, every network call runs unattended. Run this inside a Docker
# sandbox or a throwaway git worktree, not on a checkout you care about.
set -euo pipefail

ISSUES=$(cat ./issues/*.md 2>/dev/null || echo "no issues")
RECENT_COMMITS=$(git log -5 --oneline 2>/dev/null || echo "no commits yet")
PROMPT=$(cat ./prompts/implement.md)

claude --dangerously-skip-permissions "$PROMPT

## Issues (backlog)
$ISSUES

## Recent commits
$RECENT_COMMITS
"
