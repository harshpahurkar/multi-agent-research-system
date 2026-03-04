from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Protocol

from .cache import Cache, InMemoryCache, RedisCache
from .models import JobRecord, ResearchBrief, ResearchRequest, RunEvent, utc_now
from .providers import OpenAICompatibleWebResearchProvider, OpenAIResponsesProvider
from .workflow import ResearchWorkflow


class JobStore(Protocol):
    def create(self, request: ResearchRequest) -> JobRecord:
        ...

    def update(self, job: JobRecord) -> None:
        ...

    def get(self, job_id: str) -> JobRecord | None:
        ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, JobRecord] = {}

    def create(self, request: ResearchRequest) -> JobRecord:
        job = JobRecord(job_id=str(uuid.uuid4()), status="queued", request=request)
        self.jobs[job.job_id] = job
        return job

    def update(self, job: JobRecord) -> None:
        job.updated_at = utc_now()
        self.jobs[job.job_id] = job

    def get(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)


class RedisJobStore:
    def __init__(self, url: str | None = None, prefix: str = "research:job") -> None:
        try:
            import redis  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install the 'redis' extra to use RedisJobStore.") from exc
        redis_url = url or os.getenv("REDIS_URL")
        if not redis_url:
            raise RuntimeError("REDIS_URL is required when Redis job backend is enabled.")
        self.client = redis.Redis.from_url(redis_url)
        self.prefix = prefix

    def create(self, request: ResearchRequest) -> JobRecord:
        job = JobRecord(job_id=str(uuid.uuid4()), status="queued", request=request)
        self.update(job)
        return job

    def update(self, job: JobRecord) -> None:
        job.updated_at = utc_now()
        self.client.set(self._key(job.job_id), job.model_dump_json(), ex=86400)

    def get(self, job_id: str) -> JobRecord | None:
        raw = self.client.get(self._key(job_id))
        if not raw:
            return None
        payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return JobRecord.model_validate_json(payload)

    def _key(self, job_id: str) -> str:
        return f"{self.prefix}:{job_id}"


class ResearchService:
    def __init__(
        self,
        workflow: ResearchWorkflow | None = None,
        store: JobStore | None = None,
        cache: Cache | None = None,
    ) -> None:
        self.workflow = workflow or ResearchWorkflow()
        self.store = store or InMemoryJobStore()
        self.cache = cache or InMemoryCache()

    def run_sync(self, request: ResearchRequest, *, job_id: str = "sync") -> tuple[ResearchBrief, list[RunEvent], bool]:
        key = self.cache_key(request)
        cached = self.cache.get(key)
        if cached:
            event = RunEvent(node="cache", event="hit", payload={"key": key})
            return cached, [event, *cached.events], True
        brief = self.workflow.run(request, job_id=job_id)
        self.cache.set(key, brief)
        events = [RunEvent(node="cache", event="miss", payload={"key": key}), *brief.events]
        return brief, events, False

    def create_job(self, request: ResearchRequest) -> JobRecord:
        return self.store.create(request)

    def run_job(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        job.status = "running"
        self.store.update(job)
        try:
            brief, cache_events, _ = self.run_sync(job.request, job_id=job_id)
            job.status = "completed"
            job.result = brief
            job.events.extend(cache_events)
        except Exception as exc:
            job.status = "failed"
            job.error = safe_error_message(exc)
        self.store.update(job)

    def get_job(self, job_id: str) -> JobRecord | None:
        return self.store.get(job_id)

    @staticmethod
    def cache_key(request: ResearchRequest) -> str:
        provider = os.getenv("RESEARCH_PROVIDER", "fixture").lower()
        model = os.getenv("OPENAI_RESEARCH_MODEL") or default_model_for_provider(provider)
        raw = json.dumps(
            {
                "company": request.company.strip().lower(),
                "focus": request.focus.strip().lower(),
                "max_retries": request.max_retries,
                "provider": provider,
                "model": model,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_error_message(error: Exception) -> str:
    return f"{error.__class__.__name__}: workflow failed"


def default_model_for_provider(provider: str) -> str:
    if provider == "openai_responses":
        return "gpt-4.1"
    if provider in {"openai", "web"}:
        return "gpt-4.1"
    return "fixture"


def build_research_service_from_env() -> ResearchService:
    provider_name = os.getenv("RESEARCH_PROVIDER", "fixture").lower()
    if provider_name == "openai_responses":
        workflow = ResearchWorkflow(
            provider=OpenAIResponsesProvider(model=os.getenv("OPENAI_RESEARCH_MODEL", default_model_for_provider(provider_name)))
        )
    elif provider_name in {"openai", "web"}:
        workflow = ResearchWorkflow(
            provider=OpenAICompatibleWebResearchProvider(model=os.getenv("OPENAI_RESEARCH_MODEL", default_model_for_provider(provider_name)))
        )
    else:
        workflow = ResearchWorkflow()

    cache_name = os.getenv("RESEARCH_CACHE_BACKEND", "memory").lower()
    cache: Cache = RedisCache() if cache_name == "redis" else InMemoryCache()
    store_name = os.getenv("RESEARCH_JOB_BACKEND", "memory").lower()
    store: JobStore = RedisJobStore() if store_name == "redis" else InMemoryJobStore()
    return ResearchService(workflow=workflow, store=store, cache=cache)
