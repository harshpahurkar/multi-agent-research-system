from __future__ import annotations

import json
import os
import re
import ipaddress
import socket
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from .models import Evidence, PlanStep, ResearchBrief


class ResearchProvider(Protocol):
    def search(self, *, company: str, focus: str, query: str, retry_count: int) -> list[Evidence]:
        ...


class FixtureResearchProvider:
    def __init__(self, fixture_path: str | Path | None = None) -> None:
        path = Path(fixture_path) if fixture_path else Path(__file__).resolve().parents[2] / "data" / "fixtures" / "research_corpus.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Offline research fixture corpus is missing at {path}. "
                "The fixture file is required for the default no-API-key demo path."
            )
        self.records = [Evidence.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
        self.diagnostics: list[dict[str, str]] = []

    def search(self, *, company: str, focus: str, query: str, retry_count: int) -> list[Evidence]:
        company_terms = set(company.lower().split())
        focus_terms = set(focus.lower().replace(",", " ").split())
        query_terms = set(query.lower().replace(",", " ").split())
        matches: list[Evidence] = []
        for record in self.records:
            haystack = " ".join([record.company, record.title, record.text, " ".join(record.topics)]).lower()
            company_match = any(term in haystack for term in company_terms)
            focus_match = any(term in haystack for term in focus_terms | query_terms)
            if company_match and focus_match:
                matches.append(record.model_copy(update={"relevance": min(1.0, record.relevance + 0.1)}))
            elif retry_count > 0 and company_match:
                matches.append(record.model_copy(update={"relevance": max(record.relevance * 0.75, 0.35)}))
        if matches:
            return sorted(matches, key=lambda item: item.relevance, reverse=True)[:5]
        if retry_count > 0:
            self.diagnostics.append({"event": "fixture_fallback", "company": company, "query": query})
            return [
                Evidence(
                    title="Fallback market research note",
                    source="fixture://fallback",
                    company=company,
                    text=(
                        "No precise source matched the request, so the workflow broadened the search. "
                        "The final brief should be treated as partial until live research is enabled."
                    ),
                    topics=["fallback", "partial"],
                    relevance=0.35,
                )
            ]
        return []


class OpenAIPlan(BaseModel):
    steps: list[PlanStep]


class OpenAIBrief(BaseModel):
    summary: str
    findings: list[str]
    risks: list[str]


class OpenAIEvidenceList(BaseModel):
    evidence: list[Evidence]


def _default_plan(company: str, focus: str) -> OpenAIPlan:
    return OpenAIPlan(
        steps=[
            PlanStep(id="company", query=f"{company} overview {focus}", purpose="Understand the company and product surface"),
            PlanStep(id="signals", query=f"{company} recent signals {focus}", purpose="Find evidence for strategy and product direction"),
            PlanStep(id="risks", query=f"{company} risks constraints {focus}", purpose="Identify risks and gaps"),
        ]
    )


def _fallback_brief(company: str, focus: str, evidence: list[Evidence]) -> ResearchBrief:
    findings = [f"{item.title}: {item.text}" for item in evidence[:4]] or [
        "No strong evidence was found; the brief is intentionally partial."
    ]
    return ResearchBrief(
        company=company,
        focus=focus,
        summary=f"{company} research brief focused on {focus}.",
        findings=findings,
        risks=["Validate recency with live search before external use."],
        sources=list(dict.fromkeys(item.source for item in evidence)),
    )


RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
SPACE_RE = re.compile(r"\s+")


def _clean_html(value: str) -> str:
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub("", value))).strip()


def _fetch_url_text(url: str, *, max_chars: int = 1800) -> str:
    """Fetch and clean a search result page for the researcher node.

    The provider treats URL fetching as best-effort because many public sites
    block bots or return non-HTML content. Search snippets remain the fallback.
    """
    if not _is_safe_fetch_url(url):
        return ""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 portfolio-research-system"})
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            raw = response.read(300_000)
            charset = response.headers.get_content_charset() or "utf-8"
        html = raw.decode(charset, errors="ignore")
        html = SCRIPT_RE.sub(" ", html)
        html = STYLE_RE.sub(" ", html)
        return _clean_html(html)[:max_chars]
    except Exception:
        return ""


def _is_safe_fetch_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {item[4][0] for item in resolved}
    if not addresses:
        return False
    return all(ipaddress.ip_address(address).is_global for address in addresses)


