#!/usr/bin/env bash
# Multi-agent development pipeline on top of OpenSpec.
#   scout -> (you) triage -> plan -> (you) approve -> build -> review -> fix -> (you) merge -> learn
# Each role can run on a different AI (see factory.conf). Nothing is merged or pushed automatically.
set -eo pipefail

ROOT="$(git rev-parse --show-toplevel 2> /dev/null)" || {
  echo "Run this inside a git repository." >&2
  exit 1
}
cd "$ROOT"
if [ -f factory.conf ]; then
  # shellcheck source=/dev/null
  . ./factory.conf
fi
set -u

SCOUT_AGENT="${SCOUT_AGENT:-gemini}"
PLANNER_AGENT="${PLANNER_AGENT:-claude}"
BUILDER_AGENT="${BUILDER_AGENT:-claude}"
REVIEWER_AGENT="${REVIEWER_AGENT:-codex}"
LEARNER_AGENT="${LEARNER_AGENT:-claude}"
AGENT_FALLBACK_ORDER="${AGENT_FALLBACK_ORDER:-claude codex gemini opencode}"
BASE_BRANCH="${BASE_BRANCH:-$(git symbolic-ref --short HEAD 2> /dev/null || echo main)}"
CLAUDE_ALLOWED_TOOLS="${CLAUDE_ALLOWED_TOOLS:-}"

ROLES_DIR="$ROOT/docs/ai/roles"
STATE_DIR="$ROOT/.factory"
METRICS="docs/metrics/changes.md"
REPO_NAME="$(basename "$ROOT")"

usage() {
  cat << 'EOF'
Usage: ./scripts/factory.sh <command> [args]

  status                      Inbox, active changes, worktrees
  scout [agent]               Turn docs/product/signals/ (+ issues, analytics) into inbox reports
  triage [agent]              Interactive: rank the inbox with an AI, you decide
  plan <change> <input> [agent]
                              Write an OpenSpec change. <input> = inbox report path or idea text
  approve <change>            Validate and commit the plan (the human gate)
  build <change> [agent]      Implement in an isolated worktree, slice by slice
  review <change> [agent]     Review by a DIFFERENT AI; writes review.md + metrics
  fix <change> [agent]        Builder addresses review.md
  finish <change>             After you merged: remove the worktree and branch
  learn [agent]               Turn repeated mistakes into rules (docs/learnings.md, AGENTS.md)

Agents: claude | codex | gemini | opencode   (defaults in factory.conf)
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

need_agent() {
  command -v "$1" > /dev/null 2>&1 || die "'$1' is not installed or not in PATH"
}

role_prompt() {
  local role="$1" input="$2"
  [ -f "$ROLES_DIR/$role.md" ] || die "missing role file $ROLES_DIR/$role.md"
  printf '%s\n\n## Task input\n%s\n' "$(cat "$ROLES_DIR/$role.md")" "$input"
}

# run_agent <agent> <safe|full> <dir> <prompt>
#   safe: may edit files, very limited shell (planning, scouting, learning)
#   full: may run any command inside <dir> (building/reviewing in an isolated worktree)
run_agent() {
  local agent="$1" level="$2" dir="$3" prompt="$4"
  need_agent "$agent"
  echo "==> $agent ($level) in $dir"
  case "$agent" in
    claude)
      local -a perm
      if [ "$level" = full ]; then
        perm=(--permission-mode bypassPermissions)
      else
        # shellcheck disable=SC2206
        perm=(--permission-mode acceptEdits --allowedTools "Bash(git:*)" "Bash(openspec:*)" "Bash(gh issue list:*)" "Bash(gh issue view:*)" $CLAUDE_ALLOWED_TOOLS)
      fi
      (cd "$dir" && printf '%s' "$prompt" | claude -p "${perm[@]}")
      ;;
    codex)
      codex exec -C "$dir" -s workspace-write "$prompt"
      ;;
    gemini)
      local mode=auto_edit
      [ "$level" = full ] && mode=yolo
      (cd "$dir" && gemini --approval-mode "$mode" -p "$prompt")
      ;;
    opencode)
      local -a auto=()
      [ "$level" = full ] && auto=(--auto)
      (cd "$dir" && opencode run "${auto[@]}" "$prompt")
      ;;
    *) die "unknown agent '$agent' (use claude, codex, gemini or opencode)" ;;
  esac
}

