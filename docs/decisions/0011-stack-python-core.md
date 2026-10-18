# 0011. Python for the core, Swift for the macOS app
Date: 2026-10-10
Status: proposed

## Context
Key libraries are Python: Telethon, CocoIndex, sentence-transformers/FlagEmbedding, Google and
Meta API clients, the official MCP SDK. The meeting recorder needs ScreenCaptureKit.

## Decision
Core services in Python (uv, pytest, ruff, mypy) on Postgres; the meeting app in Swift/SwiftUI.

## Consequences
One language for all server code. Not yet confirmed by the owner — revisit before slice 1.
