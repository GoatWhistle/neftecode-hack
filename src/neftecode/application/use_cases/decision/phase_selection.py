from dataclasses import replace

from neftecode.domain.advisory.optimizer import rank
from neftecode.domain.advisory.response_guard import moves_temperature, weak_response_raw
from neftecode.application.services.park_phase_bounds import certify_phase_interval


class PhaseSelectionMixin:
    def _phase_certificate(self, plan, raw, confirmed, initial_tanks, current_operation):
        certificate = certify_phase_interval(self.scenario, plan, confirmed, initial_tanks, current_operation)
        scenarios = []
        pending = self.planner.confirmed_with_operation(confirmed, current_operation)
        if moves_temperature(plan, self.planner.base_controls(), pending):
            weak = weak_response_raw(raw)
            if weak is not None:
                scenarios.append(("слабый отклик", self.scenario_parser(weak)))
        if self.robustness_evaluator is not None:
            variants = getattr(self.robustness_evaluator, "phase_interval_scenarios", None)
            if not callable(variants):
                certificate["reasons"].append("Обязательные стрессы не предоставили непрерывную проверку фаз")
                certificate["complete"] = False
            else:
                scenarios.extend(variants(self.scenario, raw, plan, confirmed, current_operation))
        certificate["stress_checks"] = []
        for name, scenario in scenarios:
            check = certify_phase_interval(scenario, plan, confirmed, initial_tanks, current_operation)
            certificate["stress_checks"].append({"name": name, **check})
            if not check["complete"]:
                certificate["complete"] = False
                certificate["reasons"].extend(f"{name}: {reason}" for reason in check["reasons"])
        return certificate

    def _tank_evaluator(self, raw_scenario):
        if self.tank_estimate_evaluator is not None:
            return self.tank_estimate_evaluator
        if self.tank_estimate_factory is None or self.scenario_parser is None or raw_scenario is None:
            return None
        return self.tank_estimate_factory(self.scenario, raw_scenario, self.scenario_parser)

    def _phase_pool(self, selected, feasible, by_id, raw, confirmed, initial_tanks, current_operation):
        evaluator = self._tank_evaluator(raw)
        evaluate = getattr(evaluator, "evaluate_candidates", None)
        if not callable(evaluate):
            return selected, feasible, by_id, None

        def validate(scenario, phase_raw, plan):
            maker = replace(self, scenario=scenario, tank_estimate_evaluator=None, tank_estimate_factory=None)
            evaluation = maker._evaluate_plan(plan, confirmed, initial_tanks, current_operation)
            review = maker._review(evaluation)
            reasons = list(evaluation.gate.rejection_reasons())
            if not maker._review_passes(review):
                reasons += [text for item in review.values()
                            for text in (*item.get("vetoes", ()), *item.get("unknown", ()))]
            passed = evaluation.feasible and maker._review_passes(review)
            if passed:
                lookahead = None
                policy = scenario.policy or {}
                hours, window = policy.get("lookahead_hours"), policy.get("min_reaction_hours")
                pending = maker.planner.confirmed_with_operation(confirmed, current_operation)
                if hours and window and moves_temperature(plan, maker.planner.base_controls(), pending):
                    lookahead = {"available": True, "lookahead_hours": hours, "min_reaction_hours": window,
                                 "selected": maker.planner.lookahead(
                                     plan, hours, confirmed, initial_tanks, current_operation)}
                guard = maker._weak_response_guard(
                    plan, confirmed, phase_raw, initial_tanks, current_operation, lookahead)
                if guard is not None and guard["outcome"] == "violated":
                    passed = False
                    reasons += guard.get("violations", [])
            if passed and self.robustness_evaluator is not None:
                check = getattr(self.robustness_evaluator, "evaluate_mandatory", self.robustness_evaluator.evaluate)
                robustness = check(
                    scenario, phase_raw, plan, confirmed, initial_tanks, current_operation)
                if robustness.get("mandatory_failed", 0):
                    passed = False
                    reasons += robustness.get("mandatory_failure_names", [])
            return {"feasible": passed, "outcome": "same" if passed else "changed",
                    "reasons": reasons[:5], "production_t": evaluation.production_t,
                    "cost_per_tonne": evaluation.cost_per_tonne}

        # feasible/by_id уже ограничены вето и условиями агентов; новый поиск их обошёл бы.
        permitted = {e.candidate.candidate_id for e in feasible}
        report = evaluate({cid: plan for cid, plan in by_id.items() if cid in permitted}, validate,
                          lambda plan: self._phase_certificate(plan, raw, confirmed, initial_tanks, current_operation))
        if report is None:
            return selected, feasible, by_id, None
        allowed = set(report["allowed_ids"])
        common = [e for e in feasible if e.candidate.candidate_id in allowed]
        plans = {cid: plan for cid, plan in by_id.items() if cid in allowed}
        ranked = rank(common, hold_id="hold", min_useful_gain=self._min_useful_gain(),
                      severity_cost_tolerance_fraction=self._severity_cost_tolerance(),
                      max_severity_index=self._max_severity_index())
        report["baseline"] = selected["selected"]
        report["examined"] = len(permitted)
        return ranked, common, plans, report

    def _phase_report(self, report, selected, status):
        baseline = report["baseline"]
        plan_id = selected.get("candidate_id") if selected else None
        baseline_id = baseline["candidate_id"]
        results = report["checks"].get(plan_id or baseline_id, [])
        failed = sorted(set(report["unavailable_taus_h"]) | {r["tau_h"] for r in results if not r["feasible"]})
        changed = plan_id is not None and plan_id != baseline_id
        compromise = None
        if selected is not None:
            production_loss = baseline["production_t"] - selected["production_t"]
            old_cost, new_cost = baseline.get("cost_per_tonne"), selected.get("cost_per_tonne")
            compromise = {"baseline_plan": baseline_id, "selected_plan": plan_id,
                          "baseline_production_t": baseline["production_t"],
                          "selected_production_t": selected["production_t"],
                          "production_loss_t": production_loss,
                          "cost_per_tonne_delta": new_cost - old_cost
                          if new_cost is not None and old_cost is not None else None,
                          "basis": "Сравнение с выбором при исходной модельной фазе; не измеренная потеря завода."}
            verdict = "Выбранный план подтверждён на всём непрерывном интервале фаз парка."
            if changed:
                verdict += (f" Из-за неизвестной стадии резервуаров выпуск за {self.scenario.horizon.hours:g} ч: "
                            f"{baseline['production_t']:g} → {selected['production_t']:g} т")
                if compromise["cost_per_tonne_delta"] is not None:
                    verdict += f"; изменение условной стоимости {compromise['cost_per_tonne_delta']:+.4g} у.е./т"
                verdict += "."
        else:
            verdict = ("Среди рассмотренных планов нет общего варианта, прошедшего проверки во всех "
                       "возможных фазах парка; нужен фактический уровень резервуаров.")
            unproved = report.get("coverage", {}).get(baseline_id, {})
            if unproved.get("reasons"):
                verdict += " Непрерывная проверка: " + "; ".join(unproved["reasons"])
            if report["errors"]:
                verdict += " Проверка фаз не выполнена: " + "; ".join(report["errors"])
        return {"mode": "park_phase", "available": not report["errors"] and bool(results)
                and all(r["outcome"] != "not_evaluable" for r in results), "sensitive": selected is None,
                "tank_id": self.scenario.tank_park.component_tank_id,
                "baseline_plan": baseline_id,
                "baseline_status": "hold" if baseline.get("changes") == 0 else "recommend_scenario",
                "selected_plan": plan_id, "selected_status": status,
                "selection_changed": changed, "common_candidates": len(report["allowed_ids"]),
                "candidates_examined": report["examined"], "compromise": compromise,
                "taus_h": report["taus_h"], "failed_taus_h": failed,
                "errors": report["errors"], "unavailable_taus_h": report["unavailable_taus_h"],
                "fill_duration_h": report.get("fill_duration_h"),
                "perturbations_declared": len(report["taus_h"]),
                "perturbations_evaluated": sum(r["outcome"] != "not_evaluable" for r in results),
                "same": sum(r["feasible"] for r in results), "changed": len(failed),
                "results": results, "verdict": verdict,
                "coverage": report.get("coverage", {}).get(plan_id or baseline_id),
                "excluded_plan_ids": [cid for cid in report["checks"] if cid not in report["allowed_ids"]],
                "excluded_candidates": [
                    {"plan_id": cid, "failed_phases": [r for r in rows if not r["feasible"]],
                     "coverage": report.get("coverage", {}).get(cid)}
                    for cid, rows in report["checks"].items() if cid not in report["allowed_ids"]][:20],
                "limits": ["Фактические стадии неизвестны; τ покрывает весь интервал [0, время налива). "
                           "Стадии остальных резервуаров связаны периодическим расписанием модели.",
                           "Непрерывные границы по τ дополняют Gate на временной сетке горизонта решения; "
                           "три прямых прогона являются диагностикой, а не доказательством покрытия.",
                           "Условия доказательства достаточные: неподтверждённый план не обязательно невозможен. "
                           "Проверка не является разрешением товарного выпуска.",
                           "Поиск общего плана ограничен исследованным пулом и сохраняет запреты агентов."]}
