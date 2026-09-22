from copy import deepcopy
import hashlib
import pickle
from pathlib import Path
from threading import Lock

from neftecode.application.history.catalog import snapshot_catalog, snapshot_id
from neftecode.application.history.prepare import HistoryError, local_moment
import pandas as pd
from neftecode.infrastructure.data.data import load_sources
from neftecode.infrastructure.live.advisor import interval_coverage
from neftecode.infrastructure.live.snapshots import build_snapshot, load_snapshots
from .bundle import history_bundle
from .exclusions import ExclusionRegistry
from .overview import bounded_response, observations


class LocalHistorySource:
    def __init__(self, root: Path, out: Path):
        self.root, self.out = Path(root), Path(out)
        self.snapshots = load_snapshots(self.out)
        self.registry = ExclusionRegistry(self.root / "research/data/excluded-periods.json")
        self._loaded = None
        self._provenance = None
        self._coverage = {}
        self._lock = Lock()

    def get_snapshot(self, key: str) -> dict:
        for item in self.snapshots:
            if snapshot_id(item) == key:
                return deepcopy(item)
        raise HistoryError("snapshot_not_found", f"Срез «{key}» отсутствует в поставке")

    def capability(self) -> dict:
        task = self.root / "task"
        files = [task / "data/avt_tags.csv", task / "data/242000_tags.csv", self.out / "model.pkl"]
        available = all(path.is_file() for path in files) and bool(list(task.glob("ЛИМС*.xlsx"))) \
            and bool(list(task.glob("Выгрузка*.xlsx")))
        return {"available": available, "reason": None if available else "Полный комплект task/ и модель не поставлены"}

    def _load(self):
        with self._lock:
            if self._loaded is None:
                if not self.capability()["available"]:
                    raise HistoryError("measurements_unavailable", self.capability()["reason"])
                try:
                    model_bytes = (self.out / "model.pkl").read_bytes()
                    bundle, migrations = history_bundle(self.root, model_bytes)
                    signals, lab, online = load_sources(self.root / "task", bundle["config"]["train_end"])
                    if signals.empty or lab.empty or online.empty:
                        raise ValueError("Источники истории пусты")
                    hashes = {}
                    for name, frame in (("telemetry", signals), ("lab", lab), ("pak", online)):
                        values = pd.util.hash_pandas_object(frame, index=True).values.tobytes()
                        hashes[name] = hashlib.sha256(values + str(list(frame.columns)).encode()).hexdigest()
                    self._provenance = {
                        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
                        "metadata_migrations": migrations,
                        "model_fingerprint": (bundle.get("manifest") or {}).get("fingerprint"),
                        "normalized_sources_sha256": hashes, "timezone": "source-local",
                        "lab_delay_hours": bundle["config"]["lab_delay_hours"],
                        "lab_availability": "sample_time + assumed delay; publication timestamps not supplied",
                        "registry": self.registry.provenance,
                    }
                    self._coverage = {name: interval_coverage(self.out, bundle, name)
                                      for name in bundle.get("radii", {})}
                    self._provenance["interval_coverage"] = deepcopy(self._coverage)
                    self._loaded = (signals, lab, online, bundle)
                except (OSError, ValueError, KeyError, StopIteration, EOFError, pickle.UnpicklingError) as exc:
                    raise HistoryError("history_unavailable", f"Данные истории не удалось прочитать: {exc}") from exc
            return self._loaded

    def provenance(self) -> dict:
        self._load()
        return deepcopy(self._provenance)

    def coverage(self) -> dict:
        signals, _, _, bundle = self._load()
        return {"start": signals.index.min().isoformat(), "end": signals.index.max().isoformat(),
                "model_valid_from": bundle["config"]["calibration_end"]}

    def _check_time(self, at: str):
        when = local_moment(at)
        coverage = self.coverage()
        if when < local_moment(coverage["start"]) or when > local_moment(coverage["end"]):
            raise HistoryError("outside_coverage", "Момент вне поставленного периода телеметрии")
        valid = local_moment(coverage["model_valid_from"] + "T00:00:00"
                             if len(coverage["model_valid_from"]) == 10 else coverage["model_valid_from"])
        if when < valid:
            raise HistoryError("model_not_available", "На этот момент модель и калибровка ещё не были доступны")
        return when

    def prepare_at(self, at: str) -> tuple[dict, dict]:
        when = self._check_time(at)
        signals, lab, online, bundle = self._load()
        try:
            snapshot = build_snapshot(signals, lab, online, bundle, when, coverage=self._coverage)
        except (ValueError, KeyError, TypeError) as exc:
            raise HistoryError("point_unavailable", f"Состояние на выбранный момент не подготовлено: {exc}") from exc
        excluded = self.registry.between(at, at)
        return snapshot, {"coverage": self.coverage(), "exclusions": excluded,
                          "trust_usable": snapshot["trust"].get("usable"),
                          "preparation": "one state, two frozen forecast branches; no decision or LLM"}

    def catalog(self, offset: int = 0, limit: int = 50) -> dict:
        result = snapshot_catalog(self.snapshots, offset, limit)
        result["arbitrary"] = self.capability()
        if result["arbitrary"]["available"]:
            try:
                result["coverage"] = self.coverage()
                result["provenance"] = self.provenance()
            except HistoryError as exc:
                result["arbitrary"] = {"available": False, "reason": str(exc)}
        return bounded_response(result)

    def overview(self, start: str, end: str, points: int = 24,
                 exclusion_offset: int = 0, exclusion_limit: int = 50) -> dict:
        first, last = self._check_time(start), self._check_time(end)
        signals, lab, online, bundle = self._load()
        rows = observations(signals, lab, online, bundle["config"], first.isoformat(), last.isoformat(), points)
        return bounded_response({"points": rows, "coverage": self.coverage(), "provenance": self.provenance(),
                                 "exclusions": self.registry.between(start, end, exclusion_offset, exclusion_limit),
                                 "note": "Редкая выборка наблюдений; между точками возможны пропуски. Прогноз, пригодность и решение не вычислялись."})
