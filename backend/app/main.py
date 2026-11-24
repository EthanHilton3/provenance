import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import AuthUser, current_user
from .config import get_settings
from .db import DbError
from .items import router as items_router
from .photos import router as photos_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=30) as http:
        app.state.http = http
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title='Provenance', lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(',') if o.strip()],
        allow_methods=['*'], allow_headers=['Authorization', 'Content-Type'],
    )

    @app.exception_handler(DbError)
    async def db_error(_: Request, exc: DbError):
        # Constraint, policy and bad-token failures are the caller's problem; anything else is ours.
        # (File-storage errors take the same path as database ones.)
        status = exc.status if 400 <= exc.status < 500 or exc.status == 503 else 502
        if status >= 500:
            logger.error('Supabase call failed: %s', exc)
        body = exc.body if isinstance(exc.body, dict) else {}
        # `detail` is always an object with `message`, the same shape as the stale-version 409.
        return JSONResponse({'detail': {'message': body.get('message', 'Database error')}, 'code': body.get('code')}, status)

    @app.get('/api/health')
    async def health():
        return {'ok': True}

    @app.get('/api/me')
    async def me(user: AuthUser = Depends(current_user)):
        return {'id': user.id, 'email': user.email}

    app.include_router(items_router, prefix='/api')
    app.include_router(photos_router, prefix='/api')
    return app


app = create_app()
