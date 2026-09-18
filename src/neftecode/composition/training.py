"""Composition of data preparation, model experiments and persisted artifacts."""
import json
import pickle

from neftecode.composition.demo import make_demo
from neftecode.infrastructure.artifacts import fingerprint, write_atomic, write_json
from neftecode.infrastructure.config.trust_rules import write_source_rules
from neftecode.infrastructure.data.data import derive_source_rules, load_sources, make_dataset
from neftecode.infrastructure.data.quality import read_quality_series, report as quality_report
from neftecode.infrastructure.ml.forecast import run_experiment
from neftecode.infrastructure.ml.risk import run_risk_experiment
from neftecode.infrastructure.response.estimate import estimate_response

def train(root, out, cfg):
    manifest = fingerprint(root, cfg)
    print("Чтение телеметрии и независимых временных рядов ЛИМС/ПАК…", flush=True)
    signals, lab, online = load_sources(root / "task", cfg["train_end"])
    # Source-trust thresholds come from the training period, not from hand-set numbers.
    rules = derive_source_rules(signals, lab, online, cfg["train_end"], cfg)
    cfg = {**cfg, **rules}
    print("Пороги доверия к источникам по данным до " + cfg["train_end"] + ": "
          + ", ".join(f"{k}={rules[k]}" for k in rules if k != "source_rules"), flush=True)
    x, meta = make_dataset(signals, lab, online, cfg)
    print(f"{len(signals)} строк телеметрии, {len(meta)} независимых целевых анализов, {len(x.columns)} признаков", flush=True)
    print("Сравнение шести методов; production-выбор заморожен по rolling до 2026…", flush=True)
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
    summary["source_rules"] = {k: v for k, v in rules.items()}
    bundle["manifest"] = manifest
    # Отклик серы на T6 (C2): тот же ARX, что в исследовании, на сетке τ; живое решение берёт оценку до момента.
    print("Оценка отклика серы на температуру входа реактора по данным до train_end и по скользящим окнам…", flush=True)
    declared = json.loads((root / "config/response_model.json").read_text(encoding="utf-8"))
    response = estimate_response(signals, online, cfg["train_end"], declared, manifest["fingerprint"])
    write_json(out / "response_model.json", response)
    summary["response_model"] = {"primary_tau": response["tau"], "beta_mgkg_per_c": response["beta_mgkg_per_c"],
                                 "ci": response["ci"], "weak_strong": response["weak_strong"],
                                 "estimates": [{k: e[k] for k in ("tau", "beta_mgkg_per_c", "ci", "n_rows", "weak_strong")}
                                               for e in response["estimates"]]}
    for e in response["estimates"]:
        print(f"  τ={e['tau']}: β={e['beta_mgkg_per_c']} ДИ {e['ci']} weak/strong {e['weak_strong']} строк {e['n_rows']}", flush=True)
    write_atomic(out / "model.pkl", pickle.dumps(bundle))
    predictions.to_csv(out / "predictions.csv", index=False)
    write_json(out / "metrics.json", summary)
    write_json(out / "manifest.json", manifest)
    # Те же пороги для демо и сервисов без model.pkl в памяти (артефакт C1).
    write_source_rules(out, rules, cfg, manifest["fingerprint"])
    print(f"Основной прогноз: {summary['selected']}", flush=True)
    make_demo(root, out)
