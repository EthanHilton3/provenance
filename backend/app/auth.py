"""The only place a user ID comes from: Supabase confirms the bearer token, and we use the ID it returns.

Nothing else (request body, query string, model output) is ever trusted as an identity.
"""
from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Request

from .config import get_settings
from .db import Rest, user_db


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    token: str


async def current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthUser:
    scheme, _, token = (authorization or '').partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        raise HTTPException(401, 'Missing bearer token')
    token = token.strip()
    settings = get_settings()
    client: httpx.AsyncClient = request.app.state.http
    try:
        # Supabase checks the signature, expiry and sign-out state for us, whatever key type the project uses.
        resp = await client.get(
            f'{settings.supabase_auth_url}/user',
            headers={'apikey': settings.supabase_anon_key.get_secret_value(), 'Authorization': f'Bearer {token}'},
        )
    except httpx.HTTPError:
        raise HTTPException(503, 'Could not reach the login service') from None
    if resp.status_code in (401, 403):
        raise HTTPException(401, 'Invalid or expired token')
    if resp.status_code != 200:  # 429, 5xx: the login service is struggling, the token may be fine
        raise HTTPException(503, 'Login service unavailable')
    try:
        data = resp.json()
        user_id = str(UUID(data['id']))
        email = data.get('email')
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(503, 'Unexpected reply from the login service') from None
    return AuthUser(id=user_id, email=email, token=token)


def db_for(request: Request, user: AuthUser = Depends(current_user)) -> Rest:
    """A database handle that acts as this user, so Row Level Security applies."""
    return user_db(request.app.state.http, user.token)
