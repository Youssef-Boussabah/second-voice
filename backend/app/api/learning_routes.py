"""Lane D: learning + eval REST routes. See docs/04-api-contracts.md §1 (Lane D)."""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["learning"])

# TODO(Lane D): GET /boundaries, POST /boundaries/{id}/confirm, POST /boundaries/{id}/dismiss,
# GET /people/{id}/context, GET /eval/scoreboard, POST /admin/reset-demo
