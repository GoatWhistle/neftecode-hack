import pickle
from pathlib import Path


def load_model_bundle(out: Path) -> dict:
    path = Path(out) / "model.pkl"
    if not path.is_file():
        raise ValueError(f"Модель {path} не найдена: выполните `uv run neftecode train` или укажите --out "
                         f"каталогом, где лежит model.pkl (по умолчанию artifacts/)")
    try:
        with path.open("rb") as stream:
            bundle = pickle.load(stream)
    except (EOFError, pickle.UnpicklingError, AttributeError, ImportError, ValueError, OSError) as exc:
        raise ValueError(f"Модель {path} повреждена или не дочитана ({type(exc).__name__}: {exc}): "
                         f"выполните `uv run neftecode train` заново") from exc
    if not isinstance(bundle, dict) or "config" not in bundle:
        raise ValueError(f"Модель {path} не похожа на артефакт train (нет поля config): выполните "
                         f"`uv run neftecode train` заново")
    return bundle
