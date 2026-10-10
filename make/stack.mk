# Standard targets shared by every project. Each stack file (php.mk, python.mk, ts.mk) defines
# install-<stack>, typecheck-<stack>, lint-<stack>, test-<stack> and fmt-<stack>.
# Override any tool command by setting its variable in the project Makefile before the include.

STACK_DIR := $(dir $(lastword $(MAKEFILE_LIST)))
SUPPORTED_STACKS := php python ts

UNKNOWN_STACKS := $(filter-out $(SUPPORTED_STACKS),$(STACKS))
ifneq ($(UNKNOWN_STACKS),)
$(error Unknown STACKS: $(UNKNOWN_STACKS). Supported: $(SUPPORTED_STACKS))
endif

include $(foreach s,$(STACKS),$(STACK_DIR)$(s).mk)

# need: fail with an install hint when a tool is missing. Usage: $(call need,<path>,<install hint>)
define need
@test -x $(1) || { echo "Missing $(1). Install it with: $(2)"; exit 1; }
endef

.PHONY: help check install typecheck lint test fmt stacks-guard
.DEFAULT_GOAL := help

help: ## Show available targets
	@echo "Stacks: $(if $(strip $(STACKS)),$(STACKS),(none set - edit STACKS in Makefile))"
	@grep -h -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort -u | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  make %-18s %s\n", $$1, $$2}'

check: stacks-guard typecheck lint test ## MAIN GATE: typecheck + lint + test. Must pass before "done"
	@echo "make check passed ($(STACKS))"

install: stacks-guard $(addprefix install-,$(STACKS)) ## Install dependencies
typecheck: stacks-guard $(addprefix typecheck-,$(STACKS)) ## Static type checks
lint: stacks-guard $(addprefix lint-,$(STACKS)) ## Linters and format checks (no changes)
test: stacks-guard $(addprefix test-,$(STACKS)) ## All tests
fmt: stacks-guard $(addprefix fmt-,$(STACKS)) ## Auto-format and auto-fix

stacks-guard:
	@test -n "$(strip $(STACKS))" || { echo "STACKS is empty: set it in Makefile, e.g. STACKS := python ts"; exit 1; }
