# Response model research — working notes

Started 2026-09-15. Question: can history give g(real_state, action) -> sulfur after HT after lag, with uncertainty?
Final report: `RESPONSE_MODEL_RESEARCH.md` (repo root). Scripts: `context/response-research/*.py`, outputs `out/`.

## Stage 1 — code facts (read from implementation)

- Forecast: `infrastructure/ml/forecast.py`. Target = LIMS HT point 2 sulfur (col 94), one row per analysis,
  decision_time = sample_time - 2 h. Features `data.build_features`: 97 tags x (now, mean6h, delta6h) + lab/pak
  (lab delay 4 h, max age 48 h; PAK max age 30 min, frozen = 1 h flat, conflict with LIMS at sample time).
  Split by `config/experiment.json`: train < 2025-01-01 (by target_available_time), val 2025H1, cal 2025H2, test 2026.
  Candidates last_lab, last_pak, ridge, catboost(log1p, MAE), catboost_no_pak. Selected last_pak (gain 0.3%).
  Interval: split-conformal radius on |log1p residual|, 90%, on calibration.
- Risk model `ml/risk.py` trained and pickled, NOT used by live decision.
- Live binding `infrastructure/live/advisor.py::bind_forecast`: inflow sulfur = forecast UPPER bound
  (or last trusted PAK if frozen); tank level = mean trusted PAK over 42 h.
- Action consequences: `domain/production/process.py::HydrotreatingModel` (scenario, NOT data):
  remaining = (1-conv_ref) * exp(-k*(T - T_ref)) * (flow/flow_ref)^n, k=0.085 1/°C, n=0.7, conv_ref=0.9921,
  T_ref 348, flow_ref 256 m3/h, step lag 2 h (`effective_controls`: setpoint acts fully after lag).
  Controls: ht_reactor_inlet_temp_c [330,375] step 1; ht_feed_flow_m3h [180,300] step 10. Config `config/scenarios/*.json`.
- Integration point: `plan_operation.py::inflow_properties` -> inflow = tank.inflow_sulfur (forecast upper) *
  `_response_ratio` = chain(action)/chain(idle). So action effect enters as multiplicative ratio vs HOLD.
  -> a data-driven or hybrid response can replace `_response_ratio` (or the HT model) without touching gate/optimizer.
- Gate `domain/advisory/gate.py`: quality (S<=10, T95, cetane, density), control ranges, recipe, inventory,
  applicability (OUT_OF_REGION -> not pass), unknown blocks.
- Expert (Q&A 11.09): +1 °C -> 0.3..1 ppm less sulfur ("оценка близка"); APC on 24-2000 reacts fast to sulfur,
  feedback makes effect estimation hard; direction: higher T -> lower S. Feed sulfur vs product sulfur correlates weakly.
  Lag 0–3 h (msg 518). No HT schemes. No equipment limits.
- Tags 24-2000 (`Теги_хакатон.xlsx` КИП): 26 tags. Expert msg 520: P8 = GSS temp at R-202 inlet, T11 = mass feed,
  F19 = pressure R-202 inlet. Scales contradict (P8 median 0.17, T11 ~363, F19 ~214 with negatives).

## Data availability

- Present: task/data/avt_tags.csv (71 tags), task/data/242000_tags.csv (26 tags), 10-min grid 2023-01-01..,
  189 217 rows; LIMS xlsx; PAK xlsx (sulfur ~1/min? 189 649 pts; D15 from 2025-03-05); Теги xlsx; AVT schemes PDF.
- Missing: 24-2000 schemes; H2 partial pressure / H2-to-feed ratio tag explicit; reactor WABT/outlet per bed;
  feed sulfur LIMS at HT point 1 (check); APC setpoints/modes; operator action log.

## Stage 2 — hypotheses to test

- H1: 24-2000 descriptions are permuted vs tags; tag letters (T/P/F/W) match magnitudes. Candidate reading:
  T11 ~363 = GSS temp R-202 inlet; F19 ~168 = mass feed t/h (F19/F26 ~ 0.83 = diesel density); P13 ~3.76 = R-202 inlet
  pressure MPa; P8 ~0.12 = R-202 dP. Verify on data before using.

## Stage 2 — tag semantics check (script inline, 2026-09-15)

Filter F26>100 (unit running). Findings:
- F19/F26 median 0.832, IQR 0.824–0.840 -> F19 = mass feed t/h, F26 = volumetric feed m3/h, density ~832 kg/m3
  (diesel). Supports H1 (tag letter = physical type); expert msg 520 roles look rotated.
- F9 corr F26 = 1.00 (same flow, other scale); F1 corr W10 = 1.00; F17 corr F19 = 0.96 (product ~ feed).
- T5, T6, T11 corr 0.99, medians 369.8 / 362.7 / 363.6 -> reactor temperatures; T23 (235) corr 0.87.
- P13 median 3.92 (reactor pressure MPa), P3 3.66; P8 median 0.174, corr feed 0.68 -> plausible reactor dP.
- F2 ~89 000 (gas, circulating?), F22 ~11 000 (fresh H2?), F25 ~13 000 corr feed 0.74. F2/F26 ~350 nm3/m3 = typical HT H2/oil.
- W7 ~0.17, no relation to PAK. 307 = placeholder in many tags (Q20 22k times).
- Downtime: many tags near 0 (1% quantile) -> shutdowns must be excluded.
- F19/F26*1000 vs LIMS HT-out D15 (n=1004): mean diff -3.7 kg/m3, sd 7.7, corr ~0 (narrow D15 range). Level match supports
  mass/volume reading of F19/F26.
