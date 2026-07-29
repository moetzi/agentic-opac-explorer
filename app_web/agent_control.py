"""
app_web/agent_control.py — runtime switch for workflow mode + LLM model.
──────────────────────────────────────────────────────────────────────
Lets the /admin UI change, at runtime and without a restart:

  • Workflow mode  — which of the 6 architectures answers /api/query.
  • LLM model      — llama3.1:8b ↔ qwen2.5:7b (both via the ollama provider).

All 6 run_* entrypoints take a query string and return an AgentState, so they
are interchangeable behind `get_runner()`.

Model switching is the subtle part. reasoner.py (`llm_json`), responder.py
(`llm`) and workflow_planned.py (`llm_json`) bind the LLM at *their own* import
time (static binding). Just changing OLLAMA_MODEL is not enough — those modules
keep the old instance (the §8 "Qwen silently ran Llama" bug in catatan_riset).
So a model switch:
  1. evicts the previous model from the remote GPU's VRAM (keep_alive:0),
  2. resets the lazy singletons in llm_services,
  3. reloads the three static-binding modules,
  4. gc.collect().

standard_rag.py calls get_llm() fresh per query, so it needs no reload.

A single lock serializes switches and queries — the remote GPU holds one model
at a time and inference is effectively serial anyway, so this also prevents a
model swap from happening mid-query.
"""
from __future__ import annotations

import gc
import importlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("app_web.agent_control")

# ── Workflow registry: key → (label, description, module, function) ───────────
WORKFLOW_MODES: dict[str, tuple[str, str, str, str]] = {
    "agentic": (
        "Agentic ReAct",
        "Vector-gated ReAct: Router → Reasoner ⇄ ToolExecutor → Responder (default).",
        "agent.core.workflow",
        "run_workflow",
    ),
    "pure_react": (
        "Pure ReAct",
        "ReAct loop without the vector front-door gating.",
        "agent.core.workflow_pure_react",
        "run_workflow_pure_react",
    ),
    "act_only": (
        "Act-only ReAct",
        "ReAct without a 'thought' field — the model emits actions directly.",
        "agent.core.workflow_act_only",
        "run_workflow_act_only",
    ),
    "planned": (
        "Planned",
        "Plan-then-execute: build a tool plan up front, then run the steps.",
        "agent.core.workflow_planned",
        "run_workflow_planned",
    ),
    "standard": (
        "Standard RAG",
        "Baseline: single-hop vector search + generate, no tool-calling.",
        "agent.core.standard_rag",
        "run_standard_rag",
    ),
    "cot": (
        "CoT RAG",
        "Standard RAG with chain-of-thought generation.",
        "agent.core.standard_rag",
        "run_standard_rag_cot",
    ),
}

# Modules that bind the LLM at import time and MUST be reloaded on model switch.
# Order matters: reasoner/responder first, then workflow_planned (which re-imports
# reasoner_node/responder_node when reloaded).
_STATIC_LLM_MODULES = (
    "agent.nodes.reasoner",
    "agent.nodes.responder",
    "agent.core.workflow_planned",
)


def _available_models() -> list[str]:
    raw = os.getenv("ADMIN_OLLAMA_MODELS", "llama3.1:8b,qwen2.5:7b")
    return [m.strip() for m in raw.split(",") if m.strip()]


def _state_path() -> Path:
    override = os.getenv("AGENTIC_GRAPHRAG_ADMIN_STATE")
    if override:
        return Path(override)
    root = Path(__file__).resolve().parent.parent
    return root / ".streamlit_sessions" / "admin_state.json"


class AgentControl:
    """Holds the current (mode, model) and applies switches atomically."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.models = _available_models()
        default_model = os.getenv("OLLAMA_MODEL", self.models[0] if self.models else "llama3.1:8b")
        self.mode = "agentic"
        self.model = default_model
        self._load_persisted()
        # Make sure the environment reflects the restored model. No reload needed
        # at startup: the llm singletons are still lazy/unbuilt here.
        os.environ["OLLAMA_MODEL"] = self.model

    # ── persistence ───────────────────────────────────────────
    def _load_persisted(self) -> None:
        p = _state_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        mode = data.get("mode")
        model = data.get("model")
        if mode in WORKFLOW_MODES:
            self.mode = mode
        if model in self.models:
            self.model = model

    def _persist(self) -> None:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(
                json.dumps({"mode": self.mode, "model": self.model}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ── model switch internals ────────────────────────────────
    @staticmethod
    def _unload_ollama_model(model_name: str) -> None:
        """Best-effort: evict a model from the remote GPU VRAM (keep_alive:0)."""
        base_url = os.getenv("OLLAMA_BASE_URL")
        if not base_url:
            return
        try:
            import requests

            requests.post(
                f"{base_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=15,
            )
            logger.info("Unloaded model %r from %s", model_name, base_url)
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.warning("Could not unload model %r: %s", model_name, exc)

    def _apply_model(self, model_name: str, previous: str | None) -> None:
        if previous and previous != model_name:
            self._unload_ollama_model(previous)

        os.environ["OLLAMA_MODEL"] = model_name

        try:
            import agent.services.llm_services as llm_svc

            llm_svc._llm_instance = None
            llm_svc._llm_json_instance = None

            for mod_name in _STATIC_LLM_MODULES:
                mod = sys.modules.get(mod_name)
                if mod is not None:
                    importlib.reload(mod)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to reset/reload LLM singletons for %r: %s", model_name, exc)

        gc.collect()

    # ── public API ────────────────────────────────────────────
    def get_runner(self, mode: str | None = None) -> Callable[[str], Any]:
        """Return the run_* callable for `mode` (or the current mode)."""
        key = mode or self.mode
        _, _, mod_name, func_name = WORKFLOW_MODES[key]
        module = importlib.import_module(mod_name)
        return getattr(module, func_name)

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def switch(self, *, mode: str | None = None, model: str | None = None) -> dict[str, Any]:
        """Apply a mode and/or model change atomically; return the new snapshot."""
        with self._lock:
            if mode is not None:
                if mode not in WORKFLOW_MODES:
                    raise ValueError(f"unknown mode: {mode!r}")
                self.mode = mode
            if model is not None:
                if model not in self.models:
                    raise ValueError(f"unknown model: {model!r}")
                if model != self.model:
                    previous = self.model
                    self.model = model
                    self._apply_model(model, previous)
            self._persist()
            return self.snapshot()

    def namespace(self) -> str:
        """Cache/log namespace so results never leak across mode/model configs."""
        return f"{self.mode}:{self.model}"

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_mode": self.mode,
            "current_model": self.model,
            "provider": os.getenv("ACTIVE_LLM_PROVIDER", "ollama"),
            "modes": [
                {"key": k, "label": label, "description": desc}
                for k, (label, desc, _m, _f) in WORKFLOW_MODES.items()
            ],
            "models": list(self.models),
        }


# Module-level singleton used by the server.
CONTROL = AgentControl()
