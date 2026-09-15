"""Prototype of the recommended response layer (verdict C, hybrid). Ready to move to src after review.

g(real_state, action) -> sulfur after HT at horizon h, with interval and support label.

    sulfur(action, h) = baseline(state, h) * ratio(action, h)
    ratio = exp(-k * dT) * (F_new / F_now) ** n        (structure of the scenario HT model)

* baseline — existing state-only forecast (no action variables): the data showed action variables add no stable
  predictive value (s5), so the forecast stays the only ML fitted to the target.
* k, n — NOT free ML parameters: a box [lo, hi] consistent with data (s3 ARX, s6 double ML by year, LIMS check) and
  the expert's 0.3–1 ppm/°C. Central values are used only for display and ranking; the gate uses the box edge that is
  worst for the candidate.
* lag — asymmetric: a HARMFUL move counts from t=0, a BENEFICIAL move is credited only from `benefit_lag_h`
  (effect starts within 1 h but its dead time is not identifiable under APC feedback).
* support — SUPPORTED / LOW_SUPPORT / UNSUPPORTED from historical analog transitions (SupportGate).
"""
from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd

SUPPORTED, LOW_SUPPORT, UNSUPPORTED = "SUPPORTED", "LOW_SUPPORT", "UNSUPPORTED"


@dataclass(frozen=True)
class EffectBox:
    k_lo: float = 0.015     # 1/°C : ≈0.13 ppm/°C at 8.4 ppm (2023 estimates)
    k_mid: float = 0.035    # pooled double-ML ≈0.29 ppm/°C
    k_hi: float = 0.085     # 2026 unprovoked ≈0.70 ppm/°C; equals current scenario value
    n_lo: float = 0.4       # feed elasticity, 2023 h2
    n_mid: float = 1.0      # pooled h2
    n_hi: float = 3.0       # 2026 / LIMS check
    benefit_lag_h: float = 2.0
    harm_lag_h: float = 0.0


@dataclass
class HybridResponse:
    box: EffectBox = field(default_factory=EffectBox)

    def ratio(self, dT: float, feed_rel: float, h: float) -> dict:
        """Multiplicative effect vs HOLD at horizon h: mid, and worst/best edges of the box."""
        if feed_rel <= -1:
            raise ValueError("feed change below -100%")
        b = self.box
        edges = []
        for k in (b.k_lo, b.k_hi):
            for n in (b.n_lo, b.n_hi):
                edges.append(self._r(dT, feed_rel, k, n, h))
        mid = self._r(dT, feed_rel, b.k_mid, b.n_mid, h)
        return {"mid": mid, "lo": min(edges + [mid]), "hi": max(edges + [mid])}

    def _r(self, dT, feed_rel, k, n, h):
        # Each component is credited only after its lag: harm immediately, benefit after benefit_lag_h.
        rT = math.exp(-k * dT)
        rF = (1 + feed_rel) ** n
        out = 1.0
        for r in (rT, rF):
            lag = self.box.harm_lag_h if r > 1 else self.box.benefit_lag_h
            out *= r if h + 1e-9 >= lag else 1.0
        return out

    def predict(self, base_mid: float, base_lo: float, base_hi: float, dT: float, feed_rel: float, h: float) -> dict:
        r = self.ratio(dT, feed_rel, h)
        return {"mid": base_mid * r["mid"], "lower": base_lo * r["lo"], "upper": base_hi * r["hi"],
                "effect_vs_hold_mid": base_mid * (r["mid"] - 1),
                "effect_vs_hold_range": [base_mid * (r["lo"] - 1), base_mid * (r["hi"] - 1)]}


