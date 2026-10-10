# 0002. Use OpenSpec for spec-driven development
Date: YYYY-MM-DD
Status: accepted

## Context
AI agents lose intent between sessions. Requirements living only in chat get lost,
and switching between Claude, Codex and Gemini must not lose them either.

## Decision
Use OpenSpec. `openspec/specs/` holds living behavior specs; every feature or
behavior change goes through a change folder (proposal, design, tasks, spec deltas):
propose → review → apply → archive. Small fixes skip the change folder.
OpenSpec is installed for all four tools with `openspec init --tools claude,codex,gemini,opencode`.

## Consequences
Specs must be updated (archived) in the same work as the code, or they rot.
Slight overhead per feature; not used for trivial fixes.
