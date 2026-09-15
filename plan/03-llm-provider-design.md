# 03. LLM provider design

## 1. Порт (application/ports/llm.py)

Провайдер-независимый интерфейс, без сетевого кода и без подстроки «http» в тексте.

```python
@dataclass(frozen=True)
class ToolSpec:        name: str; description: str; parameters: dict          # JSON Schema object
@dataclass(frozen=True)
class ToolCall:        call_id: str; name: str; arguments: str                # сырой JSON-текст аргументов
@dataclass(frozen=True)
class LLMMessage:      role: str  # system|user|assistant|tool
                       content: str = ""; tool_calls: tuple[ToolCall, ...] = (); tool_call_id: str | None = None
@dataclass(frozen=True)
class LLMUsage:        prompt_tokens: int = 0; completion_tokens: int = 0; total_tokens: int = 0
@dataclass(frozen=True)
class LLMResponse:     content: str; tool_calls: tuple[ToolCall, ...]; finish_reason: str; usage: LLMUsage;
                       provider: str; model: str; latency_s: float
class LLMError(RuntimeError):  kind: str   # timeout|network|rate_limit|overloaded|quota|auth|bad_request|bad_response|provider|not_configured
                               retryable: bool; code: str | None
class LLMClient(Protocol):
    provider: str; model: str
    def chat(self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = (), *,
             max_tokens: int, timeout_s: float) -> LLMResponse: ...
```

`reasoning_content` (thinking) провайдера **не сохраняется** и не возвращается в `LLMResponse`: скрытая цепочка
рассуждений не пишется в trace и не запрашивается.

Structured output: финальный ответ агента передаётся вызовом tool `submit_opinion` / `finalize`, аргументы валидирует
`application/agentic/contracts.py`. Это единый механизм для всех провайдеров (у Z.AI нет `json_schema`, `tool_choice`
только `auto`). Если модель ответила текстом, loop пытается один локальный repair (единственный JSON-объект в тексте).

## 2. Адаптеры (infrastructure/llm)

HTTP — только stdlib `urllib.request` (через атрибут модуля, чтобы тесты подменяли `urllib.request.urlopen`).
Новых зависимостей нет (offline-развёртывание, `uv.lock` не меняется).

### 2.1 Z.AI Coding Plan (default)

Источник: официальная документация Z.AI, проверено 2026-09-16:
- https://docs.z.ai/devpack/quick-start — Coding Plan: OpenAI-compatible `https://api.z.ai/api/coding/paas/v4`,
  Anthropic-compatible `https://api.z.ai/api/anthropic`;
- https://docs.z.ai/api-reference/introduction — General API `https://api.z.ai/api/paas/v4` («When using GLM Coding Plan,
  please follow the tutorial to configure your dedicated endpoint»);
- https://docs.z.ai/devpack/faq — квота плана расходуется только на coding-endpoint; прочие endpoint списывают баланс;
  при исчерпании квоты баланс не списывается;
- https://docs.z.ai/guides/vlm/glm-5.3-flash — модель `glm-5.3-flash`: 1M контекст, 128K вывод, function calling,
  structured output, thinking;
- https://docs.z.ai/guides/capabilities/thinking-mode — GLM-5.3/GLM-5.3-Flash: thinking принудительный, отключить нельзя;
- https://docs.z.ai/api-reference/llm/chat-completion — `POST {base}/chat/completions`, `Authorization: Bearer`,
  `tools` в формате OpenAI, `tool_choice` только `auto`, `response_format` только `text|json_object`,
  `usage.prompt_tokens/completion_tokens/total_tokens`, `finish_reason` stop|tool_calls|length|sensitive|
  model_context_window_exceeded|network_error;
- https://docs.z.ai/api-reference/api-code — ошибки `{"error":{"code","message"}}`.

Реализация: `OpenAICompatibleClient(provider="zai", base_url=ZAI_BASE_URL, model=ZAI_MODEL, api_key=Secret)`.

- Default base URL: `https://api.z.ai/api/coding/paas/v4`. Если `ZAI_BASE_URL` не содержит `/api/coding/`, factory
  отказывается создавать клиента (`LLMError not_configured`), пока не задан явный `ZAI_ALLOW_GENERAL_ENDPOINT=1`.
  Так General API (списание баланса) не используется случайно.
- Тело запроса: `model, messages, tools, tool_choice:"auto" (только если tools), max_tokens, temperature: 0.2, stream: false`.
  Параметр `thinking` не отправляется (для glm-5.3-flash принудителен); `max_tokens` учитывает расход на thinking.
- Ответ: `choices[0].message.content`, `tool_calls[].{id, function.name, function.arguments}`, `finish_reason`, `usage`.
  `reasoning_content` отбрасывается.
- `finish_reason=length` без tool_calls → `LLMError bad_response` (retryable=false).

Маппинг ошибок (infrastructure/llm/errors.py):

| HTTP / code | kind | retryable |
|---|---|---|
| 401, 1000–1004 | auth | нет |
| 1113 (баланс / вне условий плана), 1308, 1309, 1310, 1311, 1313, 1315 | quota | нет |
| 1302, 429 без кода | rate_limit | да |
| 1305 | overloaded | да |
| 400, 1210–1214 | bad_request | нет |
| 1261 | bad_request (prompt too long) | нет |
| 1301, finish_reason=sensitive | provider | нет |
| 500, 502, 503, 504, 1200, 1230, 1234 | provider | да |
| socket timeout | timeout | да |
| URLError | network | да |
| JSON не разбирается | bad_response | нет |

