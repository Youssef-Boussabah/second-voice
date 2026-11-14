"""release-final regressions: privacy before the prompt, cross-partner isolation, nickname scope,
boundary toast semantics, worker exactly-once + single-instance. All run with mocks, no network."""
import os

os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("MOCK_EMBED", "true")

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from app.contracts import (  # noqa: E402
    Boundary, BoundaryScope, Memory, OpenThread, PersonOut, RetrievedContext,
)
from app.guard.enforce import filter_context  # noqa: E402
from app.memory.retrieval import partner_segment  # noqa: E402
from app.realtime.hub import boundary_change_is_news  # noqa: E402

USER = "usr_maya"
MIKE = PersonOut(id="per_mike", name="Mike Russo", relationship="acquaintance")
DANA = PersonOut(id="per_dana", name="Dana Okafor", relationship="clinician")
RULE = Boundary(id="bnd_acq_health", user_id=USER, status="active",
                scope=BoundaryScope(type="relationship", value="acquaintance"),
                topics=["health", "medication"])


def mem(mid, text, topics, kind="episode", pid="per_mike", threads=()):
    return Memory(id=mid, user_id=USER, person_id=pid, kind=kind, text=text, topics=topics,
                  open_threads=list(threads))


def mike_ctx() -> RetrievedContext:
    thread = OpenThread(id="thr_meds", text="Mike waiting for an update on the new medication", owner="partner")
    meds_ep = mem("mem_meds", "Mike asked how the new medication is working.", ["health"], threads=[thread])
    return RetrievedContext(
        person=MIKE, boundaries=[RULE],
        recent_episodes=[mem("mem_dog", "Mike's dog chewed boots.", ["small_talk"]), meds_ep],
        relevant_episodes=[meds_ep],
        open_threads=[thread, OpenThread(id="thr_snow", text="Compare snow tires", owner="user")],
        # the keyword safety net must catch an untagged sensitive fact / phrase
        facts=[mem("mem_f_pain", "Maya's back pain flares at night.", [], kind="fact", pid="global"),
               mem("mem_f_dog", "Mike has a young dog.", ["hobbies"], kind="fact")],
        phrases=[mem("mem_p_meds", "The meds are an experience.", [], kind="phrase"),
                 mem("mem_p_dog", "How's the boot thief?", ["small_talk"], kind="phrase")],
    )


def test_blocked_context_never_reaches_the_prompt():
    out, withheld = filter_context(mike_ctx(), MIKE)
    kept = [m.text for m in [*out.recent_episodes, *out.relevant_episodes, *out.facts, *out.phrases]]
    kept += [t.text for t in out.open_threads]
    blob = " ".join(kept).lower()
    assert not any(w in blob for w in ("medication", "meds", "pain")), kept
    assert [t.id for t in out.open_threads] == ["thr_snow"]
    assert [m.id for m in out.recent_episodes] == ["mem_dog"] and out.relevant_episodes == []
    assert withheld == 4   # meds episode, pain fact, meds phrase, meds thread


def test_clinician_context_is_untouched():
    ctx = mike_ctx().model_copy(update={"person": DANA})
    out, withheld = filter_context(ctx, DANA)
    assert withheld == 0 and out == ctx


def test_build_prompt_contains_no_withheld_text():
    from app.contracts import PipelineState, SpeakerMatch, Utterance
    from app.graph.pipeline import build_prompt
    utt = Utterance(session_id="ses_1", user_id=USER, text="How've you been?", source="text",
                    speaker=SpeakerMatch(kind="partner", person_id="per_mike", method="forced"))
    ctx, _ = filter_context(mike_ctx(), MIKE)
    prompt = build_prompt(PipelineState(utterance=utt, person=MIKE, context=ctx), ["health", "medication"])
    assert "medication is working" not in prompt and "back pain" not in prompt
    assert "boots" in prompt and "AVOID TOPICS: health, medication" in prompt


def _u(i, kind, pid=None):
    return {"_id": f"utt_{i}", "speaker": {"kind": kind, "person_id": pid}, "text": f"t{i}", "created_at": i}


def test_partner_segment_drops_previous_partner():
    docs = [_u(1, "partner", "per_dana"), _u(2, "user"), _u(3, "partner", "per_dana"), _u(4, "user"),
            _u(5, "partner", "per_mike"), _u(6, "user"), _u(7, "partner", None)]
    assert [d["_id"] for d in partner_segment(docs, "per_mike")] == ["utt_5", "utt_6", "utt_7"]
    assert partner_segment(docs[:6], "per_dana") == []      # Dana is no longer the trailing partner
    assert [d["_id"] for d in partner_segment(docs[:4], "per_dana")] == ["utt_1", "utt_2", "utt_3", "utt_4"]


