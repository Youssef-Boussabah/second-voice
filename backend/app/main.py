"""FastAPI entry point. SHARED + FROZEN: every lane's router is pre-wired here.

Lanes implement their routers in app/api/*_routes.py and their startup hooks in
their own packages; nobody needs to edit this file.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api import core_routes, learning_routes, voice_routes
from app.config import settings
from app.realtime import hub, ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.startup()            # Lane A: start change-stream tails
    await voice_routes.startup()   # Lane B: warm speaker model
    yield
    await hub.shutdown()
    await db.close()


app = FastAPI(title="Second Voice", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core_routes.router)       # Lane A
app.include_router(voice_routes.router)      # Lane B
app.include_router(learning_routes.router)   # Lane D
app.include_router(ws.router)                # Lane A