- Plot out/fig/ht_2025-03.png: T5 ~368 (above T6/T11 by ~7 — exotherm/outlet), T6≈T11 ~360 (inlet). Temps drift slowly
  (±5 °C over days), no clean steps; temp dips coincide with feed dips (confounding). F22 piecewise constant with steps
  (setpoint-like). P3/P13 oscillate. PAK noisy ±1–2 ppm at 10 min. 17–20.03: feed cut to ~200 m3/h while PAK rose to
  12–14 -> operator/APC reacts to quality (reverse causality).

## Research plan (files)
s1_frame.py (clean 10-min + hourly frame, running mask) -> s2_actions.py (action detection, stats, co-movement)
-> s3_lags.py (xcorr, event study, feedback direction) -> s4_models.py (A vs B vs residual vs mechanistic, temporal)
-> s5_counterfactual.py (sanity tables) -> s6_support.py (OOD gate) -> report.
Key risk to test: APC feedback => ΔT correlates with FUTURE sulfur with wrong sign (reverse causality).

## s1/s2 results (out/s1_summary.json, out/s2_actions.json)

- Running 93.8%, stable (12 h before, 6 h after) 84.8%. PAK valid in stable 98%. Long stops: 2024-03-16..04-22 (885 h,
  after it T drops 378 -> 359: catalyst change/regeneration), 2026-04-15..27, 2026-06-16..07-02.
- CATALYST CYCLE: quarterly T_in 365 (2023Q1) -> 378 (2024Q1) | stop | 359 (2024Q2) -> 372 (2026Q1) | stop | 362.
  PAK quarterly mean flat 7.5–9.2. => T level tracks catalyst activity, sulfur held at target by control. Cross-year
  regression of S on T is confounded by ageing; only short-horizon within-cycle changes carry effect information.
- Variability T_in: median |Δ| 0.18 (10 min), 0.57 (1 h), 0.95 (3 h), 2.0 (1 d), 3.5 (7 d). Hourly |ΔT|>=2: 6.6%, >=3: 2.3%.
- Clean hourly step events (flat 3 h before, held 3 h after): T >=1 °C 756; >=2 °C 115 (2023 51, 2024 33, 2025 20, 2026 11);
  >=3 °C 49. feed >=10 m3/h 183; >=15: 68. gas22 >=500: 156. h2oil changes are mostly feed changes (hourly corr -0.80)
  -> H2/oil not an independent action (gas2 roughly constant).
- Co-movement 3 h: corr(ΔT, Δfeed%) 0.25; P(|Δfeed|>=5% | |ΔT|>=2) 24% vs base 11%; P(|ΔT|>=2 | |Δfeed|>=5%) 41% vs 20%.
  Hourly corr ΔT_in–ΔT_out 0.89, ΔT–Δgas2 0.39.

## s3 results (out/s3_lags.json, out/fig/event_study.png)

- PAK vs LIMS offset: best corr when PAK taken 90 min BEFORE LIMS sample time: corr 0.29, MAE 1.65 (offset 0: corr 0.07,
  MAE 1.69). PAK is a weak proxy of lab sulfur (max corr 0.29). Any PAK-trained response = response in PAK units.
- Hourly xcorr dT(t) vs dPAK(t+k): k=-1 +0.36 (PAK rose previous hour -> T rises now = feedback), k=0 -0.48,
  k>=+1 ~0 (-0.05, -0.03). Feed: k=0 +0.22, k=+2 -0.09. No delayed effect peak at 2 h.
- Detrended levels (48 h): T vs PAK k=0..+3: -0.25..-0.21, decays by +6; k<0 positive ~+0.1..0.14.
- Event study, T steps >=1.5 °C: up n=174, down n=128 (2023–2026). Pattern UP: PAK ~-0.4 (h-6..-1) -> spike +0.54 in hour 0
  -> T raised in hour 1 (+2.05) -> PAK -0.42..-0.65 for 12 h. Feed rose ~+4 m3/h in the 6 h before step and fell after.
  DOWN mirror: PAK drop in hour 0 -> T lowered -> PAK back +0.6..+0.9. => steps are REACTIONS to PAK excursions; post-step
  change vs pre-spike level ~-0.1..-0.2 ppm for +2 °C (up), ~0..+0.2 (down): right sign, small, not separable from
  mean reversion of the spike.
- Feed steps >=8: up n=115 PAK +0.73 in 1st hour then +0.2..0.35; down n=174 PAK -0.74 then -0.15..-0.25; T moves with feed
  (up: T +1.3; down: T -1.0) -> confounded.
- ARX (10-min differences, 4 h lags of dT, dfeed, dPAK30min, train 2023–2025, n=131k): step +1 °C -> PAK -0.14 (2 h),
  -0.29 (3 h), -0.24 (6 h); month-block bootstrap 90%: 3 h [-0.32, -0.24]. Feed +1 m3/h -> +0.029 (3 h) [0.023, 0.037],
  i.e. +10 m3/h (~4%) -> +0.3 ppm. Response starts within 10–30 min, most by ~1.5 h, plateau 3 h.
