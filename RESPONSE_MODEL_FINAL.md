# Модель отклика серы на температуру ГО — финальная спецификация

> **Статус на 2026-09-16.** Официальный справочник тегов 24-2000 (чат, сообщение 585) опроверг гипотезу, на которой
> построена спецификация: `T11` — температура ГСС/продукта **на выходе** Р-202, а не на входе; `F26` — расход
> гидроочищенного ДТ в цех №8, а не сырья. Температура на входе Р-202 — `T6`, расход сырья — `F9` (массовый) и
> `F15` (объёмный). Спецификация ниже сохранена без изменений как история. В src она не переносится; пересчёт на
> `T6`/`F9` — новый эксперимент, только по решению пользователя.

Версия 3, 2026-09-15, после аудита спецификации. Выбор модели принят (раунд 2), здесь зафиксирован однозначный pipeline.
Код src не менялся.

- **Эталонная реализация (research-копия):** `context/response-research/final/response_model.py`
  (`prepare`, `rows`, `fit`, `live_state`, `predict`).
- **Аудит:** `final/f9_audit.py` → `final/out/f9_audit.json`.
- **Доказательства выбора модели:** `final/f0…f8`, журнал — `context/response-research/notes.md`.

---

## 1. Модель

```
S(t+3h | ΔT) = baseline_t + β_τ · ΔT
baseline_t   = w_τ · PAK30m(t) + (1 − w_τ) · PAK24h(t)
```

- **t** — момент решения.
- **τ** — дата обучения артефакта (τ ≤ t, t − τ ≤ 6 мес.).
- **β_τ** — не константа, а оценка ARX по trailing 12 months до τ.
  **−0.595 мг/кг/°C — только текущая оценка на τ = 2026-08-07.** На τ = 2025-07-01 было −0.348, на 2026-01-01 — −0.389.
- **w_τ** — вес, подобранный по прошлому окну (сейчас 0.20).
- Эффект по состоянию постоянный. Форма аддитивная (мультипликативная и β(state) проверены и отклонены в раунде 2).

## 2. Спецификация

```
PREDICTION INPUT (входит в формулу):
    PAK30m(t)  = среднее валидных 10-мин значений ПАК серы за (t−30 мин, t]; нужно ≥ 1 значение
    PAK24h(t)  = среднее валидных 10-мин значений ПАК за (t−24 ч, t]; нужно ≥ 72 из 144
    ΔT         = предлагаемое устойчивое изменение температуры на входе реактора (T11), °C, удерживается ≥ 3 ч
    artifact   = {τ, w_τ, β_τ, β_weak, β_strong, r0, r1}

    валидное 10-мин значение ПАК: среднее показаний 24-2000:Mg.Sulfur в интервале (t−10 мин, t] (правая метка),
    в пределах 0.05–50 мг/кг, не «зависшее»: к моменту показания значение не менялось меньше 1 ч (правило только по прошлому)

SUPPORT / VALIDITY INPUT (в формулу НЕ входит):
    T11(t)        среднее за (t−30 мин, t]           — диапазон T11 и T11+ΔT, аналоги
    T11_30d(t)    среднее T11 за 30 сут работы         — аналоги
    F26(t)        объёмный расход сырья, 30 мин        — диапазон, аналоги
    H2/сырьё(t)   F2/F26, 30 мин                       — аналоги
    run_past12h   12 ч непрерывной работы по прошлому  — допуск
    pak_frozen_now, PAK24h_coverage                    — допуск
    artifact.support: q01/q99 T11 и F26, μ/σ признаков аналогов, таблица onset-шагов (A30, признаки)

TRAINING-ONLY INPUT (для fit, в live не нужен):
    T11 и F26 10-мин — ARX-оценка β; T11 (t, t+30 мин] — исторический шаг A30; ПАК (t+3ч, t+3ч30м] — метка;
    признак stable_label (работа ещё 6 ч после момента) — только для отбора строк

OUTPUT:
    zone ∈ {HOLD, A_SUPPORTED, B_EXTRAPOLATION, C_FORBIDDEN}, reasons
    baseline, sulfur_mid, [lower, upper], effect_mid, effect_weak, effect_strong, support_analogs, β_τ, τ

UNCERTAINTY:
    ΔT = 0:  [baseline − r0, baseline + r0]
    ΔT ≠ 0:  lower = baseline + min(β_weak·ΔT, β_strong·ΔT) − r1
             upper = baseline + max(β_weak·ΔT, β_strong·ΔT) + r1          (lower ограничен снизу нулём)
    β_weak = 0.5·β_τ;   β_strong = max(m_τ·β_τ, −1.0),   m_τ = max(1, прошлые rolling-origin отношения)
```

