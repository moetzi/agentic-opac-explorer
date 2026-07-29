import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import {
  Settings, Cpu, Database, ArrowLeft, Check, Loader2, Trash2, RefreshCw, AlertTriangle,
} from "lucide-react";
import {
  getModes, setMode, getCacheStats, clearCache,
  type AgentConfig, type CacheStats,
} from "@/api";

/* Violet/glass palette shared with the chat UI. */
const C = {
  ink: "#1a1a2e",
  inkSoft: "#3d3b6e",
  violet: "#6c63ff",
  violetDeep: "#5b54e8",
  muted: "#7b7a9d",
};

const panel: React.CSSProperties = {
  background: "rgba(255,255,255,0.55)",
  backdropFilter: "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.82)",
  borderRadius: 20,
  boxShadow: "0 4px 24px rgba(108,99,255,0.09)",
};

const bg: React.CSSProperties = {
  background: `
    radial-gradient(ellipse 70% 55% at 10% 10%, rgba(167,139,250,0.26) 0%, transparent 58%),
    radial-gradient(ellipse 60% 52% at 90% 8%, rgba(147,197,253,0.18) 0%, transparent 52%),
    linear-gradient(140deg, #f3f1ff 0%, #ede9fe 30%, #e4e8ff 60%, #dbeafe 100%)
  `,
};

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl px-4 py-3" style={{ background: "rgba(108,99,255,0.07)", border: "1px solid rgba(108,99,255,0.16)" }}>
      <p style={{ fontSize: 11, color: C.muted, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase" }}>{label}</p>
      <p style={{ fontSize: 20, color: C.ink, fontWeight: 700, marginTop: 2 }}>{value}</p>
    </div>
  );
}

