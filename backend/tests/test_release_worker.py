"""Learning worker: recovery and idempotency (at-least-once processing, idempotent effects).

Every test uses the in-memory FakeDB; the same scenarios were also run against real Atlas
change streams (see docs/operations/learning-worker.md, "Verification")."""
import os

os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("MOCK_EMBED", "true")

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from app.contracts import EpisodeSummary  # noqa: E402
from app.learning import boundaries as boundaries_mod  # noqa: E402
from app.learning import episodes, phrasebook, worker  # noqa: E402
from app.learning import memory as memory_mod  # noqa: E402
from test_d_fakedb import FakeDB  # noqa: E402

USER = "usr_maya"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def database(monkeypatch):
    fake = FakeDB()
    for module in (phrasebook, boundaries_mod, episodes, memory_mod):
        monkeypatch.setattr(module, "db", lambda: fake)
    return fake


def typed(event_id, text="See you Friday, Dana.", person="per_dana", created=NOW):
    return {"_id": event_id, "user_id": USER, "type": "reply_typed", "session_id": "ses_1", "person_id": person,
            "relationship": "clinician", "text": text, "topics": [], "created_at": created}


async def add(database, *docs):
    for d in docs:
        await database["events"].insert_one(d)


def learning(database, event_id):
    return next(d for d in database["events"].docs if d["_id"] == event_id).get("learning", {})


