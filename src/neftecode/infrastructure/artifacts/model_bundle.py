"""Reading `model.pkl` with one-line errors: what is wrong, where, and what to do."""
import pickle
from pathlib import Path


def load_model_bundle(out: Path) -> dict:
    """The trained bundle from `out/model.pkl`.

    A missing or broken file is a `ValueError` with the path and the command that repairs it, not a
    traceback from `pickle`: the person who sees it is running a demo, not debugging the loader.
    """
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
