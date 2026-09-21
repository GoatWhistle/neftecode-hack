import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from neftecode.application.services.trust import DataTrustAgent
from neftecode.bootstrap import run_demo_decision
from neftecode.infrastructure.config.trust_rules import load_trust_rules
from neftecode.infrastructure.live.snapshots import bind_snapshot, load_snapshots, write_snapshot
from neftecode.infrastructure.scenarios import FileScenarioRepository, FileSnapshotRepository
from neftecode.application.conditions import apply_source_failure
from neftecode.presentation.demo import Demo, DemoError, scenes, snapshot_key, state_origin_label
from neftecode.presentation.web.server import DemoService

ROOT = Path(".")
BASELINE = json.loads((ROOT / "config/scenarios/baseline.json").read_text(encoding="utf-8"))


def real_state(decision_time="2026-01-05T08:00:00", hourly=5.0, t6=367.8):
    when = pd.Timestamp(decision_time)
    return {"decision_time": decision_time, "origin": "real_measurements_at_decision_time",
            "lab_value": 6.8, "lab_age_hours": 14.0, "lab_usable": True,
            "pak_value": 5.88, "pak_age_minutes": 0.0, "pak_usable": True, "pak_frozen": False,
            "pak_conflict": False, "telemetry_missing_fraction": 0.0,
            "pak_last_trusted_value": 5.88, "pak_last_trusted_time": decision_time,
            "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
            "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(), hourly, 6]
                                   for h in range(72)],
            "lab_recent": [],
            "measurements": {"ht.T6": None if t6 is None else {"value": t6, "time": decision_time, "age_min": 0.0},
                             "ht.F9": {"value": 206.1, "time": decision_time, "age_min": 0.0},
                             "ht.F26": {"value": 244.1, "time": decision_time, "age_min": 0.0}}}


def snapshot(label="норма", fingerprint="fp", synthetic=()):
    state = real_state(t6=None if "ht.T6" in synthetic else 367.8)
    edits = [f"{tag}: затёрто" for tag in synthetic]
    if edits:
        state["synthetic_edits"] = edits
    return {"schema_version": "v1", "at": "2026-01-05T08:00:00", "label": label, "why": "тест",
            "state": state, "trust": {"usable": True, "primary": "ЛИМС", "fallback": False},
            "forecast": {"model": "last_pak", "value": 5.88, "lower": 3.68, "upper": 9.13, "available": True,
                         "reason": "тест", "coverage_target": 0.9, "coverage_test_2026": 0.867},
            # I1 (task-pool.md, «Ключевые факты» #1, 05.01 + frozen_pak): резервный прогноз без ПАК,
            # который bind_snapshot обязан выбрать после инъекции отказа источника.
            "forecast_no_pak": {"model": "catboost_no_pak", "value": 7.511, "lower": 5.83, "upper": 10.292,
                                "available": True, "reason": "тест: резерв без ПАК"},
            "measured": state["measurements"], "synthetic_edits": edits,
            "model_fingerprint": fingerprint, "source_rules_fingerprint": None}


@pytest.fixture
def out(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"fingerprint": "fp"}), encoding="utf-8")
    return tmp_path


def trust_cfg():
    return load_trust_rules(ROOT, ROOT / "nowhere")[0]



def test_snapshots_are_loaded_in_time_order_and_checked_against_the_model(out):
    write_snapshot(out, snapshot())
    later = dict(snapshot(label="позже"), at="2026-02-01T00:00:00")
    write_snapshot(out, later)
    items = load_snapshots(out)
    assert [item["label"] for item in items] == ["норма", "позже"]
    assert load_snapshots(out / "empty") == []


def test_the_file_snapshot_repository_lists_and_loads_by_key(out):
    write_snapshot(out, snapshot())
    write_snapshot(out, dict(snapshot(label="позже"), at="2026-02-01T00:00:00"))
    repository = FileSnapshotRepository(out)
    assert repository.all() == load_snapshots(out)
    assert repository.get("20260201-000000")["label"] == "позже"
    with pytest.raises(KeyError, match="не найден"):
        repository.get("20990101-000000")


def test_a_snapshot_from_another_model_is_refused(out):
    write_snapshot(out, snapshot(fingerprint="other"))
    with pytest.raises(ValueError, match="другой модели"):
        load_snapshots(out)


def test_a_synthetic_edit_gets_its_own_file_name_and_label(out):
    path = write_snapshot(out, snapshot(synthetic=("ht.T6",)))
    assert path.name.endswith("-synthetic.json")
    item = load_snapshots(out)[0]
    assert snapshot_key(item).endswith("-synthetic")
    assert "затёрта искусственно" in state_origin_label(item["state"], item)



