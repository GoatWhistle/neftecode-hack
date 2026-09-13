"""Filesystem adapter for application artifacts."""

import json
from pathlib import Path
from typing import Any


class JsonArtifactSink:
    """Persist JSON serializable reports under a controlled output directory."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def save(self, name: str, value: object) -> str:
        path = self.directory / name
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=self._default) + "\n",
                        encoding="utf-8")
        return str(path)

    @staticmethod
    def _default(value: Any):
        if hasattr(value, "to_dict"):
            return value.to_dict()
        raise TypeError(f"Объект {type(value).__name__} нельзя сохранить как JSON")
