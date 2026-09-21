
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "neftecode"
LAYERS = {"domain", "application", "infrastructure", "evaluation", "presentation", "services", "composition"}
ALLOWED = {
    "composition": LAYERS,
    "domain": {"domain"},
    "application": {"application", "domain"},
    "infrastructure": {"infrastructure", "application", "domain"},
    "evaluation": {"evaluation", "application", "domain"},
    "presentation": {"presentation", "application", "domain"},
    "services": {"services", "presentation", "infrastructure", "application", "domain"},
}
RUNTIME_LAYERS = ("application", "composition", "infrastructure", "presentation", "services")
# Batch-команды offline-исследований (benchmark, episodes, vak, expert-grid) собираются
# в composition, но в рантайм решения не входят.
OFFLINE_ENTRY_POINTS = {PACKAGE / "composition" / "commands" / "evaluation.py"}
INNER_FORBIDDEN = {"catboost", "http", "numpy", "openpyxl", "pandas", "pickle", "sklearn"}


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = list(path.relative_to(PACKAGE).with_suffix("").parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - (node.level - 1)]
                yield ".".join([*base, *(node.module or "").split(".")]).strip(".")
            elif node.module:
                yield node.module


def layer_sources(layer: str) -> list[Path]:
    folder = PACKAGE / layer
    assert folder.is_dir(), f"Слой не найден: {folder}"
    paths = sorted(folder.rglob("*.py"))
    assert paths, f"Слой пуст: {folder}"
    return paths


def test_new_layers_only_depend_inwards():
    for layer in LAYERS:
        for path in layer_sources(layer):
            for imported in imports(path):
                parts = imported.split(".")
                target = parts[1] if parts[:1] == ["neftecode"] and len(parts) > 1 else parts[0]
                if target in LAYERS:
                    assert target in ALLOWED[layer], f"{path}: {layer} -> {target}"
                if layer in LAYERS and parts[:1] == ["neftecode"]:
                    assert target in ALLOWED[layer], f"{path}: {layer} -> flat module {target}"


def test_inner_layers_have_no_framework_or_adapter_dependencies():
    for layer in ("domain", "application"):
        for path in layer_sources(layer):
            for imported in imports(path):
                assert imported.split(".")[0] not in INNER_FORBIDDEN, f"{path}: {imported}"


def test_evaluation_receives_io_inputs_from_the_composition_root():
    for path in layer_sources("evaluation"):
        for imported in imports(path):
            assert imported.split(".")[0] not in {"openpyxl", "pathlib"}, f"{path}: {imported}"


def test_runtime_does_not_import_offline_evaluation():
    for layer in RUNTIME_LAYERS:
        for path in layer_sources(layer):
            if path in OFFLINE_ENTRY_POINTS:
                continue
            for imported in imports(path):
                parts = imported.split(".")
                target = parts[1] if parts[:1] == ["neftecode"] and len(parts) > 1 else parts[0]
                assert target != "evaluation", f"{path}: {imported}"
    for name in ("robustness.py", "tank_estimate.py"):
        assert not (PACKAGE / "evaluation" / name).exists(), name
        assert (PACKAGE / "application" / "services" / name).is_file(), name


def test_moved_flat_modules_are_deleted():
    for name in (
        "agents.py", "attribution.py", "batch.py", "benchmark.py", "blending.py",
        "claims.py", "cli.py", "contracts.py", "data.py", "demo.py", "economics.py",
        "explain.py", "forecast.py", "gate.py", "inventory.py", "lag.py", "live.py",
        "margin.py", "optimizer.py", "orchestrator.py", "planner.py", "process.py",
        "quality.py", "replay.py", "risk.py", "robustness.py", "runtime.py",
        "scenario.py", "server.py", "support.py", "trust.py", "twins.py", "ui.py",
        "vak.py",
    ):
        assert not (PACKAGE / name).exists(), name
    for name in ("batch.py", "margin.py"):
        assert not (PACKAGE / "infrastructure" / "ml" / name).exists(), name


def test_service_processes_do_not_import_each_other():
    services = {"data_service", "model_service", "decision_service", "gateway_service", "stack"}
    for name in services:
        path = PACKAGE / "services" / f"{name}.py"
        assert path.is_file(), f"Сервис не найден: {path}"
        for imported in imports(path):
            parts = imported.split(".")
            if parts[:2] == ["neftecode", "services"] and len(parts) > 2:
                assert parts[2] in {"common", name}, f"{path}: imports peer service {imported}"


def test_make_decision_is_the_only_production_coordinator():
    assert not (PACKAGE / "infrastructure/ml/agents.py").exists()
    assert not (PACKAGE / "infrastructure/ml/runtime.py").exists()
    assert not (ROOT / "config/blending-demo.json").exists()
    sources = sorted(PACKAGE.rglob("*.py"))
    assert sources, f"Пакет не найден: {PACKAGE}"
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        legacy = [node.name for node in ast.walk(tree)
                  if isinstance(node, ast.ClassDef) and node.name == "Coordinator"]
        assert not legacy, f"{path}: legacy Coordinator is forbidden"
        assert "neftecode.infrastructure.ml.agents" not in set(imports(path)), path


def test_deterministic_reviews_do_not_share_names_with_llm_agents():
    def classes(root: Path) -> set[str]:
        return {node.name for path in root.rglob("*.py")
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
                if isinstance(node, ast.ClassDef)}

    decision = PACKAGE / "application" / "use_cases" / "decision"
    assert not (decision / "agents.py").exists()
    assert {"QualityReview", "ReliabilityReview"} <= classes(decision)
    assert not classes(decision) & classes(PACKAGE / "application" / "agentic")


CONDITION_FUNCTIONS = {"apply_change", "apply_changes", "apply_source_failure", "canonical_conditions",
                       "changes_from", "defaults_for", "healthy_state", "state_under"}
CONDITION_TABLES = {"CHANGES", "PANEL_NUMBERS", "SOURCE_FAULTS"}


def test_conditions_logic_lives_only_in_application():
    """A3: правки сценария, инъекции отказов и canonical/defaults — в application/conditions.

    presentation и services только разбирают query-строку и вызывают application: они не определяют
    ни функций применения условий (в том числе любых `apply_*`), ни таблиц правок и отказов.
    """
    conditions = PACKAGE / "application" / "conditions"
    for name in ("canonical.py", "changes.py", "faults.py"):
        assert (conditions / name).is_file(), name
    assert not (PACKAGE / "presentation" / "web" / "conditions.py").exists()
    for layer in ("presentation", "services"):
        for path in layer_sources(layer):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    assert node.name not in CONDITION_FUNCTIONS and not node.name.startswith("apply_"), \
                        f"{path}: {node.name} — логика условий расчёта принадлежит application/conditions"
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    names = {t.id for t in targets if isinstance(t, ast.Name)}
                    assert not names & CONDITION_TABLES, f"{path}: {names & CONDITION_TABLES}"


def test_composition_is_only_used_by_external_entry_points():
    for layer in ("domain", "application", "infrastructure", "evaluation", "presentation"):
        for path in layer_sources(layer):
            assert not any(name.startswith("neftecode.composition") for name in imports(path)), path
    assert not (PACKAGE / "command_runtime.py").exists()
    assert not (PACKAGE / "command_dispatcher.py").exists()


def test_cli_dispatcher_covers_the_public_commands():
    from neftecode.composition.commands.dispatcher import HANDLERS
    from neftecode.presentation.cli import COMMANDS

    assert set(HANDLERS) == set(COMMANDS)