def test_the_demo_binds_the_snapshot_through_the_live_binder():
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 120, snapshots=[snapshot()])
    result = demo.run(snapshot="норма")
    assert result["state_origin"] == "real_measurements_at_decision_time"
    assert result["screen"]["state_origin"].startswith("реальный срез: норма · 05.01.2026 08:00")
    binding = result["binding"]
    assert binding["controls"]["ht_reactor_inlet_temp_c"]["current"]["source"] == "measured"
    assert binding["tank_inflow"]["source"] == "derived"
    sulfur = [c for c in result["decision"]["gate"]["checks"] if c["constraint_id"] == "quality.sulfur_mgkg"]
    assert sulfur[0]["observed"] == pytest.approx(0.9 * 5.0 + 0.1 * 2.0)


def test_without_a_snapshot_the_demo_stays_synthetic_and_says_so():
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 120)
    result = demo.run()
    assert result["snapshot"] is None and result["binding"] is None
    assert result["screen"]["state_origin"].startswith("синтетическое состояние")
    with pytest.raises(DemoError, match="не найден"):
        demo.run(snapshot="20990101-000000")


def test_an_injected_fault_on_a_real_snapshot_keeps_the_real_origin():
    state = apply_source_failure(real_state(), "frozen_pak")
    assert state["origin"] == "real_measurements_at_decision_time"
    assert state["injected_fault"] == "frozen_pak" and "инъекция" in state["injection"]
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 120, snapshots=[snapshot()])
    result = demo.run(fault="both_broken", snapshot="норма")
    assert result["decision"]["status"] == "refuse"
    assert "инъекция" in result["screen"]["state_origin"]


def test_scenes_use_real_moments_when_they_exist_and_keep_the_crude_scene_synthetic():
    items = [snapshot("норма"), dict(snapshot("отказ по данных"), at="2026-04-16T10:10:00")]
    plan = {scene["name"]: scene for scene in scenes(BASELINE, items)}
    assert plan["Нормальный режим"]["snapshot"] == "норма"
    assert plan["Ухудшение сырья"]["snapshot"] is None
    assert plan["Зависший поточный анализатор"]["fault"] == "frozen_pak", "среза нет — инъекция"
    without = {scene["name"]: scene for scene in scenes(BASELINE, [])}
    assert all(scene["snapshot"] is None for scene in without.values())



def test_the_server_offers_snapshots_first_and_the_synthetic_state_last(out):
    write_snapshot(out, snapshot())
    items = load_snapshots(out)
    service = DemoService(ROOT, lambda raw, budget: Demo(raw, run_demo_decision, trust_cfg(), budget,
                                                         snapshots=items),
                          FileScenarioRepository(ROOT / "config/scenarios"), 120, snapshots=items)
    keys = [key for key, _ in service.snapshot_options()]
    assert keys == ["20260105-080000", "synthetic"]
    titles = [item["title"] for item in service.options_payload("baseline")["snapshots"]]
    assert "синтетическое состояние сценария" in titles and "норма · 05.01.2026 08:00" in titles
    payload = service.decide({"scenario": ["baseline"]})
    assert payload["snapshot"] == "20260105-080000"
    assert service.decide({"scenario": ["baseline"], "snapshot": ["synthetic"]})["snapshot"] is None


# --- O1 (task-pool.md, «Ключевые факты» #8): источник каждого значения выбранного плана ---
#
# Критерий: срез 05.01 — АВТ «scenario», T6 «measured»; без F9 расход сырья ГО «scenario».
# С F9 расход — F9·1000/ρ, то есть пересчёт измерения: остаётся derived. Модель отклика — та же
# форма, что в test_measurement_binding (область применимости покрывает T6 = 367.8, F9 = 206.1).

O1_RESPONSE = {"schema_version": "v1", "tag": "ht.T6", "flow_tag": "ht.F9", "tau": "2026-01-01",
               "window_months": 12, "beta_mgkg_per_c": -0.4226, "ci": [-0.4767, -0.389], "envelope_dt_c": 2.0,
               "n_rows": 48938, "method": "тест", "drift": [], "flow_beta": None, "model_fingerprint": "x",
               "t6_range_c": [342.9, 386.1], "f9_range_tph": [150.3, 256.7], "weak_strong": [-0.217, -0.739]}


