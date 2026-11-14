"""Lane D: learning and evaluation read/action routes."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app import db
from app.config import settings
from app.contracts import Boundary, PersonContext, Scoreboard, ConfigMetrics
from app.learning.demo_seed import reset_demo
from app.learning.memory import retrieve_person_context

router = APIRouter(prefix="/api", tags=["learning"])

@router.get("/boundaries", response_model=list[Boundary])
async def list_boundaries():
    records = await db.db()[db.BOUNDARIES].find({"user_id": settings.demo_user_id}).sort("created_at", -1).to_list(500)
    return [Boundary.model_validate(record) for record in records]


@router.post("/boundaries/{boundary_id}/confirm", response_model=Boundary)
async def confirm_boundary(boundary_id: str):
    return await _set_boundary_status(boundary_id, "active")


@router.post("/boundaries/{boundary_id}/dismiss", response_model=Boundary)
async def dismiss_boundary(boundary_id: str):
    return await _set_boundary_status(boundary_id, "dismissed")


async def _set_boundary_status(boundary_id: str, status: str) -> Boundary:
    collection = db.db()[db.BOUNDARIES]
    record = await collection.find_one({"_id": boundary_id, "user_id": settings.demo_user_id})
    if not record:
        raise HTTPException(404, "boundary not found")
    now = datetime.now(timezone.utc)
    changes = {"status": status}
    if status == "active":
        changes["activated_at"] = now
    await collection.update_one({"_id": boundary_id, "user_id": settings.demo_user_id}, {"$set": changes})
    record.update(changes)
    return Boundary.model_validate(record)


@router.get("/people/{person_id}/context", response_model=PersonContext)
async def person_context(person_id: str):
    people = await db.db()[db.PEOPLE].find_one({"_id": person_id, "user_id": settings.demo_user_id})
    if not people:
        raise HTTPException(404, "person not found")
    context = await retrieve_person_context(settings.demo_user_id, person_id, people["relationship"])
    if context.person is None:
        raise HTTPException(404, "person not found")
    return PersonContext(
        person=context.person,
        last_episode=context.recent_episodes[0] if context.recent_episodes else None,
        open_threads=context.open_threads,
        top_phrases=[memory.text for memory in context.phrases[:8]],
    )


@router.get("/eval/scoreboard", response_model=Scoreboard)
async def eval_scoreboard():
    records = await db.db()[db.EVAL_RUNS].find({"user_id": settings.demo_user_id}).sort("created_at", -1).to_list(100)
    latest: dict[str, dict] = {}
    for record in records:
        config = record.get("config")
        if config in {"cold", "warm"} and config not in latest:
            latest[config] = record
    def metrics(config: str) -> ConfigMetrics | None:
        record = latest.get(config)
        if not record:
            return None
        data = record.get("metrics", {})
        try:
            return ConfigMetrics.model_validate(data)
        except Exception as error:
            raise HTTPException(500, f"stored {config} eval metrics are invalid") from error
    return Scoreboard(
        cold=metrics("cold"), warm=metrics("warm"),
        notes=("MOCK scores: deterministic canned LLM and mock embeddings." if any(
            record.get("label") == "MOCK" for record in latest.values()
        ) else "REAL scores: persisted Lane A model and embedding measurements."),
        updated_at=max((record.get("created_at", datetime.now(timezone.utc)) for record in latest.values()), default=datetime.now(timezone.utc)),
    )


@router.post("/admin/reset-demo")
async def admin_reset_demo(dry_run: bool = Query(False, description="preview counts without writing")):
    """Delete the demo user's lane-d learned docs + demo sessions/events, then re-seed (idempotent)."""
    return await reset_demo(db.db(), dry_run=dry_run)
