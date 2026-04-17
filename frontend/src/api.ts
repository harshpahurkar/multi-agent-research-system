export type Health = {
  status: string;
  provider: string;
  cache_backend: string;
  job_backend: string;
  offline_default: boolean;
};

export type RunEvent = {
  node: string;
  event: string;
  payload: Record<string, unknown>;
  timestamp?: string;
};

export type ResearchBrief = {
  company: string;
  focus: string;
  summary: string;
  findings: string[];
  risks: string[];
  sources: string[];
  warnings: string[];
  quality_score: number;
  retry_count: number;
  events: RunEvent[];
};

export type RunSyncResponse = {
  result: ResearchBrief;
  events: RunEvent[];
  cache_hit: boolean;
};

export type JobRecord = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  request: { company: string; focus: string; max_retries: number };
  result: ResearchBrief | null;
  events: RunEvent[];
  error?: string | null;
};

export type JobCreateResponse = {
  job_id: string;
  status: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const body = await response.text();
    let parsed: { detail?: unknown; error?: unknown } | null = null;
    try {
      parsed = JSON.parse(body) as { detail?: unknown; error?: unknown };
    } catch {
      parsed = null;
    }
    const detail = parsed?.detail ?? parsed?.error;
    if (typeof detail === "string") {
      throw new Error(detail);
    }
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => JSON.stringify(item)).join("; "));
    }
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  runSync: (payload: { company: string; focus: string; max_retries: number }) =>
    request<RunSyncResponse>("/research/run-sync", { method: "POST", body: JSON.stringify(payload) }),
  createJob: (payload: { company: string; focus: string; max_retries: number }) =>
    request<JobCreateResponse>("/research/jobs", { method: "POST", body: JSON.stringify(payload) }),
  getJob: (jobId: string) => request<JobRecord>(`/research/jobs/${jobId}`),
  getEvents: (jobId: string) => request<{ job_id: string; events: RunEvent[] }>(`/research/jobs/${jobId}/events`)
};
