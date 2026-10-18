# Installs Claude Code, Codex CLI and Gemini CLI (Windows PowerShell).
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Host "Node.js not found. Install Node.js 20+ from https://nodejs.org and rerun."; exit 1
}
$major = [int](node -p "process.versions.node.split('.')[0]")
if ($major -lt 20) { Write-Host "Node.js 20+ required."; exit 1 }

Write-Host "Installing AI CLIs..."
npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli @fission-ai/openspec@latest

claude --version; codex --version; gemini --version; openspec --version

if (Get-Command code -ErrorAction SilentlyContinue) {
  foreach ($ext in "anthropic.claude-code","openai.chatgpt","google.geminicodeassist") {
    code --install-extension $ext
  }
}
Write-Host "`nDone. Run 'claude', 'codex' and 'gemini' once each to sign in."
