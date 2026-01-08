from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .logging import append_event
from .models import Evidence, PlanStep, ResearchBrief, ResearchRequest, ResearchState
from .providers import FixtureResearchProvider, ResearchProvider


def _without_nested_events(value):
    if isinstance(value, dict):
        return {key: _without_nested_events(item) for key, item in value.items() if key != "events"}
    if isinstance(value, list):
        return [_without_nested_events(item) for item in value]
    return value


def _state_payload(state: ResearchState) -> dict:
    return _without_nested_events({key: value for key, value in dict(state).items() if key != "events"})


def _output_payload(output: dict) -> dict:
    return _without_nested_events({key: value for key, value in output.items() if key != "events"})


def _append_node_input(state: ResearchState, node: str) -> list[dict]:
    return append_event(state.get("events"), node, "node_input", state=_state_payload(state))


def _append_node_output(events: list[dict], node: str, output: dict) -> list[dict]:
    return append_event(events, node, "node_output", output=_output_payload(output))


def _plan(company: str, focus: str) -> list[PlanStep]:
    return [
        PlanStep(id="company", query=f"{company} overview {focus}", purpose="Understand the company and product surface"),
        PlanStep(id="signals", query=f"{company} recent signals {focus}", purpose="Find evidence for strategy and product direction"),
        PlanStep(id="risks", query=f"{company} risks constraints {focus}", purpose="Identify risks and gaps"),
    ]


def _score_evidence(company: str, focus: str, evidence: list[Evidence]) -> tuple[float, list[str]]:
    if not evidence:
        return 0.0, ["No research evidence was found."]
    company_terms = set(company.lower().split())
    focus_terms = set(focus.lower().replace(",", " ").split())
    relevant = 0
    relevance_total = 0.0
    warnings: list[str] = []
    for item in evidence:
        relevance_total += item.relevance
        haystack = " ".join([item.company, item.title, item.text, " ".join(item.topics)]).lower()
        company_match = any(term in haystack for term in company_terms)
        focus_match = any(term in haystack for term in focus_terms)
        if company_match and (focus_match or item.relevance >= 0.7):
            relevant += 1
    relevance_ratio = relevant / len(evidence)
    average_relevance = relevance_total / len(evidence)
    coverage = min(1.0, len(evidence) / 3)
    score = round(min(1.0, max(0.0, (0.65 * relevance_ratio) + (0.25 * average_relevance) + (0.10 * coverage))), 4)
    if score < 0.7:
        warnings.append("Research evidence was thin or partially off-topic.")
    return score, warnings


