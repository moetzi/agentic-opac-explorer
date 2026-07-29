/* ─────────────────────────────────────────────────────────────────────────
 * api.ts — bridge between the React UI and the Agentic GraphRAG backend.
 *
 * The backend lives in `app_web/server.py` (FastAPI) and exposes:
 *     POST /api/query   { query, use_cache } → QueryResponse
 *     GET  /api/health
 *
 * In dev, Vite proxies `/api` → http://127.0.0.1:8001 (see vite.config.ts),
 * so we call relative URLs. Override with VITE_API_BASE for a remote backend.
 * ──────────────────────────────────────────────────────────────────────── */

// Vite injects import.meta.env at build time; typed locally so this file does
// not depend on a tsconfig picking up vite/client (the Figma export ships none).
const API_BASE = (
  (import.meta as unknown as { env?: Record<string, string | undefined> }).env
    ?.VITE_API_BASE ?? ""
).replace(/\/$/, "");

/* ─── Backend response shapes (mirror app_web/server.py) ─────────────────── */
interface BackendBookCard {
  book_id: string;
  title: string;
  authors: string[];
  categories: string[];
  vibes: string[];
  settings: string[];
  available_at: string[];
  is_available: boolean;
  relevance_score: number;
  cover_url: string;
  pub_year: number | null;
  synopsis: string | null;
}

interface BackendQueryResponse {
  answer: string;
  books: BackendBookCard[];
  elapsed: number;
  from_cache: boolean;
  intent: string | null;
  query_type: string | null;
  hop: number;
  traversal: string[];
  tool_chain: string[];
  reasoning: string[];
  violations: string[];
  error: string | null;
}

/* ─── UI-facing shapes (structurally match App.tsx CarouselBook / meta) ───── */
export interface AgentBook {
  title: string;
  author: string;
  vibe?: string;
  kategori?: string;
  location: string;
  cover: string;
  sinopsis?: string;
}

export interface AgentTrace {
  toolChain: string[];
  reasoning: string[];
  traversal: string[];
}

export interface AgentReply {
  text: string;
  books: AgentBook[];
  meta: { query_type: string; elapsed: number; hop: number };
  /* The agent's step-by-step "thinking": plan / tool calls / curation trace,
   * surfaced so the UI can show HOW an answer was reached. */
  trace: AgentTrace;
}

/* Placeholder cover used by the backend when a book has no image. */
const PLACEHOLDER_COVER =
  "https://kios-perpustakaan.jakarta.go.id/assets/img/no-images-jaklitera.png";

/* ─── Mapping: backend BookCard → UI CarouselBook ────────────────────────── */
function toAgentBook(b: BackendBookCard): AgentBook {
  const author = b.authors.length ? b.authors.join(", ") : "—";
  const vibe = b.vibes.length ? b.vibes.join(", ") : undefined;
  const kategori = b.categories.length ? b.categories.join(", ") : undefined;
  const location = b.available_at.length
    ? b.available_at.join(", ")
    : "Tidak tersedia di cabang mana pun";
  const cover = b.cover_url && b.cover_url.trim() ? b.cover_url : PLACEHOLDER_COVER;

  return {
    title: b.title,
    author,
    vibe,
    kategori,
    location,
    cover,
    sinopsis: b.synopsis ?? undefined,
  };
}

/* ─── Public API: run one query through the agent ────────────────────────── */
export async function queryAgent(
  query: string,
  opts: { useCache?: boolean; signal?: AbortSignal } = {},
): Promise<AgentReply> {
  const res = await fetch(`${API_BASE}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, use_cache: opts.useCache ?? true }),
    signal: opts.signal,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body — keep the status string */
    }
    throw new Error(`Agent request failed: ${detail}`);
  }

  const data: BackendQueryResponse = await res.json();

  if (data.error) throw new Error(data.error);

  return {
    text: data.answer,
    books: (data.books ?? []).map(toAgentBook),
    meta: {
      query_type: data.query_type ?? data.intent ?? "react",
      elapsed: Math.round((data.elapsed ?? 0) * 100) / 100,
      hop: data.hop ?? 1,
    },
    trace: {
      toolChain: data.tool_chain ?? [],
      reasoning: data.reasoning ?? [],
      traversal: data.traversal ?? [],
    },
  };
}

/* ─── Optional health probe (used to decide online vs. offline mock) ─────── */
export async function agentHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal });
    return res.ok;
  } catch {
    return false;
  }
}

/* ─── Admin: workflow mode + LLM model ───────────────────────────────────── */
export interface ModeInfo {
  key: string;
  label: string;
  description: string;
}

export interface AgentConfig {
  current_mode: string;
  current_model: string;
  provider: string;
  modes: ModeInfo[];
  models: string[];
}

async function jsonOrThrow<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const b = await res.json();
      if (b?.detail) detail = String(b.detail);
    } catch {
      /* keep status */
    }
    throw new Error(`${what} failed: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function getModes(): Promise<AgentConfig> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/modes`), "getModes");
}

export async function setMode(body: { mode?: string; model?: string }): Promise<AgentConfig> {
  const res = await fetch(`${API_BASE}/api/mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "setMode");
}

export interface CacheStats {
  hits: number;
  misses: number;
  entries: number;
}

export async function getCacheStats(): Promise<CacheStats> {
  const d = await jsonOrThrow<{ cache: CacheStats }>(
    await fetch(`${API_BASE}/api/cache/stats`),
    "getCacheStats",
  );
  return d.cache;
}

export async function clearCache(): Promise<{ status: string; entries: number }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/cache/clear`, { method: "POST" }), "clearCache");
}
