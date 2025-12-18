from __future__ import annotations

import time

from fastapi.testclient import TestClient

from research_system.api import create_app


def test_sync_endpoint_returns_brief_and_cache_status() -> None:
    client = TestClient(create_app())
    payload = {"company": "SurveyMonkey", "focus": "survey customer feedback AI insights"}
    first = client.post("/research/run-sync", json=payload)
    assert first.status_code == 200
    assert first.json()["cache_hit"] is False
    assert first.json()["result"]["sources"]

    second = client.post("/research/run-sync", json=payload)
    assert second.status_code == 200
    assert second.json()["cache_hit"] is True


def test_async_job_lifecycle_and_events() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/research/jobs",
        json={"company": "Acme Analytics", "focus": "analytics platform risks"},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    body = None
    for _ in range(20):
        job = client.get(f"/research/jobs/{job_id}")
        assert job.status_code == 200
        body = job.json()
        if body["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert body is not None
    assert body["status"] == "completed"
    assert body["result"]["company"] == "Acme Analytics"

    events = client.get(f"/research/jobs/{job_id}/events")
    assert events.status_code == 200
    assert any(event["event"] in {"miss", "hit"} for event in events.json()["events"])
    assert any(event["node"] == "evaluator" for event in events.json()["events"])


def test_validation_rejects_tiny_company() -> None:
    client = TestClient(create_app())
    response = client.post("/research/run-sync", json={"company": "A", "focus": "AI"})
    assert response.status_code == 422
