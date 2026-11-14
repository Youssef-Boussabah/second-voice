"""Lane A: instant stage. Pure ranking tests + pipeline tests on the isolated test DB covering
a Voyage outage, an empty phrasebook, privacy rules in BOTH stages, and latency instrumentation."""
import os

os.environ.update({k: "true" for k in ["MOCK_LLM", "MOCK_EMBED", "MOCK_STT", "MOCK_SPEAKER", "MOCK_TTS"]})
os.environ["USE_CHANGE_STREAMS"] = "false"
os.environ["MONGODB_DB"] = "second_voice_test"

import uuid  # noqa: E402

import pytest  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.contracts import Memory, SpeakerMatch, Utterance, utcnow  # noqa: E402
from app.graph import instant, pipeline  # noqa: E402
from app.realtime import hub  # noqa: E402

SENSITIVE_FOR_ACQ = {"health", "medication", "distress"}


# ───────────────────────── pure ranking ─────────────────────────
def _ph(text, pid="per_x", uses=0, topics=("small_talk",)):
    return Memory(user_id="u", person_id=pid, kind="phrase", text=text, uses=uses, topics=list(topics))


def test_rank_prefers_relevant_then_used_then_person_specific():
    phrases = [_ph("Proud of you, bud.", "per_sam", uses=7),
               _ph("Did the hockey game go to overtime?", "global", uses=0),
               _ph("Living the glamorous elevator-lobby life.", "global", uses=3)]
    out = instant.rank_quick_replies("How was the hockey game last night?", phrases, "per_sam")
    assert out[0].text.startswith("Did the hockey game")       # lexical relevance wins
    assert out[1].text == "Proud of you, bud."                   # then usage + person-specific
    assert all(c.source == "phrasebook" for c in out)


def test_empty_phrasebook_gives_cue_matched_neutral_replies():
    out = instant.rank_quick_replies("Hi Maya, how have you been feeling lately?", [], None)
    texts = [c.text for c in out]
    assert len(out) >= 4
    assert texts[0] == "Hi! Good to see you." and "Doing okay, thanks. You?" in texts
    assert all(set(c.topics) <= {"small_talk", "humour"} for c in out)


# ───────────────────────── pipeline on the test DB ─────────────────────────
SUFFIX = uuid.uuid4().hex[:6]
UID = f"usr_t_{SUFFIX}"
MIKE, DANA, NEW = f"per_m_{SUFFIX}", f"per_d_{SUFFIX}", f"per_n_{SUFFIX}"


@pytest.fixture(scope="module")
def seeded():
    assert settings.mongodb_db == "second_voice_test", "test must never touch the real DB"
    try:
        mc = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
        mc.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"MongoDB unreachable: {e}")
    d = mc[settings.mongodb_db]
    d.people.insert_many([
        {"_id": MIKE, "user_id": UID, "name": "Mike", "relationship": "acquaintance"},
        {"_id": DANA, "user_id": UID, "name": "Dana", "relationship": "clinician"},
        {"_id": NEW, "user_id": UID, "name": "Pat", "relationship": "acquaintance"},
    ])
    d.memories.insert_many([
        # a sensitive phrase Maya really used with Mike before the rule existed: must be hidden
        {"_id": f"mem_a_{SUFFIX}", "user_id": UID, "person_id": MIKE, "kind": "phrase", "status": "active",
         "text": "Honestly the new meds are rough.", "topics": ["small_talk"], "uses": 9},
        {"_id": f"mem_b_{SUFFIX}", "user_id": UID, "person_id": MIKE, "kind": "phrase", "status": "active",
         "text": "Ha, the Leafs will break our hearts again.", "topics": ["humour", "hobbies"], "uses": 4},
        {"_id": f"mem_c_{SUFFIX}", "user_id": UID, "person_id": DANA, "kind": "phrase", "status": "active",
         "text": "Same refill as last month, thanks.", "topics": ["medication"], "uses": 5},
        {"_id": f"mem_d_{SUFFIX}", "user_id": UID, "person_id": "global", "kind": "phrase", "status": "active",
         "text": "Living the glamorous elevator-lobby life, obviously.", "topics": ["humour"], "uses": 3},
    ])
    d.boundaries.insert_one({"_id": f"bnd_{SUFFIX}", "user_id": UID, "status": "active", "origin": "seed",
                             "scope": {"type": "relationship", "value": "acquaintance"},
                             "topics": ["health", "medication", "distress"], "action": "block"})
    yield d
    for c in ("people", "memories", "boundaries", "utterances", "suggestion_sets", "events", "sessions"):
        d[c].delete_many({"user_id": UID})
    mc.close()


@pytest.fixture
def capture(monkeypatch):
    """Fresh async Mongo client per test loop + capture every WS message the pipeline emits."""
    db._client = None
    msgs: list[tuple[str, dict]] = []

    async def fake_emit(type_, session_id, data, *, all_sessions=False):
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json", by_alias=True)
        msgs.append((type_, data))

    monkeypatch.setattr(hub, "emit", fake_emit)
    yield msgs


