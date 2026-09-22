import pytest

from neftecode.application.history.catalog import snapshot_catalog


def item(at, edits=()):
    return {"at": at, "state": {"pak_value": 8.2}, "synthetic_edits": edits}


def test_catalog_uses_exact_data_times_and_never_invents_missing_facts():
    result = snapshot_catalog([item("2026-07-03T10:10:00", ["test edit"]), item("2026-01-03T11:00:00")], limit=1)
    assert result["total"] == 2 and result["next_offset"] == 1
    first = result["items"][0]
    assert first["snapshot"] == "20260103-110000"
    assert first["facts"]["lab_value"] is None
    assert first["facts"]["pak_value"] == 8.2
    assert result["arbitrary"]["available"] is False
    second = snapshot_catalog([item("2026-07-03T10:10:00", ["test edit"])])["items"][0]
    assert second["snapshot"].endswith("-synthetic")
    assert second["synthetic_edits"] == ["test edit"]


@pytest.mark.parametrize("kwargs", [{"limit": 101}, {"offset": -1}, {"limit": True}])
def test_catalog_budget(kwargs):
    with pytest.raises(ValueError):
        snapshot_catalog([], **kwargs)


def test_no_coverage_for_empty_delivery():
    result = snapshot_catalog([])
    assert result["items"] == [] and result["snapshot_coverage"] is None


def test_duplicate_keys_are_not_silently_overwritten():
    with pytest.raises(ValueError, match="повторяющийся"):
        snapshot_catalog([item("2026-01-03T11:00:00")] * 2)


def test_timezone_aware_saved_snapshot_is_rejected():
    with pytest.raises(ValueError, match="часовой пояс"):
        snapshot_catalog([item("2026-01-03T11:00:00+03:00")])


def test_catalog_sorts_by_time_even_if_source_formats_differ():
    result = snapshot_catalog([item("2026-01-03T09:00:00"), item("2026-01-03 11:00:00")])
    assert result["items"][0]["at"] == "2026-01-03T09:00:00"
    assert result["items"][1]["snapshot"] == "20260103-110000"


def test_microseconds_do_not_collapse_distinct_snapshots():
    result = snapshot_catalog([item("2026-01-03T09:00:00.000001"),
                               item("2026-01-03T09:00:00.000002")])
    assert result["items"][0]["snapshot"] == "20260103-090000.000001"
    assert result["items"][1]["snapshot"] == "20260103-090000.000002"
