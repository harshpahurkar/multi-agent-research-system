# Multi-Agent Research System

FastAPI service that runs a LangGraph research workflow with planner, researcher, evaluator, writer, and finalizer nodes. It is offline-first by default, so local tests and demos work without OpenAI keys or Redis. Live adapters add OpenAI-compatible planning/writing, web search, URL fetching, and Redis-backed caching/job storage when services are available.

## Architecture

```text
POST /research/run-sync or /research/jobs
        |
        v
  Planner node
        |
        v
  Researcher node -> fixture/OpenAI provider -> web search + URL fetch
        |
        v
  Evaluator node -- retry if empty/off-topic/low quality --> Researcher node
        |
        v
  Writer node
        |
        v
  Finalizer node -> JSON research brief + run events
```

## Quickstart

```powershell
cd C:\Users\Harsh\Desktop\Projects\multi-agent-research-system
$env:TEMP="$PWD\.tmp"; $env:TMP=$env:TEMP; $env:PIP_CACHE_DIR="$PWD\.pip-cache"
New-Item -ItemType Directory -Force -Path $env:TEMP,$env:PIP_CACHE_DIR | Out-Null
python -m pip install -e ".[dev]"
python -m pytest
python -m research_system
```

Open `http://127.0.0.1:8002/docs`.

## UI Demo: SignalBrief Desk

SignalBrief Desk is the browser desk for running company research briefs with visible agent planning, evidence, retries, and node-level payloads. It is a separate React app under `frontend/`, and the FastAPI server serves the production build from `/` when `frontend/dist` exists.

```powershell
cd C:\Users\Harsh\Desktop\Projects\multi-agent-research-system\frontend
npm.cmd install
npm.cmd run dev
```

In another terminal:

```powershell
cd C:\Users\Harsh\Desktop\Projects\multi-agent-research-system
python -m research_system
```

Open `http://127.0.0.1:5174`.

Demo flow:

1. Run a sync brief for `SurveyMonkey` with focus `survey customer feedback AI insights`.
2. Review the brief viewer, graph timeline, quality score, retry count, and evidence cards.
3. Create an async job and watch the job board move through queued/running/completed.
4. Open the event debugger and verify `node_input`, `node_output`, tool calls, quality scoring, and finalizer payloads.

Build the UI for the FastAPI static route:

```powershell
cd C:\Users\Harsh\Desktop\Projects\multi-agent-research-system\frontend
npm.cmd run build
cd ..
python -m research_system
```

Then open `http://127.0.0.1:8002` for the product UI or `http://127.0.0.1:8002/docs` for Swagger.

UI verification:

```powershell
cd C:\Users\Harsh\Desktop\Projects\multi-agent-research-system\frontend
npm.cmd run build
npm.cmd run test:e2e
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health |
| `POST` | `/research/run-sync` | Run the graph synchronously and return a brief |
| `POST` | `/research/jobs` | Create an async job backed by background tasks |
| `GET` | `/research/jobs/{job_id}` | Read job status and result |
| `GET` | `/research/jobs/{job_id}/events` | Read run/cache events |

Example:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8002/research/run-sync `
  -ContentType "application/json" `
  -Body '{"company":"SurveyMonkey","focus":"survey customer feedback AI insights"}'
```

## State Schema

The LangGraph state carries:

- `company`, `focus`, `max_retries`
- `plan`: planner-generated research steps
- `evidence`: researcher results with sources and relevance scores
- `quality_score`, `retry_count`, `warnings`
- `draft` and `final` brief payloads
- `events`: full per-node input payloads, output payloads, tool calls, retry decisions, state changes, and finalization metadata

## Retry Behavior

The evaluator routes back to the researcher when:

- evidence is empty
- evidence is partially off-topic
- quality score is below `0.7`
- `retry_count` is below `max_retries`

Retries are capped. If the workflow still cannot find strong evidence, it returns a partial brief with warnings instead of hanging.

## Redis And OpenAI

Redis is optional:

