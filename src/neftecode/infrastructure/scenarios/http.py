from neftecode.domain.production.scenario import Scenario
from neftecode.infrastructure.config.scenario import parse_scenario


class HttpScenarioRepository:
    """Сценарии от data-service: `GET /v1/scenarios` и `POST /v1/scenarios/get`.

    `client` — HTTP-клиент процесса с методом `request(method, url, payload, headers=...)`, ответ которого
    несёт `.data` (в стеке это `ServiceHTTPClient`). Идентификатор запроса уходит в `X-Request-ID`;
    `for_request` даёт тот же источник с идентификатором входящего запроса.
    """

    def __init__(self, client, base_url: str, request_id: str = "gateway"):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.request_id = request_id

    def for_request(self, request_id: str) -> "HttpScenarioRepository":
        return HttpScenarioRepository(self.client, self.base_url, request_id)

    def names(self) -> list[str]:
        return self.client.request("GET", self.base_url + "/v1/scenarios",
                                   headers={"X-Request-ID": self.request_id}).data["scenarios"]

    def raw(self, scenario_id: str) -> dict:
        return self.client.request("POST", self.base_url + "/v1/scenarios/get", {"scenario_id": scenario_id},
                                   headers={"X-Request-ID": self.request_id}).data

    def get(self, scenario_id: str) -> Scenario:
        return parse_scenario(self.raw(scenario_id))
