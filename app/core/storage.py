"""Storage backends for uploaded media and documents.

The app keeps the existing local-file interface for development and tests, while
production can switch to Supabase Storage automatically via settings.
"""

import mimetypes
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None

from app.core.config import Settings

ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".txt",
        ".csv",
    }
)


@dataclass(frozen=True)
class StoredFile:
    relative_path: (
        str  # posix path under the storage root, e.g. "employee-documents/<id>/<uuid>.pdf"
    )
    filename: str  # original client filename
    mime_type: str
    size_bytes: int


class LocalStorage:
    """Content-addressed local file store with traversal protection."""

    def __init__(self, root: Path, max_bytes: int):
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        namespace: str,
        data: bytes,
        original_filename: str,
        content_type: str | None,
    ) -> StoredFile:
        if len(data) > self.max_bytes:
            raise ValueError(f"File exceeds the {self.max_bytes // (1024 * 1024)} MB upload limit")
        suffix = Path(original_filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Extension '{suffix or '(none)'}' is not allowed; "
                f"allowed: {sorted(ALLOWED_EXTENSIONS)}"
            )
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        relative = PurePosixPath(namespace, stored_name)
        target = self.root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        mime = content_type or mimetypes.guess_type(original_filename)[0]
        return StoredFile(
            relative_path=relative.as_posix(),
            filename=Path(original_filename).name,
            mime_type=mime or "application/octet-stream",
            size_bytes=len(data),
        )

    def resolve(self, relative_path: str) -> Path:
        """Return the absolute path, rejecting traversal outside the root."""
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Invalid stored file path")
        return self.root.joinpath(*pure.parts)

    def delete(self, relative_path: str) -> None:
        try:
            self.resolve(relative_path).unlink(missing_ok=True)
        except ValueError:
            return


class SupabaseStorage:
    """Supabase Storage adapter that mirrors the LocalStorage interface."""

    def __init__(self, url: str, service_role_key: str, bucket: str, max_bytes: int):
        if create_client is None:
            raise RuntimeError(
                "Supabase Python package is not installed. Add the 'supabase' dependency."
            )
        self.url = url.rstrip("/")
        self.bucket = bucket
        self.max_bytes = max_bytes
        self.client = create_client(self.url, service_role_key)
        try:
            buckets = self.client.storage.list_buckets()
            bucket_names = {
                getattr(item, "name", None)
                or (item.get("name") if isinstance(item, dict) else None)
                for item in buckets
            }
            if self.bucket not in bucket_names:
                self.client.storage.create_bucket(self.bucket, {"public": True})
        except Exception:
            pass

    def save(
        self,
        namespace: str,
        data: bytes,
        original_filename: str,
        content_type: str | None,
    ) -> StoredFile:
        if len(data) > self.max_bytes:
            raise ValueError(f"File exceeds the {self.max_bytes // (1024 * 1024)} MB upload limit")
        suffix = Path(original_filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Extension '{suffix or '(none)'}' is not allowed; "
                f"allowed: {sorted(ALLOWED_EXTENSIONS)}"
            )
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        relative = PurePosixPath(namespace, stored_name)
        object_path = relative.as_posix()
        content_type_value = content_type or mimetypes.guess_type(original_filename)[0]
        self.client.storage.from_(self.bucket).upload(
            object_path,
            data,
            {"content-type": content_type_value or "application/octet-stream", "upsert": "true"},
        )
        return StoredFile(
            relative_path=object_path,
            filename=Path(original_filename).name,
            mime_type=content_type_value or "application/octet-stream",
            size_bytes=len(data),
        )

    def resolve(self, relative_path: str) -> Path:
        """Download the object into a temp file for the existing FileResponse flow."""
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Invalid stored file path")
        cache_dir = Path(tempfile.gettempdir()) / "cestos-supabase-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{uuid.uuid4().hex}-{pure.name}"
        data = self.client.storage.from_(self.bucket).download(pure.as_posix())
        if hasattr(data, "read"):
            payload = data.read()
        else:
            payload = bytes(data)
        cache_file.write_bytes(payload)
        return cache_file

    def delete(self, relative_path: str) -> None:
        try:
            self.client.storage.from_(self.bucket).remove([relative_path])
        except Exception:
            return


def build_storage(settings: Settings):
    if settings.app_env == "production":
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError(
                "Supabase storage requires a configured SUPABASE_URL and service role key"
            )
        return SupabaseStorage(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
            settings.supabase_bucket,
            settings.max_upload_size_mb * 1024 * 1024,
        )
    return LocalStorage(Path(settings.storage_dir), settings.max_upload_size_mb * 1024 * 1024)
