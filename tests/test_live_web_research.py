from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from research_system.api import create_app


@pytest.mark.integration
def test_live_web_research_with_redis_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("RUN_LIVE_STACK") != "1":
        pytest.skip("RUN_LIVE_STACK=1 is required for live web research tests.")
    if not os.getenv("REDIS_URL"):
        pytest.fail("REDIS_URL is required for live web research tests.")
    if not os.getenv("OPENAI_BASE_URL") and not os.getenv("OPENAI_API_KEY"):
        pytest.fail("OPENAI_BASE_URL or OPENAI_API_KEY is required for live web research tests.")

    monkeypatch.setenv("RESEARCH_PROVIDER", "openai")
    monkeypatch.setenv("RESEARCH_CACHE_BACKEND", "redis")
    monkeypatch.setenv("RESEARCH_JOB_BACKEND", "redis")
    monkeypatch.setenv("OPENAI_RESEARCH_MODEL", os.getenv("OPENAI_RESEARCH_MODEL", "gpt-4.1"))

    client = TestClient(create_app())
    unique = uuid.uuid4().hex[:8]
    payload = {
        "company": f"SurveyMonkey {unique}",
        "focus": "survey customer feedback AI insights",
        "max_retries": 1,
    }

    first = client.post("/research/run-sync", json=payload)
    second = client.post("/research/run-sync", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert first.json()["result"]["sources"]
    assert any(source.startswith("http") for source in first.json()["result"]["sources"])
    assert any(event["node"] == "researcher" for event in first.json()["events"])
    assert any(event["node"] == "planner" and event["payload"].get("source") == "provider" for event in first.json()["events"])
    assert any(event["node"] == "writer" and event["payload"].get("source") == "provider" for event in first.json()["events"])
    assert any(event["event"] == "node_input" and event["node"] == "planner" for event in first.json()["events"])
    assert any(event["event"] == "node_output" and event["node"] == "writer" for event in first.json()["events"])

    created = client.post("/research/jobs", json=payload)
    assert created.status_code == 200
    job = client.get(f"/research/jobs/{created.json()['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "completed"
    assert job.json()["result"]["findings"]
