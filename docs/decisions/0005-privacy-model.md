# 0005. Privacy model: local embeddings, cloud LLM under API terms, secrets redacted
Date: 2026-10-10
Status: accepted

## Context
Data includes personal chats and mail and confidential client data. The server has no GPU.
Answers are produced by Claude through MCP, so retrieved evidence reaches a cloud model at query
time regardless of what happens at ingest. Pseudonymize-then-restore was considered: it needs a
permanent mapping vault, masks queries too, hurts name-based retrieval, misses entities (worse in
uk/ru) and does not hide content itself.

## Decision
- Embeddings and reranking run locally on the server (multilingual CPU models).
- Cloud LLMs (Anthropic API, no training on API data) are used for distillation, synthesis and digests.
- Cloud speech-to-text is allowed for meetings.
- Before any text leaves the server, hard secrets are redacted locally (passwords, card numbers/IBAN,
  one-time codes, API keys/tokens). No full pseudonymization.

## Consequences
High retrieval quality with modest cost. Trust is placed in provider API terms. If the threat
model tightens later, a per-source "local only" flag (no distillation, FTS + local embeddings only)
is the escape hatch; pseudonymization stays rejected unless requirements change.
