"""The FastAPI application: API routes, live events, the built UI, and the worker in one process."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gmail_operations_agent import __version__
from gmail_operations_agent.api.events import EventHub
from gmail_operations_agent.api.routes import router
from gmail_operations_agent.api.security import BodySizeLimit, SecurityHeaders
from gmail_operations_agent.runtime import Runtime

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024


def create_app(runtime: Runtime, run_worker: bool = True) -> FastAPI:
    """`run_worker=False` leaves processing to the caller (tests drive the worker by hand)."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []
        if run_worker:
            tasks.append(asyncio.create_task(runtime.worker.run(stop), name="worker"))
            if runtime.demo:
                tasks.append(asyncio.create_task(runtime.demo.run_cleanup(stop), name="cleanup"))
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(
        title="Gmail Operations Agent",
        version=__version__,
        lifespan=lifespan,
        redoc_url=None,
    )
    app.state.runtime = runtime
    app.state.hub = EventHub(runtime.store)
    app.include_router(router)
    _mount_frontend(app, runtime.settings.web_dist_dir)
    # The last one added runs first: headers are added even to rejected bodies.
    app.add_middleware(BodySizeLimit, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(SecurityHeaders)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app, if there is one (phase 5 builds it)."""
    index = dist / "index.html"
    if not index.is_file():
        logger.info("No built UI in %s; serving the API only", dist)
        return
    root = dist.resolve()
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)  # client-side routes