```powershell
Copy-Item .env.example .env
# Edit .env and set a local Redis password before starting Redis.
docker compose --env-file .env up -d redis
$env:RESEARCH_REDIS_PASSWORD="<your-local-password>"
$env:REDIS_URL="redis://:$($env:RESEARCH_REDIS_PASSWORD)@localhost:6380/0"
$env:RESEARCH_CACHE_BACKEND="redis"
$env:RESEARCH_JOB_BACKEND="redis"
python -m pip install -e ".[redis]"
python -m pytest tests/test_redis_integration.py
```

With those variables set, `run-sync` uses Redis for cache hits and `/research/jobs` persists queued/running/completed job records in Redis instead of the in-memory job store.

OpenAI-compatible live research is optional. When `RESEARCH_PROVIDER=openai` is set, the provider uses DuckDuckGo search, fetches result URLs, and asks the configured chat model to structure planner steps, evidence, and the final brief:

```powershell
$env:OPENAI_BASE_URL="http://localhost:4141/v1"
$env:OPENAI_API_KEY="copilot-proxy"
$env:RESEARCH_PROVIDER="openai"
$env:OPENAI_RESEARCH_MODEL="gpt-4.1"
python -m pip install -e ".[openai]"
```

The optional `RESEARCH_PROVIDER=openai_responses` path remains available for the official OpenAI Responses API with hosted `web_search` when those credentials are configured.

The offline fixture provider remains the default because it makes tests deterministic.

## Testing

```powershell
python -m pytest
```

The test suite covers graph execution, planner/researcher/writer contracts, retry routing, partial results, cache hits, async job lifecycle, and FastAPI validation.

With Docker Redis running:

```powershell
$env:RESEARCH_REDIS_PASSWORD="<your-local-password>"
$env:REDIS_URL="redis://:$($env:RESEARCH_REDIS_PASSWORD)@localhost:6380/0"
python -m pytest tests/test_redis_integration.py
```

That integration test proves Redis cache hits, Redis-backed async job persistence, job event retrieval, and the FastAPI health/config surface.

Live transcript-aligned stack:

```powershell
$env:RUN_LIVE_STACK="1"
$env:OPENAI_BASE_URL="http://localhost:4141/v1"
$env:OPENAI_API_KEY="copilot-proxy"
$env:OPENAI_RESEARCH_MODEL="gpt-4.1"
$env:REDIS_URL="redis://:$($env:RESEARCH_REDIS_PASSWORD)@localhost:6380/0"
python -m pytest tests/test_live_web_research.py
```

That test proves live web search, URL-backed source evidence, provider planner/writer calls, Redis cache hits, async job storage, and full node input/output event logging.

## Debug Trace Example

A run records events like:

```json
[
  {"node":"planner","event":"node_input"},
  {"node":"planner","event":"plan_created"},
  {"node":"planner","event":"node_output"},
  {"node":"researcher","event":"node_input"},
  {"node":"researcher","event":"tool_calls_completed"},
  {"node":"researcher","event":"node_output"},
  {"node":"evaluator","event":"quality_scored"},
  {"node":"writer","event":"draft_created"},
  {"node":"finalizer","event":"brief_finalized"}
]
```

The API exposes job events separately so broken agent runs can be inspected without replaying the workflow.

## Portfolio Design Notes

- The graph is explicit and inspectable instead of hidden inside a single prompt.
- The evaluator owns retry decisions, which makes empty or off-topic research failures visible.
- Offline fixtures provide deterministic proof; OpenAI and Redis paths are additive, not required.

## Resume Claim Mapping

- LangGraph workflow with planner/researcher/writer nodes: `workflow.py` and the SignalBrief Desk graph timeline
- Retries for empty/off-topic results: evaluator conditional edge in `workflow.py` plus retry markers and warnings in the UI
- Logged node inputs, outputs, tool calls, state changes: full `node_input`/`node_output` `RunEvent` payloads, job event endpoints, and the UI Event Debugger
- FastAPI async jobs, Redis-backed caching/job storage, JSON output: `api.py`, `jobs.py`, `cache.py`, and the UI Job Board
