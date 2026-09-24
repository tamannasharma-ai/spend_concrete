from pathlib import Path
from streamlit.testing.v1 import AppTest
from unittest.mock import patch

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_demo_launch_and_delay_scenario():
    app = AppTest.from_file(APP, default_timeout=25).run()
    assert not app.exception
    original = int(app.metric[0].value)
    app.slider(key="delay").set_value(20).run()
    assert not app.exception
    assert int(app.metric[0].value) > original


def test_offline_brief_and_stale_detection():
    app = AppTest.from_file(APP, default_timeout=25).run()
    app.button(key="brief_button").click().run()
    assert not app.exception
    assert "no language model used" in app.session_state["brief"]["answer"]
    app.slider(key="safety").set_value(10).run()
    assert any("Inputs changed" in w.value for w in app.warning)


def test_hosted_provider_requires_key_and_free_tier_confirmation():
    app = AppTest.from_file(APP, default_timeout=25).run()
    app.selectbox(key="provider").select("Groq").run()
    assert not app.exception
    assert app.button(key="brief_button").disabled


def test_dbnomics_refresh_brief_and_selection_invalidation():
    doc = {"id": "DBN-DE-C2351", "title": "Cement producer price index", "source": "Eurostat via DBnomics",
           "url": "https://db.nomics.world/Eurostat/sts_inpp_m/M.PRC_PRR.C2351.NSA.I21.DE",
           "retrieved_at": "2026-09-24", "kind": "indicator", "unit": "Index (2021 = 100)",
           "series_code": "M.PRC_PRR.C2351.NSA.I21.DE", "warning": "Historical data: latest observation is 2025-11.",
           "text": "Cement producer prices historical observation 2025-11: 157.7, not a supplier quote.",
           "series": [{"date": "2025-11", "value": 157.7}]}
    app = AppTest.from_file(APP, default_timeout=25).run()
    app.checkbox(key="use_dbnomics").check().run()
    with patch("spendwise.sources.refresh", return_value=([doc], [])):
        app.button(key="refresh").click().run()
    assert not app.exception


def test_world_bank_and_te_sources_remain_session_scoped():
    from spendwise.market_sources import document
    wb = document("WB-BRENT", "Brent oil", "World Bank", "https://www.worldbank.org", "USD/barrel",
                  [{"date": "2026-08", "value": 90}], "Monthly average")
    te = document("TE-COAL", "Coal", "Trading Economics", "https://tradingeconomics.com/commodity/coal", "USD/metric tonne",
                  [{"date": "2026-09-23", "value": 140}], "Single snapshot", monthly=False)
    app = AppTest.from_file(APP, default_timeout=25).run()
    app.checkbox(key="use_wb").check().run()
    app.checkbox(key="use_te").check().run()
    app.text_input(key="te_key").set_value("private-api-key").run()
    with patch("spendwise.sources.refresh", return_value=([], [])), \
         patch("spendwise.market_sources.world_bank", return_value=([wb], [])), \
         patch("spendwise.market_sources.trading_economics", return_value=([te], [])) as fetch:
        app.button(key="refresh").click().run()
        assert fetch.call_args.args[1] == "private-api-key"
        fetch.assert_called_once()
        app.slider(key="safety").set_value(9).run()
        fetch.assert_called_once()
    assert not app.exception
    assert {d["id"] for d in app.session_state["documents"]} == {"WB-BRENT", "TE-COAL"}
    app.text_area(key="question").set_value("Brent oil coal").run()
    app.button(key="brief_button").click().run()
    assert not app.exception
    assert {d["id"] for d in app.session_state["brief"]["evidence"]} >= {"WB-BRENT", "TE-COAL"}
    app.text_input(key="te_key").set_value("replacement-key").run()
    assert not app.session_state["documents"]
    assert app.session_state["brief"] is None
    assert any("Historical data" in w.value for w in app.warning)
    app.button(key="brief_button").click().run()
    assert not app.exception
    assert any(d["id"] == doc["id"] for d in app.session_state["brief"]["evidence"])
    app.multiselect(key="dbnomics_selection").set_value(["B081"]).run()
    assert not app.session_state["documents"]
    assert app.session_state["brief"] is None
    app.session_state["documents"] = [doc]
    app.selectbox(key="country").select("France").run()
    assert not app.session_state["documents"]
    assert not app.exception
