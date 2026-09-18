"""β на T6 оценивается при обучении тем же ARX, что в исследовании; живое решение берёт оценку до момента."""
import numpy as np
import pandas as pd
import pytest

from neftecode.infrastructure.live.advisor import validate_response_model
from neftecode.infrastructure.response import estimate as E


def synthetic(months: int = 15, beta: float = -0.4, seed: int = 1):
    """10-минутная телеметрия: T6 ступенями, ПАК = уровень + β·(T6 − 360) с задержкой 3 ч + шум AR(1)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=months * 30 * 144, freq="10min")
    n = len(idx)
    steps = np.zeros(n)
    for start in range(0, n, 36):                       # новый шаг уставки каждые 6 ч
        steps[start:start + 36] = rng.normal(0, 1.5)
    t6 = 360.0 + steps + rng.normal(0, 0.05, n)
    effect = np.roll(t6 - 360.0, 18) * beta              # отклик через 3 ч
    effect[:18] = 0.0
    noise = np.zeros(n)
    for k in range(1, n):
        noise[k] = 0.7 * noise[k - 1] + rng.normal(0, 0.15)
    pak = 8.0 + effect + noise
    f9 = 200.0 + rng.normal(0, 3, n)
    f9[: n // 40] = 50.0                                 # один останов в начале: порог q01 F9 ниже рабочих значений
    signals = pd.DataFrame({"ht.T6": t6, "ht.T5": 340.0, "ht.F9": f9,
                            "ht.P13": 4.0, "ht.F2": 40000.0, "ht.T11": t6 + 5}, index=idx)
    online = pd.DataFrame({"time": idx, "value": pak})
    return signals, online


@pytest.fixture(scope="module")
def artifact():
    signals, online = synthetic()
    declared = {"schema_version": "v1", "tag": "ht.T6", "envelope_dt_c": 2.0, "response_onset_hours": 3.0,
                "horizon_response_share": 0.66, "flow_beta": None}
    return E.estimate_response(signals, online, "2024-01-01", declared, "fp", boot=8)


def test_the_estimate_recovers_a_negative_slope_of_the_right_size(artifact):
    assert pd.Timestamp(artifact["tau"]) == pd.Timestamp("2024-01-01") and artifact["primary"] == "train_end"
    assert -0.6 < artifact["beta_mgkg_per_c"] < -0.2
    assert artifact["ci"][0] <= artifact["beta_mgkg_per_c"] <= artifact["ci"][1]
    assert artifact["weak_strong"][0] == pytest.approx(0.5 * artifact["beta_mgkg_per_c"], abs=1e-3)
    assert artifact["weak_strong"][1] <= artifact["beta_mgkg_per_c"]
    assert artifact["n_rows"] >= E.MIN_ROWS
    assert artifact["t6_range_c"][0] < 360 < artifact["t6_range_c"][1]
    assert artifact["model_fingerprint"] == "fp" and artifact["horizon_response_share"] == 0.66
    assert "beta_mgkg_per_c" not in {k for k in artifact if k.startswith("history")}
    assert validate_response_model(artifact, "тест") is artifact


def test_the_grid_holds_half_year_taus_the_train_end_and_the_end_of_data(artifact):
    taus = [pd.Timestamp(e["tau"]) for e in artifact["estimates"]]
    assert taus[0] == pd.Timestamp("2024-01-01") and taus[-1] > pd.Timestamp("2024-03-01")
    assert taus[-1].hour == 23, "τ конца данных хранится с временем, а не датой: окно кончается строго до момента"
    assert all(pd.Timestamp(e["window"][1]) == pd.Timestamp(e["tau"]) - pd.Timedelta(6, "h") for e in artifact["estimates"])
    assert all(pd.Timestamp(e["feed_floor_until"]) == pd.Timestamp(e["window"][1]) for e in artifact["estimates"])
    assert all(e["ci"] is not None for e in artifact["estimates"])
    assert artifact["drift"] and all(d["beta"] < 0 for d in artifact["drift"])


def test_future_feed_does_not_change_the_causal_feed_floor():
    signals, online = synthetic(months=1)
    cut = signals.index[len(signals) // 2]
    before = E.prepare(signals, online, feed_floor_until=cut)
    changed = signals.copy()
    changed.loc[changed.index > cut, "ht.F9"] = 1.0
    after = E.prepare(changed, online, feed_floor_until=cut)
    assert before.attrs["feed_floor"] == after.attrs["feed_floor"]


def test_the_live_decision_takes_the_latest_estimate_made_before_the_moment(artifact):
    taus = [pd.Timestamp(e["tau"]) for e in artifact["estimates"]]
    chosen = E.response_at(artifact, taus[0] + pd.Timedelta(1, "D"))
    assert chosen["tau"] == artifact["estimates"][0]["tau"]
    assert "estimates" not in chosen
    assert E.response_at(artifact, taus[0] - pd.Timedelta(1, "min")) is None
    latest = E.response_at(artifact, "2030-01-01")
    assert latest["tau"] == artifact["estimates"][-1]["tau"]


def test_too_little_history_gives_no_estimate():
    signals, online = synthetic(months=1)
    with pytest.raises(ValueError, match="5000"):
        E.estimate_response(signals, online, "2023-01-20", {"envelope_dt_c": 2.0}, None, boot=0)


def test_the_step_response_of_a_pure_gain_is_the_gain():
    coef = np.zeros(3 * E.ARX_LAGS)
    coef[0] = -0.3                                        # ПАК реагирует на приращение T6 предыдущего шага
    response = E.step_response(coef)
    assert response[E.PLATEAU_STEPS].mean() == pytest.approx(-0.3)
