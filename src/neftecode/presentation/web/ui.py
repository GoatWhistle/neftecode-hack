"""Operator screen: a self-contained page rendered from the decision itself.

Deliberate choices:

* **No server and no framework.** The brief requires a reproducible run that does not depend
  critically on external services, and a separate HTTP API would only exist to feed a page that
  does not need one. The page is a single file that opens from disk.
* **No number is written into the markup.** The decision and its explanation are embedded as
  JSON and rendered by a short script, so the screen cannot drift away from the calculation.
  If a value is missing it shows as unknown rather than as a blank that reads like zero.
* **Four states are real states**, not decorations: loading, error, a decision, and a refusal.
  A refusal is a first-class screen with its next steps, not an empty result.

The main meaning is readable without opening the log; the agent trace and the full gate are in
a collapsed section underneath.
"""
from dataclasses import dataclass
import json
from pathlib import Path

STATES = ("loading", "error", "decision", "refusal")


class UiError(ValueError):
    """Raised when there is nothing checkable to render."""


#: Shared stylesheet. Both the static page and the interactive server use it, so the
#: screen looks and behaves identically whichever way it is opened.
STYLE = """ :root { color-scheme: light dark; --ok:#1a7f37; --warn:#9a6700; --bad:#b42318; --line:#d8dee4; }
 body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; max-width: 1000px; }
 h1 { font-size: 20px; margin: 0 0 4px; }
 .sub { color: #57606a; margin-bottom: 20px; }
 .badge { display:inline-block; padding:2px 10px; border-radius:12px; font-weight:600; color:#fff; }
 .badge.hold { background: var(--ok); }
 .badge.recommend_scenario { background: var(--warn); }
 .badge.refuse { background: var(--bad); }
 .badge.error { background: var(--bad); }
 section { border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:16px; }
 h2 { font-size: 15px; margin: 0 0 12px; text-transform: uppercase; letter-spacing: .04em;
       color:#57606a; }
 table { border-collapse: collapse; width: 100%; }
 td, th { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align: top; }
 th { color:#57606a; font-weight:600; width: 38%; }
 .unknown { color:#9a6700; font-style: italic; }
 .origin { color:#57606a; font-size:12px; margin-left:6px; }
 .note { color:#57606a; font-size:13px; margin-top:12px; }
 ul { margin: 0; padding-left: 20px; }
 details { margin-top: 8px; }
 pre { background:#f6f8fa; padding:12px; border-radius:6px; overflow:auto; font-size:12px; }
 .warn { color: var(--warn); font-weight:600; }
 #loading { color:#57606a; }"""

