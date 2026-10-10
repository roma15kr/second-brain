# Verification gate for humans, AI agents and CI. Run `make help` to see the targets.
# STACKS: which stacks this project uses (any of: php python ts). Set by ai-init; edit if needed.
STACKS :=

include make/stack.mk

# Project-specific targets go below, e.g.:
# test-integration: ## Integration tests (needs `docker compose up -d db`)
# 	vendor/bin/phpunit --testsuite integration
