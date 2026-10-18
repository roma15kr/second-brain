from datetime import date, datetime

import pytest

from kb import indexer
from kb.connectors import imap
from kb.search import SearchError, SearchFilters, search
from tests.fakes import FakeImap, make_email


@pytest.fixture
def seeded(conn, source, config):
    fake = FakeImap()
    fake.add(
        1,
        make_email("Marketplace contract", "Signed contract for Rozetka listing"),
        datetime(2026, 9, 1),
    )
    fake.add(2, make_email("Lunch", "sounds good, thanks"), datetime(2026, 9, 2))
    fake.add(
        3,
        make_email("Error report", "Got ERR_TOKEN_EXPIRED 0x8F2 from the API"),
        datetime(2026, 9, 3),
    )
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    while indexer.run_once(conn, config):
        pass
    return conn


def test_exact_word_finds_message(seeded):
    results = search(seeded, "Rozetka")
    assert [r.title for r in results] == ["Marketplace contract"]
    assert results[0].scopes == ["digisoft"]
    assert results[0].locator and results[0].item_id


def test_exact_error_string_ranks_first(seeded):
    assert search(seeded, "ERR_TOKEN_EXPIRED")[0].title == "Error report"


def test_scope_filter_excludes_other_scopes(seeded):
    assert search(seeded, "Rozetka", SearchFilters(scopes=["quokka"])) == []


def test_date_filter(seeded):
    assert search(seeded, "contract", SearchFilters(date_to=date(2026, 8, 31))) == []


def test_unknown_scope_error_lists_valid(seeded):
    with pytest.raises(
        SearchError, match="valid scopes: personal, digisoft, quokka, rdim, unsorted"
    ):
        search(seeded, "x", SearchFilters(scopes=["acme"]))
