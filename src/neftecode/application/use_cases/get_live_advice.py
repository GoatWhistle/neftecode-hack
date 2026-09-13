"""Use case boundary for live advice.

Data preparation and prediction remain in an outer adapter. This use case only coordinates the
gateway through a port, keeping dataframes, model runtimes and IO outside the application layer.
"""
from dataclasses import dataclass
from neftecode.application.ports import LiveAdviceGateway
from neftecode.application.contracts import LiveAdviceCommand, LiveAdviceResult


@dataclass
class GetLiveAdvice:
    gateway: LiveAdviceGateway

    def execute(self, command: LiveAdviceCommand) -> LiveAdviceResult:
        if not isinstance(command, LiveAdviceCommand):
            raise TypeError("GetLiveAdvice.execute expects LiveAdviceCommand")
        return self.gateway.advise(command.at)
