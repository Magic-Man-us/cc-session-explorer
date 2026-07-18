"""The cc-session-explorer server: the SPA plus both API lenses in one FastAPI app.

Routes: ``/`` and every client-side route the SPA owns (``/context/sessions/…`` etc.) serve
the same built single-file dashboard, so a deep link survives a hard refresh; ``/api/*`` is
the cost/usage lens and ``/timeline/*`` the context-token lens. `ExplorerSettings` is stashed
on ``app.state`` at construction — the one thing the routers' dependencies require.

Run by hand, the server holds the port until killed. Run under systemd socket activation it
inherits the already-listening socket and exits once idle: the manager keeps the port open,
so the next request starts a fresh process and the caller never sees a refusal.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import BaseHTTPMiddleware

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.api import router as timeline_router
from cc_session_explorer.base import FrozenModel
from cc_session_explorer.usage import router as usage_router

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import uvicorn
    from fastapi import Request, Response

    from cc_session_explorer.types import IdleSeconds

logger = logging.getLogger(__name__)

_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9821  # the SPA's vite dev proxy targets this port

_SYSTEMD_FIRST_FD = 3  # sd_listen_fds(3): inherited sockets arrive as fds from here up
_IDLE_POLL_SECONDS = 15.0


class SystemdActivation(BaseSettings):
    """The socket-activation handoff systemd advertises in the environment.

    Checking ``pid`` is what makes the fd safe to claim: these variables are inherited by
    every child we spawn, and only the process systemd addressed them to owns the socket.
    """

    model_config = SettingsConfigDict(env_prefix="LISTEN_")

    pid: int | None = None
    fds: int = 0

    @property
    def fd(self) -> int | None:
        """The inherited listening socket, or ``None`` when we were not socket-activated."""
        if self.fds >= 1 and self.pid == os.getpid():
            return _SYSTEMD_FIRST_FD
        return None


class HealthStatus(FrozenModel):
    """Liveness only — the process is up and answering HTTP. No DB/disk touched,
    so a poller (the plugin's dashboard-uptime monitor, a load balancer, ...)
    can hit this cheaply and often."""

    status: Literal["ok"] = "ok"


class _IdleClock:
    """When the last request landed — written by the middleware, read by the watchdog."""

    def __init__(self) -> None:
        self.last_request = time.monotonic()


def create_app(settings: ExplorerSettings | None = None) -> FastAPI:
    """Build the app: settings on state, both routers, and the SPA at the root."""
    app = FastAPI(title="cc-session-explorer")
    resolved = settings if settings is not None else ExplorerSettings()
    app.state.explorer_settings = resolved

    app.include_router(usage_router, prefix="/api")
    app.include_router(timeline_router)

    def health() -> HealthStatus:
        return HealthStatus()

    app.add_api_route("/healthz", health, response_model=HealthStatus, include_in_schema=False)

    def index() -> HTMLResponse:
        return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))

    app.add_api_route("/", index, response_class=HTMLResponse, include_in_schema=False)

    def spa_fallback(full_path: str) -> HTMLResponse:
        """Any client-side route (``/context/sessions/<id>``, …) gets the same SPA shell, so
        a deep link or hard refresh doesn't 404 — the app's own router takes it from there."""
        if full_path.startswith(("api/", "timeline/", "healthz")):
            raise HTTPException(status_code=404)
        return HTMLResponse(_STATIC_INDEX.read_text(encoding="utf-8"))

    app.add_api_route(
        "/{full_path:path}", spa_fallback, response_class=HTMLResponse, include_in_schema=False
    )
    return app


def _serve_until_idle(app: FastAPI, config: uvicorn.Config, idle_exit: IdleSeconds) -> None:
    """Serve until ``idle_exit`` seconds pass with no request, then shut down cleanly."""
    import uvicorn

    clock = _IdleClock()
    server = uvicorn.Server(config)

    async def touch(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        clock.last_request = time.monotonic()
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=touch)

    async def watchdog() -> None:
        while not server.should_exit:
            await asyncio.sleep(_IDLE_POLL_SECONDS)
            if time.monotonic() - clock.last_request >= idle_exit:
                logger.info("idle %.0fs — exiting; the next request starts us again", idle_exit)
                server.should_exit = True

    async def run() -> None:
        watching = asyncio.create_task(watchdog())
        try:
            await server.serve()
        finally:
            watching.cancel()

    asyncio.run(run())


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Serve the cc-session-explorer dashboard.")
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = parser.parse_args()

    settings = ExplorerSettings()
    app = create_app(settings)

    fd = SystemdActivation().fd
    if fd is None:
        uvicorn.run(app, host=args.host, port=args.port)
        return

    _serve_until_idle(app, uvicorn.Config(app, fd=fd), settings.idle_exit_seconds)
