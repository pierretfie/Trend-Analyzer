import { FormEvent, useEffect, useState } from "react";
import { Building2, Save } from "lucide-react";
import { api } from "../api";

const field = "mt-2 w-full rounded-xl border border-white/[0.08] bg-surface-800/80 px-4 py-2.5 text-sm text-slate-100 input-glow placeholder:text-slate-600 transition-all";

export function BusinessPanel({ notify }: { notify: (t: "ok" | "err", m: string) => void }) {
  const [name, setName] = useState("");
  const [sector, setSector] = useState("");
  const [region, setRegion] = useState("");
  const [products, setProducts] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const c = await api.getCompany();
        setName(c.name ?? ""); setSector(c.sector ?? ""); setRegion(c.region ?? "");
        setProducts(c.products ?? ""); setNotes(c.notes ?? "");
      } catch (e) { notify("err", e instanceof Error ? e.message : "Failed to load profile."); }
      setLoading(false);
    })();
  }, []);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.patchCompany({ name, sector, region, products, notes });
      notify("ok", "Business profile saved.");
    } catch (e) { notify("err", e instanceof Error ? e.message : "Save failed."); }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6 animate-slide-in-up">
      <header className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-neural/20 to-accent/10 border border-neural/20">
          <Building2 size={20} className="text-neural" />
        </div>
        <div>
          <h1 className="font-display text-2xl font-bold text-white">Business Profile</h1>
          <p className="text-sm text-slate-500">Grounds AI analysis in your operation</p>
        </div>
      </header>

      {loading ? (
        <div className="glass-card rounded-2xl p-8 text-center text-slate-500">Loading…</div>
      ) : (
        <form onSubmit={onSubmit} className="glass-card space-y-4 rounded-2xl p-6">
          {[
            { label: "Business name", val: name, set: setName, ph: "e.g. Northside Fuels" },
            { label: "Sector / industry", val: sector, set: setSector, ph: "Fuel retail / logistics" },
            { label: "Primary region", val: region, set: setRegion, ph: "Country or metro" },
          ].map(({ label, val, set, ph }) => (
            <label key={label} className="block">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</span>
              <input className={field} value={val} onChange={(e) => set(e.target.value)} placeholder={ph} />
            </label>
          ))}
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Products & services</span>
            <textarea rows={3} className={`${field} resize-y min-h-[5rem]`} value={products} onChange={(e) => setProducts(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Notes</span>
            <textarea rows={2} className={`${field} resize-y min-h-[3.5rem]`} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <button type="submit" className="btn-glow flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-glow px-6 py-2.5 text-sm font-bold text-surface-900 shadow-glow-sm hover:shadow-glow transition-all">
            <Save size={15} /> Save profile
          </button>
        </form>
      )}
    </div>
  );
}
