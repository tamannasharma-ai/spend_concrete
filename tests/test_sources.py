from unittest.mock import Mock, patch

import pytest

from spendwise.sources import dbnomics, refresh


def response(periods, values, code="M.PRC_PRR.C2351.NSA.I21.DE"):
    return Mock(json=Mock(return_value={"series": {"docs": [
        {"series_code": code, "period": periods, "value": values}
    ]}}))


def test_dbnomics_filters_missing_values_and_labels_historical_data():
    with patch("spendwise.sources.get", return_value=response(
        ["2020-03", "2020-02", "2020-01", "2020-04", "invalid"],
        [105, "NA", 100, float("nan"), 200]
    )) as get:
        doc = dbnomics("DE", "C2351")
    assert doc["series"] == [{"date": "2020-01", "value": 100}, {"date": "2020-03", "value": 105}]
    assert doc["latest_observation"] == "2020-03"
    assert "Historical data" in doc["warning"]
    assert doc["warning"] in doc["text"]
    assert "C2351.NSA.I21.DE" in get.call_args.args[0]


@pytest.mark.parametrize("payload", [
    {"series": {"docs": []}},
    {"series": {"docs": [{"series_code": "wrong-country"}]}},
])
def test_dbnomics_does_not_substitute_missing_series(payload):
    with patch("spendwise.sources.get", return_value=Mock(json=Mock(return_value=payload))):
        with pytest.raises(ValueError):
            dbnomics("DE", "C2351")


def test_dbnomics_rejects_all_missing_observations():
    with patch("spendwise.sources.get", return_value=response(["2020-01"], ["NA"])):
        with pytest.raises(ValueError, match="No usable"):
            dbnomics("DE", "C2351")


def test_refresh_preserves_other_sources_on_dbnomics_failure():
    def original(*args):
        return {"id": "OFFICIAL", "retrieved_at": "2026-09-24"}

    with patch("spendwise.sources.ecb", original), patch("spendwise.sources.eurostat", original), \
         patch("spendwise.sources.gdacs", original), patch("spendwise.sources.policy", original), \
         patch("spendwise.sources.dbnomics", side_effect=ValueError("No series")):
        docs, statuses = refresh("DE", ("C2351",))
    assert len(docs) == 4
    assert sum(s["status"] == "Unavailable" for s in statuses) == 1
