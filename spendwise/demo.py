import pandas as pd


def materials():
    return pd.DataFrame([
        ["CEM II cement", "Demo • Rhine Cement", 240, 22, 9, 750, 118, 14, 28, True],
        ["Coarse aggregate 4/20", "Demo • Valley Quarry", 620, 48, 4, 1800, 19, 9, 30, True],
        ["Fine aggregate 0/4", "Demo • River Materials", 180, 32, 7, 1000, 24, 11, 30, True],
        ["GGBS", "Demo • Circular Minerals", 110, 8, 18, 350, 96, 18, 25, True],
        ["PCE admixture", "Demo • ChemSupply EU", 14, 0.55, 14, 32, 1150, 55, 2, True],
    ], columns=["material", "supplier", "inventory_t", "daily_demand_t", "lead_days",
                "capacity_t", "price_eur_t", "freight_eur_t", "moq_t", "approved"])


def evidence():
    return [{"id": "DEMO-1", "title": "Sample supplier delivery notice", "url": "",
             "text": "SYNTHETIC DEMO ONLY. River Materials reports a possible three-day road delivery delay for fine aggregate 0/4 to the demonstration plant. This is not a real supplier event.",
             "source": "Synthetic demonstration", "retrieved_at": "Not applicable", "kind": "demo"},
            {"id": "DEMO-2", "title": "Sample procurement policy", "url": "",
             "text": "SYNTHETIC DEMO ONLY. Use approved suppliers. Maintain seven days of safety stock. Respect silo capacity and minimum order quantity. Manager approval is required before placing an order.",
             "source": "Synthetic demonstration", "retrieved_at": "Not applicable", "kind": "demo"}]
