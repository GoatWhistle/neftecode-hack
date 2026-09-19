import json

def selection_section(summary):
    lines = []
    choice = summary.get("selection_decision", {})
    if choice:
        lines += ["## Аудит прежнего validation-правила", "",
                  f"Базовый простой прогноз — **{choice['baseline']}**, ошибка {choice['baseline_mae']:.4f}."]
        if choice.get("challenger"):
            lines += [f"Лучший обучаемый претендент — **{choice['challenger']}**, ошибка "
                      f"{choice['challenger_mae']:.4f}: выигрыш {choice['relative_gain']:.2%} при "
                      f"доверительном интервале разности "
                      f"[{choice['bootstrap']['ci_low']:.4f}, {choice['bootstrap']['ci_high']:.4f}]."]
        lines += [choice["reason"] + ".", "",
                  f"Сложная модель заменяет простую только при выигрыше не меньше "
                  f"{choice['min_relative_gain']:.0%} и доверительном интервале разности, не накрывающем ноль. "
                  "Сравнение парное, на одних и тех же анализах: иначе доступность прогноза выдавала бы "
                  "себя за точность.", ""]
    production = summary.get("production_selection")
    if production:
        lines += ["## Production-выбор до финального теста", "",
                  f"Основной прогноз — **{production['selected']}**. Он выбран по заранее "
                  f"зарегистрированной скользящей проверке, завершённой до "
                  f"{production['development_end']}; фиксированный validation-выбор выше сохранён как аудит, "
                  "но не переопределяет rolling-решение.", ""]
    availability = summary.get("quality_availability")
    if availability:
        lines += ["## Что система может оценить", "",
                  "| Показатель | Лабораторных анализов | Способ оценки |", "|---|---:|---|"]
        for name, source in availability["sources"].items():
            lines.append(f"| {name} | {source['n_analyses']} | {source['method']} |")
        lines += ["", "Обученная модель заявляется только при достаточном числе анализов. Показатель "
                  "без модели берёт значение из сценария с пометкой допущения либо остаётся неизвестным; "
                  "неизвестное критическое свойство блокирует план, а не проходит проверку.", ""]
    for name, result in (summary.get("extra_targets") or {}).items():
        decision = result.get("selection_decision")
        if not decision:
            lines += [f"Прогноз {name} не построен: {result.get('reason')}", ""]
            continue
        lines += [f"## Прогноз {name}", "",
                  f"Выбран **{decision['selected']}**. {decision['reason']}.", "",
                  "| Метод | MAE на общем validation | MAE на тесте | Анализов с прогнозом |",
                  "|---|---:|---:|---:|"]
        for method, values in result["models"].items():
            t = values["test"]
            lines.append(f"| {method} | {values['validation_common_mae']:.3f} | "
                         f"{t.get('mae', 0):.3f} | {t['predicted']}/{t['n']} |")
        lines += ["", "Простой прогноз здесь — последнее доступное лабораторное значение того же "
                  "показателя, а не показание анализатора серы: сравнение с посторонней величиной "
                  "создало бы заведомо слабого соперника и завысило бы выигрыш модели.", ""]
    return lines

def make_report(out, demos):
    lines = ["# Первый рабочий проход", "", "Прогноз на реальных данных. Оптимизация смешения — явно модельный сценарий.", ""]
    if (out / "metrics.json").exists():
        summary = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        selection_text = (f"Production-выбор по rolling до 2026: **{summary['selected']}**."
                          if summary.get("production_selection") else
                          f"Выбор только по validation: **{summary['selected']}**.")
        lines += [selection_text + " Тест — 2026 год.", "",
                  "| Метод | Анализов с прогнозом | MAE, мг/кг | MAE на общих анализах | Найдено превышений точечным прогнозом | Покрытие диапазона |",
                  "|---|---:|---:|---:|---:|---:|"]
        for name, result in summary["models"].items():
            m = result["test"]
            common_mae = result["test_common"].get("mae", float("nan"))
            recall = f"{m['recall']:.1%}" if m.get("recall") is not None else "—"
            lines.append(f"| {name} | {m['predicted']}/{m['n']} | {m.get('mae', 0):.2f} | {common_mae:.2f} | {recall} | {m.get('interval_coverage', 0):.1%} |")
        lines += ["", "MAE — средняя абсолютная ошибка. Последнее измерение может отсутствовать: сравнивайте также доступность. "
                  "Подробные пропуски превышений и ложные тревоги — в metrics.json. Предел 10 здесь — ориентир риска после гидроочистки, не заключение о товарном ДТ.",
                  "", "Заявленная цель покрытия диапазона — 90%. Сравните с фактическим покрытием выше. "
                  "Маленькая средняя ошибка при низкой доле найденных превышений не означает хороший контроль риска. "
                  "Верхняя граница повышает обнаружение, но может давать много ложных тревог. Эти модели еще требуют доработки.",
                  "", "Результаты воспроизведения всех тестовых моментов с модельным смешением: " + str(summary["replay"]["statuses"]), ""]
        lines += selection_section(summary)
        lines += ["## Допущения", "", *[f"- {a}" for a in summary["assumptions"]], ""]
    if (out / "risk_metrics.json").exists():
        risk = json.loads((out / "risk_metrics.json").read_text(encoding="utf-8"))
        lines += ["## Обнаружение превышений", "",
                  f"Выбран по validation: **{risk['selected']}**, резерв: **{risk['fallback']}**. "
                  f"Экспериментальный бюджет ложных тревог: {risk['false_alarm_budget']:.0%}. "
                  f"Сравнение на {risk['common_test_n']} общих тестовых анализах:", "",
                  "| Метод | Найдено превышений | Ложных тревог среди проб без превышения | Верных тревог среди всех тревог |",
                  "|---|---:|---:|---:|"]
        def percent(value):
            return f"{value:.1%}" if value is not None else "—"
        for name, result in risk["models"].items():
            m = result["test_common"]
            lines.append(f"| {name} | {m['tp']}/{m['tp'] + m['fn']} ({percent(m['recall'])}) | "
                         f"{m['fp']}/{m['fp'] + m['tn']} ({percent(m['false_alarm_rate'])}) | {percent(m['precision'])} |")
        lines += ["", *[f"- {note}" for note in risk["limitations"]], ""]
    lines += ["## Сценарии агентов", "", "| Сценарий | Решение | Объяснение |", "|---|---|---|"]
    for name, d in demos.items():
        lines.append(f"| {name} | {d['status']} | {d['reason']} |")
    lines += ["", "## Проверяемый конфликт", ""]
    conflict = demos["conflict_synthetic"]
    action = conflict["immediate_action"]
    if action:
        reserve = action["recipe"].get("reserve", 0.0)
        lines += [f"При верхней оценке серы 14 мг/кг исходный режим не проходит ограничения. "
                  f"Единый контур MakeDecision выбрал расход {action['throughput_tph']:g} т/ч "
                  f"с массовой долей резерва {reserve:.0%}.", ""]
    lines += ["Численные условия берутся из config/scenarios/*.json. audit.jsonl содержит решения, "
              "проверки и причины запретов. Фактическое будущее в решение не передается.", "",
              "Результат остаётся исследовательским советом: решение не разрешает промышленный выпуск.", ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
