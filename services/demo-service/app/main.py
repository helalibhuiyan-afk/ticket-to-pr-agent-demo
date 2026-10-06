from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import jira, logs, repo
from .db import init_db
from .util import ApiError, api_error_handler, value_error_handler


@asynccontextmanager
async def lifespan(app):
    init_db()
    jira.seed_historical()
    yield


async def health(request):
    return JSONResponse({"status": "ok", "service": "demo-service"})


app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/jira", routes=jira.routes),
        Mount("/logs", routes=logs.routes),
        Mount("/repo", routes=repo.routes),
    ],
    exception_handlers={ApiError: api_error_handler, ValueError: value_error_handler},
    lifespan=lifespan,
)
