"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from banking_agent.api.routes import router
from banking_agent.database import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Agentic Banking Support",
    description="A tool-using personal banking support assistant.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)