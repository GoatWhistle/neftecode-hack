from neftecode.application.services.trust import DataTrustAgent

from .session_support import SessionError, finite, rounded


class SessionContextMixin:

    def base_controls(self) -> dict:
        base = self.maker.planner.base_controls()
        if self.current_operation is not None:
            base.update(self.current_operation["controls"])
        return base

    def current_recipe(self) -> tuple[dict, float, float]:
        if self.current_operation is not None:
            return (dict(self.current_operation["recipe"]), self.current_operation["throughput_tph"],
                    self.current_operation.get("additive_dose", 0.0))
        operation = self.scenario.current_operation
        return dict(operation.recipe), operation.throughput.value, 0.0

    def data_trust(self) -> dict:
        if not self.state:
            return {"state_provided": False, "note": "Сценарный запуск без измерений: доверие к данным не оценивалось"}
        report = DataTrustAgent(self.trust_cfg or {}).assess(self.state)
        return {"state_provided": True, "usable": report.usable, "primary": report.primary,
                "fallback_mode": report.fallback_mode, "telemetry_missing_fraction": report.telemetry_missing_fraction,
                "sources": {name: {"usable": v.usable, "status": v.status, "age_hours": rounded(v.age_hours, 2),
                                   "max_age_hours": v.max_age_hours, "reasons": [r[:120] for r in v.reasons][:3]}
                            for name, v in report.sources.items()},
                "reasons": [r[:160] for r in report.reasons][:4]}

    def forecast(self) -> dict:
        main = next((t for t in self.scenario.tanks if t.tank_id == "main" or t.sulfur_from_chain),
                    self.scenario.tanks[0])
        prop = main.properties.get("sulfur_mgkg")
        out = {"main_tank": main.tank_id,
               "inflow_sulfur_source": ("bound_forecast_upper" if main.inflow_sulfur is not None else
                                        "chain_model" if main.sulfur_from_chain else "scenario_value"),
               "inflow_sulfur_mgkg": main.inflow_sulfur.value if main.inflow_sulfur is not None else None,
               "tank_sulfur_mgkg": prop.value if prop is not None else None,
               "tank_sulfur_source": prop.source if prop is not None else None}
        live = (self.live_context or {}).get("forecast")
        if isinstance(live, dict):
            out["live_forecast"] = {k: live.get(k) for k in ("model", "value", "lower", "upper", "available")}
            out["live_forecast"]["reason"] = str(live.get("reason") or "")[:160]
        return out

    def measurements(self) -> dict:
        binding = (self.live_context or {}).get("binding")
        if not isinstance(binding, dict):
            return {"live": False, "note": "Сценарный запуск: измерений на момент решения нет"}
        tags = ((binding.get("measurement_binding") or {}).get("tags") or {})
        model = binding.get("response_model") or {}
        return {"live": True, "at": (self.live_context or {}).get("at"),
                "tags": {tag: (None if not isinstance(v, dict) else
                               {"value": rounded(v.get("value")), "age_min": v.get("age_min")})
                         for tag, v in tags.items()},
                "controls": binding.get("controls"),
                "response_model": {k: model.get(k) for k in ("provenance", "beta_mgkg_per_c", "beta_ci",
                                                             "weak_strong", "reference_temp_c", "envelope_dt_c")},
                "tank_inflow": binding.get("tank_inflow"),
                "tank_level_window_hours": binding.get("tank_level_window_hours"),
                "notes": list((binding.get("measurement_binding") or {}).get("notes") or [])[:4],
                "warnings": [str(w)[:300] for w in (binding.get("measurement_binding") or {}).get("warnings") or []][:3]}

    def limits(self) -> dict:
        out = {limit_id: ({"value": q.value, "unit": q.unit, "source": q.source} if q is not None else None)
               for limit_id, q in self.scenario.product.limits.items()}
        margin = (self.scenario.policy or {}).get("sulfur_operating_margin_mgkg")
        if finite(margin):
            out["sulfur_operating_margin_mgkg"] = {"value": margin, "unit": "мг/кг",
                                                   "source": "практика установки, Q&A 15.09 (1–2 ppm)"}
        return out

    def operating_state(self) -> dict:
        base = self.base_controls()
        recipe, throughput, dose = self.current_recipe()
        controls = {}
        for stage_id, stage in self.scenario.stages.items():
            for name, spec in stage.controls.items():
                actuation = spec.get("actuation")
                controls[name] = {"stage": stage_id, "current": base.get(name), "min": spec["min"].value,
                                  "max": spec["max"].value, "step": spec["step"].value if spec.get("step") else None,
                                  "actuation": getattr(actuation, "kind", None)}
        return {"controls": controls, "recipe": recipe, "throughput_tph": throughput, "additive_dose": dose,
                "tanks": {t.tank_id: {"available": t.available, "inventory_t": t.inventory.value,
                                      "max_outflow_tph": t.max_outflow.value} for t in self.scenario.tanks},
                "confirmed_actions": [{"applied_at_hours": at, "controls": dict(c)} for at, c in self.confirmed][:5],
                "max_additive_dose": self.scenario.additive.max_dose_fraction.value if self.scenario.additive else None}

    def legacy_summary(self) -> dict:
        refusal = self.legacy.get("refusal") or {}
        lookahead = self.legacy.get("lookahead") or {}
        robustness = self.legacy.get("robustness") or {}
        return {"status": self.legacy.get("status"), "selected": self.legacy_plan_id,
                "reason": str(self.legacy.get("reason") or "")[:300], "refusal_kind": refusal.get("kind"),
                "lookahead_warning": (lookahead.get("warning") or None) and str(lookahead["warning"])[:200],
                "fragile": robustness.get("fragile")}

    def search_summary(self) -> dict:
        return {"evaluated": self.evaluated, "evaluation_budget": self.evaluation_budget,
                "feasible": len(self.feasible_ids()), "allowed": len(self.allowed_ids()),
                "rounds": len(self.outcome.rounds),
                "constraints_active": [c.to_dict() for c in self.constraints]}

    def response_effect_for(self, delta_t_c: float) -> dict:
        if not finite(delta_t_c) or abs(delta_t_c) > 2.0:
            raise SessionError("delta_t_c_out_of_range: допустимо [-2, 2] °C")
        data_model = (dict(self.response_effect.effect(self.live_context or {}, delta_t_c))
                      if self.response_effect is not None else
                      {"available": False, "reason": "адаптер эффекта отклика не подключён"})
        name = "ht_reactor_inlet_temp_c"
        base = self.base_controls()
        scenario_model = {"available": False, "reason": "нет оценённого кандидата с таким шагом температуры"}
        hold = self.evaluations.get("hold")
        if name in base and hold is not None:
            recipe, throughput, _ = self.current_recipe()
            for cid, plan in self.plans.items():
                step = plan.steps[0]
                if (len(plan.steps) == 1 and abs(step.controls.get(name, base[name]) - base[name] - delta_t_c) < 1e-6
                        and all(abs(step.controls.get(k, v) - v) < 1e-9 for k, v in base.items() if k != name)
                        and all(abs(step.recipe.get(k, 0.0) - recipe.get(k, 0.0)) < 1e-9 for k in set(step.recipe) | set(recipe))
                        and abs(step.throughput_tph - throughput) < 1e-9 and step.additive_dose == 0):
                    moved = self.quality_margins(cid)["sulfur_mgkg"].get("min_margin")
                    held = self.quality_margins("hold")["sulfur_mgkg"].get("min_margin")
                    if finite(moved) and finite(held):
                        scenario_model = {"available": True, "candidate_id": cid,
                                          "sulfur_margin_change_mgkg": rounded(moved - held),
                                          "note": "Сценарная модель цепочки за горизонт 3 ч, не модель по данным"}
                    break
        return {"delta_t_c": delta_t_c, "data_model": data_model, "scenario_model": scenario_model}
