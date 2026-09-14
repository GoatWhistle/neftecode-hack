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
import html
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
  const d = data.decision, e = data.explanation;
  const current = e.current_operation || {};
  const change = (before, after, digits) => `${num(before, digits)} → ${num(after, digits)}`;
  const recipeRows = (before, after) => [...new Set([
    ...Object.keys(before || {}), ...Object.keys(after || {})
  ])].map(k => [e.component_names?.[k] || k,
    change(before ? 100 * (before[k] || 0) : null,
           after ? 100 * (after[k] || 0) : null, 1) + " %"]);
  const head = `<h1>${esc(data.title)}</h1>
    <div class="sub">Сценарий <b>${esc(d.scenario_id)}</b>, решение
    <code>${esc(d.decision_id)}</code> · <span class="badge ${esc(d.status)}">${esc(data.status_label)}</span></div>`;
  let body = card("Что делать", `<p>${esc(d.reason)}</p>` +
    (d.status === "refuse"
      ? `<p>Чтобы решение стало возможным, нужно:</p><ul>` +
        (e.next_steps || []).map(s => `<li>${esc(s.need)}` +
          (s.available_in_hours ? ` <span class="warn">(результат до ${s.available_in_hours} ч; ${esc(s.caveat || "")})</span>` : "") +
          `</li>`).join("") + `</ul>`
      : `<table>${rows((d.immediate_action ? Object.entries(d.immediate_action.controls) : [])
            .map(([k, v]) => [k, change(current.controls?.[k], v, 2)])
            .concat([["Выпуск, т/ч", change(current.throughput_tph, d.immediate_action?.throughput_tph, 1)],
                     ["Доля присадки", change(current.additive_dose, d.immediate_action?.additive_dose, 4)]]))}</table>
        <p class="note">Уставки задаются регуляторам с обратной связью:<br>${(e.statements || [])
            .filter(s => s.topic.startsWith("control.")).map(s => esc(s.text)).join("<br>")}</p>
        <h3>Состав смеси: сейчас → предложено</h3>
        <table>${rows(recipeRows(current.recipe, d.immediate_action?.recipe))}</table>`));

  if (d.status !== "refuse") {
    body += card("Ожидаемый эффект", `<table>${rows([
      ["Выпуск за горизонт, т", num(d.production_t, 1)],
      ["Условная стоимость, ед./т", num(d.cost_per_tonne, 4)],
      ["Тяжесть режима", num(d.severity_index, 4)],
      ["Проверок пройдено", `${e.checks_passed ?? "—"} из ${e.checks_total ?? "—"}`]])}</table>
      <p class="note">Условные единицы сценария. Это не тарифы завода и не измеренная экономия.</p>`);

    body += card("Качество и запас до предела", `<table>${rows(
      (e.statements || []).filter(s => ["sulfur_mgkg","t95_c","cetane_number","density_min_kgm3","density_max_kgm3"].includes(s.topic))
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
        `<p>${r.held} из ${r.perturbations_evaluated} заданных отклонений выдержано.` +
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

  body += card("Доверие к данным", `<table>${rows((data.sources || []).map(
    s => [s.name, s.usable ? "пригоден" : `<span class="unknown">${esc(s.reasons.join("; ") || s.status)}</span>`]))}</table>`
    + (data.sources && data.sources.length ? "" : `<p class="note">Состояние источников не передавалось: решение получено на сценарных условиях.</p>`));

  body += card("Технические подробности", `
    <details><summary>Журнал агентов</summary><pre>${esc(JSON.stringify(d.trace, null, 2))}</pre></details>
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