change_dir() { echo "openspec/changes/$1"; }
worktree_of() { echo "$(dirname "$ROOT")/$REPO_NAME-$1"; }
state_get() {
  local f="$STATE_DIR/$1.env"
  if [ -f "$f" ]; then
    grep "^$2=" "$f" | cut -d= -f2- || true
  fi
}
state_set() {
  mkdir -p "$STATE_DIR"
  local f="$STATE_DIR/$1.env"
  touch "$f"
  grep -v "^$2=" "$f" > "$f.tmp" || true
  echo "$2=$3" >> "$f.tmp"
  mv "$f.tmp" "$f"
}

pick_reviewer() {
  local builder="$1" wanted="$2" a
  if [ "$wanted" != "$builder" ] && command -v "$wanted" > /dev/null 2>&1; then
    echo "$wanted"
    return
  fi
  for a in $AGENT_FALLBACK_ORDER; do
    if [ "$a" != "$builder" ] && command -v "$a" > /dev/null 2>&1; then
      echo "$a"
      return
    fi
  done
  die "need a reviewer agent different from the builder ($builder)"
}

valid_name() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "change name must be kebab-case, e.g. add-csv-export"
}

cmd_status() {
  echo "== Inbox (new/updated)"
  grep -l -E '^Status: (new|updated)' docs/product/inbox/*.md 2> /dev/null | sed 's#^#  #' || echo "  (empty)"
  echo
  echo "== OpenSpec changes"
  openspec list 2> /dev/null || echo "  openspec not available"
  echo
  echo "== Worktrees"
  git worktree list
}

cmd_scout() {
  local agent="${1:-$SCOUT_AGENT}"
  run_agent "$agent" safe "$ROOT" "$(role_prompt scout "Today is $(date +%F). Process all new signals.")"
  echo
  echo "Next: review docs/product/inbox/, then run: ./scripts/factory.sh triage"
}

cmd_triage() {
  local agent="${1:-$PLANNER_AGENT}"
  need_agent "$agent"
  local prompt
  prompt="$(role_prompt triage "Today is $(date +%F).")"
  echo "Starting an interactive $agent session for triage..."
  case "$agent" in
    claude) claude "$prompt" ;;
    codex) codex "$prompt" ;;
    gemini) gemini -i "$prompt" ;;
    opencode) opencode --prompt "$prompt" ;;
    *) die "unknown agent '$agent'" ;;
  esac
}

cmd_plan() {
  local change="${1:-}" input="${2:-}" agent="${3:-$PLANNER_AGENT}"
  if [ -z "$change" ] || [ -z "$input" ]; then
    die "usage: plan <change> <inbox-report-path|idea text> [agent]"
  fi
  valid_name "$change"
  if [ -f "$input" ]; then
    input="Change name: $change
Inbox report: $input

$(cat "$input")"
  else
    input="Change name: $change
Idea: $input"
  fi
  run_agent "$agent" safe "$ROOT" "$(role_prompt planner "$input")"
  echo
  echo "Next: read $(change_dir "$change")/ (especially 'Least confident decisions'),"
  echo "edit or ask for changes, then run: ./scripts/factory.sh approve $change"
}

cmd_approve() {
  local change="${1:-}"
  [ -n "$change" ] || die "usage: approve <change>"
  local dir
  dir="$(change_dir "$change")"
  [ -d "$dir" ] || die "no change folder $dir"
  openspec validate "$change" || die "fix validation errors before approving"
  printf 'Approved by %s on %s\n' "$(git config user.name || whoami)" "$(date +%F)" > "$dir/.approved"
  git add "$dir" docs/product
  git commit -m "docs(openspec): approve $change" > /dev/null
  echo "Approved and committed. Next: ./scripts/factory.sh build $change"
}

cmd_build() {
  local change="${1:-}" agent="${2:-$BUILDER_AGENT}"
  [ -n "$change" ] || die "usage: build <change> [agent]"
  [ -f "$(change_dir "$change")/.approved" ] || die "change '$change' is not approved yet (run: approve $change)"
  local wt
  wt="$(worktree_of "$change")"
  if [ ! -d "$wt" ]; then
    git worktree add -b "change/$change" "$wt" "$BASE_BRANCH"
  fi
  state_set "$change" BUILDER "$agent"
  state_set "$change" WORKTREE "$wt"
  run_agent "$agent" full "$wt" "$(role_prompt builder "Change: $change
Change folder: $(change_dir "$change")
Base branch: $BASE_BRANCH")"
  echo
  echo "Next: ./scripts/factory.sh review $change"
}

count_matches() {
  local n
  n=$(grep -c -- "$1" "$2" 2> /dev/null) || true
  echo "${n:-0}"
}

cmd_review() {
  local change="${1:-}"
  [ -n "$change" ] || die "usage: review <change> [agent]"
  local wt builder reviewer round review
  wt="$(state_get "$change" WORKTREE)"
  if [ -z "$wt" ] || [ ! -d "$wt" ]; then die "no worktree for '$change' (run: build $change)"; fi
  builder="$(state_get "$change" BUILDER)"
  reviewer="$(pick_reviewer "$builder" "${2:-$REVIEWER_AGENT}")"
  local previous
  previous=$(grep -c -F "| $change |" "$wt/$METRICS" 2> /dev/null) || true
  round=$((${previous:-0} + 1))

  run_agent "$reviewer" full "$wt" "$(role_prompt reviewer "Change: $change
Change folder: $(change_dir "$change")
Base branch: $BASE_BRANCH
Review round: $round
Builder was: $builder")"

  review="$wt/$(change_dir "$change")/review.md"
  [ -f "$review" ] || die "reviewer did not write $review"
  if [ -n "$(git -C "$wt" status --porcelain -- . ":(exclude)$(change_dir "$change")/review.md")" ]; then
    echo "Warning: the reviewer left uncommitted changes besides review.md. Check 'git -C $wt status'."
  fi

  local blocking suggestions verdict
  blocking=$(count_matches '^- BLOCKING' "$review")
  suggestions=$(count_matches '^- SUGGESTION' "$review")
  verdict=$(grep -m1 '^Verdict:' "$review" | sed 's/Verdict: *//' || echo "?")
  printf '| %s | %s | %s | %s | %s | %s | %s | %s |\n' \
    "$(date +%F)" "$change" "$builder" "$reviewer" "$round" "$blocking" "$suggestions" "$verdict" >> "$wt/$METRICS"
  git -C "$wt" add "$METRICS" "$(change_dir "$change")/review.md"
  git -C "$wt" commit -m "review($change): round $round metrics" > /dev/null || true

  echo
  echo "Round $round by $reviewer: $verdict ($blocking blocking, $suggestions suggestions)"
  if [ "$blocking" -gt 0 ]; then
    echo "Next: ./scripts/factory.sh fix $change   (then review again)"
  else
    echo "Next: look at the diff yourself, then merge:"
    echo "  git merge --no-ff change/$change    (or push the branch and open a PR)"
    echo "  then archive the change (/opsx:archive) and run: ./scripts/factory.sh finish $change"
  fi
}

