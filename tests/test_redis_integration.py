from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from research_system.api import create_app


@pytest.mark.integration
def test_redis_cache_and_job_store_through_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        pytest.skip("REDIS_URL is required for Redis integration tests.")

    monkeypatch.setenv("RESEARCH_CACHE_BACKEND", "redis")
    monkeypatch.setenv("RESEARCH_JOB_BACKEND", "redis")
    client = TestClient(create_app())

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["cache_backend"] == "redis"
    assert health.json()["job_backend"] == "redis"

    unique = uuid.uuid4().hex[:8]
    payload = {
        "company": f"RedisCo {unique}",
        "focus": "analytics platform risks",
        "max_retries": 1,
    }
    first = client.post("/research/run-sync", json=payload)
    second = client.post("/research/run-sync", json=payload)

    assert first.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.status_code == 200
    assert second.json()["cache_hit"] is True
    assert second.json()["events"][0]["node"] == "cache"

    created = client.post(
        "/research/jobs",
        json={
            "company": f"RedisJob {unique}",
            "focus": "survey customer feedback AI insights",
            "max_retries": 1,
        },
    )
    assert created.status_code == 200

    job_id = created.json()["job_id"]
    job = client.get(f"/research/jobs/{job_id}")
    assert job.status_code == 200
    body = job.json()
    assert body["status"] == "completed"
    assert body["result"]["company"] == f"RedisJob {unique}"
    assert any(event["node"] == "evaluator" for event in body["events"])

    events = client.get(f"/research/jobs/{job_id}/events")
    assert events.status_code == 200
    assert any(event["event"] in {"miss", "hit"} for event in events.json()["events"])
