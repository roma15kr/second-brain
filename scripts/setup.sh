#!/usr/bin/env bash
# Installs Claude Code, Codex CLI and Gemini CLI (macOS / Linux / WSL).
set -e
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js not found. Install Node.js 20+ from https://nodejs.org and rerun."; exit 1
fi
NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
if [ "$NODE_MAJOR" -lt 20 ]; then echo "Node.js 20+ required (found $(node -v))."; exit 1; fi

echo "Installing AI CLIs..."
npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli @fission-ai/openspec@latest

echo; echo "Installed versions:"
claude --version || true
codex --version  || true
gemini --version || true
openspec --version || true

if command -v code >/dev/null 2>&1; then
  echo; echo "Installing VS Code extensions..."
  for ext in anthropic.claude-code openai.chatgpt google.geminicodeassist; do
    code --install-extension "$ext" || true
  done
fi

cat <<MSG

Done. First-time login (run each once):
  claude   -> sign in with your Anthropic account
  codex    -> sign in with ChatGPT or an OpenAI API key
  gemini   -> sign in with Google or a Gemini API key
MSG