- Reverse (APC evidence): past PAK lags raise R² of dT from 0.34 to 0.46. PAK deviation from 24 h mean +1..2 ppm -> T +1.03 °C
  over next 3 h; -1..-2 -> -0.97; >2 -> +1.70; <-2 -> -1.41. Closed loop ~1 °C per ppm. STRONG FEEDBACK.
- Magnitude refs: ARX 0.25–0.3 ppm/°C (~3.3 %/°C); expert Q&A 0.3–1 ppm/°C; scenario k=0.085 -> 0.68 ppm/°C at 8 ppm;
  Arrhenius Ea~120 kJ/mol, n≈1.7 kinetics -> d ln S/dT ≈ -0.05 (0.4 ppm/°C). All same order; data at low end
  (feedback + noise attenuate towards zero).
- Figure reading: FEED steps have flat PAK pre-trend (−2..0 h) -> more exogenous than T steps (which follow PAK spikes).
  Feed up (+11..13 m3/h, ~5%): PAK +0.73 in hour 1 while T still flat (open-loop phase), then T +1.3 (APC) and PAK settles +0.25.
  Feed down (−12..15): PAK −0.74 hour 1, then −0.2. Triangulation: 0.73 − 1.3·kT ≈ 0.25 -> kT ≈ 0.37 ppm/°C, matches ARX
  (0.29) and expert (0.3–1). Open-loop feed elasticity ~ (0.73/8.4)/(5%) ≈ 1.7 (upper bound, includes hydraulic transient);
  scenario uses 0.7. Effect of feed shows up within 1 h (no 2 h dead time).

## s4 dataset (out/s4_dataset.json)
Hourly decisions, valid 24 660 (2023 7346, 2024 6173, 2025 7621, 2026 3520). Per h: train 13.5k, val 3.7k, cal 3.9k, test 3.5k.
aT (next hour) q01..q99 −2.87..+3.30 °C; |aT|>=1 22.9%, >=2 6.5% (2023 702, 2024 518, 2025 283, 2026 104 hours, clustered).
aF_rel q01..q99 −5.4%..+5.5%; |aF|>=5% 2.6% (2026: 64). corr(aT, aF) 0.07; corr(aT, PAK trend last hour) 0.37 (feedback).

## s5 models (out/s5_models.json). Target PAK mean ±30 min at t+h, predict Δ vs PAK 1 h mean.
MAE test 2026 (all / |aT|>=2 / |aF|>=5%):
 h1: persistence 0.810/1.690/1.609; A_cb 0.867/1.677/1.564; B_cb 0.964/2.360/2.010; B_ridge 1.006; H_prior 0.911/1.995/1.820.
 h2: persistence 1.080/2.673/2.686; A_cb 0.964/1.634/2.348; B_cb 0.959/1.586/2.381; B_ridge 0.976/1.548/2.268;
     M_scen 0.947/1.544/2.149; H_fitted 0.941/1.530/2.177; H_prior(k=.035,n=1) 0.917/1.401/2.025 (best).
 h3: persistence 1.203/2.989/2.285; A_ridge 0.979/1.722/1.783; A_cb 1.022/1.683/1.670; B_cb 1.005/1.587/1.750;
     M_scen 0.982/1.557/1.449; H_prior 0.967/1.367/1.286 (best).
 Quiet rows: persistence best at every h (0.58/0.71/0.79 test) — ML state models worse than persistence when nothing happens.
=> MODEL B vs A: no stable gain (h1 worse, h2 ≈, h3 small). Action variables add little predictive info in open data.
Effect calibration (slope of realized residual y−A_cb on predicted effect, action rows, week-block 90% CI):
 h1: val ~0.07 (CI∋0), cal −0.42, test −0.33 for B models -> WRONG SIGN out of sample at 1 h (same-hour feedback).
 h2 test: H_prior 1.33 [1.03,1.72], M_scen 0.52 [0.41,0.64], B_cb 1.01 [0.50,1.51], R_linear 4.4 (under-predicts).
 h3 test: H_prior 1.50, M_scen 0.68, B_cb 1.45, B_ridge 2.61. cal h3: H_prior 1.70, M_scen 0.73.
 => realized T-effect at 2–3 h on held-out ≈ 1.3–1.7 × 0.3 ≈ 0.4–0.5 ppm/°C-equivalent; scenario (0.68 ppm/°C) over-predicts
    by ~1.5–2x at h2 and ok-ish at h3; fitted-on-train k (0.010–0.036) under-predicts. Unstable -> magnitude uncertain ×2–3.
 Caveat: realized residual still contains mean reversion of the PAK spike that triggered the action (confounding).
Learned coefficients: ridge aT −0.52 (h1), −0.15 (h2), −0.16 (h3) ppm/°C; aF: +19 (h1), +4 (h2), −0.5 (h3) ppm per 100%
 -> feed effect decays/flips with horizon = closed-loop APC compensation, not open-loop kinetics. gas22 ~0, drop.
PDP B_cb: T monotone (h2: −3:+0.32 … +4:−0.56); feed NON-monotone at h2 (−10%:−0.22, −5%:−0.27, +5%:−0.19, +10%:−0.72) = red flag.

