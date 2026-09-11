"""Exceedance detection; scores are not asserted to be calibrated probabilities."""
import numpy as np
from catboost import CatBoostClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import split_periods


def select_threshold(labels, scores, false_alarm_budget):
    """Lowest threshold satisfying empirical FPR budget. Ties are never split."""
    if not 0 <= false_alarm_budget < 1:
        raise ValueError("Бюджет ложных тревог должен быть в диапазоне [0, 1)")
    labels, scores = np.asarray(labels, bool), np.asarray(scores, float)
    negative = scores[~labels & np.isfinite(scores)]
    if not len(negative):
        raise ValueError("Нет проб без превышения для выбора порога")
    allowed = int(np.floor(false_alarm_budget * len(negative)))
    ordered = np.sort(negative)[::-1]
    # Strictly above this negative score: tie groups cannot breach the budget.
    return float(np.nextafter(ordered[allowed], np.inf))


def detection_metrics(labels, scores, threshold):
    labels, scores = np.asarray(labels, bool), np.asarray(scores, float)
    valid = np.isfinite(scores)
    y, p = labels[valid], scores[valid]
    alarm = p >= threshold
    tp = int((alarm & y).sum())
    fp = int((alarm & ~y).sum())
    fn = int((~alarm & y).sum())
    tn = int((~alarm & ~y).sum())
    has_both = bool(y.any() and (~y).any())
    return {
        "n": len(labels), "scored": int(valid.sum()), "unavailable": int((~valid).sum()),
        "exceedances_without_score": int(labels[~valid].sum()),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_alarm_rate": fp / (fp + tn) if fp + tn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "roc_auc": float(roc_auc_score(y, p)) if has_both else None,
        "average_precision": float(average_precision_score(y, p)) if has_both else None,
    }


def score_candidate(bundle, name, x):
    if name == "pak_threshold":
        return x["pak.sulfur"].to_numpy()
    if name == "lab_threshold":
        return x["lab.sulfur"].to_numpy()
    return bundle["models"][name].predict_proba(x[bundle["columns"][name]])[:, 1]


def run_risk_experiment(x, meta, cfg):
    masks = split_periods(meta, cfg)
    train, val, cal, test = [masks[k] for k in ("train", "validation", "calibration", "test")]
    labels = meta.actual_sulfur.to_numpy() > cfg["sulfur_limit"]
    if not (labels[train].any() and (~labels[train]).any()):
        raise ValueError("Для обучения нужны оба класса")
    columns = x.columns[x.loc[train].nunique() > 1].tolist()
    candidates = ["pak_threshold", "lab_threshold", "logistic", "risk_catboost", "risk_catboost_no_pak"]
    bundle = {"models": {}, "columns": {}, "thresholds": {}, "config": cfg}
    scores = {}
    for name in candidates:
        if name not in ("pak_threshold", "lab_threshold"):
            cols = [c for c in columns if not c.startswith("pak.")] if name.endswith("no_pak") else columns
            if name == "logistic":
                model = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                                      LogisticRegression(C=.03, class_weight="balanced", max_iter=2000, random_state=cfg["seed"]))
            else:
                model = CatBoostClassifier(iterations=350, depth=4, learning_rate=.03, loss_function="Logloss",
                                           auto_class_weights="Balanced", random_seed=cfg["seed"],
                                           thread_count=2, verbose=False, allow_writing_files=False)
            model.fit(x.loc[train, cols], labels[train])
            bundle["models"][name], bundle["columns"][name] = model, cols
        scores[name] = score_candidate(bundle, name, x)

    common_val = val & np.logical_and.reduce([np.isfinite(s) for s in scores.values()])
    common_test = test & np.logical_and.reduce([np.isfinite(s) for s in scores.values()])
    if common_val.sum() < 30 or len(np.unique(labels[common_val])) != 2:
        raise ValueError("Недостаточно общих validation-проб обоих классов")
    validation, results = {}, {}
    for name, score in scores.items():
        threshold = select_threshold(labels[common_val], score[common_val], cfg["risk_false_alarm_budget"])
        validation[name] = detection_metrics(labels[common_val], score[common_val], threshold)

    def rank(name):
        m = validation[name]
        return (-m["recall"], m["false_alarm_rate"], -m["average_precision"], name)

    selected = min(candidates, key=rank)
    fallback = min(["lab_threshold", "risk_catboost_no_pak"], key=rank)
    bundle.update(selected=selected, fallback=fallback)
    for name, score in scores.items():
        # New threshold uses calibration-period negatives; the test cannot move it.
        threshold = select_threshold(labels[cal], score[cal], cfg["risk_false_alarm_budget"])
        bundle["thresholds"][name] = threshold
        results[name] = {
            "validation_common": validation[name], "threshold": threshold,
            "calibration": detection_metrics(labels[cal], score[cal], threshold),
            "test": detection_metrics(labels[test], score[test], threshold),
            "test_common": detection_metrics(labels[common_test], score[common_test], threshold),
        }
    output = meta.loc[test, ["decision_time", "actual_sulfur"]].reset_index(drop=True)
    for name, score in scores.items():
        output[name] = score[test]
    for prefix, name in [("risk_", selected), ("risk_fallback_", fallback)]:
        output[prefix + "score"] = scores[name][test]
        output[prefix + "threshold"] = bundle["thresholds"][name]
        output[prefix + "model"] = name

    summary = {
        "selected": selected, "fallback": fallback,
        "selection": "Максимум обнаруженных превышений на общем validation при заданном бюджете ложных тревог; затем меньшая доля ложных тревог и больше average precision.",
        "threshold_policy": "Порог после выбора метода заново установлен по пробам без превышения на calibration; на тесте заморожен.",
        "false_alarm_budget": cfg["risk_false_alarm_budget"],
        "common_validation_n": int(common_val.sum()), "common_test_n": int(common_test.sum()),
        "models": results,
        "fixed_pak_10": detection_metrics(labels[test], scores["pak_threshold"][test], np.nextafter(cfg["sulfur_limit"], np.inf)),
        "limitations": [
            "Бюджет выполняется на calibration, его соблюдение на другом периоде не гарантировано.",
            "Показатель классификатора не является откалиброванной вероятностью; выводится как score.",
            "Проверка идет за 2 часа до лабораторных проб. Это не оценка задержки обнаружения всех непрерывных событий.",
            "2026 уже анализировался в предыдущем эксперименте; это фиксированный сравнительный период, а не новый слепой тест.",
            "Низкая оценка риска не отменяет проверки верхней границы серы и других ограничений.",
        ],
    }
    return bundle, summary, output