class ResearchWorkflow:
    def __init__(self, provider: ResearchProvider | None = None) -> None:
        self.provider = provider or FixtureResearchProvider()
        self.graph = self._compile()

    def run(self, request: ResearchRequest, *, job_id: str = "sync") -> ResearchBrief:
        initial: ResearchState = {
            "job_id": job_id,
            "company": request.company,
            "focus": request.focus,
            "max_retries": request.max_retries,
            "retry_count": 0,
            "warnings": [],
            "events": [],
            "should_retry": False,
            "status": "running",
        }
        try:
            final_state = self.graph.invoke(initial)
            final = final_state.get("final")
            if final is None:
                raise KeyError("workflow completed without a final brief")
            return ResearchBrief.model_validate(final)
        except Exception as exc:
            events = append_event(initial.get("events"), "workflow", "failed", error=str(exc))
            return ResearchBrief(
                company=request.company,
                focus=request.focus,
                summary=f"{request.company} research brief could not be completed.",
                findings=["The workflow failed before it could produce grounded findings."],
                risks=["Inspect the workflow failure event before using this brief."],
                sources=[],
                warnings=[f"Workflow failed: {exc}"],
                quality_score=0.0,
                retry_count=initial.get("retry_count", 0),
                events=events,
            )

    def _compile(self):
        graph = StateGraph(ResearchState)
        graph.add_node("planner", self._planner_node)
        graph.add_node("researcher", self._researcher_node)
        graph.add_node("evaluator", self._evaluator_node)
        graph.add_node("writer", self._writer_node)
        graph.add_node("finalizer", self._finalizer_node)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "researcher")
        graph.add_edge("researcher", "evaluator")
        graph.add_conditional_edges(
            "evaluator",
            self._route_after_eval,
            {"retry": "researcher", "write": "writer"},
        )
        graph.add_edge("writer", "finalizer")
        graph.add_edge("finalizer", END)
        return graph.compile()

    def _planner_node(self, state: ResearchState) -> ResearchState:
        events = _append_node_input(state, "planner")
        company = state.get("company", "Unknown")
        focus = state.get("focus", "general research")
        planner = getattr(self.provider, "plan", None)
        if callable(planner):
            try:
                steps = planner(company, focus).steps
                plan_source = "provider"
            except Exception as exc:
                steps = _plan(company, focus)
                plan_source = "fallback"
                state["warnings"] = [*state.get("warnings", []), f"Planner provider failed: {exc}"]
        else:
            steps = _plan(company, focus)
            plan_source = "local"
        events = append_event(
            events,
            "planner",
            "plan_created",
            source=plan_source,
            steps=[step.model_dump() for step in steps],
        )
        diagnostics = _consume_provider_diagnostics(self.provider)
        if diagnostics:
            events = append_event(events, "planner", "provider_diagnostics", diagnostics=diagnostics)
        output = {"plan": [step.model_dump() for step in steps], "warnings": state.get("warnings", [])}
        events = _append_node_output(events, "planner", output)
        output["events"] = events
        return output

    def _researcher_node(self, state: ResearchState) -> ResearchState:
        events = _append_node_input(state, "researcher")
        company = state.get("company", "Unknown")
        focus = state.get("focus", "general research")
        warnings = list(state.get("warnings", []))
        all_evidence: list[Evidence] = []
        retry_count = state.get("retry_count", 0)
        raw_plan = state.get("plan")
        if not raw_plan:
            warnings.append("Researcher received no plan, so it built a local fallback plan.")
            events = append_event(events, "researcher", "missing_plan_fallback")
            raw_plan = [step.model_dump() for step in _plan(company, focus)]
        for raw_step in raw_plan:
            try:
                step = PlanStep.model_validate(raw_step)
            except Exception as exc:
                warnings.append(f"Research plan step was invalid and skipped: {exc}")
                events = append_event(events, "researcher", "invalid_plan_step", error=str(exc), raw_step=raw_step)
                continue
            query = step.query
            if retry_count > 0:
                query = f"{step.query} {company} {focus} broader credible sources recent overview"
            try:
                results = self.provider.search(
                    company=company,
                    focus=focus,
                    query=query,
                    retry_count=retry_count,
                )
            except Exception as exc:
                warnings.append(f"Research provider failed for step '{step.id}': {exc}")
                events = append_event(events, "researcher", "tool_call_failed", step=step.id, query=query, error=str(exc))
                continue
            for item in results:
                try:
                    all_evidence.append(Evidence.model_validate(item))
                except Exception as exc:
                    warnings.append(f"Research provider returned invalid evidence for step '{step.id}': {exc}")
                    events = append_event(events, "researcher", "invalid_evidence", step=step.id, error=str(exc))
        deduped = {(item.source, item.title): item for item in all_evidence}
        evidence = sorted(deduped.values(), key=lambda item: item.relevance, reverse=True)[:8]
        events = append_event(
            events,
            "researcher",
            "tool_calls_completed",
            retry_count=retry_count,
            evidence_count=len(evidence),
            sources=[item.source for item in evidence],
            evidence=[item.model_dump() for item in evidence],
        )
        diagnostics = _consume_provider_diagnostics(self.provider)
        if diagnostics:
            events = append_event(events, "researcher", "provider_diagnostics", diagnostics=diagnostics)
        output = {"evidence": [item.model_dump() for item in evidence], "warnings": list(dict.fromkeys(warnings))}
        events = _append_node_output(events, "researcher", output)
        output["events"] = events
        return output

    def _evaluator_node(self, state: ResearchState) -> ResearchState:
        events = _append_node_input(state, "evaluator")
        evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
        quality_score, warnings = _score_evidence(state.get("company", "Unknown"), state.get("focus", "general research"), evidence)
        retry_count = state.get("retry_count", 0)
        should_retry = quality_score < 0.7 and retry_count < state.get("max_retries", 2)
        next_retry_count = retry_count + 1 if should_retry else retry_count
        events = append_event(
            events,
            "evaluator",
            "quality_scored",
            quality_score=quality_score,
            should_retry=should_retry,
            retry_count=next_retry_count,
            warnings=warnings,
        )
        output = {
            "quality_score": quality_score,
            "warnings": list(dict.fromkeys([*state.get("warnings", []), *warnings])),
            "retry_count": next_retry_count,
            "should_retry": should_retry,
        }
        events = _append_node_output(events, "evaluator", output)
        output["events"] = events
        return output

    def _route_after_eval(self, state: ResearchState) -> str:
        if state.get("should_retry", False):
            return "retry"
        return "write"

    def _writer_node(self, state: ResearchState) -> ResearchState:
        events = _append_node_input(state, "writer")
        company = state.get("company", "Unknown")
        focus = state.get("focus", "general research")
        evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
        writer = getattr(self.provider, "write_brief", None)
        if callable(writer):
            try:
                model_brief = writer(company, focus, evidence)
                brief = model_brief.model_dump()
                brief["warnings"] = state.get("warnings", [])
                brief["quality_score"] = state.get("quality_score", 0.0)
                brief["retry_count"] = state.get("retry_count", 0)
                events = append_event(
                    events,
                    "writer",
                    "draft_created",
                    source="provider",
                    finding_count=len(model_brief.findings),
                    draft=brief,
                )
                diagnostics = _consume_provider_diagnostics(self.provider)
                if diagnostics:
                    events = append_event(events, "writer", "provider_diagnostics", diagnostics=diagnostics)
                output = {"draft": brief}
                events = _append_node_output(events, "writer", output)
                output["events"] = events
                return output
            except Exception as exc:
                state["warnings"] = [*state.get("warnings", []), f"Writer provider failed: {exc}"]
                diagnostics = _consume_provider_diagnostics(self.provider)
                if diagnostics:
                    events = append_event(events, "writer", "provider_diagnostics", diagnostics=diagnostics)
        findings = [
            f"{item.title}: {item.text}"
            for item in evidence[:4]
        ] or ["No strong evidence was found; the brief is intentionally partial."]
        risks = [
            "Evidence quality is below threshold." if state.get("quality_score", 0.0) < 0.7 else "Validate recency with live search before external use.",
            "Fixture mode may miss late-breaking company updates.",
        ]
        brief = {
            "company": company,
            "focus": focus,
            "summary": f"{company} research brief focused on {focus}.",
            "findings": findings,
            "risks": risks,
            "sources": list(dict.fromkeys(item.source for item in evidence)),
            "warnings": state.get("warnings", []),
            "quality_score": state.get("quality_score", 0.0),
            "retry_count": state.get("retry_count", 0),
        }
        events = append_event(events, "writer", "draft_created", finding_count=len(findings), draft=brief)
        output = {"draft": brief}
        events = _append_node_output(events, "writer", output)
        output["events"] = events
        return output

    def _finalizer_node(self, state: ResearchState) -> ResearchState:
        events = _append_node_input(state, "finalizer")
        draft = state.get("draft")
        if draft is None:
            events = append_event(events, "finalizer", "missing_draft_fallback")
            draft = {
                "company": state.get("company", "Unknown"),
                "focus": state.get("focus", "general research"),
                "summary": f"{state.get('company', 'Unknown')} research brief could not be drafted.",
                "findings": ["No draft was available, so the finalizer produced a partial brief."],
                "risks": ["Inspect earlier workflow events before using this brief."],
                "sources": [],
                "warnings": [*state.get("warnings", []), "Finalizer received no draft."],
                "quality_score": state.get("quality_score", 0.0),
                "retry_count": state.get("retry_count", 0),
            }
        try:
            brief = ResearchBrief.model_validate(draft)
        except Exception as exc:
            events = append_event(events, "finalizer", "invalid_draft_fallback", error=str(exc))
            brief = ResearchBrief(
                company=state.get("company", "Unknown"),
                focus=state.get("focus", "general research"),
                summary=f"{state.get('company', 'Unknown')} research brief could not be validated.",
                findings=["The writer produced an invalid draft, so the finalizer returned a partial brief."],
                risks=["Inspect the invalid draft event before using this brief."],
                sources=[],
                warnings=[*state.get("warnings", []), f"Finalizer rejected invalid draft: {exc}"],
                quality_score=state.get("quality_score", 0.0),
                retry_count=state.get("retry_count", 0),
            )
        events = append_event(
            events,
            "finalizer",
            "brief_finalized",
            source_count=len(brief.sources),
            warning_count=len(brief.warnings),
            final=brief.model_dump(),
        )
        final = brief.model_dump()
        output = {"final": final, "status": "completed"}
        events = _append_node_output(events, "finalizer", output)
        final["events"] = events
        output["final"] = final
        output["events"] = events
        return output


def _consume_provider_diagnostics(provider: ResearchProvider) -> list[dict]:
    diagnostics = list(getattr(provider, "diagnostics", []) or [])
    if hasattr(provider, "diagnostics"):
        setattr(provider, "diagnostics", [])
    return diagnostics