#: The renderer. It reads a payload object named `data` and returns HTML. Kept separate so
#: the interactive server can re-run it after every recomputation without duplicating it.
RENDER_JS = """const esc = (s) => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const num = (v, digits) => (v === null || v === undefined)
  ? '<span class="unknown">неизвестно</span>' : Number(v).toFixed(digits ?? 3);
const rows = (pairs) => pairs.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`).join("");
const card = (title, body) => `<section><h2>${esc(title)}</h2>${body}</section>`;

function render() {
  if (data.state === "error") return card("Ошибка", `<p class="badge error">Ошибка</p>
    <p>${esc(data.message)}</p>`);
  if (data.state === "loading") return card("Решение", `<p class="unknown">${esc(data.message || "Считаем решение…")}</p>`);
  const d = data.decision, e = data.explanation;
  const current = e.current_operation || {};
  const change = (before, after, digits) => `${num(before, digits)} → ${num(after, digits)}`;
  const recipeRows = (before, after) => [...new Set([
    ...Object.keys(before || {}), ...Object.keys(after || {})
  ])].map(k => [e.component_names?.[k] || k,
    change(before ? 100 * (before[k] || 0) : null,
           after ? 100 * (after[k] || 0) : null, 1) + " %"]);
  // Текущие параметры показываются в любом состоянии экрана, включая отказ: оператору нужно
  // видеть, от чего отсчитывается решение, даже когда предлагать нечего. Каждое число несёт
  // происхождение: измерение, сценарное допущение или подтверждённый режим; нет измерения — «неизвестно».
  const originLabel = {measured: "измерение", derived: "выведено из данных", scenario: "сценарное допущение",
    decision: "подтверждённый режим", given: "выдано организаторами"};
  const origin = current.origin || {};
  const tagged = (v, o, digits, unit) => v === null || v === undefined
    ? num(v, digits) : `${num(v, digits)}${unit || ""} <span class="origin">${esc(originLabel[o] || o || "")}</span>`;
  const currentRows = () => Object.entries(current.controls || {})
    .map(([k, v]) => [k, tagged(v, (origin.controls || {})[k], 2)])
    .concat([["Выпуск, т/ч", tagged(current.throughput_tph, origin.throughput_tph, 1)],
             ["Доля присадки", tagged(current.additive_dose, origin.additive_dose, 4)]]);
  const currentRecipeRows = () => Object.entries(current.recipe || {})
    .map(([k, f]) => [e.component_names?.[k] || k, tagged(100 * f, origin.recipe, 1, " %")]);
  // Измерения тегов на момент решения (только реальный срез): то, что установка показывала на самом деле.
  const measurementRows = () => Object.entries(current.measurements || {}).map(([tag, m]) => [tag, m
    ? `${num(m.value, 2)} · ${esc(String(m.time || "").replace("T", " "))}` +
      (Number.isFinite(m.age_min) ? ` · возраст ${num(m.age_min, 0)} мин` : "")
    : '<span class="unknown">нет измерения на момент решения</span>']);
  const measurementsCard = () => measurementRows().length
    ? `<h3>Измерения на момент решения</h3><table>${rows(measurementRows())}</table>
       <p class="note">ht.T6 — температура входа Р-202, °C; ht.F9 — расход сырья ГО, т/ч; ht.F26 — гидроочищенное ДТ в цех №8, м³/ч.</p>` : "";
  const head = `<h1>${esc(data.title)}</h1>
    <div class="sub">Сценарий <b>${esc(d.scenario_id)}</b>, решение
    <code>${esc(d.decision_id)}</code> · <span class="badge ${esc(d.status)}">${esc(data.status_label)}</span>
    <br>Момент решения: ${data.decision_time
      ? esc(String(data.decision_time).replace("T", " "))
      : '<span class="unknown">неизвестен</span>'}</div>`;
  let body = card("Что делать", `<p>${esc(d.reason)}</p>` +
    (d.status === "refuse"
      ? `<p>Чтобы решение стало возможным, нужно:</p><ul>` +
        (e.next_steps || []).map(s => `<li>${esc(s.need)}` +
          (s.available_in_hours ? ` <span class="warn">(результат до ${s.available_in_hours} ч; ${esc(s.caveat || "")})</span>` : "") +
          `</li>`).join("") + `</ul>
        <h3>Ключевые текущие параметры</h3>
        <table>${rows(currentRows())}</table>` + measurementsCard() +
        (currentRecipeRows().length
          ? `<h3>Состав смеси сейчас</h3><table>${rows(currentRecipeRows())}</table>` : "")
      : `<table>${rows((d.immediate_action ? Object.entries(d.immediate_action.controls) : [])
            .map(([k, v]) => [k, `${tagged(current.controls?.[k], (origin.controls || {})[k], 2)} → ${num(v, 2)}`])
            .concat([["Выпуск, т/ч", `${tagged(current.throughput_tph, origin.throughput_tph, 1)} → ${num(d.immediate_action?.throughput_tph, 1)}`],
                     ["Доля присадки", `${tagged(current.additive_dose, origin.additive_dose, 4)} → ${num(d.immediate_action?.additive_dose, 4)}`]]))}</table>
        <p class="note">Уставки задаются регуляторам с обратной связью:<br>${(e.statements || [])
            .filter(s => s.topic.startsWith("control.")).map(s => esc(s.text)).join("<br>")}</p>
        <h3>Состав смеси: сейчас → предложено</h3>
        <table>${rows(recipeRows(current.recipe, d.immediate_action?.recipe))}</table>` + measurementsCard()));

  if (d.status !== "refuse") {
    body += card("Ожидаемый эффект", `<table>${rows([
      ["Выпуск за горизонт, т", num(d.production_t, 1)],
      ["Условная стоимость, ед./т", num(d.cost_per_tonne, 4)],
      ["Тяжесть режима", num(d.severity_index, 4)],
      ["Проверок пройдено", `${e.checks_passed ?? "—"} из ${e.checks_total ?? "—"}`]])}</table>
      <p class="note">Условные единицы сценария. Это не тарифы завода и не измеренная экономия.</p>`);

    body += card("Качество и запас до предела", `<table>${rows(
      (e.statements || []).filter(s => ["sulfur_mgkg","t95_c","cetane_number","density_min_kgm3","density_max_kgm3","lookahead"].includes(s.topic))
        .map(s => [s.topic, s.value === null ? '<span class="unknown">неизвестно</span>' : esc(s.text)]))}</table>`);

    if (d.selected_plan && d.selected_plan.steps.length > 1) {
      body += card("План по времени", `<table><tr><th>Момент</th><td>Состав, выпуск и уставки</td></tr>` +
        d.selected_plan.steps.map(s => `<tr><th>${s.time_hours} ч</th><td>` +
          Object.entries(s.recipe).filter(([, f]) => f > 0)
            .map(([k, f]) => `${esc(k)} ${(f*100).toFixed(0)}%`).join(", ") +
          ` · ${num(s.throughput_tph, 0)} т/ч` +
          `<br>Присадка: ${num(100 * s.additive_dose, 2)}%` +
          Object.entries(s.controls || {}).map(([k, v]) => `<br>${esc(k)}: ${num(v, 2)}`).join("") +
          `</td></tr>`).join("") + `</table>
        <p class="note">${esc(d.selected_plan.intent)}</p>`);
    }

    if (data.inventories && Object.keys(data.inventories).length) {
      body += card("Запас компонентов", `<table>${rows(
        Object.entries(data.inventories).map(([k, v]) => [k, num(v, 1) + " т"]))}</table>`);
    }

    if (d.robustness) {
      const r = d.robustness;
      body += card("Устойчивость к ошибкам модели",
        `<p>${r.held} из ${r.perturbations_evaluated} заданных отклонений выдержано` +
        (r.not_applicable ? `, ${r.not_applicable} к плану неприменимы (нет хода уставок ГО)` : "") + `.` +
        (r.fragile ? ` <span class="warn">План надёжным не считается.</span>` : "") + `</p>
        <ul>${(r.results || []).filter(x => x.outcome === "violated")
          .map(x => `<li>${esc(x.perturbation)}: ${esc((x.first_violation||{}).reason || "нарушение")}</li>`).join("")}</ul>
        <p class="note">Доля выдержанных отклонений — не вероятность успеха и не доверительный интервал.</p>`);
    }

    if ((e.alternatives || []).length) {
      body += card("Допустимые альтернативы", `<table><tr><th>Вариант</th><td>Выпуск, т · стоимость</td></tr>` +
        e.alternatives.map(a => `<tr><th>${esc(a.candidate_id)}</th><td>${num(a.production_t,1)} · ${num(a.cost_per_tonne,4)}</td></tr>`).join("") +
        `</table>`);
    }
  }

  // Доверие к прогнозу. Показывается и при отказе, но честно: если сценарий с прогнозом не
  // связывался (отказ по данным принят раньше), прогноз в основание решения не входил — так и пишем.
  const f = data.forecast;
  const covered = f && Number.isFinite(f.coverage_test) && Number.isFinite(f.coverage_target);
  const unused = f && f.available && data.forecast_used === false;
  body += card("Доверие к прогнозу", (f && f.available)
    ? (unused ? `<p class="warn">Прогноз рассчитан, но в основание решения не входил: отказ принят по данным
        до привязки прогноза. Числа ниже — справочно, для этого момента они не проверялись на применимость.</p>` : "")
      + `<table>${rows([
        ["Прогноз серы, мг/кг", num(f.value, 2)],
        ["Верхняя граница интервала, мг/кг", num(f.upper, 2)],
        ["Нижняя граница интервала, мг/кг", num(f.lower, 2)],
        ["Заданное покрытие интервала", num(f.coverage_target, 2)],
        ["Покрытие на отложенной проверке", num(f.coverage_test, 3)],
        ["Модель прогноза", f.model ? esc(f.model) : '<span class="unknown">неизвестна</span>']])}</table>`
      + (covered && f.coverage_test < f.coverage_target
          ? `<p class="warn">Покрытие на проверке ниже заданного: интервал на истории оказался узким.</p>` : "")
      + `<p class="note">С пределом серы сравнивается верхняя граница интервала, а не точечный прогноз.
        Покрытие — доля попаданий интервала на отложенной проверке; это не вероятность того, что
        партия пройдёт, и не гарантия для этого решения.</p>`
    : (f ? `<p class="unknown">Прогноз серы не рассчитывался: ${f.reason ? esc(f.reason) : "причина не передана"}.</p>`
         : `<p class="unknown">Прогноз серы не передавался: экран собран без живого прогноза.</p>`));

  const stale = (data.sources || []).filter(s => !s.usable);
  body += card("Доверие к данным", `<table>${rows((data.sources || []).map(
    s => [s.name, s.usable
      ? `пригоден${Number.isFinite(s.age_hours)
          ? ` · возраст ${num(s.age_hours, 1)} ч из ${num(s.max_age_hours, 1)} ч` : ""}`
      : `<span class="unknown">${esc(s.reasons.join("; ") || s.status)}</span>`]))}</table>`
    + (stale.length ? `<p class="warn">Данные устарели или отсутствуют: `
        + stale.map(s => esc(s.name)).join(", ") + `. `
        + (stale.length < data.sources.length
            ? `Решение опирается только на оставшиеся источники.`
            : `Пригодного источника качества не осталось.`) + `</p>` : "")
    + (data.sources && data.sources.length ? "" : `<p class="note">Состояние источников не передавалось.</p>`)
    + (data.state_origin ? `<p class="note">Состояние: ${esc(data.state_origin)}</p>` : "")
    + (data.rule_origin ? `<p class="note">Пороги доверия: ${esc(data.rule_origin)}</p>` : ""));

  // Агентный слой. Без сети система честно уходит в детерминированный ответ — и экран обязан
  // отличаться от прогона с живой моделью, иначе эксперт не увидит, работала ли модель.
  const a = d.agentic;
  const outcomeLabel = {selected: "агенты выбрали план, код подтвердил его проверками",
    confirmed_legacy: "агенты подтвердили детерминированный ответ",
    refused: "агенты отклонили все допустимые планы — отказ с основанием",
    fallback: "модель не отвечала — выдан детерминированный ответ",
    skipped: "агенты не вызывались: отказ по данным принят раньше"};
  const verdictLabel = {ACCEPT: "принять", REJECT: "отклонить", REVISE: "доработать", UNKNOWN: "не определено"};
  if (!a) {
    body += card("Агентный слой", `<p><span class="badge hold">выключен</span>
      Агентный слой отключён явно (<code>AGENTIC_DECISION_ENABLED=0</code>): решение детерминированное,
      модель не вызывалась.</p>`);
  } else {
    const b = a.budget || {}, u = b.usage || {};
    const ran = Number.isFinite(b.llm_calls) && b.llm_calls > 0;
    const state = a.outcome === "fallback" ? "refuse" : a.outcome === "skipped" ? "recommend_scenario" : "hold";
    const head = a.outcome === "fallback"
      ? `<p class="warn">Решение детерминированное: модель не отвечала — <code>${esc(a.fallback_reason || "причина не передана")}</code>.
         Числа и проверки те же, что без агентов; агентный слой на этом решении не работал.</p>`
      : a.outcome === "skipped"
        ? `<p class="warn">Агенты не вызывались: ${esc(a.fallback_reason || "")} — отказ по данным принят до запуска моделей.</p>`
        : `<p><span class="badge hold">модель работала</span> ${esc(outcomeLabel[a.outcome] || a.outcome)}.</p>`;
    const opinions = (a.opinions || []).map(o => `<li><b>${esc(o.role)}</b>: ${esc(verdictLabel[o.verdict] || o.verdict)}` +
      (o.risk_level ? `, риск ${esc(o.risk_level)}` : "") + (o.valid === false ? ` <span class="warn">(ответ невалиден)</span>` : "") +
      ((o.reasons || []).length ? `<br><span class="note">${o.reasons.slice(0, 4).map(r => esc(r.code + (r.text ? ": " + r.text : ""))).join("; ")}</span>` : "") +
      `</li>`).join("");
    const constraints = (a.constraints_applied || []).map(c => `<li>${esc(JSON.stringify(c))}</li>`).join("");
    const vetoed = Object.entries(a.vetoed_candidates || {}).map(([cid, roles]) => `${esc(cid)} (${esc(roles.join(", "))})`).join(", ");
    body += card("Агентный слой", head + `<table>${rows([
      ["Провайдер · модель", `${a.provider ? esc(a.provider) : '<span class="unknown">не настроен</span>'} · ${a.model ? esc(a.model) : '<span class="unknown">—</span>'}`],
      ["Исход", `<span class="badge ${state}">${esc(a.outcome || "—")}</span>`],
      ["Вызовов модели", ran || Number.isFinite(b.llm_calls) ? `${b.llm_calls ?? 0} из ${b.max_llm_calls ?? "—"}` : '<span class="unknown">не было</span>'],
      ["Токены (вход / выход)", Number.isFinite(u.total_tokens) ? `${u.prompt_tokens ?? 0} / ${u.completion_tokens ?? 0}` : '<span class="unknown">—</span>'],
      ["Мнения специалистов", opinions ? `<ul>${opinions}</ul>` : '<span class="unknown">не запрашивались</span>'],
      ["Ограничения, предложенные агентами", constraints ? `<ul>${constraints}</ul>` : "нет"],
      ["Вето по кандидатам", vetoed || "нет"],
      ["Выбор модели переопределён правилом", a.llm_choice_overridden ? '<span class="warn">да — ранжирование кода важнее выбора модели</span>' : "нет"]])}</table>
      <p class="note">${esc(a.note || "")}</p>`);
  }

  body += card("Технические подробности", `
    <details><summary>Журнал агентов</summary><pre>${esc(JSON.stringify(d.trace, null, 2))}</pre></details>` +
    (a && a.trace ? `
    <details><summary>Журнал агентного слоя (вызовы модели, инструменты, решения)</summary><pre>${esc(JSON.stringify(a.trace, null, 2))}</pre></details>` : "") + `
    <details><summary>Все проверки ограничений</summary><pre>${esc(JSON.stringify(d.gate, null, 2))}</pre></details>
    <details><summary>Ограничения вывода</summary><ul>${(e.limits || []).map(l => `<li>${esc(l)}</li>`).join("")}</ul></details>
    <p class="note">${esc(d.note || "")}</p>`);
  return head + body;
}

document.getElementById("screen").innerHTML = render();"""

