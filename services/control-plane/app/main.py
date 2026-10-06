import logging
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .api import health, internal_routes, public_routes
from .db import init_db
from .util import ApiError, api_error_handler, value_error_handler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/api", routes=public_routes),
        Mount("/internal", routes=internal_routes),
    ],
    exception_handlers={ApiError: api_error_handler, ValueError: value_error_handler},
    lifespan=lifespan,
)
