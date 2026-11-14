"""Lane A: LLM wrapper. STABLE SIGNATURE (Lane D uses it).

    await complete_json(system, user, Schema) -> Schema instance

Anthropic (default) uses structured outputs (`messages.parse(output_format=Schema)`), with a
plain-JSON fallback. OpenAI uses `response_format=json_object`. Validation errors retry once.
MOCK_LLM returns deterministic, persona-aware canned output so the demo works offline.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_anthropic_client = None
_openai_client = None


class LLMUnavailable(RuntimeError):
    """Raised when the provider can't be reached / isn't configured. Callers degrade."""


async def complete_json(system: str, user: str, schema: type[T], *, model: str | None = None,
                        temperature: float = 0.3, max_tokens: int = 2048) -> T:
    """Return an instance of `schema`. Honours settings.mock_llm."""
    t0 = time.perf_counter()
    if settings.mock_llm:
        out = mock_response(system, user, schema)
        log.info("llm mock %s %dms", schema.__name__, (time.perf_counter() - t0) * 1000)
        return out

    last_err: Exception | None = None
    prompt = user
    for attempt in range(2):
        try:
            if settings.llm_provider == "openai":
                raw = await _openai_json(system, prompt, schema, model, temperature, max_tokens)
                out = schema.model_validate_json(_extract_json(raw))
            else:
                out = await _anthropic_json(system, prompt, schema, model, max_tokens)
            log.info("llm %s %s %dms (attempt %d)", settings.llm_provider, schema.__name__,
                     (time.perf_counter() - t0) * 1000, attempt + 1)
            return out
        except (ValidationError, ValueError) as e:
            last_err = e
            log.warning("llm validation failed (attempt %d): %s", attempt + 1, str(e)[:300])
            prompt = (f"{user}\n\nYour previous answer was invalid: {str(e)[:300]}\n"
                      f"Return ONLY valid JSON matching the schema.")
    raise LLMUnavailable(f"LLM output failed validation twice: {last_err}")


# ───────────────────────── providers ─────────────────────────
def _schema_hint(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), separators=(",", ":"))


async def _anthropic_json(system: str, user: str, schema: type[T], model: str | None,
                          max_tokens: int) -> T:
    global _anthropic_client
    import anthropic

    if _anthropic_client is None:
        if not settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not set (or set MOCK_LLM=true)")
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key,
                                                     timeout=20.0, max_retries=1)
    mdl = model or settings.suggest_model
    try:
        # Structured outputs: schema-constrained decoding, validated into `schema`.
        resp = await _anthropic_client.messages.parse(
            model=mdl, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": "low"},
        )
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("model refused")
        if resp.parsed_output is not None:
            return resp.parsed_output
    except (AttributeError, TypeError, anthropic.BadRequestError) as e:
        # Older SDK / model without structured outputs → plain JSON prompt.
        log.warning("structured outputs unavailable (%s); falling back to JSON prompt", str(e)[:200])
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable(f"anthropic connection: {e}") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"anthropic {e.status_code}: {e.message}") from e

    resp = await _anthropic_client.messages.create(
        model=mdl, max_tokens=max_tokens,
        system=f"{system}\n\nRespond with ONLY a JSON object matching this JSON schema:\n{_schema_hint(schema)}",
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return schema.model_validate_json(_extract_json(text))


async def _openai_json(system: str, user: str, schema: type[BaseModel], model: str | None,
                       temperature: float, max_tokens: int) -> str:
    global _openai_client
    from openai import AsyncOpenAI

    if _openai_client is None:
        if not settings.openai_api_key:
            raise LLMUnavailable("OPENAI_API_KEY not set (or set MOCK_LLM=true)")
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=20.0, max_retries=1)
    resp = await _openai_client.chat.completions.create(
        model=model if model and not model.startswith("claude") else settings.openai_suggest_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": f"{system}\n\nRespond with ONLY a JSON object matching "
                                          f"this JSON schema:\n{_schema_hint(schema)}"},
            {"role": "user", "content": user},
        ],
        max_completion_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def _extract_json(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in LLM output: {text[:200]!r}")
    return text[start:end + 1]


# ───────────────────────── mock ─────────────────────────
# Canned replies in Maya's voice. Keyed by relationship parsed from the prompt
# (the pipeline writes a `RELATIONSHIP: <value>` line). Each list deliberately mixes
# intents and includes one sensitive candidate so the guard has something to block.
_MOCK_CANDIDATES: dict[str, list[tuple[str, list[str]]]] = {
    "clinician": [
        ("Yes please, same refill as October.", ["medication", "logistics"]),
        ("Did the blister packs come in?", ["medication", "logistics"]),
        ("The new generic looks different. Same dose?", ["medication"]),
        ("Thanks Dana, you're always quick.", ["emotions_positive"]),
        ("Breathing's been a bit harder at night.", ["health"]),
        ("Can I pick it up Friday instead?", ["logistics"]),
    ],
    "acquaintance": [
        ("Doing alright, thanks for asking.", ["small_talk"]),
        ("Honestly the new meds are rough.", ["health", "medication"]),
        ("How's the dog doing?", ["small_talk"]),
        ("Ha, the weather's finally decent.", ["small_talk", "humour"]),
        ("Been tired lately, but hanging in.", ["health"]),
        ("Good to see you, Mike.", ["small_talk"]),
    ],
    "family": [
        ("Proud of you, bud.", ["emotions_positive"]),
        ("How was practice? Did you play defence?", ["hobbies"]),
        ("Tell me everything, I've got time.", ["emotions_positive"]),
        ("Ha. Your coach is lucky to have you.", ["humour", "hobbies"]),
        ("I'm a bit tired today, but I'm good.", ["health"]),
        ("Love you. Dinner's at six.", ["emotions_positive", "logistics"]),
    ],
    "stranger": [
        ("Hi there, nice to meet you.", ["small_talk"]),
        ("Thanks, I'm all set.", ["small_talk"]),
        ("Sorry, could you say that again?", ["small_talk"]),
        ("I use this tablet to talk. Give me a sec.", ["small_talk"]),
        ("My ALS makes talking slow.", ["health"]),
        ("Have a good one!", ["small_talk"]),
    ],
}
_MOCK_CANDIDATES["close_friend"] = _MOCK_CANDIDATES["family"]
_MOCK_CANDIDATES["caregiver"] = _MOCK_CANDIDATES["clinician"]
_MOCK_CANDIDATES["service"] = _MOCK_CANDIDATES["stranger"]


def mock_response(system: str, user: str, schema: type[T]) -> T:
    name = schema.__name__
    if name == "GeneratedCandidates":
        m = re.search(r"RELATIONSHIP:\s*(\w+)", user)
        rel = m.group(1) if m else "stranger"
        cands = _MOCK_CANDIDATES.get(rel, _MOCK_CANDIDATES["stranger"])
        # The mock deliberately ignores AVOID TOPICS, like an imperfect LLM would: the
        # deterministic guard (not the prompt) is what must keep sensitive replies hidden.
        mem_ids = re.findall(r"\[(mem_[\w]+)\]", user)[:1]
        out = [{"text": t, "topics": tp, "memory_ids": mem_ids if i == 0 else []}
               for i, (t, tp) in enumerate(cands)]
        # pad to 6 with safe small talk when the avoid list removed some
        pad = ["Ha, fair enough.", "Tell me more.", "Sounds good.", "Thanks!"]
        while len(out) < 6 and pad:
            out.append({"text": pad.pop(0), "topics": ["small_talk"], "memory_ids": []})
        return schema.model_validate({"candidates": out})
    if name == "EpisodeSummary":
        return schema.model_validate({
            "summary": "Short catch-up. Talked logistics and small talk.",
            "topics": ["small_talk"], "open_threads_new": [], "threads_resolved_ids": [],
        })
    return _minimal_instance(schema)


def _minimal_instance(schema: type[T]) -> T:
    """Best-effort valid instance for unknown schemas (other lanes' LLM calls)."""
    data: dict[str, Any] = {}
    for fname, field in schema.model_fields.items():
        if not field.is_required():
            continue
        ann = field.annotation
        origin = getattr(ann, "__origin__", None)
        if ann is str:
            data[fname] = "mock"
        elif ann in (int, float):
            data[fname] = 0
        elif ann is bool:
            data[fname] = False
        elif origin in (list, set, tuple):
            data[fname] = []
        elif origin is dict:
            data[fname] = {}
        elif isinstance(ann, type) and issubclass(ann, BaseModel):
            data[fname] = _minimal_instance(ann).model_dump()
        else:
            data[fname] = None
    return schema.model_validate(data)
