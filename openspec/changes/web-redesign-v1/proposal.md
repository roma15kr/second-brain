# Proposal: web-redesign-v1 — simple, light, modern web OS

Branch: `change/web-redesign-v1`, from `main` (after or alongside `assistant-moderation-v1`).

## Why
Owner (2026-11-02): "I don't like the design of the app. Make it simple, UI and UX friendly with
fresh, light and modern design." Today: dark theme, many pages, dense text.

**Success metric:** the owner finds the day's actions (Moderate, meetings, mentions) from the
first screen without scrolling on phone and laptop; owner approves the look.

## What Changes
- **Light, modern look:** white/very light grey surfaces, one accent colour (blue from the logo),
  generous spacing, rounded cards, system font, clear type scale; light even when the device is in dark mode (dark only if chosen in Settings).
- **Simple navigation:** 5 places — **Today**, **Moderate** (drafts, tasks, comments), **Meetings**,
  **Search** (also the assistant), **Settings**; the other pages move under them (Library, People,
  Loops under Search/Today; Status under Settings). Bottom tab bar on phone, sidebar on laptop.
- **Today = one screen:** what needs action now (counts + top items), next meetings, team mentions.
- **Less text:** cards show a title and one line; details open on tap.
- No new dependencies (plain CSS with design tokens).

## Capabilities
### New Capabilities
- `web-design`: look, navigation, Today screen, text density.
### Modified Capabilities
None in `openspec/specs/`.

## Impact
`web/src/styles.css` (rewritten as tokens + components), `shell/` (navigation), `pages/Today.tsx`,
page layouts; tests updated for new navigation labels.

## Update 2026-11-03 (owner)
"Combine assistant with dictation — this function is almost the main one in the app; you hide info
in the search menu — optimize UI/UX, make it mobile friendly; dictation or AI assistant must be the
main in the menu." → assistant+dictation is one screen and the centre/first navigation action;
every section is visible in the sidebar (groups) and in the phone Menu; phone comfort rules.
