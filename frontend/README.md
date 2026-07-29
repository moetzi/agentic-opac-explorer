# Agentic OPAC Explorer — React Frontend

React 18 + Vite + Tailwind chat UI (designed in Figma Make) wired to the
**Agentic GraphRAG** agent. Every query is sent to the FastAPI backend in
[`app_web/server.py`](../app_web/server.py), which runs the selected workflow
(`run_workflow()` by default) and returns book recommendations.

Original design: https://www.figma.com/design/Im4O19GimMGoGfKJGJi6RQ/AI-Book-Recommendation-Chatbot

## Routes

The app is a two-route SPA ([`src/main.tsx`](src/main.tsx), `react-router`):

| Path     | Component                            | Purpose                                                             |
|----------|--------------------------------------|---------------------------------------------------------------------|
| `/`      | [`App.tsx`](src/app/App.tsx)         | Chat UI — ask a question, get an answer + a carousel of book cards. |
| `/admin` | [`Admin.tsx`](src/app/Admin.tsx)     | Runtime control panel — switch workflow mode / LLM model, inspect & clear the response cache. |

## How it connects

```
React UI (:5173)  ──POST /api/query──▶  Vite dev proxy  ──▶  FastAPI (:8001)
   App.tsx send()                                             CONTROL.get_runner()(query)
      │                                                            │
      └──◀── AgentReply (text + book cards + meta) ◀── QueryResponse
                    mapped in src/api.ts
```

- **[`src/api.ts`](src/api.ts)** — typed client for the backend. Maps the backend
  `BookCard` shape into the UI's `AgentBook` (cover fallback, `synopsis`,
  `query_type`/`hop`/`elapsed` meta), and wraps the admin endpoints
  (`getModes`, `setMode`, `getCacheStats`, `clearCache`).
- **[`App.tsx`](src/app/App.tsx) `send()`** — calls `queryAgent()`. If the backend
  is unreachable it falls back to a set of built-in demo replies (labelled
  "⚠️ Backend agen belum terhubung"), so the UI still works before you start the
  server.

## Features

- **Book carousel** — each answer renders up to 12 cards; hover a card to flip to
  its synopsis and branch availability. A meta pill shows `query_type` and
  `{hop}-hop · {elapsed}s`.
- **Accessibility toolbar** (header) — high-contrast mode (`hc`) and 5-step font
  sizing, both driven from React state; all controls are ≥44px and keyboard/ARIA
  labelled.
- **Session history** (left panel) — multiple chats kept in React state for the
  current browser session only. There is **no** persistence: a page reload clears
  history. (The old Streamlit `SessionMemory` on disk is not used here.)
- **Offline demo** — if `/api/query` fails, curated example replies keyed by
  regex (Tere Liye, thriller, kerajaan, cerita anak, kuliner, English, Naura)
  render so the UI is demoable without a running backend.
- **Admin panel** (`/admin`) — pick one of the 6 workflow modes and an LLM model,
  then *Terapkan*; a model switch evicts the previous model from GPU VRAM
  server-side. Cache/results are namespaced per `(mode, model)`.

## Running (development — two terminals)

**Terminal 1 — agent backend** (from the repo root):

```bash
python -m app_web.server        # serves the API on http://127.0.0.1:8001
```

Requires Neo4j + your LLM provider (Ollama/Groq) configured in the root `.env`,
same as the rest of the project.

**Terminal 2 — frontend** (from `frontend/`):

```bash
npm install        # first time only
npm run dev        # http://localhost:5173
```

Vite proxies `/api/*` to the backend, so the browser makes same-origin calls
(no CORS setup needed). Open http://localhost:5173 and ask a question.

## Configuration

| Variable          | Where              | Default                 | Purpose                                           |
|-------------------|--------------------|-------------------------|---------------------------------------------------|
| `VITE_API_TARGET` | shell / `.env`     | `http://127.0.0.1:8001` | Backend the dev proxy forwards `/api` to.         |
| `VITE_API_BASE`   | `.env` (build)     | `""` (same-origin)      | Absolute API base for a production/remote backend.|

To point at a backend on another host/port during dev:

```bash
VITE_API_TARGET=http://127.0.0.1:8011 npm run dev
```

## Backend endpoints consumed

All are served by [`app_web/server.py`](../app_web/server.py); see
[`docs/antarmuka.md`](../docs/antarmuka.md) for the full REST contract.

| Endpoint                | Used by                        |
|-------------------------|--------------------------------|
| `POST /api/query`       | `queryAgent()` — the chat turn |
| `GET  /api/health`      | (available) online/offline probe |
| `GET  /api/modes`       | Admin — current mode/model + options |
| `POST /api/mode`        | Admin — switch mode/model      |
| `GET  /api/cache/stats` | Admin — hit/miss/entries       |
| `POST /api/cache/clear` | Admin — drop cached responses  |

## Project structure

```
frontend/
├── index.html              # Vite entry
├── vite.config.ts          # React + Tailwind plugins, /api dev proxy, figma:asset resolver
├── package.json            # scripts: dev (vite), build (vite build)
└── src/
    ├── main.tsx            # createBrowserRouter → / (App) and /admin (Admin)
    ├── api.ts              # typed backend client + response mappers
    ├── app/
    │   ├── App.tsx         # chat page (carousel, history, a11y, offline fallback)
    │   ├── Admin.tsx       # runtime control panel
    │   └── components/     # shadcn/ui primitives + figma/ImageWithFallback
    ├── imports/            # logos & static images (ITS, Perpustakaan Jakarta)
    └── styles/             # Tailwind + fonts + theme
```

## Production build

```bash
npm run build              # emits static assets to frontend/dist/
npx vite preview           # optional: serve dist/ locally to sanity-check
```

`dist/` is a static bundle. Serve it behind any web server, or from FastAPI, and
set `VITE_API_BASE` at build time if the API is not same-origin. Because `/admin`
is a client-side route, the host must fall back to `index.html` for unknown paths
(the Vite dev server does this automatically; a plain static host may need an SPA
rewrite rule).
