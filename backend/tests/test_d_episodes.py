"""Lane D: session_ended → exactly one episode memory, threads resolved, idempotent."""
import os
from datetime import datetime, timezone

os.environ.setdefault("MOCK_EMBED", "true")
os.environ.setdefault("MOCK_LLM", "true")

import pytest  # noqa: E402

from app.contracts import EpisodeSummary, Event, EventType, OpenThread  # noqa: E402
from app.learning import boundaries as boundaries_mod, episodes, memory as memory_mod  # noqa: E402
from test_d_fakedb import FakeDB  # noqa: E402

USER = "usr_maya"


@pytest.fixture()
def fake_db(monkeypatch):
    database = FakeDB()
    for module in (episodes, memory_mod, boundaries_mod):
        monkeypatch.setattr(module, "db", lambda: database)
    return database


async def _session(database, session_id="ses_sam1", person_id="per_sam"):
    await database["sessions"].insert_one({"_id": session_id, "user_id": USER, "person_ids": [person_id]})
    await database["people"].insert_one({"_id": person_id, "user_id": USER, "name": "Sam Chen", "relationship": "family"})
    for index, (kind, text) in enumerate([("partner", "We won in overtime Saturday!"), ("user", "Proud of you, bud.")]):
        await database["utterances"].insert_one({"_id": f"utt_{index}", "session_id": session_id, "user_id": USER,
                                                 "speaker": {"kind": kind}, "text": text, "created_at": index})
    await database["memories"].insert_one({"_id": "mem_ep_sam_nov", "user_id": USER, "person_id": person_id,
                                           "kind": "episode", "status": "active", "text": "Nov 8", "seed_source": "lane-d",
                                           "created_at": datetime(2026, 11, 8, tzinfo=timezone.utc),
                                           "open_threads": [{"id": "thr_sam_score", "text": "send score", "owner": "partner", "status": "open"}]})
    return Event(user_id=USER, type=EventType.session_ended, session_id=session_id, person_id=person_id,
                 relationship="family")


async def test_session_end_writes_one_episode_and_is_idempotent(fake_db, monkeypatch):
    calls = []

    async def fake_llm(system, user, schema, **kw):
        calls.append(user)
        return EpisodeSummary(summary="Sam's team won in overtime; Maya said she was proud.",
                              topics=["hobbies"], threads_resolved_ids=["thr_sam_score", "thr_not_sams"],
                              open_threads_new=[OpenThread(text="Sam to send next game date", owner="partner")])
    monkeypatch.setattr(episodes, "complete_json", fake_llm)
    evt = await _session(fake_db)

    first = await episodes.summarize_session(evt)
    second = await episodes.summarize_session(evt)          # re-delivered event
    assert first == second == "mem_ep_ses_sam1" and len(calls) == 1
    eps = [m for m in fake_db["memories"].docs if m.get("session_id") == "ses_sam1"]
    assert len(eps) == 1 and eps[0]["person_id"] == "per_sam" and eps[0]["written_by"] == "lane-d"
    assert "Sam: We won in overtime" in calls[0] and "PARTNER: Sam Chen" in calls[0] and "[thr_sam_score]" in calls[0]
    old = next(m for m in fake_db["memories"].docs if m["_id"] == "mem_ep_sam_nov")
    assert old["open_threads"][0]["status"] == "resolved"

    ctx = await memory_mod.retrieve_person_context(USER, "per_sam", "family")
    assert ctx.recent_episodes[0].id == "mem_ep_ses_sam1"
    assert [t.text for t in ctx.open_threads] == ["Sam to send next game date"]


async def test_mock_llm_path_and_empty_session(fake_db):
    evt = await _session(fake_db)
    assert await episodes.summarize_session(evt) == "mem_ep_ses_sam1"   # MOCK_LLM canned summary
    await fake_db["sessions"].insert_one({"_id": "ses_empty", "user_id": USER, "person_ids": ["per_sam"]})
    empty = Event(user_id=USER, type=EventType.session_ended, session_id="ses_empty")
    assert await episodes.summarize_session(empty) is None


async def test_llm_failure_still_stores_fallback_episode(fake_db, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(episodes, "complete_json", boom)
    evt = await _session(fake_db)
    assert await episodes.summarize_session(evt) == "mem_ep_ses_sam1"
    ep = next(m for m in fake_db["memories"].docs if m["_id"] == "mem_ep_ses_sam1")
    assert "Proud of you, bud." in ep["text"]
