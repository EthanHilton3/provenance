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
    # Not used until intake and catalog lookups exist.
    openai_api_key: SecretStr = SecretStr('')
    tmdb_api_key: SecretStr = SecretStr('')

    cors_origins: str = 'http://localhost:5173'

    @property
    def supabase_rest_url(self) -> str:
        return self.supabase_url.rstrip('/') + '/rest/v1'

    @property
    def supabase_auth_url(self) -> str:
        return self.supabase_url.rstrip('/') + '/auth/v1'


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
