from typing import Protocol, runtime_checkable


@runtime_checkable
class LiveAdviceGateway(Protocol):
    def advise(self, at: str) -> dict: ...
