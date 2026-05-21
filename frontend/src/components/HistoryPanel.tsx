import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  ChevronDown,
  Clock4,
  RefreshCw,
  Trash2,
  TrendingUp,
} from "lucide-react";
import type { Analysis, Prediction, Run, Trend } from "../api";
import { api } from "../api";

function cn(...p: Array<string | false | undefined>) {
  return p.filter(Boolean).join(" ");
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

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function dayKey(iso: string) {
  return new Date(iso).toISOString().slice(0, 10);
}

function parseRecommendationItems(raw: string): string[] {
  const text = (raw || "").trim();
  if (!text) return [];
  const numbered = text
    .replace(/\r/g, "")
    .split(/\s(?=\d+\.\s)/)
    .map((s) => s.trim().replace(/^\d+\.\s*/, ""))
    .filter(Boolean);
  if (numbered.length > 1) return numbered;
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

type DateFilter = "7d" | "30d" | "90d" | "all";

export function HistoryPanel({
  notify,
}: {
  notify: (t: "ok" | "err", m: string) => void;
}) {
  const [trends, setTrends] = useState<Trend[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<DateFilter>("30d");
  const [openDays, setOpenDays] = useState<Record<string, boolean>>({});
  const [confirmDelete, setConfirmDelete] = useState<
    | { mode: "visible"; total: number }
    | { mode: "day"; day: string; total: number }
    | null
  >(null);

  async function reload() {
    try {
      setTrends(await api.listTrends(120));
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Failed trends load.");
    }
    try {
      setAnalyses(await api.listAnalyses(120));
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Failed analyses load.");
    }
    try {
      setPredictions(await api.listPredictions(120));
    } catch (e) {
      notify(
        "err",
        e instanceof Error ? e.message : "Failed predictions load.",
      );
    }
    try {
      setRuns(await api.listRuns(120));
    } catch {
      /* optional */
    }
    setLoading(false);
  }

  useEffect(() => {
    void reload();
  }, []);

  const cutoffMs = useMemo(() => {
    if (filter === "all") return 0;
    const days = filter === "7d" ? 7 : filter === "30d" ? 30 : 90;
    return Date.now() - days * 24 * 60 * 60 * 1000;
  }, [filter]);

  const visibleTrends = useMemo(
    () => trends.filter((t) => new Date(t.discovered_at).getTime() >= cutoffMs),
    [trends, cutoffMs],
  );
  const visibleAnalyses = useMemo(
    () => analyses.filter((a) => new Date(a.created_at).getTime() >= cutoffMs),
    [analyses, cutoffMs],
  );
  const visiblePredictions = useMemo(
    () =>
      predictions.filter((p) => new Date(p.created_at).getTime() >= cutoffMs),
    [predictions, cutoffMs],
  );
  const visibleRuns = useMemo(
    () => runs.filter((r) => new Date(r.started_at).getTime() >= cutoffMs),
    [runs, cutoffMs],
  );

  const grouped = useMemo(() => {
    const m = new Map<
      string,
      {
        trends: Trend[];
        analyses: Analysis[];
        predictions: Prediction[];
        runs: Run[];
      }
    >();
    for (const t of visibleTrends) {
      const k = dayKey(t.discovered_at);
      if (!m.has(k))
        m.set(k, { trends: [], analyses: [], predictions: [], runs: [] });
      m.get(k)!.trends.push(t);
    }
    for (const a of visibleAnalyses) {
      const k = dayKey(a.created_at);
      if (!m.has(k))
        m.set(k, { trends: [], analyses: [], predictions: [], runs: [] });
      m.get(k)!.analyses.push(a);
    }
    for (const p of visiblePredictions) {
      const k = dayKey(p.created_at);
      if (!m.has(k))
        m.set(k, { trends: [], analyses: [], predictions: [], runs: [] });
      m.get(k)!.predictions.push(p);
    }
    for (const r of visibleRuns) {
      const k = dayKey(r.started_at);
      if (!m.has(k))
        m.set(k, { trends: [], analyses: [], predictions: [], runs: [] });
      m.get(k)!.runs.push(r);
    }
    return Array.from(m.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  }, [visibleTrends, visibleAnalyses, visiblePredictions, visibleRuns]);

  useEffect(() => {
    if (grouped.length === 0) return;
    setOpenDays((prev) => {
      const next = { ...prev };
      for (const [k] of grouped) {
        if (next[k] === undefined) next[k] = false;
      }
      return next;
    });
  }, [grouped]);

  async function bulkDelete(
    items: {
      trends: Trend[];
      analyses: Analysis[];
      predictions: Prediction[];
      runs: Run[];
    },
    successMsg: string,
  ) {
    try {
      const body = {
        run_ids: items.runs.map((r) => r.id),
        trend_ids: items.trends.map((t) => t.id),
        analysis_ids: items.analyses.map((a) => a.id),
        prediction_ids: items.predictions.map((p) => p.id),
      };
      const res = await fetch("/api/history/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((j: { detail?: string }) => j.detail ?? res.statusText)
          .catch(() => res.statusText);
        throw new Error(detail);
      }
      notify("ok", successMsg);
      await reload();
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Delete failed.");
    }
  }

  async function deleteVisible() {
    await bulkDelete(
      {
        trends: visibleTrends,
        analyses: visibleAnalyses,
        predictions: visiblePredictions,
        runs: visibleRuns,
      },
      `Deleted ${visibleTrends.length + visibleAnalyses.length + visiblePredictions.length + visibleRuns.length} items.`,
    );
  }

  async function deleteDay(
    day: string,
    bucket: {
      trends: Trend[];
      analyses: Analysis[];
      predictions: Prediction[];
      runs: Run[];
    },
  ) {
    await bulkDelete(
      bucket,
      `Deleted history for ${new Date(day).toDateString()}.`,
    );
  }

  async function handleConfirmDelete() {
    if (!confirmDelete) return;
    try {
      if (confirmDelete.mode === "visible") {
        await deleteVisible();
      } else {
        const bucket = grouped.find(([day]) => day === confirmDelete.day)?.[1];
        if (!bucket) throw new Error("History bucket not found.");
        await deleteDay(confirmDelete.day, bucket);
      }
    } finally {
      setConfirmDelete(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 animate-slide-in-up">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-neural/20 to-pulse/10 border border-neural/20">
            <Clock4 size={20} className="text-neural" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold text-white">
              History Timeline
            </h1>
            <p className="text-sm text-slate-500">
              Collapsible history by date with trends, analyses and predictions
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as DateFilter)}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-300"
            title="Date filter"
          >
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
            <option value="all">All time</option>
          </select>
          <button
            type="button"
            onClick={() => void reload()}
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-slate-300 hover:bg-white/[0.08] transition"
          >
            <RefreshCw size={14} /> Refresh
          </button>
          <button
            type="button"
            onClick={() =>
              setConfirmDelete({
                mode: "visible",
                total:
                  visibleTrends.length +
                  visibleAnalyses.length +
                  visiblePredictions.length +
                  visibleRuns.length,
              })
            }
            className="flex items-center gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-2 text-sm font-medium text-danger hover:bg-danger/15 transition"
          >
            <Trash2 size={14} /> Delete visible
          </button>
        </div>
      </header>

      {loading ? (
        <div className="glass-card rounded-2xl p-8 text-center text-slate-500">
          Loading history…
        </div>
      ) : grouped.length === 0 ? (
        <div className="glass-card rounded-2xl p-8 text-center text-slate-500">
          No history in selected date range.
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map(([day, bucket]) => {
            const total =
              bucket.trends.length +
              bucket.analyses.length +
              bucket.predictions.length +
              bucket.runs.length;
            const isOpen = !!openDays[day];
            return (
              <section
                key={day}
                className="glass-card rounded-2xl overflow-hidden"
              >
                <div className="w-full flex items-center justify-between px-5 py-3 border-b border-white/[0.06] bg-white/[0.02]">
                  <div className="text-left">
                    <p className="text-sm font-semibold text-white">
                      {new Date(day).toDateString()}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {total} event(s)
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setConfirmDelete({ mode: "day", day, total })
                      }
                      className="rounded-lg border border-danger/20 bg-danger/10 px-2.5 py-1 text-xs text-danger hover:bg-danger/15 transition"
                      title="Delete this date group"
                    >
                      <span className="inline-flex items-center gap-1">
                        <Trash2 size={12} /> Delete day
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setOpenDays((prev) => ({ ...prev, [day]: !isOpen }))
                      }
                      className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-slate-400 hover:text-slate-200 transition"
                      title={isOpen ? "Collapse" : "Expand"}
                    >
                      <ChevronDown
                        size={16}
                        className={cn(
                          "transition-transform",
                          isOpen && "rotate-180",
                        )}
                      />
                    </button>
                  </div>
                </div>
                {isOpen && (
                  <div className="p-4 space-y-3">
                    {bucket.trends.map((t) => (
                      <div
                        key={`t-${t.id}`}
                        className="rounded-xl border border-white/[0.08] bg-surface-900/40 p-3 space-y-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <TrendingUp size={13} className="text-accent" />
                            <span className="text-[10px] uppercase tracking-wider text-slate-500">
                              Trend
                            </span>
                          </div>
                        </div>
                        <p className="text-sm font-semibold text-white">
                          {t.title}
                        </p>
                        {t.summary && (
                          <p className="text-xs text-slate-400">{t.summary}</p>
                        )}
                      </div>
                    ))}
                    {bucket.analyses.map((a) => {
                      const conf =
                        CONFIDENCE_MAP[a.confidence] ?? CONFIDENCE_MAP.medium;
                      const recs = parseRecommendationItems(a.recommendation);
                      return (
                        <div
                          key={`a-${a.id}`}
                          className="rounded-xl border border-white/[0.08] bg-surface-900/40 p-3 space-y-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <Bot size={13} className="text-neural" />
                              <span
                                className={cn(
                                  "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                                  conf.cls,
                                )}
                              >
                                {conf.label}
                              </span>
                            </div>
                          </div>
                          <p className="text-sm font-semibold text-white">
                            {a.headline}
                          </p>
                          {recs.length > 1 ? (
                            <ol className="list-decimal pl-5 space-y-1 text-xs text-slate-300">
                              {recs.map((r, i) => (
                                <li key={i}>{r}</li>
                              ))}
                            </ol>
                          ) : (
                            <p className="text-xs text-slate-300">
                              {a.recommendation}
                            </p>
                          )}
                        </div>
                      );
                    })}
                    {bucket.predictions.map((p) => (
                      <div
                        key={`p-${p.id}`}
                        className="rounded-xl border border-white/[0.08] bg-surface-900/40 p-3 space-y-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <Bot size={13} className="text-pulse" />
                            <span className="text-[10px] uppercase tracking-wider text-accent/80">
                              {p.horizon_value} {p.horizon_unit}
                            </span>
                            <span className="text-[10px] text-slate-500">
                              target{" "}
                              {new Date(p.target_date).toLocaleDateString()}
                            </span>
                          </div>
                        </div>
                        <p className="text-sm font-semibold text-white">
                          {p.prediction_text}
                        </p>
                        {p.rationale && (
                          <p className="text-xs text-slate-400">
                            {p.rationale}
                          </p>
                        )}
                      </div>
                    ))}
                    {bucket.runs.map((r) => (
                      <div
                        key={`r-${r.id}`}
                        className="rounded-xl border border-white/[0.08] bg-surface-900/30 p-3 flex items-center justify-between gap-3"
                      >
                        <div>
                          <p className="text-xs text-slate-500">
                            Run #{r.id} • {timeAgo(r.started_at)}
                          </p>
                          <p className="text-sm text-slate-300">
                            {r.summary || r.status}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {confirmDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/70 px-4 backdrop-blur-md"
          onClick={() => setConfirmDelete(null)}
          role="presentation"
        >
          <div
            className="w-full max-w-lg rounded-3xl border border-white/10 bg-surface-900 shadow-2xl shadow-black/40"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="history-delete-title"
          >
            <div className="flex items-start gap-4 border-b border-white/[0.06] px-6 py-5">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-danger/20 bg-danger/10">
                <AlertTriangle size={22} className="text-danger" />
              </div>
              <div className="min-w-0">
                <h2
                  id="history-delete-title"
                  className="font-display text-xl font-bold text-white"
                >
                  {confirmDelete.mode === "visible"
                    ? "Delete visible history?"
                    : "Delete day history?"}
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  {confirmDelete.mode === "visible"
                    ? `This will remove ${confirmDelete.total} visible item(s) from the current date filter.`
                    : `${new Date(confirmDelete.day).toDateString()} contains ${confirmDelete.total} event(s).`}
                </p>
              </div>
            </div>

            <div className="px-6 py-5">
              <div className="rounded-2xl border border-warning/20 bg-warning/10 px-4 py-3 text-sm text-warning">
                This action cannot be undone. Deleted history items are removed
                from the dashboard and history archive.
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-white/[0.06] px-6 py-4">
              <button
                type="button"
                onClick={() => setConfirmDelete(null)}
                className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-slate-300 hover:bg-white/[0.08] transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleConfirmDelete()}
                className="rounded-xl border border-danger/20 bg-danger/10 px-4 py-2 text-sm font-semibold text-danger hover:bg-danger/15 transition"
              >
                Delete now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
