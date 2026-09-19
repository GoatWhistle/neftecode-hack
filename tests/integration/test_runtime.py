import pandas as pd
import pytest

from neftecode.infrastructure.live.origin import validate_origin


def test_query_cannot_use_a_model_before_its_calibration_is_available():
    bundle = {"config": {"calibration_end": "2026-01-01"}}
    with pytest.raises(ValueError, match="утечку"):
        validate_origin("2025-12-31 23:59", bundle)
    assert validate_origin("2026-01-01", bundle) == pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="без часового пояса"):
        validate_origin("2026-01-01T00:00:00Z", bundle)
