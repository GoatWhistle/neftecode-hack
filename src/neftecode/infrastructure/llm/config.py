"""Environment configuration for language model adapters and agent budgets.

Values come from the process environment, optionally overlaid on a `.env` file. Keys are wrapped in
`Secret` and never appear in reprs, descriptions or error messages.
"""
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

ZAI_CODING_URL = "https://api.z.ai/api/coding/paas/v4"
ZAI_DEFAULT_MODEL = "glm-5.3-flash"
OPENAI_URL = "https://api.openai.com/v1"
#: Q&A 11.09: the plant network has no internet and runs a local OpenAI-compatible model up to ~30B.
#: That model is an option (`LLM_PROVIDER=local`); the default is Z.AI by the user's decision of 2026-09-17.
LOCAL_URL = "http://127.0.0.1:8000/v1"
DEFAULT_PROVIDER = "zai"
ANTHROPIC_URL = "https://api.anthropic.com"

#: Environment variables that hold a provider key, in priority order.
KEY_VARIABLES = {
    "zai": ("ZAI_API_KEY", "TOKEN", "token"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "local": ("LOCAL_LLM_API_KEY",),
}
#: Providers that work without a key (a local server inside the closed network).
KEY_OPTIONAL = {"local"}

AGENT_LIMITS = {
    "max_steps": ("AGENT_MAX_STEPS", 5),
    "specialist_max_calls": ("AGENT_SPECIALIST_MAX_CALLS", 3),
    "max_specialist_consults": ("AGENT_MAX_SPECIALIST_CONSULTS", 2),
    "max_llm_calls": ("AGENT_MAX_LLM_CALLS", 12),
    "max_replans": ("AGENT_MAX_REPLANS", 1),
    "timeout_s": ("AGENT_TIMEOUT_SECONDS", 600.0),
    "max_candidates": ("AGENT_MAX_CANDIDATES_FOR_LLM", 5),
    "max_context_chars": ("AGENT_MAX_CONTEXT_CHARS", 12000),
    "max_tool_result_chars": ("AGENT_MAX_TOOL_RESULT_CHARS", 2500),
    "max_robustness_runs": ("AGENT_MAX_ROBUSTNESS_RUNS", 2),
    "max_tool_calls_per_response": ("AGENT_MAX_TOOL_CALLS_PER_RESPONSE", 3),
}


class Secret:
    """A credential that refuses to print itself.

    Deliberately not a dataclass: `dataclasses.asdict` on settings must not unwrap the value.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str = ""):
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name, value):
        raise AttributeError("Secret is immutable")

    def __eq__(self, other) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("Secret", self._value))

    def __copy__(self) -> "Secret":
        return self

    def __deepcopy__(self, memo) -> "Secret":
        return self

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `KEY=VALUE` lines; blank lines, `#` comments and an `export ` prefix are allowed."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_environment(environ: Mapping[str, str], dotenv_path: Path | None = None) -> dict[str, str]:
    """Merge `.env` values under the real environment, which always wins."""
    merged = {}
    if dotenv_path is not None and Path(dotenv_path).is_file():
        merged.update(parse_dotenv(Path(dotenv_path).read_text(encoding="utf-8")))
    merged.update(environ)
    return merged


def truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def falsy(value) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off"}


def agentic_enabled(env: Mapping[str, str]) -> bool:
    """The agent layer is on unless explicitly switched off (tests pin the deterministic mode this way)."""
    return not falsy(env.get("AGENTIC_DECISION_ENABLED"))


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key: Secret = field(default_factory=Secret, repr=False)
    request_timeout_s: float = 120.0
    max_retries: int = 1
    max_tokens: int = 6144
    temperature: float = 0.2
    allow_general_endpoint: bool = False

    def describe(self) -> dict:
        """Safe summary for traces: no key, no query string."""
        parts = urlsplit(self.base_url)
        return {"provider": self.provider, "model": self.model,
                "base_url": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
                "max_tokens": self.max_tokens, "request_timeout_s": self.request_timeout_s,
                "max_retries": self.max_retries, "api_key": "present" if self.api_key else "missing"}


def _raw(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(env: Mapping[str, str], name: str, default, kind, *, minimum=0, strict=True):
    raw = _raw(env, name)
    if raw is None:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ValueError(f"{name}: ожидается число типа {kind.__name__}") from None
    if not math.isfinite(value) or value < minimum or (strict and value == minimum):
        relation = ">" if strict else ">="
        raise ValueError(f"{name}: ожидается значение {relation} {minimum}")
    return value


def llm_settings_from_env(env: Mapping[str, str]) -> LLMSettings:
    """Build adapter settings from an environment mapping (see plan/03 §3)."""
    provider = (_raw(env, "LLM_PROVIDER") or DEFAULT_PROVIDER).lower()
    common = dict(
        request_timeout_s=_number(env, "LLM_REQUEST_TIMEOUT_SECONDS", 120.0, float),
        max_retries=_number(env, "LLM_MAX_RETRIES", 1, int, strict=False),
        max_tokens=_number(env, "LLM_MAX_TOKENS", 6144, int),
        temperature=_number(env, "LLM_TEMPERATURE", 0.2, float, strict=False),
    )
    key = next((value for name in KEY_VARIABLES.get(provider, ()) if (value := _raw(env, name))), "")
    if provider == "zai":
        return LLMSettings(provider, _raw(env, "ZAI_MODEL") or ZAI_DEFAULT_MODEL,
                           _raw(env, "ZAI_BASE_URL") or ZAI_CODING_URL, Secret(key),
                           allow_general_endpoint=truthy(env.get("ZAI_ALLOW_GENERAL_ENDPOINT")), **common)
    if provider == "openai":
        return LLMSettings(provider, _raw(env, "OPENAI_MODEL") or "",
                           _raw(env, "OPENAI_BASE_URL") or OPENAI_URL, Secret(key), **common)
    if provider == "anthropic":
        return LLMSettings(provider, _raw(env, "ANTHROPIC_MODEL") or "",
                           _raw(env, "ANTHROPIC_BASE_URL") or ANTHROPIC_URL, Secret(key), **common)
    if provider == "local":
        return LLMSettings(provider, _raw(env, "LOCAL_LLM_MODEL") or "",
                           _raw(env, "LOCAL_LLM_BASE_URL") or LOCAL_URL, Secret(key), **common)
    if provider == "scripted":
        return LLMSettings(provider, "scripted", "", Secret(), **common)
    return LLMSettings(provider, "", "", Secret(), **common)


def decision_wait_seconds(root: Path, environ: Mapping[str, str] | None = None, margin_s: float = 60.0) -> float:
    """How long a caller waits for one decision: the agent budget (`AGENT_TIMEOUT_SECONDS`) plus a margin.

    The retry inside a model call is bounded by the same budget (see `call_with_retries`), so this is a
    true upper bound; the gateway and the demo page share it instead of a separate constant.
    """
    env = load_environment(os.environ if environ is None else environ, Path(root) / ".env")
    try:
        return float(agent_limits_from_env(env)["timeout_s"]) + margin_s
    except ValueError:
        return AGENT_LIMITS["timeout_s"][1] + margin_s


def agent_limits_from_env(env: Mapping[str, str]) -> dict[str, int | float]:
    """Agent budgets; every value must be positive, invalid input raises instead of clamping."""
    return {key: _number(env, name, default, type(default)) for key, (name, default) in AGENT_LIMITS.items()}