## 3. Происхождение baseline

| Что | Как выбрано | Какие данные | EVAL 2025H2/2026 использован? |
|---|---|---|---|
| Форма «смешение ПАК» вместо persistence/ridge/CatBoost | MAE на VAL | 2025H1 | нет |
| w = 0.15 в оценке раунда 2 (F4–F5) | сетка 0…1 шаг 0.05, MAE | FIT: target < 2025-01-01 | нет |
| w = 0.20 и радиусы 2.35/3.37 в версии 2 документа | переоценка на окнах 2025-02…2026-08 | **2025H2 и 2026** | **да — это production-переоценка; радиус для шага был посчитан без β·ΔT, ошибка** |
| **w_τ по правилу версии 3** | та же сетка, MAE на строках с target в (τ−18 мес., τ−6 мес.] | только прошлое τ | нет по построению |

Проверка правила:
- при τ = 2025-07-01 → w = 0.10; при τ = 2026-01-01 → w = 0.10; MAE следующего полугодия 0.721 / 0.998;
- с зафиксированным w = 0.15 — 0.720 / 0.994;
- выбор w в пределах 0.10–0.20 на качество не влияет.

**Смысл baseline.** Через 3 ч ПАК в основном возвращается к суточному уровню: 80–90% веса у PAK24h.

## 4. Аудит утечек и неоднозначностей

| # | Находка | Статус |
|---|---|---|
| 1 | k/β и диапазон в раунде 1 оценены с участием 2026 | исправлено в раунде 2 (F0) |
| 2 | Флаг «зависания» ПАК (`common.flat_mask`) использовал будущий конец плато | заменён правилом только по прошлому; отличие 0.23% бинов, изменение MAE baseline ≤ 0.0005 — пересчёт выводов не нужен |
| 3 | Признак `stable` смотрит на 6 ч вперёд | разрешён только для отбора обучающих строк; все окна `fit` заканчиваются в τ − 6 ч; в live — `run_past12h` |
| 4 | w = 0.20 и радиусы v2 взяты из окон с EVAL; радиус шага без β·ΔT | заменено rolling-правилом (§3); r1 считается по остаткам полной модели |
| 5 | Правило окна 12 мес. и множители выбраны после просмотра дрейфа | окно 12 мес. и weak = 0.5 — объявленные константы (post-hoc, помечено); m_τ считается только по прошлым полугодиям; ограничение −1.0 — априорное (эксперт) |
| 6 | Единицы support: ΔT — устойчивый шаг, аналоги — начальный 30-мин шаг A30 | принято: support измеряет, делались ли **шаги такого размера** в похожем режиме; устойчивая доставка шага ≈ 0.66–1.3·A30 |
| 7 | T11/F26/H₂ назывались входами модели | разделено: входы прогноза только ПАК и ΔT (§2) |
| 8 | Пример в версии 2 считался по ручным числам | пример v3 получен через `predict` (§7) |

## 5. Operating envelope

Пороги объявлены до расчёта долей.

| Зона | Условие | Что разрешено говорить |
|---|---|---|
| **HOLD** | ΔT = 0, ПАК валиден | прогноз baseline с интервалом r0 |
| **A_SUPPORTED** (интерполяция) | 0 < |ΔT| ≤ 1 °C, ≥ 5 неспровоцированных аналогов того же знака с |A30 − ΔT| ≤ 0.5 в радиусе 0.5 SD по (T11, T11_30d, F26, H₂/сырьё), все проверки допуска | эффект подкреплён данными, с диапазоном [β_weak·ΔT; β_strong·ΔT] |
| **B_EXTRAPOLATION** | проверки допуска пройдены, но |ΔT| > 1 °C (до 2) или аналогов < 5 | линейная экстраполяция β. Годится только консервативный край: польза — по β_weak, вред — по β_strong. «Data-backed» не называть |
| **C_FORBIDDEN** (отказ) | |ΔT| > 2 °C; T11 или T11+ΔT вне q01–q99 истории; F26 вне q01–q99; нет 12 ч работы; ПАК завис или нет значения за 30 мин; покрытие ПАК за 24 ч < 50%; артефакт старше 6 мес. или новее t; β_τ ≥ 0 | прогноза эффекта нет |

