"""
local_llm.py — GGUF local model inference via llama-cpp-python
===============================================================
Lazy-loads the model on first call and caches it.
Re-loads automatically if the model path changes.
"""

from __future__ import annotations

import logging
import threading
from typing import Generator, Sequence

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_llm = None  # cached Llama instance
_loaded_path: str | None = None
_loaded_n_ctx: int = 0
_loaded_n_gpu_layers: int = -999  # sentinel


def _get_llm(model_path: str, n_ctx: int, n_gpu_layers: int):
    global _llm, _loaded_path, _loaded_n_ctx, _loaded_n_gpu_layers
    with _lock:
        if (
            _llm is None
            or _loaded_path != model_path
            or _loaded_n_ctx != n_ctx
            or _loaded_n_gpu_layers != n_gpu_layers
        ):
            try:
                from llama_cpp import Llama  # type: ignore[import-untyped]
            except ImportError:
                raise RuntimeError(
                    "llama-cpp-python is not installed. "
                    "Run: pip install llama-cpp-python"
                )
            logger.info(
                "Loading local model %s (n_ctx=%d, n_gpu_layers=%d)",
                model_path,
                n_ctx,
                n_gpu_layers,
            )
            _llm = Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                verbose=False,
                chat_format="chatml",  # works for Qwen2.5 and most modern instruct models
            )
            _loaded_path = model_path
            _loaded_n_ctx = n_ctx
            _loaded_n_gpu_layers = n_gpu_layers
            logger.info("Local model loaded successfully.")
    return _llm


def _build_messages(system: str, turns: Sequence[tuple[str, str]]) -> list[dict]:
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    for role, content in turns:
        msgs.append({"role": role, "content": content})
    return msgs


def call_local(
    model_path: str,
    system: str,
    turns: Sequence[tuple[str, str]],
    n_ctx: int = 4096,
    n_gpu_layers: int = 0,
) -> str:
    llm = _get_llm(model_path, n_ctx, n_gpu_layers)
    messages = _build_messages(system, turns)
    output = llm.create_chat_completion(
        messages=messages,
        temperature=0.2,
        stream=False,
    )
    return (output["choices"][0]["message"]["content"] or "").strip()  # type: ignore[index]


def call_local_stream(
    model_path: str,
    system: str,
    turns: Sequence[tuple[str, str]],
    n_ctx: int = 4096,
    n_gpu_layers: int = 0,
) -> Generator[str, None, None]:
    llm = _get_llm(model_path, n_ctx, n_gpu_layers)
    messages = _build_messages(system, turns)
    stream = llm.create_chat_completion(
        messages=messages,
        temperature=0.2,
        stream=True,
    )
    for chunk in stream:  # type: ignore[union-attr]
        delta = (chunk["choices"][0]).get("delta") or {}
        text = delta.get("content")
        if text:
            yield text


def unload():
    """Release the cached model from memory (call when model path changes)."""
    global _llm, _loaded_path, _loaded_n_ctx, _loaded_n_gpu_layers
    with _lock:
        _llm = None
        _loaded_path = None
        _loaded_n_ctx = 0
        _loaded_n_gpu_layers = -999
