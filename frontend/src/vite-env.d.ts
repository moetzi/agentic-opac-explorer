/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the FastAPI agent backend. Empty = same-origin (dev proxy). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
