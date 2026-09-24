import json
from unittest.mock import patch, Mock
from spendwise.agents import run_workflow, call_model
from spendwise.demo import materials, evidence
from spendwise.planning import plan_all


def test_offline_workflow_never_calls_model():
    with patch("spendwise.agents.requests.post") as post:
        result = run_workflow("aggregate delivery", evidence(), plan_all(materials()))
    post.assert_not_called()
    assert "no language model used" in result["answer"]
    assert result["evidence"][0]["id"] == "DEMO-1"
    assert len(result["trace"]) == 6


def test_tool_round_trip():
    first = Mock(status_code=200)
    first.json.return_value = {"choices": [{"message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "get_procurement_plan", "arguments": "{}"}}]}}]}
    second = Mock(status_code=200)
    second.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "Review supplier delivery [DEMO-1]."}}]}
    with patch("spendwise.agents.requests.post", side_effect=[first, second]) as post:
        text, trace = call_model("Groq", "llama-3.3-70b-versatile", "test-key", "delivery", evidence(), plan_all(materials()))
    assert "[DEMO-1]" in text
    assert len(trace) == 1
    sent = post.call_args.kwargs["json"]["messages"]
    assert any(m["role"] == "tool" for m in sent)


def test_rate_limit_uses_offline_fallback():
    with patch("spendwise.agents.requests.post", return_value=Mock(status_code=429)):
        result = run_workflow("delivery", evidence(), plan_all(materials()), "Groq", "test-model", "secret")
    assert "no language model used" in result["answer"]
    assert "429" in result["warnings"][0]
    assert "secret" not in json.dumps(result)


def test_unknown_citation_withholds_answer():
    with patch("spendwise.agents.call_model", return_value=("Prices rise [FAKE-123]", [])):
        result = run_workflow("delivery", evidence(), plan_all(materials()), "Groq", "test-model", "secret")
    assert "withheld" in result["answer"]
