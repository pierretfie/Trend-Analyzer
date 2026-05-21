import { useCallback, useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import type { Status } from "./api";
import { api } from "./api";
import { Sidebar, TABS } from "./components/Sidebar";
import type { Tab } from "./components/Sidebar";
import { Overview } from "./components/Overview";
import { BusinessPanel } from "./components/BusinessPanel";
import { InstructionsPanel } from "./components/InstructionsPanel";
import { ModelSetupPanel } from "./components/ModelSetupPanel";
import { SchedulesPanel } from "./components/SchedulesPanel";
import { ReportsPanel } from "./components/ReportsPanel";
import { ChatPanel } from "./ChatPanel";

function cn(...p: Array<string | false | undefined>) {
  return p.filter(Boolean).join(" ");
}

const VALID_TABS = new Set<Tab>([
  "overview",
  "chat",
  "business",
  "instructions",
  "model",
  "schedules",
  "reports",
]);

function tabFromHash(): Tab {
  const hash = window.location.hash.replace(/^#/, "") as Tab;
  return VALID_TABS.has(hash) ? hash : "overview";
}

export function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [status, setStatus] = useState<Status | null>(null);
  const [toast, setToast] = useState<{
    type: "ok" | "err";
    text: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const notify = useCallback((type: "ok" | "err", text: string) => {
    setToast({ type, text });
    setTimeout(() => setToast(null), 5000);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.status());
    } catch {
      notify("err", "Cannot reach API. Is the backend running?");
    }
  }, [notify]);

  useEffect(() => {
    void loadStatus();
    const iv = window.setInterval(() => void loadStatus(), 12000);
    return () => window.clearInterval(iv);
  }, [loadStatus]);

  // Keep hash in sync when tab changes programmatically.
  useEffect(() => {
    if (window.location.hash.replace(/^#/, "") !== tab) {
      window.location.hash = tab;
    }
  }, [tab]);

  // Restore tab if the user hits the browser Back/Forward buttons.
  useEffect(() => {
    const onHashChange = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  function handleTabChange(t: Tab) {
    setTab(t);
    setMobileOpen(false);
  }

  return (
    <div className="flex min-h-screen neural-grid">
      {/* ── Desktop sidebar ─────────────────────────── */}
      <Sidebar tab={tab} setTab={handleTabChange} status={status} />

      {/* ── Mobile drawer backdrop ───────────────────── */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ── Mobile sidebar drawer ────────────────────── */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-[268px] flex flex-col border-r border-white/[0.06] bg-surface-900/95 backdrop-blur-xl transition-transform duration-300 lg:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <span className="font-display text-sm font-bold text-white">
            Trend Analyzer
          </span>
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="text-slate-500 hover:text-white"
          >
            <X size={18} />
          </button>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3 overflow-y-auto">
          {TABS.map((t) => {
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => handleTabChange(t.id)}
                className={cn(
                  "relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-all",
                  active
                    ? "bg-gradient-to-r from-accent/10 to-neural/5 border border-accent/20"
                    : "text-slate-400 hover:bg-white/[0.04] border border-transparent",
                )}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent" />
                )}
                <span
                  className={cn(
                    "shrink-0",
                    active ? "text-accent" : "text-slate-600",
                  )}
                >
                  {t.icon}
                </span>
                <span>
                  <span
                    className={cn(
                      "block text-[13px] font-semibold",
                      active ? "text-white" : "",
                    )}
                  >
                    {t.title}
                  </span>
                  <span
                    className={cn(
                      "mt-0.5 block text-[11px]",
                      active ? "text-accent/60" : "text-slate-600",
                    )}
                  >
                    {t.desc}
                  </span>
                </span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* ── Main area ───────────────────────────────── */}
      <main className="flex min-h-0 flex-1 flex-col">
        {/* Mobile topbar */}
        <div className="flex items-center gap-3 border-b border-white/[0.06] bg-surface-900/80 backdrop-blur-xl px-4 py-3 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="text-slate-400 hover:text-white transition"
          >
            <Menu size={20} />
          </button>
          <span className="font-display text-sm font-bold text-white flex-1">
            Trend Analyzer
          </span>
          <span className="text-xs font-semibold text-accent/70 uppercase tracking-widest">
            {TABS.find((t) => t.id === tab)?.title}
          </span>
        </div>

        {/* Toast */}
        {toast && (
          <div
            role="alert"
            className={cn(
              "flex items-start justify-between gap-3 px-5 py-3 text-sm border-b animate-slide-in-up",
              toast.type === "ok"
                ? "bg-accent/10 border-accent/20 text-accent"
                : "bg-danger/10 border-danger/20 text-danger",
            )}
          >
            <span>{toast.text}</span>
            <button
              type="button"
              onClick={() => setToast(null)}
              className="shrink-0 rounded-md px-2 py-0.5 text-xs font-medium opacity-70 hover:opacity-100 transition"
            >
              ✕
            </button>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-8 lg:px-10 lg:py-10">
          {tab === "overview" && (
            <Overview
              status={status}
              onRefresh={() => void loadStatus()}
              busy={busy}
              setBusy={setBusy}
              notify={notify}
            />
          )}
          {tab === "chat" && <ChatPanel notify={notify} />}
          {tab === "business" && <BusinessPanel notify={notify} />}
          {tab === "instructions" && <InstructionsPanel notify={notify} />}
          {tab === "model" && <ModelSetupPanel notify={notify} />}
          {tab === "schedules" && <SchedulesPanel notify={notify} />}
          {tab === "reports" && <ReportsPanel notify={notify} />}
        </div>
      </main>
    </div>
  );
}
