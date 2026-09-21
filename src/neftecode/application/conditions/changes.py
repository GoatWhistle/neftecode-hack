import copy

CHANGES = {
    "crude_sulfur_wt_pct": ("crude", "Сера сырья, % масс."),
    "product_sulfur_mgkg": ("product", "Предел серы продукта, мг/кг"),
    "product_t95_c": ("product", "Предел T95, °C"),
    "product_cetane_number": ("product", "Минимум цетанового числа"),
    "tank_inventory": ("tanks", "Запас резервуара, т"),
    "tank_available": ("tanks", "Доступность резервуара"),
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
    elif change == "throughput_tph":
        out["current_operation"]["throughput"]["value"] = value
    return out


def apply_changes(raw: dict, changes) -> dict:
    out = copy.deepcopy(raw)
    for change in changes:
        out = apply_change(out, change["change"], change.get("value"), change.get("target"))
    return out
