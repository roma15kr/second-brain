#!/usr/bin/env bash
# Usage: ./scripts/new-project.sh [--dry-run] /path/to/project
#   --dry-run  only print how many template files would be added, change nothing
# Adds the AI project template to a new or existing project. Safe to run again:
#   - existing files are never overwritten;
#   - a file whose name differs only in case from an existing one (docs/architecture.md vs
#     docs/ARCHITECTURE.md) is not added, and template references are pointed at your file;
#   - template CI workflows are not added when the project already has CI;
#   - paths listed in .ai-template-ignore (one path or glob per line) are never added;
#   - missing .gitignore entries are appended to an existing .gitignore.
# Then detects the project's stacks for the Makefile and sets up OpenSpec.
set -euo pipefail
DRY_RUN=false
if [ "${1:-}" = --dry-run ]; then
  DRY_RUN=true
  shift
fi
TARGET="${1:?Usage: new-project.sh [--dry-run] /path/to/project}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

agents_existed=false
[ -f "$TARGET/AGENTS.md" ] && agents_existed=true
openspec_existed=false
[ -f "$TARGET/openspec/config.yaml" ] && openspec_existed=true
gitignore_existed=false
[ -f "$TARGET/.gitignore" ] && gitignore_existed=true

ignore_patterns=()
if [ -f "$TARGET/.ai-template-ignore" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs)"
    [ -n "$line" ] && ignore_patterns+=("$line")
  done < "$TARGET/.ai-template-ignore"
fi

is_ignored() {
  local path="$1" pattern
  for pattern in "${ignore_patterns[@]+"${ignore_patterns[@]}"}"; do
    # shellcheck disable=SC2053
    if [[ "$path" == $pattern ]] || [[ "$path" == $pattern/* ]]; then
      return 0
    fi
  done
  return 1
}

# Existing project files by lower-case path, to detect names that differ only in case.
declare -A existing_lower=()
while IFS= read -r f; do
  existing_lower["${f,,}"]="$f"
done < <(cd "$TARGET" && find . \( -name .git -o -name node_modules -o -name vendor -o -name .venv \) -prune \
  -o -type f -print | sed 's#^\./##')

has_own_ci=false
for f in "$TARGET"/.github/workflows/*.yml "$TARGET"/.github/workflows/*.yaml; do
  [ -e "$f" ] || continue
  case "$(basename "$f")" in
    check.yml | openspec.yml | scout.yml) ;;
    *) has_own_ci=true ;;
  esac
done

copied=()
declare -A redirect=()
skipped_case=()
skipped_ci=()

while IFS= read -r f; do
  [ "$f" = README.md ] && continue
  [ "$f" = .gitignore ] && continue
  is_ignored "$f" && continue
  [ -e "$TARGET/$f" ] && continue
  if [ -n "${existing_lower[${f,,}]+x}" ]; then
    redirect["$f"]="${existing_lower[${f,,}]}"
    skipped_case+=("$f -> ${existing_lower[${f,,}]}")
    continue
  fi
  if [ "$has_own_ci" = true ] && [[ "$f" == .github/workflows/* ]]; then
    skipped_ci+=("$f")
    continue
  fi
  if [ "$DRY_RUN" = false ]; then
    mkdir -p "$TARGET/$(dirname "$f")"
    cp -p "$SRC/$f" "$TARGET/$f"
  fi
  copied+=("$f")
done < <(cd "$SRC" && find . -type f ! -path './.git/*' | sed 's#^\./##' | sort)

if [ "$DRY_RUN" = true ]; then
  echo "${#copied[@]}"
  exit 0
fi

# Point references in the files we just added at the project's own file names.
for from in "${!redirect[@]}"; do
  to="${redirect[$from]}"
  for f in "${copied[@]+"${copied[@]}"}"; do
    if grep -qF "$from" "$TARGET/$f" 2> /dev/null; then
      sed -i "s#${from//./\\.}#${to}#g" "$TARGET/$f"
    fi
  done
done

# Merge .gitignore entries.
gitignore_added=0
if [ -f "$SRC/.gitignore" ]; then
  touch "$TARGET/.gitignore"
  header_written=false
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in "" | "#"*) continue ;; esac
    if ! grep -qxF "$line" "$TARGET/.gitignore"; then
      if [ "$gitignore_existed" = true ] && [ "$header_written" = false ]; then
        printf '\n# Added by the AI project template\n' >> "$TARGET/.gitignore"
        header_written=true
      fi
      echo "$line" >> "$TARGET/.gitignore"
      gitignore_added=$((gitignore_added + 1))
    fi
  done < "$SRC/.gitignore"
fi

cd "$TARGET"
[ -d .git ] || git init -q
[ -x scripts/detect-stacks.sh ] && ./scripts/detect-stacks.sh .

# A freshly added AGENTS.md keeps only the verification notes for this project's stacks.
if [ "$agents_existed" = false ] && [ -f AGENTS.md ]; then
  stacks="$(sed -n 's/^STACKS := *//p' Makefile 2> /dev/null || true)"
  for s in php python ts; do
    if [ -z "$stacks" ] || [[ " $stacks " == *" $s "* ]]; then
      sed -i "/^<!-- \/\{0,1\}stack:$s -->$/d" AGENTS.md
    else
      sed -i "/^<!-- stack:$s -->$/,/^<!-- \/stack:$s -->$/d" AGENTS.md
    fi
  done
fi

[ -x scripts/init-openspec.sh ] && ./scripts/init-openspec.sh .

echo
echo "== AI project template: summary for $TARGET"
echo "Added ${#copied[@]} file(s); ${gitignore_added} .gitignore entr(y/ies)."
if [ "${#skipped_case[@]}" -gt 0 ]; then
  echo "Not added (same name in different case; references now point to your file):"
  printf '  %s\n' "${skipped_case[@]}"
fi
if [ "${#skipped_ci[@]}" -gt 0 ]; then
  echo "Not added because the project already has CI (run 'make check' in your own workflow):"
  printf '  %s\n' "${skipped_ci[@]}"
fi
needs_review=()
if [ "$agents_existed" = true ]; then
  needs_review+=("AGENTS.md is yours: copy any new sections you want from $SRC/AGENTS.md")
fi
for f in CLAUDE.md GEMINI.md; do
  if [ -f "$f" ] && ! grep -qE '^@(\./)?AGENTS\.md' "$f"; then
    needs_review+=("$f has its own content: move shared rules into AGENTS.md and import it with '@AGENTS.md'")
  fi
done
if [ "$openspec_existed" = true ] && ! grep -q "Least confident decisions" openspec/config.yaml 2> /dev/null; then
  needs_review+=("openspec/config.yaml kept its old rules: run './scripts/init-openspec.sh . --reset-rules' for the new ones")
fi
if [ "${#needs_review[@]}" -gt 0 ]; then
  echo "Kept as-is; please review:"
  printf '  - %s\n' "${needs_review[@]}"
fi
echo "To never add a template file to this project, list it in .ai-template-ignore."
echo "Next: fill the <placeholders> in AGENTS.md, check 'make help', then commit."
