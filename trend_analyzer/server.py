"""FastAPI app: JSON API + optional built SPA (after `npm run build`)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from trend_analyzer.api_routes import router as api_router
from trend_analyzer.scheduling_daemon import SchedulerDaemon

UI_DIST = Path(__file__).resolve().parent / "ui_dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    daemon = SchedulerDaemon(reload_interval_sec=60.0)
    daemon.start()
    app.state.scheduler = daemon
    yield
    daemon.shutdown()


def create_app() -> FastAPI:
    application = FastAPI(
        lifespan=lifespan,
        title="Trend Analyzer",
        description="Local trend research scheduler and business context",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)

    index_html = UI_DIST / "index.html"
    dist_root = UI_DIST.resolve()
    if index_html.is_file():
        assets = UI_DIST / "assets"
        if assets.is_dir():
            application.mount(
                "/assets",
                StaticFiles(directory=str(assets)),
                name="ui-assets",
            )

        @application.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            cand = (UI_DIST / full_path).resolve()
            if not cand.is_relative_to(dist_root):
                return FileResponse(index_html)
            if cand.is_file():
                return FileResponse(cand)
            return FileResponse(index_html)

    return application


app = create_app()
