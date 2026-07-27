---
name: prd-to-issues
description: Break a PRD into independently grabbable vertical-slice (tracer-bullet) issues with blocking relationships. Use after a PRD exists.
---

# PRD to Issues

Break the PRD into independently grabbable issues using VERTICAL SLICES
(tracer bullets). Write them as local markdown files in `./issues/`.

Steps:
1. Locate the PRD.
2. Explore the codebase if this is a fresh session.
3. Draft vertical slices: each slice must cut through EVERY layer it touches
   (schema change + new/updated service + a minimal VISIBLE representation).
   Reject horizontal slices (all-DB, then all-API, then all-UI) — they give no
   feedback until the end.
4. Set blocking relationships so a DAG forms (this enables parallel agents).
5. Tag each issue: AFK (an agent can do it alone) or HUMAN (needs a human).
6. Quiz me on anything unclear, then create one markdown file per issue.

## Issue file template (issues/NN-slug.md)

    # NN — <title>

    Type: AFK | HUMAN
    Blocked by: <issue numbers, or none>

    ## Stories delivered
    - ...

    ## Reviewable end state
    <something I can QA immediately once this is done>

    ## Notes
    <constraints, module boundaries, test boundary>
