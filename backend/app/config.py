"""Settings loaded from the repo-root .env. Lane A owns this file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "second_voice"
    use_change_streams: bool = True
    demo_user_id: str = "usr_maya"

    # LLM
    llm_provider: str = "nebius"               # nebius | anthropic | openai
    suggest_model: str = "claude-haiku-5-5"
    summary_model: str = "claude-sonnet-5-5"
    openai_suggest_model: str = "gpt-5-mini"   # DECISION: set to whatever your OpenAI key has
    anthropic_api_key: str = ""
    # Nebius Token Factory (OpenAI-compatible). Model is verified against /v1/models at first use;
    # if it isn't listed, llm.py picks the first available entry of nebius_fallback_models.
    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    # DECISION (measured 2026-11-14 on Token Factory): zai-org/GLM-5.3-Flash is available but is a
    # reasoning model: 8.6 s per suggestion call even at reasoning_effort=low (40 s+ under
    # concurrency, empty content at defaults). Qwen3-30B-A3B-Instruct-2507 returned valid JSON in
    # 0.85-1.3 s, so it drives the hot path; GLM-5.3-Flash handles latency-tolerant summaries.
    nebius_model: str = "Qwen/Qwen3-30B-A3B-Instruct-2507"     # hot path: reply suggestions
    nebius_summary_model: str = "zai-org/GLM-5.3-Flash"        # Lane D episode summaries
    nebius_fallback_models: str = (
        "MiniMaxAI/MiniMax-M3.1-Flash,deepseek-ai/DeepSeek-V4.1-Flash-1017,"
        "Qwen/Qwen3-235B-A22B-Instruct-2507,openai/gpt-oss-120b,zai-org/GLM-5.3-Flash"
    )
    # Models that think before answering: we send reasoning_effort=low and a bigger token budget.
    nebius_reasoning_models: str = "zai-org/GLM,openai/gpt-oss,deepseek-ai/DeepSeek-V4-Pro,moonshotai/Kimi"
    # DECISION: 10 s caps a stalled hot-path call; instant suggestions are already on screen and
    # the client SDK retries once, so the worst case stays well under a conversational pause x2.
    llm_timeout_s: float = 10.0                # hot path (suggestions)
    llm_summary_timeout_s: float = 90.0        # summaries / non-hot-path calls
    # Hedged hot path (see llm._hedged). Empty model = off.
    llm_hedge_model: str = ""
    llm_hedge_after_s: float = 3.5
    openai_api_key: str = ""

    # Embeddings (Voyage AI, a MongoDB company)
    voyage_api_key: str = ""
    embed_model: str = "voyage-4-lite"
    embed_dim: int = 1024

    # Voice (ElevenLabs + SpeechBrain)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    stt_model: str = "scribe_v2"
    tts_model: str = "eleven_flash_v2_5"
    voice_embed_dim: int = 192
    speaker_threshold: float = 0.80            # Atlas cosine score (1+cos)/2; tune with voice_calibrate.py

    # Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "second-voice"

    # Mocks (1 = on)
    mock_llm: bool = False
    mock_embed: bool = False
    mock_stt: bool = False
    mock_speaker: bool = False
    mock_tts: bool = False

    # App
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Destructive demo reset (deletes the demo user's learned rules/phrases/episodes and demo
    # sessions/events). OFF by default. Executing it needs ENABLE_DEMO_RESET=true AND, over HTTP,
    # an X-Admin-Token header equal to ADMIN_TOKEN (non-empty). Dry runs are always read-only.
    enable_demo_reset: bool = False
    admin_token: str = ""
    # Debug only: log the full suggestion prompt (contains private memories; never enable on a
    # shared machine). Used to verify that blocked context is withheld from the model.
    log_prompts: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
