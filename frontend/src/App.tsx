import {
  Activity,
  AlertTriangle,
  Bot,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileText,
  GitBranch,
  Loader2,
  PanelRightOpen,
  Radar,
  Search,
  Send,
  Sparkles,
  Workflow,
  X
} from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, Health, JobRecord, ResearchBrief, RunEvent } from "./api";

const nodes = ["planner", "researcher", "evaluator", "writer", "finalizer"];
const navItems = [
  { id: "runner", label: "Run research", icon: Search },
  { id: "brief", label: "Read brief", icon: BriefcaseBusiness },
  { id: "evidence", label: "Check evidence", icon: FileText },
  { id: "graph", label: "Watch workflow", icon: Workflow },
  { id: "jobs", label: "Async job", icon: Clock3 },
  { id: "events", label: "Inspect events", icon: PanelRightOpen }
];
const navIds = navItems.map((item) => item.id);

function researchSnapshot(events: RunEvent[]) {
  const latestToolEvent = [...events]
    .reverse()
    .find((item) => item.node === "researcher" && item.event === "tool_calls_completed");
  if (latestToolEvent) {
    return {
      evidence: (latestToolEvent.payload.evidence as Array<Record<string, unknown>> | undefined) ?? [],
      retryCount: Number(latestToolEvent.payload.retry_count ?? 0),
      source: "latest researcher pass"
    };
  }
  const researcherOutput = [...events]
    .reverse()
    .find((item) => item.node === "researcher" && item.event === "node_output");
  const output = researcherOutput?.payload?.output as { evidence?: Array<Record<string, unknown>> } | undefined;
  return { evidence: output?.evidence ?? [], retryCount: 0, source: "node output" };
}

function providerLabel(health?: Health) {
  if (!health) return "Connecting";
  if (health.provider === "fixture") return "Offline fixture";
  if (health.provider === "openai_responses") return "Live Responses";
  if (health.provider === "openai" || health.provider === "web") return "Live web";
  return health.provider;
}

function sourceKind(source: string) {
  if (source.startsWith("fixture://")) return "fixture";
  if (source.startsWith("responses://")) return "provider diagnostic";
  if (source.startsWith("web://")) return "web diagnostic";
  if (/^https?:\/\//.test(source)) return "live url";
  return "source";
}

function formatScore(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return "0.00";
  return value.toFixed(2);
}

function metricScore(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return "--";
  return value.toFixed(2);
}

function useActiveSection(ids: string[]) {
  const [active, setActive] = useState(ids[0]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
        if (visible?.target.id) {
          setActive(visible.target.id);
        }
      },
      { rootMargin: "-18% 0px -68% 0px", threshold: [0.1, 0.35, 0.6] }
    );

    ids.forEach((id) => {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    });

    return () => observer.disconnect();
  }, [ids]);

  return active;
}

function StatCard({
  label,
  value,
  detail,
  icon: Icon
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Activity;
}) {
  return (
    <section className="metric-card">
      <div className="metric-icon"><Icon size={18} /></div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
    </section>
  );
}

