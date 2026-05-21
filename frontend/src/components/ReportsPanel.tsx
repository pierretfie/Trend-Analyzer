import { useEffect, useMemo, useState } from "react";
import { MermaidChart } from "./MermaidChart";
import { DataChart } from "./DataChart";
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  FileText,
  RefreshCw,
  Shield,
  Trash2,
  TrendingUp,
  Zap,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

type Severity = "low" | "medium" | "high" | "critical";

type TrendReport = {
  id: number;
  timestamp: string;
  query_used: string;
  summary: string;
  trend_signals: string[];
  recommended_actions: string[];
  severity: Severity;
  sources: string[];
  visualisation: string;
  provider_used: string;
  run_id: number | null;
  created_at: string;
};

type Prediction = {
  id: number;
  prediction_text: string;
  horizon_value: number;
  horizon_unit: "days" | "weeks" | "months" | "years";
  target_date: string;
  confidence: "low" | "medium" | "high";
  rationale: string;
  status: "open" | "resolved" | "expired";
  sources: string[];
};

type SeverityFilter = "all" | Severity;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function cn(...p: Array<string | false | undefined | null>) {
  return p.filter(Boolean).join(" ");
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }) +
    " · " +
    d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
  );
}

// Severity config ──────────────────────────────────────────────────────────────

const SEVERITY_CONFIG: Record<
  Severity,
  { label: string; badge: string; border: string; icon: React.ReactNode }
> = {
  critical: {
    label: "Critical",
    badge: "text-red-400 bg-red-500/10 border border-red-500/20",
    border: "border-l-red-500",
    icon: <AlertTriangle size={12} className="text-red-400" />,
  },
  high: {
    label: "High",
    badge: "text-orange-400 bg-orange-500/10 border border-orange-500/20",
    border: "border-l-orange-500",
    icon: <Zap size={12} className="text-orange-400" />,
  },
  medium: {
    label: "Medium",
    badge: "text-amber-400 bg-amber-500/10 border border-amber-500/20",
    border: "border-l-amber-500",
    icon: <TrendingUp size={12} className="text-amber-400" />,
  },
  low: {
    label: "Low",
    badge: "text-slate-400 bg-slate-500/10 border border-slate-500/20",
    border: "border-l-slate-500",
    icon: <Shield size={12} className="text-slate-400" />,
  },
};

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="glass-card rounded-2xl border-l-4 border-l-white/10 overflow-hidden animate-pulse">
      <div className="px-5 py-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="h-5 w-16 rounded-full bg-white/[0.07]" />
            <div className="h-4 w-28 rounded bg-white/[0.05]" />
            <div className="h-4 w-20 rounded bg-white/[0.05]" />
          </div>
          <div className="h-4 w-12 rounded bg-white/[0.05]" />
        </div>
        <div className="h-3.5 w-full rounded bg-white/[0.05]" />
        <div className="h-3.5 w-4/5 rounded bg-white/[0.04]" />
      </div>
    </div>
  );
}

// ─── Report Card ──────────────────────────────────────────────────────────────

