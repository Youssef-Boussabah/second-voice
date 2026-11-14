"""Lane A: LangGraph suggestion pipeline. See docs/02-architecture.md.

STABLE SIGNATURE (Lane B calls this):
    async def on_partner_utterance(utt: Utterance) -> None
"""
import logging

from app.contracts import Utterance

log = logging.getLogger(__name__)


async def on_partner_utterance(utt: Utterance) -> None:
    """Run instant + final stages and publish SuggestionSets. Must never raise."""
    log.info("STUB on_partner_utterance(%s): %r", utt.id, utt.text)
    # TODO(Lane A): identify_context → instant_suggest → retrieve → generate → guard → publish
