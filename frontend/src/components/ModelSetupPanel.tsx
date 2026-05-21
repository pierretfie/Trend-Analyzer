import { FormEvent, useEffect, useState } from "react";
import {
  Settings2,
  CheckCircle2,
  XCircle,
  Save,
  Search,
  Cpu,
} from "lucide-react";
import type { ModelSetup } from "../api";
import { api } from "../api";

function cn(...p: Array<string | false | undefined>) {
  return p.filter(Boolean).join(" ");
}

const field =
  "mt-2 w-full rounded-xl border border-white/[0.08] bg-surface-800/80 px-4 py-2.5 font-mono text-sm text-slate-100 input-glow placeholder:text-slate-600 transition-all";

export function ModelSetupPanel({
  notify,
}: {
  notify: (t: "ok" | "err", m: string) => void;
}) {
  const [setup, setSetup] = useState<ModelSetup | null>(null);
  const [loading, setLoading] = useState(true);

  // LLM key fields
  const [openaiKey, setOpenaiKey] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [provider, setProvider] = useState<ModelSetup["llm_provider"]>("none");
  const [geminiModel, setGeminiModel] = useState("gemini-2.5-flash");

  // Google Search fields
  const [googleKey, setGoogleKey] = useState("");
  const [googleCx, setGoogleCx] = useState("");
  const [googleSearchEnabled, setGoogleSearchEnabled] = useState(true);
  const [serpapiKey, setSerpapiKey] = useState("");
  const [serpapiEngine, setSerpapiEngine] = useState("bing");
  const [serpapiSearchEnabled, setSerpapiSearchEnabled] = useState(false);
  const [firecrawlKey, setFirecrawlKey] = useState("");
  const [firecrawlSearchEnabled, setFirecrawlSearchEnabled] = useState(false);
  const [ddgSearchEnabled, setDdgSearchEnabled] = useState(false);
  const [ddgRegion, setDdgRegion] = useState("wt-wt");
  const [ddgTimelimit, setDdgTimelimit] = useState("");
  const [thinkingLevel, setThinkingLevel] = useState(2);
  const [showPurgeConfirm, setShowPurgeConfirm] = useState(false);
  const [purging, setPurging] = useState(false);

  // Local GGUF model fields
  const [localModelPath, setLocalModelPath] = useState("");
  const [localNCtx, setLocalNCtx] = useState(4096);
  const [localNGpuLayers, setLocalNGpuLayers] = useState(0);
  const [localScanDir, setLocalScanDir] = useState("");
  const [localScanResults, setLocalScanResults] = useState<
    { name: string; path: string; size_mb: number }[]
  >([]);
  const [localScanning, setLocalScanning] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const s = await api.getModelSetup();
        setSetup(s);
        setProvider(s.llm_provider);
        setGeminiModel(s.gemini_model ?? "gemini-2.5-flash");
        setGoogleCx(s.google_cx ?? "");
        setGoogleSearchEnabled(Boolean(s.google_search_enabled));
        setSerpapiEngine(s.serpapi_engine ?? "bing");
        setSerpapiSearchEnabled(Boolean(s.serpapi_search_enabled));
        setFirecrawlSearchEnabled(Boolean(s.firecrawl_search_enabled));
        setDdgSearchEnabled(Boolean(s.ddg_search_enabled));
        setDdgRegion(s.ddg_region ?? "wt-wt");
        setDdgTimelimit(s.ddg_timelimit ?? "");
        setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? 2)));
        setLocalModelPath(s.local_model_path ?? "");
        setLocalNCtx(Math.max(512, s.local_n_ctx ?? 4096));
        setLocalNGpuLayers(s.local_n_gpu_layers ?? 0);
      } catch (e) {
        notify(
          "err",
          e instanceof Error ? e.message : "Failed to load model settings.",
        );
      }
      setLoading(false);
    })();
  }, [notify]);

  async function saveLlmKeys(ev: FormEvent) {
    ev.preventDefault();
    const patch: Parameters<typeof api.patchModelSetup>[0] = {};
    if (openaiKey.trim()) patch.openai_api_key = openaiKey.trim();
    if (geminiKey.trim()) patch.gemini_api_key = geminiKey.trim();
    if (!openaiKey.trim() && !geminiKey.trim()) {
      notify("err", "Paste at least one API key.");
      return;
    }
    try {
      const s = await api.patchModelSetup(patch);
      setSetup(s);
      setOpenaiKey("");
      setGeminiKey("");
      notify("ok", "API keys saved.");
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Save failed.");
    }
  }

  async function saveSearchSettings(ev: FormEvent) {
    ev.preventDefault();
    try {
      const patch: Parameters<typeof api.patchModelSetup>[0] = {};
      if (googleKey.trim()) patch.google_api_key = googleKey.trim();
      if (googleCx.trim()) patch.google_cx = googleCx.trim();
      if (serpapiKey.trim()) patch.serpapi_api_key = serpapiKey.trim();
      patch.google_search_enabled = googleSearchEnabled;
      patch.serpapi_engine = serpapiEngine.trim() || "bing";
      patch.serpapi_search_enabled = serpapiSearchEnabled;
      if (firecrawlKey.trim()) patch.firecrawl_api_key = firecrawlKey.trim();
      patch.firecrawl_search_enabled = firecrawlSearchEnabled;
      patch.ddg_search_enabled = ddgSearchEnabled;
      patch.ddg_region = ddgRegion.trim() || "wt-wt";
      patch.ddg_timelimit = ddgTimelimit.trim();
      const s = await api.patchModelSetup(patch);
      setSetup(s);
      setGoogleKey("");
      setSerpapiKey("");
      setGoogleCx(s.google_cx ?? "");
      setGoogleSearchEnabled(Boolean(s.google_search_enabled));
      setSerpapiEngine(s.serpapi_engine ?? "bing");
      setSerpapiSearchEnabled(Boolean(s.serpapi_search_enabled));
      setFirecrawlSearchEnabled(Boolean(s.firecrawl_search_enabled));
      setFirecrawlKey("");
      setDdgSearchEnabled(Boolean(s.ddg_search_enabled));
      setDdgRegion(s.ddg_region ?? "wt-wt");
      setDdgTimelimit(s.ddg_timelimit ?? "");
      notify("ok", "Search tool settings saved.");
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Save failed.");
    }
  }

  async function saveProvider(next: ModelSetup["llm_provider"]) {
    try {
      const s = await api.patchModelSetup({ llm_provider: next });
      setSetup(s);
      setProvider(s.llm_provider);
      notify("ok", "Default provider updated.");
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Update failed.");
    }
  }

  async function saveGeminiModel(model: string) {
    try {
      const s = await api.patchModelSetup({ gemini_model: model });
      setSetup(s);
      setGeminiModel(s.gemini_model ?? model);
      notify("ok", `Gemini model set to ${model}.`);
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Update failed.");
    }
  }

  async function purgeResearchData() {
    setPurging(true);
    try {
      const r = await fetch("/api/research-data", { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as { total: number };
      setShowPurgeConfirm(false);
      notify(
        "ok",
        `Cleared ${data.total} records. Credentials and profile kept.`,
      );
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Purge failed.");
    } finally {
      setPurging(false);
    }
  }

  async function saveThinkingLevel(next: number) {
    try {
      const s = await api.patchModelSetup({ thinking_level: next });
      setSetup(s);
      setThinkingLevel(Math.max(1, Math.min(5, s.thinking_level ?? next)));
      notify("ok", "Autonomous thinking level updated.");
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Update failed.");
    }
  }

  async function clearKey(
    which: "openai" | "gemini" | "google" | "serpapi" | "firecrawl",
  ) {
    const label =
      which === "openai"
        ? "OpenAI"
        : which === "gemini"
          ? "Gemini"
          : which === "google"
            ? "Google Search"
            : which === "serpapi"
              ? "SerpAPI"
              : "Firecrawl";
    if (!window.confirm(`Remove the saved ${label} key?`)) return;
    try {
      const patch =
        which === "openai"
          ? { openai_api_key: "" }
          : which === "gemini"
            ? { gemini_api_key: "" }
            : which === "google"
              ? { google_api_key: "" }
              : which === "firecrawl"
                ? { firecrawl_api_key: "" }
                : { serpapi_api_key: "" };
      const s = await api.patchModelSetup(patch);
      setSetup(s);
      if (which === "openai") setOpenaiKey("");
      if (which === "gemini") setGeminiKey("");
      if (which === "google") {
        setGoogleKey("");
        setGoogleCx(s.google_cx ?? "");
      }
      if (which === "serpapi") {
        setSerpapiKey("");
        setSerpapiEngine(s.serpapi_engine ?? "bing");
      }
      if (which === "firecrawl") {
        setFirecrawlKey("");
      }
      notify("ok", `${label} key cleared.`);
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Clear failed.");
    }
  }

  async function saveLocalModel(ev: FormEvent) {
    ev.preventDefault();
    if (!localModelPath.trim()) {
      notify("err", "Paste or select a path to a .gguf model file.");
      return;
    }
    try {
      const s = await api.patchModelSetup({
        local_model_path: localModelPath.trim(),
        local_n_ctx: localNCtx,
        local_n_gpu_layers: localNGpuLayers,
      });
      setSetup(s);
      setLocalModelPath(s.local_model_path ?? "");
      setLocalNCtx(s.local_n_ctx ?? 4096);
      setLocalNGpuLayers(s.local_n_gpu_layers ?? 0);
      notify("ok", "Local model settings saved.");
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Save failed.");
    }
  }

  async function scanForModels() {
    setLocalScanning(true);
    setLocalScanResults([]);
    try {
      const result = await api.listLocalModels(
        localScanDir.trim() || undefined,
      );
      setLocalScanResults(result.models);
      if (result.models.length === 0) {
        notify("err", `No .gguf files found in ${result.directory}`);
      }
    } catch (e) {
      notify("err", e instanceof Error ? e.message : "Scan failed.");
    } finally {
      setLocalScanning(false);
    }
  }

  const PROVIDERS = [
    ["none", "None yet"],
    ["openai", "OpenAI"],
    ["gemini", "Gemini"],
    ["local", "Local GGUF"],
  ] as const;

  return (
    <div className="mx-auto max-w-xl space-y-6 animate-slide-in-up">
      <header className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-neural/20 to-accent/10 border border-neural/20">
          <Settings2 size={20} className="text-neural" />
        </div>
        <div>
          <h1 className="font-display text-2xl font-bold text-white">
            Model Setup
          </h1>
          <p className="text-sm text-slate-500">
            Keys stored only in local SQLite
          </p>
        </div>
      </header>

      {loading ? (
        <div className="glass-card rounded-2xl p-8 text-center text-slate-500">
          Loading…
        </div>
      ) : (
        <>
          {/* ── Default LLM Provider ── */}
          <section className="glass-card rounded-2xl p-5 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Default LLM Provider
            </h2>
            <div className="flex flex-wrap gap-2">
              {PROVIDERS.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => void saveProvider(id)}
                  className={cn(
                    "btn-glow rounded-xl px-4 py-2 text-sm font-semibold transition-all",
                    provider === id
                      ? "bg-gradient-to-r from-accent to-accent-glow text-surface-900 shadow-glow-sm"
                      : "border border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* ── LLM API Keys ── */}
          <form
            onSubmit={saveLlmKeys}
            className="glass-card space-y-5 rounded-2xl p-5"
          >
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              LLM API Keys
            </h2>

            {(["openai", "gemini"] as const).map((which) => {
              const isOpenai = which === "openai";
              const configured = isOpenai
                ? setup?.openai_configured
                : setup?.gemini_configured;
              const masked = isOpenai
                ? setup?.openai_masked
                : setup?.gemini_masked;
              const val = isOpenai ? openaiKey : geminiKey;
              const set = isOpenai ? setOpenaiKey : setGeminiKey;
              const label = isOpenai
                ? "OpenAI API Key"
                : "Google Gemini API Key";
              const ph = isOpenai ? "sk-…" : "AIza…";
              return (
                <div key={which} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-300">
                      {label}
                    </label>
                    {configured ? (
                      <span className="flex items-center gap-1 text-xs text-accent/90 font-mono">
                        <CheckCircle2 size={11} /> Saved{" "}
                        {masked ? `(${masked})` : ""}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-xs text-slate-600">
                        <XCircle size={11} /> Not set
                      </span>
                    )}
                  </div>
                  <input
                    className={field}
                    type="password"
                    autoComplete="off"
                    value={val}
                    onChange={(e) => set(e.target.value)}
                    placeholder={ph}
                  />
                  {configured && (
                    <button
                      type="button"
                      onClick={() => void clearKey(which)}
                      className="text-xs text-danger/70 hover:text-danger transition"
                    >
                      Clear saved key
                    </button>
                  )}
                </div>
              );
            })}

            <button
              type="submit"
              className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-glow px-6 py-2.5 text-sm font-bold text-surface-900 shadow-glow-sm hover:shadow-glow transition-all"
            >
              <Save size={15} /> Save LLM keys
            </button>
          </form>

          {/* ── Gemini Model Selector ── */}
          {(setup?.gemini_configured || provider === "gemini") && (
            <section className="glass-card rounded-2xl p-5 space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Gemini Model
              </h2>
              <div className="flex flex-wrap gap-2">
                {[
                  {
                    id: "gemini-2.5-flash-lite",
                    label: "Flash Lite",
                    hint: "Fastest · lowest cost",
                  },
                  {
                    id: "gemini-2.5-flash",
                    label: "Flash",
                    hint: "Balanced · recommended",
                  },
                  { id: "gemini-2.5-pro", label: "Pro", hint: "Most capable" },
                ].map(({ id, label, hint }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => void saveGeminiModel(id)}
                    className={cn(
                      "flex flex-col items-start rounded-xl px-4 py-2.5 text-left transition-all btn-glow border",
                      geminiModel === id
                        ? "bg-gradient-to-br from-neural/20 to-accent/10 border-neural/30 shadow-glow-neural"
                        : "border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06]",
                    )}
                  >
                    <span
                      className={cn(
                        "text-sm font-bold",
                        geminiModel === id ? "text-white" : "text-slate-300",
                      )}
                    >
                      {label}
                    </span>
                    <span className="text-[10px] text-slate-500 mt-0.5">
                      {hint}
                    </span>
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-slate-600">
                Active:{" "}
                <span className="font-mono text-slate-400">{geminiModel}</span>
              </p>
            </section>
          )}

          {/* ── Google Search ── */}
          <form
            onSubmit={saveSearchSettings}
            className="glass-card space-y-5 rounded-2xl p-5"
          >
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-500/10 border border-blue-500/20">
                <Search size={13} className="text-blue-400" />
              </div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Search Tools
              </h2>
            </div>

            <p className="text-xs text-slate-500 leading-relaxed">
              Enable one or more tools for live web research. You can toggle
              tools on/off without deleting keys.
            </p>

            <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
                <span>Enable Google Custom Search</span>
                <input
                  type="checkbox"
                  checked={googleSearchEnabled}
                  onChange={(e) => setGoogleSearchEnabled(e.target.checked)}
                  className="h-4 w-4 accent-accent"
                />
              </label>
            </div>

            {/* API Key */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-slate-300">
                  Google API Key
                </label>
                {setup?.google_configured ? (
                  <span className="flex items-center gap-1 text-xs text-accent/90 font-mono">
                    <CheckCircle2 size={11} /> Saved{" "}
                    {setup.google_masked ? `(${setup.google_masked})` : ""}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-slate-600">
                    <XCircle size={11} /> Not set
                  </span>
                )}
              </div>
              <input
                className={field}
                type="password"
                autoComplete="off"
                value={googleKey}
                onChange={(e) => setGoogleKey(e.target.value)}
                placeholder="AIza…"
              />
              {setup?.google_configured && (
                <button
                  type="button"
                  onClick={() => void clearKey("google")}
                  className="text-xs text-danger/70 hover:text-danger transition"
                >
                  Clear saved key
                </button>
              )}
            </div>

            {/* CX / Search Engine ID */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-slate-300">
                  Search Engine ID{" "}
                  <span className="text-slate-600 font-normal">(cx)</span>
                </label>
                {googleCx && !googleKey ? (
                  <span className="flex items-center gap-1 text-xs text-accent/90 font-mono">
                    <CheckCircle2 size={11} /> Saved
                  </span>
                ) : null}
              </div>
              <input
                className={field}
                type="text"
                autoComplete="off"
                value={googleCx}
                onChange={(e) => setGoogleCx(e.target.value)}
                placeholder="e.g. 017576662512468239146:omuauf…"
              />
              <p className="text-[11px] text-slate-600">
                Tip: set the search engine to "Search the entire web" for best
                results.
              </p>
            </div>

            <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
                <span>Enable SerpAPI Search</span>
                <input
                  type="checkbox"
                  checked={serpapiSearchEnabled}
                  onChange={(e) => setSerpapiSearchEnabled(e.target.checked)}
                  className="h-4 w-4 accent-accent"
                />
              </label>
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-slate-300">
                  SerpAPI Key
                </label>
                {setup?.serpapi_configured ? (
                  <span className="flex items-center gap-1 text-xs text-accent/90 font-mono">
                    <CheckCircle2 size={11} /> Saved{" "}
                    {setup.serpapi_masked ? `(${setup.serpapi_masked})` : ""}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-slate-600">
                    <XCircle size={11} /> Not set
                  </span>
                )}
              </div>
              <input
                className={field}
                type="password"
                autoComplete="off"
                value={serpapiKey}
                onChange={(e) => setSerpapiKey(e.target.value)}
                placeholder="SerpAPI key"
              />
              {setup?.serpapi_configured && (
                <button
                  type="button"
                  onClick={() => void clearKey("serpapi")}
                  className="text-xs text-danger/70 hover:text-danger transition"
                >
                  Clear saved key
                </button>
              )}
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-300">
                SerpAPI engine
              </label>
              <input
                className={field}
                type="text"
                autoComplete="off"
                value={serpapiEngine}
                onChange={(e) => setSerpapiEngine(e.target.value)}
                placeholder="bing"
              />
              <p className="text-[11px] text-slate-600">
                Example: <span className="font-mono">bing</span>,{" "}
                <span className="font-mono">google</span>.
              </p>
            </div>

            {/* ── Firecrawl ── */}
            <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
                <span>Enable Firecrawl Search</span>
                <input
                  type="checkbox"
                  checked={firecrawlSearchEnabled}
                  onChange={(e) => setFirecrawlSearchEnabled(e.target.checked)}
                  className="h-4 w-4 accent-accent"
                />
              </label>
              <p className="mt-1 text-[11px] text-slate-500">
                Firecrawl returns full page content alongside search results —
                no separate deep-read step needed.
              </p>
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-slate-300">
                  Firecrawl API Key
                </label>
                {setup?.firecrawl_configured ? (
                  <span className="flex items-center gap-1 text-xs text-accent/90 font-mono">
                    <CheckCircle2 size={11} /> Saved{" "}
                    {setup.firecrawl_masked
                      ? `(${setup.firecrawl_masked})`
                      : ""}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-slate-600">
                    <XCircle size={11} /> Not set
                  </span>
                )}
              </div>
              <input
                className={field}
                type="password"
                autoComplete="off"
                value={firecrawlKey}
                onChange={(e) => setFirecrawlKey(e.target.value)}
                placeholder="fc-…"
              />
              {setup?.firecrawl_configured && (
                <button
                  type="button"
                  onClick={() => void clearKey("firecrawl")}
                  className="text-xs text-danger/70 hover:text-danger transition"
                >
                  Clear saved key
                </button>
              )}
            </div>

            {/* ── DuckDuckGo ── */}
            <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
                <span>Enable DuckDuckGo Search</span>
                <input
                  type="checkbox"
                  checked={ddgSearchEnabled}
                  onChange={(e) => setDdgSearchEnabled(e.target.checked)}
                  className="h-4 w-4 accent-accent"
                />
              </label>
              <p className="mt-1 text-[11px] text-slate-500">
                Free, no API key required. Uses the open-source{" "}
                <span className="font-mono">duckduckgo-search</span> library.
              </p>
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-300">
                DDG Region
              </label>
              <input
                className={field}
                type="text"
                autoComplete="off"
                value={ddgRegion}
                onChange={(e) => setDdgRegion(e.target.value)}
                placeholder="wt-wt"
              />
              <p className="text-[11px] text-slate-600">
                Worldwide: <span className="font-mono">wt-wt</span> · US:{" "}
                <span className="font-mono">us-en</span> · UK:{" "}
                <span className="font-mono">uk-en</span>
              </p>
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-300">
                DDG Time Limit
              </label>
              <select
                className={field}
                value={ddgTimelimit}
                onChange={(e) => setDdgTimelimit(e.target.value)}
              >
                <option value="">No limit</option>
                <option value="d">Past day</option>
                <option value="w">Past week</option>
                <option value="m">Past month</option>
                <option value="y">Past year</option>
              </select>
              <p className="text-[11px] text-slate-600">
                Restrict results to a recent time window.
              </p>
            </div>

            <button
              type="submit"
              className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-500/80 to-blue-400 px-6 py-2.5 text-sm font-bold text-white shadow-lg hover:shadow-blue-500/20 transition-all"
            >
              <Save size={15} /> Save search tool settings
            </button>
          </form>

          <section className="glass-card rounded-2xl p-5 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Autonomous Thinking Level
            </h2>
            <p className="text-xs text-slate-500">
              Controls refinement depth for scheduled research and "Run research
              now".
            </p>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={thinkingLevel}
                onChange={(e) => setThinkingLevel(Number(e.target.value))}
                className="w-full accent-accent"
              />
              <span className="w-10 text-right font-mono text-sm text-slate-300">
                L{thinkingLevel}
              </span>
            </div>
            <button
              type="button"
              onClick={() => void saveThinkingLevel(thinkingLevel)}
              className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-neural/80 to-accent/70 px-5 py-2 text-sm font-bold text-white shadow-glow-neural transition-all"
            >
              <Save size={14} /> Save thinking level
            </button>
          </section>

          {/* ── Local GGUF Model ── */}
          <form
            onSubmit={saveLocalModel}
            className="glass-card space-y-5 rounded-2xl p-5"
          >
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-purple-500/10 border border-purple-500/20">
                <Cpu size={13} className="text-purple-400" />
              </div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Local GGUF Model
              </h2>
            </div>

            <p className="text-xs text-slate-500 leading-relaxed">
              Run inference entirely offline using a local{" "}
              <span className="font-mono">.gguf</span> model file (requires{" "}
              <span className="font-mono">llama-cpp-python</span> installed).
              Select &ldquo;Local GGUF&rdquo; as the default provider above to
              use it.
            </p>

            {/* Scan directory */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-300">
                Scan directory for .gguf files
              </label>
              <div className="flex gap-2">
                <input
                  className={field + " flex-1"}
                  type="text"
                  value={localScanDir}
                  onChange={(e) => setLocalScanDir(e.target.value)}
                  placeholder="~/models  (leave blank for home directory)"
                />
                <button
                  type="button"
                  onClick={() => void scanForModels()}
                  disabled={localScanning}
                  className="btn-glow rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 py-2 text-sm font-semibold text-purple-300 hover:bg-purple-500/20 disabled:opacity-50 transition-all"
                >
                  {localScanning ? "Scanning\u2026" : "Scan"}
                </button>
              </div>
              {localScanResults.length > 0 && (
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] divide-y divide-white/[0.04] max-h-48 overflow-y-auto">
                  {localScanResults.map((m) => (
                    <button
                      key={m.path}
                      type="button"
                      onClick={() => setLocalModelPath(m.path)}
                      className="w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-white/[0.04] transition"
                    >
                      <div>
                        <p className="text-xs font-mono text-slate-200 truncate">
                          {m.name}
                        </p>
                        <p className="text-[10px] text-slate-500 truncate">
                          {m.path}
                        </p>
                      </div>
                      <span className="shrink-0 text-[10px] text-slate-500">
                        {m.size_mb} MB
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Model path */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-slate-300">
                  Model file path
                </label>
                {setup?.local_model_path ? (
                  <span className="flex items-center gap-1 text-xs text-accent/90 font-mono">
                    <CheckCircle2 size={11} /> Configured
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-slate-600">
                    <XCircle size={11} /> Not set
                  </span>
                )}
              </div>
              <input
                className={field}
                type="text"
                value={localModelPath}
                onChange={(e) => setLocalModelPath(e.target.value)}
                placeholder="/home/user/models/qwen2.5-coder-7b-instruct-q3_k_m.gguf"
              />
              {setup?.local_model_path && (
                <p className="text-[11px] text-slate-600 font-mono truncate">
                  Active: {setup.local_model_path}
                </p>
              )}
            </div>

            {/* Context window */}
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-300">
                Context window{" "}
                <span className="text-slate-500 font-normal">(n_ctx)</span>
              </label>
              <input
                className={field}
                type="number"
                min={512}
                max={131072}
                step={512}
                value={localNCtx}
                onChange={(e) =>
                  setLocalNCtx(Math.max(512, Number(e.target.value)))
                }
              />
              <p className="text-[11px] text-slate-600">
                Typical values: 4096, 8192, 16384. Higher = more memory.
              </p>
            </div>

            {/* GPU layers */}
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-300">
                GPU layers{" "}
                <span className="text-slate-500 font-normal">
                  (n_gpu_layers)
                </span>
              </label>
              <input
                className={field}
                type="number"
                min={-1}
                max={999}
                value={localNGpuLayers}
                onChange={(e) => setLocalNGpuLayers(Number(e.target.value))}
              />
              <p className="text-[11px] text-slate-600">
                <span className="font-mono">0</span> = CPU only &middot;{" "}
                <span className="font-mono">-1</span> = offload all layers to
                GPU &middot; positive = partial GPU offload.
              </p>
            </div>

            <button
              type="submit"
              className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-purple-600/80 to-purple-500 px-6 py-2.5 text-sm font-bold text-white shadow-lg hover:shadow-purple-500/20 transition-all"
            >
              <Save size={15} /> Save local model settings
            </button>
          </form>

          {/* ── Danger Zone ── */}
          <section className="glass-card rounded-2xl p-5 space-y-3 border border-danger/20">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-danger/70">
              Danger Zone
            </h2>
            <p className="text-xs text-slate-500 leading-relaxed">
              Permanently delete all research runs, reports, trends, analyses,
              predictions, and chat history. API keys, business profile,
              instructions, and schedules are kept.
            </p>
            <button
              type="button"
              onClick={() => setShowPurgeConfirm(true)}
              className="flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/10 px-4 py-2.5 text-sm font-semibold text-danger hover:bg-danger/20 transition-all"
            >
              Clear all research data
            </button>
          </section>

          {/* ── Purge confirmation modal ── */}
          {showPurgeConfirm && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-slide-in-up">
              <div className="glass-card w-full max-w-md rounded-2xl p-6 space-y-4 border border-danger/30 mx-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-danger/10 border border-danger/20">
                    <span className="text-danger text-lg">⚠</span>
                  </div>
                  <div>
                    <h3 className="font-display text-lg font-bold text-white">
                      Clear all research data?
                    </h3>
                    <p className="text-xs text-slate-500">
                      This cannot be undone.
                    </p>
                  </div>
                </div>
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 space-y-1 text-xs text-slate-400">
                  <p className="font-semibold text-slate-300 mb-1">
                    Will be deleted:
                  </p>
                  <p>• All research runs &amp; run history</p>
                  <p>• All trend reports</p>
                  <p>• All discovered trends &amp; AI analyses</p>
                  <p>• All predictions</p>
                  <p>• All chat sessions &amp; messages</p>
                  <p className="font-semibold text-accent mt-2">
                    Will be kept:
                  </p>
                  <p className="text-accent/80">
                    • API keys &amp; provider settings
                  </p>
                  <p className="text-accent/80">
                    • Business profile &amp; instructions
                  </p>
                  <p className="text-accent/80">• Research schedules</p>
                </div>
                <div className="flex gap-3 pt-1">
                  <button
                    type="button"
                    onClick={() => setShowPurgeConfirm(false)}
                    disabled={purging}
                    className="flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5 text-sm font-semibold text-slate-300 hover:bg-white/[0.08] disabled:opacity-50 transition"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void purgeResearchData()}
                    disabled={purging}
                    className="flex-1 rounded-xl bg-danger px-4 py-2.5 text-sm font-bold text-white hover:bg-danger/90 disabled:opacity-50 transition"
                  >
                    {purging ? "Clearing…" : "Yes, delete everything"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
