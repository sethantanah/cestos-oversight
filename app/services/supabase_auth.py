from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.models.user import User

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None


class SupabaseAuthSyncService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        if not self.settings.supabase_auth_enabled:
            return None
        if not self.settings.supabase_url or not self.settings.supabase_service_role_key:
            raise ValueError("Supabase auth sync requires a configured URL and service-role key")
        if create_client is None:
            raise RuntimeError("Supabase Python package is required for Supabase auth sync")
        return create_client(self.settings.supabase_url, self.settings.supabase_service_role_key.get_secret_value())

    def sync_user(self, user: User, password: str | None = None, *, metadata: dict[str, Any] | None = None) -> str | None:
        if not self.settings.supabase_auth_enabled:
            return None

        client = self._client()
        if client is None:
            return None

        payload = {
            "email": user.email,
            "email_confirm": True,
            "user_metadata": {
                "app_user_id": str(user.id),
                "organization_id": str(user.organization_id),
                **(metadata or {}),
            },
        }
        if password:
            payload["password"] = password

        existing = getattr(user, "supabase_user_id", None)
        if existing:
            client.auth.admin.update_user_by_id(existing, {"user_metadata": payload["user_metadata"]})
            return existing

        result = client.auth.admin.create_user(payload)
        supabase_id = getattr(result.user, "id", None)
        if supabase_id:
            user.supabase_user_id = supabase_id
        return supabase_id
