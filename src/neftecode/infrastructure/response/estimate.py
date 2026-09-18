"""β — отклик серы после гидроочистки на температуру входа реактора, оценённый при обучении.

Перенос без изменения метода из `context/response-research/t6/response_model.py` (`RESPONSE_MODEL_T6.md`):

* 10-минутный кадр `prepare`: установка в работе (T6, T5 > 320 °C, P13 > 3 МПа, F2 > 30000, F9 > q01 F9 на «горячих»
  строках, без NaN в опорных тегах), `stable_label` = работа ≥ 12 ч до и 6 ч после строки, ПАК на сетке 10 мин
  (среднее, правая метка), зависание — плато ≥ 1 ч по прошлому, ПАК валиден в 0.05–50 мг/кг;
  F2 по справочнику — расход газа на линии от ЦК-201; здесь это только эмпирический фильтр режима,
  не управляющая уставка и не утверждение, что весь поток проходит через Р-202;
* ARX на 10-минутных приращениях (24 лага T6, F9, ПАК-30 мин) по строкам `stable_label`; β — среднее накопленного
  отклика через 3–8 ч на устойчивый шаг +1 °C по T6; окно (τ − 12 мес., τ − 6 ч]; ДИ90 — бутстреп по месяцам, 40 повторов;
* weak = 0.5·β; strong = β × max прошлых отношений realized/estimate по полугодиям (cap −1.0 мг/кг/°C);
* область: q01–q99 T6 и F9 по пригодным 30-минутным строкам до τ; дрейф — тот же ARX по полугодиям (realized).

Оценка делается на сетке τ (1 января / 1 июля, начиная с первого τ, у которого есть 12 месяцев истории, плюс
`train_end` и конец данных); живое решение берёт последнюю оценку с τ не позже момента решения (`response_at`),
все её окна заканчиваются в τ − 6 ч — строго до момента.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

TEMPERATURE_TAG = "ht.T6"
FLOW_TAG = "ht.F9"
CORE_TAGS = ("ht.T6", "ht.T5", "ht.F9", "ht.P13", "ht.F2", "ht.T11")
HORIZON_H = 3.0
GUARD = pd.Timedelta(6, "h")             # окна заканчиваются в τ − 6 ч: метка устойчивости смотрит на 6 ч вперёд
WINDOW_MONTHS = 12
ARX_LAGS = 24                            # 4 ч 10-минутных лагов
STEP_HORIZON = 54                        # шагов отклика: 9 ч
PLATEAU_STEPS = slice(17, 48)            # накопленный отклик на 3.0 … 8.0 ч
MIN_ROWS = 5000
BOOT = 40
SEED = 0
WEAK_MULT = 0.5
STRONG_DEFAULT = 2.5
STRONG_CAP = -1.0                        # мг/кг на °C, верхняя граница эксперта (Q&A 11.09) — априорная, не из данных
FEED_FLOOR_Q = 0.01
SCHEMA_VERSION = "v1"


def prepare(signals: pd.DataFrame, online: pd.DataFrame, feed_floor_until) -> pd.DataFrame:
    """10-минутный кадр: T6, F9, ПАК, признаки работы установки. Все флаги смотрят в прошлое, кроме `stable_label`.

    `feed_floor_until` обязателен: порог расхода q01(F9) учится только на «горячих» строках не позже этого
    момента (τ − 6 ч), иначе будущее просачивается в отбор строк. Сама маска `hot` при этом не усекается —
    `running` считается по всей истории.
    """
    missing = [tag for tag in CORE_TAGS if tag not in signals.columns]
    if missing:
        raise ValueError(f"Для оценки отклика нет тегов {missing}")
    idx = signals.index
    f = pd.DataFrame(index=idx)
    f["T6"], f["T5"], f["F9"] = signals[TEMPERATURE_TAG], signals["ht.T5"], signals[FLOW_TAG]
    f["P13"], f["F2"] = signals["ht.P13"], signals["ht.F2"]
    hot = (f.T6 > 320) & (f.T5 > 320) & (f.P13 > 3.0) & (f.F2 > 30000) & (f.F9 > 0)
    if feed_floor_until is None:
        raise ValueError("prepare: нужен feed_floor_until (τ − 6 ч), иначе порог расхода учится на будущем")
    # Новый объект: `&=` на ссылке усекал бы саму `hot`, и `running` терял бы строки после τ.
    floor_rows = hot & (f.index <= pd.Timestamp(feed_floor_until))
    feed_floor = float(f.F9[floor_rows].quantile(FEED_FLOOR_Q)) if floor_rows.any() else math.nan
    running = hot & (f.F9 > feed_floor) & signals[list(CORE_TAGS)].notna().all(axis=1)
    f["running"] = running
    f.attrs["feed_floor"] = feed_floor
    f.attrs["feed_floor_until"] = pd.Timestamp(feed_floor_until).isoformat()
    r = running.astype(float)
    f["run_past12h"] = r.rolling("12h").min().eq(1)
    f["stable_label"] = f.run_past12h & r[::-1].rolling(37, min_periods=1).min()[::-1].eq(1)
    p = online.set_index("time").value.sort_index()
    changed = p.diff().abs().gt(1e-6) | p.diff().isna()
    run = changed.cumsum()
    t = p.index.to_series()
    frozen = (t - t.groupby(run).transform("min")) >= pd.Timedelta(1, "h")
    grid = lambda s, how: s.resample("10min", label="right", closed="right").agg(how).reindex(idx)
    pak = grid(p, "mean")
    fr = grid(frozen.astype(float), "max").fillna(1.0).astype(bool)
    f["pak"] = pak.where(~fr & pak.between(0.05, 50))
    return f


def _wmean(s: pd.Series, t: pd.DatetimeIndex, start_min: int, end_min: int, min_valid: int = 1):
    width = (end_min - start_min) // 10
    return s.rolling(width, min_periods=min_valid).mean().reindex(t + pd.Timedelta(end_min, "min")).to_numpy()


def decision_rows(f: pd.DataFrame, times: pd.DatetimeIndex) -> pd.DataFrame:
    """30-минутные строки: входы, шаг T6 за 30 мин, цель через 3 ч и признак пригодности для обучения."""
    d = pd.DataFrame(index=times)
    d["PAK30m"] = _wmean(f.pak, times, -30, 0, 1)
    d["PAK24h"] = _wmean(f.pak, times, -1440, 0, 72)
    d["T6"] = _wmean(f.T6, times, -30, 0, 1)
    d["F9"] = _wmean(f.F9, times, -30, 0, 1)
    d["A30"] = _wmean(f.T6, times, 0, 30, 1) - d.T6
    d["y3"] = _wmean(f.pak, times, 180, 210, 2)
    ok = np.ones(len(times), bool)
    for off in (-420, -60, 0, 30, 60, 120, 180, 210):
        ok &= f.stable_label.reindex(times + pd.Timedelta(off, "min")).fillna(False).to_numpy(bool)
    d["train_valid"] = ok & np.isfinite(d[["PAK30m", "PAK24h", "T6", "F9", "A30", "y3"]]).all(axis=1).to_numpy()
    return d


def row_times(f: pd.DataFrame) -> pd.DatetimeIndex:
    times = f.index[(f.index.minute % 30 == 0)]
    return times[(times >= times[0] + pd.Timedelta(31, "D")) & (times <= times[-1] - pd.Timedelta(4, "h"))]


def arx_design(f: pd.DataFrame):
    """(времена, X, y) ARX на 10-минутных приращениях по строкам stable_label с валидным ПАК."""
    g = pd.DataFrame({"T6": f.T6, "F9": f.F9, "pak": f.pak.rolling("30min").mean()})
    D = g.diff()
    X = pd.concat({f"{c}_{j}": D[c].shift(j) for c in ("T6", "F9", "pak") for j in range(1, ARX_LAGS + 1)}, axis=1)
    m = (f.stable_label & f.pak.notna() & f.stable_label.shift(ARX_LAGS, fill_value=False) & X.notna().all(axis=1)
         & D.pak.notna()).to_numpy()
    return f.index[m], X.to_numpy()[m], D.pak.to_numpy()[m]


def step_response(coef: np.ndarray) -> np.ndarray:
    """Накопленный отклик ПАК на устойчивый шаг +1 °C по T6 (первые ARX_LAGS коэффициентов — T6, последние — ПАК)."""
    b, a = coef[:ARX_LAGS], coef[2 * ARX_LAGS:3 * ARX_LAGS]
    u = np.zeros(STEP_HORIZON + ARX_LAGS)
    u[ARX_LAGS] = 1.0
    ys = np.zeros(STEP_HORIZON + ARX_LAGS)
    for k in range(ARX_LAGS, STEP_HORIZON + ARX_LAGS):
        ys[k] = b @ u[k - ARX_LAGS:k][::-1] + a @ ys[k - ARX_LAGS:k][::-1]
    return np.cumsum(ys[ARX_LAGS:])


def plateau(T: pd.DatetimeIndex, X: np.ndarray, y: np.ndarray, mask: np.ndarray, boot: int = 0, seed: int = SEED):
    """β на строках mask: среднее накопленного отклика на 3–8 ч; с boot > 0 — (β, [q05, q95], n), иначе (β, None, n)."""
    def one(ix):
        return float(step_response(LinearRegression().fit(X[ix], y[ix]).coef_)[PLATEAU_STEPS].mean())
    ix = np.flatnonzero(mask)
    if len(ix) < MIN_ROWS:
        return math.nan, None, int(len(ix))
    est = one(ix)
    if not boot:
        return est, None, int(len(ix))
    rng = np.random.default_rng(seed)
    months = np.asarray(T[ix].to_period("M").astype(str))
    unique = np.unique(months)
    groups = {u: ix[months == u] for u in unique}
    draws = [one(np.concatenate([groups[u] for u in rng.choice(unique, len(unique))])) for _ in range(boot)]
    return est, [float(np.percentile(draws, 5)), float(np.percentile(draws, 95))], int(len(ix))


def _window_mask(T: pd.DatetimeIndex, start, end) -> np.ndarray:
    return np.asarray((T > pd.Timestamp(start)) & (T <= pd.Timestamp(end)))


def past_ratios(T, X, y, first_time, cut) -> dict[str, float]:
    """Отношения realized/estimate правила trailing-12 по полугодиям, закончившимся до τ − 6 ч."""
    ratios = {}
    h0 = pd.Timestamp(first_time) + pd.DateOffset(months=WINDOW_MONTHS)
    starts = [x for x in pd.date_range(pd.Timestamp(h0.year, 1, 1), cut, freq="MS") if x.month in (1, 7) and x >= h0]
    for s0 in starts:
        s1 = s0 + pd.DateOffset(months=6)
        if s1 > cut or s0 - pd.DateOffset(months=WINDOW_MONTHS) < pd.Timestamp(first_time):
            continue
        est_prev, _, _ = plateau(T, X, y, _window_mask(T, s0 - pd.DateOffset(months=WINDOW_MONTHS), s0))
        real, _, _ = plateau(T, X, y, _window_mask(T, s0, s1))
        if np.isfinite(est_prev) and np.isfinite(real) and est_prev < -0.02:
            ratios[str(s0.date())] = float(real / est_prev)
    return ratios


def fit_at(f: pd.DataFrame, R: pd.DataFrame, T, X, y, tau, boot: int = BOOT) -> dict | None:
    """Оценка при τ по данным до τ − 6 ч; None, если строк ARX в окне меньше MIN_ROWS."""
    tau = pd.Timestamp(tau)
    cut = tau - GUARD
    lo = tau - pd.DateOffset(months=WINDOW_MONTHS)
    beta, ci, n_rows = plateau(T, X, y, _window_mask(T, lo, cut), boot=boot)
    if not np.isfinite(beta):
        return None
    ratios = past_ratios(T, X, y, f.index[0], cut)
    strong_mult = max(1.0, max(ratios.values())) if ratios else STRONG_DEFAULT
    weak = WEAK_MULT * beta if beta < 0 else math.nan
    strong = max(strong_mult * beta, STRONG_CAP) if beta < 0 else math.nan
    target_time = R.index + pd.Timedelta(HORIZON_H + 0.5, "h")
    usable = R.train_valid.to_numpy() & np.asarray(target_time <= cut)
    H = R[usable]
    return {
        "tau": tau.isoformat(),
        "beta_mgkg_per_c": round(float(beta), 4),
        "ci": [round(v, 4) for v in ci] if ci else None,
        "n_rows": n_rows,
        "weak_strong": ([round(float(weak), 3), round(float(strong), 3)] if np.isfinite(weak) else None),
        "strong_multiplier": round(float(strong_mult), 3),
        "past_ratios": {k: round(v, 3) for k, v in ratios.items()},
        "t6_range_c": [round(float(H.T6.quantile(.01)), 1), round(float(H.T6.quantile(.99)), 1)] if len(H) else None,
        "f9_range_tph": [round(float(H.F9.quantile(.01)), 1), round(float(H.F9.quantile(.99)), 1)] if len(H) else None,
        "n_history_rows": int(len(H)),
        "feed_floor_tph": round(float(f.attrs["feed_floor"]), 3),
        "feed_floor_until": f.attrs["feed_floor_until"],
        "window": [str(lo), str(cut)],
    }


def halves(index) -> np.ndarray:
    index = pd.DatetimeIndex(index)
    return np.asarray(index.year.astype(str)) + np.where(index.month <= 6, "H1", "H2")


def drift(T, X, y) -> list[dict]:
    """Тот же ARX внутри каждого полугодия (realized, не trailing)."""
    hv = halves(T)
    out = []
    for h in sorted(np.unique(hv)):
        beta, _, _ = plateau(T, X, y, hv == h)
        if np.isfinite(beta):
            out.append({"tau": f"{h[:4]}-{'01' if h.endswith('H1') else '07'}-01", "beta": round(float(beta), 4)})
    return out


def tau_grid(f: pd.DataFrame, train_end) -> list[pd.Timestamp]:
    first = pd.Timestamp(f.index[0]) + pd.DateOffset(months=WINDOW_MONTHS)
    last = pd.Timestamp(f.index[-1])
    taus = {x for x in pd.date_range(pd.Timestamp(first.year, 1, 1), last, freq="MS") if x.month in (1, 7) and x >= first}
    taus.add(pd.Timestamp(train_end))
    taus.add(last)
    return sorted(taus)


def estimate_response(signals: pd.DataFrame, online: pd.DataFrame, train_end, declared: dict,
                      model_fingerprint: str | None = None, boot: int = BOOT) -> dict:
    """Артефакт C2: объявленная политика из `declared` (config/response_model.json) плюс оценки по данным на сетке τ."""
    estimates = []
    latest_parts = None
    for tau in tau_grid(pd.DataFrame(index=signals.index), train_end):
        cut = pd.Timestamp(tau) - GUARD
        f = prepare(signals, online, feed_floor_until=cut)
        R = decision_rows(f, row_times(f))
        T, X, y = arx_design(f)
        estimate = fit_at(f, R, T, X, y, tau, boot=boot)
        if estimate is not None:
            estimates.append(estimate)
            latest_parts = (T, X, y)
    if not estimates:
        raise ValueError("Оценка отклика невозможна: ни в одном окне нет 5000 строк ARX")
    primary = next((e for e in estimates if pd.Timestamp(e["tau"]) == pd.Timestamp(train_end)), estimates[0])
    method = (f"ARX({ARX_LAGS} lags, 10-min differences of {TEMPERATURE_TAG}, {FLOW_TAG}, PAK 30-min mean), beta = mean cumulative "
              f"PAK response at 3-8 h to a sustained +1 C step in T6; window = {WINDOW_MONTHS} months before tau minus 6 h guard; "
              f"rows = unit running >=12 h before and 6 h after (T6,T5>320 C, P13>3 MPa, F2>30000, "
              f"F9>q01 learned on hot rows no later than each tau minus 6 h, no NaN), PAK valid "
              f"(0.05-50 mg/kg, not frozen >=1 h); ci = month-block bootstrap "
              f"90% ({boot} draws, seed {SEED}); weak = 0.5*beta, strong = beta * max past realized/estimate ratio (cap {STRONG_CAP}); "
              f"drift = same ARX per half-year (realized); estimated at training on the tau grid, the live decision takes the "
              f"latest tau <= decision time. Method of context/response-research/t6/response_model.py, unchanged.")
    keep = {k: v for k, v in declared.items()
            if k not in ("tau", "beta_mgkg_per_c", "ci", "n_rows", "drift", "model_fingerprint", "t6_range_c",
                         "f9_range_tph", "weak_strong", "method")}
    out = {"schema_version": SCHEMA_VERSION, "tag": TEMPERATURE_TAG, "flow_tag": FLOW_TAG, **keep,
           "window_months": WINDOW_MONTHS, "method": method, "flow_beta": declared.get("flow_beta"),
           "primary": "train_end", "train_end": str(pd.Timestamp(train_end)),
           **{k: primary[k] for k in ("tau", "beta_mgkg_per_c", "ci", "n_rows", "weak_strong", "t6_range_c",
                                         "f9_range_tph", "feed_floor_tph", "feed_floor_until")},
           "drift": drift(*latest_parts), "model_fingerprint": model_fingerprint,
           "selection_rule": "latest estimate with tau <= decision time; every window of an estimate ends at tau - 6 h",
           "estimates": estimates}
    return out


def response_at(response: dict | None, when) -> dict | None:
    """Модель отклика, сделанная строго до момента `when`: последняя оценка с τ ≤ when; без `estimates` — сам файл."""
    if response is None:
        return None
    estimates = response.get("estimates")
    if not estimates:
        return response
    when = pd.Timestamp(when)
    chosen = None
    for estimate in estimates:
        if pd.Timestamp(estimate["tau"]) <= when and (estimate.get("ci") is not None):
            if chosen is None or pd.Timestamp(estimate["tau"]) > pd.Timestamp(chosen["tau"]):
                chosen = estimate
    if chosen is None:
        return None
    base = {k: v for k, v in response.items() if k != "estimates"}
    required = ("tau", "beta_mgkg_per_c", "ci", "n_rows", "weak_strong", "t6_range_c", "f9_range_tph")
    optional = ("feed_floor_tph", "feed_floor_until")
    selected = {k: chosen[k] for k in required}
    selected.update({k: chosen[k] for k in optional if k in chosen})
    return {**base, **selected}
