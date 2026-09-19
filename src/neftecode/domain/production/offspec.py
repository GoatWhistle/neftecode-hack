import math

from neftecode.domain.production.scenario import Scenario

OFFSPEC_SHARE_KEY = "offspec_rework_cost_share"

OFFSPEC_NOTE = ("Справочная величина: доля некондиции по ответу организаторов 18.09 и разница "
                "стоимости с сохранением режима. На допустимость плана не влияет — её решает "
                "проверка пределов продукта.")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def main_tank_stock_t(scenario: Scenario, initial_tanks=None) -> tuple[str | None, float | None, float | None]:
    tanks = scenario.available_tanks() or list(scenario.tanks)
    if not tanks:
        return None, None, None
    main = tanks[0]
    stock = main.inventory.value
    if initial_tanks is not None:
        state = initial_tanks.get(main.tank_id)
        if state is not None and _finite(getattr(state, "inventory_t", None)):
            stock = state.inventory_t
    price = main.cost_per_t.value
    return main.tank_id, (stock if _finite(stock) else None), (price if _finite(price) else None)


def offspec_block(scenario: Scenario, hold_cost_per_tonne, plan_cost_per_tonne,
                  production_t, initial_tanks=None) -> dict:
    economics = scenario.economics or {}
    share_q = economics.get(OFFSPEC_SHARE_KEY)
    if share_q is None:
        return {"available": False,
                "reason": f"В economics сценария нет {OFFSPEC_SHARE_KEY}: стоимость некондиции не считается",
                "affects_admissibility": False, "note": OFFSPEC_NOTE}
    share = share_q.value
    tank_id, stock_t, price_per_t = main_tank_stock_t(scenario, initial_tanks)
    rework_cost = (share * price_per_t * stock_t
                   if all(_finite(v) for v in (share, price_per_t, stock_t)) else None)
    delta = (plan_cost_per_tonne - hold_cost_per_tonne
             if _finite(plan_cost_per_tonne) and _finite(hold_cost_per_tonne) else None)
    plan_extra_cost = (delta * production_t if _finite(delta) and _finite(production_t) else None)
    return {
        "available": True,
        "share": share,
        "share_source": share_q.source,
        "main_tank": tank_id,
        "main_stock_t": stock_t,
        "main_price_per_t": price_per_t,
        "rework_cost": rework_cost,
        "hold_cost_per_tonne": hold_cost_per_tonne if _finite(hold_cost_per_tonne) else None,
        "plan_cost_per_tonne": plan_cost_per_tonne if _finite(plan_cost_per_tonne) else None,
        "delta_cost_per_tonne": delta,
        "production_t": production_t if _finite(production_t) else None,
        "plan_extra_cost": plan_extra_cost,
        "affects_admissibility": False,
        "note": OFFSPEC_NOTE,
    }
