import json

from neftecode.evaluation.benchmark import compare as compare_strategies
from neftecode.evaluation.expert_grid import ExpertGrid, totals as grid_totals
from neftecode.evaluation.episodes import (
    _as_series, classify_episodes, excursion_episodes, lead_times, margin_series,
    sampling_step_hours, violation_profile,
)
from neftecode.infrastructure.live.tank_check import tank_level_check
from neftecode.evaluation.vak import check_all
from neftecode.infrastructure.artifacts import load_model_bundle, write_json
from neftecode.infrastructure.config.avt_tags import load_avt_tags
from neftecode.composition.decision import make_interactive_demo
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.config.scenario import load_scenario, parse_scenario
from neftecode.infrastructure.data.data import load_sources
from neftecode.infrastructure.data.vak_workbooks import load_vak_inputs, read_avt_points

def benchmark(args, parser, root, out):
    items = []
    for path in sorted((root / "config/scenarios").glob("*.json")):
        items.append((load_scenario(path), json.loads(path.read_text(encoding="utf-8"))))
    report = compare_strategies(items, scenario_parser=parse_scenario)
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

def tank_check(args, parser, root, out):
    cfg = load_model_bundle(out)["config"]
    _, lab, online = load_sources(root / "task", cfg["train_end"])
    report = tank_level_check(lab, online, cfg)
    write_json(out / "tank_level_check.json", report)
    for name, row in report["summary"].items():
        print(f"  {name:10s} n={row['n']:4d} MAE={row['mae']}  bias={row['bias']}  r={row['corr']}")
    print(f"Журнал: {out / 'tank_level_check.json'}")

def episodes(args, parser, root, out):
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    _, _, online = load_sources(root / "task", cfg.get("train_end"))
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

def vak(args, parser, root, out):
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    signals, _, _ = load_sources(root / "task", cfg.get("train_end"))
    formula_rows, lab_series = load_vak_inputs(root / "task")
    avt_lab = read_avt_points(next((root / "task").glob("ЛИМС*.xlsx")))
    report = check_all(formula_rows, lab_series, signals,
                       tag_map=load_avt_tags(root / "config/avt_tags.json"), avt_lab=avt_lab)
    write_json(out / "vak_check.json", report)
    print(f"Разобрано формул: {len(report['formulas'])}; итог проверки: {report['summary']}")
    print(f"Прошли порог корреляции: {report['passed_correlation_threshold'] or 'ни одной'}")
    print(f"Используется как оценка качества: {report['used_as_quality_estimate'] or 'ни одна'}")
    print(f"Журнал: {out / 'vak_check.json'}")

def expert_grid(args, parser, root, out):
    trust_cfg, trust_origin = load_trust_rules(root, out)
    per_scenario = []
    for path in sorted((root / "config/scenarios").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        demo = make_interactive_demo(raw, 200, trust_cfg, trust_origin)
        record = ExpertGrid(demo.run, raw, path.stem).run(progress=lambda line: print(line, flush=True))
        for row in record["rows"]:
            row["scenario_id"] = path.stem
        per_scenario.append(record)
        print(f"=== {path.stem}: {record['combinations']} комбинаций, трейсбеков "
              f"{len(record['tracebacks'])}, худшее время {record['seconds']['max']} с")
        for name, count in record["statuses"].items():
            print(f"  {name:22s} {count}")
    report = {"totals": grid_totals(per_scenario), "scenarios": per_scenario}
    write_json(out / "expert_grid.json", report)
    print(report["totals"]["criterion"])
    print(f"Журнал: {out / 'expert_grid.json'}")