def _normalize_duckduckgo_url(href: str) -> str:
    href = unescape(href)
    parsed = urllib.parse.urlparse(href)
    params = urllib.parse.parse_qs(parsed.query)
    for key in ("uddg", "u"):
        if key in params and params[key]:
            href = params[key][0]
            break
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.endswith("/y.js"):
        return ""
    return href


def _duckduckgo_search(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 portfolio-research-system"})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="ignore")
    results: list[dict[str, str]] = []
    for match in RESULT_RE.finditer(html):
        href = _normalize_duckduckgo_url(match.group("href"))
        title = _clean_html(match.group("title"))
        snippet = _clean_html(match.group("snippet"))
        if href.startswith("http") and title and snippet:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _search_and_fetch(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    results = _duckduckgo_search(query, limit=limit)
    for item in results:
        item["page_text"] = _fetch_url_text(item["url"])
        item["fetched"] = bool(item["page_text"])
    return results


class OpenAICompatibleWebResearchProvider:
    """Live web-search provider that structures search snippets with Chat Completions."""

    def __init__(self, model: str = "gpt-4.1") -> None:
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key and not base_url:
            raise RuntimeError("OPENAI_API_KEY or OPENAI_BASE_URL is required for OpenAI-compatible research.")
        from openai import OpenAI  # type: ignore

        self.client = OpenAI(api_key=api_key or "openai-compatible-local", base_url=base_url)
        self.model = model
        self.diagnostics: list[dict[str, str]] = []

    def _chat_json(self, *, system: str, payload: dict, max_tokens: int = 900) -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0,
            max_tokens=max_tokens,
            timeout=30,
        )
        content = response.choices[0].message.content or ""
        return json.loads(_extract_json_object(content))

    def plan(self, company: str, focus: str) -> OpenAIPlan:
        payload = {
            "company": company,
            "focus": focus,
            "instruction": "Return JSON only with a 'steps' array of 3 concise research steps. Each step needs id, query, and purpose.",
        }
        try:
            parsed = self._chat_json(
                system="You create compact, source-seeking company research plans.",
                payload=payload,
                max_tokens=500,
            )
            return OpenAIPlan.model_validate(parsed)
        except Exception as exc:
            self.diagnostics.append({"event": "planner_fallback", "error": str(exc)})
            return OpenAIPlan(
                steps=[
                    PlanStep(id="company", query=f"{company} overview {focus}", purpose="Understand the company and product surface"),
                    PlanStep(id="signals", query=f"{company} recent signals {focus}", purpose="Find evidence for strategy and product direction"),
                    PlanStep(id="risks", query=f"{company} risks constraints {focus}", purpose="Identify risks and gaps"),
                ]
            )

    def search(self, *, company: str, focus: str, query: str, retry_count: int) -> list[Evidence]:
        search_query = f"{query} {company} {focus}".strip()
        search_results = _search_and_fetch(search_query, limit=5)
        if not search_results:
            if retry_count > 0:
                self.diagnostics.append({"event": "web_search_empty", "query": search_query})
                return [
                    Evidence(
                        title="Live web search returned no results",
                        source="web://duckduckgo-empty",
                        company=company,
                        text="The live web search provider returned no result snippets for this query.",
                        topics=["web-search", "empty"],
                        relevance=0.2,
                    )
                ]
            return []
        prompt = {
            "company": company,
            "focus": focus,
            "query": query,
            "search_results": search_results,
            "instruction": (
                "Return JSON only with an 'evidence' array. Each item must have title, source, company, "
                "text, topics, and relevance. Use fetched page_text when available and the snippet otherwise. "
                "Use the search result URL as source. Do not invent sources."
            ),
        }
        try:
            payload = self._chat_json(
                system="You convert live web search snippets into structured company research evidence.",
                payload=prompt,
                max_tokens=900,
            )
            parsed = OpenAIEvidenceList.model_validate(payload)
            return parsed.evidence[:5]
        except Exception as exc:
            self.diagnostics.append({"event": "evidence_structuring_fallback", "error": str(exc), "query": search_query})
            return [
                Evidence(
                    title=item["title"],
                    source=item["url"],
                    company=company,
                    text=item.get("page_text") or item["snippet"],
                    topics=["web-search", "url-fetch" if item.get("fetched") else "snippet", focus],
                    relevance=max(0.4, 0.85 - (index * 0.08)),
                )
                for index, item in enumerate(search_results)
            ]

    def write_brief(self, company: str, focus: str, evidence: list[Evidence]) -> ResearchBrief:
        payload = {
            "company": company,
            "focus": focus,
            "evidence": [item.model_dump() for item in evidence],
            "instruction": (
                "Return JSON only with summary, findings, and risks. Findings must be grounded in the supplied evidence. "
                "Do not invent sources or claims."
            ),
        }
        try:
            parsed = self._chat_json(
                system="You write concise, evidence-grounded company research briefs.",
                payload=payload,
                max_tokens=900,
            )
            brief = OpenAIBrief.model_validate(parsed)
            return ResearchBrief(
                company=company,
                focus=focus,
                summary=brief.summary,
                findings=brief.findings,
                risks=brief.risks,
                sources=list(dict.fromkeys(item.source for item in evidence)),
            )
        except Exception as exc:
            self.diagnostics.append({"event": "brief_writer_fallback", "error": str(exc)})
            findings = [f"{item.title}: {item.text}" for item in evidence[:4]] or [
                "No strong evidence was found; the brief is intentionally partial."
            ]
            return ResearchBrief(
                company=company,
                focus=focus,
                summary=f"{company} research brief focused on {focus}.",
                findings=findings,
                risks=["Validate recency with live search before external use."],
                sources=list(dict.fromkeys(item.source for item in evidence)),
            )


def _extract_json_object(text: str) -> str:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
            return text[index : index + end]
        except json.JSONDecodeError:
            continue
    raise ValueError("No JSON object found in model response.")


class OpenAIResponsesProvider:
    """Responses API provider with managed web search and structured outputs."""

    def __init__(self, model: str = "gpt-4.1") -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key and not base_url:
            raise RuntimeError("OPENAI_API_KEY or OPENAI_BASE_URL is required for OpenAI Responses research provider.")
        from openai import OpenAI  # type: ignore

        client_kwargs = {"api_key": api_key or "openai-compatible-local"}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = OpenAI(**client_kwargs)
        self.model = model
        self.diagnostics: list[dict[str, str]] = []

    def search(self, *, company: str, focus: str, query: str, retry_count: int) -> list[Evidence]:
        try:
            response = self.client.responses.parse(
                model=self.model,
                tools=[{"type": "web_search", "search_context_size": "medium"}],
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Return company research evidence as structured data. "
                            "Use concise source labels and relevance scores between 0 and 1. "
                            "Do not invent URLs or claims."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "company": company,
                                "focus": focus,
                                "query": query,
                                "retry_count": retry_count,
                                "instruction": "Use current, sourced web evidence where available.",
                            }
                        ),
                    },
                ],
                text_format=OpenAIEvidenceList,
                timeout=30,
            )
            parsed = response.output_parsed
            return parsed.evidence[:5]
        except Exception as exc:
            self.diagnostics.append({"event": "responses_search_failed", "error": str(exc), "query": query})
            if retry_count > 0:
                return [
                    Evidence(
                        title="Responses web search unavailable",
                        source="responses://web-search-unavailable",
                        company=company,
                        text="The Responses provider could not return structured web evidence for this retry.",
                        topics=["responses", "web-search", "partial"],
                        relevance=0.25,
                    )
                ]
            return []

    def plan(self, company: str, focus: str) -> OpenAIPlan:
        try:
            return self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": "Return a concise research plan as structured data."},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "company": company,
                                "focus": focus,
                                "instruction": "Return exactly three source-seeking steps with id, query, and purpose.",
                            }
                        ),
                    },
                ],
                text_format=OpenAIPlan,
                timeout=30,
            ).output_parsed
        except Exception as exc:
            self.diagnostics.append({"event": "responses_plan_failed", "error": str(exc)})
            return _default_plan(company, focus)

    def write_brief(self, company: str, focus: str, evidence: list[Evidence]) -> ResearchBrief:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": "Write a concise company research brief only from supplied evidence. Do not invent sources.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "company": company,
                                "focus": focus,
                                "evidence": [item.model_dump() for item in evidence],
                            }
                        ),
                    },
                ],
                text_format=OpenAIBrief,
                timeout=30,
            )
            parsed = response.output_parsed
            return ResearchBrief(
                company=company,
                focus=focus,
                summary=parsed.summary,
                findings=parsed.findings,
                risks=parsed.risks,
                sources=list(dict.fromkeys(item.source for item in evidence)),
            )
        except Exception as exc:
            self.diagnostics.append({"event": "responses_writer_failed", "error": str(exc)})
            return _fallback_brief(company, focus, evidence)