def plan_origin_on_2026_01_05(without_f9: bool) -> tuple[dict, dict]:
    item = snapshot()
    if without_f9:
        item["state"]["measurements"]["ht.F9"] = None
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 300, snapshots=[item], response_model=O1_RESPONSE)
    result = demo.run(snapshot="норма")
    return result["decision"], result["screen"]["explanation"]["plan_origin"]


@pytest.mark.parametrize("without_f9", [False, True])
def test_o1_plan_values_on_2026_01_05_carry_their_real_source(without_f9):
    decision, origin = plan_origin_on_2026_01_05(without_f9)
    assert decision["status"] == "hold" and decision["immediate_action"] is not None
    action = origin["immediate_action"]
    assert action == origin["steps"][0]
    for step in origin["steps"]:
        controls = step["controls"]
        assert controls["crude_feed_rate_tph"] == controls["avt_furnace_outlet_temp_c"] == "scenario"
        assert controls["ht_reactor_inlet_temp_c"] == "measured"
        assert controls["ht_feed_flow_m3h"] == ("scenario" if without_f9 else "derived")
        assert (step["recipe"], step["throughput_tph"], step["additive_dose"]) == ("scenario",) * 3
    assert decision["immediate_action"]["controls"]["ht_reactor_inlet_temp_c"] == pytest.approx(367.8)


# --- Z5 (task-pool.md, дефект #1): регрессия «прогноз не пересчитывается после инъекции отказа ПАК» ---
#
# Срез момента 2026-07-24T03:00 «риск по качеству при возврате нагрузки»
# (`config/snapshot_moments.json`) был собран, когда ПАК ещё был доверен: build_snapshot вызвал
# forecast_at(..., fallback=False) и получил last_pak_bc 14.933 / верхняя граница 20.942 —
# это и есть forecast, сохранённый в срезе. Реальных исходных данных (task/data/, artifacts/model.pkl)
# в рабочем дереве нет, поэтому вместо повторного запуска ML-модели используется фикстура состояния
# с теми же измеренными фактами, что задокументированы для этого момента (лаборатория, ПАК, T6/F9/F26)
# и теми же прогнозами, что зафиксированы в «Доказательной базе 21.09» task-pool.md.
#
# Если после сборки среза источник данных отказывает (условие `frozen_pak`), DataTrustAgent
# пересчитывает доверие правильно (ПАК становится unusable, fallback_mode=True), но
# `bind_snapshot` игнорирует это и продолжает использовать forecast, сохранённый в срезе на момент
# его сборки, вместо повторного forecast_at(..., fallback=True) → catboost_no_pak. Ожидаемо:
# catboost_no_pak 8.11 / 11.09, решение hold (task-pool.md, «Доказательная база 21.09»).

def real_2026_07_24_state(pak_frozen: bool = False, pak_usable: bool = True) -> dict:
    decision_time = "2026-07-24T03:00:00"
    when = pd.Timestamp(decision_time)

    def hourly_mean(h: int) -> float:
        # Последние часы перед срезом всё ещё несут след эпизода превышения (пик 14.811,
        # среднее 12.415 за 00:00-04:10, см. config/snapshot_moments.json); более ранние часы
        # окна обновления (tank_level_window_hours = 18.81 в baseline.json) — режим до эпизода.
        return 12.415 if h <= 3 else 6.5

    return {"decision_time": decision_time, "origin": "real_measurements_at_decision_time",
            "lab_value": 6.4, "lab_age_hours": 17.0, "lab_usable": True,
            "pak_value": 14.637, "pak_age_minutes": 0.0, "pak_usable": pak_usable, "pak_frozen": pak_frozen,
            "pak_conflict": False, "telemetry_missing_fraction": 0.0104,
            "pak_last_trusted_value": 9.0, "pak_last_trusted_time": decision_time,
            "quality_history_hours": 72, "pak_expected_per_hour": 6.0,
            "pak_trusted_hourly": [[(when.floor("h") - pd.Timedelta(value=h, unit="h")).isoformat(),
                                    hourly_mean(h), 6] for h in range(72)],
            "lab_recent": [],
            "measurements": {"ht.T6": {"value": 365.8, "time": decision_time, "age_min": 0.0},
                             "ht.F9": {"value": 228.6, "time": decision_time, "age_min": 0.0},
                             "ht.F26": {"value": 228.6, "time": decision_time, "age_min": 0.0}}}