### 2.2 OpenAI

Тот же `OpenAICompatibleClient(provider="openai", base_url=OPENAI_BASE_URL default https://api.openai.com/v1)`.
Подходит и для локальной OpenAI-compatible LLM завода (закрытая сеть, Q&A 11.09: до ~30B допустимо).
Live не тестируется (ключа нет).

### 2.3 Anthropic

`AnthropicClient`: `POST {base}/v1/messages`, заголовки `x-api-key`, `anthropic-version: 2023-06-01`; `system` отдельно;
tools `{name, description, input_schema}`; ответ — блоки `text`/`tool_use{id,name,input}`; результаты tool — блоки
`tool_result{tool_use_id, content}` в сообщении user; `usage.input_tokens/output_tokens`. Live не тестируется.

### 2.4 Scripted / Policy (без сети)

`ScriptedLLM(steps)` — заранее заданные ответы по очереди; `PolicyLLM(policy)` — функция `(agent_role, messages, tools)
-> LLMResponse`, читающая результаты tools. Используются в тестах и в детерминированном demo trace. Явно
помечаются `provider="scripted"`: это не LLM и не доказательство «интеллекта».

## 3. Конфигурация (env)

| Переменная | Default | Смысл |
|---|---|---|
| `AGENTIC_DECISION_ENABLED` | `false` | Включить agentic-путь (`1/true/yes/on`) |
| `LLM_PROVIDER` | `zai` | `zai`, `openai`, `anthropic`, `scripted` |
| `ZAI_API_KEY` | — | Ключ Coding Plan; aliases `TOKEN`, `token` (так записан текущий `.env`) |
| `ZAI_MODEL` | `glm-5.3-flash` | |
| `ZAI_BASE_URL` | `https://api.z.ai/api/coding/paas/v4` | |
| `ZAI_ALLOW_GENERAL_ENDPOINT` | `0` | Защита от случайного General API |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | —, —, `https://api.openai.com/v1` | |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL` | —, —, `https://api.anthropic.com` | |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | На один запрос |
| `LLM_MAX_RETRIES` | `1` | Только retryable ошибки |
| `LLM_MAX_TOKENS` | `2048` | Включая thinking |
| `LLM_TEMPERATURE` | `0.2` | |
| `AGENT_MAX_STEPS` | `5` | Шагов оркестратора (вызовов LLM оркестратора) |
| `AGENT_SPECIALIST_MAX_CALLS` | `3` | Вызовов LLM на одно обращение к специалисту |
| `AGENT_MAX_SPECIALIST_CONSULTS` | `2` | Обращений к каждому специалисту за решение |
| `AGENT_MAX_LLM_CALLS` | `12` | Всего на одно решение |
| `AGENT_MAX_REPLANS` | `1` | `search_candidates` за решение |
| `AGENT_TIMEOUT_SECONDS` | `180` | Всё agentic-решение |
| `AGENT_MAX_CANDIDATES_FOR_LLM` | `5` | Размер shortlist |
| `AGENT_MAX_CONTEXT_CHARS` | `12000` | Начальный контекст агента |
| `AGENT_MAX_TOOL_RESULT_CHARS` | `2500` | Результат одного tool |
| `AGENT_MAX_ROBUSTNESS_RUNS` | `2` | Запусков robustness через tools |
| `AGENT_MAX_TOOL_CALLS_PER_RESPONSE` | `3` | Лишние tool_calls в одном ответе отклоняются |

Загрузка: `infrastructure/llm/config.py::load_settings(environ, dotenv_path)`. `.env` читается **только** при
включённом флаге и не перекрывает уже заданные переменные окружения. Парсер: `KEY=VALUE`, комментарии `#`, кавычки.

## 4. Секреты

- Ключ хранится в `Secret` (`__repr__`/`__str__` → `Secret(***)`), значение достаётся только в адаптере при сборке заголовка.
- Сообщения исключений формируются из кода/типа ошибки провайдера, без заголовков и тела запроса.
- Trace, decision, логи содержат только provider, model, base_url (без query), usage.
- `.env` в `.gitignore` (проверено `git check-ignore`). Ключ не передаётся субагентам и не печатается, даже частично.

## 5. Условия использования Z.AI Coding Plan — принятый риск

Документация Z.AI (quick-start, FAQ, usage-policy, проверено 2026-09-16): «The GLM Coding Plan is strictly limited to
use within officially supported tools and products»; нарушения могут вести к ограничению скорости, заморозке или бану
аккаунта; код 1315 «API Key limited to enterprise coding scenarios». Прямой вызов из приложения формально выходит за эти
условия. **Решение пользователя 2026-09-16: использовать Coding Plan endpoint, риск принят.** Меры: один live smoke,
без повторов, маленький бюджет, остановка при коде 1113/1313/1315. Для эксплуатации рекомендован локальный
OpenAI-compatible endpoint завода или платный API (см. 07-risks.md).

## 6. Лимиты расхода

Квота Coding Plan (overview): Lite 2 000 кредитов / 5 ч; GLM-5.3-Flash множители input 2.3, cached 0.56, output 8
(кредиты = Σ токены×множитель / 10 000). Оценка одного agentic-решения: ≤12 вызовов × (≈4K input + ≈1.5K output)
≈ 12 × (4000×2.3 + 1500×8)/10000 ≈ 25 кредитов. Один live smoke ≈ ≤30 кредитов.
