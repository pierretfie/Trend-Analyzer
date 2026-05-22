import { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bot,
  ChevronDown,
  ChevronRight,
  Globe,
  Loader2,
  PlayCircle,
  RefreshCw,
  Square,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import { DataChart } from "./DataChart";
import { MermaidChart } from "./MermaidChart";
import type {
  Analysis,
  Prediction,
  Status,
  Trend,
  TrendReport,
  ModelSetup,
} from "../api";
import { api } from "../api";

interface OverviewProps {
  status: Status | null;
  onRefresh: () => void;
  busy: boolean;
  setBusy: (v: boolean) => void;
  notify: (t: "ok" | "err", m: string) => void;
}

function SignalBars() {
  return (
    <div className="flex items-end gap-[3px] h-8">
      {[0.4, 0.65, 1, 0.75, 0.5, 0.85, 0.6, 0.45, 0.9, 0.55].map((h, i) => (
        <div
          key={i}
          className="signal-bar w-1.5 rounded-sm bg-accent/60"
          style={{ height: `${h * 100}%`, animationDelay: `${i * 0.1}s` }}
        />
      ))}
    </div>
  );
}

const CATEGORY_COLORS: Record<string, string> = {
  general: "bg-slate-700/60 text-slate-300",
  energy: "bg-amber-900/40 text-amber-300 border border-amber-500/20",
  finance: "bg-emerald-900/40 text-emerald-300 border border-emerald-500/20",
  regulation: "bg-purple-900/40 text-purple-300 border border-purple-500/20",
  technology: "bg-blue-900/40 text-blue-300 border border-blue-500/20",
  logistics: "bg-cyan-900/40 text-cyan-300 border border-cyan-500/20",
  market: "bg-rose-900/40 text-rose-300 border border-rose-500/20",
};

function categoryClass(cat: string) {
  return CATEGORY_COLORS[cat.toLowerCase()] ?? CATEGORY_COLORS.general;
}

const CONFIDENCE_MAP = {
  high: {
    cls: "bg-accent/10 text-accent border border-accent/20",
    label: "High confidence",
  },
  medium: {
    cls: "bg-pulse/10 text-pulse border border-pulse/20",
    label: "Medium confidence",
  },
  low: {
    cls: "bg-slate-700/50 text-slate-400 border border-white/10",
    label: "Low confidence",
  },
};

function RelevanceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const color =
    pct >= 75 ? "bg-accent" : pct >= 40 ? "bg-pulse" : "bg-slate-600";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 rounded-full bg-white/[0.06]">
        <div
          className={`h-1 rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] font-mono text-slate-500 w-6 text-right">
        {pct}
      </span>
    </div>
  );
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Strip common markdown formatting the LLM emits into plain text. */
function stripMd(text: string): string {
  return (
    (text || "")
      // **bold** or __bold__
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/__(.+?)__/g, "$1")
      // *italic* or _italic_
      .replace(/\*(.+?)\*/g, "$1")
      .replace(/_(.+?)_/g, "$1")
      // `code`
      .replace(/`(.+?)`/g, "$1")
      // ### headings
      .replace(/^#{1,6}\s+/gm, "")
      // leading list markers: - item / * item / 1. item
      .replace(/^[\-\*]\s+/gm, "")
      .replace(/^\d+\.\s+/gm, "")
      .trim()
  );
}

function parseRecommendationItems(raw: string): string[] {
  const text = (raw || "").trim();
  if (!text) return [];
  const normalized = text.replace(/\r/g, "");
  const numbered = normalized
    .split(/\s(?=\d+\.\s)/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => s.replace(/^\d+\.\s*/, "").trim())
    .filter(Boolean);
  if (numbered.length > 1) return numbered;
  return normalized
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function Overview({
  status,
  onRefresh,
  busy,
  setBusy,
  notify,
}: OverviewProps) {
  const [trends, setTrends] = useState<Trend[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [latestReport, setLatestReport] = useState<TrendReport | null>(null);
  const [latestRunId, setLatestRunId] = useState<number | null>(null);
  const [thinkingLevel, setThinkingLevel] = useState(2);
  const [deepReadEnabled, setDeepReadEnabled] = useState(true);
  const [deepReadMaxArticles, setDeepReadMaxArticles] = useState(3);
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<"run" | "reload" | null>(
    null,
  );
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [runElapsedSec, setRunElapsedSec] = useState(0);
  const [runPhase, setRunPhase] = useState<"searching" | "thinking">(
    "thinking",
  );
  const [runQuery, setRunQuery] = useState<string | undefined>(undefined);
  const [runLogs, setRunLogs] = useState<string[]>([]);
  const [runSources, setRunSources] = useState<
    { title: string; link: string; snippet: string }[]
  >([]);
  const [runReading, setRunReading] = useState<
    {
      status: "started" | "completed" | "skipped";
      title: string;
      url: string;
      words?: number;
    }[]
  >([]);
  type RunTrace = {
    logs: string[];
    sources: { title: string; link: string; snippet: string }[];
    reading: {
      status: "started" | "completed" | "skipped";
      title: string;
      url: string;
      words?: number;
    }[];
    durationSec: number;
  };
  const TRACE_KEY = "ta_last_run_trace";
  function loadTrace(): RunTrace | null {
    try {
      const raw = localStorage.getItem(TRACE_KEY);
      return raw ? (JSON.parse(raw) as RunTrace) : null;
    } catch {
      return null;
    }
  }
  function saveTrace(t: RunTrace | null) {
    try {
      if (t === null) localStorage.removeItem(TRACE_KEY);
      else localStorage.setItem(TRACE_KEY, JSON.stringify(t));
    } catch {
      /* storage full — ignore */
    }
  }
  const [lastRunTrace, setLastRunTrace] = useState<RunTrace | null>(loadTrace);
  const [runTraceExpanded, setRunTraceExpanded] = useState(false);
  const [selectedTrend, setSelectedTrend] = useState<Trend | null>(null);
  const runAbortRef = useRef<AbortController | null>(null);
  const runLogBufferRef = useRef<string[]>([]);
  const runLogRafRef = useRef<number | null>(null);
  // Auto-scroll ref for the live log container
  const logScrollRef = useRef<HTMLDivElement | null>(null);

  function enqueueRunLog(line: string) {
    runLogBufferRef.current.push(line);
    if (runLogRafRef.current !== null) return;
    runLogRafRef.current = window.requestAnimationFrame(() => {
      const batch = runLogBufferRef.current;
      runLogBufferRef.current = [];
      runLogRafRef.current = null;
      if (batch.length) {
        setRunLogs((prev) => [...prev, ...batch]);
      }
    });
  }

  // Auto-scroll log container to bottom whenever new logs arrive during a run
  useEffect(() => {
    if (
      busy &&
      activeAction === "run" &&
      runTraceExpanded &&
      logScrollRef.current
    ) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [runLogs, busy, activeAction, runTraceExpanded]);

  async function loadFeed(retries = 2) {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const runs = await api.listRuns(1);
        const latest = runs[0]?.id ?? null;
        setLatestRunId(latest);
        const trendsRaw = await api.listTrends(20);
        const analysesRaw = await api.listAnalyses(20);
        const predictionsRaw = await api.listPredictions(20);
        const reportsRaw = await api.listTrendReports(1);
        setLatestReport(reportsRaw[0] ?? null);

        // Always show the most recent rows. When a run ID is available,
        // prefer rows from that run; fall back to the latest N rows so the
        // page is never blank after a successful run.
        const filterByRun = <T extends { run_id: number | null }>(
          rows: T[],
        ) => {
          if (latest != null) {
            const matched = rows.filter(
              (r) => Number(r.run_id) === Number(latest),
            );
            if (matched.length > 0) return matched;
          }
          return rows.slice(0, 8);
        };

        setTrends(filterByRun(trendsRaw));
        setAnalyses(filterByRun(analysesRaw));
        setPredictions(filterByRun(predictionsRaw));
        return; // success — stop retrying
      } catch {
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
        }
      }
    }
  }

  useEffect(() => {
    void loadFeed();
    const iv = setInterval(() => void loadFeed(), 30000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const s = await api.getModelSetup();
        setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? 2)));
        setDeepReadEnabled(Boolean(s.deep_read_enabled ?? true));
        setDeepReadMaxArticles(
          Math.max(1, Math.min(8, s.deep_read_max_articles ?? 3)),
        );
        // Determine which provider is active
        const pref = s.llm_provider;
        if (pref === "openai" && s.openai_configured)
          setActiveProvider("openai");
        else if (pref === "gemini" && s.gemini_configured)
          setActiveProvider("gemini");
        else if (pref === "local" && s.local_model_path)
          setActiveProvider("local");
        else if (s.openai_configured) setActiveProvider("openai");
        else if (s.gemini_configured) setActiveProvider("gemini");
        else if (s.local_model_path) setActiveProvider("local");
        else setActiveProvider("none");
      } catch {
        setThinkingLevel(2);
        setDeepReadEnabled(true);
        setDeepReadMaxArticles(3);
      }
    })();
  }, []);

  useEffect(() => {
    if (busy && activeAction === "run" && runStartedAt) {
      const tick = window.setInterval(() => {
        setRunElapsedSec(Math.max(0, (Date.now() - runStartedAt) / 1000));
      }, 1000);
      return () => window.clearInterval(tick);
    }
    setRunElapsedSec(0);
    return undefined;
  }, [busy, activeAction, runStartedAt]);

  const estimatedSeconds = Math.max(
    20,
    Math.round(
      25 + thinkingLevel * 18 + (deepReadEnabled ? deepReadMaxArticles * 6 : 0),
    ),
  );
  const remainingSeconds = Math.max(
    0,
    estimatedSeconds - Math.round(runElapsedSec),
  );
  const progressPct = Math.min(
    100,
    Math.round((runElapsedSec / estimatedSeconds) * 100),
  );

  async function reloadSched() {
    setBusy(true);
    setActiveAction("reload");
    try {
      const r = await api.reloadScheduler();
      notify(
        "ok",
        `Scheduler reloaded — ${r.scheduler_jobs} cron job(s) active.`,
      );
      onRefresh();
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Reload failed.");
    }
    setBusy(false);
    setActiveAction(null);
  }

  async function runNow() {
    const startedAt = Date.now();
    setBusy(true);
    setActiveAction("run");
    setRunStartedAt(startedAt);
    setRunPhase("thinking");
    setRunQuery(undefined);
    setRunLogs(["Starting research pass..."]);
    runLogBufferRef.current = [];
    if (runLogRafRef.current !== null) {
      window.cancelAnimationFrame(runLogRafRef.current);
      runLogRafRef.current = null;
    }
    setRunSources([]);
    setRunReading([]);
    setLastRunTrace(null);
    saveTrace(null);
    // Auto-expand the trace panel when a run starts so logs stream visibly
    setRunTraceExpanded(true);
    runAbortRef.current = new AbortController();
    const traceLogs: string[] = ["Starting research pass..."];
    const traceSources: { title: string; link: string; snippet: string }[] = [];
    const traceReading: {
      status: "started" | "completed" | "skipped";
      title: string;
      url: string;
      words?: number;
    }[] = [];
    try {
      await api.runOnceStream(
        { thinking_level: thinkingLevel },
        {
          onStatus: (phase, query, _message) => {
            // Only update phase/query state here.
            // The same message is already forwarded as a `process` event
            // by api_routes.py progress_cb, so logging it here would duplicate it.
            setRunPhase(phase);
            setRunQuery(query);
          },
          onProcess: (message, phase) => {
            if (phase === "reading") setRunPhase("thinking");
            if (!message) return;
            traceLogs.push(message);
            enqueueRunLog(message);
          },
          onSources: (results) => {
            traceSources.push(...results);
            setRunSources((prev) => {
              const seen = new Set(prev.map((r) => r.link));
              const fresh = results.filter((r) => r.link && !seen.has(r.link));
              return [...prev, ...fresh];
            });
          },
          onReading: (meta) => {
            const title = String(meta.title || "").trim();
            const url = String(meta.url || "").trim();
            if (url) {
              const item = {
                status: meta.status,
                title,
                url,
                words: meta.words,
              };
              traceReading.push(item);
              setRunReading((prev) => [...prev, item]);
            }
          },
          onDone: (summary) => {
            notify("ok", summary);
            const trace = {
              logs: traceLogs,
              sources: traceSources,
              reading: traceReading,
              durationSec: Math.max(0, (Date.now() - startedAt) / 1000),
            };
            setLastRunTrace(trace);
            saveTrace(trace);
            setRunTraceExpanded(false);
          },
          onError: (msg) => {
            notify("err", msg);
            setRunTraceExpanded(false);
          },
        },
        runAbortRef.current.signal,
      );
      // Stream finished — reload feed then update status bar.
      await loadFeed();
      onRefresh();
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Run failed.");
      setRunTraceExpanded(false);
    }
    runAbortRef.current = null;
    setBusy(false);
    setActiveAction(null);
    setRunStartedAt(null);
  }

  function cancelRunNow() {
    if (!runAbortRef.current) return;
    runAbortRef.current.abort();
    runAbortRef.current = null;
    setBusy(false);
    setActiveAction(null);
    setRunStartedAt(null);
    setRunTraceExpanded(false);
    notify("ok", "Research run cancelled.");
  }

  async function updateThinkingLevel(next: number) {
    const clamped = Math.max(1, Math.min(5, next));
    setThinkingLevel(clamped);
    try {
      const s = await api.patchModelSetup({ thinking_level: clamped });
      setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? clamped)));
      notify("ok", `Default thinking level set to L${clamped}.`);
    } catch {
      notify("err", "Failed to save thinking level.");
    }
  }

  async function updateProvider(next: ModelSetup["llm_provider"]) {
    setActiveProvider(next);
    try {
      const s = await api.patchModelSetup({ llm_provider: next });
      setActiveProvider(s.llm_provider);
      notify("ok", `Global research model switched to ${next === "openai" ? "OpenAI" : next === "gemini" ? "Gemini" : next === "local" ? "Local" : "None"}.`);
    } catch {
      notify("err", "Failed to switch model.");
    }
  }

  async function updateDeepRead(
    enabled: boolean,
    maxArticles: number = deepReadMaxArticles,
  ) {
    const clamped = Math.max(1, Math.min(8, maxArticles));
    setDeepReadEnabled(enabled);
    setDeepReadMaxArticles(clamped);
    try {
      const s = await api.patchModelSetup({
        deep_read_enabled: enabled,
        deep_read_max_articles: clamped,
      });
      setDeepReadEnabled(Boolean(s.deep_read_enabled ?? enabled));
      setDeepReadMaxArticles(
        Math.max(1, Math.min(8, s.deep_read_max_articles ?? clamped)),
      );
      notify("ok", "Reading mode settings saved.");
    } catch {
      notify("err", "Failed to save Reading mode settings.");
    }
  }

  // Derive which data to show in the unified trace panel
  const isRunning = busy && activeAction === "run";
  const traceLogs = isRunning ? runLogs : (lastRunTrace?.logs ?? []);
  const traceSources = isRunning ? runSources : (lastRunTrace?.sources ?? []);
  const traceReading = isRunning ? runReading : (lastRunTrace?.reading ?? []);
  const showTracePanel = isRunning ? runLogs.length > 0 : !!lastRunTrace;

  return (
    <>
      <div className="mx-auto max-w-5xl space-y-8 animate-slide-in-up">
        {/* ── Hero ── */}
        <header className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-gradient-to-br from-accent/20 to-neural/10 border border-accent/15">
              <Zap size={20} className="text-accent" />
            </div>
            <div>
              <h1 className="font-display text-3xl font-bold text-gradient-accent">
                Command Center
              </h1>
              <p className="text-sm text-slate-400">
                Intelligence running for your business
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4 rounded-2xl border border-accent/10 bg-accent/[0.04] px-5 py-3">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                {status?.scheduler_running ? (
                  <>
                    <span className="absolute inline-flex h-full w-full rounded-full bg-accent opacity-75 animate-ping" />
                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
                  </>
                ) : (
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-slate-600" />
                )}
              </span>
              <span className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                {status?.scheduler_running
                  ? "Monitoring Active"
                  : "Daemon Idle"}
              </span>
            </div>
            <div className="h-4 w-px bg-white/10" />
            <SignalBars />
            <div className="h-4 w-px bg-white/10" />
            <span className="text-xs text-slate-500 font-mono">
              {new Date().toLocaleTimeString()}
            </span>
          </div>
        </header>

        {/* ── Stat card + Actions ── */}
        <div className="grid gap-4 sm:grid-cols-2">
          {status ? (
            <div className="glass-card group relative overflow-hidden rounded-2xl p-5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-glow">
              <div className="absolute inset-0 bg-gradient-to-br from-white/[0.02] to-transparent pointer-events-none" />
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.06] mb-3">
                <Activity size={18} className="text-accent" />
              </div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Active Cron Jobs
              </p>
              <p className="mt-1.5 font-display text-2xl font-bold text-white">
                {status.scheduler_jobs}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {status.scheduler_running ? "Scheduler running" : "Idle"}
              </p>
            </div>
          ) : (
            <div className="glass-card rounded-2xl p-5 text-sm text-slate-500">
              Connecting…
            </div>
          )}

          <div className="glass-card rounded-2xl p-5 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Quick Actions
              </p>
              <div className="ml-auto">
                <select
                  disabled={busy}
                  value={activeProvider || "none"}
                  onChange={(e) =>
                    void updateProvider(e.target.value as ModelSetup["llm_provider"])
                  }
                  className="rounded-lg border border-white/[0.10] bg-surface-800 px-2 py-1 text-[11px] text-slate-200 hover:border-white/[0.20] transition-all cursor-pointer focus:outline-none disabled:opacity-50"
                >
                  <option value="none">Auto</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                  <option value="local">Local</option>
                </select>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Research depth
                </span>
                <select
                  disabled={busy}
                  value={thinkingLevel}
                  onChange={(e) => {
                    void updateThinkingLevel(Number(e.target.value));
                  }}
                  className="ml-auto rounded-lg border border-accent/20 bg-surface-800 px-2 py-1 text-[11px] text-accent hover:border-accent/40 transition-all cursor-pointer focus:outline-none disabled:opacity-50"
                  title="Default research refinement iterations (persists)"
                >
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      L{n}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Deep read
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    void updateDeepRead(!deepReadEnabled);
                  }}
                  className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all ${
                    deepReadEnabled
                      ? "border-neural/30 bg-neural/10 text-neural"
                      : "border-white/10 bg-white/[0.04] text-slate-400"
                  }`}
                >
                  {deepReadEnabled ? "On" : "Off"}
                </button>
                <select
                  disabled={busy || !deepReadEnabled}
                  value={deepReadMaxArticles}
                  onChange={(e) => {
                    void updateDeepRead(
                      deepReadEnabled,
                      Number(e.target.value),
                    );
                  }}
                  className="ml-auto rounded-lg border border-neural/20 bg-surface-800 px-2 py-1 text-[11px] text-neural hover:border-neural/40 transition-all cursor-pointer focus:outline-none disabled:opacity-50"
                  title="How many top links to read fully per run"
                >
                  {[1, 2, 3, 4, 5, 6, 8].map((n) => (
                    <option key={n} value={n}>
                      {n}s
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void runNow()}
                className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-glow px-4 py-2.5 text-sm font-bold text-surface-900 shadow-glow-sm hover:shadow-glow disabled:opacity-50 transition-all"
              >
                <PlayCircle size={15} /> Run research now
              </button>
              {isRunning && (
                <button
                  type="button"
                  onClick={cancelRunNow}
                  className="btn-glow flex items-center justify-center gap-2 rounded-xl border border-danger/30 bg-danger/15 px-4 py-2 text-xs font-semibold text-danger hover:bg-danger/20 transition-all"
                >
                  <Square size={12} className="fill-current" /> Cancel run
                </button>
              )}

              {/* ── Progress bar (only while running) ── */}
              {isRunning && (
                <div className="rounded-xl border border-accent/20 bg-accent/[0.06] px-4 py-3 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-accent/80">
                      Research running
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">
                      {Math.floor(runElapsedSec)}s / ~{estimatedSeconds}s
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-white/[0.06] overflow-hidden">
                    <div
                      className="h-2 rounded-full bg-gradient-to-r from-accent to-neural transition-all duration-1000"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  <div
                    className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wider ${
                      runPhase === "searching"
                        ? "bg-amber-500/10 text-amber-500 border border-amber-500/20"
                        : "bg-accent/10 text-accent border border-accent/20"
                    }`}
                  >
                    {runPhase === "searching" ? (
                      <Globe size={12} className="animate-pulse" />
                    ) : (
                      <Loader2 size={12} className="animate-spin" />
                    )}
                    <span className="flex-1">
                      {runPhase === "searching"
                        ? `Search tool: ${runQuery || "Web"}`
                        : "Synthesizing research..."}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500">
                    ~{remainingSeconds}s remaining · reading mode{" "}
                    {deepReadEnabled
                      ? `on (${deepReadMaxArticles} picks)`
                      : "off"}
                  </p>
                </div>
              )}

              {/* ── Unified Model Process panel (live during run, static after) ── */}
              {showTracePanel && (
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 space-y-2">
                  <button
                    type="button"
                    onClick={() => setRunTraceExpanded((v) => !v)}
                    className="flex w-full items-center gap-2 text-left"
                  >
                    {runTraceExpanded ? (
                      <ChevronDown
                        size={14}
                        className="text-slate-400 shrink-0"
                      />
                    ) : (
                      <ChevronRight
                        size={14}
                        className="text-slate-400 shrink-0"
                      />
                    )}
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      Model process
                    </span>
                    <span className="ml-auto flex items-center gap-1.5 text-[10px] text-slate-500 shrink-0">
                      {isRunning && (
                        <Loader2
                          size={10}
                          className="animate-spin text-accent"
                        />
                      )}
                      {traceLogs.length} step(s) · {traceSources.length}{" "}
                      source(s)
                      {!isRunning && lastRunTrace
                        ? ` · ${lastRunTrace.durationSec.toFixed(1)}s`
                        : ""}
                    </span>
                  </button>

                  {runTraceExpanded && (
                    <div className="border-t border-white/[0.05] pt-3 space-y-3">
                      {/* Scrollable log stream */}
                      {traceLogs.length > 0 && (
                        <div
                          ref={logScrollRef}
                          className="max-h-48 overflow-y-auto space-y-1 pr-1 scrollbar-thin"
                        >
                          {traceLogs.map((log, i) => (
                            <div
                              key={`${i}-${log.slice(0, 20)}`}
                              className="text-[11px] text-slate-400 break-words leading-relaxed"
                            >
                              {log}
                            </div>
                          ))}
                          {/* Blinking cursor while streaming */}
                          {isRunning && (
                            <div className="flex items-center gap-1 pt-0.5">
                              <span className="h-1 w-1 rounded-full bg-accent animate-pulse" />
                              <span className="h-1 w-1 rounded-full bg-accent animate-pulse [animation-delay:150ms]" />
                              <span className="h-1 w-1 rounded-full bg-accent animate-pulse [animation-delay:300ms]" />
                            </div>
                          )}
                        </div>
                      )}

                      {/* Sources */}
                      {traceSources.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                            Sources discovered
                          </p>
                          {traceSources.map((s, i) => (
                            <a
                              key={`${s.link}-${i}`}
                              href={s.link}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-1 text-[11px] text-slate-300 hover:text-accent transition-colors"
                            >
                              <Globe
                                size={11}
                                className="text-slate-500 shrink-0"
                              />
                              <span className="truncate">
                                {s.title || s.link}
                              </span>
                              <ChevronRight
                                size={10}
                                className="ml-auto text-slate-600 shrink-0"
                              />
                            </a>
                          ))}
                        </div>
                      )}

                      {/* Reading */}
                      {traceReading.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                            Reading mode
                          </p>
                          {traceReading.map((r, i) => (
                            <div
                              key={`${r.url}-${i}`}
                              className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-1 text-[11px] text-slate-300"
                            >
                              <div className="flex items-center gap-2">
                                <span
                                  className={`h-1.5 w-1.5 rounded-full shrink-0 transition-colors ${
                                    r.status === "completed"
                                      ? "bg-accent"
                                      : r.status === "started"
                                        ? "bg-amber-400 animate-pulse"
                                        : "bg-slate-500"
                                  }`}
                                />
                                <span className="truncate">
                                  {r.title || r.url}
                                </span>
                              </div>
                              <p className="truncate text-[10px] text-slate-500 pl-3.5">
                                {r.url}
                                {r.words ? ` • ${r.words} words` : ""}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void reloadSched()}
                  className="btn-glow flex flex-1 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-slate-300 hover:bg-white/[0.08] disabled:opacity-50 transition"
                >
                  <RefreshCw size={12} className={busy ? "animate-spin" : ""} />{" "}
                  Reload scheduler
                </button>
                <button
                  type="button"
                  onClick={onRefresh}
                  className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium text-slate-500 hover:text-accent transition"
                >
                  <RefreshCw size={12} /> Refresh
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ── Strategic Visualization ── */}
        {latestReport?.visualisation && (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap size={16} className="text-accent" />
                <h2 className="text-sm font-bold text-white">
                  Strategic Intelligence Visual
                </h2>
              </div>
              <span className="text-[11px] text-slate-600">
                From latest report #{latestReport.id}
              </span>
            </div>
            <div className="glass-card rounded-2xl p-6">
              {(() => {
                const raw = latestReport.visualisation.trim();
                let visType: "mermaid" | "json" | null = null;
                let visCode = "";

                // Chart-type keywords that mean the content is a JSON chart
                // config, not a Mermaid diagram.
                const JSON_CHART_TYPES = new Set([
                  "bar",
                  "line",
                  "area",
                  "pie",
                  "doughnut",
                ]);
                const MERMAID_KEYWORDS = [
                  "graph",
                  "flowchart",
                  "sequencediagram",
                  "gantt",
                  "erdiagram",
                  "statediagram",
                  "journey",
                  "classdiagram",
                  "gitgraph",
                  "mindmap",
                  "timeline",
                  "xychart",
                ];

                const looksLikeJsonChart = (code: string) => {
                  const c = code.trim();
                  if (!c.startsWith("{") && !c.startsWith("[")) return false;
                  try {
                    const p = JSON.parse(c);
                    return (
                      p &&
                      typeof p === "object" &&
                      JSON_CHART_TYPES.has(String(p.type))
                    );
                  } catch {
                    return false;
                  }
                };

                const looksLikeMermaid = (code: string) => {
                  const first =
                    code.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
                  return MERMAID_KEYWORDS.some((k) => first.startsWith(k));
                };

                try {
                  const parsed = JSON.parse(raw);
                  if (parsed && typeof parsed.code === "string") {
                    // Model returned the expected wrapper: {type, code}
                    // But don't trust parsed.type blindly — inspect the code itself.
                    const code = parsed.code.trim();
                    if (looksLikeJsonChart(code)) {
                      visType = "json";
                    } else if (parsed.type === "json") {
                      visType = "json";
                    } else {
                      visType = "mermaid";
                    }
                    visCode = code;
                  } else if (
                    parsed &&
                    JSON_CHART_TYPES.has(String(parsed.type))
                  ) {
                    // Model returned chart JSON directly without wrapper
                    visType = "json";
                    visCode = raw;
                  }
                } catch {
                  // raw is not JSON — try to detect Mermaid by first keyword
                  if (looksLikeMermaid(raw)) {
                    visType = "mermaid";
                    visCode = raw;
                  } else if (raw.startsWith("{") || raw.startsWith("[")) {
                    visType = "json";
                    visCode = raw;
                  }
                }

                if (!visType || !visCode)
                  return (
                    <p className="text-sm text-slate-500 text-center py-4">
                      Visual data formatting in progress or unavailable.
                    </p>
                  );
                return visType === "mermaid" ? (
                  <MermaidChart code={visCode} />
                ) : (
                  <DataChart code={visCode} />
                );
              })()}
            </div>
          </section>
        )}

        {/* ── Recent Trends ── */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp size={16} className="text-accent" />
              <h2 className="text-sm font-bold text-white">
                Recent Trends Discovered
              </h2>
            </div>
            <span className="text-[11px] text-slate-600">
              {trends.length} found{" "}
              {latestRunId ? `for run #${latestRunId}` : ""}
            </span>
          </div>

          {trends.length === 0 ? (
            <div className="glass-card rounded-2xl px-6 py-10 flex flex-col items-center gap-3 text-center">
              <TrendingUp size={28} className="text-slate-700" />
              <p className="text-sm text-slate-500">No trends recorded yet.</p>
              <p className="text-xs text-slate-600">
                Run research to start discovering business-relevant signals.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {trends.map((t) => (
                <div
                  key={t.id}
                  onClick={() => setSelectedTrend(t)}
                  className="glass-card group rounded-2xl p-4 space-y-2.5 transition-all hover:-translate-y-0.5 hover:shadow-glow cursor-pointer"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${categoryClass(t.category)}`}
                    >
                      {t.category}
                    </span>
                    <span className="text-[10px] text-slate-600 font-mono shrink-0">
                      {timeAgo(t.discovered_at)}
                    </span>
                  </div>
                  <p className="text-sm font-semibold text-white leading-snug text-balance break-words">
                    {stripMd(t.title)}
                  </p>
                  {t.summary && (
                    <div className="space-y-1">
                      <p className="text-xs text-slate-400 leading-relaxed line-clamp-2">
                        {stripMd(t.summary)}
                      </p>
                      <span className="text-[10px] text-accent/60 group-hover:text-accent transition">
                        Read more &rarr;
                      </span>
                    </div>
                  )}
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
                      Relevance
                    </span>
                    <RelevanceBar value={t.relevance} />
                  </div>
                  {t.source_url && (
                    <a
                      href={t.source_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 text-[11px] text-accent/70 hover:text-accent transition"
                    >
                      Source <ArrowUpRight size={10} />
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── AI Analyses ── */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot size={16} className="text-neural" />
              <h2 className="text-sm font-bold text-white">
                Recent AI Analysis & Advice
              </h2>
            </div>
            <span className="text-[11px] text-slate-600">
              {analyses.length} insights{" "}
              {latestRunId ? `for run #${latestRunId}` : ""}
            </span>
          </div>

          {analyses.length === 0 ? (
            <div className="glass-card rounded-2xl px-6 py-10 flex flex-col items-center gap-3 text-center">
              <Bot size={28} className="text-slate-700" />
              <p className="text-sm text-slate-500">No AI advice yet.</p>
              <p className="text-xs text-slate-600">
                The agent will post insights here after each research pass.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {analyses.map((a) => {
                const conf =
                  CONFIDENCE_MAP[a.confidence] ?? CONFIDENCE_MAP.medium;
                return (
                  <div
                    key={a.id}
                    className="glass-card rounded-2xl p-5 space-y-3 transition-all hover:shadow-glow-neural"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${conf.cls}`}
                      >
                        <AlertTriangle size={9} /> {conf.label}
                      </span>
                      {a.trend_title && (
                        <span className="text-[11px] text-slate-500">
                          re:{" "}
                          <span className="text-slate-400 font-medium">
                            {stripMd(a.trend_title)}
                          </span>
                        </span>
                      )}
                      <span className="ml-auto text-[10px] text-slate-600 font-mono">
                        {timeAgo(a.created_at)}
                      </span>
                    </div>
                    <p className="text-sm font-bold text-white leading-snug">
                      {stripMd(a.headline)}
                    </p>
                    {a.recommendation && (
                      <div className="rounded-xl border border-neural/15 bg-neural/[0.05] px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-neural/60 mb-1">
                          Recommendation
                        </p>
                        {(() => {
                          const items = parseRecommendationItems(
                            a.recommendation,
                          ).map(stripMd);
                          if (items.length <= 1) {
                            return (
                              <p className="text-sm text-slate-200 leading-relaxed">
                                {stripMd(a.recommendation)}
                              </p>
                            );
                          }
                          return (
                            <ol className="list-decimal pl-5 space-y-1 text-sm text-slate-200 leading-relaxed">
                              {items.map((item, idx) => (
                                <li key={idx}>{item}</li>
                              ))}
                            </ol>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* ── Predictions ── */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot size={16} className="text-pulse" />
              <h2 className="text-sm font-bold text-white">AI Predictions</h2>
            </div>
            <span className="text-[11px] text-slate-600">
              {predictions.length} forecast(s){" "}
              {latestRunId ? `for run #${latestRunId}` : ""}
            </span>
          </div>
          {predictions.length === 0 ? (
            <div className="glass-card rounded-2xl px-6 py-10 flex flex-col items-center gap-3 text-center">
              <Bot size={28} className="text-slate-700" />
              <p className="text-sm text-slate-500">No predictions yet.</p>
              <p className="text-xs text-slate-600">
                Run research to generate horizon-based forecasts.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {predictions.map((p) => {
                const conf =
                  CONFIDENCE_MAP[p.confidence] ?? CONFIDENCE_MAP.medium;
                return (
                  <div
                    key={p.id}
                    className="glass-card rounded-2xl p-5 space-y-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${conf.cls}`}
                      >
                        {conf.label}
                      </span>
                      <span className="text-[11px] text-accent/80 font-semibold uppercase tracking-wider">
                        {p.horizon_value} {p.horizon_unit}
                      </span>
                      <span className="text-[11px] text-slate-500">
                        target {new Date(p.target_date).toLocaleDateString()}
                      </span>
                      <span className="ml-auto text-[10px] text-slate-600 font-mono">
                        {timeAgo(p.created_at)}
                      </span>
                    </div>
                    <p className="text-sm font-bold text-white leading-snug">
                      {stripMd(p.prediction_text)}
                    </p>
                    {p.rationale && (
                      <p className="text-xs text-slate-400 leading-relaxed">
                        {stripMd(p.rationale)}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* ── Trend Detail Modal ── */}
      {selectedTrend && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          onClick={() => setSelectedTrend(null)}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

          {/* Modal card */}
          <div
            className="relative z-10 glass-card rounded-2xl p-6 max-w-lg w-full space-y-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${categoryClass(selectedTrend.category)}`}
                >
                  {selectedTrend.category}
                </span>
                <span className="text-[10px] text-slate-500 font-mono">
                  {timeAgo(selectedTrend.discovered_at)}
                </span>
              </div>
              <button
                onClick={() => setSelectedTrend(null)}
                className="shrink-0 rounded-full p-1 text-slate-500 hover:text-white hover:bg-white/10 transition"
              >
                <X size={16} />
              </button>
            </div>

            {/* Title */}
            <p className="text-sm font-semibold text-white leading-snug">
              {stripMd(selectedTrend.title)}
            </p>

            {/* Full summary */}
            {selectedTrend.summary && (
              <p className="text-xs text-slate-300 leading-relaxed">
                {stripMd(selectedTrend.summary)}
              </p>
            )}

            {/* Relevance */}
            <div className="space-y-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
                Relevance
              </span>
              <RelevanceBar value={selectedTrend.relevance} />
            </div>

            {/* Source link */}
            {selectedTrend.source_url && (
              <a
                href={selectedTrend.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] text-accent/70 hover:text-accent transition"
              >
                Source <ArrowUpRight size={10} />
              </a>
            )}
          </div>
        </div>
      )}
    </>
  );
}