function ReportCard({
  report,
  onDelete,
}: {
  report: TrendReport;
  onDelete: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [predsLoading, setPredsLoading] = useState(false);
  const [predsLoaded, setPredsLoaded] = useState(false);

  const sev = SEVERITY_CONFIG[report.severity] ?? SEVERITY_CONFIG.low;

  // Get the first ~2 lines of summary for the collapsed preview
  const previewLines = useMemo(() => {
    const lines = report.summary.split("\n").filter((l) => l.trim().length > 0);
    return lines.slice(0, 2).join(" ").slice(0, 240);
  }, [report.summary]);

  const hasMore =
    report.summary.split("\n").filter((l) => l.trim().length > 0).length > 2 ||
    report.summary.length > 240;

  return (
    <>
      <article
        className={cn(
          "glass-card rounded-2xl border-l-4 overflow-hidden transition-all",
          sev.border,
        )}
      >
        {/* ── Collapsed header (always visible) ─── */}
        <button
          type="button"
          className="w-full text-left px-5 py-4 group"
          onClick={() => {
            const next = !expanded;
            setExpanded(next);
            if (next && !predsLoaded) {
              setPredsLoading(true);
              fetch(`/api/trend-reports/${report.id}/predictions`)
                .then((r) => r.json())
                .then((data) => {
                  setPredictions(data as Prediction[]);
                  setPredsLoaded(true);
                })
                .catch(() => setPredictions([]))
                .finally(() => setPredsLoading(false));
            }
          }}
          aria-expanded={expanded}
        >
          <div className="flex items-start justify-between gap-3">
            {/* Left meta row */}
            <div className="flex flex-wrap items-center gap-2 min-w-0">
              {/* Severity badge */}
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide shrink-0",
                  sev.badge,
                )}
              >
                {sev.icon}
                {sev.label}
              </span>

              {/* Timestamp */}
              <span className="text-xs text-slate-400 shrink-0">
                {formatTimestamp(report.timestamp)}
              </span>
              <span className="text-[11px] text-slate-600 shrink-0">
                {timeAgo(report.timestamp)}
              </span>

              {/* Run badge */}
              {report.run_id !== null && (
                <span className="inline-flex items-center rounded-full border border-accent/20 bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent shrink-0">
                  Run #{report.run_id}
                </span>
              )}

              {/* Provider badge */}
              {report.provider_used && (
                <span className="inline-flex items-center rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[11px] text-slate-500 shrink-0">
                  {report.provider_used}
                </span>
              )}
            </div>

            {/* Chevron */}
            <span className="mt-0.5 shrink-0 text-slate-500 group-hover:text-slate-300 transition-colors">
              {expanded ? (
                <ChevronDown size={16} />
              ) : (
                <ChevronRight size={16} />
              )}
            </span>
          </div>

          {/* Summary preview */}
          <p className="mt-2.5 text-sm text-slate-300 leading-relaxed line-clamp-2">
            {previewLines}
            {!expanded && hasMore && (
              <span className="ml-1 text-xs text-slate-500">&hellip;</span>
            )}
          </p>
        </button>

        {/* ── Expanded body ────────────────────── */}
        {expanded && (
          <div className="border-t border-white/[0.06] px-5 pb-5 pt-4 space-y-5">
            {/* Full summary */}
            <div>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500">
                Summary
              </h3>
              <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">
                {report.summary}
              </p>
            </div>

            {/* Visualisation */}
            {report.visualisation &&
              (() => {
                const raw = report.visualisation.trim();
                // The LLM stores it as JSON: {"type":"mermaid"|"json","code":"..."}
                // or sometimes as a raw mermaid/json string.
                let visType: "mermaid" | "json" | null = null;
                let visCode = "";
                try {
                  const parsed = JSON.parse(raw) as {
                    type?: string;
                    code?: string;
                  };
                  if (parsed && typeof parsed.code === "string") {
                    visType = parsed.type === "json" ? "json" : "mermaid";
                    visCode = parsed.code.trim();
                  }
                } catch {
                  // Raw string — detect type from first word
                  const first = raw.split(/\s+/)[0]?.toLowerCase() ?? "";
                  const mermaidKeywords = [
                    "graph",
                    "flowchart",
                    "sequencediagram",
                    "gantt",
                    "pie",
                    "erdiagram",
                    "statediagram",
                    "journey",
                    "classDiagram",
                    "gitgraph",
                    "mindmap",
                    "timeline",
                    "xychart",
                  ];
                  if (
                    mermaidKeywords.some((k) =>
                      first.startsWith(k.toLowerCase()),
                    )
                  ) {
                    visType = "mermaid";
                    visCode = raw;
                  } else if (raw.startsWith("{") || raw.startsWith("[")) {
                    visType = "json";
                    visCode = raw;
                  }
                }
                if (!visType || !visCode) return null;
                return (
                  <div className="space-y-1.5">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      Visualisation
                    </p>
                    {visType === "mermaid" ? (
                      <MermaidChart code={visCode} />
                    ) : (
                      <DataChart code={visCode} />
                    )}
                  </div>
                );
              })()}

            {/* Query used */}
            {report.query_used && (
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500">
                  Query Used
                </h3>
                <p className="rounded-xl border border-white/[0.06] bg-white/[0.03] px-3 py-2 text-xs font-mono text-slate-400">
                  {report.query_used}
                </p>
              </div>
            )}

            {/* Trend signals */}
            {report.trend_signals.length > 0 && (
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500">
                  Trend Signals
                </h3>
                <ul className="space-y-1.5">
                  {report.trend_signals.map((signal, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-sm text-slate-300"
                    >
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent/60" />
                      {signal}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommended actions */}
            {report.recommended_actions.length > 0 && (
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500">
                  Recommended Actions
                </h3>
                <ol className="space-y-1.5 list-none">
                  {report.recommended_actions.map((action, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2.5 text-sm text-slate-300"
                    >
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-white/[0.10] bg-white/[0.04] text-[10px] font-bold text-slate-400">
                        {i + 1}
                      </span>
                      {action}
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {/* Sources */}
            {report.sources.length > 0 && (
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500">
                  Sources
                </h3>
                <ul className="space-y-1.5">
                  {report.sources.map((src, i) => (
                    <li key={i}>
                      <a
                        href={src}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group inline-flex items-center gap-1.5 text-xs text-accent/80 underline-offset-2 hover:text-accent hover:underline transition-colors break-all"
                      >
                        <ArrowUpRight
                          size={11}
                          className="shrink-0 opacity-60 group-hover:opacity-100 transition-opacity"
                        />
                        {src}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Predictions */}
            {predsLoading && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  Predictions
                </p>
                <div className="h-6 w-32 animate-pulse rounded bg-white/[0.06]" />
              </div>
            )}
            {!predsLoading && predsLoaded && predictions.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  Predictions ({predictions.length})
                </p>
                <div className="space-y-2">
                  {predictions.map((p) => (
                    <div
                      key={p.id}
                      className="rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2.5 space-y-1"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                            p.confidence === "high"
                              ? "bg-accent/10 text-accent border border-accent/20"
                              : p.confidence === "medium"
                                ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                : "bg-slate-500/10 text-slate-400 border border-slate-500/20",
                          )}
                        >
                          {p.confidence}
                        </span>
                        <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider">
                          {p.horizon_value} {p.horizon_unit}
                        </span>
                        <span className="text-[11px] text-slate-500">
                          → {new Date(p.target_date).toLocaleDateString()}
                        </span>
                        <span
                          className={cn(
                            "ml-auto inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                            p.status === "resolved"
                              ? "bg-accent/10 text-accent"
                              : p.status === "expired"
                                ? "bg-slate-500/10 text-slate-500"
                                : "bg-neural/10 text-neural",
                          )}
                        >
                          {p.status}
                        </span>
                      </div>
                      <p className="text-sm text-slate-200 leading-snug">
                        {p.prediction_text}
                      </p>
                      {p.rationale && (
                        <p className="text-[11px] text-slate-500 leading-relaxed">
                          {p.rationale}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Delete button */}
            <div className="flex justify-end pt-1">
              <button
                type="button"
                onClick={() => setConfirmDelete(true)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-danger/20 bg-danger/10 px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger/15 transition"
              >
                <Trash2 size={12} />
                Delete report
              </button>
            </div>
          </div>
        )}
      </article>

      {/* ── Delete confirmation modal ─────────────────────────────────────── */}
      {confirmDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/70 px-4 backdrop-blur-md"
          onClick={() => setConfirmDelete(false)}
          role="presentation"
        >
          <div
            className="w-full max-w-md rounded-3xl border border-white/10 bg-surface-900 shadow-2xl shadow-black/40"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`delete-report-${report.id}-title`}
          >
            <div className="flex items-start gap-4 border-b border-white/[0.06] px-6 py-5">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-danger/20 bg-danger/10">
                <AlertTriangle size={22} className="text-danger" />
              </div>
              <div className="min-w-0">
                <h2
                  id={`delete-report-${report.id}-title`}
                  className="font-display text-xl font-bold text-white"
                >
                  Delete this report?
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  Report #{report.id} &mdash;{" "}
                  {formatTimestamp(report.timestamp)}
                </p>
              </div>
            </div>
            <div className="px-6 py-5">
              <div className="rounded-2xl border border-warning/20 bg-warning/10 px-4 py-3 text-sm text-warning">
                This action cannot be undone. The report will be permanently
                deleted.
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-white/[0.06] px-6 py-4">
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-slate-300 hover:bg-white/[0.08] transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setConfirmDelete(false);
                  onDelete(report.id);
                }}
                className="rounded-xl border border-danger/20 bg-danger/10 px-4 py-2 text-sm font-semibold text-danger hover:bg-danger/15 transition"
              >
                Delete now
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function ReportsPanel({
  notify,
}: {
  notify: (t: "ok" | "err", m: string) => void;
}) {
  const [reports, setReports] = useState<TrendReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [showDeleteAllConfirm, setShowDeleteAllConfirm] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);

  // ── Data fetching ──────────────────────────────────────────────────────────

  async function loadReports() {
    setLoading(true);
    try {
      const data = (await fetch("/api/trend-reports?limit=100").then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })) as TrendReport[];
      // Sort newest-first by timestamp
      const sorted = [...data].sort(
        (a, b) =>
          new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      );
      setReports(sorted);
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Failed to load reports.");
    } finally {
      setLoading(false);
    }
  }

  async function deleteReport(id: number) {
    try {
      const r = await fetch(`/api/trend-reports/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setReports((prev) => prev.filter((rep) => rep.id !== id));
      notify("ok", `Report #${id} deleted.`);
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Delete failed.");
    }
  }

  async function deleteAllReports() {
    setDeletingAll(true);
    try {
      const r = await fetch("/api/trend-reports", { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as { deleted: number };
      setReports([]);
      setShowDeleteAllConfirm(false);
      notify(
        "ok",
        `Deleted ${data.deleted} report${data.deleted !== 1 ? "s" : ""}.`,
      );
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setDeletingAll(false);
    }
  }

  useEffect(() => {
    void loadReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Derived data ───────────────────────────────────────────────────────────

  const counts = useMemo(
    () =>
      ({
        all: reports.length,
        critical: reports.filter((r) => r.severity === "critical").length,
        high: reports.filter((r) => r.severity === "high").length,
        medium: reports.filter((r) => r.severity === "medium").length,
        low: reports.filter((r) => r.severity === "low").length,
      }) satisfies Record<SeverityFilter, number>,
    [reports],
  );

  const visibleReports = useMemo(
    () =>
      severityFilter === "all"
        ? reports
        : reports.filter((r) => r.severity === severityFilter),
    [reports, severityFilter],
  );

  // ── Filter bar config ──────────────────────────────────────────────────────

  const FILTERS: {
    key: SeverityFilter;
    label: string;
    countStyle: string;
    activeStyle: string;
  }[] = [
    {
      key: "all",
      label: "All",
      countStyle: "bg-white/[0.06] text-slate-400",
      activeStyle: "border-accent/30 bg-accent/10 text-accent",
    },
    {
      key: "critical",
      label: "Critical",
      countStyle: "bg-red-500/10 text-red-400",
      activeStyle: "border-red-500/30 bg-red-500/10 text-red-300",
    },
    {
      key: "high",
      label: "High",
      countStyle: "bg-orange-500/10 text-orange-400",
      activeStyle: "border-orange-500/30 bg-orange-500/10 text-orange-300",
    },
    {
      key: "medium",
      label: "Medium",
      countStyle: "bg-amber-500/10 text-amber-400",
      activeStyle: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    },
    {
      key: "low",
      label: "Low",
      countStyle: "bg-slate-500/10 text-slate-400",
      activeStyle: "border-slate-500/30 bg-slate-500/10 text-slate-300",
    },
  ];

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-5xl space-y-6 animate-slide-in-up">
      {/* ── Page header ─────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent/20 to-pulse/10 border border-accent/20">
            <FileText size={20} className="text-accent" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold text-white">
              Research Reports
            </h1>
            <p className="text-sm text-slate-500">
              Scheduled run reports with trend signals and recommended actions
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void loadReports()}
            disabled={loading}
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-slate-300 hover:bg-white/[0.08] disabled:opacity-50 transition"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          {reports.length > 0 && (
            <button
              type="button"
              onClick={() => setShowDeleteAllConfirm(true)}
              disabled={loading}
              className="flex items-center gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-2 text-sm font-medium text-danger hover:bg-danger/15 disabled:opacity-50 transition"
            >
              <Trash2 size={14} />
              Delete all
            </button>
          )}
        </div>
      </header>

      {/* ── Severity filter bar ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map(({ key, label, countStyle, activeStyle }) => {
          const isActive = severityFilter === key;
          const count = counts[key];
          return (
            <button
              key={key}
              type="button"
              onClick={() => setSeverityFilter(key)}
              className={cn(
                "inline-flex items-center gap-2 rounded-xl border px-3.5 py-1.5 text-sm font-medium transition",
                isActive
                  ? activeStyle
                  : "border-white/[0.08] bg-white/[0.03] text-slate-400 hover:bg-white/[0.06] hover:text-slate-200",
              )}
            >
              {label}
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[11px] font-bold",
                  isActive ? countStyle : "bg-white/[0.06] text-slate-500",
                )}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── Report list ─────────────────────────────────────────────────── */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : visibleReports.length === 0 ? (
        /* ── Empty state ──────────────────────────────────────────────── */
        <div className="glass-card rounded-2xl p-12 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-white/[0.08] bg-white/[0.03]">
            <FileText size={26} className="text-slate-600" />
          </div>
          <h2 className="font-display text-lg font-semibold text-slate-300">
            {severityFilter === "all"
              ? "No reports yet"
              : `No ${severityFilter} reports`}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            {severityFilter === "all"
              ? "Reports will appear here after scheduled research runs complete."
              : `There are no reports with ${severityFilter} severity. Try a different filter.`}
          </p>
          {severityFilter !== "all" && (
            <button
              type="button"
              onClick={() => setSeverityFilter("all")}
              className="mt-4 inline-flex items-center gap-1.5 rounded-xl border border-accent/20 bg-accent/10 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/15 transition"
            >
              Show all reports
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {visibleReports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              onDelete={deleteReport}
            />
          ))}
        </div>
      )}

      {/* ── Delete all confirmation modal ───────────────────────────────── */}
      {showDeleteAllConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/70 px-4 backdrop-blur-md"
          onClick={() => setShowDeleteAllConfirm(false)}
          role="presentation"
        >
          <div
            className="w-full max-w-md rounded-3xl border border-white/10 bg-surface-900 shadow-2xl shadow-black/40"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="flex items-start gap-4 border-b border-white/[0.06] px-6 py-5">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-danger/20 bg-danger/10">
                <AlertTriangle size={22} className="text-danger" />
              </div>
              <div className="min-w-0">
                <h2 className="font-display text-xl font-bold text-white">
                  Delete all reports?
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  {reports.length} report{reports.length !== 1 ? "s" : ""} will
                  be permanently deleted.
                </p>
              </div>
            </div>
            <div className="px-6 py-5">
              <div className="rounded-2xl border border-warning/20 bg-warning/10 px-4 py-3 text-sm text-warning space-y-1">
                <p className="font-semibold">This cannot be undone.</p>
                <p>
                  Each report and all data from the same run will be deleted:
                </p>
                <ul className="mt-1 space-y-0.5 text-xs opacity-90">
                  <li>• All trend reports</li>
                  <li>• All discovered trends &amp; AI analyses</li>
                  <li>• All predictions</li>
                  <li>• All run log entries</li>
                </ul>
                <p className="text-xs opacity-75 pt-1">
                  API keys, schedules, business profile, and chat are kept.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-white/[0.06] px-6 py-4">
              <button
                type="button"
                onClick={() => setShowDeleteAllConfirm(false)}
                disabled={deletingAll}
                className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-slate-300 hover:bg-white/[0.08] disabled:opacity-50 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void deleteAllReports()}
                disabled={deletingAll}
                className="rounded-xl border border-danger/20 bg-danger/10 px-4 py-2 text-sm font-semibold text-danger hover:bg-danger/15 disabled:opacity-50 transition"
              >
                {deletingAll ? "Deleting…" : "Delete all"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
