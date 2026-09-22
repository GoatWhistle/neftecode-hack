import json

import pytest

from neftecode.infrastructure.history.exclusions import ExclusionRegistry


def test_registry_paginates_original_reasons_and_covers_endpoints(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"stub_row_bursts": [
        {"from": "2026-01-01T00:00:00", "to": "2026-01-01T01:00:00", "reason": "307"}
    ], "pak_lab_conflict_events": [{"at": "2026-01-01T01:00:00", "reason": "Конфликт"}]}))
    registry = ExclusionRegistry(path)
    first = registry.between("2026-01-01T01:00:00", "2026-01-01T01:00:00", limit=1)
    assert first["total"] == 2 and first["next_offset"] == 1
    last = registry.between("2026-01-01T01:00:00", "2026-01-01T01:00:00", offset=1)
    assert last["items"][0]["scope"] == "pak_lab_sample" and last["items"][0]["reason"] == "Конфликт"
    assert last["next_offset"] is None
    assert registry.between("2026-01-01T01:00:01", "2026-01-01T01:00:01")["total"] == 0
    with pytest.raises(ValueError):
        registry.between("2026-01-01T00:00:00", "2026-01-01T01:00:00", limit=101)


def test_missing_registry_is_not_reported_as_clean_history(tmp_path):
    result = ExclusionRegistry(tmp_path / "absent.json").between("2026-01-01T00:00:00", "2026-01-01T01:00:00")
    assert result["provenance"]["available"] is False
