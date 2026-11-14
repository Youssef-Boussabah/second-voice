"""Lane D: a Voyage rate limit must never lose an episode or a phrase."""
import os
import time

os.environ.setdefault("MOCK_EMBED", "true")
os.environ.setdefault("MOCK_LLM", "true")

import pytest  # noqa: E402

from app.contracts import Event, EventType  # noqa: E402
from app.learning import boundaries as boundaries_mod, episodes, memory as memory_mod, phrasebook, safe_embed  # noqa: E402
from test_d_fakedb import FakeDB  # noqa: E402
from test_d_episodes import _session  # noqa: E402

USER = "usr_maya"


class RateLimitError(Exception):
    """Same class name as voyageai.error.RateLimitError."""


@pytest.fixture()
def fake_db(monkeypatch):
    database = FakeDB()
    for module in (episodes, memory_mod, boundaries_mod, phrasebook):
        monkeypatch.setattr(module, "db", lambda: database)
    return database


@pytest.fixture()
def voyage_down(monkeypatch):
    calls = []

    async def rate_limited(texts, input_type):
        calls.append(texts)
        raise RateLimitError("3 RPM")
    monkeypatch.setattr(safe_embed, "embed", rate_limited)
    return calls


async def test_rate_limit_still_saves_episode_without_embedding(fake_db, voyage_down):
    evt = await _session(fake_db)
    started = time.perf_counter()
    saved = await episodes.summarize_session(evt)
    assert time.perf_counter() - started < 2.5
    assert saved == "mem_ep_ses_sam1" and len(voyage_down) == 2          # one try + one short retry
    doc = next(m for m in fake_db["memories"].docs if m["_id"] == saved)
    # the insert itself is what the hub's memories change stream turns into memory.updated
    assert "embedding" not in doc and doc["person_id"] == "per_sam" and doc["written_by"] == "lane-d"
    ctx = await memory_mod.retrieve_person_context(USER, "per_sam", "family")
    assert ctx.recent_episodes[0].id == saved
    assert await episodes.summarize_session(evt) == saved                 # still idempotent
    assert sum(m.get("session_id") == "ses_sam1" for m in fake_db["memories"].docs) == 1


async def test_rate_limit_still_learns_phrase_and_dedupes_by_text(fake_db, voyage_down):
    evt = dict(user_id=USER, type=EventType.reply_typed, person_id="per_dana", text="See you Friday")
    first = await phrasebook.learn_phrase(Event(**evt))
    again = await phrasebook.learn_phrase(Event(**evt))
    assert first == again
    doc = fake_db["memories"].docs[0]
    assert "embedding" not in doc and doc["uses"] == 2


async def test_slow_voyage_is_time_boxed(monkeypatch):
    import asyncio

    async def slow(texts, input_type):
        await asyncio.sleep(5)
    monkeypatch.setattr(safe_embed, "embed", slow)
    started = time.perf_counter()
    assert await safe_embed.embed_document_or_none("hi", budget_s=0.5) is None
    assert time.perf_counter() - started < 1.0


async def test_healthy_voyage_returns_vector(monkeypatch):
    async def ok(texts, input_type):
        return [[0.5] * 4]
    monkeypatch.setattr(safe_embed, "embed", ok)
    assert await safe_embed.embed_document_or_none("hi") == [0.5] * 4
