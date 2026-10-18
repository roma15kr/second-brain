---
description: Review current changes (use a different AI than the one that wrote them)
---

Review the current changes as a careful senior reviewer. Another AI (or I) wrote them;
look for what the author could have missed. Do not edit any code.

1. Find the changes: `git diff` and `git diff --staged`; if both are empty, review the branch
   against the main branch (`git diff $(git merge-base HEAD main)..HEAD`).
2. Read AGENTS.md, docs/learnings.md and, if an OpenSpec change is active (`openspec list`),
   its proposal.md, specs and design.md.
3. Check: does the code do what the proposal/specs say (missing or extra behavior)? Are tests
   real (would they fail without the change, none skipped or weakened)? AGENTS.md rules,
   architecture boundaries, error handling, security.
4. Run `make check` (the main gate from AGENTS.md) and report the result.

Answer in this format:
Verdict: APPROVE | CHANGES REQUESTED
- BLOCKING: <file:line> <problem> -> <fix>      (only real defects)
- SUGGESTION: <file:line> <problem> -> <fix>
Lesson: <if a mistake could happen again, one general rule for docs/learnings.md; else "none">
