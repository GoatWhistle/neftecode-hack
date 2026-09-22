import copy

CHANGES = {
    "crude_sulfur_wt_pct": ("crude", "Сера сырья, % масс."),
    "product_sulfur_mgkg": ("product", "Предел серы продукта, мг/кг"),
    "product_t95_c": ("product", "Предел T95, °C"),
    "product_cetane_number": ("product", "Минимум цетанового числа"),
    "tank_inventory": ("tanks", "Запас резервуара, т"),
    "tank_available": ("tanks", "Доступность резервуара"),
    "tank_park_phase_fraction": ("tank_park", "Фаза налива парка, доля длительности"),
    "throughput_tph": ("current_operation", "Текущий выпуск, т/ч"),
    "source_failure": ("state", "Исправность источников данных"),
}


class ConditionsError(ValueError):
    pass


def apply_change(raw: dict, change: str, value, target: str | None = None) -> dict:
    if change not in CHANGES:
        raise ConditionsError(f"Демонстрация не умеет менять «{change}». "
                              f"Доступно: {', '.join(sorted(CHANGES))}")
    out = copy.deepcopy(raw)
    if change == "crude_sulfur_wt_pct":
        out["crude"]["sulfur_wt_pct"]["value"] = value
    elif change.startswith("product_"):
        key = change[len("product_"):]
        if out["product"].get(key) is None:
            raise ConditionsError(f"Показатель {key} в сценарии не задан, менять нечего")
        out["product"][key]["value"] = value
    elif change in ("tank_inventory", "tank_available"):
        if not target:
            raise ConditionsError(f"{change}: нужно указать резервуар")
        for tank in out["tanks"]:
            if tank["tank_id"] == target:
                if change == "tank_inventory":
                    if tank.get("on_demand"):
                        raise ConditionsError(f"{target}: компонент производится по необходимости, запаса у него нет")
                    tank["inventory"]["value"] = value
                else:
                    tank["available"] = bool(value)
                    tank["note"] = ("Недоступность резервуара — инъекция условий демонстрации, "
                                    "а не наблюдение из данных.")
                break
        else:
            raise ConditionsError(f"Резервуар {target} не описан в сценарии")
    elif change == "tank_park_phase_fraction":
        park = out.get("tank_park")
        if not isinstance(park, dict):
            raise ConditionsError("Парк резервуаров в сценарии не описан")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value < 1:
            raise ConditionsError("Фаза налива должна быть долей от 0 включительно до 1 исключительно")
        component = park.get("component_tank_id")
        tank = next((item for item in out.get("tanks", ()) if item.get("tank_id") == component), None)
        if tank is None:
            raise ConditionsError("Компонент парка отсутствует в tanks")
        inflow = ((tank.get("inflow") or {}).get("value"))
        capacity_t = park.get("capacity_m3", 0) * park.get("density_kgm3", 0) / 1000.0
        if not isinstance(inflow, (int, float)) or inflow <= 0 or capacity_t <= 0:
            raise ConditionsError("Для изменения фазы нужны положительные вместимость и приток")
        fill_h = capacity_t / inflow
        tau = float(value) * fill_h
        count = int(park.get("tank_count", 0))
        cycle_h = count * fill_h
        park["phase_offsets_h"] = [round((tau + index * fill_h) % cycle_h, 9)
                                   for index in range(count)]
        park["source"] = "derived"
    elif change == "throughput_tph":
        out["current_operation"]["throughput"]["value"] = value
    return out


def apply_changes(raw: dict, changes) -> dict:
    out = copy.deepcopy(raw)
    for change in changes:
        out = apply_change(out, change["change"], change.get("value"), change.get("target"))
    return out
