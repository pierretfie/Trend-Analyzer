import {
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
  memo,
} from "react";
import {
  Bot,
  User,
  Send,
  Trash2,
  MessageSquare,
  Sparkles,
  Loader2,
  Globe,
  Plus,
  History,
  ChevronRight,
  ChevronDown,
  Square,
  AlertCircle,
  PanelLeftOpen,
  PanelLeftClose,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import DOMPurify from "dompurify";
import type { ModelSetup, ChatSession } from "./api";
import { api } from "./api";
import { MermaidChart } from "./components/MermaidChart";
import { DataChart } from "./components/DataChart";

type ProcessTrace = {
  logs: string[];
  sources: { title: string; link: string; snippet: string }[];
  reading: {
    title?: string;
    url?: string;
    status: "started" | "completed" | "skipped";
  }[];
  durationSec: number;
};
type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  html?: string;
  processTrace?: ProcessTrace;
};
function cn(...p: Array<string | false | undefined>) {
  return p.filter(Boolean).join(" ");
}

const saveTraceToLocal = (sessionId: number, msgs: ChatMsg[]) => {
  const traces = msgs.map((m) => ({
    html: m.html,
    processTrace: m.processTrace,
  }));
  localStorage.setItem(`chat_trace_${sessionId}`, JSON.stringify(traces));
};

function isCasualMessage(text: string): boolean {
  const t = text.trim().toLowerCase();
  if (!t) return false;
  if (
    t.length <= 40 &&
    /^(hi|hello|hey|yo|thanks|thank you|ok|okay|cool|nice|good morning|good afternoon|good evening)[!. ]*$/.test(
      t,
    )
  )
    return true;
  if (t.length <= 60 && /^(how are you|what's up|whats up)[!? ]*$/.test(t))
    return true;
  return false;
}

const Message = memo(function Message({ m }: { m: ChatMsg }) {
  const isUser = m.role === "user";
  const safeHtml =
    !isUser && m.html
      ? DOMPurify.sanitize(m.html, {
          USE_PROFILES: { html: true },
          FORBID_TAGS: [
            "script",
            "style",
            "iframe",
            "object",
            "embed",
            "link",
            "meta",
          ],
          FORBID_ATTR: ["style", "onerror", "onload", "onclick", "onmouseover"],
          ALLOWED_ATTR: [
            "class",
            "href",
            "target",
            "rel",
            "aria-label",
            "title",
            "role",
            "colspan",
            "rowspan",
          ],
          ALLOW_DATA_ATTR: false,
          ALLOWED_URI_REGEXP:
            /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.-]|$))/i,
        })
      : "";

  return (
    <div
      className={cn(
        "flex gap-2 animate-slide-in-up",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border mt-0.5",
          isUser
            ? "bg-gradient-to-br from-accent/30 to-neural/20 border-accent/25"
            : "bg-gradient-to-br from-neural/20 to-surface-800 border-neural/20",
        )}
      >
        {isUser ? (
          <User size={11} className="text-accent" />
        ) : (
          <Bot size={11} className="text-neural" />
        )}
      </div>

      {/* Assistant bubbles expand to fill width; user bubbles stay right-anchored */}
      <div
        className={cn(
          "rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-lg",
          isUser
            ? "max-w-[60%] rounded-tr-sm bg-gradient-to-br from-accent/20 to-neural/10 border border-accent/20 text-white"
            : "flex-1 min-w-0 rounded-tl-sm border border-white/[0.07] bg-surface-800/95 text-slate-100",
        )}
      >
        <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-pre:bg-surface-900 prose-pre:border prose-pre:border-white/10 prose-code:text-accent prose-a:text-accent hover:prose-a:text-accent-glow prose-table:text-xs prose-td:py-1.5 prose-th:py-1.5 transition-colors">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ node, inline, className, children, ...props }: any) {
                const match = /language-(\w+)/.exec(className || "");
                const lang = match ? match[1] : "";
                const content = String(children).replace(/\n$/, "");
                if (!inline && lang === "mermaid")
                  return <MermaidChart code={content} />;
                if (!inline && lang === "json" && content.includes('"type"')) {
                  try {
                    const parsed = JSON.parse(content);
                    const isChartSpec =
                      parsed &&
                      typeof parsed.type === "string" &&
                      (Array.isArray(parsed.data) ||
                        (parsed.data &&
                          typeof parsed.data === "object" &&
                          Array.isArray(parsed.data.labels) &&
                          Array.isArray(parsed.data.datasets)));
                    if (isChartSpec) return <DataChart code={content} />;
                  } catch {
                    /* fall through */
                  }
                }
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              },
            }}
          >
            {m.content}
          </ReactMarkdown>
        </div>
        {!isUser && m.html && m.html.trim() && (
          <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <div
              className="ta-html-brief prose prose-invert prose-sm max-w-none"
              dangerouslySetInnerHTML={{ __html: safeHtml }}
            />
          </div>
        )}
      </div>
    </div>
  );
});

