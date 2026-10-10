# 0001. Tool-agnostic AI agent setup
Date: YYYY-MM-DD
Status: accepted

## Context
Several AI coding agents are used (Claude Code, Codex CLI, Gemini CLI, OpenCode).
AI tools lose context between sessions and do not share memory.

## Decision
The repository is the single source of memory:
AGENTS.md (rules), STATUS.md (handoff), docs/ (architecture, decisions), tests.
CLAUDE.md and GEMINI.md only import AGENTS.md; Codex and OpenCode read AGENTS.md directly.

## Consequences
Any agent can continue work after reading the files.
STATUS.md must be updated at the end of every session.