## s6 identification (out/s6_identification.json) — double ML, time-block cross-fitting, week-block CI 90%
- Action predictability from state: R²(aT) 0.32 (reaction to state/PAK), R²(aF) 0.04 (feed moves ~exogenous to HT state).
- theta_T ppm/°C pooled: h1 −0.36 [−0.40,−0.32]; h2 −0.23 [−0.26,−0.19]; h3 −0.28 [−0.32,−0.24].
  Unprovoked (no PAK excursion before, 24% of rows): h1 −0.30, h2 −0.28 [−0.34,−0.22], h3 −0.30 [−0.37,−0.24].
  By year h3: 2023 −0.14, 2024 −0.29, 2025 −0.47, 2026 −0.50; unprovoked h3: 2023 −0.17, 2024 +0.01 (CI −0.11..0.18),
  2025 −0.48, 2026 −0.70 [−0.87,−0.50]. h2 by year: −0.17, −0.19, −0.28, −0.48. => SIGN stable, MAGNITUDE varies ×3–5
  between years (possibly catalyst state). Pooled ≈ −0.28 ppm/°C ≈ 3.3 %/°C (k≈0.035 1/°C).
- theta_feed ppm per +1% feed: h1 +0.15, h2 +0.09, h3 +0.06 (pooled; decays = APC compensation). By year h3: 2023 0.00,
  2024 +0.03, 2025 +0.11, 2026 +0.21. Elasticity at 8.4 ppm: 0.7 (h3 pooled) .. 2.5 (2026). Scenario n=0.7 = low end.
- LIMS independent check (n=1142, lab at τ vs actions after τ−2h, residualized actions): T −0.35 [−0.51,−0.22] ppm/°C,
  feed +0.29 [+0.20,+0.36] ppm per 1%. Raw (not residualized) T −0.73. Same sign as PAK; magnitude similar for T.
- Scenario k=0.085 -> 0.71 ppm/°C at 8.4 = ~2.5× pooled; effect-calibration slope of M_scen 0.5–0.7 on test confirms over-prediction.

## s7 counterfactual / support / uncertainty (out/s7_counterfactual.json, out/s7_tables.md; prototype response_prototype.py)
- Tables for 5 real states (h=3): B_cb flat beyond +3 °C (T+4 = T+6 = 6.70 demo; 8.18 hot state) = trees cannot extrapolate;
  B_ridge linear unbounded; scenario (k .085) sits at upper edge of data box; hybrid mid with effect range, e.g. demo
  T+2: −0.48 (−1.12..−0.21) ppm; feed−5%: −0.36 (−1.02..−0.15) -> sign sure, magnitude ×5, T+2 vs feed−5% NOT distinguishable.
- Over 400 test states (h3): B_cb T non-monotone in 41% of states; feed "wrong direction" in 100% for both B models
  (B_ridge: feed −5% -> +0.027 ppm); B_cb effect T+2 median −0.25 [q05 −0.40, q95 −0.03]; T+4 − T+3 ≈ −0.01.
- Interval coverage test 2026 h3, target 90% (conformal on 2025H2): A_cb all .83 / action rows .71; B_cb .82/.69;
  scenario .80/.68; HYBRID with effect box .87/.85 (width 3.8 all, 4.5 action). Only hybrid near nominal on action rows.
- SupportGate v2 (history before decision; state T_in/feed/h2oil; analogs = sustained 3 h moves, same sign, ±max(0.5, 35%);
  SUPPORTED ≥30 analogs & ≥5 days; LOW ≥10 & ≥3 days; hard ranges q0.5–q99.5 and hourly step ≤ q99.5 (4.7 °C, 8.7%)).
  Test states: T+1 SUPPORTED 16% / LOW 20% / UNSUP 64%; T+2 5/16/78; T+3 0/13/87; T+4 0/3/97; feed±5% ≥95% UNSUP;
  T+2&feed−5% 100% UNSUP. Historical data almost never contain "feed changed while T held" (APC moves T with feed).
  Realized hybrid MAE by gate label on test transitions: SUPPORTED 0.77 (n274), LOW 0.92 (150), UNSUPPORTED 1.04 (748).
- Hot end-of-cycle state T 383: T+2 -> 385 outside history -> UNSUPPORTED (correct). High feed 305 -> outside range.

## Decision drafted: VERDICT C (hybrid)
baseline = existing state-only forecast (+conformal) × mechanistic ratio exp(−k dT)(1+dF)^n, k∈[0.015,0.085] mid 0.035,
n∈[0.4,3.0] mid 1.0, asymmetric lag (harm 0 h, benefit 2 h), gate uses worst box edge; SupportGate: UNSUPPORTED -> block (unknown),
LOW -> allowed only with worst edge. Pure response ML (B) rejected: no stable gain, wrong sign at 1 h out of sample,
non-monotone, saturates. Only actions: reactor inlet T (T11), feed rate (F26, low support). Not actions: H2/oil, gas22, P.

## Report
Final: RESPONSE_MODEL_RESEARCH.md (repo root), 2026-09-15. Verdict C. Code in src NOT changed; prototype in response_prototype.py.
Open: confirm 24-2000 tag semantics (T11/F26/F19) with organizers; request APC log; decide whether to implement §21.