TEMPLATE = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<title>Нефтекод — экран оператора</title>
<style>
""" + STYLE + """
</style>
<body>
<div id="loading">Загрузка решения…</div>
<div id="screen" hidden></div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const data = JSON.parse(document.getElementById("payload").textContent);
""" + RENDER_JS + """
document.getElementById("screen").innerHTML = render();
document.getElementById("loading").hidden = true;
document.getElementById("screen").hidden = false;
</script>
</body>
</html>
"""


STATUS_LABELS = {"hold": "Сохранить режим", "recommend_scenario": "Сценарная рекомендация",
                 "refuse": "Надёжной рекомендации нет"}


@dataclass
class Screen:
    """Builds the payload the page renders. No formatting decisions live in the page."""

    decision: dict
    explanation: dict
    inventories: dict | None = None
    sources: list | None = None
    #: Откуда пороги доверия: derived:… (обучение) или fallback:… (config/experiment.json).
    rule_origin: str | None = None
    #: Откуда состояние: реальный срез (C3) или синтетическое состояние сценария.
    state_origin: str | None = None
    #: Момент решения (ISO, местное время источников) — из state["decision_time"] или --at.
    decision_time: str | None = None
    #: Прогноз серы с интервалом (`value`, `lower`, `upper`, `coverage_*`); None — не передавался.
    forecast: dict | None = None
    #: Вошёл ли прогноз в основание решения: False — посчитан, но сценарий с ним не связывался
    #: (отказ по данным принят раньше); None — не известно (сценарные экраны без прогноза).
    forecast_used: bool | None = None
    title: str = "Советчик оператору цепочки АВТ → гидроочистка → смешение"

    def payload(self) -> dict:
        status = self.decision.get("status")
        if status not in STATUS_LABELS:
            raise UiError(f"Неизвестный статус решения: {status}")
        return {
            "state": "refusal" if status == "refuse" else "decision",
            "title": self.title,
            "status_label": STATUS_LABELS[status],
            "decision": self.decision,
            "explanation": self.explanation,
            "inventories": self.inventories or {},
            "sources": self.sources or [],
            "rule_origin": self.rule_origin,
            "state_origin": self.state_origin,
            "decision_time": self.decision_time,
            "forecast": self.forecast,
            "forecast_used": self.forecast_used,
        }


def error_payload(message: str) -> dict:
    return {"state": "error", "message": message}


def render(payload: dict) -> str:
    """Embed the payload into the page. Values are rendered by the page, never baked in."""
    if payload.get("state") not in STATES:
        raise UiError(f"Неизвестное состояние экрана: {payload.get('state')}")
    # Placeholder substitution, not str.format: the page carries CSS and JavaScript full of
    # braces, and escaping every one of them would make the source unreadable and fragile.
    return TEMPLATE.replace("__PAYLOAD__",
                            json.dumps(payload, ensure_ascii=False, default=str))


def write_screen(path: Path, payload: dict) -> Path:
    path = Path(path)
    path.write_text(render(payload), encoding="utf-8")
    return path
