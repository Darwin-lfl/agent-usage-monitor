from __future__ import annotations

import socket
import threading
import webbrowser
from functools import partial
from importlib import resources
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import __version__
from .analytics import GRANULARITIES
from .models import Agent
from .output import AGENT_LABELS
from .service import RANGES, MeasurementRequest, MeasurementService


def create_app(
    *,
    service: MeasurementService | None = None,
    custom_paths: dict[Agent, list[Path]] | None = None,
    include_estimates: bool = True,
    static_dir: Path | None = None,
) -> FastAPI:
    measurement_service = service or MeasurementService()
    data_paths = custom_paths or {}
    app = FastAPI(
        title="Agent Usage Monitor",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def local_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/v1/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__, "scope": "localhost"}

    @app.get("/api/v1/options")
    async def options(
        agent: Annotated[list[str] | None, Query()] = None,
        range_name: Annotated[str, Query(alias="range")] = "7d",
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        _validate_range(range_name, start)
        agents = _parse_agents(agent)
        request = MeasurementRequest(
            agents=agents,
            range_name=range_name,
            start=start,
            end=end,
            custom_paths=data_paths,
            include_estimates=include_estimates,
        )
        _, snapshot = await run_in_threadpool(
            partial(measurement_service.measure, request, max_age=2)
        )
        return {
            "agents": [
                {"value": item.value, "label": AGENT_LABELS[item.value]} for item in Agent
            ],
            "ranges": list(RANGES),
            "granularities": list(GRANULARITIES),
            "models": sorted({row["model"] for row in snapshot["models"]}),
        }

    @app.get("/api/v1/snapshot")
    async def snapshot(
        agent: Annotated[list[str] | None, Query()] = None,
        model: Annotated[list[str] | None, Query()] = None,
        range_name: Annotated[str, Query(alias="range")] = "7d",
        start: str | None = None,
        end: str | None = None,
        granularity: str = "day",
        exact_only: bool = False,
        refresh: bool = False,
    ) -> dict:
        _validate_range(range_name, start)
        if granularity not in GRANULARITIES:
            raise HTTPException(status_code=400, detail="unsupported granularity")
        request = MeasurementRequest(
            agents=_parse_agents(agent),
            models=model or [],
            range_name=range_name,
            start=start,
            end=end,
            granularity=granularity,
            custom_paths=data_paths,
            include_estimates=include_estimates and not exact_only,
        )
        _, result = await run_in_threadpool(
            partial(measurement_service.measure, request, max_age=0 if refresh else 2)
        )
        return result

    assets = static_dir or _packaged_static_dir()
    if assets.is_dir():
        app.mount("/", StaticFiles(directory=assets, html=True), name="web")
    else:
        @app.get("/")
        async def missing_frontend() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={"detail": "Web assets are missing; rebuild the frontend."},
            )
    return app


def run_web(
    *,
    port: int = 8765,
    open_browser: bool = True,
    custom_paths: dict[Agent, list[Path]] | None = None,
    include_estimates: bool = True,
) -> None:
    import uvicorn

    selected_port = _available_port(port)
    url = f"http://127.0.0.1:{selected_port}"
    app = create_app(custom_paths=custom_paths, include_estimates=include_estimates)
    print(f"Agent Usage Monitor: {url}")
    print("Press Ctrl+C to stop the local server.")
    if open_browser:
        timer = threading.Timer(0.7, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=selected_port,
        log_level="warning",
        lifespan="off",
    )


def _parse_agents(values: list[str] | None) -> list[Agent]:
    if not values:
        return list(Agent)
    try:
        return list(dict.fromkeys(Agent(value.lower()) for value in values))
    except ValueError as exc:
        raise ValueError(f"unknown agent: {exc.args[0]}") from exc


def _validate_range(range_name: str, start: str | None) -> None:
    if range_name not in RANGES:
        raise ValueError(f"unsupported time range: {range_name}")
    if range_name == "custom" and not start:
        raise ValueError("custom range requires a start date")


def _available_port(preferred: int) -> int:
    if preferred == 0:
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            return int(candidate.getsockname()[1])
    for candidate_port in range(preferred, min(preferred + 25, 65536)):
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", candidate_port))
            except OSError:
                continue
            return candidate_port
    raise RuntimeError(f"no available local port found from {preferred}")


def _packaged_static_dir() -> Path:
    return Path(str(resources.files("agent_usage_monitor").joinpath("web_dist")))
