import argparse
import hashlib
import json
from pathlib import Path
import pickle
import platform

import numpy as np
import pandas as pd

from .agents import Coordinator, Forecast
from .data import load_sources, make_dataset
from .forecast import run_experiment
from .risk import run_risk_experiment
from .runtime import decision_at, validate_origin
from .benchmark import compare as compare_strategies
from .batch import _as_series, classify_episodes, excursion_episodes, sampling_step_hours, violation_profile
from .margin import lead_times, margin_series
from .quality import report as quality_report, read_quality_series
from .demo import Demo, scenes as demo_scenes
from .live import LiveAdvisor
from .server import serve as serve_demo
from .ui import Screen, error_payload, write_screen
from .vak import check_all


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def write_json(path, obj):
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def fingerprint(root, cfg):
    files = [*sorted((root / "task/data").glob("*.csv")), *sorted((root / "task").glob("*.xlsx")),
             *sorted((root / "src/neftecode").glob("*.py")), root / "uv.lock"]
    hashes = {}
    for path in files:
        with path.open("rb") as stream:
            hashes[str(path.relative_to(root))] = hashlib.file_digest(stream, "sha256").hexdigest()
    key = hashlib.sha256(json.dumps([hashes, cfg], sort_keys=True).encode()).hexdigest()
    return {"fingerprint": key, "files": hashes, "config": cfg, "python": platform.python_version()}


def train(root, out, cfg):
    manifest = fingerprint(root, cfg)
    print("Чтение телеметрии и независимых временных рядов ЛИМС/ПАК…", flush=True)
    signals, lab, online = load_sources(root / "task")
    x, meta = make_dataset(signals, lab, online, cfg)
    print(f"{len(signals)} строк телеметрии, {len(meta)} независимых целевых анализов, {len(x.columns)} признаков", flush=True)
    print("Сравнение пяти методов на последовательных периодах…", flush=True)
    bundle, summary, predictions = run_experiment(x, meta, cfg)
    print("Отдельная проверка обнаружения превышений и ложных тревог…", flush=True)
    risk_bundle, risk_summary, risk_predictions = run_risk_experiment(x, meta, cfg)
    bundle["risk"] = risk_bundle
    risk_columns = [c for c in risk_predictions if c.startswith("risk_") and not c.startswith("risk_catboost")]
    predictions = predictions.merge(risk_predictions[["decision_time", *risk_columns]], on="decision_time", validate="one_to_one")
    risk_predictions.to_csv(out / "risk_predictions.csv", index=False)
    write_json(out / "risk_metrics.json", risk_summary)
    print("Оценка доступности по каждому показателю качества…", flush=True)
    availability = quality_report(root / "task")
    bundle["quality_availability"] = availability
    summary["quality_availability"] = availability
    # T95 has its own laboratory series at the same point, so it gets the same honest treatment.
    series = read_quality_series(root / "task")
    extra = {}
    for name in availability["modelled"]:
        if name == "sulfur_mgkg":
            continue
        try:
            xq, mq = make_dataset(signals, lab, online, cfg, target_lab=series[name])
            # Risk thresholds belong to the measured property.  In particular,
            # an absent T95 product limit remains unknown; sulfur's 10 mg/kg
            # limit must never be inherited by a temperature forecast.
            quality_cfg = cfg.get("quality_metrics", {}).get(name, {})
            qbundle, qsummary, _ = run_experiment(
                xq, mq, cfg, target="actual_target",
                limit=quality_cfg.get("limit"),
                direction=quality_cfg.get("direction", "max"),
                near_margin=quality_cfg.get("near_margin"),
            )
            extra[name] = {"selected": qsummary["selected"],
                           "limit": qsummary["limit"],
                           "direction": qsummary["direction"],
                           "near_margin": qsummary["near_margin"],
                           "selection_decision": qsummary["selection_decision"],
                           "models": {k: {"validation_common_mae": v["validation_common_mae"],
                                          "test": v["test"]} for k, v in qsummary["models"].items()}}
            bundle.setdefault("extra_models", {})[name] = qbundle
            print(f"  {name}: выбран {qsummary['selected']}", flush=True)
        except ValueError as exc:
            extra[name] = {"selected": None, "reason": str(exc)}
            print(f"  {name}: прогноз не построен — {exc}", flush=True)
    summary["extra_targets"] = extra
    bundle["manifest"] = manifest
    with (out / "model.pkl").open("wb") as stream:
        pickle.dump(bundle, stream)
    predictions.to_csv(out / "predictions.csv", index=False)
    write_json(out / "metrics.json", summary)
    write_json(out / "manifest.json", manifest)
    print(f"Выбран по validation: {summary['selected']}", flush=True)
    make_demo(root, out)