@dataclass
class SupportGate:
    """Label (state, action) by how many similar historical SUSTAINED transitions exist before decision time.

    State space (standardized): T_in (catalyst/temperature regime), feed, h2oil. Sulfur level is not used: the effect is
    multiplicative and scale-free. A transition is an analog when its state is within `radius` and the move sustained
    over the next 3 h (aT_path3, aF_path3) has the same direction and similar size (tolerance max(abs_tol, 35% of move)).
    Hard checks: resulting setpoints inside [q0.5, q99.5] of stable history; hourly step within q99.5 of hourly moves.
    HOLD needs no response model and is always SUPPORTED here (the baseline forecast has its own trust checks).
    """

    history: pd.DataFrame            # STATE_COLS + a_T_in, a_feed_rel, aT_path3, aF_path3; only data before decision
    min_supported: int = 30
    min_low: int = 10
    min_days_supported: int = 5
    min_days_low: int = 3
    radius: float | None = None

    STATE_COLS = ("T_in", "feed", "h2oil")

    def __post_init__(self):
        need = list(self.STATE_COLS) + ["a_T_in", "a_feed_rel", "aT_path3", "aF_path3"]
        H = self.history.dropna(subset=need)
        self.H = H
        self.mu = H[list(self.STATE_COLS)].mean()
        self.sd = H[list(self.STATE_COLS)].std()
        self.Z = ((H[list(self.STATE_COLS)] - self.mu) / self.sd).to_numpy()
        self.mT = H.aT_path3.to_numpy()
        self.mF = H.aF_path3.to_numpy()
        self.day = H.index.floor("D").to_numpy()
        q = lambda s, a: float(np.nanquantile(s, a))
        self.T_range = (q(H.T_in, .005), q(H.T_in, .995))
        self.F_range = (q(H.feed, .005), q(H.feed, .995))
        self.aT_max = q(H.a_T_in.abs(), .995)
        self.aF_max = q(H.a_feed_rel.abs(), .995)
        if self.radius is None:
            rng = np.random.default_rng(0)
            sample = self.Z[rng.choice(len(self.Z), min(400, len(self.Z)), replace=False)]
            dist = np.sqrt(((sample[:, None, :] - self.Z[None, :, :]) ** 2).sum(-1))
            self.radius = float(np.median(np.sort(dist, axis=1)[:, 200]))

    def assess(self, state: dict, dT: float, feed_rel: float) -> dict:
        if abs(dT) < 1e-9 and abs(feed_rel) < 1e-9:
            return {"label": SUPPORTED, "analogs": None, "analog_days": None, "reasons": ["HOLD: no response model used"]}
        reasons = []
        T_new, F_new = state["T_in"] + dT, state["feed"] * (1 + feed_rel)
        if not self.T_range[0] <= T_new <= self.T_range[1]:
            reasons.append(f"T after move {T_new:.1f} outside history [{self.T_range[0]:.1f}, {self.T_range[1]:.1f}]")
        if not self.F_range[0] <= F_new <= self.F_range[1]:
            reasons.append(f"feed after move {F_new:.0f} outside history [{self.F_range[0]:.0f}, {self.F_range[1]:.0f}]")
        if abs(dT) > self.aT_max:
            reasons.append(f"|dT| {abs(dT):.1f} > hourly q99.5 {self.aT_max:.1f} °C: split into steps")
        if abs(feed_rel) > self.aF_max:
            reasons.append(f"|dF| {abs(feed_rel):.1%} > hourly q99.5 {self.aF_max:.1%}")
        z = np.array([(state[c] - self.mu[c]) / self.sd[c] for c in self.STATE_COLS])
        near = np.sqrt(((self.Z - z) ** 2).sum(1)) <= self.radius

        def similar(hist, a, abs_tol, still):
            if abs(a) < still:
                return np.abs(hist) < still
            return (np.sign(hist) == np.sign(a)) & (np.abs(hist - a) <= max(abs_tol, 0.35 * abs(a)))

        match = near & similar(self.mT, dT, 0.5, 0.5) & similar(self.mF, feed_rel, 0.01, 0.01)
        n = int(match.sum())
        days = int(len(np.unique(self.day[match]))) if n else 0
        if reasons or n < self.min_low or days < self.min_days_low:
            label = UNSUPPORTED
        elif n < self.min_supported or days < self.min_days_supported:
            label = LOW_SUPPORT
        else:
            label = SUPPORTED
        return {"label": label, "analogs": n, "analog_days": days, "state_neighbours": int(near.sum()), "reasons": reasons}
