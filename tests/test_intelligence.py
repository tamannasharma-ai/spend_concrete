import json
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from spendwise.intelligence import parse_records, evidence_records, fetch_feed


def test_import_mapping_provenance_and_deduplication():
    frame = parse_records(b'title,price,unit,date\nCement,90,EUR/t,2026-09-01\nCement,90,EUR/t,2026-09-01\n', 'csv')
    docs = evidence_records(frame, "AmplifiPRO", "title", ["price", "unit"], "date")
    assert len(docs) == 1
    assert "EUR/t" in docs[0]["text"]
    assert "2026-09-01" in docs[0]["text"]
    assert docs[0]["source"] == "AmplifiPRO"
    assert docs[0]["link_type"] == "Provider homepage"


def test_import_failures_are_atomic():
    for raw in [b'[]', b'{}', b'bad-json']:
        with pytest.raises(ValueError):
            parse_records(raw, 'json')
    frame = pd.DataFrame([{"title": "Cement", "text": "data", "date": "bad-date"}])
    with pytest.raises(ValueError):
        evidence_records(frame, "AmplifiPRO", "title", ["text"], "date")
    frame["url"] = "https://example.com/?api_key=secret"
    with pytest.raises(ValueError):
        evidence_records(frame, "AmplifiPRO", "title", ["text"], url_column="url")


def test_configured_api_nested_records_and_credentials():
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b'{"data":{"items":[{"title":"Cement","text":"Market report"}]}}']
    config = {"endpoint": "https://amplifipro.thesmartcube.com/example", "records_path": "data.items"}
    with patch("spendwise.intelligence.requests.get", return_value=response) as get:
        frame = fetch_feed("AmplifiPRO", config, "secret-token")
    assert len(frame) == 1
    assert get.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer secret-token"}
    assert "secret-token" not in frame.to_json()


def test_api_rejects_wrong_hosts_redirects_and_sanitizes_errors():
    with patch("spendwise.intelligence.requests.get") as get:
        for endpoint in ["http://amplifipro.thesmartcube.com/data", "https://localhost/data", "https://thesmartcube.com.evil.com/data", "https://thesmartcube.com/data?key=secret"]:
            with pytest.raises(ValueError):
                fetch_feed("AmplifiPRO", {"endpoint": endpoint}, "token")
        get.assert_not_called()
    with patch("spendwise.intelligence.requests.get", side_effect=requests.Timeout("secret-token")):
        with pytest.raises(ValueError, match="Provider connection failed") as error:
            fetch_feed("AmplifiPRO", {"endpoint": "https://amplifipro.thesmartcube.com/data"}, "secret-token")
        assert "secret-token" not in str(error.value)