# ROUND 2 — final temperature response model (plan ~/.claude/plans/temporal-noodling-muffin.md), 2026-09-15
Scope: only ΔT (T11). Strict split: SELECT < 2025-07-01 (FIT 2023–2024, VAL 2025H1), EVAL-1 2025H2, EVAL-2 2026.
Everything (coefficients, ranges, form, features, action def, horizon, conformal radius, support thresholds) on SELECT only.
Scripts final/f0..f5, outputs final/out. Final doc RESPONSE_MODEL_FINAL.md.
Known leak in round 1: k=0.035 and box [0.015,0.085] used DML over 2023–2026 (k_hi from 2026 unprovoked); conformal on 2025H2.

## F0 leak fix (final/out/f0_leakfix.json) — same ds.pkl, A_cb baseline (<2025), DML theta on SELECT only
- SELECT theta_T ppm/°C (joint with feed): h2 −0.19 [−0.23,−0.15]; h3 −0.22 [−0.27,−0.17]. Per period h3: 2023 −0.13
  [−0.17,−0.07], 2024 −0.26 [−0.33,−0.19], 2025H1 −0.45 [−0.56,−0.34]. h2: −0.17, −0.17, −0.23.
  => effect magnitude GROWS over time 2023 -> 2025H1 (x3.5 at h3). Honest k_mid 0.025, box [0.0085, 0.065]
  (0.07–0.56 ppm/°C). Leaky was 0.035 [0.015, 0.085].
- EVAL with honest k (h3): EVAL1 MAE action 1.033 (leaky 0.995; baseline-only 1.202), EVAL2 1.225 (leaky 1.207; base 1.376);
  coverage action .91 / .85; effect calibration slope EVAL1 2.14 [1.94,2.34], EVAL2 1.86 [1.58,2.18] (leaky 1.70 / 1.50).
  h2: slope honest 1.15 [0.89,1.45] EVAL1, 1.72 [1.31,2.26] EVAL2.
- Reading: leak inflated k towards the later (larger) effect; honest pooled SELECT k under-predicts later realized effect ~2×
  at h3. Realized "effect" metric (y − A_cb on action rows) still contains mean reversion -> F2 must check cleaner estimates.
  Factual MAE almost unchanged by leak fix (±0.04) -> the leak mattered for the COEFFICIENT, not the score.

## F1 dataset (final/out/ds_final.pkl, f1_dataset.json) — 30-min grid
- valid 48 590 (valid_long for h<=8: 47 439). Restarts after stops >5 d: 2024-04-22, 2026-04-27, 2026-07-02.
  cycle_id 0 = data start..2024-04 (age unknown at start), 1 = 2024-04-22..2026-04 (29.7k rows), 2,3 = short 2026 cycles.
- No setpoint (SP) tag among 26 tags -> action reconstructed from PV T11.
- A30 q01..q99 −2.10..+2.30; |A30|>=1 14.7%, >=2 2.8%. Onset (|pre_T|<0.5, |s_jump|<0.5, |s_dev24|<1): 26%;
  onset & |A30|>=1: 2023 166, 2024 161, 2025 119, 2026 54 (30-min rows, clustered).
- Feedback markers: corr(A30, s_dev24) 0.40, corr(A30, s_jump) 0.14 (A60 0.11); inside onset corr(A30,s_jump) 0.02.
- APC gain (14 d past-only slope of 3 h dT on PAK deviation): median 0.65 °C/ppm, q05–q95 0.25–1.28; by quarter
  2023Q1 .45 … 2024Q1 .44, 2024Q4 .83, 2025Q1 .98, 2025Q2 1.01, 2025H2 .75–.80, 2026Q1 .61, Q2 .52, Q3 .38.
  NOTE: SELECT theta magnitude grew 2023->2025H1 together with APC gain -> possible bias link, test in F2(c).
- Delivered move after A30>=1: T path +1.83 at 0.5 h, +1.35 (1 h), +1.30 (3 h), +1.06–1.14 (4–8 h). A step is held ~8 h
  (not reverted). Per-A30 effect must be rescaled by first-stage slope to get per-sustained-°C effect.

## F1 select (final/out/f1_select.json; SELECT n=32 600 rows with all h<=8 valid). theta ppm per unit action [90% CI]
A30 pooled by h: 0.5 −0.52 | 1 −0.37 | 1.5 −0.06 | 2 −0.12 | 3 −0.19 [−0.24,−0.13] | 4 −0.10 | 6 −0.13 | 8 −0.13
A30 ONSET subset: 0.5 −0.25 | 1 −0.08 (∋0) | 1.5 +0.09 | 2 −0.07 | 3 −0.08 [−0.16,0.00] | 4 +0.03 | 6 −0.09 | 8 −0.15 [−0.21,−0.08]
A30 per period h3: 2023 −0.21, 2024 −0.25, 2025H1 −0.13; h8: −0.13, −0.12, −0.19.
A60: h3 pooled −0.20, onset −0.15 [−0.23,−0.08], periods −0.16/−0.27/−0.25; h8 −0.12, onset −0.17, periods −0.11/−0.14/−0.15 (most stable).
First stage (delivered T path per unit A30): 0.5 h 1.15, 1 h 0.78, 3 h 0.66, 8 h 0.53. Per delivered °C: h3 −0.29 (A30), −0.30 (A60);
h6–8 −0.23..−0.25.
R²(A30|state) 0.40, R²(A60|state) 0.41, R²(F30|state) 0.04.
Reading: large 0.5–1 h effect shrinks strongly in onset subset -> mostly feedback/mean reversion of the triggering spike.
Dip at 1.5 h matches T path dip (APC partial pull-back) and ARX shape in s3. Sustained effect h 3–8: −0.10..−0.20 per A30,
≈ −0.16..−0.30 per delivered °C; onset suggests lower end. Magnitude depends on action definition by up to 2× (F0 hourly
2025H1 −0.45 vs here −0.13..−0.25) -> fragile; must be a range.

