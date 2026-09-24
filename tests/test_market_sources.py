import json
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from spendwise.market_sources import trading_economics, world_bank


def te_response(payload, code=200):
    return Mock(status_code=code, content=b"[]", json=Mock(return_value=payload))


def test_te_missing_key_never_calls_network():
    with patch("spendwise.market_sources.requests.get") as get:
        docs, statuses = trading_economics(("coal",), "")
    get.assert_not_called()
    assert not docs
    assert "API key" in statuses[0]["detail"]


def test_te_auth_header_exact_benchmark_units_and_partial_failure():
    payload = [{"URL": "/commodity/eu-natural-gas", "Last": 42.5, "Date": "2020-01-03T00:00:00"},
               {"URL": "/commodity/natural-gas", "Last": 3, "Date": "2020-01-03T00:00:00"}]
    with patch("spendwise.market_sources.requests.get", return_value=te_response(payload)) as get:
        docs, statuses = trading_economics(("eu-natural-gas", "coal"), "private-api-key")
    assert len(docs) == 1
    assert docs[0]["unit"] == "EUR/MWh"
    assert docs[0]["series"][0]["value"] == 42.5
    assert docs[0]["warning"] in docs[0]["text"]
    assert any(s["status"] == "Unavailable" for s in statuses)
    assert get.call_args.kwargs["headers"]["Authorization"] == "private-api-key"
    assert "private-api-key" not in get.call_args.args[0]
    assert "private-api-key" not in json.dumps((docs, statuses))


@pytest.mark.parametrize("code", [401, 403, 429, 500])
def test_te_failed_access_returns_safe_status(code):
    with patch("spendwise.market_sources.requests.get", return_value=te_response({}, code)):
        docs, statuses = trading_economics(("coal",), "private-api-key")
    assert not docs
    assert str(code) in statuses[0]["detail"]
    assert "private-api-key" not in json.dumps(statuses)


@pytest.mark.parametrize("value,date", [(None, "2026-01-01"), (float("inf"), "2026-01-01"), (23, "bad")])
def test_te_invalid_observations_not_shown(value, date):
    with patch("spendwise.market_sources.requests.get", return_value=te_response([
        {"URL": "/commodity/coal", "Last": value, "Date": date}
    ])):
        docs, statuses = trading_economics(("coal",), "key")
    assert not docs
    assert statuses[0]["status"] == "Unavailable"


def test_world_bank_filters_missing_values_and_reports_missing_column():
    frame = pd.DataFrame([
        ["Title", None], [None, "Crude oil, Brent"], [None, "($/bbl)"],
        ["2020M01", 50], ["2020M02", ".."], ["2020M03", 55], ["footnote", 100]
    ])
    with patch("spendwise.market_sources.requests.get", return_value=Mock(content=b"workbook")) as get, \
         patch("spendwise.market_sources.pd.read_excel", return_value=frame):
        docs, statuses = world_bank(("BRENT", "COAL"))
    get.assert_called_once()
    assert docs[0]["series"] == [{"date": "2020-01", "value": 50}, {"date": "2020-03", "value": 55}]
    assert docs[0]["unit"] == "USD/barrel"
    assert docs[0]["warning"]
    assert statuses[1]["status"] == "Unavailable"


def test_world_bank_changed_workbook_layout_fails_cleanly():
    with patch("spendwise.market_sources.requests.get", return_value=Mock(content=b"workbook")), \
         patch("spendwise.market_sources.pd.read_excel", return_value=pd.DataFrame([["wrong layout"]])):
        docs, statuses = world_bank(("BRENT",))
    assert not docs
    assert statuses[0]["status"] == "Unavailable"
