"""Read-only official EU connectors. Failed sources never become demo data."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import StringIO
import xml.etree.ElementTree as ET
import pandas as pd
import requests
import math
import re
from functools import partial

COUNTRIES = {"Germany": "DE", "France": "FR", "Italy": "IT", "Spain": "ES", "Netherlands": "NL", "Poland": "PL", "Belgium": "BE"}
POLICY_URL = "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-definitive-regime_en"
DBNOMICS_INDICATORS = {
    "C2351": "Cement", "C2363": "Ready-mixed concrete",
    "B081": "Stone, sand and clay (aggregate proxy)",
    "C192": "Refined petroleum products", "D": "Electricity, gas and steam",
}


def dbnomics(country, indicator):
    """Fetch an exact monthly Eurostat series via DBnomics; never substitute geography."""
    if country not in COUNTRIES.values() or indicator not in DBNOMICS_INDICATORS:
        raise ValueError("Unsupported country or indicator")
    code = f"M.PRC_PRR.{indicator}.NSA.I21.{country}"
    url = f"https://api.db.nomics.world/v22/series/Eurostat/sts_inpp_m/{code}"
    data = get(url, {"observations": 1}).json()
    docs = data.get("series", {}).get("docs", [])
    if len(docs) != 1 or docs[0].get("series_code") != code:
        raise ValueError("Requested DBnomics series is unavailable")
    series = docs[0]
    periods, values = series.get("period", []), series.get("value", [])
    if len(periods) != len(values):
        raise ValueError("Mismatched DBnomics observations")
    rows = []
    for period, value in zip(periods, values):
        if not isinstance(period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        rows.append({"date": period, "value": value})
    rows.sort(key=lambda row: row["date"])
    if not rows:
        raise ValueError("No usable DBnomics observations")
    latest = rows[-1]
    today = datetime.now(timezone.utc)
    year, month = map(int, latest["date"].split("-"))
    age = (today.year - year) * 12 + today.month - month
    warning = (f"Historical data: latest observation is {latest['date']}, more than 3 calendar months old. "
               "Check direct Eurostat for newer releases.") if age > 3 else ""
    label = DBNOMICS_INDICATORS[indicator]
    return {"id": f"DBN-{country}-{indicator}", "title": f"{label} producer price index · {country} · DBnomics",
            "source": "Eurostat via DBnomics", "url": f"https://db.nomics.world/Eurostat/sts_inpp_m/{code}",
            "api_url": url, "series_code": code, "retrieved_at": now(), "kind": "indicator",
            "unit": "Index (2021 = 100)", "series": rows[-120:], "latest_observation": latest["date"],
            "warning": warning,
            "text": f"{country}: {label} ({indicator}), monthly total-market producer price index, unadjusted. "
                    f"Latest observation {latest['date']}: {latest['value']} (2021=100). "
                    f"Eurostat data retrieved through DBnomics. {warning} "
                    "Historical market context, not a supplier quote in EUR/t, a forecast, or an automatic purchase-price adjustment."}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(url, params=None):
    response = requests.get(url, params=params, timeout=(8, 22), headers={"User-Agent": "SpendWiseConcreteAI/0.1 (procurement research)"})
    response.raise_for_status()
    if len(response.content) > 8_000_000:
        raise ValueError("Source exceeds size limit")
    return response


def ecb():
    url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
    response = get(url, {"format": "csvdata", "lastNObservations": 90})
    frame = pd.read_csv(StringIO(response.text))
    rows = frame[["TIME_PERIOD", "OBS_VALUE"]].dropna().rename(columns={"TIME_PERIOD": "date", "OBS_VALUE": "value"})
    rows = rows.sort_values("date")
    if rows.empty:
        raise ValueError("No exchange-rate observations")
    latest = rows.iloc[-1]
    return {"id": "ECB-FX", "title": "EUR / USD reference exchange rate", "source": "European Central Bank", "url": response.url,
            "retrieved_at": now(), "kind": "indicator", "unit": "USD per EUR", "series": rows.to_dict("records"),
            "text": f"Latest observed EUR/USD: {latest['value']} USD per EUR on {latest['date']}. Reference rate, not a supplier FX quote. Higher values mean a stronger euro against USD."}


def eurostat(country):
    url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpp_m"
    response = get(url, {"geo": country, "nace_r2": "C23", "indic_bt": "PRC_PRR", "unit": "I21", "s_adj": "NSA", "lastTimePeriod": 36, "lang": "EN"})
    data = response.json()
    if "error" in data:
        raise ValueError("Eurostat rejected dataset filters")
    ids, sizes = data["id"], data["size"]
    if any(size != 1 for key, size in zip(ids, sizes) if key != "time"):
        raise ValueError("Ambiguous Eurostat series; review dataset dimensions")
    positions = data["dimension"]["time"]["category"]["index"]
    positions = positions if isinstance(positions, dict) else {v: i for i, v in enumerate(positions)}
    values = data.get("value", {})
    rows = []
    for date, idx in positions.items():
        value = values.get(str(idx)) if isinstance(values, dict) else values[idx]
        if value is not None:
            rows.append({"date": date, "value": value})
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise ValueError("No observations available for this country/filter")
    latest = rows[-1]
    return {"id": "EU-PPI", "title": f"Non-metallic minerals producer price index · {country}",
            "source": "Eurostat · sts_inpp_m · C23", "url": response.url, "retrieved_at": now(),
            "kind": "indicator", "unit": "Index (2021 = 100)", "series": rows,
            "text": f"{country}: non-metallic mineral products (C23) total-market producer price index, not seasonally adjusted. Latest {latest['date']}: {latest['value']} (2021=100). Broad industry proxy, NOT a cement quote or delivered price. Source observations may be revised."}


def gdacs():
    url = "https://www.gdacs.org/xml/rss.xml"
    response = get(url)
    root = ET.fromstring(response.content)
    items = []
    for item in root.findall("./channel/item")[:12]:
        items.append(" | ".join([item.findtext("title", ""), item.findtext("pubDate", ""), item.findtext("link", "")]))
    if not items:
        raise ValueError("No GDACS feed items returned")
    return {"id": "GDACS", "title": "Global disaster watch · exposure not assessed", "source": "GDACS", "url": url,
            "retrieved_at": now(), "kind": "research", "text": "Global alerts; these do NOT establish exposure for the selected EU plant. Match supplier and route locations before changing a procurement decision.\n" + "\n".join(items)}


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.blocked = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.blocked += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.blocked = max(0, self.blocked - 1)

    def handle_data(self, data):
        if not self.blocked and data.strip():
            self.parts.append(data.strip())


def policy():
    page = get(POLICY_URL)
    parser = PageText()
    parser.feed(page.text)
    content = "\n".join(parser.parts)
    start = content.lower().find("rules and obligations")
    if start >= 0:
        content = content[start:]
    if len(content) < 100:
        raise ValueError("Policy page did not contain usable text")
    return {"id": "EU-CBAM", "title": "CBAM definitive regime · official policy", "source": "European Commission",
            "url": POLICY_URL, "retrieved_at": now(), "kind": "research", "text": content[:16000]}


def refresh(country="DE", dbnomics_indicators=()):
    jobs = {"ECB exchange rates": ecb, "Eurostat producer prices": lambda: eurostat(country),
            "GDACS disaster feed": gdacs, "European Commission CBAM": policy}
    for indicator in dict.fromkeys(dbnomics_indicators):
        if indicator not in DBNOMICS_INDICATORS:
            raise ValueError("Unsupported DBnomics indicator")
        jobs[f"DBnomics · {DBNOMICS_INDICATORS[indicator]}"] = partial(dbnomics, country, indicator)
    documents, statuses = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                doc = future.result()
                documents.append(doc)
                statuses.append({"source": name, "status": "Retrieved · historical" if doc.get("warning") else "Retrieved",
                                 "detail": doc.get("warning") or doc["retrieved_at"]})
            except Exception as exc:
                # Do not expose request internals or confuse failure with fresh data.
                statuses.append({"source": name, "status": "Unavailable", "detail": f"{type(exc).__name__}: retry later or check source availability."})
    return sorted(documents, key=lambda d: d["id"]), sorted(statuses, key=lambda s: s["source"])