## F2 closed loop (final/out/f2_closed_loop.json; SELECT only). Effect per DELIVERED sustained °C (theta_A30 / first stage)
- (a) DML pooled: h3 −0.29, h4 −0.16, h6 −0.23, h8 −0.24.
- (b) onset: h3 −0.17 (per A30 −0.08 [−0.16,0.00]), h4 +0.06 (∋0), h6 −0.17, h8 −0.28.
- (c) APC gain terciles (edges 0.58 / 0.81 °C per ppm): LOW gain h3 −0.40 (per A30 −0.29 [−0.37,−0.20]), h6 −0.38, h8 −0.43;
  MID −0.19/−0.15/−0.22; HIGH −0.31/−0.19/−0.15; HIGH&onset ≈ 0. => stronger feedback ATTENUATES apparent effect;
  weakest-feedback windows give the largest effect (−0.3..−0.4). Earlier worry "gain inflates theta" not supported.
- (d) matching: 701 pairs (same cycle, ±3 d, caliper; mean |diff| T 0.67, s_now 0.25, s_jump 0.18): per A30 h3 −0.20
  [−0.26,−0.12], h4 −0.07, h6 −0.09, h8 −0.10; pair first stage low 0.27–0.39 -> per delivered −0.50/−0.22/−0.24/−0.36.
  Up −0.21 vs down −0.18 at h3 (symmetric).
- (e) ARX 10-min SELECT, +1 °C permanent step: 0.5 h −0.16, 1 h −0.20, 1.5 h −0.30, 2 h −0.12, 3 h −0.24 [−0.28,−0.19],
  4 h −0.23, 6 h −0.23, 8 h −0.23, 9 h −0.24 [−0.27,−0.20]. Plateau from 3 h, very stable.
=> Consolidated sustained effect: point ≈ −0.25 ppm/°C, method range ≈ [−0.10, −0.45] (onset lower edge, low-gain/matching
   upper edge). At SELECT mean PAK 8.63: k ≈ 0.029 [0.012, 0.052]. Leaky round-1 box was 0.13–0.71 ppm/°C.

## F3 form & state dependence (final/out/f3_form_state.json; SELECT, OOF 10 blocks, week bootstrap)
- Multiplicative (effect ∝ s_now) vs additive const: OOF loss gain −0.04% [CI ∋ 0] h3, −0.01% h6 -> NO difference.
  Interaction a~×s_now θ1 = +0.007 per SD [−0.034, 0.047]; multiplicative would imply ≈ −0.033 -> no evidence of proportionality.
  Rule (tie -> simpler) => ADDITIVE constant ppm/°C.
- θ(z) for z in {s_now, T_in, T_30d, T_rel30, feed, h2oil, T_d6, apc_gain14d, days_since_restart, s_dev24}: no z improves OOF
  loss (all ≤0 or CI∋0; best feed h6 +0.03% CI∋0). Signs NOT reproducible across cycles: T_in θ1 c0 −0.02 / c1 +0.16,
  T_30d c0 −0.06/−0.14 vs c1 +0.17/+0.13, days_since_restart c0 −0.06/−0.11 vs c1 +0.10/+0.01. feed h6 same sign both cycles
  (+0.05, +0.09) but fails OOF rule. => CONSTANT effect.
- Catalyst stage (θ per A30, h3): cycle0 2023-02..2024-03 (T_30d 367→373): early −0.12, middle −0.28, late −0.31;
  cycle1 2024-05..2025-06 (fresh, T_30d 359/355/360): early −0.29, middle −0.20, late −0.06. Opposite trends -> no reproducible
  dependence on cycle stage. Also 2025H1: −0.06..−0.13 here vs −0.45 in F0 hourly definition -> period-level θ is
  definition-fragile; per-period k is not defensible.

## F4 candidates (final/out/f4_candidates.json), h=3, action A30, learned on FIT, chosen/calibrated on VAL, β from SELECT
- Baseline VAL MAE: persistence 0.976, blend w·s_now+(1−w)·s_24h 0.783 (w from FIT), ridge_min 0.817, cb_min 0.936,
  cb_full 0.835 -> BASELINE = simple blend (ML state-only worse on VAL).
- Realized orthogonal θ per sustained °C (nuisance trained on SELECT, applied out-of-sample): VAL −0.31 [−0.43,−0.20],
  EVAL1 −0.59 [−0.72,−0.46], EVAL2 −0.50 [−0.69,−0.28]. => out-of-time effect ≈ 2× SELECT point −0.25, beyond SELECT range edge −0.45.
