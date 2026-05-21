async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = (await r.json()) as { detail?: string | unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export type Status = {
  db_path: string;
  data_dir: string;
  scheduler_running: boolean;
  scheduler_jobs: number;
};

export type Schedule = {
  id: number;
  enabled: boolean;
  label: string | null;
  frequency: "hourly" | "daily" | "weekly" | "once";
  weekdays: number[];
  time_points: string[];
  timezone: string;
  last_run_status?: string | null;
  last_run_at?: string | null;
  last_run_summary?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type Run = {
  id: number;
  schedule_id: number | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  summary: string | null;
};

export type ModelSetup = {
  llm_provider: "none" | "openai" | "gemini" | "local";
  openai_configured: boolean;
  openai_masked: string | null;
  gemini_configured: boolean;
  gemini_masked: string | null;
  gemini_model: string;
  google_configured: boolean;
  google_masked: string | null;
  google_cx: string;
  google_search_enabled: boolean;
  serpapi_configured: boolean;
  serpapi_masked: string | null;
  serpapi_engine: string;
  serpapi_search_enabled: boolean;
  firecrawl_configured: boolean;
  firecrawl_masked: string | null;
  firecrawl_search_enabled: boolean;
  ddg_search_enabled: boolean;
  ddg_region: string;
  ddg_timelimit: string;
  thinking_level: number;
  deep_read_enabled: boolean;
  deep_read_max_articles: number;
  local_model_path: string;
  local_n_ctx: number;
  local_n_gpu_layers: number;
};

export type TrendReport = {
  id: number;
  timestamp: string;
  query_used: string;
  summary: string;
  trend_signals: string[];
  recommended_actions: string[];
  severity: "low" | "medium" | "high" | "critical";
  sources: string[];
  visualisation: string;
  provider_used: string;
  run_id: number | null;
  created_at: string;
};

export type Trend = {
  id: number;
  run_id: number | null;
  title: string;
  summary: string;
  category: string;
  source_url: string | null;
  relevance: number;
  discovered_at: string;
};

export type Analysis = {
  id: number;
  run_id: number | null;
  trend_id: number | null;
  trend_title: string | null;
  headline: string;
  recommendation: string;
  confidence: "low" | "medium" | "high";
  created_at: string;
};

export type Prediction = {
  id: number;
  run_id: number | null;
  prediction_text: string;
  horizon_value: number;
  horizon_unit: "days" | "weeks" | "months" | "years";
  target_date: string;
  confidence: "low" | "medium" | "high";
  rationale: string;
  status: "open" | "resolved" | "expired";
  resolution_note: string;
  sources: string[];
  created_at: string;
};

export type ChatSession = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export const api = {
  status: () => fetchJson<Status>("/api/status"),
  reloadScheduler: () =>
    fetchJson<{ scheduler_jobs: number }>("/api/scheduler/reload", {
      method: "POST",
    }),
  runOnce: (schedule_id?: number, thinking_level?: number) =>
    fetchJson<{ summary: string }>("/api/research/run-once", {
      method: "POST",
      body: JSON.stringify({
        schedule_id: schedule_id ?? null,
        thinking_level: thinking_level ?? null,
      }),
    }),
  runOnceStream: async (
    body: { schedule_id?: number; thinking_level?: number },
    callbacks: {
      onStatus: (
        phase: "searching" | "thinking",
        query?: string,
        message?: string,
      ) => void;
      onProcess?: (
        message: string,
        phase?: "searching" | "thinking" | "reading",
        seq?: number,
      ) => void;
      onSources?: (
        results: { title: string; link: string; snippet: string }[],
      ) => void;
      onReading?: (meta: {
        phase: "reading";
        status: "started" | "completed" | "skipped";
        title?: string;
        url?: string;
        chars?: number;
        words?: number;
      }) => void;
      onDone: (summary: string) => void;
      onError: (msg: string) => void;
    },
    signal?: AbortSignal,
  ): Promise<void> => {
    let res: Response;
    try {
      res = await fetch("/api/research/run-once/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schedule_id: body.schedule_id ?? null,
          thinking_level: body.thinking_level ?? null,
        }),
        signal,
      });
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        callbacks.onError("Aborted by user");
        return;
      }
      callbacks.onError(e instanceof Error ? e.message : "Network error");
      return;
    }
    if (!res.ok || !res.body) {
      let detail = res.statusText;
      try {
        const j = (await res.json()) as { detail?: unknown };
        if (typeof j.detail === "string") {
          detail = j.detail;
        } else if (Array.isArray(j.detail) && j.detail.length > 0) {
          const first = j.detail[0] as { msg?: string } | string;
          detail =
            typeof first === "string"
              ? first
              : (first?.msg ?? `Validation error (HTTP ${res.status})`);
        }
      } catch {
        /* ignore */
      }
      callbacks.onError(detail || `HTTP ${res.status}`);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const chunks = buf.split("\n\n");
      buf = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const lines = chunk.split("\n");
        let evtType = "";
        let evtData = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) evtType = line.slice(7).trim();
          else if (line.startsWith("data: ")) evtData = line.slice(6).trim();
        }
        if (!evtType || !evtData) continue;
        try {
          const payload = JSON.parse(evtData);
          if (evtType === "status")
            callbacks.onStatus(
              payload.phase as "searching" | "thinking",
              payload.query,
              payload.message,
            );
          else if (evtType === "process")
            callbacks.onProcess?.(
              payload.message ?? "",
              payload.phase as "searching" | "thinking" | "reading",
              payload.seq as number,
            );
          else if (evtType === "sources")
            callbacks.onSources?.(payload.results);
          else if (evtType === "reading") callbacks.onReading?.(payload);
          else if (evtType === "done")
            callbacks.onDone(payload.summary ?? "Analysis complete.");
          else if (evtType === "error")
            callbacks.onError(payload.detail ?? "Unknown error");
        } catch {
          /* ignore malformed */
        }
      }
    }
  },
  listSchedules: () => fetchJson<Schedule[]>("/api/schedules"),
  createSchedule: (body: {
    frequency: "hourly" | "daily" | "weekly" | "once";
    time_points: string[];
    weekdays?: number[];
    label?: string;
    timezone?: string;
    enabled?: boolean;
  }) =>
    fetchJson<Schedule>("/api/schedules", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchSchedule: (
    id: number,
    body: Partial<
      Pick<
        Schedule,
        | "enabled"
        | "frequency"
        | "time_points"
        | "weekdays"
        | "timezone"
        | "label"
      >
    >,
  ) =>
    fetchJson<Schedule>(`/api/schedules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteSchedule: (id: number) =>
    fetchJson<{ ok: string }>(`/api/schedules/${id}`, { method: "DELETE" }),
  getCompany: () =>
    fetchJson<{
      name: string | null;
      sector: string | null;
      region: string | null;
      products: string | null;
      notes: string | null;
      updated_at: string;
    }>("/api/company"),
  patchCompany: (
    body: Partial<{
      name: string;
      sector: string;
      region: string;
      products: string;
      notes: string;
    }>,
  ) =>
    fetchJson("/api/company", { method: "PATCH", body: JSON.stringify(body) }),
  getInstructions: () => fetchJson<{ body: string }>("/api/instructions"),
  putInstructions: (body: string) =>
    fetchJson("/api/instructions", {
      method: "PUT",
      body: JSON.stringify({ body }),
    }),
  listRuns: (limit = 40) => fetchJson<Run[]>(`/api/runs?limit=${limit}`),
  deleteRun: (id: number) =>
    fetchJson<{ ok: string }>(`/api/runs/${id}`, { method: "DELETE" }),
  getModelSetup: () => fetchJson<ModelSetup>("/api/model-setup"),
  patchModelSetup: (body: {
    llm_provider?: "none" | "openai" | "gemini" | "local";
    openai_api_key?: string | null;
    gemini_api_key?: string | null;
    gemini_model?: string;
    google_api_key?: string | null;
    google_cx?: string | null;
    google_search_enabled?: boolean;
    serpapi_api_key?: string | null;
    serpapi_engine?: string;
    serpapi_search_enabled?: boolean;
    firecrawl_api_key?: string | null;
    firecrawl_search_enabled?: boolean;
    ddg_search_enabled?: boolean;
    ddg_region?: string;
    ddg_timelimit?: string;
    thinking_level?: number;
    deep_read_enabled?: boolean;
    deep_read_max_articles?: number;
    local_model_path?: string;
    local_n_ctx?: number;
    local_n_gpu_layers?: number;
  }) =>
    fetchJson<ModelSetup>("/api/model-setup", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  chat: (body: {
    messages: { role: "user" | "assistant"; content: string }[];
    mode?: "chat" | "analysis" | "search";
    provider?: "auto" | "openai" | "gemini" | "local";
    session_id?: number;
    thinking_level?: number;
  }) =>
    fetchJson<{ reply: string; html: string; provider: "openai" | "gemini" }>(
      "/api/chat",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  chatStream: async (
    body: {
      messages: { role: "user" | "assistant"; content: string }[];
      mode?: "chat" | "analysis" | "search";
      provider?: "auto" | "openai" | "gemini" | "local";
      session_id?: number;
      thinking_level?: number;
    },
    callbacks: {
      onStatus: (
        phase: "searching" | "thinking",
        query?: string,
        message?: string,
      ) => void;
      onProcess?: (
        message: string,
        phase?: "searching" | "thinking" | "reading",
        seq?: number,
      ) => void;
      onSources?: (
        results: { title: string; link: string; snippet: string }[],
      ) => void;
      onReading?: (meta: {
        phase: "reading";
        status: "started" | "completed" | "skipped";
        title?: string;
        url?: string;
        chars?: number;
        words?: number;
      }) => void;
      onToken?: (text: string) => void;
      onDone: (
        reply: string,
        html: string,
        provider: "openai" | "gemini" | "local",
      ) => void;
      onError: (msg: string) => void;
    },
    signal?: AbortSignal,
  ): Promise<void> => {
    let res: Response;
    try {
      res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        callbacks.onError("Aborted by user");
        return;
      }
      callbacks.onError(e instanceof Error ? e.message : "Network error");
      return;
    }
    if (!res.ok || !res.body) {
      let detail = res.statusText;
      try {
        const j = (await res.json()) as { detail?: unknown };
        if (typeof j.detail === "string") {
          detail = j.detail;
        } else if (Array.isArray(j.detail) && j.detail.length > 0) {
          // Pydantic v2 returns detail as an array of {type,loc,msg,input,ctx}
          const first = j.detail[0] as { msg?: string } | string;
          detail =
            typeof first === "string"
              ? first
              : (first?.msg ?? `Validation error (HTTP ${res.status})`);
        }
      } catch {
        /* ignore */
      }
      callbacks.onError(detail || `HTTP ${res.status}`);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const chunks = buf.split("\n\n");
      buf = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const lines = chunk.split("\n");
        let evtType = "";
        let evtData = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) evtType = line.slice(7).trim();
          else if (line.startsWith("data: ")) evtData = line.slice(6).trim();
        }
        if (!evtType || !evtData) continue;
        try {
          const payload = JSON.parse(evtData);
          if (evtType === "status")
            callbacks.onStatus(
              payload.phase as "searching" | "thinking",
              payload.query,
              payload.message,
            );
          else if (evtType === "process")
            callbacks.onProcess?.(
              payload.message ?? "",
              payload.phase as "searching" | "thinking" | "reading",
              payload.seq as number,
            );
          else if (evtType === "sources")
            callbacks.onSources?.(payload.results);
          else if (evtType === "reading") callbacks.onReading?.(payload);
          else if (evtType === "token") callbacks.onToken?.(payload.text ?? "");
          else if (evtType === "done")
            callbacks.onDone(
              payload.reply,
              payload.html ?? "",
              payload.provider as "openai" | "gemini" | "local",
            );
          else if (evtType === "error")
            callbacks.onError(
              typeof payload.detail === "string"
                ? payload.detail
                : "Unknown error",
            );
        } catch {
          /* ignore malformed */
        }
      }
    }
  },
  listChatSessions: () => fetchJson<ChatSession[]>("/api/chat/sessions"),
  createChatSession: () =>
    fetchJson<ChatSession>("/api/chat/sessions", { method: "POST" }),
  getChatMessages: (sessionId: number) =>
    fetchJson<{ role: "user" | "assistant"; content: string }[]>(
      `/api/chat/sessions/${sessionId}/messages`,
    ),
  deleteChatSession: (sessionId: number) =>
    fetchJson<{ ok: string }>(`/api/chat/sessions/${sessionId}`, {
      method: "DELETE",
    }),
  listTrends: (limit = 8) => fetchJson<Trend[]>(`/api/trends?limit=${limit}`),
  deleteTrend: (id: number) =>
    fetchJson<{ ok: string }>(`/api/trends/${id}`, { method: "DELETE" }),
  listAnalyses: (limit = 8) =>
    fetchJson<Analysis[]>(`/api/analyses?limit=${limit}`),
  deleteAnalysis: (id: number) =>
    fetchJson<{ ok: string }>(`/api/analyses/${id}`, { method: "DELETE" }),
  listPredictions: (limit = 8) =>
    fetchJson<Prediction[]>(`/api/predictions?limit=${limit}`),
  deletePrediction: (id: number) =>
    fetchJson<{ ok: string }>(`/api/predictions/${id}`, { method: "DELETE" }),
  listTrendReports: (limit = 100, severity?: string) =>
    fetchJson<TrendReport[]>(
      `/api/trend-reports?limit=${limit}${severity ? `&severity=${severity}` : ""}`,
    ),
  getTrendReport: (id: number) =>
    fetchJson<TrendReport>(`/api/trend-reports/${id}`),
  deleteTrendReport: (id: number) =>
    fetchJson<{ ok: string }>(`/api/trend-reports/${id}`, { method: "DELETE" }),
  listLocalModels: (directory?: string) =>
    fetchJson<{
      directory: string;
      models: { name: string; path: string; size_mb: number }[];
    }>(
      `/api/local-models${directory ? `?directory=${encodeURIComponent(directory)}` : ""}`,
    ),
};
