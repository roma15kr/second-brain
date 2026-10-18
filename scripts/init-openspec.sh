#!/usr/bin/env bash
# Usage: ./scripts/init-openspec.sh [project-path]   (default: current dir)
# Sets up OpenSpec for Claude Code, Codex CLI and Gemini CLI. Safe to rerun.
set -e
# Add --reset-rules to replace an existing context/rules block with this template's version
# (a backup is saved as openspec/config.yaml.bak).
DIR="${1:-.}"; RESET_RULES="${2:-}"; cd "$DIR"
command -v openspec >/dev/null 2>&1 || { echo "Install first: npm install -g @fission-ai/openspec@latest"; exit 1; }

# Safe on existing projects: adds missing tools, refreshes the rest, keeps openspec/config.yaml.
openspec init --tools claude,codex,gemini,opencode --no-animation .

if [ "$RESET_RULES" = "--reset-rules" ] && grep -q '^context:' openspec/config.yaml; then
  cp openspec/config.yaml openspec/config.yaml.bak
  sed -i '/^context:/,$d' openspec/config.yaml
  echo "Old context/rules removed (backup: openspec/config.yaml.bak)"
fi

# Point OpenSpec at AGENTS.md instead of duplicating project context
if ! grep -q '^context:' openspec/config.yaml; then
cat >> openspec/config.yaml <<'YAML'

context: |
  Project rules, stack and commands are in AGENTS.md; architecture in docs/architecture.md;
  decisions in docs/decisions/; lessons learned in docs/learnings.md; current state in STATUS.md;
  customer and business evidence in docs/product/. Read them and follow them.
rules:
  proposal:
    - "Start with Problem (in the end user's words), Evidence (links to docs/product/inbox reports, feedback or issues) and Success metric (one number tied to the business, and how it is measured)."
    - "Include an Announcement: 3-5 sentences telling users about the change. If you cannot write it convincingly, say the change may be the wrong one."
    - "Include a Non-goals section."
    - "No implementation details (tables, endpoints, file names) in the proposal; they belong in design."
    - "For UI changes, create plain HTML mockups (no framework) in mockups/ inside the change folder, one file per screen."
  specs:
    - "Requirements describe observable behavior with WHEN/THEN scenarios, never implementation details."
  design:
    - "Read the relevant existing code before writing; never design against an imagined codebase."
    - "Include: Files (each file created or changed, and why), Types and signatures (no bodies), Call stack for each main flow, Test plan (test names and what each asserts)."
    - "End with Least confident decisions: a numbered list of the choices most worth challenging now."
    - "Record env var NAMES and external services in docs/external/ (never secret values)."
  tasks:
    - "Organize tasks as vertical slices. Slice 1 is a tracer bullet: thin, end to end and runnable. Then real logic one testable slice at a time. Never build horizontally (all database, then all API, then all UI)."
    - "Every slice ends in a working state, includes its tests, and is committed. A test must fail without the change it tests."
    - "Never skip, weaken or delete tests to get to green."
    - "The last task is always to update STATUS.md."
YAML
fi
echo "OpenSpec ready. Claude/Gemini: /opsx:propose  OpenCode: /opsx-propose  Codex: \$openspec-propose"
