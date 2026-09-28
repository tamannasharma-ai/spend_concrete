"""Session-scoped imports and administrator-configured intelligence feeds."""
import hashlib
import io
import json
from urllib.parse import urlsplit

import pandas as pd
import requests

from .sources import now

PROVIDERS = {
    "AmplifiPRO": ("https://amplifipro.thesmartcube.com/login", ("thesmartcube.com", "wnsprocurement.com")),
    "ICIS": ("https://www.icis.com", ("icis.com",)),
    "S&P Global": ("https://www.spglobal.com", ("spglobal.com",)),
    "Fastmarkets": ("https://www.fastmarkets.com", ("fastmarkets.com",)),
    "Other provider": ("", ()),
}
MAX_BYTES = 5_000_000
MAX_RECORDS = 1000


def safe_url(value):
    try:
        p = urlsplit(str(value))
        return bool(p.scheme == "https" and p.hostname and not p.username and not p.password
                    and p.port in (None, 443) and not p.query and not p.fragment)
    except ValueError:
        return False


def parse_records(content, file_format, records_path=""):
    if len(content) > MAX_BYTES:
        raise ValueError("Data exceeds the 5 MB limit.")
    try:
        if file_format == "csv":
            frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, nrows=MAX_RECORDS + 1)
        else:
            payload = json.loads(content)
            for part in records_path.split(".") if records_path else []:
                payload = payload[part]
            if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
                raise ValueError("JSON must contain an array of records. Configure records_path for nested API responses.")
            frame = pd.DataFrame(payload)
        if frame.empty or len(frame) > MAX_RECORDS or len(frame.columns) > 50:
            raise ValueError("Provide 1–1,000 records with at most 50 columns.")
        if any(not isinstance(c, str) for c in frame.columns):
            raise ValueError("Column names must be text.")
        return frame.fillna("").astype(str)
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError, KeyError, TypeError) as exc:
        raise ValueError("Cannot read the data. Use UTF-8 CSV or a JSON array of records.") from exc


def fetch_feed(provider, config, token):
    """One GET to a configured vendor host; no redirects or credentials in URLs."""
    if provider not in PROVIDERS or not isinstance(config, dict):
        raise ValueError("Unsupported provider configuration.")
    endpoint = config.get("endpoint", "")
    if not safe_url(endpoint):
        raise ValueError("Configure an HTTPS endpoint without credentials, query string, or fragment.")
    host = urlsplit(endpoint).hostname.lower()
    domains = PROVIDERS[provider][1]
    if not domains or not any(host == d or host.endswith("." + d) for d in domains):
        raise ValueError("Endpoint must belong to the selected provider's supported domain.")
    if not token.strip() or "\n" in token or "\r" in token:
        raise ValueError("Provide a valid API token.")
    auth = config.get("auth", "bearer")
    if auth not in ("bearer", "x-api-key"):
        raise ValueError("Supported authentication: bearer or x-api-key.")
    headers = {"Authorization": "Bearer " + token.strip()} if auth == "bearer" else {"X-API-Key": token.strip()}
    try:
        with requests.get(endpoint, headers=headers, timeout=(8, 30), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError(f"Provider returned HTTP {response.status_code}. Check endpoint, access and quota.")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Provider response exceeds 5 MB.")
                chunks.append(chunk)
        return parse_records(b"".join(chunks), "json", config.get("records_path", ""))
    except requests.RequestException:
        raise ValueError("Provider connection failed. Check connectivity and account configuration.") from None


def evidence_records(frame, provider, title_column, content_columns, date_column=None, url_column=None):
    if provider not in PROVIDERS or title_column not in frame or not content_columns or any(c not in frame for c in content_columns):
        raise ValueError("Select a title and at least one content column.")
    if not 0 < len(frame) <= MAX_RECORDS:
        raise ValueError("Provide 1–1,000 records.")
    documents = {}
    for _, row in frame.iterrows():
        title = str(row[title_column]).strip()[:250]
        text = "\n".join(f"{c}: {row[c]}" for c in content_columns if str(row[c]).strip())[:12000]
        if not title or not text:
            raise ValueError("Every record needs a nonempty title and content. No records were imported.")
        raw_date = str(row[date_column]).strip() if date_column else ""
        date = pd.to_datetime(raw_date, errors="coerce", utc=True) if raw_date else None
        if raw_date and pd.isna(date):
            raise ValueError("An observation/publication date is invalid. Correct it or leave the date mapping empty.")
        observed = date.isoformat() if date is not None else "Unknown"
        raw_url = str(row[url_column]).strip() if url_column else ""
        if raw_url and not safe_url(raw_url):
            raise ValueError("Source links must be HTTPS without credentials, query strings or fragments.")
        url = raw_url or PROVIDERS[provider][0]
        identity = json.dumps([provider, title, text, observed, url], ensure_ascii=False)
        doc_id = "EXT-" + hashlib.sha256(identity.encode()).hexdigest()[:16].upper()
        documents[doc_id] = {"id": doc_id, "title": title, "source": provider,
                             "url": url, "retrieved_at": now(), "published_at": observed,
                             "kind": "external", "text": f"Provider: {provider}. Observation/publication date: {observed}.\n{text}",
                             "provenance": "User-selected provider; imported content is not independently verified.",
                             "link_type": "Record link" if raw_url else "Provider homepage"}
    return list(documents.values())