cmd_fix() {
  local change="${1:-}"
  [ -n "$change" ] || die "usage: fix <change> [agent]"
  local wt agent
  wt="$(state_get "$change" WORKTREE)"
  if [ -z "$wt" ] || [ ! -d "$wt" ]; then die "no worktree for '$change'"; fi
  agent="${2:-$(state_get "$change" BUILDER)}"
  run_agent "$agent" full "$wt" "$(role_prompt builder "Change: $change
Change folder: $(change_dir "$change")
Base branch: $BASE_BRANCH
Task: address openspec/changes/$change/review.md (BLOCKING items first).")"
  echo
  echo "Next: ./scripts/factory.sh review $change"
}

cmd_finish() {
  local change="${1:-}"
  [ -n "$change" ] || die "usage: finish <change>"
  local wt
  wt="$(state_get "$change" WORKTREE)"
  git branch --merged "$BASE_BRANCH" | grep -q "change/$change\$" ||
    die "branch change/$change is not merged into $BASE_BRANCH yet"
  if [ -n "$wt" ] && [ -d "$wt" ]; then git worktree remove "$wt"; fi
  git branch -d "change/$change"
  rm -f "$STATE_DIR/$change.env"
  echo "Cleaned up $change. Consider running: ./scripts/factory.sh learn"
}

cmd_learn() {
  local agent="${1:-$LEARNER_AGENT}"
  run_agent "$agent" safe "$ROOT" "$(role_prompt learner "Today is $(date +%F).")"
  echo
  echo "Next: review with 'git diff -- AGENTS.md docs/learnings.md' and commit what you agree with."
}

cmd="${1:-}"
[ $# -gt 0 ] && shift
case "$cmd" in
  status) cmd_status ;;
  scout) cmd_scout "$@" ;;
  triage) cmd_triage "$@" ;;
  plan) cmd_plan "$@" ;;
  approve) cmd_approve "$@" ;;
  build) cmd_build "$@" ;;
  review) cmd_review "$@" ;;
  fix) cmd_fix "$@" ;;
  finish) cmd_finish "$@" ;;
  learn) cmd_learn "$@" ;;
  "" | -h | --help | help) usage ;;
  *)
    usage
    exit 1
    ;;
esac
