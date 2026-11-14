"""Lane A: LLM wrapper. STABLE SIGNATURE (Lane D uses it).

    await complete_json(system, user, Schema) -> Schema instance

Providers (settings.llm_provider):
- nebius (default): Nebius Token Factory through the OpenAI-compatible client. The configured
  model is checked against GET /v1/models on first use; if it isn't listed, the first available
  entry of NEBIUS_FALLBACK_MODELS is used (and logged). JSON mode (`response_format=json_object`)
  is used when the model accepts it, otherwise prompt-only JSON + extraction.
- anthropic: structured outputs (`messages.parse(output_format=Schema)`), plain-JSON fallback.
- openai: `response_format=json_object`.
Every path validates with Pydantic and retries once on a validation error.
MOCK_LLM returns deterministic, persona-aware canned output so the demo works offline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.contracts import Topic

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_anthropic_client = None
_openai_client = None
_nebius_client = None
_nebius_models: list[str] | None = None          # ids from /v1/models (cached)
_nebius_resolved: dict[str, str] = {}             # requested id -> id actually used
_json_mode_ok: dict[str, bool] = {}               # model id -> response_format accepted?
_resolve_lock: asyncio.Lock | None = None


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
    if (settings.llm_provider == "nebius" and settings.llm_hedge_model
            and _nebius_requested(model) == settings.nebius_model):
        return await _hedged(system, user, schema, temperature, max_tokens)
    return await _complete(system, user, schema, model, temperature, max_tokens)


# ───────────────────────── hedged hot path ─────────────────────────
# DECISION (measured 2026-11-14 16:10 ET): Qwen3-30B-A3B on Token Factory slowed to 6-7 s per
# call (18.8 s once, timeout + SDK retry) while MiniMax-M3.1-Flash answered the same prompt in
# 1.3-1.7 s. The configured model stays primary; if it hasn't answered after LLM_HEDGE_AFTER_S a
# parallel request goes to LLM_HEDGE_MODEL and the first VALID answer wins. Disabled when
# LLM_HEDGE_MODEL is empty. Winners are counted so the demo can say exactly which model answered.
hedge_stats: dict[str, int] = {"primary": 0, "hedge": 0, "failed": 0}
last_hot_model: str | None = None


async def _hedged(system: str, user: str, schema: type[T], temperature: float, max_tokens: int) -> T:
    global last_hot_model
    t0 = time.perf_counter()
    primary = asyncio.create_task(
        _complete(system, user, schema, settings.nebius_model, temperature, max_tokens), name="llm-primary")
    labels: dict[asyncio.Task, tuple[str, str]] = {primary: ("primary", settings.nebius_model)}
    done, _ = await asyncio.wait({primary}, timeout=settings.llm_hedge_after_s)
    pending: set[asyncio.Task] = {primary}
    if not done:
        hedge = asyncio.create_task(
            _complete(system, user, schema, settings.llm_hedge_model, temperature, max_tokens), name="llm-hedge")
        labels[hedge] = ("hedge", settings.llm_hedge_model)
        pending.add(hedge)
        log.info("llm hedge: %s silent after %.1fs; also asking %s", settings.nebius_model,
                 settings.llm_hedge_after_s, settings.llm_hedge_model)
    last_err: BaseException | None = None
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            err = task.exception()
            if err is None:
                for other in pending:
                    other.cancel()
                kind, mdl = labels[task]
                hedge_stats[kind] += 1
                last_hot_model = mdl
                log.info("llm hot path answered by %s (%s) in %dms", mdl, kind, (time.perf_counter() - t0) * 1000)
                return task.result()
            last_err = err
            log.warning("llm %s failed: %s", labels[task][1], str(err)[:200])
            if task is primary and len(labels) == 1:   # primary failed fast: hedge immediately
                hedge = asyncio.create_task(
                    _complete(system, user, schema, settings.llm_hedge_model, temperature, max_tokens))
                labels[hedge] = ("hedge", settings.llm_hedge_model)
                pending.add(hedge)
    hedge_stats["failed"] += 1
    raise last_err if isinstance(last_err, Exception) else LLMUnavailable("hot path failed")


async def _complete(system: str, user: str, schema: type[T], model: str | None,
                    temperature: float, max_tokens: int) -> T:
    t0 = time.perf_counter()
    last_err: Exception | None = None
    prompt = user
    for attempt in range(2):
        try:
            if settings.llm_provider == "nebius":
                requested = _nebius_requested(model)
                mdl = await resolve_nebius_model(requested)
                hot = requested in (settings.nebius_model, settings.llm_hedge_model)
                reasoning = _is_reasoning(mdl)
                raw = await _openai_compat_json(
                    _get_nebius(), mdl, system, prompt, schema, temperature,
                    max(max_tokens, 4096) if reasoning else max_tokens,
                    extra_body={"reasoning_effort": "low"} if reasoning else None,
                    timeout=settings.llm_timeout_s if hot else settings.llm_summary_timeout_s)
                out = _validate(schema, raw)
            elif settings.llm_provider == "openai":
                mdl = model if model and model.startswith(("gpt", "o")) else settings.openai_suggest_model
                raw = await _openai_compat_json(_get_openai(), mdl, system, prompt, schema,
                                                temperature, max_tokens)
                out = _validate(schema, raw)
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


# ───────────────────────── validation ─────────────────────────
_TOPICS = {t.value for t in Topic}


def _clean_topics(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for t in v:
        s = str(t).strip().lower().replace(" ", "_").replace("-", "_")
        if s in _TOPICS and s not in out:
            out.append(s)
    return out


def _sanitize_candidates(d: dict[str, Any]) -> dict[str, Any]:
    cands = d.get("candidates") if isinstance(d, dict) else None
    if isinstance(d, list):
        cands = d
    if not isinstance(cands, list):
        return d
    clean = []
    for c in cands:
        if isinstance(c, str):
            c = {"text": c}
        if not isinstance(c, dict) or not str(c.get("text", "")).strip():
            continue
        mids = c.get("memory_ids") or []
        clean.append({"text": str(c["text"]).strip(), "topics": _clean_topics(c.get("topics")),
                      "memory_ids": [str(m) for m in mids] if isinstance(mids, list) else []})
    return {"candidates": clean}


def _sanitize_summary(d: dict[str, Any]) -> dict[str, Any]:
    if isinstance(d, dict) and "topics" in d:
        d = {**d, "topics": _clean_topics(d["topics"])}
    return d


# Off-taxonomy topics from a real LLM ("weather") must not fail the whole response.
_SANITIZERS: dict[str, Callable[[Any], Any]] = {
    "GeneratedCandidates": _sanitize_candidates,
    "EpisodeSummary": _sanitize_summary,
}


def _validate(schema: type[T], raw: str) -> T:
    data = json.loads(_extract_json(raw))
    fix = _SANITIZERS.get(schema.__name__)
    if fix:
        data = fix(data)
    return schema.model_validate(data)


def _extract_json(text: str) -> str:
    text = _THINK.sub("", text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in LLM output: {text[:200]!r}")
    return text[start:end + 1]


def _schema_hint(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), separators=(",", ":"))


def _json_system(system: str, schema: type[BaseModel]) -> str:
    return (f"{system}\n\nRespond with ONLY a JSON object (no prose, no markdown fences) that "
            f"matches this JSON schema:\n{_schema_hint(schema)}")


# ───────────────────────── Nebius Token Factory ─────────────────────────
def _get_nebius():
    global _nebius_client
    from openai import AsyncOpenAI

    if _nebius_client is None:
        if not settings.nebius_api_key:
            raise LLMUnavailable("NEBIUS_API_KEY not set (or set MOCK_LLM=true)")
        _nebius_client = AsyncOpenAI(base_url=settings.nebius_base_url,
                                     api_key=settings.nebius_api_key,
                                     timeout=settings.llm_timeout_s, max_retries=1)
    return _nebius_client


def _nebius_requested(model: str | None) -> str:
    """Map a caller's model arg onto a Nebius model id.
    Callers pass settings.suggest_model / settings.summary_model (Claude ids from the original
    design); those map to the Nebius equivalents. A Nebius-style id ("org/name") passes through."""
    if model and "/" in model:
        return model
    if model and model == settings.summary_model and settings.nebius_summary_model:
        return settings.nebius_summary_model
    return settings.nebius_model


async def list_nebius_models() -> list[str]:
    global _nebius_models
    if _nebius_models is None:
        page = await _get_nebius().models.list()
        _nebius_models = sorted(m.id for m in page.data)
    return _nebius_models


async def resolve_nebius_model(requested: str) -> str:
    """Return `requested` if /v1/models lists it, else the first available fallback."""
    global _resolve_lock
    if requested in _nebius_resolved:
        return _nebius_resolved[requested]
    if _resolve_lock is None:
        _resolve_lock = asyncio.Lock()
    async with _resolve_lock:
        if requested in _nebius_resolved:
            return _nebius_resolved[requested]
        try:
            available = await list_nebius_models()
        except Exception as e:  # noqa: BLE001  can't list → trust the configured id
            log.warning("nebius /v1/models failed (%s); using %s unverified", str(e)[:200], requested)
            _nebius_resolved[requested] = requested
            return requested
        chosen = pick_model(requested, available,
                            [f.strip() for f in settings.nebius_fallback_models.split(",") if f.strip()])
        if chosen is None:
            raise LLMUnavailable(f"nebius: {requested} not available and no fallback listed; "
                                 f"available: {available[:20]}")
        if chosen != requested:
            log.warning("nebius model %s not available; using fallback %s", requested, chosen)
        else:
            log.info("nebius model %s verified via /v1/models", chosen)
        _nebius_resolved[requested] = chosen
        return chosen


def pick_model(requested: str, available: list[str], fallbacks: list[str]) -> str | None:
    """Pure: exact match, then case-insensitive match, then first available fallback."""
    avail = set(available)
    if requested in avail:
        return requested
    lower = {a.lower(): a for a in available}
    if requested.lower() in lower:
        return lower[requested.lower()]
    for fb in fallbacks:
        if fb in avail:
            return fb
        if fb.lower() in lower:
            return lower[fb.lower()]
    return None


# ───────────────────────── OpenAI-compatible (Nebius + OpenAI) ─────────────────────────
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _is_reasoning(model: str) -> bool:
    prefixes = [p.strip().lower() for p in settings.nebius_reasoning_models.split(",") if p.strip()]
    return any(model.lower().startswith(p) for p in prefixes)


async def _openai_compat_json(client, model: str, system: str, user: str, schema: type[BaseModel],
                              temperature: float, max_tokens: int, *,
                              extra_body: dict[str, Any] | None = None,
                              timeout: float | None = None) -> str:
    """Chat completion asking for JSON. Uses response_format=json_object when the model accepts
    it; on a 400 that mentions it, remembers that and retries prompt-only."""
    import openai

    if timeout is not None and hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout)
    messages = [{"role": "system", "content": _json_system(system, schema)},
                {"role": "user", "content": user}]
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                              "temperature": temperature}
    if extra_body:
        kwargs["extra_body"] = extra_body
    if _json_mode_ok.get(model, True):
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = await client.chat.completions.create(**kwargs)
    except openai.BadRequestError as e:
        msg = str(e).lower()
        if "response_format" in kwargs and ("response_format" in msg or "json" in msg):
            log.warning("%s rejected response_format (%s); using prompt-only JSON", model, str(e)[:160])
            _json_mode_ok[model] = False
            kwargs.pop("response_format")
        elif "extra_body" in kwargs and "reasoning" in msg:
            log.warning("%s rejected reasoning_effort; retrying without it", model)
            kwargs.pop("extra_body")
        elif "max_tokens" in msg or "temperature" in msg:
            kwargs.pop("temperature", None)
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        else:
            raise LLMUnavailable(f"{model} 400: {str(e)[:200]}") from e
        try:
            resp = await client.chat.completions.create(**kwargs)
        except openai.APIError as e2:
            raise LLMUnavailable(f"{model}: {str(e2)[:200]}") from e2
    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        raise LLMUnavailable(f"{model} connection: {str(e)[:200]}") from e
    except openai.APIStatusError as e:
        raise LLMUnavailable(f"{model} {e.status_code}: {str(e)[:200]}") from e
    if not resp.choices:
        raise ValueError(f"{model} returned no choices")
    choice = resp.choices[0]
    text = choice.message.content or ""
    if not text.strip():
        # reasoning models can burn the whole budget thinking and return empty content
        raise ValueError(f"{model} returned empty content (finish_reason={choice.finish_reason})")
    return text


def _get_openai():
    global _openai_client
    from openai import AsyncOpenAI

    if _openai_client is None:
        if not settings.openai_api_key:
            raise LLMUnavailable("OPENAI_API_KEY not set (or set MOCK_LLM=true)")
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key,
                                     timeout=settings.llm_timeout_s, max_retries=1)
    return _openai_client


# ───────────────────────── Anthropic ─────────────────────────
async def _anthropic_json(system: str, user: str, schema: type[T], model: str | None,
                          max_tokens: int) -> T:
    global _anthropic_client
    import anthropic

    if _anthropic_client is None:
        if not settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not set (or set MOCK_LLM=true)")
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key,
                                                     timeout=settings.llm_timeout_s, max_retries=1)
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
        log.warning("structured outputs unavailable (%s); falling back to JSON prompt", str(e)[:200])
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable(f"anthropic connection: {e}") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"anthropic {e.status_code}: {e.message}") from e

    resp = await _anthropic_client.messages.create(
        model=mdl, max_tokens=max_tokens, system=_json_system(system, schema),
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _validate(schema, text)


# ───────────────────────── mock ─────────────────────────
# Canned replies in Maya's voice. Keyed by relationship parsed from the prompt
# (the pipeline writes a `RELATIONSHIP: <value>` line). Each list deliberately mixes
# intents and includes a sensitive candidate so the guard has something to block.
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
