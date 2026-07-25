# aihealth-server — working rules

## Comments (full standard: docs/comment-standard.md)

A comment states something true about the code that the code cannot say
itself — and that stays true after the PR merges. Constraints, invariants,
non-obvious why-this-way, failure ordering, hidden conventions/units.

Never: change history ("used to", "previously", "the old order"), diff
justification, next-line narration, review/ticket references, commented-out
code. Change rationale belongs in the commit message.

## Codebase conventions

- ai_foundation is standalone: no v1/v2 legacy agent imports.
- Typed enums/Literals over string conventions; validate at the API edge.
- No hardcoded translated strings or language whitelists — English is the
  canonical string; everything else goes through TranslationService.
- Never commit alembic/versions files (migrations run server-side).
- Async end-to-end: no sync I/O or `nest_asyncio` wrappers in async paths;
  fire-and-forget tasks hold strong references.
- Shared Mongo docs: writers `$set` only fields they own, target turns by
  `_id`, never "the latest".
- Patient-local timezones for all user-facing timestamps; naive datetimes for
  Postgres `TIMESTAMP WITHOUT TIME ZONE`.
