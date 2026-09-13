from typing import Protocol


class ArtifactSink(Protocol):
    def save(self, name: str, value: object) -> str | None: ...
