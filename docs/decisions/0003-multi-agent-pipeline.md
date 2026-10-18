# 0003. Multi-agent pipeline with human gates
Date: YYYY-MM-DD
Status: accepted

## Context
One AI planning, building and checking its own work repeats its own blind spots, and the same
mistakes recur across sessions. Customer and business feedback was scattered.

## Decision
Use `scripts/factory.sh` with separate roles (scout, planner, builder, reviewer, learner) defined
in `docs/ai/roles/`. The reviewer is always a different model than the builder. Builders work in
isolated git worktrees. Humans triage, approve plans and merge. Review findings are recorded in
`docs/metrics/changes.md`; repeated mistakes become rules in `docs/learnings.md` and AGENTS.md.
OpenSpec rules enforce product evidence, a success metric, program design and vertical slices.

## Consequences
More AI calls per feature (plan + build + 1-3 reviews). Fewer defects reach review/merge, and
the instructions improve over time. Small fixes skip the pipeline.