async def _run(pid, text):
    utt = Utterance(session_id=f"ses_t_{SUFFIX}", user_id=UID, text=text, source="text",
                    speaker=SpeakerMatch(kind="partner", person_id=pid, method="forced"))
    await db.db()[db.UTTERANCES].insert_one(utt.to_mongo())
    final = await pipeline.run(utt)
    await db.close()
    return final


def _sets(msgs):
    return [d for t, d in msgs if t == "suggestions.ready"]


def _no_leak(s):
    for c in s["candidates"]:
        assert not (set(c["topics"]) & SENSITIVE_FOR_ACQ), f"leak in {s['stage']}: {c}"


async def test_voyage_outage_still_publishes_instant_then_final(seeded, capture, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("voyage 429: rate limited")
    monkeypatch.setattr(pipeline, "embed_query", boom)
    final = await _run(MIKE, "Hey Maya, did you catch the Leafs game?")
    sets = _sets(capture)
    assert [s["stage"] for s in sets] == ["instant", "final"]          # instant first, then replaced
    assert len(sets[0]["candidates"]) == 4 and len(sets[1]["candidates"]) == 4
    assert sets[0]["candidates"][0]["text"].startswith("Ha, the Leafs")  # relevant saved phrase first
    assert final.stage == "final"


async def test_missing_phrases_uses_neutral_quick_replies(seeded, capture):
    await _run(NEW, "Hi Maya! How have you been feeling lately?")
    inst = _sets(capture)[0]
    assert inst["stage"] == "instant" and len(inst["candidates"]) == 4
    texts = [c["text"] for c in inst["candidates"]]
    assert "Hi! Good to see you." in texts and "Doing okay, thanks. You?" in texts
    _no_leak(inst)


async def test_privacy_enforced_in_both_stages(seeded, capture):
    await _run(MIKE, "How are the new meds treating you?")
    inst, fin = _sets(capture)
    _no_leak(inst)
    _no_leak(fin)
    # the mislabelled sensitive phrase was caught by the safety net and hidden, not dropped silently
    assert any(b["text"] == "Honestly the new meds are rough." and b["blocked_by"] == f"bnd_{SUFFIX}"
               for b in inst["blocked"])
    assert fin["blocked"], "mock LLM proposes meds/tired replies; the guard must hide them"


async def test_clinician_keeps_medication_phrase(seeded, capture):
    await _run(DANA, "Here for your refill?")
    inst = _sets(capture)[0]
    assert inst["candidates"][0]["text"] == "Same refill as last month, thanks."


async def test_latency_instrumented_separately(seeded, capture):
    await _run(MIKE, "Morning Maya!")
    inst, fin = _sets(capture)
    li, lf = inst["latency_ms"], fin["latency_ms"]
    assert {"first_suggestion", "instant_db", "since_utterance"} <= set(li)
    assert {"first_suggestion", "final", "total", "since_utterance"} <= set(lf)
    assert li["first_suggestion"] == lf["first_suggestion"] <= lf["final"]


def test_near_duplicate_neutral_replies_are_skipped():
    out = instant.rank_quick_replies("Can you hear me?", [_ph("Give me a second to type that.", uses=2)], None)
    texts = [c.text for c in out]
    assert "Give me a second to type that." in texts and "Give me a sec to type." not in texts


async def test_immediate_select_after_emit_never_404s(seeded, monkeypatch):
    """Regression: a tap at the exact moment a set becomes visible must succeed.
    We 'tap' from inside hub.emit itself (zero delay, before the pipeline continues)."""
    from app.api import core_routes
    from app.contracts import SelectIn

    db._client = None
    sid = f"ses_tap_{SUFFIX}"
    await db.db()[db.SESSIONS].insert_one({"_id": sid, "user_id": UID, "person_ids": [MIKE],
                                           "status": "active", "started_at": utcnow()})
    taps: list[tuple[str, str]] = []

    async def tapping_emit(type_, session_id, data, *, all_sessions=False):
        if type_ != "suggestions.ready":
            return
        cand = data.candidates[0]
        out = await core_routes.select_suggestion(          # raises HTTPException(404) on a race
            data.id, SelectIn(candidate_id=cand.id, event_id=f"evt_tap_{data.stage}_{SUFFIX}"))
        taps.append((data.stage, out.text_to_speak))

    monkeypatch.setattr(hub, "emit", tapping_emit)
    utt = Utterance(session_id=sid, user_id=UID, text="Hey Maya, did you catch the Leafs game?",
                    source="text", speaker=SpeakerMatch(kind="partner", person_id=MIKE, method="forced"))
    await db.db()[db.UTTERANCES].insert_one(utt.to_mongo())
    await pipeline.run(utt)
    events = await db.db()[db.EVENTS].count_documents({"session_id": sid, "type": "suggestion_selected"})
    await db.close()
    assert [stage for stage, _ in taps] == ["instant", "final"]
    assert all(text for _, text in taps) and events == 2