STATE_COLUMNS = ["decision_time", "lab_sample_time", "lab_available_time", "lab_value", "lab_age_hours",
                 "lab_usable", "pak_sample_time", "pak_value", "pak_age_minutes", "pak_frozen",
                 "pak_conflict", "pak_usable", "telemetry_missing_fraction"]


def from_row(row, prefix, model):
    return Forecast(*[clean(row[prefix + c]) for c in ("prediction", "lower", "upper")], model)


def risk_from_row(row):
    return {name: {field: clean(row.get(prefix + field)) for field in ("score", "threshold", "model")}
            for name, prefix in [("main", "risk_"), ("fallback", "risk_fallback_")]}


def make_demo(root, out):
    cfg = json.loads((root / "config/blending-demo.json").read_text())
    coordinator = Coordinator(cfg)
    # Synthetic inputs test the decision mechanics independently of forecast performance.
    healthy = {"decision_time": "2026-01-15T10:00:00",
               "lab_value": 8.0, "lab_age_hours": 5.0, "lab_usable": True,
               "pak_value": 8.4, "pak_age_minutes": 10.0, "pak_usable": True,
               "pak_frozen": False, "pak_conflict": False, "telemetry_missing_fraction": 0,
               "origin": "synthetic_acceptance_test"}
    demos = {}
    demos["normal_synthetic"] = coordinator.run(healthy, Forecast(6, 4, 8, "synthetic"))
    demos["conflict_synthetic"] = coordinator.run(healthy, Forecast(12, 10, 14, "synthetic"))
    demos["missing_synthetic"] = coordinator.run(
        dict(healthy, lab_value=None, lab_usable=False, pak_value=None, pak_usable=False,
             telemetry_missing_fraction=1), Forecast(None, None, None, "missing"))
    demos["no_feasible_synthetic"] = coordinator.run(healthy, Forecast(100, 80, 120, "synthetic"))
    replay_rows = []
    if (out / "predictions.csv").exists():
        frame = pd.read_csv(out / "predictions.csv")
        summary = json.loads((out / "metrics.json").read_text())
        for _, row in frame.iterrows():
            # Deliberate allowlist: future target and its actual value NEVER reach agents.
            state = clean({key: row[key] for key in STATE_COLUMNS})
            state["origin"] = "historical_replay_with_synthetic_blending"
            forecast = from_row(row, "", summary["selected"])
            fallback = from_row(row, "fallback_", "catboost_no_pak")
            risk = risk_from_row(row)
            decision = coordinator.run(state, forecast, fallback, risk)
            key = "historical_" + decision["status"]
            if key not in demos:
                demos[key] = decision
            replay_rows.append({"decision_time": row.decision_time, "decision_id": decision["decision_id"],
                                "status": decision["status"], "source": decision["trust"]["source"],
                                "forecast_model": decision["forecast"]["model"],
                                "risk_model": decision["risk"]["model"], "risk_alarm": decision["risk"]["alarm"]})
            if state["pak_usable"] and state["lab_usable"] and "frozen_pak_injected" not in demos:
                damaged = dict(state, pak_usable=False, pak_frozen=True, origin="historical_state_with_injected_pak_failure")
                demos["frozen_pak_injected"] = coordinator.run(damaged, forecast, fallback, risk)
        pd.DataFrame(replay_rows).to_csv(out / "replay.csv", index=False)
        summary["replay"] = {
            "n": len(replay_rows),
            "statuses": pd.Series([r["status"] for r in replay_rows]).value_counts().to_dict(),
            "scope": "Работа механизма рекомендаций в синтетическом смешении; не доказательство экономии или безопасности реального выпуска.",
        }
        write_json(out / "metrics.json", summary)
    write_json(out / "demo.json", demos)
    with (out / "audit.jsonl").open("w") as stream:
        for name, decision in demos.items():
            stream.write(json.dumps(clean({"case": name, **decision}), ensure_ascii=False, allow_nan=False) + "\n")
    make_report(out, demos)
    print(f"Готово: {out / 'report.md'}", flush=True)


