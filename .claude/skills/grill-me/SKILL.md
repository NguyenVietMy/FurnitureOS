---
name: grill-me
description: Interview me relentlessly to reach a shared understanding before any plan or code. Use at the very start of a feature or when requirements are fuzzy.
---

# Grill Me

Interview me relentlessly about every aspect of this plan until we reach a
shared understanding. Walk down each branch of the design tree, resolving
dependencies one by one.

Rules:
- Ask questions ONE AT A TIME.
- For each question, provide your RECOMMENDED answer.
- Explore the codebase first (use a sub-agent) so questions are grounded in reality.
- Surface hidden decisions I haven't considered (data backfill, edge cases, scope,
  auth, failure modes).
- Do NOT produce a plan or document yet. The goal is alignment, not an artifact.
- Continue until we have a genuine shared design concept, then stop and confirm.

You may also start from a pasted brief, Slack message, or meeting transcript and
grill through its unstated assumptions.
