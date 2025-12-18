from __future__ import annotations

from research_system import providers


def test_search_provider_fetches_result_pages(monkeypatch) -> None:
    monkeypatch.setattr(
        providers,
        "_duckduckgo_search",
        lambda query, limit=5: [
            {
                "title": "SurveyMonkey AI analysis",
                "url": "https://example.com/surveymonkey-ai",
                "snippet": "SurveyMonkey turns feedback into insights.",
            }
        ],
    )
    monkeypatch.setattr(
        providers,
        "_fetch_url_text",
        lambda url: "Fetched page text about SurveyMonkey AI analysis and customer feedback insights.",
    )

    results = providers._search_and_fetch("SurveyMonkey AI analysis", limit=1)

    assert results[0]["fetched"] is True
    assert "Fetched page text" in results[0]["page_text"]


def test_fetch_url_rejects_local_and_metadata_hosts() -> None:
    assert providers._is_safe_fetch_url("http://127.0.0.1:6379/") is False
    assert providers._is_safe_fetch_url("http://localhost:8000/") is False
    assert providers._is_safe_fetch_url("http://169.254.169.254/latest/meta-data/") is False


def test_extract_json_object_handles_braces_inside_strings() -> None:
    payload = providers._extract_json_object('prefix {"text": "literal { brace }", "nested": {"ok": true}} suffix')
    assert payload == '{"text": "literal { brace }", "nested": {"ok": true}}'
