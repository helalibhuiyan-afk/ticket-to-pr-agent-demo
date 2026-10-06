"""Small HTTP helper: backend errors are returned to the model as {"error": ...} so it can react."""
import os

import requests

DEMO_SERVICE_URL = os.environ.get("DEMO_SERVICE_URL", "http://demo-service:8000").rstrip("/")
CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://control-plane:8000").rstrip("/")
TIMEOUT = int(os.environ.get("BACKEND_TIMEOUT_SECONDS", "90"))


def call(method: str, url: str, **kwargs) -> dict:
    try:
        resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        return {"error": f"backend unreachable: {exc}"}
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}
    if resp.status_code >= 400:
        return {"error": data.get("error", resp.text) if isinstance(data, dict) else resp.text,
                "status": resp.status_code}
    return data


def demo(method: str, path: str, **kwargs) -> dict:
    return call(method, DEMO_SERVICE_URL + path, **kwargs)


def control(method: str, path: str, **kwargs) -> dict:
    return call(method, CONTROL_PLANE_URL + path, **kwargs)
