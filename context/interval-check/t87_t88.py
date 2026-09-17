"""T87/T88: приток резервуара из данных и честность интервала прогноза. Только чтение; модель не переобучается."""
import json, pickle
from pathlib import Path
import numpy as np, pandas as pd
from neftecode.infrastructure.data.data import load_sources, build_features, split_periods
from neftecode.infrastructure.ml.forecast import calibrate, interval, predict_candidate

root = Path('.')
signals, lab, online = load_sources(root / 'task')
bundle = pickle.load(open(root / 'artifacts/model.pkl', 'rb'))
cfg = bundle['config']
out = {}

# --- T87: плотность и приток ---
book = __import__('openpyxl').load_workbook(next((root / 'task').glob('ЛИМС*.xlsx')), read_only=True, data_only=True)
rows = list(book.active.values); book.close()
# точка 2 гидроочистки начинается с колонки 82; найдём D15 в этой группе
hdr = rows[1]
dcols = [i for i in range(82, 94) if isinstance(hdr[i], str) and 'D15' in hdr[i]]
import datetime as dt
dens = pd.Series({r[dcols[0]]: r[dcols[0] + 1] for r in rows[4:] if isinstance(r[dcols[0]], dt.datetime)}).astype(float)
dens = dens[(dens > 700) & (dens < 900)].sort_index()
rho_train = float(dens[dens.index < '2025-01-01'].median()); rho_all = float(dens.median())
f26 = signals['ht.F26'].dropna(); f26 = f26[f26 > 0]
def q(s): return {'median': round(float(s.median()), 2), 'q10': round(float(s.quantile(.1)), 2), 'q90': round(float(s.quantile(.9)), 2), 'n': int(len(s))}
inflow_train = f26[f26.index < '2025-01-01'] * rho_train / 1000
inflow_2026 = f26[f26.index >= '2026-01-01'] * rho_all / 1000
out['t87'] = {'density_kgm3': {'train_median': round(rho_train, 1), 'all_median': round(rho_all, 1), 'n': int(len(dens)), 'column': hdr[dcols[0]]},
              'f26_m3h': {'train': q(f26[f26.index < '2025-01-01']), '2026': q(f26[f26.index >= '2026-01-01'])},
              'inflow_tph': {'train': q(inflow_train), '2026': q(inflow_2026)}}
M = 4000.0
for name, qq in (('scenario_95', 95.0), ('data_train', out['t87']['inflow_tph']['train']['median'])):
    out['t87'][f'window_h_{name}'] = round(M / qq, 2)
    out['t87'][f'dS_3h_{name}'] = round((9.13 - 5.19) * (1 - np.exp(-qq * 3 / M)), 3)
    out['t87'][f'stock_growth_48h_{name}'] = round((qq - 100.0) * 48, 0)

# --- T88: покрытие интервала last_pak ---
x, meta = build_features(signals, lab, online, None, cfg) if False else (None, None)
from neftecode.infrastructure.data.data import make_dataset
x, meta = make_dataset(signals, lab, online, cfg)
y = meta['actual_sulfur'].to_numpy()
pred = predict_candidate(bundle, 'last_pak', x)
t = pd.to_datetime(meta['decision_time'])
r0 = bundle['radii']['last_pak']
def coverage(mask, radius):
    m = mask & np.isfinite(pred)
    lo, hi = interval(pred[m], radius)
    inside = (y[m] >= lo) & (y[m] <= hi)
    return {'n': int(m.sum()), 'coverage': round(float(inside.mean()), 3) if m.sum() else None,
            'width': round(float((hi - lo).mean()), 2) if m.sum() else None}
halves = [('2023H1', '2023-01-01', '2023-07-01'), ('2023H2', '2023-07-01', '2024-01-01'), ('2024H1', '2024-01-01', '2024-07-01'),
          ('2024H2', '2024-07-01', '2025-01-01'), ('2025H1', '2025-01-01', '2025-07-01'), ('2025H2', '2025-07-01', '2026-01-01'),
          ('2026', '2026-01-01', '2027-01-01')]
out['t88'] = {'radius_current': round(float(r0), 4), 'calibration': '2025H2 (calibration_end 2026-01-01)', 'fixed': {}, 'rolling': {}}
for name, a, b in halves:
    mask = (t >= a) & (t < b)
    out['t88']['fixed'][name] = coverage(mask.to_numpy(), r0)
for i in range(2, len(halves)):
    name, a, b = halves[i]; pa, pb = halves[i - 1][1], halves[i - 1][2]
    prev = ((t >= pa) & (t < pb)).to_numpy() & np.isfinite(pred)
    radius = calibrate(y[prev], pred[prev], cfg['interval_coverage'])
    out['t88']['rolling'][name] = {'radius': round(float(radius), 4), 'calibrated_on': halves[i - 1][0],
                                   **coverage(((t >= a) & (t < b)).to_numpy(), radius)}
json.dump(out, open(root / 'context/interval-check/t87_t88.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
