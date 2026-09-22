from copy import deepcopy

import pytest

from neftecode.application.history.prepare import HistoryError, HistoryRequest, PrepareHistoricalState, local_moment


class Source:
    def get_snapshot(self, key):
        if key != "20260105-080000":
            raise HistoryError("snapshot_not_found", "Срез не найден")
        return self.prepare_at("2026-01-05T08:00:00")[0]

    def prepare_at(self, at):
        return {"at": at, "state": {"decision_time": at}}, {}

    def provenance(self):
        return {"version": "fixed"}


@pytest.mark.parametrize("at", ["", "2026-01-05", "NaT", "not a date", "2026-01-05T08:00:00Z", "2026-01-05T08:00:00+03:00"])
def test_invalid_time_and_timezone_are_not_silently_reinterpreted(at):
    with pytest.raises(HistoryError):
        local_moment(at)


def test_exact_time_and_requested_conditions_survive_preparation():
    request = HistoryRequest(at="2026-01-05T08:07:13", fault="frozen_pak",
                             changes=({"change": "tank_inventory", "target": "main", "value": 3},))
    before = deepcopy(request)
    result = PrepareHistoricalState(Source()).execute(request)
    assert result["effective_at"] == result["requested_at"] == request.at
    assert result["alignment"] == "exact_as_of"
    assert result["conditions"]["fault"] == "frozen_pak"
    result["conditions"]["changes"][0]["value"] = 5
    assert request == before


@pytest.mark.parametrize("command,code", [
    (HistoryRequest(), "ambiguous_moment"),
    (HistoryRequest(at="2026-01-05T08:00:00", snapshot="20260105-080000"), "ambiguous_moment"),
    (HistoryRequest(snapshot="unknown"), "snapshot_not_found"),
    (HistoryRequest(snapshot="20260105-080000", fault="unknown"), "unknown_fault"),
])
def test_no_silent_snapshot_or_fault_substitution(command, code):
    with pytest.raises(HistoryError) as exc:
        PrepareHistoricalState(Source()).execute(command)
    assert exc.value.code == code


def test_provider_cannot_replace_selected_moment():
    source = Source()
    source.prepare_at = lambda at: ({"at": "2026-01-05T08:00:00", "state": {}}, {})
    with pytest.raises(HistoryError, match="не совпадает"):
        PrepareHistoricalState(source).execute(HistoryRequest(at="2026-01-05T08:07:00"))


def test_nanoseconds_are_not_silently_truncated():
    with pytest.raises(HistoryError, match="округления"):
        local_moment("2026-01-05T08:07:13.123456789")
