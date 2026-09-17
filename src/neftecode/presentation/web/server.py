"""Local interactive demonstration: change the conditions, watch the core recompute.

Only the standard library. The brief requires a run that does not depend critically on external
services, and a framework here would buy nothing: the page is one file and the server has two
routes. It binds to localhost and is a demonstration tool, not a deployment.

The controls edit the scenario document, which then goes through the same loader, the same
validation and the same agent loop as every other entry point. There is no branch here that
returns a prepared answer, and an inadmissible change comes back as the loader's own error.
"""
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from html import escape
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from neftecode.presentation.demo import SOURCE_FAULTS, Demo, DemoError, snapshot_key, snapshot_title
from .ui import RENDER_JS, STYLE, error_payload

#: Where the scenario files live, relative to the project root.
SCENARIO_DIR = Path("config/scenarios")

CONTROLS_STYLE = """
 .layout { display: grid; grid-template-columns: 320px 1fr; gap: 24px; align-items: start; }
 @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
 /* The panel is taller than a short viewport, so it scrolls inside itself and the buttons
    stay reachable instead of sliding off the screen. */
 #panel { position: sticky; top: 16px; border:1px solid var(--line); border-radius:8px;
   padding:16px; max-height: calc(100vh - 32px); overflow-y: auto; }
 #panel h2 { margin-top: 0; }
 #panel label { display:block; margin: 12px 0 4px; font-size: 13px; color:#57606a; }
 #panel input, #panel select { width: 100%; padding: 6px 8px; font: inherit;
   border:1px solid var(--line); border-radius:6px; background: transparent; color: inherit; }
 #panel .row { display:flex; gap:8px; align-items:center; margin-top:12px;
   position: sticky; bottom: 0; padding: 12px 0 4px; background: var(--panel-bg, inherit); }
 #panel button { flex:1; padding: 8px 12px; font: inherit; font-weight:600; cursor:pointer;
   border:1px solid var(--line); border-radius:6px; background:#1a7f37; color:#fff; }
 #panel button.secondary { background: transparent; color: inherit; font-weight: 400; }
 #panel .hint { font-size:12px; color:#57606a; margin-top:12px; line-height:1.4; }
 #busy { font-size:13px; color:#9a6700; min-height: 18px; margin-top: 8px; }
"""

PAGE = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<title>Нефтекод — интерактивная демонстрация</title>
<style>
__STYLE__
__CONTROLS_STYLE__
</style>
<body>
<div class="layout">
<form id="panel" onsubmit="return false;">
  <h2>Условия</h2>
  <div class="row" style="position:static;margin-top:0">
    <button id="run-top" type="button">Пересчитать</button>
    <button id="reset-top" type="button" class="secondary">Сброс</button>
  </div>

  <label for="scenario">Сценарий</label>
  <select id="scenario">__SCENARIOS__</select>

  <label for="crude">Сера сырья, % масс.</label>
  <input id="crude" type="number" step="0.05" min="0" max="6">

  <label for="sulfur">Предел серы продукта, мг/кг (не выше 10)</label>
  <input id="sulfur" type="number" step="0.5" min="0" max="10">

  <label for="t95">Предел T95, °C</label>
  <input id="t95" type="number" step="1" min="0">

  <label for="cetane">Минимум цетанового числа</label>
  <input id="cetane" type="number" step="0.5" min="0">

  <label for="throughput">Текущий выпуск, т/ч</label>
  <input id="throughput" type="number" step="5" min="0">

  <label for="tank">Резервуар</label>
  <select id="tank"></select>

  <label for="stock">Запас резервуара, т</label>
  <input id="stock" type="number" step="10" min="0">

  <label for="available">Резервуар доступен</label>
  <select id="available"><option value="1">да</option><option value="0">нет</option></select>

  <label for="snapshot">Состояние данных</label>
  <select id="snapshot">__SNAPSHOTS__</select>

  <label for="fault">Исправность источников</label>
  <select id="fault">__FAULTS__</select>

  <div class="row">
    <button id="run" type="button">Пересчитать</button>
    <button id="reset" type="button" class="secondary">Сброс</button>
  </div>
  <div id="busy"></div>
  <p class="hint">Любое изменение проводится через тот же загрузчик сценария и то же ядро
  решения, что и командная строка. Недопустимое условие отклоняется загрузчиком, а не
  исправляется молча. Отказы источников — модельные инъекции, а не наблюдения из данных.</p>
</form>

<div>
  <div id="loading">Загрузка решения…</div>
  <div id="screen" hidden></div>
</div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
let data = JSON.parse(document.getElementById("payload").textContent);
__RENDER_JS__

const $ = (id) => document.getElementById(id);
const defaults = JSON.parse(document.getElementById("payload").textContent).defaults || {};

