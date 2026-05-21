import { FormEvent, useEffect, useState } from "react";
import {
  Bot,
  CalendarClock,
  Plus,
  Pause,
  Play,
  Trash2,
} from "lucide-react";
import type { Schedule, ModelSetup } from "../api";
import { api } from "../api";

function cn(...p: Array<string | false | undefined>) {
  return p.filter(Boolean).join(" ");
}

const WK = [
  { v: 0, l: "Mon" },
  { v: 1, l: "Tue" },
  { v: 2, l: "Wed" },
  { v: 3, l: "Thu" },
  { v: 4, l: "Fri" },
  { v: 5, l: "Sat" },
  { v: 6, l: "Sun" },
];

const inp =
  "mt-2 w-full rounded-xl border border-white/[0.08] bg-surface-800/80 px-4 py-2.5 text-sm text-slate-100 input-glow placeholder:text-slate-600 transition-all";

// All 7 days selected by default
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

export function SchedulesPanel({
  notify,
}: {
  notify: (t: "ok" | "err", m: string) => void;
}) {
  const [rows, setRows] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [thinkingLevel, setThinkingLevel] = useState(2);
  const [deepReadEnabled, setDeepReadEnabled] = useState(true);
  const [deepReadMaxArticles, setDeepReadMaxArticles] = useState(3);
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  // Unified state — days + times
  const [activeDays, setActiveDays] = useState<number[]>(ALL_DAYS); // default: every day
  const [runCount, setRunCount] = useState(1);
  const [slotTimes, setSlotTimes] = useState<string[]>(["07:00"]);
  const [label, setLabel] = useState("");
  const [tz, setTz] = useState("local");
  const [isOnce, setIsOnce] = useState(false);
  const [onceDateTime, setOnceDateTime] = useState("");

  async function reload() {
    try {
      setRows(await api.listSchedules());
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "List failed.");
    }
    setLoading(false);
  }
  useEffect(() => {
    void reload();
    void (async () => {
      try {
        const s = await api.getModelSetup();
        setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? 2)));
        setDeepReadEnabled(Boolean(s.deep_read_enabled ?? true));
        setDeepReadMaxArticles(
          Math.max(1, Math.min(8, s.deep_read_max_articles ?? 3)),
        );
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

  function toggleDay(v: number) {
    setActiveDays((prev) =>
      prev.includes(v)
        ? prev.filter((x) => x !== v)
        : [...prev, v].sort((a, b) => a - b),
    );
  }

  function selectPreset(days: number[]) {
    setIsOnce(false);
    setActiveDays([...days]);
  }
  function selectOnce() {
    setIsOnce(true);
    setActiveDays([]);
  }

  function handleCountChange(n: number) {
    setRunCount(n);
    setSlotTimes((prev) => {
      const next = [...prev];
      while (next.length < n) next.push("12:00");
      return next.slice(0, n);
    });
  }

  async function add(ev: FormEvent) {
    ev.preventDefault();
    if (!isOnce && activeDays.length === 0) {
      notify("err", "Select at least one day.");
      return;
    }

    try {
      if (isOnce) {
        if (!onceDateTime) {
          notify("err", "Select a date and time.");
          return;
        }
        await api.createSchedule({
          frequency: "once",
          time_points: [onceDateTime],
          weekdays: [],
          label: label || undefined,
          timezone: tz || "local",
        });
      } else {
        const tp = slotTimes.filter(Boolean);
        const isAllDays = activeDays.length === 7;
        await api.createSchedule({
          frequency: isAllDays ? "daily" : "weekly",
          time_points: tp,
          weekdays: isAllDays ? [] : activeDays,
          label: label || undefined,
          timezone: tz || "local",
        });
      }
      notify("ok", "Schedule added.");
      setLabel("");
      void reload();
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Create failed.");
    }
  }

  async function toggle(s: Schedule) {
    try {
      await api.patchSchedule(s.id, { enabled: !s.enabled });
      notify("ok", !s.enabled ? "Enabled." : "Paused.");
      void reload();
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Update failed.");
    }
  }

  async function remove(s: Schedule) {
    if (!window.confirm(`Delete schedule #${s.id}?`)) return;
    try {
      await api.deleteSchedule(s.id);
      notify("ok", "Removed.");
      void reload();
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Delete failed.");
    }
  }

  async function updateThinkingLevel(next: number) {
    const clamped = Math.max(1, Math.min(5, next));
    setThinkingLevel(clamped);
    try {
      const s = await api.patchModelSetup({ thinking_level: clamped });
      setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? clamped)));
      notify("ok", `Default scheduled thinking level set to L${clamped}.`);
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

  return (
    <div className="mx-auto max-w-4xl space-y-8 animate-slide-in-up">
      <header className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-pulse/20 to-accent/10 border border-pulse/20">
          <CalendarClock size={20} className="text-pulse" />
        </div>
        <div>
          <h1 className="font-display text-2xl font-bold text-white">
            Research Schedules
          </h1>
          <p className="text-sm text-slate-500">
            Automate when your agent gathers signals
          </p>
        </div>
      </header>

      {/* ── Global autonomous research settings ── */}
      <section className="glass-card rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-accent/10 border border-accent/20">
              <Bot size={13} className="text-accent" />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Autonomous Research Settings
            </h2>
          </div>
          <div className="ml-auto">
            <select
              value={activeProvider || "none"}
              onChange={(e) =>
                void updateProvider(e.target.value as ModelSetup["llm_provider"])
              }
              className={cn(
                "rounded-lg border px-2 py-1 text-[11px] font-semibold transition-all cursor-pointer focus:outline-none hover:border-white/[0.20]",
                activeProvider && activeProvider !== "none"
                  ? "border-white/[0.10] bg-surface-800 text-slate-200"
                  : "border-danger/30 bg-danger/10 text-danger/80",
              )}
            >
              <option value="none">Auto</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="local">Local</option>
            </select>
          </div>
        </div>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          These are{" "}
          <span className="text-slate-300 font-medium">global defaults</span>{" "}
          shared by all scheduled runs, quick runs, and the Overview panel.
          Changes save immediately.
        </p>

        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Research depth
            </span>
            <select
              value={thinkingLevel}
              onChange={(e) => {
                void updateThinkingLevel(Number(e.target.value));
              }}
              className="ml-auto rounded-lg border border-accent/20 bg-surface-800 px-2 py-1 text-[11px] text-accent hover:border-accent/40 transition-all cursor-pointer focus:outline-none"
              title="How many search-and-refine iterations the agent runs"
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  L{n}
                </option>
              ))}
            </select>
          </div>
          <p className="mt-2 text-[11px] text-slate-600">
            How many search-and-refine iterations the agent runs. L1 is fastest,
            L5 is most thorough.
          </p>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Deep read
            </span>
            <button
              type="button"
              onClick={() => {
                void updateDeepRead(!deepReadEnabled);
              }}
              className={cn(
                "ml-auto rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all",
                deepReadEnabled
                  ? "border-neural/30 bg-neural/10 text-neural"
                  : "border-white/10 bg-white/[0.04] text-slate-400",
              )}
            >
              {deepReadEnabled ? "On" : "Off"}
            </button>
            <select
              disabled={!deepReadEnabled}
              value={deepReadMaxArticles}
              onChange={(e) => {
                void updateDeepRead(deepReadEnabled, Number(e.target.value));
              }}
              className="rounded-lg border border-neural/20 bg-surface-800 px-2 py-1 text-[11px] text-neural hover:border-neural/40 transition-all cursor-pointer focus:outline-none disabled:opacity-50"
              title="How many top links to read fully per run"
            >
              {[1, 2, 3, 4, 5, 6, 8].map((n) => (
                <option key={n} value={n}>
                  {n}s
                </option>
              ))}
            </select>
          </div>
          <p className="mt-2 text-[11px] text-slate-600">
            Fetches and reads full article text before analysis — not just
            snippets.
          </p>
        </div>
      </section>

      {/* Add form */}
      <form onSubmit={add} className="glass-card space-y-6 rounded-2xl p-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Add New Schedule
        </h2>

        {/* ── Day selection ── */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Days to run
            </span>
            <div className="flex gap-2">
              {[
                { label: "Every day", days: ALL_DAYS },
                { label: "Weekdays", days: [0, 1, 2, 3, 4] },
                { label: "Weekends", days: [5, 6] },
              ].map(({ label: lbl, days }) => {
                const active =
                  !isOnce &&
                  days.every((d) => activeDays.includes(d)) &&
                  activeDays.length === days.length;
                return (
                  <button
                    key={lbl}
                    type="button"
                    onClick={() => selectPreset(days)}
                    className={cn(
                      "rounded-lg px-2.5 py-1 text-[11px] font-semibold transition-all",
                      active
                        ? "bg-accent/20 text-accent border border-accent/30"
                        : "text-slate-500 hover:text-slate-300 border border-white/[0.06]",
                    )}
                  >
                    {lbl}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={selectOnce}
                className={cn(
                  "rounded-lg px-2.5 py-1 text-[11px] font-semibold transition-all",
                  isOnce
                    ? "bg-accent/20 text-accent border border-accent/30"
                    : "text-slate-500 hover:text-slate-300 border border-white/[0.06]",
                )}
              >
                Once
              </button>
            </div>
          </div>

          {!isOnce ? (
            <>
              <div className="flex flex-wrap gap-2">
                {WK.map((d) => {
                  const sel = activeDays.includes(d.v);
                  return (
                    <button
                      key={d.v}
                      type="button"
                      onClick={() => toggleDay(d.v)}
                      className={cn(
                        "rounded-xl px-3.5 py-2 text-xs font-bold uppercase tracking-wide transition-all btn-glow",
                        sel
                          ? "bg-gradient-to-r from-accent to-accent-glow text-surface-900 shadow-glow-sm"
                          : "border border-white/10 bg-white/[0.04] text-slate-500 hover:border-accent/30 hover:text-slate-300",
                      )}
                    >
                      {d.l}
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-slate-600">
                {activeDays.length === 7
                  ? "Runs every day (daily)"
                  : activeDays.length === 0
                    ? "⚠ Select at least one day"
                    : `Runs on: ${activeDays.map((v) => WK[v]?.l ?? v).join(", ")}`}
              </p>
            </>
          ) : (
            <div className="space-y-2">
              <input
                type="datetime-local"
                value={onceDateTime}
                onChange={(e) => setOnceDateTime(e.target.value)}
                className="w-full rounded-xl border border-white/[0.08] bg-surface-800/80 px-4 py-2.5 text-sm text-slate-100 input-glow transition-all [color-scheme:dark]"
              />
              <p className="text-[11px] text-slate-600">
                Research will run once at the specified date and time, then
                pause automatically.
              </p>
            </div>
          )}
        </div>

        {/* ── Times per day (hide if Once) ── */}
        {!isOnce && (
          <div className="space-y-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Times per day
            </span>
            <div className="flex flex-wrap gap-2">
              {[1, 2, 3, 4, 6].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => handleCountChange(n)}
                  className={cn(
                    "h-9 w-9 rounded-xl text-sm font-bold transition-all btn-glow",
                    runCount === n
                      ? "bg-gradient-to-r from-accent to-accent-glow text-surface-900 shadow-glow-sm"
                      : "border border-white/10 bg-white/[0.04] text-slate-400 hover:bg-white/[0.08]",
                  )}
                >
                  {n}×
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Time slots (hide if Once) ── */}
        {!isOnce && (
          <div className="space-y-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Run times{" "}
              <span className="font-normal text-slate-600">(HH:MM)</span>
            </span>
            <div
              className={cn("grid gap-3", runCount > 1 ? "sm:grid-cols-2" : "")}
            >
              {slotTimes.map((t, i) => (
                <label key={i} className="flex items-center gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent/10 text-[11px] font-bold text-accent/80">
                    {i + 1}
                  </span>
                  <input
                    type="time"
                    value={t}
                    onChange={(e) =>
                      setSlotTimes((prev) => {
                        const next = [...prev];
                        next[i] = e.target.value;
                        return next;
                      })
                    }
                    className="flex-1 rounded-xl border border-white/[0.08] bg-surface-800/80 px-3 py-2 font-mono text-sm text-slate-100 input-glow transition-all [color-scheme:dark]"
                  />
                </label>
              ))}
            </div>
          </div>
        )}

        {/* ── Label + TZ ── */}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Label
            </span>
            <input
              className={inp}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Morning scan"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Time zone
            </span>
            <input
              className={`${inp} font-mono`}
              value={tz}
              onChange={(e) => setTz(e.target.value)}
              placeholder="local"
            />
          </label>
        </div>

        <button
          type="submit"
          className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-glow px-6 py-2.5 text-sm font-bold text-surface-900 shadow-glow-sm hover:shadow-glow transition-all"
        >
          <Plus size={15} /> Add schedule
        </button>
      </form>

      {/* Table */}
      <div className="glass-card overflow-hidden rounded-2xl">
        {loading ? (
          <p className="p-6 text-slate-500">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="p-8 text-center text-sm text-slate-500">
            No schedules yet. Add one above.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/[0.06] bg-surface-800/60 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              <tr>
                {["#", "When", "Label", "TZ", ""].map((h) => (
                  <th key={h} className="px-5 py-3">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {rows.map((s) => (
                <tr
                  key={s.id}
                  className={cn(
                    "transition-colors hover:bg-white/[0.02]",
                    !s.enabled && "opacity-40",
                  )}
                >
                  <td className="px-5 py-3 font-mono text-xs text-accent/80">
                    #{s.id}
                  </td>
                  <td className="px-5 py-3 text-slate-300">
                    <span className="capitalize font-medium">
                      {s.frequency}
                    </span>
                    <span className="ml-2 font-mono text-xs text-accent/70">
                      {s.time_points.join(", ")}
                    </span>
                    {s.weekdays.length > 0 && (
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {s.weekdays.map((v) => WK[v]?.l ?? v).join(", ")}
                      </span>
                    )}
                    {s.last_run_status && (
                      <div className="mt-2 flex items-center gap-1.5">
                        <div
                          className={cn(
                            "h-1.5 w-1.5 rounded-full shadow-[0_0_8px]",
                            s.last_run_status === "ok"
                              ? "bg-green-500 shadow-green-500/50"
                              : s.last_run_status === "missed"
                                ? "bg-amber-500 shadow-amber-500/50"
                                : s.last_run_status === "skipped"
                                  ? "bg-slate-500 shadow-slate-500/50"
                                  : "bg-red-500 shadow-red-500/50",
                          )}
                        />
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                          Last run:{" "}
                          {s.last_run_status === "ok"
                            ? "Success"
                            : s.last_run_status === "missed"
                              ? "Missed"
                              : s.last_run_status === "skipped"
                                ? "Skipped"
                                : "Error"}
                        </span>
                        {s.last_run_summary && (
                          <span
                            className="text-[10px] text-slate-600 truncate max-w-[200px]"
                            title={s.last_run_summary}
                          >
                            — {s.last_run_summary.replace(/^error: /, "")}
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-3 text-slate-400">{s.label || "—"}</td>
                  <td className="px-5 py-3 font-mono text-xs text-slate-500">
                    {s.timezone}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => void toggle(s)}
                        className="flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-accent/80 hover:bg-accent/10 transition"
                      >
                        {s.enabled ? (
                          <>
                            <Pause size={11} />
                            Pause
                          </>
                        ) : (
                          <>
                            <Play size={11} />
                            Resume
                          </>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(s)}
                        className="flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-danger/70 hover:bg-danger/10 transition"
                      >
                        <Trash2 size={11} /> Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
