<h1 align="center">Multi-Agent Research System</h1>

<p align="center">
  <em>5-node LangGraph pipeline that plans, researches, evaluates evidence quality, and writes structured company briefs — offline by default, OpenAI-ready in production.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white&style=flat-square" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-8A2BE2?style=flat-square" alt="LangGraph" />
  <img src="https://img.shields.io/badge/FastAPI-async%20jobs-009688?logo=fastapi&logoColor=white&style=flat-square" alt="FastAPI" />
  <img src="https://img.shields.io/badge/offline--first-no%20API%20keys%20needed-brightgreen?style=flat-square" alt="Offline-first" />
  <img src="https://img.shields.io/badge/Redis-optional%20cache-DC382D?logo=redis&logoColor=white&style=flat-square" alt="Redis" />
  <img src="https://img.shields.io/github/license/harshpahurkar/multi-agent-research-system?style=flat-square" alt="License" />
</p>

---

**Multi-Agent Research System** is a FastAPI service backed by a LangGraph `StateGraph` that autonomously researches any company or topic and returns a structured brief with sources, quality scores, and full node-level execution traces. The pipeline runs **fully offline** against fixture providers — no API keys required to run, test, or evaluate it. Configure `OPENAI_API_KEY` and a `REDIS_URL` to upgrade to live LLM planning, web search, and persistent async job storage.

The core design question: *how do you stop a multi-agent pipeline from returning junk when the researcher finds nothing useful?* The answer here is an explicit evaluator node that scores evidence quality using a weighted formula and routes back to the researcher for a broader retry before the writer ever runs.

## Key Features

- **5-node LangGraph DAG** — Planner → Researcher → Evaluator → Writer → Finalizer with full state schema
- **Evidence quality gate** — evaluator scores `0.65 × relevance_ratio + 0.25 × avg_relevance + 0.10 × coverage` and retries below `0.70`
- **Swappable providers** — fixture (offline), OpenAI-compatible LLM, Tavily/SerpAPI web search, Redis cache
- **Async job API** — `POST /research/jobs` returns a job ID; poll status and stream per-node events
- **React dashboard** (SignalBrief Desk) — live pipeline graph, evidence cards, retry counter, event inspector
- **Fully observable** — every node emits `node_input`, `node_output`, tool call, and retry decision events

## Quickstart

```bash
pip install -e ".[dev]"
python -m pytest                 # all tests pass offline — no keys needed
python -m research_system        # → http://127.0.0.1:8002/docs
```

Run a research brief in one command:

```bash
curl -s -X POST http://127.0.0.1:8002/research/run-sync \
  -H "Content-Type: application/json" \
  -d '{"company":"Stripe","focus":"fraud detection AI"}' | python -m json.tool
```

## UI — SignalBrief Desk

```bash
# Terminal 1 — backend
python -m research_system

# Terminal 2 — frontend dev server
cd frontend && npm install && npm run dev
# → http://127.0.0.1:5174
```

**Demo flow:**
1. Click **Run sample brief** — auto-runs SurveyMonkey research
2. Watch the pipeline diagram light up node by node
3. Check the quality score card and retry indicator
4. Open the event inspector to see raw `node_input` / `node_output` payloads

Build the production UI (served by FastAPI at `/`):

```bash
cd frontend && npm run build
python -m research_system        # → http://127.0.0.1:8002
```

## Architecture

```
POST /research/run-sync  or  POST /research/jobs
              │
              ▼
        ┌─────────────┐
        │   Planner   │  generates research steps from company + focus
        └──────┬──────┘
               │
               ▼
        ┌─────────────────────────────────────────────────────┐
        │             Researcher                              │
        │  fixture provider (offline) / OpenAI / Tavily      │
        └──────┬──────────────────────────────────────────────┘
               │
               ▼
        ┌─────────────┐    score < 0.70 or empty evidence
        │  Evaluator  │ ─────────────────────────────────► Researcher (retry)
        └──────┬──────┘    max_retries respected
               │ score ≥ 0.70
               ▼
        ┌──────────────┐
        │    Writer    │  structures findings, risks, and citations
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │  Finalizer   │  assembles brief + run metadata + event log
        └──────────────┘
               │
               ▼
   JSON brief  +  /research/jobs/{id}/events
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Service liveness and current configuration |
| `POST` | `/research/run-sync` | Run the full pipeline synchronously and return a brief |
| `POST` | `/research/jobs` | Queue an async job; returns `{ job_id }` immediately |
| `GET` | `/research/jobs/{job_id}` | Read job status (`queued` / `running` / `completed` / `failed`) |
| `GET` | `/research/jobs/{job_id}/events` | Stream per-node `node_input`, `node_output`, and tool call events |

**Example — sync request:**

```bash
curl -s -X POST http://127.0.0.1:8002/research/run-sync \
  -H "Content-Type: application/json" \
  -d '{"company":"SurveyMonkey","focus":"survey customer feedback AI insights"}' \
  | python -m json.tool