def selection_section(summary):
    """Why this forecast won, and what the system can estimate at all."""
    lines = []
    choice = summary.get("selection_decision", {})
    if choice:
        lines += ["## Почему выбран именно этот прогноз", "",
                  f"Базовый простой прогноз — **{choice['baseline']}**, ошибка {choice['baseline_mae']:.4f}."]
        if choice.get("challenger"):
            lines += [f"Лучший обучаемый претендент — **{choice['challenger']}**, ошибка "
                      f"{choice['challenger_mae']:.4f}: выигрыш {choice['relative_gain']:.2%} при "
                      f"доверительном интервале разности "
                      f"[{choice['bootstrap']['ci_low']:.4f}, {choice['bootstrap']['ci_high']:.4f}]."]
        lines += [choice["reason"] + ".", "",
                  f"Сложная модель заменяет простую только при выигрыше не меньше "
                  f"{choice['min_relative_gain']:.0%} и доверительном интервале разности, не накрывающем ноль. "
                  "Сравнение парное, на одних и тех же анализах: иначе доступность прогноза выдавала бы "
                  "себя за точность.", ""]
    availability = summary.get("quality_availability")
    if availability:
        lines += ["## Что система может оценить", "",
                  "| Показатель | Лабораторных анализов | Способ оценки |", "|---|---:|---|"]
        for name, source in availability["sources"].items():
            lines.append(f"| {name} | {source['n_analyses']} | {source['method']} |")
        lines += ["", "Обученная модель заявляется только при достаточном числе анализов. Показатель "
                  "без модели берёт значение из сценария с пометкой допущения либо остаётся неизвестным; "
                  "неизвестное критическое свойство блокирует план, а не проходит проверку.", ""]
    for name, result in (summary.get("extra_targets") or {}).items():
        decision = result.get("selection_decision")
        if not decision:
            lines += [f"Прогноз {name} не построен: {result.get('reason')}", ""]
            continue
        lines += [f"## Прогноз {name}", "",
                  f"Выбран **{decision['selected']}**. {decision['reason']}.", "",
                  "| Метод | MAE на общем validation | MAE на тесте | Анализов с прогнозом |",
                  "|---|---:|---:|---:|"]
        for method, values in result["models"].items():
            t = values["test"]
            lines.append(f"| {method} | {values['validation_common_mae']:.3f} | "
                         f"{t.get('mae', 0):.3f} | {t['predicted']}/{t['n']} |")
        lines += ["", "Простой прогноз здесь — последнее доступное лабораторное значение того же "
                  "показателя, а не показание анализатора серы: сравнение с посторонней величиной "
                  "создало бы заведомо слабого соперника и завысило бы выигрыш модели.", ""]
    return lines


