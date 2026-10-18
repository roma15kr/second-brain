# TypeScript/JavaScript: package.json scripts are the source of truth.
# Package manager is detected from the lock file.
PM ?= $(if $(wildcard pnpm-lock.yaml),pnpm,$(if $(wildcard yarn.lock),yarn,$(if $(wildcard bun.lock bun.lockb),bun,npm)))
PM_EXEC ?= $(if $(filter pnpm,$(PM)),pnpm exec,$(if $(filter yarn,$(PM)),yarn,$(if $(filter bun,$(PM)),bunx,npx --no-install)))
has_script = $(shell node -e "process.exit((require('./package.json').scripts||{})['$(1)']?0:1)" 2> /dev/null && echo yes)
TS_TYPECHECK ?= $(if $(call has_script,typecheck),$(PM) run typecheck,$(PM_EXEC) tsc --noEmit)

.PHONY: install-ts typecheck-ts lint-ts test-ts fmt-ts

install-ts:
	$(PM) install

typecheck-ts:
	$(TS_TYPECHECK)

lint-ts:
	@test -n "$(call has_script,lint)" || { echo 'Add a "lint" script to package.json (e.g. "eslint ." or "biome check .")'; exit 1; }
	$(PM) run lint

# CI=1 makes Vitest and Jest run once instead of starting watch mode.
test-ts:
	@test -n "$(call has_script,test)" || { echo 'Add a "test" script to package.json (e.g. "vitest run")'; exit 1; }
	CI=1 $(PM) run test

fmt-ts:
	@test -n "$(call has_script,format)" || { echo 'Add a "format" script to package.json (e.g. "prettier --write .")'; exit 1; }
	$(PM) run format
