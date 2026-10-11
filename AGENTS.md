# AGENTS.md — instructions for ALL AI coding agents
# (Claude Code, Codex CLI, Gemini CLI and OpenCode read this file. Keep it short: < 100 lines.)

## Before you start any task
1. Read `STATUS.md` (current focus, next steps, known problems).
2. Read `docs/architecture.md` if the task touches more than one module.
3. Check `docs/decisions/` before changing an established approach, and follow `docs/learnings.md`.
4. Run `openspec list` to see active changes; read `openspec/specs/<area>/spec.md` for the area you change.

## Project
- Name: second-brain
- Purpose: A personal knowledge base and research repository for organizing, storing, and referencing insights from across the web.
- Stack: Python (uv) core on Postgres + pgvector, deployed with Coolify; Swift macOS meeting app (ADR 0011, proposed)

## Verification (how every change is checked)
- **Main gate: `make check`** (typecheck + lint + test). It must pass before you say a task is done.
  CI runs the same command. Other targets: `make install`, `make fmt`, `make help`.
- While working, run only the tests you touched (fast feedback), then `make check` at the end:
  - PHP: `vendor/bin/phpunit tests/Unit/FooTest.php` or `vendor/bin/phpunit --filter testName`
    (Pest: `vendor/bin/pest --filter "name"`)
  - Python: `uv run pytest tests/test_foo.py::test_name -x`
    (without uv.lock: `.venv/bin/python -m pytest tests/test_foo.py::test_name -x`)
  - TypeScript: `npx vitest run src/foo.test.ts -t "test name"` (Jest: `npx jest src/foo.test.ts -t "name"`;
    use `pnpm exec` / `yarn` instead of `npx` if the project uses them)
- Never skip, weaken or delete a test, and never loosen lint or type settings to make the gate pass.
- Run the app locally: `<e.g. make dev / composer run dev / npm run dev>`

### Testing traps (add one whenever a test-related mistake happens twice)
- <e.g. integration tests need `docker compose up -d db` first>

## Tools in this environment
- Search code with `rg` (ripgrep): fast, respects .gitignore. Prefer it over `grep -r` and `find | xargs grep`.
  Examples: `rg -n "functionName"`, `rg -l "TODO" src/`, `rg -t py "import requests"`.
- Read and transform JSON with `jq` instead of ad-hoc scripts.
  Examples: `jq '.dependencies' package.json`, `openspec list --json | jq '.changes[].name'`.
- Do not install system packages with apt/sudo; ask the human to add them to the workspace image.

## Rules
- Plan before coding for anything bigger than a small fix; show the plan first.
- Write or update tests for every behavior change. Run `make check` before saying "done".
- Keep changes small and focused. One task = one commit.
- Follow existing code style and patterns; do not introduce new libraries without asking.
- Never commit secrets. Never edit `.env` files.
- Do not reverse a decision recorded in `docs/decisions/` without asking.
- If something is unclear, ask instead of guessing.
- Scripted find/replace edits must assert the target text exists (formatters rewrap lines); test wiring at the real entry point, not only the inner function.

## Spec-driven workflow (OpenSpec)
- `openspec/specs/` = source of truth for how the system BEHAVES. Trust it; keep it true.
- New feature / behavior change / big refactor → OpenSpec change:
  propose → (I review) → apply → archive. Never start `apply` before I approve the proposal.
- Small bug fix, typo, internal cleanup with no behavior change → no change folder needed.
- Specs describe behavior (requirements + scenarios), not implementation details.
- While applying, tick tasks in `tasks.md`; if the plan turns out wrong, update the change first.
- Validate with `openspec validate --all` before archiving.

## Review and roles
- Never merge, push or archive yourself; the human does that.
- When asked to review, do not edit code; report BLOCKING/SUGGESTION findings.
- (Optional) If a prompt starts with "# Role: ...", act strictly within that role (`docs/ai/roles/`).

## Architecture boundaries
- <e.g. UI code never accesses the database directly>
- <e.g. all external API calls go through src/clients/>

## When you finish a task
1. Run `make check`; fix failures.
2. Update `STATUS.md` (done, next steps, open questions, gotchas).
3. If an OpenSpec change is fully done and tested: archive it (specs get updated).
   Update `docs/architecture.md` if structure changed.
4. Add an ADR in `docs/decisions/` if an important decision was made.
5. Suggest a commit message (Conventional Commits: `feat:`, `fix:`, `refactor:`...).