async def test_mixed_session_episode_only_covers_last_partner(monkeypatch):
    from app.contracts import EpisodeSummary, Event, EventType
    from app.learning import episodes, memory as memory_mod
    from test_d_fakedb import FakeDB
    database = FakeDB()
    for module in (episodes, memory_mod):
        monkeypatch.setattr(module, "db", lambda: database)
    await database["people"].insert_one({"_id": "per_sam", "user_id": USER, "name": "Sam Chen",
                                         "relationship": "family", "label": "Maya's grandson"})
    turns = [("partner", "per_dana", "Any side effects with the new generic?"), ("user", None, "None so far."),
             ("partner", "per_sam", "We won Saturday!"), ("user", None, "Proud of you, bud.")]
    for i, (kind, pid, text) in enumerate(turns):
        await database["utterances"].insert_one({"_id": f"utt_{i}", "session_id": "ses_mix", "user_id": USER,
                                                 "speaker": {"kind": kind, "person_id": pid}, "text": text,
                                                 "created_at": i})
    seen = []

    async def fake_llm(system, user, schema, **kw):
        seen.append(user)
        return EpisodeSummary(summary="Sam's team won Saturday.", topics=["hobbies"])
    monkeypatch.setattr(episodes, "complete_json", fake_llm)
    evt = Event(user_id=USER, type=EventType.session_ended, session_id="ses_mix", person_id="per_sam",
                relationship="family")
    assert await episodes.summarize_session(evt) == "mem_ep_ses_mix"
    assert "side effects" not in seen[0] and "generic" not in seen[0]
    assert "Sam: We won Saturday!" in seen[0] and "PARTNER: Sam Chen (Maya's grandson)" in seen[0]


async def test_bud_is_dropped_for_non_family(monkeypatch):
    from app.contracts import GeneratedCandidates, PipelineState, SpeakerMatch, Utterance
    from app.graph import pipeline

    async def fake_llm(system, user, schema, **kw):
        return GeneratedCandidates.model_validate({"candidates": [
            {"text": "Good to see you, bud.", "topics": ["small_talk"]},
            {"text": "Good to see you, Mike.", "topics": ["small_talk"]}]})
    monkeypatch.setattr(pipeline, "complete_json", fake_llm)
    utt = Utterance(session_id="ses_1", user_id=USER, text="Hey!", source="text",
                    speaker=SpeakerMatch(kind="partner", person_id="per_mike", method="forced"))
    sam = PersonOut(id="per_sam", name="Sam Chen", relationship="family")
    for person, expected in ((MIKE, ["Good to see you, Mike."]),
                             (sam, ["Good to see you, bud.", "Good to see you, Mike."])):
        st = PipelineState(utterance=utt, person=person, context=RetrievedContext())
        await pipeline.generate(st)
        assert [c.text for c in st.generated] == expected


@pytest.mark.parametrize("change,status,news", [
    ({"operationType": "insert"}, "active", True),
    ({"operationType": "insert"}, "proposed", True),
    ({"operationType": "replace"}, "active", False),                     # demo reset re-seeding
    ({"operationType": "update", "updateDescription": {"updatedFields": {"status": "active"}}}, "active", True),
    ({"operationType": "update", "updateDescription": {"updatedFields": {"evidence": {}}}}, "active", False),
])
def test_boundary_toast_only_on_real_changes(change, status, news):
    assert boundary_change_is_news(change, status) is news


async def test_worker_processes_each_event_once(monkeypatch):
    from app.learning import worker
    from test_d_fakedb import FakeDB
    database = FakeDB()
    calls = []

    async def fake_handle(event):
        calls.append(event.id)
    monkeypatch.setattr(worker, "handle", fake_handle)
    record = {"_id": "evt_2", "user_id": USER, "type": "suggestion_selected",
              "created_at": datetime.now(timezone.utc)}
    await database["events"].insert_one(record)
    for _ in range(2):                       # change-stream re-delivery after a crash
        await worker.process_change(database, {"fullDocument": record})
    assert calls == ["evt_2"]
    assert await worker.claim(database, "evt_2") is False


async def test_second_worker_is_refused_a_lease():
    from pymongo.errors import DuplicateKeyError

    from app.learning import worker
    from test_d_fakedb import matches

    class LeaseColl:
        """Mongo semantics for the lease upsert: a live lease held by someone else → duplicate key."""
        def __init__(self):
            self.doc = None

        async def update_one(self, flt, update, upsert=False):
            if self.doc is not None and matches(self.doc, flt):
                self.doc.update(update["$set"])
            elif self.doc is not None:
                raise DuplicateKeyError("E11000 duplicate key")
            else:
                self.doc = {"_id": flt["_id"], **update["$set"]}

    lease_db = {"worker_state": LeaseColl()}
    assert await worker.acquire_lease(lease_db, owner="pc:1") is True
    assert await worker.acquire_lease(lease_db, owner="pc:2") is False   # second worker refused
    assert await worker.acquire_lease(lease_db, owner="pc:1") is True    # heartbeat renews


async def test_same_rejection_never_creates_two_rules(monkeypatch):
    """Live 2026-11-14: two workers processed one rejection and wrote two identical rules."""
    from app.contracts import Event, EventType
    from app.learning import boundaries as boundaries_mod
    from test_d_fakedb import FakeDB
    database = FakeDB()
    monkeypatch.setattr(boundaries_mod, "db", lambda: database)
    evt = Event(id="evt_f657f7aaee40", user_id=USER, type=EventType.suggestion_rejected, person_id="per_mike",
                relationship="acquaintance", text="Still surviving the medication grind.",
                topics=["medication"], reason="too_personal")
    first = await boundaries_mod.propose_and_validate(evt)
    # simulate a second worker that has not seen the first rule yet (status not active)
    database["boundaries"].docs[0]["status"] = "proposed"
    second = await boundaries_mod.propose_and_validate(evt)
    assert first is not None and first.id == "bnd_f657f7aaee40" and second is None
    assert len(database["boundaries"].docs) == 1


def test_partner_and_typed_text_is_bounded():
    from fastapi import HTTPException

    from app.api.core_routes import MAX_TEXT, _checked_text
    assert _checked_text("  hi  ") == "hi"
    for bad in ("   ", "x" * (MAX_TEXT + 1)):
        with pytest.raises(HTTPException) as err:
            _checked_text(bad)
        assert err.value.status_code == 400