Доли зон на реальных состояниях (артефакт, обученный на начало полугодия):

| ΔT | 2025H2: A / B / C | 2026: A / B / C |
|---|---|---|
| ±0.5 | 83–84% / 15–17% / 0.9% | 58–63% / 18–23% / 19% |
| ±1 | 65–67% / 32–34% / 0.9% | 37–38% / 43–45% / 19% |
| ±1.5, ±2 | 0 / 99% / 0.9% | 0 / 81% / 19% |

- В 2026 зона C на 18.1 п.п. из 19% — это возраст артефакта: состояния после 2026-07-01 с артефактом от 2026-01-01.
  При ежемесячном переобучении их нет. Остальное: ПАК завис или нет значения — 1.9%, покрытие 24 ч — 2.0%, T11 вне диапазона — 0.6%.
- Реальные переходы 2025H2–2026 по зонам:
  - A: n 1985, MAE 0.85, покрытие 0.97;
  - B: n 1443, MAE 1.27, покрытие 0.90;
  - C: n 464, отказ.

**Итог envelope.** Данными подкреплены шаги до ±1 °C, и то не во всех режимах. ±1.5…2 °C — всегда экстраполяция.
Больше 2 °C за шаг — запрещено.

## 6. TRAINING — процедура `fit(τ)`

```
raw data
  task/data/242000_tags.csv (10 мин): T11, T5, T6, F26, F19, P13, F2;  Выгрузка ПАК.xlsx: 24-2000:Mg.Sulfur
  │
  ▼ preprocessing  (prepare)
  pak_bin(t)    = mean показаний в (t−10м, t];  frozen(t) = (t − начало текущего плато) ≥ 1 ч
  pak(t)        = pak_bin, если не frozen и 0.05 ≤ pak_bin ≤ 50, иначе NaN
  running(t)    = F26>150 ∧ T11>320 ∧ T5>320 ∧ P13>3 ∧ F2>30000 ∧ F19/F26∈[0.75,0.9] ∧ нет 307
  run_past12h   = running на всём (t−12ч, t];   stable_label = run_past12h(t) ∧ running на [t, t+6ч]
  T11_30d(t)    = mean T11 за (t−30сут, t] при run_past12h (≥ 1000 бинов)
  │
  ▼ decision rows каждые 30 мин  (rows)
  PAK30m, PAK24h (≥72 бина), PAK24h_cov, PAK1h, T11, F26, H2/сырьё (30 мин), T11_30d
  A30  = mean T11 (t, t+30м] − mean T11 (t−30м, t]
  onset = |T11 − mean T11 (t−90м, t−60м]| < 0.5 ∧ |PAK30m − mean pak (t−90м, t−30м]| < 0.5 ∧ |PAK1h − PAK24h| < 1
  y3   = mean pak (t+3ч, t+3ч30м] (≥ 2 из 3 бинов)
  train_valid = stable_label в t−7ч, −1ч, 0, +30м, +1ч, +2ч, +3ч, +3.5ч ∧ все поля конечны
  usable = train_valid ∧ (t + 3.5ч) ≤ τ − 6ч
  │
  ▼ baseline parameters
  w_τ = argmin_{w ∈ {0,…,1} шаг .05} MAE(y3, w·PAK30m + (1−w)·PAK24h)   на usable, target ∈ (τ−18м, τ−6м]
  │
  ▼ rolling ARX β
  ряд 10 мин в (τ−12м, τ−6ч], stable_label ∧ stable_label(−4ч) ∧ pak:
     p30 = mean pak за 30 мин;  ΔX = первые разности (T11, F26, p30)
     Δp30_t = c + Σ_{j=1..24} (b_j ΔT11_{t−j} + g_j ΔF26_{t−j} + a_j Δp30_{t−j}) + e      (OLS)
     симуляция: ступень ΔT11 = +1 в момент 0, ΔF26 = 0 → кумулятивный отклик R(k)
     β_τ = mean R(k), k = 18…48 (3.0…8.0 ч);  CI90 — бутстреп по месяцам (40)
  если β_τ ≥ 0 → артефакт не допускает ΔT ≠ 0
  │
  ▼ multipliers
  для каждого полугодия H с концом ≤ τ−6ч и 12 мес. истории до него:
     ratio_H = β(ARX на H) / β(ARX на 12 мес. до H)
  m_τ = max(1, max ratio_H)  (нет H → 2.5);  β_weak = 0.5·β_τ;  β_strong = max(m_τ·β_τ, −1.0)
  │
  ▼ uncertainty calibration
  строки usable с target ∈ (τ−6м, τ−6ч]:  res = |y3 − (w_τ·PAK30m + (1−w_τ)·PAK24h + β_τ·0.66·A30)|
  r0 = q0.90(res | |A30| < 1);   r1 = q0.90(res | |A30| ≥ 1)          (0.66 — доставка шага за 3 ч, F1 на SELECT)
  │
  ▼ support context
  все usable строки: q01/q99 T11 и F26; μ, σ (T11, T11_30d, F26, H2/сырьё); таблица onset-строк (z-признаки, A30)
  │
  ▼ artifact  {τ, w_τ, β_τ, CI, m_τ, β_weak, β_strong, r0, r1, q01/q99, μ, σ, таблица аналогов, окна дат}
```

