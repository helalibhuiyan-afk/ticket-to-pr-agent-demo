"""Minimal OpenAI-compatible chat-completions client (works with Ollama, vLLM, llama.cpp, hosted APIs)."""
import time

import requests

from .config import BACKENDS, LLM_TEMPERATURE, LLM_TIMEOUT_SECONDS


class LLMError(Exception):
    pass


def chat(messages: list[dict], tools: list[dict], mode: str = "real") -> tuple[dict, dict]:
    """Returns (assistant_message, stats). mode selects the backend: "real" or "mock"."""
    backend = BACKENDS.get(mode, BACKENDS["real"])
    started = time.monotonic()
    try:
        resp = requests.post(
            f"{backend['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {backend['api_key']}"},
            json={"model": backend["model"], "messages": messages, "tools": tools, "tool_choice": "auto",
                  "temperature": LLM_TEMPERATURE},
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise LLMError(f"LLM returned HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"unexpected LLM response: {str(data)[:500]}") from exc
    usage = data.get("usage") or {}
    stats = {"seconds": round(time.monotonic() - started, 1),
             "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}
    return message, stats
