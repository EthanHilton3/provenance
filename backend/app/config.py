"""Settings come from the process environment first, then the repo-root .env."""
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')

    supabase_url: str
    supabase_anon_key: SecretStr
    # Backend only. Bypasses RLS: only for the shared catalog and the intake worker, never for user reads.
    supabase_service_role_key: SecretStr = SecretStr('')
    # The intake worker's key (app/worker.py). The API uses it only for the duplicate-release check's embeddings
    # (app/embeddings.py, S12), never for the vision models. TMDB is for the catalog service (app/catalog.py).
    openai_api_key: SecretStr = SecretStr('')
    tmdb_api_key: SecretStr = SecretStr('')

    # UPCitemdb's free trial endpoint (no key): about 100 lookups a day for the whole app. The daily budget leaves
    # 10 for testing by hand; the per-user share stops one user from spending it; the per-minute cap stays under its
    # undocumented per-minute limit (the barcode test paced calls 11 s apart and never hit it).
    upcitemdb_url: str = 'https://api.upcitemdb.com/prod/trial/lookup'
    upc_daily_budget: int = 90
    upc_per_user_daily: int = 20
    upc_per_minute: int = 5

    # Catalog service (app/catalog.py). TMDB_API_KEY is a v3 key: it goes in TMDB's query string only, never in a
    # log. TMDB's own limit is about 50 requests a second; these caps are for abuse, not for TMDB. Open Library asks
    # for gentle use, so it gets a lower per-minute cap. The URLs can point at app/fake_catalog.py for a local walk.
    tmdb_url: str = 'https://api.themoviedb.org/3'
    tmdb_daily_budget: int = 20000
    tmdb_per_user_daily: int = 500
    tmdb_per_minute: int = 120
    openlibrary_url: str = 'https://openlibrary.org'
    openlibrary_daily_budget: int = 5000
    openlibrary_per_user_daily: int = 300
    openlibrary_per_minute: int = 30

    # Duplicate-release check (app/embeddings.py, app/releases.py). The threshold comes from docs/DUPLICATE_THRESHOLD.md.
    duplicate_max_distance: float = 0.028
    embed_daily_budget: int = 5000
    embed_per_user_daily: int = 200
    embed_per_minute: int = 60
    # Fake vectors instead of OpenAI, for a local walk at no cost. Refused unless Supabase is local: fake vectors in
    # a real database would make the check meaningless for everyone.
    embeddings_fake: bool = False

    cors_origins: str = 'http://localhost:5173'

    @property
    def supabase_is_local(self) -> bool:
        return self.supabase_url.startswith(('http://127.0.0.1', 'http://localhost'))

    @property
    def supabase_rest_url(self) -> str:
        return self.supabase_url.rstrip('/') + '/rest/v1'

    @property
    def supabase_storage_url(self) -> str:
        return self.supabase_url.rstrip('/') + '/storage/v1'

    @property
    def supabase_auth_url(self) -> str:
        return self.supabase_url.rstrip('/') + '/auth/v1'


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