function fillFrom(defs) {
  $("crude").value = defs.crude_sulfur_wt_pct ?? "";
  $("sulfur").value = defs.product_sulfur_mgkg ?? "";
  $("t95").value = defs.product_t95_c ?? "";
  $("cetane").value = defs.product_cetane_number ?? "";
  $("throughput").value = defs.throughput_tph ?? "";
  $("tank").innerHTML = (defs.tanks || []).map(t => `<option value="${t.id}">${t.id}</option>`).join("");
  if ((defs.tanks || []).length) syncTank();
}

function syncTank() {
  const tanks = (data.defaults || defaults).tanks || [];
  const chosen = tanks.find(t => t.id === $("tank").value) || tanks[0];
  if (!chosen) return;
  $("stock").value = chosen.inventory;
  $("available").value = chosen.available ? "1" : "0";
}
$("tank").addEventListener("change", syncTank);

function show() {
  $("screen").innerHTML = render();
  $("loading").hidden = true;
  $("screen").hidden = false;
}

async function recompute() {
  $("busy").textContent = "Считаем…";
  const params = new URLSearchParams({
    scenario: $("scenario").value,
    crude_sulfur_wt_pct: $("crude").value,
    product_sulfur_mgkg: $("sulfur").value,
    product_t95_c: $("t95").value,
    product_cetane_number: $("cetane").value,
    throughput_tph: $("throughput").value,
    tank: $("tank").value,
    tank_inventory: $("stock").value,
    tank_available: $("available").value,
    fault: $("fault").value,
    snapshot: $("snapshot").value,
  });
  try {
    const response = await fetch("/api/decide?" + params.toString());
    data = await response.json();
    show();
    $("busy").textContent = data.state === "error" ? "Условие отклонено" : "Пересчитано";
  } catch (error) {
    data = {state: "error", message: String(error)};
    show();
    $("busy").textContent = "Ошибка запроса";
  }
}

$("run").addEventListener("click", recompute);
$("run-top").addEventListener("click", recompute);
$("reset-top").addEventListener("click", () => $("reset").click());
$("reset").addEventListener("click", async () => {
  const response = await fetch("/api/defaults?scenario=" + encodeURIComponent($("scenario").value));
  const fresh = await response.json();
  fillFrom(fresh);
  $("fault").value = "healthy";
  await recompute();
});
$("scenario").addEventListener("change", () => $("reset").click());

fillFrom(defaults);
show();
</script>
</body>
</html>
"""


class DemoServerError(ValueError):
    """Raised when the server cannot serve a request as asked."""


def _number(values: dict, key: str):
    raw = (values.get(key) or [""])[0].strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise DemoServerError(f"{key}: ожидается число, получено «{raw}»") from exc


def defaults_for(raw: dict) -> dict:
    """Current values of everything the panel can change."""
    product = raw.get("product", {})
    return {
        "crude_sulfur_wt_pct": raw["crude"]["sulfur_wt_pct"]["value"],
        "product_sulfur_mgkg": (product.get("sulfur_mgkg") or {}).get("value"),
        "product_t95_c": (product.get("t95_c") or {}).get("value"),
        "product_cetane_number": (product.get("cetane_number") or {}).get("value"),
        "throughput_tph": raw["current_operation"]["throughput"]["value"],
        "tanks": [{"id": t["tank_id"], "inventory": t["inventory"]["value"],
                   "available": t["available"]} for t in raw["tanks"]],
    }


def changes_from(values: dict, raw: dict) -> list[dict]:
    """Turn the panel's fields into scenario changes, skipping anything left as it was."""
    defaults = defaults_for(raw)
    changes = []
    for field, change in (("crude_sulfur_wt_pct", "crude_sulfur_wt_pct"),
                          ("product_sulfur_mgkg", "product_sulfur_mgkg"),
                          ("product_t95_c", "product_t95_c"),
                          ("product_cetane_number", "product_cetane_number"),
                          ("throughput_tph", "throughput_tph")):
        value = _number(values, field)
        if value is None or defaults.get(field) is None:
            continue
        if abs(value - float(defaults[field])) > 1e-9:
            changes.append({"change": change, "value": value})
    tank = (values.get("tank") or [""])[0]
    if tank:
        current = next((t for t in defaults["tanks"] if t["id"] == tank), None)
        stock = _number(values, "tank_inventory")
        if current and stock is not None and abs(stock - float(current["inventory"])) > 1e-9:
            changes.append({"change": "tank_inventory", "value": stock, "target": tank})
        raw_available = (values.get("tank_available") or [""])[0]
        if current and raw_available in ("0", "1"):
            available = raw_available == "1"
            if available != bool(current["available"]):
                changes.append({"change": "tank_available", "value": available, "target": tank})
    return changes


