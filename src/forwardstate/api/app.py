"""FastAPI application factory and the module-level ``app`` (``forwardstate serve``).

Importing this module never builds services: they are built on the first request that needs
them, so a missing engine shows up as a clear 503, not an import crash.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from forwardstate import __version__
from forwardstate.contracts import DECISION_BOUNDARY

from . import routes_admin, routes_compute, routes_data
from .container import Services
from .context import AppContext
from .errors import install_error_handlers

CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(
    services: Services | None = None,
    state_dir: Path = Path("data/state"),
    *,
    config_dir: Path | None = None,
    data_dir: Path = Path("data"),
    services_factory: Callable[[], Services] | None = None,
    web_dist: Path | None = None,
) -> FastAPI:
    """Build the API. Pass ``services`` (tests) or let it build the real ones lazily."""
    app = FastAPI(
        title="ForwardState API",
        version=__version__,
        description=DECISION_BOUNDARY,
    )
    app.state.ctx = AppContext(
        services,
        state_dir=Path(state_dir),
        config_dir=config_dir,
        data_dir=Path(data_dir),
        services_factory=services_factory,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
        expose_headers=["X-Run-Id"],
    )
    install_error_handlers(app)
    for r in (routes_admin.router, routes_data.router, routes_compute.router):
        app.include_router(r)
    mount_web_ui(app, web_dist or WEB_DIST)
    return app


WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def mount_web_ui(app: FastAPI, dist: Path) -> None:
    """Serve the built React app (``npm run build``) from the same origin, if it exists.

    Any non-API GET falls back to ``index.html`` so client-side routes like /portfolio work.
    API routes are registered first and always win.
    """
    index = dist / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def _spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
