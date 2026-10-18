# 0006. Hybrid retrieval fused with RRF and reranked locally
Date: 2026-10-10
Status: accepted

## Context
Vector search alone fails on short or low-density messages, exact strings (errors, order ids, campaign
names) and stale answers. Data is mixed Ukrainian/Russian/English; Postgres has no Ukrainian stemmer.

## Decision
Follow the Cerebras pipeline: full-text (`simple` config + unaccent, plus pg_trgm), embeddings
(multilingual, HNSW), IDF-weighted lexical scoring, age decay. Conversations are distilled
(question / summary / resolution / entities) before embedding; qualifying bursts (IDF >= 4,
>= 200 chars, reactions) are embedded with the topic prepended. Lists are fused with RRF
(weight / (60 + rank)), deduplicated per source, capped per parent, reranked by a local
cross-encoder, top 10 expanded with neighbours. Telegram has no threads: units are reply chains,
forum topics, or time-gap segments.

## Consequences
More moving parts than plain RAG; needs a small evaluation set (real questions + expected items)
to tune weights, segment gap and burst thresholds. Thresholds from Cerebras are starting points only.