Частота: переобучение не реже раза в месяц; артефакт старше 6 месяцев не используется.

## 7. LIVE — процедура `predict(state, ΔT)`

```
PAK за 24 ч + T11, F26, F2 за 30 сут + предлагаемое ΔT
  │ live_state(t): PAK30m, PAK24h, PAK24h_cov, pak_frozen_now, T11, T11_30d, F26, H2/сырьё, run_past12h
  ▼ проверки зоны C → при нарушении: zone = C_FORBIDDEN, reasons, без прогноза
  ▼ baseline  = w_τ·PAK30m + (1−w_τ)·PAK24h
  ▼ ΔT = 0 → HOLD: [baseline ± r0]
  ▼ ΔT ≠ 0 → sulfur_mid = baseline + β_τ·ΔT; интервал по §2 с r1
  ▼ support: число аналогов → zone A (|ΔT| ≤ 1 ∧ ≥ 5) или B
  ▼ выход: zone, baseline, sulfur_mid, [lower, upper], effect_mid/weak/strong, support_analogs, β_τ, τ
```

Пример через `predict` (артефакт τ = 2026-01-01: w 0.10, β −0.389, β_weak −0.194, β_strong −1.0, r0 1.48, r1 2.48;
состояние 2026-01-05 08:00: PAK30m 5.88, PAK24h 4.71, T11 368.3):

| ΔT | зона | S(t+3h) | интервал | эффект mid (weak…strong) | аналогов |
|---|---|---|---|---|---|
| 0 | HOLD | 4.82 | [3.34; 6.31] | 0 | — |
| +0.5 | A_SUPPORTED | 4.63 | [1.84; 7.21] | −0.19 (−0.10…−0.50) | 11 |
| +1 | B_EXTRAPOLATION | 4.43 | [1.34; 7.11] | −0.39 (−0.19…−1.0) | 1 |
| +2 | B_EXTRAPOLATION | 4.05 | [0.34; 6.92] | −0.78 (−0.39…−2.0) | 0 |
| −1 | B_EXTRAPOLATION | 5.21 | [2.54; 8.30] | +0.39 (+0.19…+1.0) | 3 |
| +2.5 | C_FORBIDDEN | — | — | — | — |

## 8. Артефакты и проверка процедуры на следующем полугодии

| τ | w | β_τ [CI90] | m_τ | β_weak / β_strong | r0 / r1 | Следующее полугодие: MAE все / с шагом | Покрытие все / спокойные / с шагом |
|---|---|---|---|---|---|---|---|
| 2025-07-01 | 0.10 | −0.348 [−0.373; −0.315] | 2.64 | −0.174 / −0.917 | 1.69 / 2.28 | 0.721 / 1.161 (baseline 0.741) | 0.937 / 0.938 / 0.920 |
| 2026-01-01 | 0.10 | −0.389 [−0.444; −0.351] | 2.64 | −0.194 / −1.0 | 1.48 / 2.48 | 0.998 / 1.382 (baseline 1.014) | 0.825 / 0.820 / 0.886 |
| **2026-08-07 (текущий)** | **0.20** | **−0.595 [−0.643; −0.560]** | 2.64 | **−0.298 / −1.0** | **2.15 / 3.19** | — | — |