function SkeletonCard() {
  return (
    <section className="metric-card skeleton-card" aria-label="Loading status">
      <span className="skeleton skeleton-icon" />
      <div>
        <span className="skeleton skeleton-line short" />
        <span className="skeleton skeleton-line large" />
        <span className="skeleton skeleton-line" />
      </div>
    </section>
  );
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="json-panel">
      <div className="panel-title">{title}</div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

function SourceGate({
  health,
  quality,
  sourceCount,
  retryCount,
  backendError
}: {
  health?: Health;
  quality?: number;
  sourceCount: number;
  retryCount: number;
  backendError: string;
}) {
  const fixtureMode = health?.provider === "fixture";
  return (
    <section className={`source-gate ${fixtureMode ? "fixture" : "live"}`} role={backendError ? "alert" : undefined}>
      <div>
        <span className="eyebrow">Trust gate</span>
        <h2>{backendError ? "Research backend is offline" : providerLabel(health)}</h2>
        <p>
          {backendError ||
            (fixtureMode
              ? "Offline fixture mode is for demos and CI. Do not treat a high score as current market research."
              : "Live provider mode still needs source review before external use.")}
        </p>
      </div>
      <div className="gate-metrics">
        <span>Quality {quality === undefined ? "--" : formatScore(quality)}</span>
        <span>{sourceCount || "--"} sources</span>
        <span>{retryCount} retries</span>
      </div>
    </section>
  );
}

function SourceReference({ source }: { source: string }) {
  const kind = sourceKind(source);
  if (kind === "fixture") {
    return <span className="source-reference fixture-source">{source}</span>;
  }
  if (kind.includes("diagnostic")) {
    return <span className="source-reference diagnostic-source">{source}</span>;
  }
  return (
    <a className="source-reference" href={source} target="_blank" rel="noreferrer">
      <ExternalLink size={14} /> {source}
    </a>
  );
}

export default function App() {
  const [eventDrawerOpen, setEventDrawerOpen] = useState(false);
  const [guideVisible, setGuideVisible] = useState(() => localStorage.getItem("signalbrief:start-guide") !== "hidden");
  const activeSection = useActiveSection(navIds);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5000 });
  const syncRun = useMutation({ mutationFn: api.runSync });
  const createJob = useMutation({ mutationFn: api.createJob });

  const jobId = createJob.data?.job_id;
  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 2500;
    }
  });
  const eventQuery = useQuery({
    queryKey: ["events", jobId, jobQuery.data?.status],
    queryFn: () => api.getEvents(jobId as string),
    enabled: Boolean(jobId && jobQuery.data?.status === "completed")
  });

  const activeBrief = jobQuery.data?.result ?? syncRun.data?.result;
  const activeEvents = eventQuery.data?.events ?? jobQuery.data?.events ?? syncRun.data?.events ?? activeBrief?.events ?? [];
  const snapshot = researchSnapshot(activeEvents);
  const evidence = snapshot.evidence;
  const isRunning = syncRun.isPending || createJob.isPending || jobQuery.data?.status === "running" || jobQuery.data?.status === "queued";
  const firstLoad = health.isPending && !health.data && !activeBrief;
  const backendError = health.error instanceof Error ? health.error.message : health.error ? String(health.error) : "";

  function dismissGuide() {
    localStorage.setItem("signalbrief:start-guide", "hidden");
    setGuideVisible(false);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">
          <div className="brand-icon"><Radar size={22} /></div>
          <div>
            <p>SignalBrief</p>
            <h1>Desk</h1>
          </div>
        </div>
        <nav>
          {navItems.map((item) => (
            <a href={`#${item.id}`} key={item.id} className={activeSection === item.id ? "active" : undefined}>
              <item.icon size={17} /> {item.label}
            </a>
          ))}
        </nav>
        <div className="sidebar-card">
          <Bot size={18} />
          <span>Manual company research eats 45 minutes. This writes the brief only after evidence clears a quality check, and it leaves receipts.</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">Traceable company research</span>
            <h1>SignalBrief Desk</h1>
            <p>Generate the brief, then check provider mode, evidence quality, and the latest source pass before trusting it.</p>
          </div>
          <div className="status-pill">
            <span className={health.data?.status === "ok" ? "dot ok" : "dot"} />
            {backendError ? "Backend offline" : `${providerLabel(health.data)} / ${health.data?.job_backend ?? "jobs"}`}
          </div>
        </header>

        <SourceGate
          health={health.data}
          quality={activeBrief?.quality_score}
          sourceCount={activeBrief?.sources.length ?? evidence.length}
          retryCount={activeBrief?.retry_count ?? snapshot.retryCount}
          backendError={backendError}
        />

        {guideVisible && !activeBrief && (
          <section className="start-guide">
            <div>
              <span className="eyebrow">Start here</span>
              <h2>Run one company brief with receipts</h2>
              <p>Use the default SurveyMonkey prompt. The evaluator must clear evidence quality before the writer turns it into a brief.</p>
            </div>
            <button className="primary" onClick={() => {
              dismissGuide();
              syncRun.mutate({ company: "SurveyMonkey", focus: "survey customer feedback AI insights", max_retries: 1 });
            }}>
              <Send size={16} /> Run sample brief
            </button>
            <button className="icon-button" aria-label="Dismiss start guide" onClick={dismissGuide}>
              <X size={17} />
            </button>
          </section>
        )}

        {(activeBrief || firstLoad) && (
          <section className="metric-grid compact-metrics">
            {firstLoad ? (
              Array.from({ length: 4 }).map((_, index) => <SkeletonCard key={index} />)
            ) : (
              <>
              <StatCard icon={BriefcaseBusiness} label="Company" value={activeBrief?.company ?? "--"} detail={activeBrief ? "Brief target loaded." : "Choose a company to research."} />
              <StatCard icon={Sparkles} label="Quality score" value={metricScore(activeBrief?.quality_score)} detail={activeBrief ? `${metricScore(activeBrief.quality_score)} against a 0.70 writing threshold.` : "Run a brief to see evaluator confidence."} />
              <StatCard icon={GitBranch} label="Retry count" value={activeBrief ? String(activeBrief.retry_count) : "--"} detail={activeBrief ? (activeBrief.retry_count > 0 ? "Evidence was weak, so it tried again." : "Evidence cleared without retry.") : "Retries happen only when evidence is weak."} />
              <StatCard icon={ExternalLink} label="Sources" value={activeBrief?.sources?.length ? String(activeBrief.sources.length) : "--"} detail={activeBrief ? "Open evidence cards below." : "Sources appear after research runs."} />
              </>
            )}
          </section>
        )}

        <section className="card panel" id="runner">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Research Runner</span>
              <h2>Start a traceable brief</h2>
            </div>
          </div>
          <RunForm
            syncPending={syncRun.isPending}
            asyncPending={createJob.isPending}
            onSync={(payload) => {
              dismissGuide();
              syncRun.mutate(payload);
            }}
            onAsync={(payload) => {
              dismissGuide();
              createJob.mutate(payload);
            }}
          />
          {isRunning && <div className="loading-row"><Loader2 className="spin" size={18} /> Researcher is collecting evidence. If the evaluator scores it below 0.70, the graph retries with a broader query.</div>}
          {(syncRun.error || createJob.error) && <div className="alert error">{syncRun.error?.message ?? createJob.error?.message}</div>}
        </section>

        {activeBrief ? <BriefViewer brief={activeBrief} /> : <BriefPreview />}

        <section className="card panel" id="evidence">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Evidence receipts</span>
              <h2>Latest source pass</h2>
            </div>
          </div>
          <p className="section-copy">Showing {snapshot.source}. Fixture sources are demo evidence, not current web citations.</p>
          <div className="evidence-grid">
            {evidence.map((item, index) => (
              <article className="evidence-card" key={`${String(item.source)}-${index}`}>
                <div>
                  <strong>{String(item.title)}</strong>
                  <span>{formatScore(Number(item.relevance))}</span>
                </div>
                <div className="source-meta">
                  <span>{sourceKind(String(item.source))}</span>
                  <span>retry {snapshot.retryCount}</span>
                </div>
                <p>{String(item.text).slice(0, 360)}</p>
                <SourceReference source={String(item.source)} />
                <div className="tag-row">
                  {((item.topics as string[]) ?? []).map((topic) => <span key={topic}>{topic}</span>)}
                </div>
              </article>
            ))}
            {!evidence.length && <div className="empty-state">Run a brief. The evidence cards will show the source URL, relevance score, excerpt, and topic tags that make the final write-up trustworthy.</div>}
          </div>
        </section>

        <section className="two-column">
          <section className="card panel" id="jobs">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Job Board</span>
                <h2>Async status</h2>
              </div>
              {jobQuery.isFetching && <Loader2 className="spin muted-icon" size={18} />}
            </div>
            <JobBoard job={jobQuery.data} created={createJob.data} />
          </section>

          <section className="card panel" id="graph">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Workflow pipeline</span>
                <h2>Planner to finalizer</h2>
              </div>
            </div>
            <PipelineDiagram events={activeEvents} />
          </section>
        </section>

        <section className="card panel" id="events">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Event Debugger</span>
              <h2>Full node inputs and outputs</h2>
            </div>
            <button className="secondary" aria-label="Open event debugger" onClick={() => setEventDrawerOpen(true)}>
              <PanelRightOpen size={16} />
              Open event debugger
            </button>
          </div>
          <div className="trace-grid">
            {activeEvents.map((event, index) => (
              <JsonPanel key={`${event.node}-${event.event}-${index}`} title={`${event.node}.${event.event}`} value={event.payload} />
            ))}
            {!activeEvents.length && <div className="empty-state">Run a brief first. This will show the exact planner input, researcher output, evaluator score, retry decision, writer draft, and finalizer payload.</div>}
          </div>
        </section>
      </section>
      <EventDrawer open={eventDrawerOpen} events={activeEvents} onClose={() => setEventDrawerOpen(false)} />
    </main>
  );
}

