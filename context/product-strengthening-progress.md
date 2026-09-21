# Журнал выполнения: четыре продуктовые доработки (U1–U4)

Начато 22.09.2026, ветка `main`, база `42d34b9`. Push не выполняется.

| Часть | Статус |
|---|---|
| Подготовка | выполнено |
| U3 тяжесть режима | выполнено (backend + тесты; UI-подпись — в U1) |
| U1 парное сравнение | не начато |
| U2 карта планов | не начато |
| U4 протокол | не начато |
| Общая приёмка | не начато |

## Подготовка

- Исходная точка на scripted (порт 18901, `LLM_PROVIDER=scripted`): `context/product-strengthening-baseline/{normal,risk,bad}.json`
  (полный ответ `/api/decide`) и `summary.json`.
  Норма: baseline / 20260105-080000 / healthy → hold, тяжесть 0.0. Риск: sour_crude / 20260724-030000 / healthy →
  recommend_scenario c0042, стоимость 1.158, тяжесть 0.0. Плохие данные: baseline / 20260416-101000 / both_broken → refuse.
- RunRecord (frontend-запись завершённого прогона, спроектирована в U1/U4): версия схемы, run_id, время, условия запроса
  и фактически применённые (`applied`, `injection`, `snapshot`, `binding`), fingerprint входов, версия модели/отпечаток
  данных, версия кода + признак изменённого дерева, provider/model, payload и события. Метаданные собирает backend
  (`run_meta` рядом со screen payload); бизнес-логика во frontend не дублируется.
