"""Read a whole result set through PostgREST's row cap.

PostgREST answers at most `max_rows` (1,000) rows per request and says nothing
when it stops there, so an unpaged "select everything" is silently a "select
the first 1,000". The admin dashboard's counts and totals were built that way
and under-reported once a table passed the cap (audit SCL-2).
"""

from collections.abc import Callable
from typing import Any

PAGE_SIZE = 1000


def fetch_all(build_query: Callable[[], Any], page_size: int = PAGE_SIZE) -> list[dict]:
    """Every row `build_query()` selects, one `.range()` page at a time.

    `build_query` must return a fresh, fully-filtered query each call, with a
    deterministic order — paging an unordered result can skip or repeat rows.
    """
    rows: list[dict] = []
    start = 0
    while True:
        page = build_query().range(start, start + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size