def make_report(out, demos):
    lines = ["# Первый рабочий проход", "", "Прогноз на реальных данных. Оптимизация смешения — явно модельный сценарий.", ""]
    if (out / "metrics.json").exists():
        summary = json.loads((out / "metrics.json").read_text())
        lines += [f"Выбор только по validation: **{summary['selected']}**. Тест — 2026 год.", "",
                  "| Метод | Анализов с прогнозом | MAE, мг/кг | MAE на общих анализах | Найдено превышений точечным прогнозом | Покрытие диапазона |",
                  "|---|---:|---:|---:|---:|---:|"]
        for name, result in summary["models"].items():
            m = result["test"]
            common_mae = result["test_common"].get("mae", float("nan"))
            recall = f"{m['recall']:.1%}" if m.get("recall") is not None else "—"
            lines.append(f"| {name} | {m['predicted']}/{m['n']} | {m.get('mae', 0):.2f} | {common_mae:.2f} | {recall} | {m.get('interval_coverage', 0):.1%} |")
        lines += ["", "MAE — средняя абсолютная ошибка. Последнее измерение может отсутствовать: сравнивайте также доступность. "
                  "Подробные пропуски превышений и ложные тревоги — в metrics.json. Предел 10 здесь — ориентир риска после гидроочистки, не заключение о товарном ДТ.",
                  "", "Заявленная цель покрытия диапазона — 90%. Сравните с фактическим покрытием выше. "
                  "Маленькая средняя ошибка при низкой доле найденных превышений не означает хороший контроль риска. "
                  "Верхняя граница повышает обнаружение, но может давать много ложных тревог. Эти модели еще требуют доработки.",
                  "", "Результаты воспроизведения всех тестовых моментов с модельным смешением: " + str(summary["replay"]["statuses"]), ""]
        lines += selection_section(summary)
        lines += ["## Допущения", "", *[f"- {a}" for a in summary["assumptions"]], ""]
    if (out / "risk_metrics.json").exists():
        risk = json.loads((out / "risk_metrics.json").read_text())
        lines += ["## Обнаружение превышений", "",
                  f"Выбран по validation: **{risk['selected']}**, резерв: **{risk['fallback']}**. "
                  f"Экспериментальный бюджет ложных тревог: {risk['false_alarm_budget']:.0%}. "
                  f"Сравнение на {risk['common_test_n']} общих тестовых анализах:", "",
                  "| Метод | Найдено превышений | Ложных тревог среди проб без превышения | Верных тревог среди всех тревог |",
                  "|---|---:|---:|---:|"]
        def percent(value):
            return f"{value:.1%}" if value is not None else "—"
        for name, result in risk["models"].items():
            m = result["test_common"]
            lines.append(f"| {name} | {m['tp']}/{m['tp'] + m['fn']} ({percent(m['recall'])}) | "
                         f"{m['fp']}/{m['fp'] + m['tn']} ({percent(m['false_alarm_rate'])}) | {percent(m['precision'])} |")
        lines += ["", *[f"- {note}" for note in risk["limitations"]], ""]
    lines += ["## Сценарии агентов", "", "| Сценарий | Решение | Объяснение |", "|---|---|---|"]
    for name, d in demos.items():
        lines.append(f"| {name} | {d['status']} | {d['reason']} |")
    lines += ["", "## Проверяемый конфликт", ""]
    conflict = demos["conflict_synthetic"]
    c = conflict["chosen"]
    if c:
        lines += [f"При верхней оценке серы 14 мг/кг исходные 100 т/ч не проходят ограничения. "
                  f"После запрета оборудования выбран расход {c['throughput_tph']:g} т/ч с массовой долей резерва {c['reserve_fraction']:.0%}. "
                  f"Верхняя оценка смеси {c['quality']['sulfur_upper']:.2f} мг/кг; "
                  f"насос {c['throughput_tph'] * c['reserve_fraction']:g} т/ч при пределе 30 т/ч.", ""]
    lines += ["Все численные условия этого конфликта заданы в config/blending-demo.json. "
              "audit.jsonl содержит входы, оценки, все кандидаты и причины запрета. Фактическое будущее в журнал агентов не передается.", "",
              "Полный промышленный советчик пока не готов: нужны подтвержденные управляющие теги, "
              "остальные спецификации качества и проверка модели последствий действий.", ""]
    (out / "report.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Локальный исследовательский прототип Нефтекод")
    parser.add_argument("command", choices=["train", "demo", "advise", "vak", "episodes", "benchmark", "screen", "scenes", "serve"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    parser.add_argument("--config", type=Path, default=Path("config/experiment.json"))
    parser.add_argument("--at", help="Местное время решения для advise, например 2026-01-05T08:00:00")
    parser.add_argument("--scenario", type=Path, help="Файл сценария для screen")
    parser.add_argument("--decision", type=Path, help="Сохранённое решение для повторного просмотра")
    parser.add_argument("--port", type=int, default=8765, help="Порт демонстрационного сервера")
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "train":
            cfg = json.loads(args.config.read_text())
            train(root, out, cfg)
        elif args.command == "serve":
            serve_demo(root, args.port)
        elif args.command == "scenes":
            scenario_path = args.scenario or (root / "config/scenarios/baseline.json")
            demo = Demo.from_path(scenario_path, budget=400)
            folder = out / "scenes"
            folder.mkdir(parents=True, exist_ok=True)
            index = []
            for number, scene in enumerate(demo_scenes(scenario_path), start=1):
                result = demo.run(scene["changes"], scene["fault"])
                page = folder / f"{number:02d}-{scene['name'].replace(' ', '_')}.html"
                write_screen(page, result["screen"])
                status = "отклонено" if result["rejected"] else result["decision"]["status"]
                index.append({"scene": scene["name"], "expected": scene["expect"],
                              "status": status, "injected_fault": scene["fault"],
                              "page": str(page.relative_to(out))})
                print(f"  {scene['name']:48s} {status}")
            write_json(out / "scenes.json", {
                "scenario": str(scenario_path), "scenes": index,
                "note": "Каждая сцена получена пересчётом через тот же загрузчик и то же ядро. "
                        "Инъекции отказов помечены как модельные."})
            print(f"Журнал: {out / 'scenes.json'}")
        elif args.command == "screen":
            from .explain import explain
            from .inventory import initial_state
            from .orchestrator import Orchestrator
            from .scenario import load_scenario
            target = out / "screen.html"
            try:
                scenario_path = args.scenario or (root / "config/scenarios/sour_crude.json")
                scenario = load_scenario(scenario_path)
                if args.decision:
                    # Reviewing a stored decision: nothing is recomputed.
                    decision = json.loads(args.decision.read_text())
                else:
                    decision = Orchestrator(scenario).decide(
                        budget=400, raw_scenario=json.loads(Path(scenario_path).read_text()))
                    write_json(out / f"decision-{scenario.scenario_id}.json", decision)
                payload = Screen(
                    decision, explain(decision, scenario),
                    inventories={k: v.inventory_t for k, v in initial_state(scenario).items()},
                ).payload()
            except (ValueError, OSError) as exc:
                payload = error_payload(str(exc))
            write_screen(target, payload)
            print(f"Экран оператора: {target}")
        elif args.command == "benchmark":
            from .scenario import load_scenario
            items = []
            for path in sorted((root / "config/scenarios").glob("*.json")):
                items.append((load_scenario(path), json.loads(path.read_text())))
            report = compare_strategies(items)
            write_json(out / "benchmark.json", report)
            for record in report["scenarios"]:
                print(f"=== {record['scenario_id']}")
                for name, result in record["strategies"].items():
                    if result.get("refused"):
                        print(f"  {name:30s} отказ")
                    else:
                        print(f"  {name:30s} допустим={result['feasible']} "
                              f"нарушений={result['violations']} выпуск={result['production_t']:.0f} т")
            print(f"Выигрышей: {len(report['wins'])}, проигрышей: {len(report['losses'])}")
            print(f"Журнал: {out / 'benchmark.json'}")
        elif args.command == "episodes":
            cfg = json.loads(args.config.read_text())
            _, _, online = load_sources(root / "task")
            series = _as_series(online)
            episodes = classify_episodes(excursion_episodes(series, cfg["sulfur_limit"]),
                                         cfg["sustained_exceedance_hours"])
            trend = margin_series(online, cfg["sulfur_limit"], cfg["batch_window_hours"],
                                  cfg["margin_trend_window_hours"], cfg["response_lag_hours"])
            alarms = trend.index[trend.alarm]
            report = {
                "profile": violation_profile(series, cfg["sulfur_limit"],
                                             sustained_hours=cfg["sustained_exceedance_hours"]),
                "sampling_step_hours": sampling_step_hours(series),
                "episodes": {
                    "total": int(len(episodes)),
                    "sustained": int((episodes.kind == "sustained").sum()),
                    "median_duration_hours": float(episodes.duration_hours.median()),
                    "total_hours": float(episodes.duration_hours.sum()),
                    "hours_in_flickers": float(episodes.loc[episodes.kind == "flicker", "duration_hours"].sum()),
                    "hours_in_sustained": float(episodes.loc[episodes.kind == "sustained", "duration_hours"].sum()),
                },
                "alarms": {k: v for k, v in lead_times(
                    online, alarms, cfg["sulfur_limit"], cfg["sustained_exceedance_hours"],
                    cfg["lead_time_matching_window_hours"], total_readings=len(series),
                    rearm_hours=cfg["alarm_rearm_hours"]).items() if k != "per_episode"},
                "limitations": [
                    "Это описательная статистика ряда ПАК, не доля брака и не доказанные отказы прибора.",
                    "Короткое превышение показания не является доказанной неисправностью анализатора.",
                    "Упреждение читается только вместе с нагрузкой тревог и числом поздних срабатываний.",
                ],
            }
            write_json(out / "episodes.json", report)
            a = report["alarms"]
            print(f"Эпизодов {report['episodes']['total']}, устойчивых {report['episodes']['sustained']}, "
                  f"медиана {report['episodes']['median_duration_hours']:.2f} ч, всего "
                  f"{report['episodes']['total_hours']:.1f} ч")
            print(f"Тревоги: рано {a['early']}, поздно {a['late']}, пропущено {a['missed']}, "
                  f"неизвестно {a['unknown']}; событий {a['alarm_events']} при {a['alarm_readings']} отсчётах")
            print(f"Журнал: {out / 'episodes.json'}")
        elif args.command == "vak":
            signals, _, _ = load_sources(root / "task")
            report = check_all(root / "task", signals)
            write_json(out / "vak_check.json", report)
            print(f"Разобрано формул: {len(report['formulas'])}; итог проверки: {report['summary']}")
            print(f"Прошли порог корреляции: {report['passed_correlation_threshold'] or 'ни одной'}")
            print(f"Используется как оценка качества: {report['used_as_quality_estimate'] or 'ни одна'}")
            print(f"Журнал: {out / 'vak_check.json'}")
        elif args.command == "advise":
            if not args.at:
                parser.error("Для advise нужен --at с местным временем решения")
            with (out / "model.pkl").open("rb") as stream:
                bundle = pickle.load(stream)
            when = validate_origin(args.at, bundle)
            signals, lab, online = load_sources(root / "task")
            scenario_path = args.scenario or (root / "config/scenarios/baseline.json")
            advisor = LiveAdvisor(signals, lab, online, bundle,
                                  json.loads(Path(scenario_path).read_text()))
            result = advisor.advise(when)
            stamp = when.strftime("%Y%m%d-%H%M%S")
            path = out / f"decision-{stamp}.json"
            write_json(path, result)
            write_screen(out / f"screen-{stamp}.html", advisor.screen(result))
            forecast = result["forecast"]
            print(f"Прогноз {forecast['model']}: "
                  + ("недоступен" if not forecast["available"] else
                     f"{forecast['value']:.2f} мг/кг, верхняя граница {forecast['upper']:.2f}"))
            print(f"Источники: {result['trust']['primary'] or 'нет пригодного'}")
            if result["decision"] is None:
                print(f"Решение не выдано: {result.get('error')}")
            else:
                print(f"{result['decision']['status']}: {result['decision']['reason']}")
            print(f"Журнал: {path}\nЭкран: {out / f'screen-{stamp}.html'}")
        else:
            make_demo(root, out)
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"Ошибка: {exc}\n")


if __name__ == "__main__":
    main()
