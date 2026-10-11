# Learnings
Rules learned from real mistakes. Maintained by the Learner role (`./scripts/factory.sh learn`)
and by you. Agents must read this file before planning, building or reviewing.
Entries with Count >= 3 get promoted to AGENTS.md.

<!-- Format:
## <rule in one line>
Seen: <dates/changes>  Count: <n>
Why: <one or two sentences>
-->

## Test text detectors (redaction, parsing) on real-shaped samples: multi-line, values on the next line, numbers in between
Seen: 2026-10-10 v1-mail-telegram-search slice 3 (passwords without ':', codes on the next line)  Count: 2
Why: single-line unit-test strings passed while real mail/Telegram put the value on its own line; check live excerpts
with whitespace preserved (don't collapse `\s+` when inspecting) before calling a detector done.

## After a deploy, wait for /health = 200 before running live checks, and treat non-JSON responses as failures
Seen: 2026-10-10 slice 3 verification  Count: 1
Why: right after a Coolify redeploy the proxy returns an error page; a check that ignores parse errors reports false success.

## Never pipe the verification gate into another command before `&&`
Seen: 2026-10-10 slice 5 commit (`make check | tail -1 && git commit` committed a lint failure)  Count: 1
Why: a pipeline's exit status is the last command's (`tail`), so the failure is hidden. Redirect to a file,
check `$?`, or use `set -o pipefail`.

## Scripted text replacements must assert they matched
Seen: 2026-10-11 slice 8.3 (cmd_mcp never got the reranker), slice 3/8 test edits missed after the
formatter rewrapped lines (3 times)  Count: 3
Why: `s.replace(old, new)` silently does nothing when `old` differs by a line break, so a change "applied"
in a script never reached the file; tests that bypass the entry point (cmd_mcp) did not notice. Assert
`old in s` before replacing, or use the Edit tool; add a test at the real entry point.
