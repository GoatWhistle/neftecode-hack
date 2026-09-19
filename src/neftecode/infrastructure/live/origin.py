
import pandas as pd


def validate_origin(at, bundle: dict) -> pd.Timestamp:
    when = pd.Timestamp(at)
    if pd.isna(when) or when.tzinfo is not None:
        raise ValueError("Укажите корректное местное время без часового пояса, как в исходных данных")
    if when < pd.Timestamp(bundle["config"]["calibration_end"]):
        raise ValueError(
            "На этот момент модель и калибровка еще не были доступны; запуск создал бы утечку из будущего"
        )
    return when