- MAE all / quiet / action (|A30|>=1):
  EVAL1: P0 .741/.636/1.341; P1a .729/.638/1.267; P1b .818/.735/1.340; P2 .725/.634/1.222; P3 .725/.634/1.224; P5 .734/.642/1.250
  EVAL2: P0 1.011/.905/1.468; P1a 1.034/.961/1.376; P1b 1.072/1.004/1.388; P2 .999/.902/1.399; P3 1.000/.902/1.400; P5 .998/.920/1.349
- Orthogonal calibration slope (1 = right magnitude): VAL P2 1.24 [0.80,1.70]; EVAL1 P1a 1.82, P1b 2.19, P2 2.35 [1.87,2.92],
  P3 2.59, P5 2.35; EVAL2 P1a 1.79 [0.85,2.42], P1b 2.16, P2 2.01 [1.11,2.69], P3 1.98, P5 2.01. All >0 (sign right), all under-predict.
- Matched pairs (EVAL1 111, EVAL2 69): slope obs/pred P2 1.38 / 2.13, P1a 1.47 / 1.21; sign concordance 0.60–0.68 all models.
- Rows with non-negative local effect (wrong/flat): P1a 2–3%, P1b 1%, P2/P3/P5 0%.
- Coverage with plain VAL radius: all ≈ .92/.84 overall, action rows .72–.76 -> needs action-aware widening.
Rule outcome: P1a fails rule 2 (non-monotone 2–3%) and has no sustained-setpoint semantics; P1b worse MAE and calibration;
P3 = P2 (tie, F3) -> simpler P2; P5 improves action MAE only in EVAL2 (not EVAL1) -> rejected; P4 rejected in F3.
WINNER candidate: P2 additive constant. Honest caveat: SELECT β under-predicts later effect ~2× (safe for benefit, unsafe for harm).

## F5 sanity / uncertainty / support (final/out/f5.json)
- Baseline blend weight w = 0.15 (base = 0.15·PAK_30min + 0.85·PAK_24h): 3 h ahead PAK mostly reverts to daily mean.
- Sanity on 1500 EVAL states, ΔT 0..4: P1a monotone 88.7%, effect/°C median −0.08, saturates fully after +2 (step4/step1 = 0),
  q95 |2nd diff| 0.19; P1b monotone 100% but flat after +2 (saturation 0); P2 monotone 100%, linear −0.25/°C, smooth;
  P3 monotone, effect +2 −0.36..−0.52 (level dependent); P5 == P2 in counterfactual (correction flat in A30).
- Uncertainty P2 (r_VAL 1.72 quiet, r_VAL_action 2.24, coefficient range [−0.10, −0.45]): coverage VAL all .92 / action .92;
  EVAL1 .93 / .88; EVAL2 .86 / .82 (below .85 on action rows in 2026 — consistent with 2× under-predicted effect). Width 3.6 / 4.8.
- Support diagnostic (onset analogs within 0.5 SD, |A30−ΔT|<=0.5; thresholds a priori): EVAL states ΔT=+1: IN 1.6%, LOW 57.6%,
  OUT 40.8%; +2: LOW 1.4%, OUT 98.6%; +3/+4: OUT 100%; −1 similar to +1. SELECT onset moves near |A30|≈1: 1416, ≈2: 90,
  ≈3: 4, ≈4: 1 (all valid rows: 10 806 / 2223 / 434 / 91, but provoked). Error by label on real EVAL moves: IN MAE .76 cov .92;
  LOW .99 / .88; OUT 1.32 / .80 -> label is informative.
- Examples: demo 2026-01-05 08:00 (PAK 5.88, 24h 4.71): base 4.88; ΔT+2 -> 4.38 [1.75, 6.92] OUT; P1a 7.12 -> 6.91 (flat after +2).

## F6 refit on all history (final/out/f6_refit_all.json) — NOT evaluated, for artifact
- DML per delivered °C h3: pooled −0.31 [−0.38,−0.25], onset −0.30; half-years 2023H1 −0.27, 2023H2 −0.31, 2024H1 −0.31,
  2024H2 −0.35, 2025H1 −0.28, 2025H2 −0.73 [−0.84,−0.59], 2026H1 −0.47. h6/h8 pooled −0.15/−0.13 (noisier, CI wide).
- ARX plateau (3–8 h) all data −0.29 [−0.33,−0.25]. ARX BY HALF-YEAR: 2023H1 −0.13, 2023H2 −0.11, 2024H1 −0.20, 2024H2 −0.34,
  2025H1 −0.31, 2025H2 −0.53, 2026H1 −0.65 => magnitude grows ~5× over 3.5 years, monotone except 2025H1. Crosses cycles
  (cycle0 end small, cycle1 growing) -> not a consistent catalyst-stage law (F3), but a time drift (APC tuning? analyser?
  feed?). Explains F4 "2× under-prediction" of SELECT β on EVAL.
- Pre-declared artifact rule result: point −0.29, weak −0.08, strong −0.73.
- NOTE: idea "estimate β on trailing window" arose AFTER seeing this drift -> must be checked by rolling origin, flagged post-hoc.

