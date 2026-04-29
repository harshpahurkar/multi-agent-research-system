from __future__ import annotations

import json
from pathlib import Path

from research_system.jobs import ResearchService, default_model_for_provider
from research_system.models import ResearchRequest
from research_system.providers import OpenAIResponsesProvider
from research_system.workflow import ResearchWorkflow


def test_fixture_corpus_file_is_committed_for_offline_default() -> None:
    corpus = Path("data/fixtures/research_corpus.json")
    assert corpus.exists()
    records = json.loads(corpus.read_text(encoding="utf-8"))
    assert len(records) >= 10
    assert {"SurveyMonkey", "Shopify", "Acme Analytics"} <= {record["company"] for record in records}


def test_workflow_completes_with_relevant_evidence() -> None:
    workflow = ResearchWorkflow()
    brief = workflow.run(
        ResearchRequest(company="SurveyMonkey", focus="survey customer feedback AI insights"),
        job_id="test",
    )
    assert brief.company == "SurveyMonkey"
    assert brief.quality_score >= 0.7
    assert brief.sources
    assert any("survey" in finding.lower() for finding in brief.findings)
    assert any(event.node == "planner" and event.event == "node_input" for event in brief.events)
    assert any(event.node == "researcher" and event.event == "node_output" for event in brief.events)
    assert any(event.node == "writer" and "draft" in event.payload.get("output", {}) for event in brief.events)


def test_fixture_corpus_supports_multiple_demo_companies() -> None:
    workflow = ResearchWorkflow()
    brief = workflow.run(
        ResearchRequest(company="Shopify", focus="commerce platform payments merchant risks"),
        job_id="fixture-breadth",
    )
    assert brief.company == "Shopify"
    assert brief.quality_score >= 0.7
    assert len(brief.sources) >= 3
    assert any("commerce" in finding.lower() for finding in brief.findings)


def test_workflow_retries_and_returns_partial_brief_for_unknown_company() -> None:
    workflow = ResearchWorkflow()
    brief = workflow.run(
        ResearchRequest(company="UnknownCo", focus="enterprise analytics roadmap", max_retries=2),
        job_id="retry",
    )
    assert brief.retry_count >= 1
    assert brief.quality_score < 0.7
    assert brief.warnings
    assert brief.sources == ["fixture://fallback"]


def test_provider_search_failure_returns_partial_brief_with_events() -> None:
    class BrokenProvider:
        diagnostics: list[dict] = []

        def search(self, *, company: str, focus: str, query: str, retry_count: int):
            raise RuntimeError(f"search failed for {query}")

    workflow = ResearchWorkflow(provider=BrokenProvider())
    brief = workflow.run(
        ResearchRequest(company="BrokenCo", focus="research resilience", max_retries=1),
        job_id="broken-provider",
    )

    assert brief.company == "BrokenCo"
    assert brief.quality_score < 0.7
    assert brief.warnings
    assert any(event.node == "researcher" and event.event == "tool_call_failed" for event in brief.events)
    assert any("partial" in finding.lower() for finding in brief.findings)


def test_researcher_falls_back_when_state_has_no_plan() -> None:
    workflow = ResearchWorkflow()
    output = workflow._researcher_node(
        {
            "job_id": "misrouted",
            "company": "SurveyMonkey",
            "focus": "survey customer feedback AI insights",
            "max_retries": 1,
            "retry_count": 0,
            "warnings": [],
            "events": [],
            "should_retry": False,
            "status": "running",
        }
    )

    assert output["evidence"]
    assert any("fallback plan" in warning for warning in output["warnings"])


def test_service_cache_records_hit_on_second_run() -> None:
    service = ResearchService()
    request = ResearchRequest(company="Acme Analytics", focus="analytics platform risks")
    first, first_events, first_hit = service.run_sync(request)
    second, second_events, second_hit = service.run_sync(request)
    assert first.summary == second.summary
    assert first_hit is False
    assert second_hit is True
    assert first_events[0].event == "miss"
    assert second_events[0].event == "hit"
    assert any(event.node == "planner" for event in first_events)
    assert any(event.node == "planner" for event in second_events)
    assert any(event.event == "node_input" for event in first_events)
    assert any(event.event == "node_output" for event in first_events)


def test_cache_key_includes_provider(monkeypatch) -> None:
    request = ResearchRequest(company="Acme Analytics", focus="analytics platform risks")
    monkeypatch.setenv("RESEARCH_PROVIDER", "fixture")
    fixture_key = ResearchService.cache_key(request)
    monkeypatch.setenv("RESEARCH_PROVIDER", "openai")
    live_key = ResearchService.cache_key(request)
    assert fixture_key != live_key
    assert len(fixture_key) == 64


def test_openai_responses_provider_falls_back_with_diagnostics() -> None:
    class BrokenResponses:
        def parse(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
    provider.client = type("BrokenClient", (), {"responses": BrokenResponses()})()
    provider.model = "gpt-4.1"
    provider.diagnostics = []

    plan = provider.plan("Shopify", "commerce payments")
    evidence = provider.search(company="Shopify", focus="commerce payments", query="Shopify payments", retry_count=1)
    brief = provider.write_brief("Shopify", "commerce payments", evidence)

    assert default_model_for_provider("openai_responses") == "gpt-4.1"
    assert len(plan.steps) == 3
    assert evidence[0].source == "responses://web-search-unavailable"
    assert brief.sources == ["responses://web-search-unavailable"]
    assert {item["event"] for item in provider.diagnostics} == {
        "responses_plan_failed",
        "responses_search_failed",
        "responses_writer_failed",
    }
