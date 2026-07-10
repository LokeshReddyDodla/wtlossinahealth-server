# Comment Standard

One rule decides everything: **a comment states something true about the code
that the code cannot say itself — and that stays true after the PR merges.**

A comment is for the *next reader*, not the current reviewer. If it argues that
a change is correct, references how things used to be, or narrates what the
next line does, it's review-talk — it becomes noise the day after merge.

## What a comment IS for

| Kind | Example (from this codebase) |
|---|---|
| **Invariant / constraint** the code can't express | `# Fail closed: an unsigned webhook would let anyone chat as any patient whose phone number they know.` |
| **Non-obvious WHY-this-way** | `# 'is None', not truthiness — an EMPTY PromptRegistry is falsy (__len__ == 0) and would skip registration forever.` |
| **Failure semantics / ordering contract** | `# Record BEFORE sending: a recorded-but-unsent insight self-heals; a sent-but-unrecorded one double-pushes.` |
| **Convention / unit that isn't visible** | `# Python weekday int (Mon=0) — models misread the convention (assume Sun=0), so spell out the name.` |
| **Deliberate ceiling + upgrade path** | `# in-memory cache, per-process; move to Redis if instances multiply` |
| **Cross-file coupling** | `# MUST stay a subset of the event triggers that enqueue handle_proactive_event — an AWAIT with no producer is a promise the system can't keep.` |

## What a comment is NOT for

- **History.** ~~`a whole-doc write here used to erase a pending request`~~ →
  state the live rule: `each writer $set-s only the fields it owns — concurrent
  writers share this document.`
- **Justifying the diff.** ~~`the old order left the user with permanent
  silence`~~ → state the contract: `append before clear: if the append fails
  the ask must survive for the next event.`
- **Narrating the next line.** ~~`# increment the counter`~~ — delete.
- **Referencing reviews/tickets/sessions.** Findings live in git history and
  PRs, not in source.
- **Commented-out code.** Delete it; git remembers.

## Docstrings

- **Every public module**: 2–6 lines — what this module owns, and the one or
  two design invariants a caller must not violate.
- **Public functions/methods**: one-line imperative summary. Add param/return
  notes ONLY where semantics aren't obvious from names and types (units,
  ownership, "None means X", failure behavior). Never restate the signature.
- **Private helpers**: docstring only when the contract is subtle; otherwise
  the name carries it.

## Mechanics

- `TODO(name): <actionable condition>` — a TODO without an owner and a trigger
  ("when X ships") is a wish, not a TODO. No bare `TODO: fix later`.
- Tests: comment states the *invariant under test* when the assert alone
  doesn't make it obvious — especially regression tests, where the comment is
  the only place the failure mode is written down.
- Log-message strings follow the same rule: name the state, not the apology.

## The self-check before committing

Read each new comment and ask: *"Will this sentence still be true and useful
to someone who never saw this PR?"* If it needs the diff to make sense, it
belongs in the commit message instead — commit messages are where change
rationale lives, permanently and searchably.
