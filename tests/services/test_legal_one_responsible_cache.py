import logging

from app.services.legal_one_client import LegalOneApiClient


def _client_without_init():
    client = LegalOneApiClient.__new__(LegalOneApiClient)
    client.logger = logging.getLogger(__name__)
    return client


def test_prefetch_lawsuit_responsibles_uses_cache_hits_and_fetches_missing(monkeypatch):
    client = _client_without_init()
    merged_updates = {}

    monkeypatch.setattr(
        client,
        "_lawsuit_cache_lookup",
        lambda ids: (
            {101: {"responsibleUser": {"id": 11, "name": "Cached"}}},
            [202],
        ),
    )
    monkeypatch.setattr(
        client,
        "fetch_lawsuit_responsibles_batch",
        lambda ids, max_workers=2: {202: {"id": 22, "name": "Fetched"}},
    )
    monkeypatch.setattr(
        client,
        "_lawsuit_cache_merge_upsert",
        lambda updates: merged_updates.update(updates),
    )

    result = client.prefetch_lawsuit_responsibles_cache([101, 202, 101])

    assert result == {
        101: {"id": 11, "name": "Cached"},
        202: {"id": 22, "name": "Fetched"},
    }
    assert merged_updates == {
        202: {"responsibleUser": {"id": 22, "name": "Fetched"}},
    }


def test_get_cached_lawsuit_responsibles_batch_never_fetches_api(monkeypatch):
    client = _client_without_init()

    monkeypatch.setattr(
        client,
        "_lawsuit_cache_lookup",
        lambda ids: (
            {
                101: {"responsibleUser": {"id": 11}},
                202: {"id": 202},
            },
            [],
        ),
    )

    result = client.get_cached_lawsuit_responsibles_batch([101, 202])

    assert result == {101: {"id": 11}}
