import json
from unittest.mock import Mock, patch

import pytest
import requests

from spendwise.research import (TOPICS, normalize_results, report_markdown, run_research,
                                search_web, source_type, validate_analysis, synthesize)


def result(url="https://www.usgs.gov/cement", **kwargs):
    return {"url": url, "title": "Cement supply", "content": "Cement production and supply background. " * 10, **kwargs}


def test_source_screening_and_deduplication():
    assert source_type("https://ec.europa.eu/report") == "Official / public institution"
    for url in ["https://usgs.gov.evil.com/x", "http://usgs.gov/x", "https://localhost/x", "https://user@usgs.gov/x", "https://usgs.gov:888/x"]:
        assert source_type(url) is None
    with patch("spendwise.research.search_web", return_value=[result(), result()]):
        report = run_research("Germany", list(TOPICS)[:2], search_key="private-key")
    assert len(report["evidence"]) == 1
    assert len(report["evidence"][0]["topics"]) == 2
    assert len(report["trace"]) == 4
    assert "private-key" not in json.dumps(report)
    assert report["analysis"]["gaps"]
    assert "Source register" in report_markdown(report)


def test_followups_only_for_sparse_coverage_and_no_model_offline():
    with patch("spendwise.research.search_web", return_value=[result(), result("https://iea.org/cement")]) as search, \
         patch("spendwise.research.synthesize") as model:
        report = run_research("France", ["Cement & clinker"], search_key="key")
    assert search.call_count == 1
    assert not model.called
    assert report["coverage"]["Cement & clinker"]["publishers"] == 2


def test_partial_and_total_failure_keep_honest_report():
    with patch("spendwise.research.search_web", side_effect=requests.Timeout("secret-key")):
        report = run_research("Germany", list(TOPICS), search_key="secret-key")
    assert len(report["trace"]) == 9
    assert not report["evidence"]
    assert "secret-key" not in json.dumps(report)
    assert any("No usable evidence" in w for w in report["warnings"])
    with patch("spendwise.research.search_web", side_effect=[[result()], requests.Timeout(), []]):
        report = run_research("Germany", ["Cement & clinker"], search_key="key")
    assert report["evidence"] and report["warnings"]


def test_model_failure_preserves_evidence():
    with patch("spendwise.research.search_web", return_value=[result()]), \
         patch("spendwise.research.synthesize", side_effect=ValueError("bad citation")):
        report = run_research("Germany", ["Cement & clinker"], search_key="key", provider="Groq", model_key="secret")
    assert report["evidence"]
    assert not report["analysis"]["findings"]
    assert any("citations" in w for w in report["warnings"])


def test_citations_must_be_known_and_nonempty():
    finding = dict.fromkeys(["topic", "assessment", "scenario", "trigger", "action"], "some text")
    for ids in [[], ["WEB-UNKNOWN"], "WEB-KNOWN", [None]]:
        with pytest.raises(ValueError):
            validate_analysis({"findings": [{**finding, "source_ids": ids}], "gaps": []}, {"WEB-KNOWN"})
    validate_analysis({"findings": [{**finding, "source_ids": ["WEB-KNOWN"]}], "gaps": []}, {"WEB-KNOWN"})


def test_search_request_and_missing_dates():
    response = Mock(status_code=200)
    response.json.return_value = {"results": [result()]}
    with patch("spendwise.research.requests.post", return_value=response) as post:
        docs = normalize_results(search_web("cement", "key"), "Cement & clinker")
    assert docs[0]["published_at"] == "Unknown"
    assert docs[0]["content_type"] == "Search excerpt"
    assert post.call_args.kwargs["json"]["time_range"] == "year"
    assert post.call_args.kwargs["json"]["include_domains"]
    with pytest.raises(ValueError):
        run_research("Germany", ["Cement & clinker"])


def test_synthesis_request_and_cited_response():
    docs = normalize_results([result()], "Cement & clinker")
    finding = dict.fromkeys(["topic", "assessment", "scenario", "trigger", "action"], "Sample assessment")
    finding["source_ids"] = [docs[0]["id"]]
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": json.dumps({"findings": [finding], "gaps": []})}}]}
    with patch("spendwise.research.requests.post", return_value=response) as post:
        analysis = synthesize({"topics": ["Cement & clinker"]}, docs, "Groq", "model", "secret")
    assert analysis["findings"][0]["source_ids"] == [docs[0]["id"]]
    payload = post.call_args.kwargs["json"]
    assert "secret" not in json.dumps(payload)
    assert "untrusted" in payload["messages"][0]["content"]
