from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


SCHEMA = "run-meta/1"
UNKNOWN = None


def _digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def build_run_meta(provenance, canonical: dict, payload: dict, snapshots: list, raw_scenario: dict,
                   key_of=lambda item: None) -> dict:
    decision = payload.get("decision") or {}
    agentic = decision.get("agentic") or {}
    snapshot_key = payload.get("snapshot")
    snapshot = next((item for item in snapshots if key_of(item) == snapshot_key), None)
    binding = payload.get("binding") or {}
    response = binding.get("response_model") or {}
    model = provenance["model"]
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
        "code": provenance["code"],
        "model": model,
        "provider": {"provider": agentic.get("provider"), "model": agentic.get("model"),
                     "deterministic_policy": agentic.get("deterministic_policy"),
                     "mode": agentic.get("mode"), "outcome": agentic.get("outcome")},
        "horizon_hours": (raw_scenario.get("horizon") or {}).get("hours"),
        "severity_profile": inputs["severity_profile"],
        "unknown_note": "Отсутствующие сведения помечены null и не заменяются значениями по умолчанию.",
    }
