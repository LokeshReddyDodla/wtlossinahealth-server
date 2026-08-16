"""Whitespace-tokenized substring search for list endpoints."""

from typing import Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.sql import ColumnElement, Select


def apply_token_search(
    stmt: Select, search: Optional[str], fields: Sequence[ColumnElement]
) -> Select:
    """Require every whitespace term in `search` to match at least one of
    `fields` (AND across terms, OR across fields). No-op when search is blank."""
    if not search:
        return stmt
    for term in search.split():
        pattern = f"%{term}%"
        stmt = stmt.where(or_(*(field.ilike(pattern) for field in fields)))
    return stmt
