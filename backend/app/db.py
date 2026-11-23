"""A thin PostgREST client. Two flavours, and the difference matters:

* `user_db(token)` sends the signed-in user's own token, so Row Level Security applies to every query.
  All user data goes through this.
* `service_db()` uses the secret key and bypasses RLS. Only shared-catalog writes and workers use it.
"""
from typing import Any

import httpx

from .config import get_settings


class DbError(Exception):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f'PostgREST {status}: {body}')


class Rest:
    def __init__(self, client: httpx.AsyncClient, apikey: str, bearer: str):
        self._client = client
        self._headers = {'apikey': apikey, 'Authorization': f'Bearer {bearer}'}
        self._base = get_settings().supabase_rest_url

    async def _call(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                    prefer: str = 'return=representation') -> Any:
        try:
            resp = await self._client.request(
                method, f'{self._base}/{path}', params=params, json=json, headers={**self._headers, 'Prefer': prefer},
            )
        except httpx.HTTPError as e:
            raise DbError(503, {'message': 'Could not reach the database'}) from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise DbError(resp.status_code, body)
        return resp.json() if resp.content else []

    async def select(self, table: str, params: dict | None = None) -> list[dict]:
        return await self._call('GET', table, params=params)

    async def insert(self, table: str, rows: dict | list[dict]) -> list[dict]:
        return await self._call('POST', table, json=rows)

    async def update(self, table: str, params: dict, values: dict) -> list[dict]:
        return await self._call('PATCH', table, params=params, json=values)

    async def delete(self, table: str, params: dict) -> list[dict]:
        return await self._call('DELETE', table, params=params)

    async def rpc(self, function: str, args: dict) -> Any:
        return await self._call('POST', f'rpc/{function}', json=args)


def user_db(client: httpx.AsyncClient, token: str) -> Rest:
    return Rest(client, get_settings().supabase_anon_key.get_secret_value(), token)


def service_db(client: httpx.AsyncClient) -> Rest:
    key = get_settings().supabase_service_role_key.get_secret_value()
    if not key:
        raise RuntimeError('SUPABASE_SERVICE_ROLE_KEY is not set')
    return Rest(client, key, key)