function EventDrawer({
  open,
  events,
  onClose
}: {
  open: boolean;
  events: RunEvent[];
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="inspector-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Event debugger"
        data-testid="event-drawer"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span className="eyebrow">Event Debugger</span>
            <h2>Per-node payload audit</h2>
          </div>
          <button className="icon-button" aria-label="Close event debugger" onClick={onClose}>
            <X size={17} />
          </button>
        </header>
        <div className="drawer-body">
          {events.map((event, index) => (
            <JsonPanel key={`${event.node}-${event.event}-${index}`} title={`${event.node}.${event.event}`} value={event.payload} />
          ))}
          {!events.length && <div className="empty-state">Run a brief first; the drawer will show planner, researcher, evaluator, writer, and finalizer payloads.</div>}
        </div>
      </aside>
    </div>
  );
}

function RunForm({
  syncPending,
  asyncPending,
  onSync,
  onAsync
}: {
  syncPending: boolean;
  asyncPending: boolean;
  onSync: (payload: { company: string; focus: string; max_retries: number }) => void;
  onAsync: (payload: { company: string; focus: string; max_retries: number }) => void;
}) {
  function payload(form: HTMLFormElement) {
    const data = new FormData(form);
    return {
      company: String(data.get("company")),
      focus: String(data.get("focus")),
      max_retries: Number(data.get("maxRetries"))
    };
  }
  return (
    <form className="run-form">
      <div>
        <label htmlFor="company">Company</label>
        <input id="company" name="company" defaultValue="SurveyMonkey" />
      </div>
      <div>
        <label htmlFor="focus">Focus</label>
        <input id="focus" name="focus" defaultValue="survey customer feedback AI insights" />
      </div>
      <div>
        <label htmlFor="maxRetries">Max retries</label>
        <input id="maxRetries" name="maxRetries" type="number" min={0} max={5} defaultValue={1} />
      </div>
      <button className="primary" type="button" disabled={syncPending} onClick={(event) => onSync(payload(event.currentTarget.form as HTMLFormElement))}>
        {syncPending ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
        Run sync brief
      </button>
      <details className="async-details">
        <summary>Async mode</summary>
        <button className="secondary" type="button" disabled={asyncPending} onClick={(event) => onAsync(payload(event.currentTarget.form as HTMLFormElement))}>
          {asyncPending ? <Loader2 className="spin" size={16} /> : <Clock3 size={16} />}
          Create async job
        </button>
      </details>
    </form>
  );
}

function JobBoard({ job, created }: { job?: JobRecord; created?: { job_id: string; status: string } }) {
  const status = job?.status ?? created?.status ?? "No job yet";
  return (
    <div className="job-board">
      <div className={`job-status ${status}`}>
        {status === "completed" ? <CheckCircle2 size={18} /> : status === "failed" ? <AlertTriangle size={18} /> : <Clock3 size={18} />}
        <strong>{status}</strong>
      </div>
      <div className="mode-grid">
        <span>Job ID</span>
        <strong>{job?.job_id ?? created?.job_id ?? "pending"}</strong>
        <span>Company</span>
        <strong>{job?.request.company ?? "not queued"}</strong>
        <span>Events</span>
        <strong>{job?.events.length ?? 0}</strong>
      </div>
      {job?.status === "failed" && <div className="alert error">{job.error ?? "Job failed without a stored error."}</div>}
    </div>
  );
}

function PipelineDiagram({ events }: { events: RunEvent[] }) {
  const researcherInputs = events.filter((event) => event.node === "researcher" && event.event === "node_input").length;
  return (
    <div className="pipeline">
      {nodes.map((node, index) => {
        const nodeEvents = events.filter((event) => event.node === node);
        const done = nodeEvents.some((event) => event.event === "node_output" || event.event === "brief_finalized");
        const retried = node === "researcher" && researcherInputs > 1;
        const label = retried ? "retried for quality" : done ? "complete" : "waiting";
        return (
          <article className={done ? "pipeline-step done" : "pipeline-step"} key={node}>
            <div className="pipeline-marker">{done ? <CheckCircle2 size={17} /> : <Clock3 size={17} />}</div>
            {index < nodes.length - 1 && <span className={done ? "pipeline-line done" : "pipeline-line"} />}
            <strong>{node}</strong>
            <span>{label}</span>
          </article>
        );
      })}
    </div>
  );
}

function BriefViewer({ brief }: { brief: ResearchBrief }) {
  return (
    <section className="card panel" id="brief">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Brief Viewer</span>
          <h2>{brief.company}</h2>
        </div>
      </div>
      <p className="brief-summary">{brief.summary}</p>
      <div className="brief-columns">
        <section>
          <div className="panel-title">Findings</div>
          <ol className="finding-list">
            {brief.findings.map((item, index) => (
              <li key={`${index}-${item}`}>
                <span>{index + 1}</span>
                <p>{item}</p>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <div className="panel-title">Risks</div>
          <div className="risk-list">
            {brief.risks.map((item, index) => (
              <article className="risk-card" key={`${index}-${item}`}>
                <AlertTriangle size={16} />
                <p>{item}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
      {brief.retry_count > 0 && <div className="alert warn">Evidence missed the quality threshold, so the evaluator sent the researcher back for a broader pass before writing.</div>}
      {brief.warnings.length > 0 && <div className="alert warn">{brief.warnings.join(" ")}</div>}
    </section>
  );
}

function BriefPreview() {
  return (
    <section className="card panel preview-panel" id="brief">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Brief Viewer</span>
          <h2>What appears after a run</h2>
        </div>
      </div>
      <div className="preview-grid">
        <article>
          <strong>Summary</strong>
          <span>A short company readout grounded only in accepted evidence.</span>
        </article>
        <article>
          <strong>Findings</strong>
          <span>Concrete signals the researcher found, not generic AI filler.</span>
        </article>
        <article>
          <strong>Risks</strong>
          <span>Gaps, weak evidence, or market concerns called out before you use the brief.</span>
        </article>
        <article>
          <strong>Receipts</strong>
          <span>Sources, relevance scores, node inputs, node outputs, and retry decisions.</span>
        </article>
      </div>
    </section>
  );
}
