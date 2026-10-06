"""Minimal OpenAI-compatible chat-completions client (works with Ollama, vLLM, llama.cpp, hosted APIs)."""
import time

import requests

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT_SECONDS


class LLMError(Exception):
    pass


def chat(messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
    """Returns (assistant_message, stats)."""
    started = time.monotonic()
    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={"model": LLM_MODEL, "messages": messages, "tools": tools, "tool_choice": "auto",
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
