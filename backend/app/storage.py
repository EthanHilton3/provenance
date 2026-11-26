"""A thin Supabase Storage client for the private `photos` bucket.

Called with the signed-in user's own token, so the storage policies (own `<user id>/` prefix only) apply here exactly
as Row Level Security applies in db.py. The one exception is the intake worker (worker.py), which has no user token:
it downloads with the service key, and only after checking the photo row and path belong to the job's owner.
"""
from typing import Any

import httpx

from .config import get_settings
from .db import DbError

BUCKET = 'photos'
SIGNED_URL_SECONDS = 3600


class StorageError(DbError):
    """Same shape as a database error, so the app maps it to a client status the same way."""

    def __init__(self, status: int, body: Any):
        super().__init__(status, body)
        self.args = (f'Storage {status}: {body}',)


class Storage:
    def __init__(self, client: httpx.AsyncClient, apikey: str, bearer: str):
        self._client = client
        self._headers = {'apikey': apikey, 'Authorization': f'Bearer {bearer}'}
        self._base = get_settings().supabase_storage_url

    async def _call(self, method: str, path: str, *, headers: dict | None = None, **kwargs) -> Any:
        headers = {**self._headers, **(headers or {})}
        try:
            resp = await self._client.request(method, f'{self._base}/{path}', headers=headers, **kwargs)
        except httpx.HTTPError as e:
            raise StorageError(503, {'message': 'Could not reach file storage'}) from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise StorageError(resp.status_code, body)
        return resp.json() if resp.content else None

    async def upload(self, path: str, data: bytes) -> None:
        """Fails if the path already exists (no upsert): every photo gets a new id."""
        await self._call('POST', f'object/{BUCKET}/{path}', content=data, headers={'Content-Type': 'image/jpeg'})

    async def remove(self, paths: list[str]) -> None:
        """Deletes the files. A path that is already gone is not an error, so a retry after a half-finished delete works."""
        if paths:
            await self._call('DELETE', f'object/{BUCKET}', json={'prefixes': paths})

    async def download(self, path: str) -> bytes:
        try:
            resp = await self._client.get(f'{self._base}/object/{BUCKET}/{path}', headers=self._headers)
        except httpx.HTTPError as e:
            raise StorageError(503, {'message': 'Could not reach file storage'}) from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise StorageError(resp.status_code, body)
        return resp.content

    async def sign(self, paths: list[str]) -> dict[str, str | None]:
        """Short-lived URLs for the paths this user may read; None for any that are missing or not theirs."""
        replies = await self._call('POST', f'object/sign/{BUCKET}', json={'expiresIn': SIGNED_URL_SECONDS, 'paths': paths})
        # The reply gives a path relative to the storage API, which already carries the token.
        return {r['path']: f'{self._base}{r["signedURL"]}' if r.get('signedURL') else None for r in replies}


def user_storage(client: httpx.AsyncClient, token: str) -> Storage:
    return Storage(client, get_settings().supabase_anon_key.get_secret_value(), token)


def service_storage(client: httpx.AsyncClient) -> Storage:
    """Bypasses the bucket policies. Only the intake worker uses it, after its owner checks."""
    key = get_settings().supabase_service_role_key.get_secret_value()
    if not key:
        raise RuntimeError('SUPABASE_SERVICE_ROLE_KEY is not set')
    return Storage(client, key, key)
