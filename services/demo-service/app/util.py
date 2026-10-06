from datetime import datetime, timezone

from starlette.responses import JSONResponse


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


async def api_error_handler(request, exc: ApiError):
    return JSONResponse({"error": exc.detail}, status_code=exc.status)


async def json_body(request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "request body must be JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "request body must be a JSON object")
    return body


async def value_error_handler(request, exc: ValueError):
    return JSONResponse({"error": f"invalid parameter: {exc}"}, status_code=400)
