# SpendWiseConcreteAI

A Streamlit MVP for EU ready-mix concrete procurement. Runs without an API key. Optional Gemini/Groq integrations add bounded model tool calling through a LangGraph workflow.

## Run locally

Use Python 3.12. From this directory on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502
```

Open http://localhost:8502. Start with the labeled demo, refresh official sources, try the scenario planner, and build an offline brief. Import your CSV from Data workspace when ready.

## Features implemented

- Inventory coverage, reorder review, delivery shortfalls, capacity/MOQ and supplier-approval checks.
- Same-lot price/carrying-cost sensitivity analysis; assumptions are not forecasts.
- Official Eurostat C23 total-market producer-price index, ECB EUR/USD, GDACS global alerts and European Commission CBAM page.
- Source retrieval timestamps, latest observation dates, partial-failure reporting and one-hour public-data cache.
- Small lexical BM25-style RAG over official documents and pasted supplier notices. No embedding API charges.
- LangGraph research → indicators → risk → explanation → citation-ID validation workflow.
- Optional Gemini or Groq tool calling with at most three model requests, limited tool calls and deterministic fallback.
- CSV imports/exports, editable snapshots and downloadable JSON brief with evidence and activity log.

## External intelligence module

Open **External intelligence** to fetch World Bank benchmarks without an account,
or Trading Economics with an entitled API key. The same module accepts AmplifiPRO,
ICIS, S&P Global, Fastmarkets, or other provider exports as UTF-8 CSV / JSON arrays.
Preview the records, map title, content, date and URL columns, then import. Include
price, unit, currency and geography as content columns for quantitative exports.
Limits: 5 MB, 1,000 records, 50 columns. Blank required fields and invalid dates
reject the import. Exact duplicate records are merged. Data remains session-scoped.

AmplifiPRO account access is not configured. No native AmplifiPRO API schema has
been verified. The generic adapter supports one HTTPS GET, bearer or X-API-Key
authentication, and a JSON array at a configured dot-separated records path.
No pagination or token refresh is implemented. If your vendor uses a different
contract, its documentation is needed to extend the adapter. There is no portal scraper.

After receiving vendor API documentation, configure `.streamlit/secrets.toml`:

```toml
[INTELLIGENCE_FEEDS.AmplifiPRO]
endpoint = "" # Insert the actual vendor-issued HTTPS endpoint, without a query string.
auth = "bearer" # Or "x-api-key"
records_path = "" # Empty for a top-level array; e.g. "data.items" for a nested array.
token = "" # Alternatively enter the token in the app.
```

Equivalent sections can use quoted provider names such as
`[INTELLIGENCE_FEEDS."S&P Global"]`. Supported host families are listed in
`spendwise/intelligence.py`. Other-provider imports work; custom-host API fetching
is not enabled. Redirects are rejected. Tokens are never stored in evidence exports.

Use **Include external intelligence in evidence search and AI briefing** to make
the library available to the existing briefing workflow. With hosted AI selected,
running a brief sends relevant records to that provider. Imported labels and content
are not independently verified. No unit conversion, local exposure inference, or
inventory price adjustment occurs. Download the library before ending the session.

## Supply research agent

Open **Supply research**, add a `TAVILY_API_KEY`, choose topics, and click **Run supply research**.
The key can also be configured in `.streamlit/secrets.toml` or the environment.
Search uses the [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search).
It requires an account with available search quota; no new Python dependencies are needed.

The agent plans one search per selected topic (cement/clinker, aggregates, SCMs, admixtures,
energy/logistics, water/climate, and trade/regulation), screens results against a curated
publisher list, deduplicates URLs, and runs at most two background follow-ups for topics
with fewer than two publishers. A full run makes at most nine search requests. Initial
searches request the past year; background follow-ups are unrestricted by date. Unknown
publication dates remain explicitly unknown. Publisher count is not independent corroboration.

Select Gemini or Groq in the sidebar for structured findings, conditional disruption
scenarios, monitoring triggers, and actions. One additional model request is made. Every
finding must cite retrieved IDs; malformed or uncited analysis falls back to the evidence
report. This does not validate factual entailment. Offline mode disables model calls but
**Run supply research still uses live search** and produces an evidence report.

Country, topics, and focus are sent to Tavily. Synthesis sends the research scope and public
evidence to the selected model, without inventory or supplier records. Avoid private data
in the focus field. Reports and keys stay in the session; ordinary UI reruns do not repeat
searches. Download Markdown reports and JSON evidence/audits to retain them. Search and
model failures are reported without exposing credentials or substituting invented evidence.

Evidence automatically joins the existing Market & evidence library and AI briefing for
the report's country. Changed research inputs mark the previous snapshot stale; a country
change excludes that report from briefing evidence. Research never changes purchasing math.
Coverage is bounded, not exhaustive; industry accounts can be biased and excerpts incomplete.
Disruption scenarios are conditional, not calibrated probabilities or proven supplier exposure.

## Optional DBnomics indicators

Enable **Include DBnomics indicators** in the sidebar, select the indicators, then click
**Refresh public sources** in **Market & evidence**. No DBnomics account or key is needed.
Available monthly Eurostat producer-price indices cover cement, ready-mixed concrete,
stone/sand/clay (an aggregate proxy), refined petroleum, and electricity/gas/steam.
The selected plant country is used exactly; unavailable country/indicator combinations
report a failure individually while other sources remain available.

The app retains direct Eurostat and its other official feeds. DBnomics is an optional
mirror, not an automatic fallback or independent corroborating source. Its observations
can lag the original source: observations more than three calendar months old show a
historical-data warning, also included in evidence sent to the briefing workflow.
Charts show up to 120 usable monthly observations with CSV downloads. Missing values
are excluded. These indices (2021=100) provide context, not EUR/tonne supplier prices,
forecasts, or automatic changes to procurement calculations.

Responses are cached for one hour per country and indicator selection. Changing either
clears the loaded public evidence and brief; refresh again to load the new selection.

## Free model configuration

Select a provider in the sidebar and supply a key from a free-tier account. Model availability and quotas vary. The model ID is configurable; the supplied choices are starting points, not an entitlement to free usage.

Alternatively, create `.streamlit/secrets.toml` (gitignored):

```toml
GEMINI_API_KEY = "your-key"
GROQ_API_KEY = "your-key"
```

No automatic paid provider fallback is implemented. A billing-enabled key may still incur provider charges; enforce account-level limits. Only click Build procurement brief when comfortable sending the current plan and retrieved evidence to the selected provider. Keys never enter workflow state or exported audit records. No hosted model calls happen in Offline mode.

The local LangGraph package needs no LangSmith service. Do not enable external tracing for confidential data. Ollama and OpenRouter are future integrations, not implemented in this MVP.

## Input contract

One row per material / current supplier. Columns: `material`, `supplier`, `inventory_t`, `daily_demand_t`, `lead_days`, `capacity_t`, `price_eur_t`, `freight_eur_t`, `moq_t`, `approved`.

Quantities: metric tonnes. Price/freight: EUR per tonne, excluding VAT, duty and carbon charges. Lead time: days. `approved`: true/false. Numeric fields must be finite and non-negative, price/capacity positive, stock no greater than capacity. Duplicate materials are rejected.

## Decision boundaries

This MVP uses constant daily demand and a single supplier per material. It does not model open purchase orders, backorders, credit constraints, shelf life, discrete truck sizes, dynamic demand schedules or supplier-route exposure. Confirm these independently before acting. Existing shortfall before a proposed delivery is explicitly flagged and is not repaired by that later delivery.

Order-now quantity tops up projected arrival stock to cycle days plus safety days, bounded by storage and MOQ. The review date is coverage minus lead time and safety days. The hypothetical quantity applies if ordered today, even when the action is Schedule review; recalculate before a later order.

Public indexes are explanatory context, not supplier quotations. Global disaster alerts are not proof of local exposure. The app does not forecast geopolitical events, provide calibrated price probabilities, optimize multiple suppliers, estimate CBAM liabilities or execute purchase orders. Price-trend charts show observations, not predictions.

LLM citations are checked against retrieved source IDs, but this is not a factual entailment or arithmetic verifier. The deterministic plan is authoritative; a manager must review generated explanations. Uploaded documents are unverified. Demo evidence stays labeled synthetic.

## Data and hosting

Private uploads, working data, keys entered in the sidebar and briefs stay in the current Streamlit session; downloads let users retain them. No persistent private database or authentication is configured. Refreshing/restarting a session can discard data. Only public-source results are shared through Streamlit's cache.

To deploy: create a GitHub repository for this directory excluding `.venv`, secrets, and private files. In Streamlit Community Cloud select the repository, `app.py`, and Python 3.12. Set optional API keys in the deployment's secrets settings. The app does not require them. This repository has not been published by this build.

Community Cloud sleeps and is resource-limited. This MVP refreshes on demand, not via a continuous monitoring service. For real confidential operational data, add appropriate access control and durable storage before deploying broadly.

## Verification

```powershell
.\.venv\Scripts\pip.exe install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover stockouts, capacity, supplier approval, invalid data, cost arithmetic, tool-call handling, quota fallback, citation rejection, and Streamlit interactions. Model API tests use mocks; live model inference requires an account key.

## Sources

- Eurostat: https://ec.europa.eu/eurostat/web/query-builder/
- ECB: https://data.ecb.europa.eu/help/api/data-examples
- GDACS: https://www.gdacs.org/feed_reference.aspx
- CBAM: https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-definitive-regime_en
- Gemini: https://ai.google.dev/gemini-api/docs/pricing
- Groq: https://console.groq.com/docs/tool-use/overview
