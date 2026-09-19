from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATIC_DIR = Path("src/frontend/dist")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}

FALLBACK_MIME = "application/octet-stream"

INDEX = "index.html"


class StaticError(ValueError):
    pass


def content_type_for(path: Path) -> str:
    return MIME_TYPES.get(path.suffix.lower(), FALLBACK_MIME)


@dataclass(frozen=True)
class StaticAsset:
    body: bytes
    content_type: str


def resolve_static_dir(root: Path, static: Path | str | None = None) -> Path:
    candidate = Path(static) if static is not None else DEFAULT_STATIC_DIR
    if not candidate.is_absolute():
        candidate = Path(root) / candidate
    return candidate


class StaticFiles:
    def __init__(self, directory: Path | str, index: str = INDEX) -> None:
        self.directory = Path(directory)
        self.index = index

    def available(self) -> bool:
        return (self.directory / self.index).is_file()

    def missing_message(self) -> str:
        return (f"Каталог собранного фронтенда не найден: {self.directory}. "
                f"Соберите его (npm run build в src/frontend) или укажите путь параметром --static.")

    def _target(self, path: str) -> Path:
        relative = path.lstrip("/") or self.index
        if relative.endswith("/"):
            relative += self.index
        base = self.directory.resolve()
        candidate = (base / relative).resolve()
        if candidate != base and base not in candidate.parents:
            raise StaticError("Путь выходит за пределы каталога статики")
        if candidate.is_dir():
            candidate = candidate / self.index
        return candidate

    def asset(self, path: str) -> StaticAsset:
        if not self.available():
            raise StaticError(self.missing_message())
        candidate = self._target(path)
        if not candidate.is_file():
            candidate = self.directory.resolve() / self.index
        if not candidate.is_file():
            raise StaticError(self.missing_message())
        return StaticAsset(candidate.read_bytes(), content_type_for(candidate))