```

**Example — async job:**

```bash
JOB=$(curl -s -X POST http://127.0.0.1:8002/research/jobs \
  -H "Content-Type: application/json" \
  -d '{"company":"Stripe","focus":"fraud detection ML"}' | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

curl http://127.0.0.1:8002/research/jobs/$JOB/events
```

## LangGraph State Schema

```python
company:       str              # target company or topic
focus:         str              # research angle
max_retries:   int              # default 2
plan:          list[str]        # planner-generated research steps
evidence:      list[Evidence]   # results with sources + relevance scores
quality_score: float            # 0.65*relevance_ratio + 0.25*avg_relevance + 0.10*coverage
retry_count:   int              # increments on each Evaluator → Researcher loop
warnings:      list[str]        # populated on partial or retried runs
draft:         dict             # Writer output (findings, risks, recommendations)
final:         dict             # Finalizer output (brief + metadata)
events:        list[RunEvent]   # full per-node trace
```

## Evidence Quality Formula

The Evaluator node scores the Researcher's output before passing it to the Writer:

```
quality = 0.65 × relevance_ratio
        + 0.25 × avg_relevance
        + 0.10 × coverage

threshold = 0.70
```

If `quality < 0.70` and `retry_count < max_retries`, the pipeline routes back to the Researcher with a broadened query. If the threshold is still not met after all retries, the brief is returned with `warnings` rather than silently failing.

## Retry Behavior

The Evaluator routes back to the Researcher when:

- Evidence list is empty
- Evidence is partially off-topic (low relevance scores)
- Quality score is below `0.70`
- `retry_count < max_retries`

On retry, the Researcher broadens its query terms based on planner context. Retries are capped so the pipeline never hangs.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RESEARCH_PROVIDER` | No | `fixture` | `fixture` (offline) \| `openai` \| `openai_responses` |
| `OPENAI_API_KEY` | If OpenAI | — | API key for live LLM planning and writing |
| `OPENAI_BASE_URL` | No | OpenAI | Point to any OpenAI-compatible proxy |
| `OPENAI_RESEARCH_MODEL` | No | `gpt-4o` | Model for planner, researcher, writer nodes |
| `REDIS_URL` | No | — | Enables Redis-backed cache and job storage |
| `RESEARCH_CACHE_BACKEND` | No | `memory` | `memory` \| `redis` |
| `RESEARCH_JOB_BACKEND` | No | `memory` | `memory` \| `redis` |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Workflow | [LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph` |
| Backend | Python 3.11 · FastAPI · Uvicorn |
| AI Providers | OpenAI-compatible LLM · Tavily / SerpAPI web search |
| Caching / Jobs | Redis (optional) · in-memory fallback |
| Frontend | React 18 · Vite · TanStack Query · Recharts · Tailwind CSS |
| Testing | Pytest · Playwright E2E |
| Containers | Docker Compose (Redis) |

## Testing

```bash
# Full offline suite
python -m pytest

# Redis integration (requires Docker Redis running)
REDIS_URL=redis://localhost:6380/0 python -m pytest tests/test_redis_integration.py

# Frontend E2E
cd frontend && npm run build && npm run test:e2e
```

The test suite covers graph execution, retry routing, partial results, cache hits, async job lifecycle, FastAPI validation, and Playwright E2E against the built UI.

## Event Trace Example

Every run records a complete event log accessible via `/research/jobs/{id}/events`:

```json
[
  { "node": "planner",    "event": "node_input",           "payload": { "company": "Stripe" } },
  { "node": "planner",    "event": "node_output",          "payload": { "plan": ["..."] } },
  { "node": "researcher", "event": "tool_calls_completed", "payload": { "sources": 4 } },
  { "node": "evaluator",  "event": "quality_scored",       "payload": { "score": 0.61, "retry": true } },
  { "node": "researcher", "event": "tool_calls_completed", "payload": { "sources": 7 } },
  { "node": "evaluator",  "event": "quality_scored",       "payload": { "score": 0.78, "retry": false } },
  { "node": "writer",     "event": "draft_created",        "payload": {} },
  { "node": "finalizer",  "event": "brief_finalized",      "payload": {} }
]
```

This trace is what the SignalBrief Desk event inspector renders. Broken agent runs are fully inspectable without replaying the workflow.

## License

MIT