def expire(database, event_id):
    """Simulate time passing past the event's lease / backoff."""
    learning(database, event_id)["lease_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)


def phrases(database):
    return [d for d in database["memories"].docs if d["kind"] == "phrase"]


# ───────────────────────── failure → retry → recovery ─────────────────────────
async def test_failed_attempt_is_released_and_recovered_by_sweep(database, monkeypatch):
    await add(database, typed("evt_a"))
    real = phrasebook.learn_phrase
    calls = {"n": 0}

    async def flaky(evt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("Atlas blip")
        return await real(evt)
    monkeypatch.setattr(worker, "learn_phrase", flaky)

    assert await worker.process_event(database, "evt_a") == "failed"
    state = learning(database, "evt_a")
    assert state["state"] == "failed" and state["attempts"] == 1 and "Atlas blip" in state["last_error"]
    # backoff: a sweep right away must NOT retry yet
    assert await worker.sweep(database) == {}
    expire(database, "evt_a")
    assert await worker.sweep(database) == {"done": 1}
    assert learning(database, "evt_a")["state"] == "done" and learning(database, "evt_a")["attempts"] == 2
    assert len(phrases(database)) == 1 and phrases(database)[0]["uses"] == 1


async def test_crash_after_side_effect_is_retried_without_duplicates(database):
    """Worker A writes the phrase, then dies before recording `done`. Its lease expires and
    worker B re-runs the event: the phrase must still be counted once."""
    await add(database, typed("evt_b"))
    assert await worker.claim(database, "evt_b", owner="pcA:1") is not None
    await phrasebook.learn_phrase(worker.Event.model_validate(database["events"].docs[0]))   # side effect done
    # ...crash: no complete(). B cannot take a live claim:
    assert await worker.process_event(database, "evt_b", owner="pcB:2") == "skipped"
    expire(database, "evt_b")
    assert await worker.process_event(database, "evt_b", owner="pcB:2") == "done"
    assert len(phrases(database)) == 1 and phrases(database)[0]["uses"] == 1
    # A wakes up late and tries to finish: its stale claim is not trusted
    assert await worker.complete(database, "evt_b", owner="pcA:1") is False
    assert learning(database, "evt_b")["owner"] == "pcB:2"


async def test_two_workers_never_hold_the_same_claim(database):
    await add(database, typed("evt_c"))
    first = await worker.claim(database, "evt_c", owner="pcA:1")
    second = await worker.claim(database, "evt_c", owner="pcB:2")
    assert first is not None and second is None


async def test_poison_event_is_parked_dead_after_max_attempts(database, monkeypatch):
    await add(database, typed("evt_d"))

    async def always_fails(evt):
        raise ValueError("malformed")
    monkeypatch.setattr(worker, "learn_phrase", always_fails)
    outcomes = []
    for _ in range(worker.MAX_ATTEMPTS):
        outcomes.append(await worker.process_event(database, "evt_d"))
        expire(database, "evt_d")
    assert outcomes == ["failed"] * (worker.MAX_ATTEMPTS - 1) + ["dead"]
    assert await worker.sweep(database) == {}                     # dead events are not retried
    assert learning(database, "evt_d")["state"] == "dead"


async def test_done_events_are_never_reprocessed(database, monkeypatch):
    await add(database, typed("evt_e"))
    assert await worker.process_event(database, "evt_e") == "done"
    assert await worker.process_event(database, "evt_e") == "skipped"     # change-stream re-delivery
    assert await worker.sweep(database) == {}
    assert phrases(database)[0]["uses"] == 1


# ───────────────────────── sweep scope ─────────────────────────
async def test_sweep_ignores_history_seed_and_non_learning_events(database):
    since = NOW - timedelta(minutes=1)
    await add(database,
              typed("evt_old", created=NOW - timedelta(days=1)),                      # before sweep_since
              typed("evt_seed") | {"seed_source": "lane-d"},                           # seeded history
              {"_id": "evt_start", "user_id": USER, "type": "session_started", "created_at": NOW},
              typed("evt_other_user") | {"user_id": "usr_eval"},                       # eval harness user
              typed("evt_new"))
    assert await worker.sweep(database, since=since) == {"done": 1}
    handled = [d["_id"] for d in database["events"].docs if d.get("learning")]
    assert handled == ["evt_new"]


async def test_sweep_since_is_fixed_once(database):
    first = await worker.sweep_since(database)
    again = await worker.sweep_since(database)
    assert first == again


# ───────────────────────── idempotent side effects ─────────────────────────
async def test_phrase_counts_each_event_once_and_merges_same_wording(database):
    e1, e2 = worker.Event.model_validate(typed("evt_1")), worker.Event.model_validate(typed("evt_2", "see you friday,  dana."))
    for evt in (e1, e1, e2, e2):            # each event delivered twice
        await phrasebook.learn_phrase(evt)
    assert len(phrases(database)) == 1
    assert phrases(database)[0]["uses"] == 2 and phrases(database)[0]["learning_events"] == ["evt_1", "evt_2"]


async def test_concurrent_new_phrase_inserts_collapse(database):
    """Both writers miss the existing-phrase lookup and race to insert the same new wording."""
    e1, e2 = worker.Event.model_validate(typed("evt_x")), worker.Event.model_validate(typed("evt_y"))
    pid = phrasebook.phrase_id(USER, "per_dana", "See you Friday, Dana.")
    await database["memories"].insert_one({"_id": pid, "user_id": USER, "person_id": "per_dana", "kind": "phrase",
                                           "status": "retired", "text": "See you Friday, Dana.", "uses": 1,
                                           "learning_events": ["evt_x"]})   # writer X won (not visible as active)
    await phrasebook.learn_phrase(e2)           # writer Y: lookup misses (retired), insert collides
    await phrasebook.learn_phrase(e1)           # X retried: already counted
    assert len(phrases(database)) == 1 and phrases(database)[0]["uses"] == 2


async def test_rule_is_learned_once_across_retries(database):
    evt = worker.Event.model_validate({"_id": "evt_r", "user_id": USER, "type": "suggestion_rejected",
                                       "person_id": "per_mike", "relationship": "acquaintance",
                                       "text": "The meds are rough.", "topics": ["medication"],
                                       "reason": "too_personal", "created_at": NOW})
    first = await boundaries_mod.propose_and_validate(evt)
    database["boundaries"].docs[0]["status"] = "proposed"        # a retry that doesn't see it active
    assert first is not None and await boundaries_mod.propose_and_validate(evt) is None
    assert len(database["boundaries"].docs) == 1


async def test_episode_retry_finishes_thread_resolution_without_new_episode(database, monkeypatch):
    await database["people"].insert_one({"_id": "per_sam", "user_id": USER, "name": "Sam Chen", "relationship": "family"})
    await database["memories"].insert_one({"_id": "mem_old", "user_id": USER, "person_id": "per_sam", "kind": "episode",
                                           "status": "active", "text": "Nov 8", "created_at": NOW,
                                           "open_threads": [{"id": "thr_1", "text": "send score", "owner": "partner",
                                                             "status": "open"}]})
    for i, (kind, pid, text) in enumerate([("partner", "per_sam", "We won 4-2!"), ("user", None, "Proud of you, bud.")]):
        await database["utterances"].insert_one({"_id": f"u{i}", "session_id": "ses_s", "user_id": USER,
                                                 "speaker": {"kind": kind, "person_id": pid}, "text": text,
                                                 "created_at": i})
    llm_calls = []

    async def fake_llm(system, user, schema, **kw):
        llm_calls.append(1)
        return EpisodeSummary(summary="Sam won 4-2.", topics=["hobbies"], threads_resolved_ids=["thr_1"])
    monkeypatch.setattr(episodes, "complete_json", fake_llm)

    async def crash_before_threads(*args, **kwargs):
        raise RuntimeError("worker killed")
    monkeypatch.setattr(memory_mod, "resolve_threads", crash_before_threads)
    evt = worker.Event.model_validate({"_id": "evt_end", "user_id": USER, "type": "session_ended",
                                       "session_id": "ses_s", "person_id": "per_sam", "created_at": NOW})
    with pytest.raises(RuntimeError):
        await episodes.summarize_session(evt)            # episode inserted, threads NOT resolved
    old = next(d for d in database["memories"].docs if d["_id"] == "mem_old")
    assert old["open_threads"][0]["status"] == "open"

    monkeypatch.undo()                                   # restart with healthy code
    for module in (phrasebook, boundaries_mod, episodes, memory_mod):
        monkeypatch.setattr(module, "db", lambda: database)
    monkeypatch.setattr(episodes, "complete_json", fake_llm)
    assert await episodes.summarize_session(evt) == "mem_ep_ses_s"
    episodes_written = [d for d in database["memories"].docs if d.get("session_id") == "ses_s"]
    assert len(episodes_written) == 1 and len(llm_calls) == 1
    assert old["open_threads"][0]["status"] == "resolved"


# ───────────────────────── worker-level lease ─────────────────────────
async def test_standby_takes_over_after_lease_expiry(database):
    assert await worker.acquire_lease(database, owner="pcA:1") is True
    assert await worker.acquire_lease(database, owner="pcB:2") is False         # standby
    lock = next(d for d in database["worker_state"].docs if d["_id"] == worker.LOCK_ID)
    lock["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)       # A crashed, no heartbeat
    assert await worker.acquire_lease(database, owner="pcB:2") is True
    assert await worker.acquire_lease(database, owner="pcA:1") is False         # A restarts → standby
