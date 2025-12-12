from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse as FastAPIJSONResponse
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .jobs import build_research_service_from_env
from .models import EventListResponse, JobCreateResponse, ResearchRequest


RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RESEARCH_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX = int(os.getenv("RESEARCH_RATE_LIMIT_MAX", "60"))
_request_counts: dict[str, tuple[float, int]] = {}


def create_app() -> FastAPI:
    service = build_research_service_from_env()
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    app = FastAPI(
        title="Multi-Agent Research System",
        version="0.1.0",
        description="LangGraph research workflow with retries, async jobs, cache, and traceable run events.",
    )
    app.state.research_service = service

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path not in {"/", "/favicon.ico"} and _is_rate_limited(request):
            return FastAPIJSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, object]:
        provider = os.getenv("RESEARCH_PROVIDER", "fixture").lower()
        cache_backend = os.getenv("RESEARCH_CACHE_BACKEND", "memory").lower()
        job_backend = os.getenv("RESEARCH_JOB_BACKEND", "memory").lower()
        return {
            "status": "ok",
            "provider": provider,
            "cache_backend": cache_backend,
            "job_backend": job_backend,
            "offline_default": provider == "fixture" and cache_backend == "memory" and job_backend == "memory",
        }

    @app.post("/research/run-sync")
    def run_sync(request: ResearchRequest):
        brief, events, cache_hit = service.run_sync(request)
        return {"result": brief, "events": events, "cache_hit": cache_hit}

    @app.post("/research/jobs", response_model=JobCreateResponse)
    def create_job(request: ResearchRequest, background_tasks: BackgroundTasks):
        job = service.create_job(request)
        background_tasks.add_task(service.run_job, job.job_id)
        return JobCreateResponse(job_id=job.job_id, status=job.status)

    @app.get("/research/jobs/{job_id}")
    def get_job(job_id: str):
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/research/jobs/{job_id}/events", response_model=EventListResponse)
    def get_job_events(job_id: str):
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return EventListResponse(job_id=job_id, events=job.events)

    if (frontend_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index():
        index = frontend_dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            {
                "app": "SignalBrief Desk",
                "detail": "Frontend build not found. Run npm.cmd install and npm.cmd run build in frontend/.",
                "docs": "/docs",
            }
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    return app


app = create_app()


def _is_rate_limited(request: Request) -> bool:
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window_start, count = _request_counts.get(client, (now, 0))
    if now - window_start >= RATE_LIMIT_WINDOW_SECONDS:
        _request_counts[client] = (now, 1)
        return False
    count += 1
    _request_counts[client] = (window_start, count)
    return count > RATE_LIMIT_MAX
