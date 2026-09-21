"""Реестр исключённых из данных периодов (задача пула S1, QA-сессия 21.09, раздел 12).

Строит воспроизводимый список интервалов «с … по …» и причину для того, что в исходных
данных `task/` реально размечено кодом проекта как непригодное/исключённое:

- колонки телеметрии, которые целиком являются заглушкой 307 (`mask_stubs`,
  `DEAD_COLUMN_STUB_SHARE`, `STUB_VALUE`);
- временные интервалы, где заглушка 307 стоит одновременно во многих колонках строки
  (массовый сбой опроса, см. `context/task-review/data-facts.md`);
- временные интервалы «зависания» поточного анализатора серы (ПАК) — N подряд неизменных
  показаний, порог берётся тем же способом, что при обучении (`derive_source_rules`,
  `_untrusted_runs` в `infrastructure/data/rules.py`);
- отдельные лабораторные пробы, где показание ПАК на момент отбора расходится с ЛИМС
  (`conflict_mask`) — точечные события, не интервалы.

Это диагностический скрипт, а не часть production-конвейера `neftecode`. Он работает по
исходным `task/` (если их нет в рабочем дереве — см. `--root`, указывающий на каталог,
где есть `task/`) и не изменяет `src/`.

Запуск:

    uv run python scripts/excluded_periods.py --root <каталог с task/> \
        --out context/excluded-periods.json

Если `task/<root>` не содержит исходных файлов, скрипт не выдумывает интервалы: он
завершается с понятным сообщением и (если указан `--allow-missing`) пишет артефакт
с пустым реестром и явным перечнем ограничений.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from neftecode.infrastructure.data.rules import _untrusted_runs, conflict_mask, derive_source_rules  # noqa: E402
from neftecode.infrastructure.data.sources import DEAD_COLUMN_STUB_SHARE, STUB_VALUE, load_sources  # noqa: E402


def _load_raw_signals(task: Path) -> pd.DataFrame:
    """Телеметрия без маскировки 307 — нужна, чтобы увидеть сам артефакт, а не его следствие."""
    frames = []
    for filename, prefix in [("avt_tags.csv", "avt"), ("242000_tags.csv", "ht")]:
        frame = pd.read_csv(task / "data" / filename)
        frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed:")]
        frame["date"] = pd.to_datetime(frame.date, errors="raise")
        frame = frame.set_index("date").sort_index().astype(float)
        frames.append(frame.add_prefix(prefix + "."))
    return pd.concat(frames, axis=1).sort_index()


def _runs(flag: pd.Series) -> list[dict]:
    """Группирует подряд идущие True в интервалы [начало, конец] по индексу времени flag."""
    if flag.empty:
        return []
    flag = flag.fillna(False)
    group = (flag != flag.shift()).cumsum()
    out = []
    for _, idx in flag[flag].groupby(group[flag]).groups.items():
        idx = pd.DatetimeIndex(idx)
        out.append({"from": idx.min().isoformat(), "to": idx.max().isoformat(), "n_readings": int(len(idx))})
    return out


def build_registry(task: Path, cfg: dict, row_stub_threshold: int) -> dict:
    signals_raw = _load_raw_signals(task)
    signals, lab, online = load_sources(task, dead_until=None)

    dead = [c for c in signals_raw.columns if (signals_raw[c] == STUB_VALUE).mean() > DEAD_COLUMN_STUB_SHARE]
    dead_columns = []
    for col in dead:
        share = float((signals_raw[col] == STUB_VALUE).mean())
        non_stub = signals_raw.index[signals_raw[col] != STUB_VALUE]
        dead_columns.append({
            "column": col,
            "stub_share": round(share, 4),
            "data_from": signals_raw.index.min().isoformat(),
            "data_to": signals_raw.index.max().isoformat(),
            "non_stub_readings": int(len(non_stub)),
            "reason": f"Заглушка опроса 307 в {share:.1%} строк за всю историю (порог "
                      f"{DEAD_COLUMN_STUB_SHARE:.0%}); колонка исключена из признаков целиком, "
                      "а не по интервалу (config/experiment.json, assumptions).",
        })

    stub_count = (signals_raw == STUB_VALUE).sum(axis=1)
    burst_flag = stub_count >= row_stub_threshold
    stub_bursts = _runs(burst_flag)
    for b in stub_bursts:
        window = stub_count.loc[b["from"]:b["to"]]
        b["max_columns_at_307"] = int(window.max())
        b["reason"] = (f"Массовый сбой опроса: одновременно ровно 307 в {row_stub_threshold}+ "
                        "колонках телеметрии в одной строке (см. context/task-review/data-facts.md).")

    rules = derive_source_rules(signals, lab, online, cfg["train_end"], cfg)
    full_cfg = {**cfg, **rules}

    pak = online.set_index("time").value
    frozen_flag = _untrusted_runs(pak, full_cfg)
    frozen_runs = _runs(frozen_flag)
    for r in frozen_runs:
        r["reason"] = (f"Зависание ПАК: {full_cfg['pak_frozen_readings']}+ подряд неизменных показаний "
                        "(порог выведен derive_source_rules из истории до train_end, как при обучении).")

    pak_period = float(rules["pak_period_minutes"])
    joined = pd.merge_asof(
        lab.sort_values("time"), online.rename(columns={"value": "pak"}).sort_values("time"),
        on="time", direction="backward",
        tolerance=pd.Timedelta(value=pak_period * cfg.get("source_rule_method", {}).get("pak_age_periods", 3), unit="m"),
    ).dropna(subset=["pak"])
    conflict = conflict_mask(joined.pak.to_numpy(), joined.value.to_numpy(), full_cfg)
    conflicts = []
    for _, row in joined.loc[conflict].iterrows():
        conflicts.append({
            "at": row.time.isoformat(),
            "lab_mgkg": float(row.value),
            "pak_ppm": float(row.pak),
            "reason": "Показание ПАК на момент отбора пробы расходится с результатом ЛИМС "
                      f"сверх порога {full_cfg['pak_conflict_mgkg']:g} мг/кг (conflict_mask); "
                      "точечное событие пробы, не интервал.",
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "scripts/excluded_periods.py",
        "task_root": str(task),
        "row_stub_threshold": row_stub_threshold,
        "derived_rules_until_train_end": {k: rules[k] for k in rules if k != "source_rules"},
        "dead_columns_excluded_entirely": dead_columns,
        "stub_row_bursts": stub_bursts,
        "pak_frozen_intervals": frozen_runs,
        "pak_lab_conflict_events": conflicts,
        "not_reproduced_by_this_script": [
            "Плановые остановки установки (стоп производства): в task/ нет отдельного флага "
            "«установка остановлена»; в infrastructure/data и services/trust нет списка конкретных "
            "исторических интервалов останова, только пороги качества данных (возраст, зависание, "
            "конфликт, пропуски). Даты остановок не выдуманы.",
            "Устаревание ЛИМС как отдельный реестр периодов: возраст пробы проверяется на каждый "
            "момент решения (lab_max_age_hours в trust.py/_lab_verdict), а не хранится как список "
            "интервалов простоя лаборатории; при необходимости реестр строится по тем же данным "
            "отдельным проходом по времени готовности каждой пробы.",
            "Покрытие плотности ПАК (24-2000:D15) — данные есть только с 2025-03-05 "
            "(см. context/task-review/data-facts.md); load_sources() не читает D15, поэтому этот "
            "скрипт не переcчитывает интервал отсутствия — это не детектируемое исключение, а "
            "изначальный пробел источника.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Каталог, где лежит task/")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "experiment.json")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "context" / "excluded-periods.json")
    parser.add_argument("--row-stub-threshold", type=int, default=10,
                        help="Сколько колонок одновременно должны быть ровно 307 в строке, "
                             "чтобы считать это массовым сбоем (по умолчанию 10, как в audits)")
    parser.add_argument("--allow-missing", action="store_true",
                        help="Не падать, если task/ отсутствует — записать артефакт с ограничением")
    args = parser.parse_args()

    task = args.root / "task"
    cfg = json.loads(args.config.read_text(encoding="utf-8"))

    if not (task / "data" / "avt_tags.csv").exists():
        message = (f"Нет исходных данных в {task}: task/ не входит в Git (см. README, раздел "
                   "«Данные и артефакты»). Реестр не может быть пересчитан без исходного пакета.")
        if not args.allow_missing:
            print("Ошибка: " + message, file=sys.stderr)
            return 2
        print("Предупреждение: " + message, file=sys.stderr)
        registry = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "scripts/excluded_periods.py",
            "task_root": str(task),
            "error": message,
            "dead_columns_excluded_entirely": [],
            "stub_row_bursts": [],
            "pak_frozen_intervals": [],
            "pak_lab_conflict_events": [],
            "not_reproduced_by_this_script": [message],
        }
    else:
        registry = build_registry(task, cfg, args.row_stub_threshold)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Записано {args.out}")
    print(f"  колонок исключено целиком: {len(registry['dead_columns_excluded_entirely'])}")
    print(f"  интервалов массового сбоя 307: {len(registry['stub_row_bursts'])}")
    print(f"  интервалов зависания ПАК: {len(registry['pak_frozen_intervals'])}")
    print(f"  конфликтов ПАК/ЛИМС (точки): {len(registry['pak_lab_conflict_events'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
