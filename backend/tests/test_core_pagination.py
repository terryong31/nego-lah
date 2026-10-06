"""Audit SCL-2: PostgREST stops at 1,000 rows without saying so."""

from unittest.mock import MagicMock

from core.pagination import fetch_all


def test_fetch_all_reads_every_page_until_a_short_one():
    pages = [[{"n": i} for i in range(3)], [{"n": i} for i in range(3, 6)], [{"n": 6}]]
    query = MagicMock()
    query.range.return_value.execute.side_effect = [MagicMock(data=p) for p in pages]

    rows = fetch_all(lambda: query, page_size=3)

    assert [r["n"] for r in rows] == list(range(7))
    assert [c.args for c in query.range.call_args_list] == [(0, 2), (3, 5), (6, 8)]


def test_fetch_all_stops_on_an_empty_first_page():
    query = MagicMock()
    query.range.return_value.execute.return_value = MagicMock(data=None)
    assert fetch_all(lambda: query) == []
