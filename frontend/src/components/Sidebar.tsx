import {
  BarChart2,
  Bot,
  Brain,
  Building2,
  CalendarClock,
  FileText,
  Settings2,
} from "lucide-react";
import type { Status } from "../api";

export type Tab =
  | "overview"
  | "chat"
  | "business"
  | "instructions"
  | "model"
  | "schedules"
  | "reports";

const TABS: { id: Tab; title: string; desc: string; icon: React.ReactNode }[] =
  [
    {
      id: "overview",
      title: "Overview",
      desc: "Health & actions",
      icon: <BarChart2 size={16} />,
    },
    {
      id: "chat",
      title: "Research Chat",
      desc: "Search & ask",
      icon: <Bot size={16} />,
    },
    {
      id: "business",
      title: "Business Profile",
      desc: "What you operate",
      icon: <Building2 size={16} />,
    },
    {
      id: "instructions",
      title: "Instructions",
      desc: "Rules for analysis",
      icon: <Brain size={16} />,
    },
    {
      id: "model",
      title: "Model Setup",
      desc: "API keys & provider",
      icon: <Settings2 size={16} />,
    },
    {
      id: "schedules",
      title: "Research Schedule",
      desc: "When to gather signals",
      icon: <CalendarClock size={16} />,
    },
    {
      id: "reports",
      title: "Research Reports",
      desc: "Full scheduled reports",
      icon: <FileText size={16} />,
    },
  ];

interface SidebarProps {
  tab: Tab;
  setTab: (t: Tab) => void;
  status: Status | null;
}

export function Sidebar({ tab, setTab, status }: SidebarProps) {
  const isLive = status?.scheduler_running ?? false;

  return (
    <aside className="hidden w-[268px] shrink-0 flex-col border-r border-white/[0.06] bg-surface-900/80 backdrop-blur-xl lg:flex">
      {/* Logo */}
      <div className="px-5 py-6 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent/30 to-neural/20 border border-accent/20 shadow-glow-sm">
            <BarChart2 size={18} className="text-accent" />
            <span className="absolute -top-0.5 -right-0.5 flex h-2.5 w-2.5">
              <span
                className={`absolute inline-flex h-full w-full rounded-full ${isLive ? "bg-accent opacity-75 animate-ping" : "bg-slate-600"}`}
              />
              <span
                className={`relative inline-flex h-2.5 w-2.5 rounded-full ${isLive ? "bg-accent live-dot" : "bg-slate-600"}`}
              />
            </span>
          </div>
          <div>
            <p className="font-display text-[15px] font-bold tracking-tight text-white">
              Trend Analyzer
            </p>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-accent/70">
              {isLive ? "● Live" : "○ Idle"}
            </p>
          </div>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-500 text-balance">
          AI-powered trend intelligence for your business.
        </p>
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-all duration-200 ${
                active
                  ? "bg-gradient-to-r from-accent/10 to-neural/5 border border-accent/20 shadow-glow-sm"
                  : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200 border border-transparent"
              }`}
            >
              {active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-[3px] rounded-r-full bg-accent shadow-glow" />
              )}
              <span
                className={`shrink-0 transition-colors ${active ? "text-accent" : "text-slate-500 group-hover:text-slate-300"}`}
              >
                {t.icon}
              </span>
              <span className="min-w-0">
                <span
                  className={`block text-[13px] font-semibold ${active ? "text-white" : ""}`}
                >
                  {t.title}
                </span>
                <span
                  className={`mt-0.5 block text-[11px] ${active ? "text-accent/60" : "text-slate-600"}`}
                >
                  {t.desc}
                </span>
              </span>
            </button>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-white/[0.05] p-4 space-y-1">
        {status && (
          <p className="text-[11px] text-slate-600">
            {status.scheduler_jobs} cron job
            {status.scheduler_jobs !== 1 ? "s" : ""} active
          </p>
        )}
      </div>
    </aside>
  );
}

export { TABS };
