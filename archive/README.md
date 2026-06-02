# archive/

Historical operator + planning documents from prior development
cycles. Moved here at v0.8.0 packaging to keep the project root
navigable (per CLAUDE.md "do not proliferate documents — archive,
don't delete").

## Layout

- **`punch-lists/`** — per-cycle punch lists (M1 through V0_7).
  Each file documents the scope, decisions, and outcomes for one
  cycle. The active punch list for the current release lives at
  the project root (`V0_8_PUNCH_LIST.md`).
- **`runbooks/`** — per-cycle runbooks for Tier-C/D/G live A/B
  testing. Captures the exact commands + verification steps used
  at the time. Reference value: similar structure may be useful
  for future cycle planning.
- **`V0_4_ARCHITECTURE.md`** — the v0.4 architecture decision
  document (architect-then-parallel-compose pivot). Still
  referenced by the v0.4 opt-in code paths.

## What this directory is NOT

- Not a place for active planning (use the root punch list).
- Not deleted code or experiments (those go through git history).
- Not auto-generated artifacts (those stay in their working dirs).

## Restoration

If a prior cycle's work needs to be resumed (very unlikely past
v0.8.0), move the relevant file back to the root + reference it
from the active punch list with a re-opened decision number.