export default function Admin() {
  const [cfg, setCfg] = useState<AgentConfig | null>(null);
  const [selMode, setSelMode] = useState<string>("");
  const [selModel, setSelModel] = useState<string>("");
  const [applying, setApplying] = useState(false);
  const [cache, setCache] = useState<CacheStats | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const loadCache = useCallback(async () => {
    try { setCache(await getCacheStats()); } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const c = await getModes();
        setCfg(c);
        setSelMode(c.current_mode);
        setSelModel(c.current_model);
      } catch (e) {
        setMsg({ kind: "err", text: `Gagal memuat konfigurasi: ${(e as Error).message}` });
      }
      loadCache();
    })();
  }, [loadCache]);

  const dirty = !!cfg && (selMode !== cfg.current_mode || selModel !== cfg.current_model);
  const modelChanged = !!cfg && selModel !== cfg.current_model;

  const apply = useCallback(async () => {
    if (!cfg || !dirty) return;
    setApplying(true);
    setMsg(null);
    try {
      const next = await setMode({ mode: selMode, model: selModel });
      setCfg(next);
      setSelMode(next.current_mode);
      setSelModel(next.current_model);
      setMsg({ kind: "ok", text: `Aktif: ${next.current_mode} · ${next.current_model}` });
    } catch (e) {
      setMsg({ kind: "err", text: `Gagal switch: ${(e as Error).message}` });
    } finally {
      setApplying(false);
    }
  }, [cfg, dirty, selMode, selModel]);

  const onClearCache = useCallback(async () => {
    try {
      const r = await clearCache();
      setMsg({ kind: "ok", text: `Cache dibersihkan (${r.entries} entri tersisa).` });
      loadCache();
    } catch (e) {
      setMsg({ kind: "err", text: `Gagal clear cache: ${(e as Error).message}` });
    }
  }, [loadCache]);

  return (
    <div className="fixed inset-0 overflow-y-auto" style={{ fontFamily: "'Inter', sans-serif", ...bg }}>
      <div className="mx-auto w-full max-w-3xl px-5 py-8 flex flex-col gap-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "linear-gradient(135deg,#6c63ff,#a78bfa)" }}>
              <Settings size={19} color="white" />
            </div>
            <div>
              <h1 style={{ fontSize: 20, fontWeight: 800, color: C.ink, letterSpacing: "-0.01em" }}>Admin — Konfigurasi Agent</h1>
              <p style={{ fontSize: 12, color: C.muted }}>Ganti arsitektur workflow &amp; model LLM saat runtime</p>
            </div>
          </div>
          <Link to="/" className="flex items-center gap-1.5 px-3 py-2 rounded-xl font-semibold transition-all hover:scale-105"
            style={{ fontSize: 13, color: C.violetDeep, background: "rgba(108,99,255,0.08)", border: "1px solid rgba(108,99,255,0.22)" }}>
            <ArrowLeft size={15} /> Chat
          </Link>
        </div>

        {/* status message */}
        {msg && (
          <div className="rounded-xl px-4 py-3 flex items-center gap-2" style={{
            fontSize: 13, fontWeight: 600,
            color: msg.kind === "ok" ? "#166534" : "#b91c1c",
            background: msg.kind === "ok" ? "rgba(34,197,94,0.10)" : "rgba(220,38,38,0.08)",
            border: `1px solid ${msg.kind === "ok" ? "rgba(34,197,94,0.30)" : "rgba(220,38,38,0.30)"}`,
          }}>
            {msg.kind === "ok" ? <Check size={16} /> : <AlertTriangle size={16} />}
            {msg.text}
          </div>
        )}

        {/* Current status */}
        <div className="grid grid-cols-3 gap-3">
          <StatTile label="Mode aktif" value={cfg?.current_mode ?? "—"} />
          <StatTile label="Model aktif" value={cfg?.current_model ?? "—"} />
          <StatTile label="Provider" value={cfg?.provider ?? "—"} />
        </div>

        {/* Workflow mode */}
        <section style={panel} className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Cpu size={16} style={{ color: C.violet }} />
            <h2 style={{ fontSize: 14, fontWeight: 700, color: C.ink }}>Workflow Mode</h2>
          </div>
          <div className="flex flex-col gap-2">
            {cfg?.modes.map(m => {
              const active = selMode === m.key;
              return (
                <button key={m.key} onClick={() => setSelMode(m.key)}
                  className="text-left rounded-xl px-4 py-3 transition-all"
                  style={{
                    background: active ? "rgba(108,99,255,0.12)" : "rgba(255,255,255,0.5)",
                    border: active ? "1.5px solid #6c63ff" : "1px solid rgba(108,99,255,0.15)",
                  }}>
                  <div className="flex items-center justify-between">
                    <span style={{ fontSize: 14, fontWeight: 700, color: C.ink }}>{m.label}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: C.muted, fontFamily: "monospace" }}>{m.key}</span>
                  </div>
                  <p style={{ fontSize: 12, color: C.inkSoft, marginTop: 3, lineHeight: 1.5 }}>{m.description}</p>
                </button>
              );
            })}
          </div>
        </section>

        {/* Model */}
        <section style={panel} className="p-5">
          <div className="flex items-center gap-2 mb-1">
            <Database size={16} style={{ color: C.violet }} />
            <h2 style={{ fontSize: 14, fontWeight: 700, color: C.ink }}>Model LLM</h2>
          </div>
          <p style={{ fontSize: 12, color: C.muted, marginBottom: 12 }}>
            Ganti model akan meng-evict model lama dari VRAM GPU (butuh beberapa detik).
          </p>
          <div className="flex gap-2 flex-wrap">
            {cfg?.models.map(md => {
              const active = selModel === md;
              return (
                <button key={md} onClick={() => setSelModel(md)}
                  className="px-4 py-2.5 rounded-xl font-semibold transition-all hover:scale-[1.02]"
                  style={{
                    fontSize: 13,
                    color: active ? "#fff" : C.inkSoft,
                    background: active ? C.violetDeep : "rgba(255,255,255,0.6)",
                    border: active ? "none" : "1px solid rgba(108,99,255,0.22)",
                    boxShadow: active ? "0 2px 10px rgba(91,84,232,0.3)" : "none",
                  }}>
                  {md}
                </button>
              );
            })}
          </div>
        </section>

        {/* Apply */}
        <button onClick={apply} disabled={!dirty || applying}
          className="rounded-2xl py-4 font-bold transition-all flex items-center justify-center gap-2"
          style={{
            fontSize: 15, color: "#fff",
            background: !dirty || applying ? "rgba(108,99,255,0.35)" : "#5b54e8",
            boxShadow: !dirty || applying ? "none" : "0 4px 18px rgba(91,84,232,0.4)",
            cursor: !dirty || applying ? "not-allowed" : "pointer",
          }}>
          {applying
            ? <><Loader2 size={17} className="animate-spin" /> {modelChanged ? "Switching model (VRAM)…" : "Menerapkan…"}</>
            : <>Terapkan Perubahan</>}
        </button>

        {/* Cache */}
        <section style={panel} className="p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Database size={16} style={{ color: C.violet }} />
              <h2 style={{ fontSize: 14, fontWeight: 700, color: C.ink }}>Response Cache</h2>
            </div>
            <div className="flex gap-2">
              <button onClick={loadCache} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold"
                style={{ fontSize: 12, color: C.violetDeep, background: "rgba(108,99,255,0.08)", border: "1px solid rgba(108,99,255,0.2)" }}>
                <RefreshCw size={13} /> Refresh
              </button>
              <button onClick={onClearCache} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold"
                style={{ fontSize: 12, color: "#b91c1c", background: "rgba(220,38,38,0.08)", border: "1px solid rgba(220,38,38,0.25)" }}>
                <Trash2 size={13} /> Clear
              </button>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <StatTile label="Entri" value={cache?.entries ?? "—"} />
            <StatTile label="Hits" value={cache?.hits ?? "—"} />
            <StatTile label="Misses" value={cache?.misses ?? "—"} />
          </div>
        </section>

        <p style={{ fontSize: 11, color: C.muted, textAlign: "center" }}>
          Cache & hasil di-namespace per (mode, model) — hasil satu konfigurasi tidak bocor ke konfigurasi lain.
        </p>
      </div>
    </div>
  );
}
