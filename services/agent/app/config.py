import os
import socket

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://control-plane:8000").rstrip("/")
DEMO_SERVICE_URL = os.environ.get("DEMO_SERVICE_URL", "http://demo-service:8000").rstrip("/")
MCP_URL = os.environ.get("MCP_URL", "http://mcp-gateway:8000/mcp")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://ollama:11434/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-oss:20b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "900"))

# The scripted mock LLM, selectable per task from the UI ("mock" mode).
MOCK_LLM_BASE_URL = os.environ.get("MOCK_LLM_BASE_URL", "http://mock-llm:9010/v1").rstrip("/")

BACKENDS = {
    "real": {"base_url": LLM_BASE_URL, "model": LLM_MODEL, "api_key": LLM_API_KEY},
    "mock": {"base_url": MOCK_LLM_BASE_URL, "model": "scripted-mock", "api_key": "mock"},
}

WORKER_ID = os.environ.get("WORKER_ID", f"agent-{socket.gethostname()[:8]}")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
HEARTBEAT_SECONDS = float(os.environ.get("HEARTBEAT_SECONDS", "30"))
MAX_TOOL_RESULT_CHARS = int(os.environ.get("MAX_TOOL_RESULT_CHARS", "6000"))
