import math
import pandas as pd
import pytest
from spendwise.demo import materials
from spendwise.planning import plan_material, validate_materials


def row(**changes):
    r = materials().iloc[0].to_dict()
    r.update(changes)
    return r


def test_shortfall_is_not_hidden_by_future_order():
    p = plan_material(row(inventory_t=100, daily_demand_t=20, lead_days=8))
    assert p["uncovered_demand_t"] == 60
    assert p["action"] == "Expedite / alternative supply"
    assert p["quantity_t"] > 0
    assert any("does not repair" in flag for flag in p["flags"])


def test_quantity_fits_storage_at_arrival():
    p = plan_material(row(inventory_t=400, daily_demand_t=20, lead_days=5, capacity_t=500))
    assert p["arrival_stock_t"] == 300
    assert p["quantity_t"] == 200
    assert p["arrival_stock_t"] + p["quantity_t"] <= 500


def test_unapproved_supplier_cannot_generate_order():
    p = plan_material(row(approved=False))
    assert p["quantity_t"] == 0
    assert p["action"] == "Approval required"


def test_infeasible_moq_is_blocked():
    p = plan_material(row(capacity_t=250, inventory_t=240, moq_t=400))
    assert p["quantity_t"] == 0
    assert p["action"] == "Resolve capacity / MOQ"


def test_zero_demand_does_not_purchase():
    p = plan_material(row(daily_demand_t=0))
    assert p["coverage_days"] is None
    assert p["quantity_t"] == 0
    assert p["action"] == "No demand"


def test_scenario_price_change_does_not_inflate_freight():
    p = plan_material(row(price_eur_t=100, freight_eur_t=20), price_change_pct=10, holding_pct=0)
    assert p["scenario_price_delta_eur"] == pytest.approx(p["quantity_t"] * 10)
    assert p["scenario_net_advantage_eur"] == p["scenario_price_delta_eur"]


@pytest.mark.parametrize("value", [-1, math.nan, math.inf, "bad"])
def test_reject_invalid_inventory(value):
    with pytest.raises(ValueError):
        validate_materials(pd.DataFrame([row(inventory_t=value)]))


def test_bool_strings_and_duplicates():
    assert not validate_materials(pd.DataFrame([row(approved="false")])).iloc[0].approved
    with pytest.raises(ValueError, match="one row"):
        validate_materials(pd.DataFrame([row(), row()]))
