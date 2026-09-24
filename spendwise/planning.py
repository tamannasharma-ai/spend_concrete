"""Deterministic, unit-explicit inventory planning. No LLM arithmetic."""
import math
import pandas as pd

REQUIRED = ["material", "supplier", "inventory_t", "daily_demand_t", "lead_days",
            "capacity_t", "price_eur_t", "freight_eur_t", "moq_t", "approved"]
NUMERIC = REQUIRED[2:-1]


def validate_materials(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    df = frame[REQUIRED].copy()
    if df.empty or len(df) > 500:
        raise ValueError("Provide between 1 and 500 material rows.")
    for col in ("material", "supplier"):
        if df[col].isna().any() or df[col].astype(str).str.strip().eq("").any():
            raise ValueError(f"{col} must not be blank.")
        df[col] = df[col].astype(str).str.strip()
    if df.material.duplicated().any():
        raise ValueError("Use one row per material; choose its current approved supplier.")
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if not df[col].map(lambda x: pd.notna(x) and math.isfinite(x) and x >= 0).all():
            raise ValueError(f"{col} must contain finite, non-negative numbers.")
    if (df.capacity_t <= 0).any() or (df.price_eur_t <= 0).any():
        raise ValueError("Capacity and material price must be positive.")
    if (df.inventory_t > df.capacity_t).any():
        raise ValueError("Inventory cannot exceed storage capacity.")
    normalized = df.approved.astype(str).str.lower().str.strip()
    if not normalized.isin(["true", "false", "1", "0", "yes", "no"]).all():
        raise ValueError("approved must be true or false.")
    df["approved"] = normalized.isin(["true", "1", "yes"])
    return df


def plan_material(row: dict, target_days=28, safety_days=7, delay_days=0,
                  price_change_pct=0, holding_pct=12, demand_change_pct=0) -> dict:
    values = [target_days, safety_days, delay_days, price_change_pct, holding_pct, demand_change_pct]
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError("Scenario inputs must be finite.")
    if min(target_days, safety_days, delay_days, holding_pct) < 0 or min(price_change_pct, demand_change_pct) < -100:
        raise ValueError("Invalid scenario input.")
    r = validate_materials(pd.DataFrame([row])).iloc[0].to_dict()
    demand = r["daily_demand_t"] * (1 + demand_change_pct / 100)
    lead = r["lead_days"] + delay_days
    stock = r["inventory_t"]
    cover = stock / demand if demand else None
    at_arrival = max(0, stock - demand * lead)
    target_stock = min(r["capacity_t"], demand * (target_days + safety_days))
    need = max(0, target_stock - at_arrival) if demand else 0
    room = r["capacity_t"] - at_arrival
    proposed = max(need, r["moq_t"]) if need else 0
    feasible = proposed <= room
    qty = proposed if feasible and r["approved"] else 0
    shortfall = max(0, demand * lead - stock)
    order_in = max(0, (cover or 0) - lead - safety_days) if demand else 0
    flags = []
    if not r["approved"]:
        action = "Approval required"
        flags.append("Supplier is not approved. No purchase quantity is authorized.")
    elif not demand:
        action = "No demand"
    elif not feasible:
        action = "Resolve capacity / MOQ"
        flags.append("Minimum order exceeds available storage at arrival; negotiate split deliveries.")
    elif shortfall > 0:
        action = "Expedite / alternative supply"
    elif order_in <= 0:
        action = "Order now"
    else:
        action = "Schedule review"
    if shortfall > 0:
        flags.append(f"Normal arrival leaves {shortfall:,.1f} t of demand uncovered. Proposed quantity does not repair this earlier shortfall.")
    if demand * safety_days > r["capacity_t"]:
        flags.append("Storage cannot hold the requested safety stock.")
    if target_stock < demand * (target_days + safety_days):
        flags.append("Target coverage is capped by storage; plan more frequent deliveries.")
    landed = r["price_eur_t"] + r["freight_eur_t"]
    # Same-lot comparison: price scenario applies to material component only.
    # Financing/storage proxy assumes the whole lot is held an extra target_days.
    early_carry = qty * landed * holding_pct / 100 * target_days / 365
    price_delta = qty * r["price_eur_t"] * price_change_pct / 100
    return {
        "material": r["material"], "supplier": r["supplier"], "action": action,
        "coverage_days": cover, "order_in_days": order_in, "arrival_days": lead,
        "uncovered_demand_t": shortfall, "quantity_t": round(qty, 2),
        "landed_eur_t": round(landed, 2), "order_cost_eur": round(qty * landed, 2),
        "arrival_stock_t": round(at_arrival, 2), "capacity_t": r["capacity_t"],
        "scenario_price_delta_eur": round(price_delta, 2), "early_carry_eur": round(early_carry, 2),
        "scenario_net_advantage_eur": round(price_delta - early_carry, 2),
        "flags": flags,
    }


def plan_all(frame, **kwargs):
    return [plan_material(row, **kwargs) for row in validate_materials(frame).to_dict("records")]
