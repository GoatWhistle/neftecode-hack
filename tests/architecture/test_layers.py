"""Dependency rules for the target Clean Architecture layout."""

import ast
from pathlib import Path


PACKAGE = Path("src/neftecode")
LAYERS = {"domain", "application", "infrastructure", "evaluation", "presentation"}
ALLOWED = {
    "domain": {"domain"},
    "application": {"application", "domain"},
    "infrastructure": {"infrastructure", "application", "domain"},
    "evaluation": {"evaluation", "application", "domain"},
    "presentation": {"presentation", "application", "domain"},
}
INNER_FORBIDDEN = {"catboost", "http", "numpy", "openpyxl", "pandas", "pickle", "sklearn"}


def imports(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
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


def test_new_layers_only_depend_inwards():
    """The rule applies as soon as a module is moved into a target layer."""
    for layer in LAYERS:
        folder = PACKAGE / layer
        for path in folder.rglob("*.py") if folder.exists() else ():
            for imported in imports(path):
                parts = imported.split(".")
                target = parts[1] if parts[:1] == ["neftecode"] and len(parts) > 1 else parts[0]
                if target in LAYERS:
                    assert target in ALLOWED[layer], f"{path}: {layer} -> {target}"
                if layer in {"domain", "application", "infrastructure"} and parts[:1] == ["neftecode"]:
                    assert target in ALLOWED[layer], f"{path}: {layer} -> flat module {target}"


def test_inner_layers_have_no_framework_or_adapter_dependencies():
    for layer in ("domain", "application"):
        folder = PACKAGE / layer
        for path in folder.rglob("*.py") if folder.exists() else ():
            for imported in imports(path):
                assert imported.split(".")[0] not in INNER_FORBIDDEN, f"{path}: {imported}"
