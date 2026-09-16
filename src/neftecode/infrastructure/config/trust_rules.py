"""Единые пороги доверия к источникам для демо, HTTP-сервисов и live-советчика.

Пороги выводятся при обучении (`derive_source_rules`) и лежат в `model.pkl`; чтобы демо и
сервисы без модели в памяти пользовались теми же числами, обучение пишет их ещё и в
`artifacts/source_rules.json` (артефакт C1). Здесь этот артефакт накладывается поверх запасных
значений из `config/experiment.json`, и вызывающий код всегда знает, откуда пороги пришли.
"""
import json
from pathlib import Path

from neftecode.infrastructure.artifacts import write_json

SCHEMA_VERSION = "v1"
ARTIFACT_NAME = "source_rules.json"
ORIGIN_DERIVED = "derived:artifacts/source_rules.json"
ORIGIN_FALLBACK = "fallback:config/experiment.json"

#: Ключи порогов, которые `derive_source_rules` возвращает числами.
RULE_KEYS = ("lab_max_age_hours", "pak_max_age_minutes", "pak_period_minutes", "pak_frozen_readings",
             "pak_conflict_mgkg", "telemetry_max_missing_fraction")


def source_rules_artifact(rules: dict, cfg: dict, model_fingerprint: str | None) -> dict:
    """Содержимое C1 из результата `derive_source_rules` и конфигурации обучения."""
    missing = [key for key in RULE_KEYS if key not in rules]
    if missing:
        raise ValueError("Нет порогов для source_rules.json: " + ", ".join(missing))
    return {"schema_version": SCHEMA_VERSION,
            "train_end": cfg.get("train_end"),
            "method": cfg.get("source_rule_method"),
            "rules": {key: rules[key] for key in RULE_KEYS},
            "source_rules": rules.get("source_rules"),
            "model_fingerprint": model_fingerprint}


def write_source_rules(out: Path, rules: dict, cfg: dict, model_fingerprint: str | None) -> Path:
    """Записать C1 рядом с metrics.json. В config/ ничего не пишется."""
    path = Path(out) / ARTIFACT_NAME
    write_json(path, source_rules_artifact(rules, cfg, model_fingerprint))
    return path


def _read_artifact(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Артефакт порогов доверия {path} не читается: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Артефакт порогов доверия {path}: ожидается schema_version={SCHEMA_VERSION!r}")
    rules = value.get("rules")
    if not isinstance(rules, dict):
        raise ValueError(f"Артефакт порогов доверия {path}: нет объекта rules")
    missing = [key for key in RULE_KEYS if key not in rules]
    if missing:
        raise ValueError(f"Артефакт порогов доверия {path}: нет ключей " + ", ".join(missing))
    for key in RULE_KEYS:
        if isinstance(rules[key], bool) or not isinstance(rules[key], (int, float)):
            raise ValueError(f"Артефакт порогов доверия {path}: {key} должен быть числом")
    return value


def load_trust_rules(root: Path, out: Path) -> tuple[dict, str]:
    """Конфиг для DataTrustAgent/frozen_rule и строка происхождения порогов.

    Основа — `config/experiment.json`; если в `out` лежит валидный `source_rules.json`, его
    `rules` перекрывают запасные значения. Битый артефакт — ошибка, а не тихий откат.
    """
    root, out = Path(root), Path(out)
    cfg = json.loads((root / "config" / "experiment.json").read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("config/experiment.json должен быть JSON-объектом")
    artifact = out / ARTIFACT_NAME
    if not artifact.exists():
        return cfg, ORIGIN_FALLBACK
    value = _read_artifact(artifact)
    return {**cfg, **value["rules"], "source_rules": value.get("source_rules")}, ORIGIN_DERIVED
