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
    nebius_model: str = "zai-org/GLM-5.3-Flash"
    nebius_summary_model: str = ""             # empty → same as nebius_model
    nebius_fallback_models: str = (
        "zai-org/GLM-4.5-Air,Qwen/Qwen3-30B-A3B-Instruct-2507,meta-llama/Llama-3.3-70B-Instruct,"
        "openai/gpt-oss-20b,Qwen/Qwen3-235B-A22B-Instruct-2507,deepseek-ai/DeepSeek-V3-0324"
    )
    llm_timeout_s: float = 20.0
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
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