def real_2026_07_24_snapshot() -> dict:
    state = real_2026_07_24_state(pak_frozen=False, pak_usable=True)
    return {"schema_version": "v1", "at": state["decision_time"],
            "label": "риск по качеству при возврате нагрузки",
            "why": "config/snapshot_moments.json: ПАК 14.637 мг/кг, не завис, без конфликта на "
                   "момент сборки среза — forecast_at вызван с fallback=False",
            "state": state, "trust": {"usable": True, "primary": "ЛИМС", "fallback": False},
            "forecast": {"model": "last_pak_bc", "value": 14.933, "lower": 8.924, "upper": 20.942,
                         "available": True,
                         "reason": "лабораторное значение прогнозируется по ПАК с причинной "
                                   "медианой 20 последних доступных пар; это не заводская "
                                   "калибровка ПАК к шкале ЛИМС"},
            # I1 (task-pool.md, «Доказательная база 21.09»): резервный прогноз без ПАК, посчитанный
            # на тот же момент сборки среза (forecast_at(..., fallback=True)) — bind_snapshot обязан
            # выбрать его после инъекции frozen_pak.
            "forecast_no_pak": {"model": "catboost_no_pak", "value": 8.11, "lower": 6.31, "upper": 11.09,
                                "available": True,
                                "reason": "тест Z5: пересчёт без ПАК после отказа источника"},
            "measured": state["measurements"], "synthetic_edits": [],
            "model_fingerprint": "fp", "source_rules_fingerprint": None}


def test_z5_bind_snapshot_ignores_a_pak_failure_injected_after_the_snapshot_was_built():
    """Регрессия #1: `bind_snapshot` не пересчитывает прогноз по свежему доверию. Красный сейчас —
    должен стать зелёным после I1 (срез хранит основной и no-PAK прогноз; bind_snapshot выбирает
    по пересчитанному trust)."""
    raw = copy.deepcopy(BASELINE)
    snapshot = real_2026_07_24_snapshot()
    frozen_state = apply_source_failure(copy.deepcopy(snapshot["state"]), "frozen_pak")

    trust = DataTrustAgent(trust_cfg()).assess(frozen_state)
    assert trust.fallback_mode is True, ("инъекция frozen_pak должна лишить ПАК доверия — иначе "
                                         "тест ничего не проверяет")

    _, bound_raw = bind_snapshot(raw, frozen_state, snapshot, None, trust_cfg())
    main = next(t for t in bound_raw["tanks"] if t["tank_id"] == "main")
    inflow = main["inflow_sulfur_mgkg"]

    assert "catboost_no_pak" in inflow["note"], (
        "bind_snapshot должен переключиться на прогноз catboost_no_pak после инъекции "
        f"frozen_pak (ПАК недоверен), а использовал: {inflow['note']!r}"
    )
    assert inflow["value"] == pytest.approx(11.09, abs=0.05), (
        "ожидалась верхняя граница catboost_no_pak ≈ 11.09 мг/кг после инъекции frozen_pak, "
        f"получено {inflow['value']} — bind_snapshot взял прогноз last_pak_bc (14.93 / 20.94), "
        "сохранённый в срезе на момент его сборки, вместо пересчёта по текущему (недоверенному) "
        "состоянию ПАК"
    )


def test_z5_end_to_end_decision_on_2026_07_24_with_frozen_pak_must_hold():
    """Регрессия #1 через полный decision-путь (Demo → run_demo_decision → bind_snapshot →
    решение), тот же путь, что использует demo и decision-service. Ожидание из
    task-pool.md «Доказательная база 21.09»: срез 2026-07-24T03:00 + `frozen_pak` →
    catboost_no_pak 8.11 / 11.09 → hold. Красный сейчас: bind_snapshot возвращает решение по
    устаревшему last_pak_bc 14.93 / 20.94 (план c0042 в этой фикстуре, не hold)."""
    demo = Demo(BASELINE, run_demo_decision, trust_cfg(), 300, snapshots=[real_2026_07_24_snapshot()])
    result = demo.run(fault="frozen_pak", snapshot="20260724-030000")

    note = result["binding"]["inflow_sulfur_note"]
    status = result["decision"]["status"]
    plan_id = (result["decision"].get("selected_plan") or {}).get("plan_id")

    assert "catboost_no_pak" in note, (
        f"Ожидался прогноз catboost_no_pak после инъекции frozen_pak, использован: {note!r}"
    )
    assert status == "hold", (
        "Ожидалось решение hold (catboost_no_pak 8.11/11.09 укладывается в запас реакции 12 ч), "
        f"получено status={status!r}, план={plan_id!r}. Регрессия #1: bind_snapshot использовал "
        "устаревший прогноз last_pak_bc 14.93/20.94, сохранённый в срезе на момент его сборки, "
        "и проигнорировал инъекцию frozen_pak."
    )