@dataclass
class DemoService:
    """Holds the scenarios and runs one recomputation per request."""

    root: Path
    demo_factory: Callable[[dict, int], Demo]
    budget: int = 400
    #: Замороженные реальные срезы (C3): первый в списке страницы — свежайший; без них — синтетика.
    snapshots: list = field(default_factory=list)

    def snapshot_options(self) -> list[tuple[str, str]]:
        options = [(snapshot_key(item), snapshot_title(item)) for item in reversed(self.snapshots)]
        return options + [("synthetic", "синтетическое состояние сценария")]

    def default_snapshot(self) -> str:
        return self.snapshot_options()[0][0]

    def scenarios(self) -> list[str]:
        return sorted(p.stem for p in (self.root / SCENARIO_DIR).glob("*.json"))

    def raw(self, name: str) -> dict:
        if name not in self.scenarios():
            raise DemoServerError(f"Сценарий «{name}» не найден")
        return json.loads((self.root / SCENARIO_DIR / f"{name}.json").read_text())

    def decide(self, values: dict) -> dict:
        name = (values.get("scenario") or [self.scenarios()[0]])[0]
        raw = self.raw(name)
        fault = (values.get("fault") or ["healthy"])[0]
        if fault not in SOURCE_FAULTS:
            raise DemoServerError(f"Неизвестный отказ источника «{fault}»")
        snapshot = (values.get("snapshot") or [self.default_snapshot()])[0]
        result = self.demo_factory(raw, self.budget).run(changes_from(values, raw), fault, snapshot=snapshot)
        payload = dict(result["screen"])
        payload["defaults"] = defaults_for(raw)
        payload["applied"] = result.get("applied", [])
        payload["injection"] = result.get("injection")
        payload["snapshot"] = result.get("snapshot")
        payload["binding"] = result.get("binding")
        return payload

    def page(self, name: str | None = None) -> str:
        names = self.scenarios()
        chosen = name if name in names else names[0]
        try:
            payload = self.decide({"scenario": [chosen]})
        except (DemoServerError, DemoError, ValueError) as exc:
            payload = error_payload(str(exc))
            payload["defaults"] = {}
        options = "".join(f'<option value="{n}"{" selected" if n == chosen else ""}>{n}</option>'
                          for n in names)
        faults = "".join(f'<option value="{f}">{f}</option>' for f in SOURCE_FAULTS)
        snapshots = "".join(f'<option value="{key}">{escape(title)}</option>'
                            for key, title in self.snapshot_options())
        # Placeholder substitution for the same reason as in ui.py: the page is mostly CSS and
        # JavaScript, and doubling every brace for str.format would be a trap.
        replacements = {
            "__STYLE__": STYLE, "__CONTROLS_STYLE__": CONTROLS_STYLE, "__RENDER_JS__": RENDER_JS,
            "__SCENARIOS__": options, "__FAULTS__": faults, "__SNAPSHOTS__": snapshots,
            "__PAYLOAD__": json.dumps(payload, ensure_ascii=False, default=str),
        }
        page = PAGE
        for token, value in replacements.items():
            page = page.replace(token, value)
        return page


def make_handler(service: DemoService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "neftecode-demo"

        def log_message(self, fmt, *args):  # noqa: A003 - quieter than the default access log
            pass

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status: int = 200):
            self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode(),
                       "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            try:
                if parsed.path in ("/", "/index.html"):
                    name = (values.get("scenario") or [None])[0]
                    self._send(200, service.page(name).encode(), "text/html; charset=utf-8")
                elif parsed.path == "/api/decide":
                    self._json(service.decide(values))
                elif parsed.path == "/api/defaults":
                    name = (values.get("scenario") or [service.scenarios()[0]])[0]
                    self._json(defaults_for(service.raw(name)))
                elif parsed.path == "/api/scenarios":
                    self._json({"scenarios": service.scenarios()})
                else:
                    self._json({"error": "Неизвестный путь"}, status=404)
            except (DemoServerError, DemoError, ValueError) as exc:
                # An inadmissible condition is an answer, not a crash: the screen shows it.
                self._json({**error_payload(str(exc)), "defaults": {}}, status=200)
            except Exception as exc:  # pragma: no cover - last resort, never a silent success
                self._json({**error_payload(f"Внутренняя ошибка: {exc}"), "defaults": {}},
                           status=500)

    return Handler


def serve(service: DemoService, port: int = 8765):
    """Run the demonstration server on localhost until interrupted."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(service))
    print(f"Демонстрация: http://127.0.0.1:{port}/")
    print(f"Сценарии: {', '.join(service.scenarios())}")
    print("Остановить — Ctrl+C. Сервер слушает только localhost.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        httpd.server_close()
    return httpd
