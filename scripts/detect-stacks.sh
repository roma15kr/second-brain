#!/usr/bin/env bash
# Detects the project's stacks from files in its root folder and writes them to STACKS in the
# Makefile, but only when STACKS is still empty (a value you set yourself is never changed).
# Usage: ./scripts/detect-stacks.sh [project-path]     Prints the detected stacks.
set -euo pipefail
cd "${1:-.}"

stacks=()
[ -f composer.json ] && stacks+=(php)
if [ -f pyproject.toml ] || [ -f requirements.txt ] || [ -f setup.py ] || [ -f Pipfile ]; then
  stacks+=(python)
fi
if [ -f package.json ] || [ -f tsconfig.json ]; then
  stacks+=(ts)
fi
detected="${stacks[*]:-}"
echo "Detected stacks: ${detected:-none}"

if [ -f Makefile ] && grep -q '^include make/stack.mk' Makefile; then
  if grep -qE '^STACKS :=[[:space:]]*$' Makefile; then
    if [ -n "$detected" ]; then
      sed -i "s/^STACKS :=[[:space:]]*$/STACKS := $detected/" Makefile
      echo "Makefile: STACKS := $detected"
    else
      echo "Makefile: no stack files found yet. When you add one, run this script again"
      echo "or set STACKS in Makefile by hand (php python ts)."
    fi
  else
    echo "Makefile: STACKS already set ($(sed -n 's/^STACKS := *//p' Makefile)), not changed."
  fi
elif [ -f Makefile ]; then
  echo "This project has its own Makefile. To add the standard targets (check, test, lint, ...),"
  echo "add these two lines near the top of it, and rename any of your targets that clash:"
  echo "  STACKS := ${detected:-<php python ts>}"
  echo "  include make/stack.mk"
fi
