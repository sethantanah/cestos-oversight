"""
Find files that use `Path(...)` but don't import it.
"""
from pathlib import Path

ROOT = Path(".")  # run from repo root

def uses_path(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # crude: look for `Path(` but not `from pathlib` / `PurePosixPath(`
        if "Path(" in stripped and "PurePosixPath(" not in stripped:
            # exclude import lines
            if not stripped.startswith(("import ", "from ")):
                return True
    return False

def imports_path(text: str) -> bool:
    for line in text.splitlines():
        s = line.strip()
        if s in ("from pathlib import Path", "from pathlib import Path, PurePosixPath"):
            return True
        if s == "from pathlib import *":
            return True
        if s == "import pathlib":
            return True
    return False

missing = []
for py in ROOT.rglob("*.py"):
    if "__pycache__" in py.parts or ".venv" in py.parts:
        continue
    try:
        text = py.read_text(encoding="utf-8")
    except Exception:
        continue
    if uses_path(text) and not imports_path(text):
        missing.append(py)

print("Files using Path() without importing it:")
for py in missing:
    print(f"  {py}")

if not missing:
    print("  (none — the import is present everywhere Path is used)")