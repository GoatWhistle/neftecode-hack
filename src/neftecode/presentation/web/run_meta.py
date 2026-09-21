from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess

SCHEMA = "run-meta/1"
UNKNOWN = None


def _digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return UNKNOWN


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    return done.stdout.strip() if done.returncode == 0 else UNKNOWN


@lru_cache(maxsize=4)
def code_version(root: str) -> dict:
    """Версия кода: коммит и признак изменённого дерева (только исходники и конфигурация, не документы)."""
    path = Path(root)
    commit = _git(path, "rev-parse", "HEAD")
    changed = _git(path, "status", "--porcelain", "--", "src/neftecode", "config", "pyproject.toml")
    return {"commit": commit, "dirty": None if changed is None else bool(changed),
            "note": None if commit else "git недоступен: версия кода неизвестна"}


@lru_cache(maxsize=4)
def model_version(root: str) -> dict:
    path = Path(root)
    manifest = path / "artifacts" / "manifest.json"
    training = None
    try:
        training = json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint")
    except (OSError, ValueError):
        pass
    return {"response_model_sha256": _file_digest(path / "artifacts" / "response_model.json"),
            "training_fingerprint": training}


def build_run_meta(root: Path, canonical: dict, payload: dict, snapshots: list, raw_scenario: dict,
                   key_of=lambda item: None) -> dict:
    decision = payload.get("decision") or {}
    agentic = decision.get("agentic") or {}
    snapshot_key = payload.get("snapshot")
    snapshot = next((item for item in snapshots if key_of(item) == snapshot_key), None)
    binding = payload.get("binding") or {}
    response = binding.get("response_model") or {}
    model = model_version(str(root))
    inputs = {
        "conditions": canonical, "scenario_sha256": _digest(raw_scenario),
        "snapshot": snapshot_key, "snapshot_sha256": _digest(snapshot) if snapshot is not None else UNKNOWN,
        "model": model, "response_binding": {k: response.get(k) for k in
                                             ("provenance", "beta_mgkg_per_c", "reference_temp_c",
                                              "reference_space_velocity_m3h")},
        "severity_profile": ((decision.get("severity") or {}).get("selected") or
                             (decision.get("severity") or {}).get("current") or {}).get("profile_id"),
    }
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conditions_requested": canonical,
        "conditions_applied": {"changes": payload.get("applied") or [], "snapshot": snapshot_key,
                               "fault": canonical.get("fault"), "injection": payload.get("injection"),
                               "decision_time": payload.get("decision_time")},
        "input_fingerprint": _digest(inputs),
        "input_parts": {k: v for k, v in inputs.items() if k in ("scenario_sha256", "snapshot_sha256", "model")},
        "code": code_version(str(root)),
        "model": model,
        "provider": {"provider": agentic.get("provider"), "model": agentic.get("model"),
                     "deterministic_policy": agentic.get("deterministic_policy"),
                     "mode": agentic.get("mode"), "outcome": agentic.get("outcome")},
        "horizon_hours": ((decision.get("tradeoff") or {}).get("horizon_hours")),
        "severity_profile": inputs["severity_profile"],
        "unknown_note": "Отсутствующие сведения помечены null и не заменяются значениями по умолчанию.",
    }