function ProcessTracePanel({
  logs,
  sources,
  reading,
  durationSec,
  live,
}: {
  logs: string[];
  sources: { title: string; link: string; snippet?: string }[];
  reading: {
    title?: string;
    url?: string;
    status: "started" | "completed" | "skipped";
  }[];
  durationSec: number;
  live: boolean;
}) {
  const [expanded, setExpanded] = useState(live);
  const logScrollRef = useRef<HTMLDivElement | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // Tick every second while live; stop and lock to final durationSec when done.
  useEffect(() => {
    if (!live) {
      setElapsed(0);
      return;
    }
    setElapsed(0);
    const id = window.setInterval(() => {
      setElapsed((s) => s + 1);
    }, 1000);
    return () => window.clearInterval(id);
  }, [live]);

  const displaySec = live ? elapsed : durationSec;

  useEffect(() => {
    if (live && expanded && logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [logs, live, expanded]);

  return (
    <div className="pl-8 animate-slide-in-up">
      <div className="rounded-xl border border-white/[0.06] bg-surface-800/60 px-3 py-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center gap-2 text-left"
        >
          {expanded ? (
            <ChevronDown size={12} className="text-slate-500 shrink-0" />
          ) : (
            <ChevronRight size={12} className="text-slate-500 shrink-0" />
          )}
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Model process
          </span>
          <span className="ml-auto flex items-center gap-1.5 text-[10px] text-slate-600 shrink-0">
            {live && <Loader2 size={9} className="animate-spin text-accent" />}
            {logs.length} step(s) · {sources.length} src ·{" "}
            {displaySec.toFixed(live ? 0 : 1)}s
          </span>
        </button>

        {expanded && (
          <div className="mt-2 space-y-2 border-t border-white/[0.05] pt-2">
            {logs.length > 0 && (
              <div
                ref={logScrollRef}
                className="max-h-36 overflow-y-auto space-y-0.5 pr-1"
              >
                {logs.map((log, i) => (
                  <div
                    key={`${i}-${log.slice(0, 20)}`}
                    className="text-[11px] text-slate-400 break-words leading-relaxed"
                  >
                    {log}
                  </div>
                ))}
                {live && (
                  <div className="flex items-center gap-1 pt-0.5">
                    <span className="h-1 w-1 rounded-full bg-accent animate-pulse" />
                    <span className="h-1 w-1 rounded-full bg-accent animate-pulse [animation-delay:150ms]" />
                    <span className="h-1 w-1 rounded-full bg-accent animate-pulse [animation-delay:300ms]" />
                  </div>
                )}
              </div>
            )}
            {sources.length > 0 && (
              <div className="space-y-1">
                <p className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">
                  Sources
                </p>
                {sources.map((s, i) => (
                  <a
                    key={`${s.link}-${i}`}
                    href={s.link}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 px-2 py-1 rounded-lg bg-white/[0.02] hover:bg-white/[0.05] border border-white/[0.04] group transition-all"
                  >
                    <Globe
                      size={10}
                      className="text-slate-600 group-hover:text-accent shrink-0 transition-colors"
                    />
                    <span className="text-[10px] text-slate-400 truncate group-hover:text-slate-200">
                      {s.title || s.link}
                    </span>
                    <ChevronRight
                      size={9}
                      className="text-slate-700 ml-auto shrink-0"
                    />
                  </a>
                ))}
              </div>
            )}
            {reading.length > 0 && (
              <div className="space-y-1">
                <p className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">
                  Reading
                </p>
                {reading.map((r, i) => (
                  <div
                    key={`${r.url}-${i}`}
                    className="flex items-center gap-2 rounded-lg border border-white/[0.04] bg-white/[0.02] px-2 py-1"
                  >
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full shrink-0",
                        r.status === "completed"
                          ? "bg-accent"
                          : r.status === "started"
                            ? "bg-amber-400 animate-pulse"
                            : "bg-slate-600",
                      )}
                    />
                    <span className="text-[10px] text-slate-400 truncate">
                      {r.title || r.url}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function ChatPanel({
  notify,
}: {
  notify: (t: "ok" | "err", m: string) => void;
}) {
  const [setup, setSetup] = useState<ModelSetup | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState<
    "auto" | "openai" | "gemini" | "local"
  >(
    () =>
      (localStorage.getItem("ta_chat_provider") ?? "auto") as
        | "auto"
        | "openai"
        | "gemini"
        | "local",
  );
  const [thinkingEnabled, setThinkingEnabled] = useState(
    () => localStorage.getItem("ta_chat_think_on") !== "0",
  );
  const [thinkingLevel, setThinkingLevel] = useState(2);
  const [deepReadEnabled, setDeepReadEnabled] = useState(true);
  const [deepReadMaxArticles, setDeepReadMaxArticles] = useState(3);
  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [_phase, setPhase] = useState<"searching" | "thinking" | "reading">(
    "thinking",
  );
  const [_query, setQuery] = useState<string | undefined>();
  const [liveTraceLogs, setLiveTraceLogs] = useState<string[]>([]);
  const [liveTraceSources, setLiveTraceSources] = useState<
    { title: string; link: string; snippet: string }[]
  >([]);
  const [liveTraceReading, setLiveTraceReading] = useState<
    {
      title?: string;
      url?: string;
      status: "started" | "completed" | "skipped";
    }[]
  >([]);
  const [liveTraceStartedAt, setLiveTraceStartedAt] = useState<number>(0);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [confirmDeleteSessionId, setConfirmDeleteSessionId] = useState<
    number | null
  >(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Track whether the user has manually scrolled up so we don't hijack them.
  const userScrolledUpRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const logBufferRef = useRef<string[]>([]);
  const logRafRef = useRef<number | null>(null);

  const enqueueLog = useCallback((line: string) => {
    logBufferRef.current.push(line);
    if (logRafRef.current !== null) return;
    logRafRef.current = window.requestAnimationFrame(() => {
      const batch = logBufferRef.current;
      logBufferRef.current = [];
      logRafRef.current = null;
      if (batch.length) setLiveTraceLogs((prev) => [...prev, ...batch]);
    });
  }, []);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  const scrollToBottom = useCallback((force = false) => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // Don't scroll if the user deliberately scrolled up — unless forced
    // (e.g. when the user sends a new message).
    if (!force && userScrolledUpRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await api.listChatSessions();
      setSessions(list);
    } catch {
      /* ignore */
    }
    setLoadingHistory(false);
  }, []);

  // Persist provider + thinking toggle to localStorage
  useEffect(() => {
    localStorage.setItem("ta_chat_provider", provider);
  }, [provider]);
  useEffect(() => {
    localStorage.setItem("ta_chat_think_on", thinkingEnabled ? "1" : "0");
  }, [thinkingEnabled]);

  useEffect(() => {
    void (async () => {
      try {
        const s = await api.getModelSetup();
        setSetup(s);
        setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? 2)));
        setDeepReadEnabled(Boolean(s.deep_read_enabled ?? true));
        setDeepReadMaxArticles(
          Math.max(1, Math.min(8, s.deep_read_max_articles ?? 3)),
        );
      } catch {
        /* offline */
      }
      void refreshSessions();
    })();
  }, [refreshSessions]);

  useEffect(() => {
    if (activeSession) {
      void (async () => {
        try {
          const msgs = (await api.getChatMessages(
            activeSession.id,
          )) as ChatMsg[];
          try {
            const local = localStorage.getItem(
              `chat_trace_${activeSession.id}`,
            );
            if (local) {
              const traces = JSON.parse(local);
              msgs.forEach((m, i) => {
                if (traces[i]) {
                  m.html = traces[i].html;
                  m.processTrace = traces[i].processTrace;
                }
              });
            }
          } catch {}
          setMessages(msgs);
        } catch {
          setMessages([]);
        }
      })();
    } else {
      setMessages([]);
    }
  }, [activeSession]);

  // Attach a scroll listener to detect when the user scrolls up manually.
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      // Consider "scrolled up" if more than 80px from the bottom.
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = distFromBottom > 80;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Force-scroll when new committed messages arrive (user sent / assistant done).
  useEffect(() => {
    scrollToBottom(true);
  }, [messages, scrollToBottom]);

  // Auto-scroll during streaming: tokens and trace logs.
  useEffect(() => {
    if (sending) scrollToBottom();
  }, [streamingContent, liveTraceLogs, sending, scrollToBottom]);

  // Auto-collapse sidebar when a conversation begins
  useEffect(() => {
    if (messages.length > 0) setSidebarOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length > 0]);

  const hasKeys =
    setup &&
    (setup.openai_configured ||
      setup.gemini_configured ||
      !!setup.local_model_path);

  async function startNewChat() {
    if (sending) return;
    try {
      const s = await api.createChatSession();
      setActiveSession(s);
      setSessions([s, ...sessions]);
      setSidebarOpen(false);
    } catch {
      notify("err", "Failed to create new chat session.");
    }
  }

  async function deleteSession(id: number) {
    try {
      await api.deleteChatSession(id);
      setSessions(sessions.filter((s) => s.id !== id));
      if (activeSession?.id === id) setActiveSession(null);
      notify("ok", "Thread deleted.");
    } catch {
      notify("err", "Failed to delete thread.");
    }
  }

  async function updateThinkingLevel(next: number) {
    const clamped = Math.max(1, Math.min(5, next));
    setThinkingLevel(clamped);
    try {
      const s = await api.patchModelSetup({ thinking_level: clamped });
      setSetup(s);
      setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? clamped)));
    } catch {
      notify("err", "Failed to save thinking level.");
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
      setSetup(s);
      setDeepReadEnabled(Boolean(s.deep_read_enabled ?? enabled));
      setDeepReadMaxArticles(
        Math.max(1, Math.min(8, s.deep_read_max_articles ?? clamped)),
      );
    } catch {
      notify("err", "Failed to save Reading mode settings.");
    }
  }

  async function send(raw: string) {
    const text = raw.trim();
    if (!text || sending) return;
    if (!hasKeys) {
      notify("err", "Add an API key under Model Setup first.");
      return;
    }

    let targetSession = activeSession;
    if (!targetSession) {
      try {
        targetSession = await api.createChatSession();
        setActiveSession(targetSession);
        setSessions([targetSession, ...sessions]);
      } catch {
        notify("err", "Failed to initialize chat session.");
        return;
      }
    }

    const next: ChatMsg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setSending(true);
    setSidebarOpen(false);
    setPhase("thinking");
    setQuery(undefined);
    userScrolledUpRef.current = false; // always follow the stream on a new send
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const startedAt = Date.now();
    setLiveTraceStartedAt(startedAt);
    setStreamingContent("");
    setLiveTraceLogs([]);
    setLiveTraceSources([]);
    setLiveTraceReading([]);
    logBufferRef.current = [];
    if (logRafRef.current !== null) {
      window.cancelAnimationFrame(logRafRef.current);
      logRafRef.current = null;
    }

    abortControllerRef.current = new AbortController();
    const traceLogs: string[] = [];
    const traceSources: { title: string; link: string; snippet: string }[] = [];
    const traceReading: {
      title?: string;
      url?: string;
      status: "started" | "completed" | "skipped";
    }[] = [];

    try {
      const effectiveThinkingLevel = thinkingEnabled ? thinkingLevel : 1;
      const chatMode: "chat" | "search" = isCasualMessage(text)
        ? "chat"
        : "search";

      await api.chatStream(
        {
          messages: next,
          mode: chatMode,
          provider,
          session_id: targetSession.id,
          thinking_level: effectiveThinkingLevel,
        },
        {
          onStatus: (p, q, m) => {
            setPhase(p);
            setQuery(q);
            if (m) {
              traceLogs.push(m);
              enqueueLog(m);
            }
          },
          onProcess: (message, p) => {
            if (p === "reading") setPhase("reading");
            if (!message) return;
            traceLogs.push(message);
            enqueueLog(message);
          },
          onReading: (meta) => {
            setPhase("reading");
            const item = {
              title: meta.title,
              url: meta.url,
              status: meta.status,
            };
            traceReading.push(item);
            setLiveTraceReading((prev) => [...prev, item]);
          },
          onSources: (res) => {
            traceSources.push(...res);
            setLiveTraceSources((prev) => {
              const seen = new Set(prev.map((p) => p.link));
              const merged = [...prev];
              for (const r of res) {
                if (!seen.has(r.link)) {
                  seen.add(r.link);
                  merged.push(r);
                }
              }
              return merged;
            });
          },
          onToken: (text) => {
            setStreamingContent((prev) => prev + text);
          },
          onDone: (reply, html) => {
            setStreamingContent("");
            const trace: ProcessTrace = {
              logs: traceLogs,
              sources: traceSources,
              reading: traceReading,
              durationSec: Math.max(0, (Date.now() - startedAt) / 1000),
            };
            const finalMsgs: ChatMsg[] = [
              ...next,
              { role: "assistant", content: reply, html, processTrace: trace },
            ];
            setMessages(finalMsgs);
            if (targetSession) saveTraceToLocal(targetSession.id, finalMsgs);
            setSending(false);
            void refreshSessions();
          },
          onError: (msg) => {
            setStreamingContent("");
            notify("err", msg);
            setSending(false);
          },
        },
        abortControllerRef.current.signal,
      );

      setMessages((prev) => {
        const lastIdx = prev.length - 1;
        const last = prev[lastIdx];
        if (!last || last.role !== "assistant" || last.processTrace)
          return prev;
        const copy = [...prev];
        copy[lastIdx] = {
          ...last,
          processTrace: {
            logs: traceLogs,
            sources: traceSources,
            reading: traceReading,
            durationSec: Math.max(0, (Date.now() - startedAt) / 1000),
          },
        };
        if (targetSession) saveTraceToLocal(targetSession.id, copy);
        return copy;
      });
    } catch (e) {
      setSending(false);
      notify("err", e instanceof Error ? e.message : "Request failed.");
    }
  }

  function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    void send(input);
  }

  const STARTERS = [
    "What regulatory or macro signals should I watch for my sector this quarter?",
    "List competitor angles I should monitor and how to track them cheaply.",
    "What customer trends could disrupt my products in the next 12 months?",
  ];

  return (
    <div className="flex w-full h-[calc(100vh-120px)] overflow-hidden animate-slide-in-up gap-3">
      {/* ── Sidebar: slides in/out, doesn't push layout when closed ── */}
      <aside
        className={cn(
          "flex-shrink-0 flex flex-col transition-all duration-300 ease-in-out overflow-hidden",
          sidebarOpen
            ? "w-56 opacity-100"
            : "w-0 opacity-0 pointer-events-none",
        )}
      >
        <div className="w-56 h-full glass-card rounded-2xl flex flex-col overflow-hidden">
          <div className="p-3 border-b border-white/[0.05] flex items-center gap-2">
            <button
              onClick={startNewChat}
              disabled={sending}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-accent/10 border border-accent/20 px-3 py-2 text-xs font-bold text-accent hover:bg-accent/20 transition-all"
            >
              <Plus size={13} /> New
            </button>
            <button
              onClick={() => setSidebarOpen(false)}
              className="p-1.5 rounded-lg text-slate-600 hover:text-slate-300 hover:bg-white/[0.05] transition-all"
            >
              <X size={13} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            <div className="px-2 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-600 flex items-center gap-1.5">
              <History size={9} /> History
            </div>
            {loadingHistory ? (
              <div className="text-center py-6 text-slate-600 text-xs italic">
                Loading…
              </div>
            ) : sessions.length === 0 ? (
              <div className="text-center py-6 text-slate-600 text-[11px] italic px-3">
                No threads yet.
              </div>
            ) : (
              sessions.map((s) => (
                <div key={s.id} className="group relative">
                  <button
                    onClick={() => {
                      setActiveSession(s);
                      setSidebarOpen(false);
                    }}
                    className={cn(
                      "w-full text-left rounded-lg px-2.5 py-2 text-[12px] transition-all flex items-center gap-2",
                      activeSession?.id === s.id
                        ? "bg-white/[0.07] text-white border border-white/10"
                        : "text-slate-400 hover:bg-white/[0.03] hover:text-slate-200",
                    )}
                  >
                    <MessageSquare
                      size={11}
                      className={cn(
                        "shrink-0",
                        activeSession?.id === s.id
                          ? "text-accent"
                          : "text-slate-600",
                      )}
                    />
                    <span className="truncate flex-1">{s.title}</span>
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDeleteSessionId(s.id);
                    }}
                    className="absolute right-1 top-1/2 -translate-y-1/2 p-1 opacity-0 group-hover:opacity-100 text-slate-600 hover:text-danger transition-all bg-surface-900/80 rounded"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </aside>

      {/* ── Main chat column ── */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0 glass-card rounded-2xl overflow-hidden">
        {/* Slim top bar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.05] shrink-0">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="p-1.5 rounded-lg text-slate-500 hover:text-accent hover:bg-white/[0.05] transition-all shrink-0"
            title={sidebarOpen ? "Hide history" : "Show history"}
          >
            {sidebarOpen ? (
              <PanelLeftClose size={14} />
            ) : (
              <PanelLeftOpen size={14} />
            )}
          </button>

          <Sparkles size={12} className="text-accent shrink-0" />
          <span className="font-display text-sm font-bold text-white flex-1 min-w-0 truncate">
            Research Chat
          </span>
          {activeSession && (
            <span className="text-[10px] text-slate-600 font-mono shrink-0">
              #{activeSession.id}
            </span>
          )}

          {activeSession && (
            <button
              type="button"
              onClick={startNewChat}
              disabled={sending}
              className="flex items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1.5 text-[11px] font-medium text-slate-400 hover:text-accent hover:border-accent/30 hover:bg-accent/5 transition-all"
              title="New thread"
            >
              <Plus size={11} /> New
            </button>
          )}
        </div>

        {/* Message list — takes all remaining vertical space */}
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0"
        >
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6">
              <div className="mb-5 p-4 rounded-3xl bg-accent/5 border border-accent/10">
                <Bot size={40} className="text-accent/30" />
              </div>
              <h2 className="text-lg font-bold text-white mb-1.5">
                Ready to explore
              </h2>
              <p className="text-slate-500 text-sm max-w-md mb-6">
                Start a research thread or pick a starter below.
              </p>
              <div className="grid grid-cols-1 gap-2.5 w-full max-w-xl">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    disabled={sending || !hasKeys}
                    onClick={() => void send(s)}
                    className="group rounded-2xl border border-white/[0.06] bg-surface-800/40 px-4 py-3 text-left text-sm text-slate-400 transition-all hover:border-accent/25 hover:bg-accent/5 hover:text-slate-100 disabled:opacity-40"
                  >
                    <div className="flex items-center gap-3">
                      <span className="h-7 w-7 rounded-xl bg-white/[0.03] flex items-center justify-center text-accent/50 group-hover:text-accent group-hover:bg-accent/10 transition-all shrink-0">
                        ›
                      </span>
                      {s}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((m, i) => (
                <div key={`${i}-${m.role}`} className="space-y-1.5">
                  <Message m={m} />
                  {m.role === "assistant" && m.processTrace && (
                    <ProcessTracePanel
                      logs={m.processTrace.logs}
                      sources={m.processTrace.sources}
                      reading={m.processTrace.reading}
                      durationSec={m.processTrace.durationSec}
                      live={false}
                    />
                  )}
                </div>
              ))}
              {sending && (
                <ProcessTracePanel
                  logs={liveTraceLogs}
                  sources={liveTraceSources}
                  reading={liveTraceReading}
                  durationSec={(Date.now() - liveTraceStartedAt) / 1000}
                  live={true}
                />
              )}
              {sending && streamingContent && (
                <div className="flex gap-2 animate-slide-in-up">
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border mt-0.5 bg-gradient-to-br from-neural/20 to-surface-800 border-neural/20">
                    <Bot size={11} className="text-neural" />
                  </div>
                  <div className="flex-1 min-w-0 rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed shadow-lg border border-white/[0.07] bg-surface-800/95 text-slate-100">
                    <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-p:my-1.5">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {streamingContent}
                      </ReactMarkdown>
                    </div>
                    <span className="inline-block w-0.5 h-4 bg-accent ml-0.5 animate-pulse align-middle" />
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="border-t border-white/[0.05] bg-surface-900/30 px-3 py-3 shrink-0">
          <form onSubmit={onSubmit}>
            {/* Unified input container */}
            <div className="rounded-2xl border border-white/[0.1] bg-surface-800/80 input-glow transition-all focus-within:border-accent/30 focus-within:shadow-[0_0_0_1px_rgba(var(--color-accent)/0.15)]">
              {/* Textarea */}
              <textarea
                ref={textareaRef}
                id="chat-input"
                rows={1}
                disabled={sending || !hasKeys}
                className="w-full resize-none bg-transparent px-4 pt-3 pb-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none min-h-[48px] max-h-[180px]"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = e.target.scrollHeight + "px";
                }}
                placeholder={
                  hasKeys
                    ? "Ask anything about your market, competitors, trends…"
                    : "Configure an API key in Model Setup to start."
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(input);
                  }
                }}
              />

              {/* Toolbar row */}
              <div className="flex items-center gap-1.5 px-2 pb-2 pt-1">
                {/* Model selector */}
                <select
                  disabled={sending}
                  value={provider}
                  onChange={(e) =>
                    setProvider(e.target.value as typeof provider)
                  }
                  className="rounded-lg border border-white/[0.10] bg-surface-800 px-2 py-1 text-[11px] text-slate-200 hover:border-white/[0.20] transition-all cursor-pointer focus:outline-none"
                  title="Model"
                >
                  <option value="auto">Auto</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                  <option value="local">Local</option>
                </select>

                {/* Divider */}
                <span className="h-3.5 w-px bg-white/[0.08]" />

                {/* Think toggle + level */}
                <button
                  type="button"
                  disabled={sending}
                  onClick={() => setThinkingEnabled((v) => !v)}
                  className={cn(
                    "rounded-lg px-2 py-1 text-[11px] font-medium border transition-all",
                    thinkingEnabled
                      ? "bg-accent/10 border-accent/20 text-accent"
                      : "bg-transparent border-white/[0.07] text-slate-500 hover:text-slate-300",
                  )}
                  title="Toggle thinking depth"
                >
                  Think
                </button>
                {thinkingEnabled && (
                  <select
                    disabled={sending}
                    value={thinkingLevel}
                    onChange={(e) =>
                      void updateThinkingLevel(Number(e.target.value))
                    }
                    className="rounded-lg border border-accent/20 bg-surface-800 px-1.5 py-1 text-[11px] text-accent hover:border-accent/40 transition-all cursor-pointer focus:outline-none"
                    title="Thinking level"
                  >
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>
                        L{n}
                      </option>
                    ))}
                  </select>
                )}

                {/* Read toggle + sources */}
                <button
                  type="button"
                  disabled={sending}
                  onClick={() => void updateDeepRead(!deepReadEnabled)}
                  className={cn(
                    "rounded-lg px-2 py-1 text-[11px] font-medium border transition-all",
                    deepReadEnabled
                      ? "bg-neural/10 border-neural/20 text-neural"
                      : "bg-transparent border-white/[0.07] text-slate-500 hover:text-slate-300",
                  )}
                  title="Toggle deep reading"
                >
                  Read
                </button>
                {deepReadEnabled && (
                  <select
                    disabled={sending}
                    value={deepReadMaxArticles}
                    onChange={(e) =>
                      void updateDeepRead(
                        deepReadEnabled,
                        Number(e.target.value),
                      )
                    }
                    className="rounded-lg border border-neural/20 bg-surface-800 px-1.5 py-1 text-[11px] text-neural hover:border-neural/40 transition-all cursor-pointer focus:outline-none"
                    title="Sources to read"
                  >
                    {[1, 2, 3, 4, 5, 6, 8].map((n) => (
                      <option key={n} value={n}>
                        {n}s
                      </option>
                    ))}
                  </select>
                )}

                {/* Spacer */}
                <span className="flex-1" />

                {/* Hint */}
                <span className="hidden sm:inline text-[10px] text-slate-700">
                  ↵ Send · Shift+↵ newline
                </span>

                {/* Send / Stop */}
                {sending ? (
                  <button
                    type="button"
                    onClick={stopGeneration}
                    className="p-1.5 rounded-lg bg-surface-700 border border-white/10 text-slate-300 hover:text-danger hover:bg-danger/10 transition-all"
                    title="Stop"
                  >
                    <Square size={12} className="fill-current" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!hasKeys || !input.trim()}
                    className="p-1.5 rounded-lg bg-accent text-surface-900 shadow-glow-sm hover:shadow-glow disabled:opacity-40 transition-all"
                    title="Send"
                  >
                    <Send size={13} />
                  </button>
                )}
              </div>
            </div>
          </form>
        </div>
      </div>

      {/* Delete confirm modal */}
      {confirmDeleteSessionId !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/75 p-4 backdrop-blur-sm"
          onClick={() => setConfirmDeleteSessionId(null)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-white/[0.12] bg-surface-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-xl border border-danger/30 bg-danger/10 p-2">
                <AlertCircle size={16} className="text-danger" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">
                  Delete this thread?
                </h3>
                <p className="mt-1 text-xs text-slate-400">
                  This action cannot be undone.
                </p>
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDeleteSessionId(null)}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06] transition-all"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  const id = confirmDeleteSessionId;
                  setConfirmDeleteSessionId(null);
                  if (id !== null) void deleteSession(id);
                }}
                className="rounded-xl border border-danger/30 bg-danger/20 px-3 py-1.5 text-xs font-semibold text-danger hover:bg-danger/25 transition-all"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
