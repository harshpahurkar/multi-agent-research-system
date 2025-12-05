from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, NotRequired, Required, TypedDict

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchRequest(BaseModel):
    company: str = Field(min_length=2)
    focus: str = Field(default="company strategy, product, risks", min_length=3)
    max_retries: int = Field(default=2, ge=0, le=5)


class PlanStep(BaseModel):
    id: str
    query: str
    purpose: str


class Evidence(BaseModel):
    title: str
    source: str
    company: str
    text: str
    topics: list[str] = Field(default_factory=list)
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)


class RunEvent(BaseModel):
    node: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class ResearchBrief(BaseModel):
    company: str
    focus: str
    summary: str
    findings: list[str]
    risks: list[str]
    sources: list[str]
    warnings: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    retry_count: int = 0
    events: list[RunEvent] = Field(default_factory=list)


class ResearchState(TypedDict):
    job_id: Required[str]
    company: Required[str]
    focus: Required[str]
    max_retries: Required[int]
    retry_count: Required[int]
    warnings: Required[list[str]]
    events: Required[list[dict[str, Any]]]
    should_retry: Required[bool]
    status: Required[str]
    plan: NotRequired[list[dict[str, str]]]
    evidence: NotRequired[list[dict[str, Any]]]
    quality_score: NotRequired[float]
    draft: NotRequired[dict[str, Any]]
    final: NotRequired[dict[str, Any]]


class JobRecord(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    request: ResearchRequest
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    result: ResearchBrief | None = None
    events: list[RunEvent] = Field(default_factory=list)
    error: str | None = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class EventListResponse(BaseModel):
    job_id: str
    events: list[RunEvent]
