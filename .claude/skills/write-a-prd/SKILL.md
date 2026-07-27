---
name: write-a-prd
description: Turn an aligned design concept into a destination PRD (problem, solution, user stories, decisions, out-of-scope). Use after a grilling session.
---

# Write a PRD

Write a Product Requirements Document — the destination document.

Steps:
1. Ask me for a long, detailed description of the problem (or use our grilling session).
2. Explore the repo if this is a fresh session.
3. Interview me relentlessly on anything still ambiguous (one question at a time,
   with your recommended answer).
4. Propose the set of modules you intend to create or modify — keep the code in mind.
   Prefer deep modules with small interfaces.
5. Produce the PRD using the template below.

Write the file to `docs/prd-<slug>.md` (or `issues/`). Summarize faithfully — do
not invent scope. I will not read this closely, so it must be an accurate summary
of what we aligned on.

## Template

    # PRD: <feature>

    ## Problem statement
    <the problem the user faces>

    ## Solution
    <the approach>

    ## User stories (definition of done)
    - As a <role>, I can <action> so that <value>.

    ## Modules to create / modify
    - <module> — <interface / responsibility>

    ## Implementation decisions
    - <decision + rationale>

    ## Testing decisions
    - <what to test, at what boundary, with what fixtures>

    ## Out of scope
    - <what we explicitly decided NOT to do, incl. rejected alternatives>