## F7 rolling origin for β window (final/out/f7_rolling_origin.json) — post-hoc question
Realized next-half ARX vs estimate (ratio realized/est): 2024H1 −0.20: exp 1.41, tr12 1.41, tr6 1.85 | 2024H2 −0.34: 2.19/2.47/1.71 |
2025H1 −0.31: 1.43/1.01/0.90 | 2025H2 −0.53: 2.21/1.57/1.71 | 2026H1 −0.65: 2.44/1.71/1.24.
Mean |log ratio|: expanding 0.64, trailing12 0.45, trailing6 0.40 (eval halves: 0.84 / 0.49 / 0.37).
=> drift persists: next half usually 1.2–2.5× stronger than any past estimate. Recency helps, does not remove it.

## F8 artifact numbers (final/out/f8_artifact.json)
- Post-hoc rule β = ARX plateau on trailing 12 months, range [0.5β, 2.5β]: EVAL1 β −0.335 -> coverage all .94 / action .91,
  MAE action 1.188 (SELECT β −0.25: 1.222); EVAL2 β −0.382 -> .87 / .86, MAE action 1.377 (1.399). Width action ≈ 5.1–5.2.
- Current (window 2025-08-07..2026-08-07): β = −0.59 [−0.64, −0.56] ppm/°C; trailing 6 m −0.67.
  Range 0.5β..2.5β = −0.30..−1.49 -> strong edge capped at −1.0 (expert Q&A 0.3–1 ppm/°C; all half-year data estimates ≤ 0.73).
- Current baseline refit: w 0.20, radius90 2.35 (quiet), 2.35→3.37 with action (last 6 months, n 5573; 2026 more volatile).
FINAL: additive constant-in-state response, β re-estimated on trailing 12 months, 3 h horizon, |ΔT| ≤ 2 °C per step.

# ROUND 3 — spec audit (plan: ~/.claude/plans/temporal-noodling-muffin.md), 2026-09-15
Reference implementation final/response_model.py (prepare, rows, fit, live_state, predict); audit final/f9_audit.py -> out/f9_audit.json.
- Baseline provenance: evaluated w=0.15 chosen on FIT (target < 2025-01-01) by MAE grid 0..1 step .05; blend chosen on VAL 2025H1.
  No EVAL. BUT FINAL doc v1 showed w=0.20 and radii 2.35/3.37 from f8 windows 2025-02..2026-08 (EVAL data = production refit)
  and f8 action radius ignored β·ΔT -> superseded by rolling rule.
- Frozen PAK flag: legacy flat_mask used plateau's future end. Past-only rule: 7.23% vs 7.45% bins frozen, differ 0.23%,
  EVAL baseline MAE change <= 0.0005 -> no recompute needed; past-only adopted.
- `stable` label uses +6 h future: allowed only for training row selection; fit() windows end at τ−6h; live uses run_past12h.
- Rolling fits: τ=2025-07-01: w .10, β −0.348 [−.373,−.315], strong mult 2.64 -> −0.917, weak −0.174, r0 1.69, r1 2.28.
  Next half 2025H2: MAE all .721 (baseline .741), action 1.161; coverage all .937 / quiet .938 / action .920. With w=.15: .720/1.183/.922.
  τ=2026-01-01: w .10, β −0.389 [−.444,−.351], strong −1.0 (cap), weak −0.194, r0 1.48, r1 2.48. Next half 2026H1:
  MAE .998 (base 1.014), action 1.382; coverage .825 / quiet .820 / action .886 (quiet under-covers in 2026).
- Current artifact τ=2026-08-07: w .20, β −0.595 [−0.643,−0.560], strong mult 2.64 -> capped −1.0, weak −0.298, r0 2.15,
  r1 3.19, T11 q01–q99 345.3–383.1, F26 171.0–301.6, onset analog table 12 763 rows; past ratios 1.37, 2.64, 1.02, 1.52, 1.68.
- Envelope zones (artifact at half start): 2025H2 states: ±0.5 A 83–84%, ±1 A 65–67% (rest B), ±1.5/±2 B 99%, C 0.9%.
  2026 states: ±0.5 A 58–63%, ±1 A 37–38%, ±1.5/±2 B 81%, C 19% (18.1% = artifact older than 6 months after 2026-07-01;
  PAK missing/frozen 1.9%, PAK24h coverage 2.0%, T11 range 0.6%).
  Real transitions: A n 1985 MAE .85 cov .97; B n 1443 MAE 1.27 cov .90; C n 464 refused.
- Smoke (τ=2026-01-01, state 2026-01-05 08:00): HOLD 4.82 [3.34,6.31]; +0.5 4.63 [1.84,7.21] A (11 analogs);
  +1 4.43 [1.34,7.11] B (1); +2 4.05 [0.34,6.92] B; +2.5 C; −1 5.21 [2.54,8.30] B (3). Asserts passed.

## FROZEN 2026-09-15
User accepted model + pipeline (RESPONSE_MODEL_FINAL.md v3). No new experiments. No transfer to src until organizers confirm
T11 = reactor inlet temperature and F26 = volumetric feed. Then implement exactly the spec (no changes to math, coefficients rule,
envelope, uncertainty/support rules). Scripts' out/ directories are not committed; regenerate with s1..s7, final/f0..f9.
