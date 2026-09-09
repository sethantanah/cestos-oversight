"""Local-folder file storage.

Phase 1 keeps uploaded document files on local disk under STORAGE_DIR so the
API contract (metadata + file_url) can be validated end to end. A future cloud
backend only needs to implement the same small interface (save/open/delete)
and return remote URLs from save().
"""

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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
