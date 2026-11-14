"""Lane A: LLM wrapper tests. Offline (fake OpenAI-compatible client) + one live test that runs
only when NEBIUS_API_KEY is configured and MOCK_LLM is off in the environment/.env."""
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from app import llm
from app.contracts import GeneratedCandidates


def test_pick_model_exact_case_and_fallback():
    avail = ["Qwen/Qwen3-30B-A3B-Instruct-2507", "zai-org/glm-5.3-flash", "meta-llama/Llama-3.3-70B-Instruct"]
    fb = ["missing/x", "meta-llama/Llama-3.3-70B-Instruct"]
    assert llm.pick_model("zai-org/GLM-5.3-Flash", avail, fb) == "zai-org/glm-5.3-flash"
    assert llm.pick_model("nope/model", avail, fb) == "meta-llama/Llama-3.3-70B-Instruct"
    assert llm.pick_model("nope/model", avail, ["missing/x"]) is None


def test_requested_mapping():
    from app.config import settings
    assert llm._nebius_requested(None) == settings.nebius_model
    assert llm._nebius_requested(settings.suggest_model) == settings.nebius_model
    assert llm._nebius_requested("org/custom") == "org/custom"


def test_validate_sanitizes_offtaxonomy_topics_and_think_tags():
    raw = ('<think>let me think</think>```json\n{"candidates":[{"text":"Nice weather!",'
           '"topics":["Weather","small talk"]},{"text":"My meds are rough","topics":["Medication"]},'
           '"Just a string reply"]}\n```')
    out = llm._validate(GeneratedCandidates, raw)
    assert [c.text for c in out.candidates] == ["Nice weather!", "My meds are rough", "Just a string reply"]
    assert out.candidates[0].topics == ["small_talk"]
    assert out.candidates[1].topics == ["medication"]


class _FakeCompletions:
    def __init__(self, reject_json_mode: bool, payload: dict):
        self.reject = reject_json_mode
        self.payload = payload
        self.calls: list[dict] = []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.reject and "response_format" in kw:
            req = httpx.Request("POST", "https://example.test/v1/chat/completions")
            resp = httpx.Response(400, request=req, json={"error": {"message": "response_format not supported"}})
            raise openai.BadRequestError("response_format json_object is not supported", response=resp, body=None)
        msg = SimpleNamespace(content=json.dumps(self.payload), reasoning_content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _client(fake):
    return SimpleNamespace(chat=SimpleNamespace(completions=fake))


PAYLOAD = {"candidates": [{"text": "Yes please, same as October.", "topics": ["medication"], "memory_ids": []}]}


async def test_json_mode_used_when_supported():
    fake = _FakeCompletions(False, PAYLOAD)
    raw = await llm._openai_compat_json(_client(fake), "m/ok", "sys", "user", GeneratedCandidates, 0.3, 500)
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert llm._validate(GeneratedCandidates, raw).candidates[0].text.startswith("Yes")


async def test_json_mode_fallback_when_rejected():
    fake = _FakeCompletions(True, PAYLOAD)
    raw = await llm._openai_compat_json(_client(fake), "m/nojson", "sys", "user", GeneratedCandidates, 0.3, 500)
    assert len(fake.calls) == 2 and "response_format" not in fake.calls[1]
    assert llm._json_mode_ok["m/nojson"] is False
    assert llm._validate(GeneratedCandidates, raw).candidates
    # remembered: next call skips json mode straight away
    await llm._openai_compat_json(_client(fake), "m/nojson", "sys", "user", GeneratedCandidates, 0.3, 500)
    assert len(fake.calls) == 3 and "response_format" not in fake.calls[2]


async def test_mock_still_works(monkeypatch):
    monkeypatch.setattr(llm.settings, "mock_llm", True)
    out = await llm.complete_json("s", "RELATIONSHIP: clinician\nhi", GeneratedCandidates)
    assert len(out.candidates) == 6
