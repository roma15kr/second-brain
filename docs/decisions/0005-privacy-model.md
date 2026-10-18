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
- Cloud LLMs (an API provider that does not train on API data; OpenAI since the 2026-10-10 amendment below) are used for distillation, synthesis and digests.
- Cloud speech-to-text is allowed for meetings.
- Before any text leaves the server, hard secrets are redacted locally (passwords, card numbers/IBAN,
  one-time codes, API keys/tokens). No full pseudonymization.

## Consequences
High retrieval quality with modest cost. Trust is placed in provider API terms. If the threat
model tightens later, a per-source "local only" flag (no distillation, FTS + local embeddings only)
is the escape hatch; pseudonymization stays rejected unless requirements change.

## Amendment 2026-10-10: server-side LLM provider is OpenAI
The owner's Claude Pro subscription does not include API access, and an OpenAI API key already
exists; at current prices the OpenAI and Anthropic cheap/mid tiers cost the same. Server-side LLM
calls (distillation, scope classification, digests, standups) use the OpenAI API under the same
rules: redacted text only, no training on API data. Interactive answering stays with Claude Code /
Claude Desktop via MCP (covered by the subscription; no API key involved).
