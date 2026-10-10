# 0008. Numeric marketing and commerce data goes to a metrics warehouse, not embeddings
Date: 2026-10-10
Status: accepted

## Context
Quokka (marketplace APIs, Meta, TikTok, GA) and RDIM (Meta, GA, Google Ads, own B2B system) and
Digisoft (Shopify, historical Stripe) produce time series. Embeddings cannot answer "CPA last week".

## Decision
Scheduled pulls into typed Postgres tables in a `metrics` schema, tagged by scope. Exposed through
an MCP tool `query_metrics` (read-only role, predefined views first, raw SQL allowed). Only text
artifacts (campaign/ad names, ad copy, change history, notes) go into `items`.

## Consequences
Claude can join "why" (ClickUp, mail, meetings) with "what" (numbers). Each platform needs its own
schema mapping and token refresh handling. Anomaly detection for standups runs on these tables.
