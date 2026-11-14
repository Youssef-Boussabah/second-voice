"""Lane A: LLM wrapper. STABLE SIGNATURE (Lane D uses it)."""
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def complete_json(system: str, user: str, schema: type[T], *, model: str | None = None) -> T:
    """Return an instance of `schema`. Honour settings.mock_llm.
    TODO(Lane A): Anthropic/OpenAI by settings.llm_provider; validate; retry once."""
    raise NotImplementedError
