from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
from typing import Mapping

from neftecode.application.agentic.contracts import AgentSettings
from neftecode.application.agentic.decision import AgenticMakeDecision
from neftecode.application.ports.llm import LLMClient, LLMError
from neftecode.application.use_cases.make_decision import MakeDecision
from neftecode.infrastructure.llm.config import (agent_limits_from_env, agentic_enabled, llm_settings_from_env,
                                                 load_environment)
from neftecode.infrastructure.llm.demo_policy import demo_llm
from neftecode.infrastructure.llm.factory import make_llm_client
from neftecode.infrastructure.response.data_model import DataResponseEffect


@dataclass
class DecisionFactory:
    enabled: bool = False
    llm: LLMClient | None = None
    settings: AgentSettings = field(default_factory=AgentSettings)
    configuration_error: str | None = None
    provider_description: dict = field(default_factory=dict)

    def __call__(self, scenario, robustness_evaluator=None, live_context: dict | None = None):
        if not self.enabled:
            return MakeDecision(scenario, robustness_evaluator=robustness_evaluator)
        return AgenticMakeDecision(scenario, self.llm, settings=self.settings,
                                   robustness_evaluator=robustness_evaluator,
                                   response_effect=DataResponseEffect(), live_context=live_context,
                                   configuration_error=self.configuration_error,
                                   provider_description=self.provider_description or None)

    def describe(self) -> dict:
        return {"agentic_enabled": self.enabled, "configuration_error": self.configuration_error,
                "settings": self.settings.to_dict() if self.enabled else None, **self.provider_description}


def build_decision_factory(environ: Mapping[str, str] | None = None, dotenv_path: Path | None = None,
                           llm: LLMClient | None = None) -> DecisionFactory:
    environ = os.environ if environ is None else environ
    if not agentic_enabled(environ):
        return DecisionFactory(enabled=False)
    env = load_environment(environ, dotenv_path if dotenv_path is not None else Path.cwd() / ".env")
    try:
        llm_settings = llm_settings_from_env(env)
        limits = agent_limits_from_env(env)
        settings = AgentSettings.from_mapping({**limits, "max_tokens": llm_settings.max_tokens,
                                               "request_timeout_s": llm_settings.request_timeout_s})
    except ValueError as exc:
        return DecisionFactory(enabled=True, configuration_error=f"invalid_configuration: {exc}")
    description = llm_settings.describe()
    if llm is not None:
        return DecisionFactory(True, llm, settings, None, description)
    if llm_settings.provider == "scripted":
        return DecisionFactory(True, demo_llm(), settings, None, description)
    try:
        client = make_llm_client(llm_settings, environ)
    except LLMError as exc:
        return DecisionFactory(True, None, settings, f"llm_not_configured: {str(exc)[:200]}", description)
    return DecisionFactory(True, client, settings, None, description)


@lru_cache(maxsize=4)
def _cached_default(dotenv_path: Path) -> DecisionFactory:
    return build_decision_factory(dotenv_path=dotenv_path)


def default_decision_factory(root: Path | None = None) -> DecisionFactory:
    return _cached_default((Path(root) if root is not None else Path.cwd()).resolve() / ".env")
