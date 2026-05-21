import { useEffect, useState } from "react";
import { Brain, Save } from "lucide-react";
import { api } from "../api";

export function InstructionsPanel({ notify }: { notify: (t: "ok" | "err", m: string) => void }) {
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const r = await api.getInstructions();
        setBody(r.body);
      } catch (e) { notify("err", e instanceof Error ? e.message : "Load failed."); }
      setLoading(false);
    })();
  }, [notify]);

  async function save() {
    try {
      await api.putInstructions(body);
      notify("ok", "Instructions updated.");
    } catch (e) { notify("err", e instanceof Error ? e.message : "Save failed."); }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 animate-slide-in-up">
      <header className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent/20 to-neural/10 border border-accent/15">
          <Brain size={20} className="text-accent" />
        </div>
        <div>
          <h1 className="font-display text-2xl font-bold text-white">Standing Instructions</h1>
          <p className="text-sm text-slate-500">Guidance wired into every reasoning pass</p>
        </div>
      </header>

      {loading ? (
        <div className="glass-card rounded-2xl p-8 text-center text-slate-500">Loading…</div>
      ) : (
        <div className="glass-card space-y-4 rounded-2xl p-6">
          <p className="text-xs text-slate-500 leading-relaxed">
            Instructions are injected into every analysis run. Use this to define pricing rules,
            competitor names, regulatory terms, vocabulary to avoid, or any standing context.
          </p>
          <textarea
            rows={10}
            className="w-full rounded-xl border border-white/[0.08] bg-surface-800/80 px-4 py-3 font-mono text-sm text-slate-100 input-glow placeholder:text-slate-600 resize-y min-h-[14rem] transition-all"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={"Focus on fuel price trends in East Africa.\nAlert if crude oil moves >5% in a week.\nIgnore cryptocurrency news unless it affects logistics costs."}
          />
          <button
            type="button"
            onClick={() => void save()}
            className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-glow px-6 py-2.5 text-sm font-bold text-surface-900 shadow-glow-sm hover:shadow-glow transition-all"
          >
            <Save size={15} /> Save instructions
          </button>
        </div>
      )}
    </div>
  );
}