- Текущий артефакт: q01–q99 T11 345.3–383.1 °C, F26 171–302 м³/ч; таблица аналогов — 12 763 onset-строки;
  прошлые отношения 1.37, 2.64, 1.02, 1.52, 1.68.
- **Ограничение.** В 2026 интервал спокойных строк недопокрывает: 0.82 при цели 0.90 — волатильность ПАК выросла после 2025H2.
  Номинальное покрытие для HOLD в новых режимах не гарантируется.

## 9. Почему именно эта модель (кратко, раунд 2)

- **Прямая ML «состояние + шаг → сера»:** немонотонна в 11% состояний, после +2 °C прогноз не меняется,
  по out-of-time калибровке не лучше. Отклонена.
- **Мультипликативная форма и β(state):** не улучшают out-of-fold loss; зависимости от T и стадии катализатора
  меняют знак между циклами.
- **Эффект по методам:** знак устойчив (ARX, DML, matching, onset, окна слабой обратной связи APC).
  Величина нестационарна: ARX по полугодиям −0.13 → −0.65 за 3.5 года. Отсюда trailing-окно и широкий диапазон.
- **Горизонт 3 ч:** короче эффект смешан с реакцией APC; с 3 до 8–9 ч плато.
- **Смысл тегов** T11 = вход реактора, F26 = объёмный расход сырья выведен из данных и противоречит сообщению эксперта 520.
  До внедрения его нужно подтвердить.
- **Интерпретация:** это эмпирический отклик в замкнутом контуре APC, не доказанная причинная связь.
  Данными подкреплена только зона A.

---

## 10. Псевдокод

