"""Commodity context from World Bank and authenticated Trading Economics snapshots."""
from datetime import datetime, timezone
from io import BytesIO
import math
import re
from urllib.parse import urlparse

import pandas as pd
import requests

WB_URL = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
WB_INDICATORS = {
    "BRENT": ("Crude oil, Brent", "USD/barrel"),
    "EU-GAS": ("Natural gas, Europe", "USD/MMBtu"),
    "COAL": ("Coal, Australian", "USD/metric tonne"),
    "IRON": ("Iron ore, cfr spot", "USD/dry metric tonne"),
    "ALUMINUM": ("Aluminum", "USD/metric tonne"),
    "COPPER": ("Copper", "USD/metric tonne"),
}
TE_INDICATORS = {
    "brent-crude-oil": ("Brent oil", "USD/barrel"),
    "eu-natural-gas": ("EU natural gas", "EUR/MWh"),
    "coal": ("Coal", "USD/metric tonne"),
    "steel": ("Steel rebar · China", "CNY/metric tonne"),
}


def numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def document(doc_id, label, source, url, unit, rows, context, monthly=True):
    rows = sorted(rows, key=lambda r: r["date"])[-120:]
    if not rows:
        raise ValueError("No usable observations")
    latest = rows[-1]
    today = datetime.now(timezone.utc)
    observed = datetime.fromisoformat(latest["date"] + ("-01" if monthly else "")).replace(tzinfo=timezone.utc)
    old = ((today.year - observed.year) * 12 + today.month - observed.month > 3) if monthly else (today - observed).days > 7
    warning = f"Historical data: latest observation is {latest['date']}. Check the source for newer releases." if old else ""
    return {"id": doc_id, "title": label, "source": source, "url": url,
            "retrieved_at": today.isoformat(timespec="seconds"), "kind": "indicator", "unit": unit,
            "series_code": doc_id, "series": rows, "latest_observation": latest["date"], "warning": warning,
            "text": f"{label}. Latest observation {latest['date']}: {latest['value']} {unit}. {warning} {context} "
                    "Market context only, not a delivered supplier quote, forecast, or automatic adjustment to procurement prices."}


def status(name, doc=None, detail=None):
    return {"source": name, "status": ("Retrieved · historical" if doc.get("warning") else "Retrieved") if doc else "Unavailable",
            "detail": (doc.get("warning") or doc["retrieved_at"]) if doc else detail}


def world_bank(selected):
    """Download once and resolve each selected Pink Sheet series independently."""
    if not selected:
        return [], []
    selected = tuple(dict.fromkeys(selected))
    if any(code not in WB_INDICATORS for code in selected):
        raise ValueError("Unsupported World Bank indicator")
    docs, statuses = [], []
    try:
        response = requests.get(WB_URL, timeout=(8, 30))
        response.raise_for_status()
        if len(response.content) > 8_000_000:
            raise ValueError("Workbook exceeds size limit")
        frame = pd.read_excel(BytesIO(response.content), sheet_name="Monthly Prices", header=None, engine="openpyxl")
        header = next(i for i in range(min(20, len(frame))) if "Crude oil, Brent" in frame.iloc[i].values)
        names = frame.iloc[header].astype(str).str.strip().tolist()
    except Exception:
        return [], [status(f"World Bank · {WB_INDICATORS[c][0]}", detail="Could not read the Pink Sheet. Retry later or check the World Bank source.") for c in selected]
    for code in selected:
        label, unit = WB_INDICATORS[code]
        name = f"World Bank · {label}"
        try:
            col = names.index(label)
            rows = []
            for _, row in frame.iloc[header + 2:].iterrows():
                period = str(row.iloc[0])
                value = numeric(row.iloc[col])
                if re.fullmatch(r"\d{4}M(0[1-9]|1[0-2])", period) and value is not None:
                    rows.append({"date": period.replace("M", "-"), "value": value})
            doc = document(f"WB-{code}", label, "World Bank · Pink Sheet", WB_URL, unit, rows,
                           "Monthly nominal USD benchmark averages. Geography follows the benchmark, not the selected plant. "
                           "Energy provides fuel-cost context; metals provide construction-input context.")
            docs.append(doc)
            statuses.append(status(name, doc))
        except (ValueError, IndexError, TypeError):
            statuses.append(status(name, detail="Selected series is missing or has no usable observations."))
    return docs, statuses


def trading_economics(selected, key):
    """One authorized snapshot request; credentials never enter URLs or returned records."""
    if not selected:
        return [], []
    selected = tuple(dict.fromkeys(selected))
    if any(code not in TE_INDICATORS for code in selected):
        raise ValueError("Unsupported Trading Economics indicator")
    def failed(detail):
        return [], [status(f"Trading Economics · {TE_INDICATORS[c][0]}", detail=detail) for c in selected]
    if not key.strip():
        return failed("Add a Trading Economics API key with commodity access in the sidebar.")
    try:
        response = requests.get("https://api.tradingeconomics.com/markets/commodities",
                                headers={"Authorization": key.strip()}, params={"f": "json"}, timeout=(8, 30))
        if response.status_code != 200:
            return failed(f"Trading Economics HTTP {response.status_code}. Check API credentials, plan access, or quota.")
        if len(response.content) > 8_000_000:
            return failed("Trading Economics response exceeds size limit.")
        payload = response.json()
        if not isinstance(payload, list):
            return failed("Unexpected Trading Economics response. Check your API plan.")
    except (requests.RequestException, ValueError):
        return failed("Trading Economics connection or response failed. Retry later.")
    docs, statuses = [], []
    for code in selected:
        label, unit = TE_INDICATORS[code]
        name = f"Trading Economics · {label}"
        matches = [r for r in payload if isinstance(r, dict) and
                   urlparse(str(r.get("URL", ""))).path.rstrip("/").lower() == f"/commodity/{code}"]
        try:
            if len(matches) != 1:
                raise ValueError("Missing or ambiguous benchmark")
            row = matches[0]
            value = numeric(row.get("Last"))
            date = pd.to_datetime(row.get("Date"), errors="coerce", utc=True)
            if value is None or pd.isna(date):
                raise ValueError("Missing quote or observation date")
            doc = document("TE-" + code.upper(), label, "Trading Economics · market snapshot",
                           f"https://tradingeconomics.com/commodity/{code}", unit,
                           [{"date": date.strftime("%Y-%m-%d"), "value": value}],
                           "Single market snapshot, not a historical series or monthly average. "
                           "OTC/CFD market reference; geography and currency follow the benchmark. "
                           "No conversion to EUR or inference of local supplier exposure.", monthly=False)
            docs.append(doc)
            statuses.append(status(name, doc))
        except (ValueError, TypeError):
            statuses.append(status(name, detail="Selected benchmark is missing, ambiguous, or has no dated numeric quote. Check plan coverage."))
    return docs, statuses