```text
CONSTANTS
  H = 3h; GUARD = 6h; FS = 0.66; WEAK = 0.5; STRONG_CAP = -1.0; STRONG_DEFAULT = 2.5
  MAX_DT = 2.0; ZONE_A_MAX_DT = 1.0; MIN_ANALOGS = 5; RADIUS_SD = 0.5; MAX_AGE = 6 months
  W_GRID = {0.00, 0.05, ..., 1.00}; ARX_LAGS = 24 (10-min); PLATEAU = steps 18..48 (3..8 h)

function prepare(raw_tags, raw_pak):
  for each 10-min bin t:
    pak_bin[t]  = mean(pak readings in (t-10m, t])
    frozen[t]   = (t - start_of_current_constant_run) >= 1h
    pak[t]      = pak_bin[t] if not frozen[t] and 0.05 <= pak_bin[t] <= 50 else NaN
    running[t]  = F26>150 and T11>320 and T5>320 and P13>3 and F2>30000
                  and 0.75 <= F19/F26 <= 0.9 and no tag == 307
    run_past12h[t]  = all(running in (t-12h, t])
    stable_label[t] = run_past12h[t] and all(running in [t, t+6h])        # training only
    T11_30d[t]      = mean(T11 in (t-30d, t] where run_past12h), needs >= 1000 bins
  return frame

function rows(frame, times):          # every 30 min
  for t in times:
    PAK30m = mean(pak in (t-30m, t]) (>=1);  PAK24h = mean(pak in (t-24h, t]) (>=72);  PAK24h_cov = share valid
    PAK1h = mean(pak in (t-1h, t]);  T11, F26, H2oil = mean over (t-30m, t];  T11_30d = T11_30d[t]
    A30   = mean(T11 in (t, t+30m]) - T11
    onset = |T11 - mean(T11 in (t-90m, t-60m])| < 0.5 and |PAK30m - mean(pak in (t-90m, t-30m])| < 0.5
            and |PAK1h - PAK24h| < 1
    y3    = mean(pak in (t+3h, t+3h30m]) (>=2 of 3)
    train_valid = stable_label at t-7h, t-1h, t, t+30m, t+1h, t+2h, t+3h, t+3h30m and all fields finite

function arx_beta(frame, start, end):
  select 10-min bins k in (start, end] with stable_label[k], stable_label[k-24], pak[k] finite
  p30 = rolling mean of pak over 30 min; dT = diff(T11); dF = diff(F26); dP = diff(p30)
  OLS: dP[k] = c + sum_{j=1..24} ( b_j*dT[k-j] + g_j*dF[k-j] + a_j*dP[k-j] )
  simulate: u[0] = 1 (dT impulse = permanent +1 °C step), dF = 0
            y[k] = sum_j b_j*u[k-j] + sum_j a_j*y[k-j];  R[k] = cumsum(y)[k]
  return mean(R[18..48])

function fit(frame, R, tau):
  cut = tau - GUARD
  U = R where train_valid and (t + 3.5h) <= cut
  # baseline
  Uw = U where (t + 3.5h) in (tau - 18 months, tau - 6 months]
  w = argmin_{w in W_GRID} mean |Uw.y3 - (w*Uw.PAK30m + (1-w)*Uw.PAK24h)|
  # response
  beta = arx_beta(frame, tau - 12 months, cut);  beta_ci = month-block bootstrap of arx_beta
  ratios = []
  for each half-year H = [s, s+6m) with s+6m <= cut and s-12m >= data_start:
    prev = arx_beta(frame, s-12m, s);  real = arx_beta(frame, s, s+6m)
    if prev < -0.02: ratios.append(real / prev)
  m = max(1, max(ratios)) if ratios else STRONG_DEFAULT
  beta_weak = WEAK * beta;  beta_strong = max(m * beta, STRONG_CAP)          # only if beta < 0
  # uncertainty
  Ur = U where (t + 3.5h) in (tau - 6 months, cut]
  res = |Ur.y3 - (w*Ur.PAK30m + (1-w)*Ur.PAK24h + beta*FS*Ur.A30)|
  r0 = quantile_0.90(res where |A30| < 1);  r1 = quantile_0.90(res where |A30| >= 1)
  # support
  q = quantiles 0.01/0.99 of U.T11 and U.F26;  mu, sd of (T11, T11_30d, F26, H2oil) over U
  analogs = { (z = (x - mu)/sd, A30) for rows in U where onset }
  return Artifact(tau, w, beta, beta_ci, m, beta_weak, beta_strong, r0, r1, q, mu, sd, analogs)

function predict(art, state, delta_T):        # state = live_state(frame, t), data up to t only
  reasons = []
  if state.t < art.tau or state.t - art.tau > MAX_AGE: reasons += "artifact age"
  if not state.run_past12h:                           reasons += "no 12 h running"
  if state.pak_frozen_now or state.PAK30m is NaN:     reasons += "PAK frozen/missing"
  if state.PAK24h is NaN or state.PAK24h_cov < 0.5:   reasons += "PAK 24h coverage"
  if delta_T != 0:
    if not (art.beta < 0):                            reasons += "beta not negative"
    if |delta_T| > MAX_DT:                            reasons += "step > 2 °C"
    if state.T11 or state.T11 + delta_T outside art.q(T11): reasons += "T11 range"
    if state.F26 outside art.q(F26):                  reasons += "F26 range"
  if reasons: return {zone: C_FORBIDDEN, reasons}

  base = art.w * state.PAK30m + (1 - art.w) * state.PAK24h
  if delta_T == 0:
    return {zone: HOLD, sulfur_mid: base, lower: max(0, base - art.r0), upper: base + art.r0}

  e_mid = art.beta * delta_T;  e_weak = art.beta_weak * delta_T;  e_strong = art.beta_strong * delta_T
  lower = max(0, base + min(e_weak, e_strong) - art.r1)
  upper = base + max(e_weak, e_strong) + art.r1
  z = ((state.T11, state.T11_30d, state.F26, state.H2oil) - art.mu) / art.sd
  n = count(analogs with ||analog.z - z|| <= RADIUS_SD and sign(analog.A30) == sign(delta_T)
            and |analog.A30 - delta_T| <= 0.5)
  zone = A_SUPPORTED if (|delta_T| <= ZONE_A_MAX_DT and n >= MIN_ANALOGS) else B_EXTRAPOLATION
  return {zone, baseline: base, sulfur_mid: base + e_mid, lower, upper,
          effect_mid: e_mid, effect_weak: e_weak, effect_strong: e_strong,
          support_analogs: n, beta_tau: art.beta, artifact_tau: art.tau}
```
