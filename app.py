"""Run: streamlit run app.py"""
import hashlib
import json
import os
from datetime import datetime, timezone
import altair as alt
import pandas as pd
import streamlit as st
from spendwise import demo
from spendwise.agents import MODELS, run_workflow
from spendwise.planning import plan_all, validate_materials, NUMERIC
from spendwise.sources import COUNTRIES, DBNOMICS_INDICATORS, refresh, now
from spendwise.retrieval import retrieve
from spendwise.market_sources import WB_INDICATORS, TE_INDICATORS, world_bank, trading_economics
from spendwise.research import TOPICS, DOMAINS, run_research, report_markdown
from spendwise.intelligence import PROVIDERS, parse_records, fetch_feed, evidence_records

st.set_page_config(page_title="SpendWiseConcreteAI", page_icon=":material/domain:", layout="wide")

DEFAULTS = {"materials": demo.materials(), "data_mode": "Demo", "documents": [], "statuses": [],
            "source_country": "", "source_selection": None, "user_documents": [], "brief": None, "brief_signature": "",
            "research_report": None, "research_documents": [], "research_country": "",
            "external_documents": [], "external_preview": None, "external_statuses": [], "external_use": False}
for name, value in DEFAULTS.items():
    if name not in st.session_state:
        st.session_state[name] = value


@st.cache_data(ttl=3600, max_entries=8, show_spinner=False)
def public_sources(country, dbnomics_indicators=()):
    return refresh(country, dbnomics_indicators)


@st.cache_data(ttl=3600, max_entries=8, show_spinner=False)
def world_bank_sources(selected):
    return world_bank(selected)


def clear_loaded_sources():
    st.session_state.documents = []
    st.session_state.statuses = []
    st.session_state.brief = None


def secret(name):
    try:
        return st.secrets.get(name, os.getenv(name, ""))
    except (FileNotFoundError, KeyError):
        return os.getenv(name, "")


def csv_export(frame):
    # Prevent formula execution if manager-controlled text is opened in Excel.
    clean = frame.copy()
    for col in clean.select_dtypes(include=["object", "string"]).columns:
        clean[col] = clean[col].map(lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v)
    return clean.to_csv(index=False).encode("utf-8-sig")


with st.sidebar:
    st.markdown("### SpendWiseConcreteAI")
    st.caption("PROCUREMENT INTELLIGENCE / EU")
    country_name = st.selectbox("Plant country", list(COUNTRIES), key="country")
    st.caption("Country filters public indicators. It does not change your supplier prices.")
    use_dbnomics = st.checkbox("Include DBnomics indicators", key="use_dbnomics")
    dbnomics_selection = []
    if use_dbnomics:
        dbnomics_selection = st.multiselect(
            "DBnomics indicators", list(DBNOMICS_INDICATORS),
            default=["C2351", "C2363", "B081"],
            format_func=lambda code: DBNOMICS_INDICATORS[code], key="dbnomics_selection")
        st.caption("No API key needed. Coverage varies by country; mirrored data can lag Eurostat. Refresh in Market & evidence to load.")
    use_wb = st.checkbox("Include World Bank commodities", key="use_wb")
    wb_selection = []
    if use_wb:
        wb_selection = st.multiselect("World Bank benchmarks", list(WB_INDICATORS),
                                      default=["BRENT", "EU-GAS", "COAL"],
                                      format_func=lambda code: WB_INDICATORS[code][0], key="wb_selection")
        st.caption("Free monthly Pink Sheet data. Global or regional benchmarks in USD; not plant-specific quotes.")
    use_te = st.checkbox("Include Trading Economics", key="use_te")
    te_selection, te_key = [], ""
    if use_te:
        te_selection = st.multiselect("Trading Economics benchmarks", list(TE_INDICATORS),
                                      default=["brent-crude-oil", "eu-natural-gas", "coal"],
                                      format_func=lambda code: TE_INDICATORS[code][0], key="te_selection")
        te_key = st.text_input("Trading Economics API key", type="password", key="te_key",
                               on_change=clear_loaded_sources) or secret("TRADING_ECONOMICS_API_KEY")
        st.caption("Requires a Trading Economics API plan with commodity access. Refresh makes one API request. Quotes stay in this session; your plan's quota and terms apply.")
    st.divider()
    st.markdown("**Planning assumptions**")
    target = st.slider("Cycle stock target (days)", 7, 60, 28, key="target")
    safety = st.slider("Safety stock (days)", 0, 21, 7, key="safety")
    delay = st.slider("Extra delivery delay (days)", 0, 30, 0, key="delay")
    demand_change = st.slider("Demand change (%)", -100, 100, 0, key="demand_change")
    st.divider()
    provider = st.selectbox("AI provider", ["Offline", "Gemini", "Groq"], key="provider")
    model, key = "", ""
    eligible = False
    if provider != "Offline":
        model = st.selectbox("Model", MODELS[provider], key=f"model_{provider}")
        custom = st.text_input("Model ID override (optional)", key=f"override_{provider}")
        model = custom.strip() or model
        key_name = "GEMINI_API_KEY" if provider == "Gemini" else "GROQ_API_KEY"
        key = st.text_input("API key", type="password", key=f"key_{provider}") or secret(key_name)
        eligible = st.checkbox("I am using a free-tier account/model", key=f"free_{provider}")
        st.caption("Account billing is controlled by your provider. No automatic provider switching. Running a brief sends evidence and procurement figures; running research sends its scope and public evidence.")
    else:
        st.caption("No API key needed. Numerical planning and evidence retrieval work offline; generative AI is off.")

st.caption("SPENDWISE / CONCRETE OPERATIONS")
st.title("Buy with evidence. Build with confidence.")
st.markdown("Your EU concrete procurement workspace. Turn inventory, market signals and supply evidence into a practical buying plan.")
with st.container(horizontal=True):
    st.badge("EU pilot", icon=":material/public:")
    st.badge(f"{st.session_state.data_mode} procurement data", color="orange" if st.session_state.data_mode == "Demo" else "blue")
    st.badge("Manager decision support", color="gray")
if st.session_state.data_mode == "Demo":
    st.info("Demonstration: all suppliers, stock quantities and material prices are synthetic. Public sources become live only after a refresh.", icon=":material/info:")

country_code = COUNTRIES[country_name]
source_selection = (country_code, tuple(sorted(dbnomics_selection)), tuple(sorted(wb_selection)), tuple(sorted(te_selection)))
if st.session_state.source_selection != source_selection:
    st.session_state.documents = []
    st.session_state.statuses = []
    st.session_state.source_country = ""
    st.session_state.brief = None
    st.session_state.source_selection = source_selection

settings = {"target_days": target, "safety_days": safety, "delay_days": delay, "demand_change_pct": demand_change}
plans = plan_all(st.session_state.materials, **settings)
plan_df = pd.DataFrame(plans)
documents = st.session_state.documents + st.session_state.user_documents
if st.session_state.external_use:
    documents += st.session_state.external_documents
if st.session_state.research_country == country_name:
    documents += st.session_state.research_documents
if st.session_state.data_mode == "Demo":
    documents += demo.evidence()
documents = list({d["id"]: d for d in documents}.values())
signature = hashlib.sha256(json.dumps({"plan": plans, "docs": documents, "country": country_code}, sort_keys=True).encode()).hexdigest()

overview, market, research_tab, external_tab, scenario, copilot, data = st.tabs(["Procurement overview", "Market & evidence", "Supply research", "External intelligence", "Scenario planner", "AI briefing", "Data workspace"])

with overview:
    st.subheader("Your next procurement decisions")
    urgent = sum(p["uncovered_demand_t"] > 0 for p in plans)
    now_count = sum(p["action"] == "Order now" for p in plans)
    inventory_value = sum(r.inventory_t * (r.price_eur_t + r.freight_eur_t) for r in st.session_state.materials.itertuples())
    with st.container(horizontal=True):
        st.metric("Materials before stockout", urgent, border=True, help="Demand exceeds current stock before the assumed delivery date.")
        st.metric("Reorder point reached", now_count, border=True)
        st.metric("Inventory at current landed cost", f"€{inventory_value:,.0f}", border=True)
        st.metric("Materials monitored", len(plans), border=True)
    left, right = st.columns([1.4, 1])
    with left:
        st.markdown("#### Inventory coverage vs. delivery lead time")
        plot = plan_df[["material", "coverage_days", "arrival_days"]].rename(columns={"coverage_days": "Inventory coverage", "arrival_days": "Delivery lead + delay"}).melt(id_vars="material", var_name="Measure", value_name="Days").dropna()
        chart = alt.Chart(plot).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("material:N", title="Material", sort=None), x=alt.X("Days:Q", title="Days"),
            yOffset="Measure:N", color=alt.Color("Measure:N", scale=alt.Scale(domain=["Inventory coverage", "Delivery lead + delay"], range=["#087F73", "#C08A48"]), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["material:N", "Measure:N", alt.Tooltip("Days:Q", format=".1f")]).properties(height=300)
        st.altair_chart(chart)
        st.caption("Source: active inventory snapshot and sidebar assumptions. Constant daily demand; excludes open purchase orders.")
    with right:
        st.markdown("#### Attention queue")
        ranked = sorted(plans, key=lambda p: (p["uncovered_demand_t"] > 0, p["action"] == "Order now"), reverse=True)
        for p in ranked[:3]:
            with st.container(border=True):
                st.markdown(f"**{p['material']}**")
                st.markdown(f":{'orange' if p['uncovered_demand_t'] else 'green'}[{p['action']}]")
                st.caption(p["flags"][0] if p["flags"] else f"Review within {p['order_in_days']:.1f} days. Recalculate with a current quote.")
    st.markdown("#### Material plan")
    show = plan_df[["material", "action", "coverage_days", "order_in_days", "quantity_t", "landed_eur_t", "order_cost_eur"]].rename(columns={"material": "Material", "action": "Action", "coverage_days": "Cover (days)", "order_in_days": "Review within (days)", "quantity_t": "Order-now quantity (t)", "landed_eur_t": "Landed price (€/t)", "order_cost_eur": "Order-now cost (€)"})
    st.dataframe(show, hide_index=True, column_config={"Landed price (€/t)": st.column_config.NumberColumn(format="€%.2f"), "Order-now cost (€)": st.column_config.NumberColumn(format="€%.0f"), "Cover (days)": st.column_config.NumberColumn(format="%.1f"), "Review within (days)": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Quantity is a feasible order-placed-today scenario, not an instruction to buy all materials now. Prices exclude tax, duties and carbon costs. No orders are placed.")
    st.download_button("Export current plan", csv_export(show), "spendwise_plan.csv", "text/csv", icon=":material/download:")
    with st.expander("Calculation method and limits"):
        st.markdown("Coverage = stock ÷ adjusted daily demand. Reorder review = coverage − lead time − safety days (floored at zero). Order-now quantity fills projected arrival stock to cycle stock plus safety stock, capped by capacity and subject to MOQ and supplier approval.")
        st.markdown("This MVP assumes constant demand, no open purchase orders, no backlog recovery and one supplier per material. Delay assumptions apply to all materials. It does not forecast geopolitical events, qualify substitute materials, or calculate CBAM liabilities. Validate orders and production needs before using the plan.")

with market:
    st.subheader("Market signals, traceable evidence")
    st.caption("Eurostat: non-metallic mineral producer prices · ECB: EUR/USD · GDACS: global disaster alerts · European Commission: CBAM")
    if dbnomics_selection:
        st.caption("Also selected: Eurostat via DBnomics · " + ", ".join(DBNOMICS_INDICATORS[c] for c in dbnomics_selection))
    if wb_selection:
        st.caption("World Bank Pink Sheet · " + ", ".join(WB_INDICATORS[c][0] for c in wb_selection))
    if te_selection:
        st.caption("Trading Economics snapshots · " + ", ".join(TE_INDICATORS[c][0] for c in te_selection))
        if not te_key:
            st.info("Add a Trading Economics API key in the sidebar to retrieve its quotes. Other selected sources can still refresh.")
    if st.button("Refresh public sources", type="primary", icon=":material/sync:", key="refresh"):
        with st.spinner("Fetching selected sources. Each connector reports its own status…"):
            docs, statuses = public_sources(country_code, source_selection[1])
            wb_docs, wb_statuses = world_bank_sources(source_selection[2])
            # Licensed Trading Economics results are never placed in a shared cache.
            te_docs, te_statuses = trading_economics(source_selection[3], te_key)
            docs = docs + wb_docs + te_docs
            statuses = statuses + wb_statuses + te_statuses
        st.session_state.documents = docs
        st.session_state.statuses = statuses
        st.session_state.source_country = country_code
        st.session_state.brief = None
        st.rerun()
    st.caption("Public responses are cached for one hour. Trading Economics is requested on each refresh and retained only in this session. Retrieval time and observation date are separate.")
    if st.session_state.statuses:
        st.dataframe(pd.DataFrame(st.session_state.statuses), hide_index=True)
    else:
        st.info("Refresh sources to load official indicators. No live figures have been fetched for this session.")
    for doc in st.session_state.documents:
        if doc.get("series"):
            with st.container(border=True):
                st.markdown(f"#### {doc['title']}")
                if doc.get("warning"):
                    st.warning(doc["warning"])
                series = pd.DataFrame(doc["series"])
                latest = series.iloc[-1]
                st.metric(f"Latest observation · {latest['date']} · {doc['unit']}", f"{latest['value']:,.3f}")
                if len(series) > 1:
                    st.line_chart(series, x="date", y="value", x_label="Observation date", y_label=doc["unit"], color="#087F73")
                st.caption(f"Source: {doc['source']} · {series.iloc[0]['date']} to {latest['date']} · retrieved {doc['retrieved_at']}")
                st.markdown(doc["text"])
                st.link_button("Open original source", doc["url"])
                if doc.get("series_code"):
                    st.download_button("Download indicator history", csv_export(series),
                                       f"{doc['id']}.csv", "text/csv", key=f"download_{doc['id']}")
    st.markdown("#### Evidence library")
    query = st.text_input("Find evidence", placeholder="e.g. cement carbon imports or aggregate delivery", key="evidence_query")
    visible = retrieve(query, documents, 12) if query else documents
    for doc in visible:
        with st.expander(f"[{doc['id']}] {doc['title']}"):
            st.caption(f"{doc['source']} · {doc['kind']} · retrieved {doc['retrieved_at']}")
            st.text(doc["text"])
            if doc["url"]:
                st.link_button("Source document", doc["url"], key=f"source_{doc['id']}")
    if query and not visible:
        st.info("No matching evidence. Broaden your query or add a relevant document.")

with scenario:
    st.subheader("Stress-test a purchasing decision")
    st.caption("Scenario analysis, not a price prediction. Adjust assumptions to compare the same purchase quantity.")
    c1, c2 = st.columns(2)
    with c1:
        selected = st.selectbox("Material", st.session_state.materials.material, key="scenario_material")
        price_change = st.slider("Material price change over cycle (%)", -30, 50, 5, key="price_change")
    with c2:
        holding = st.slider("Annual carrying cost (%)", 0, 40, 12, key="holding")
        st.caption("Carrying cost is a user-entered annual financing/storage proxy. Freight stays unchanged in this comparison.")
    comparison = plan_all(st.session_state.materials, **settings, price_change_pct=price_change, holding_pct=holding)
    p = next(x for x in comparison if x["material"] == selected)
    with st.container(horizontal=True):
        st.metric("Order-now quantity", f"{p['quantity_t']:,.1f} t", border=True)
        st.metric("Assumed later material-price increase", f"€{p['scenario_price_delta_eur']:,.0f}", border=True)
        st.metric("Extra early-purchase carrying cost", f"€{p['early_carry_eur']:,.0f}", border=True)
        st.metric("Early-buy advantage under assumptions", f"€{p['scenario_net_advantage_eur']:,.0f}", border=True)
    st.markdown(f"**Inventory action: {p['action']}**")
    for warning in p["flags"]:
        st.warning(warning)
    st.caption(f"Same-lot comparison over {target} days. Advantage = quantity × material price × assumed change − quantity × landed price × annual carrying rate × days/365. This is not expected savings, a forecast, or a complete wait-versus-buy simulation.")
    if p["uncovered_demand_t"]:
        st.error("Waiting is not feasible under these demand and delivery assumptions without alternative supply or a production change.")
    steps = list(range(-20, 31, 5))
    row = st.session_state.materials[st.session_state.materials.material == selected]
    sensitivity = pd.DataFrame([{"Price change (%)": x, "Early-buy advantage (€)": plan_all(row, **settings, price_change_pct=x, holding_pct=holding)[0]["scenario_net_advantage_eur"]} for x in steps])
    st.line_chart(sensitivity, x="Price change (%)", y="Early-buy advantage (€)", color="#087F73")
    st.caption("Sensitivity: same lot, current material quote and fixed freight. Positive values favor buying earlier on these cost assumptions only.")

with copilot:
    st.subheader("An evidence-backed procurement brief")
    st.markdown("Ask about stock exposure, material costs, or the evidence behind a decision. The workflow retrieves evidence, checks indicators and inventory risk, and builds a cited brief.")
    question = st.text_area("Procurement question", "Which materials need attention, and what evidence should I review before buying cement or aggregates?", max_chars=2000, key="question")
    ready = provider == "Offline" or bool(key and eligible)
    if provider != "Offline" and not ready:
        st.info("Add a provider API key and confirm a free-tier account in the sidebar, or select Offline.")
    if st.button("Build procurement brief", type="primary", disabled=not ready, icon=":material/auto_awesome:", key="brief_button"):
        with st.status("Building procurement brief…", expanded=True) as status:
            st.write("Retrieving evidence and running the bounded agent workflow.")
            result = run_workflow(question, documents, plans, provider, model, key)
            result["snapshot"] = {"generated_at": now(), "country": country_name,
                                  "data_mode": st.session_state.data_mode, "assumptions": settings.copy()}
            st.session_state.brief = result
            st.session_state.brief_signature = signature
            status.update(label="Brief ready", state="complete", expanded=False)
    result = st.session_state.brief
    if result:
        if st.session_state.brief_signature != signature:
            st.warning("Inputs changed since this brief. Rebuild it to reflect the current plan.")
        for warning in result.get("warnings", []):
            st.warning(warning)
        st.caption(f"Brief question: {result['question']} · provider: {result['provider']} · model: {result['model'] or 'none'}")
        with st.chat_message("assistant", avatar=":material/domain:"):
            st.markdown(result["answer"])
        with st.expander("Workflow activity and evidence"):
            for entry in result["trace"]:
                st.write(entry)
            for doc in result["evidence"]:
                st.caption(f"[{doc['id']}] {doc['title']} · {doc['retrieved_at']}")
                if doc["url"]:
                    st.link_button("View evidence", doc["url"], key=f"brief_{doc['id']}")
        export = {**result["snapshot"],
                  "question": result["question"], "answer": result["answer"], "plan": result["plan"],
                  "evidence": result["evidence"], "trace": result["trace"], "warnings": result["warnings"]}
        st.download_button("Download brief and audit record", json.dumps(export, ensure_ascii=False, indent=2), "spendwise_brief.json", "application/json")
    st.caption("Offline mode uses lexical retrieval and templates. Hosted mode adds real model tool calling. Citation-ID validation does not certify every narrative claim; review the linked evidence.")

with research_tab:
    st.subheader("Concrete supply research agent")
    st.write("Investigate material availability, disruption signals, and procurement context for your plant country.")
    st.caption("Plan → search → assess coverage → follow up → report. Up to one search per topic plus two follow-ups. Recent searches cover the past year; follow-ups may retrieve older background.")
    search_key = st.text_input("Tavily search API key", type="password", key="research_search_key") or secret("TAVILY_API_KEY")
    st.caption("Uses your Tavily quota. Search queries contain the country, selected topics, and your research focus. Avoid private supplier details in the focus field. Keys and results stay in this session.")
    research_topics = st.multiselect("Research topics", list(TOPICS), default=list(TOPICS), key="research_topics")
    research_focus = st.text_area("Research focus (optional)", max_chars=600, key="research_focus",
                                  placeholder="e.g. European cement imports, low-carbon binder availability, winter logistics")
    st.caption(f"Region: {country_name} · Analysis: {provider}. Offline disables model synthesis, but this research action still searches the web.")
    with st.expander("Source selection and report limits"):
        for category, domains in DOMAINS.items():
            st.write(f"{category}: {', '.join(domains)}")
        st.write("Publisher screening is a credibility heuristic, not a guarantee. Search extracts may be incomplete. Multiple publishers may repeat the same original account. The agent cannot cover every internet source or calculate disruption probabilities.")
    can_research = bool(search_key and research_topics and (provider == "Offline" or (key and eligible)))
    if not search_key:
        st.info("Add a Tavily API key here or set TAVILY_API_KEY in Streamlit secrets to enable live research.")
    if st.button("Run supply research", type="primary", key="research_run", disabled=not can_research):
        progress = st.empty()
        with st.spinner("Researching supply evidence…"):
            try:
                result = run_research(country_name, research_topics, research_focus, search_key,
                                      provider, model, key, progress=progress.info)
                st.session_state.research_report = result
                st.session_state.research_documents = result["evidence"]
                st.session_state.research_country = country_name
                st.session_state.brief = None
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        progress.empty()
    research_result = st.session_state.research_report
    if research_result:
        scope = research_result["scope"]
        if (scope["country"], scope["topics"], scope["focus"]) != (country_name, research_topics, research_focus):
            st.warning("Research inputs changed. This is the previous report; run research again for the current scope.")
        st.caption(f"Report snapshot: {scope['country']} · {scope['as_of']} · {research_result['mode']}")
        for warning in research_result["warnings"]:
            st.warning(warning)
        with st.container(horizontal=True):
            st.metric("Sources retrieved", len(research_result["evidence"]))
            st.metric("Searches used", f"{len(research_result['trace'])} / {research_result['search_budget']}")
            st.metric("Topics with evidence", sum(c["documents"] > 0 for c in research_result["coverage"].values()))
        for finding in research_result["analysis"]["findings"]:
            with st.container(border=True):
                st.markdown(f"#### {finding['topic']}")
                st.write(finding["assessment"])
                st.write("Conditional disruption scenario: " + finding["scenario"])
                st.write("Monitor: " + finding["trigger"])
                st.write("Next action: " + finding["action"])
                st.caption("Sources: " + ", ".join(finding["source_ids"]))
        if not research_result["analysis"]["findings"]:
            st.info("Evidence report only: review the source extracts below. Select Gemini or Groq to generate a cited analysis and conditional disruption scenarios.")
        for gap in research_result["analysis"]["gaps"]:
            st.write("Evidence gap: " + gap)
        for doc in research_result["evidence"]:
            with st.expander(f"[{doc['id']}] {doc['title']}"):
                st.caption(f"{doc['source_type']} · Published: {doc['published_at']} · Retrieved: {doc['retrieved_at']}")
                st.caption(doc["content_type"] + " — source text, not verified conclusions")
                st.text(doc["text"])
                st.link_button("Read original source", doc["url"], key="research_" + doc["id"])
        with st.expander("Research activity and coverage"):
            st.json({"coverage": research_result["coverage"], "searches": research_result["trace"]})
        st.download_button("Download research report", report_markdown(research_result), "spendwise_supply_research.md", "text/markdown", key="research_md")
        st.download_button("Download research evidence and audit", json.dumps(research_result, ensure_ascii=False, indent=2), "spendwise_supply_research.json", "application/json", key="research_json")
        st.caption("Research evidence is also available in Market & evidence and AI briefing for the report's country. Research does not alter inventory calculations. Citation checks do not verify factual support or supplier exposure.")

with external_tab:
    st.subheader("External market intelligence")
    st.write("Bring procurement reports, commodity prices, and supplier intelligence into Spendwise.")
    external_provider = st.selectbox("Data provider", ["World Bank", "Trading Economics"] + list(PROVIDERS), key="external_provider")
    if external_provider in ("World Bank", "Trading Economics"):
        catalog = WB_INDICATORS if external_provider == "World Bank" else TE_INDICATORS
        selected_external = st.multiselect("Benchmarks to fetch", list(catalog), default=list(catalog)[:3],
                                           format_func=lambda c: catalog[c][0], key="external_benchmarks_" + external_provider)
        access_key = ""
        if external_provider == "Trading Economics":
            access_key = st.text_input("Trading Economics access key", type="password", key="external_te_key") or secret("TRADING_ECONOMICS_API_KEY")
            st.caption("API subscription with commodity access required.")
        else:
            st.caption("Ready to fetch · Public monthly Pink Sheet benchmarks. No account needed; public results are cached for one hour.")
        if st.button("Fetch benchmarks", key="external_fetch_benchmarks", disabled=not selected_external or (external_provider == "Trading Economics" and not access_key)):
            with st.spinner("Fetching benchmarks…"):
                fetched, statuses = (world_bank_sources(tuple(selected_external)) if external_provider == "World Bank"
                                      else trading_economics(selected_external, access_key))
            # Replace this provider's previous fetch, including failures; do not present old data as fresh.
            prefix = "WB-" if external_provider == "World Bank" else "TE-"
            st.session_state.external_documents = [d for d in st.session_state.external_documents if not d["id"].startswith(prefix)] + fetched
            st.session_state.external_statuses = statuses
            st.session_state.brief = None
            st.rerun()
    else:
        portal, _ = PROVIDERS[external_provider]
        if portal:
            st.link_button("Open provider portal", portal)
        st.caption("File import is ready. Direct API access requires a provider-issued endpoint and token; no AmplifiPRO API contract is assumed.")
        method = st.radio("Get data", ["Import export", "Configured API"], key="external_method")
        if method == "Import export":
            st.caption("Upload UTF-8 CSV or a JSON array, then map your export columns. Maximum 5 MB / 1,000 records. Price, currency, unit and geography columns can all be included as content.")
            template = 'title,text,date,url\nExample cement market report,Replace with your exported content,2026-09-01,\n'
            st.download_button("Download import template", template, "intelligence_template.csv", "text/csv")
            external_file = st.file_uploader("Provider export", type=["csv", "json"], key="external_file")
            if st.button("Preview export", key="external_preview_file", disabled=external_file is None):
                st.session_state.external_preview = None
                try:
                    frame = parse_records(external_file.getvalue(), external_file.name.rsplit(".", 1)[-1].lower())
                    st.session_state.external_preview = {"provider": external_provider, "frame": frame, "method": method}
                except ValueError as exc:
                    st.error(str(exc))
        else:
            configs = secret("INTELLIGENCE_FEEDS") or {}
            config = dict(configs.get(external_provider, {})) if hasattr(configs, "get") else {}
            api_token = st.text_input("Provider API token", type="password", key="external_api_token_" + external_provider) or config.get("token", "")
            if not config.get("endpoint"):
                st.info("Not connected. When you obtain API access, configure this provider under INTELLIGENCE_FEEDS in Streamlit secrets. See README for the supported contract.")
            if st.button("Fetch provider data", key="external_fetch_api", disabled=not (config.get("endpoint") and api_token)):
                st.session_state.external_preview = None
                try:
                    with st.spinner("Fetching provider data…"):
                        frame = fetch_feed(external_provider, config, api_token)
                    st.session_state.external_preview = {"provider": external_provider, "frame": frame, "method": method}
                except ValueError as exc:
                    st.error(str(exc))
        preview = st.session_state.external_preview
        if preview and preview["provider"] == external_provider and preview["method"] == method:
            frame = preview["frame"]
            st.dataframe(frame.head(20), hide_index=True)
            st.caption(f"{len(frame)} records loaded. Preview shows the first 20. Importing stores the mapped records in this session.")
            columns = list(frame.columns)
            with st.form("external_mapping"):
                title_col = st.selectbox("Title / material column", columns)
                content_cols = st.multiselect("Content columns", columns, default=[c for c in columns if c not in ("title", "date", "url")][:6])
                date_col = st.selectbox("Observation / publication date column", ["(none)"] + columns,
                                        index=columns.index("date") + 1 if "date" in columns else 0)
                url_col = st.selectbox("Original source URL column", ["(none)"] + columns,
                                       index=columns.index("url") + 1 if "url" in columns else 0)
                if st.form_submit_button("Import into intelligence library"):
                    try:
                        imported = evidence_records(frame, external_provider, title_col, content_cols,
                                                    None if date_col == "(none)" else date_col,
                                                    None if url_col == "(none)" else url_col)
                        merged = {d["id"]: d for d in st.session_state.external_documents}
                        merged.update({d["id"]: d for d in imported})
                        if len(merged) > 1000:
                            raise ValueError("Session limit is 1,000 records. Clear the library before importing more.")
                        st.session_state.external_documents = list(merged.values())
                        st.session_state.external_preview = None
                        st.session_state.brief = None
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    for external_status in st.session_state.external_statuses:
        st.caption(f"{external_status['source']}: {external_status['status']} · {external_status['detail']}")
    st.divider()
    st.checkbox("Include external intelligence in evidence search and AI briefing", key="external_use")
    st.caption("When enabled, running a hosted AI briefing sends relevant external records to your selected model. Imported provider labels are user-supplied. Units, geography and dates remain as supplied; inventory prices are not changed.")
    external_docs = st.session_state.external_documents
    st.write(f"{len(external_docs)} records in your session library")
    if external_docs:
        st.dataframe(pd.DataFrame([{k: d.get(k, "") for k in ("title", "source", "published_at", "retrieved_at")} for d in external_docs]), hide_index=True)
        record_index = st.selectbox("Inspect record", range(len(external_docs)), format_func=lambda i: external_docs[i]["title"], key="external_inspect")
        selected_doc = external_docs[record_index]
        st.text(selected_doc["text"])
        if selected_doc.get("series"):
            st.line_chart(pd.DataFrame(selected_doc["series"]), x="date", y="value")
        if selected_doc.get("url"):
            st.link_button(selected_doc.get("link_type", "Original source"), selected_doc["url"])
        st.download_button("Download intelligence library", json.dumps(external_docs, ensure_ascii=False, indent=2), "spendwise_intelligence.json", "application/json")
        if st.button("Clear external intelligence", key="external_clear"):
            st.session_state.external_documents = []
            st.session_state.external_preview = None
            st.session_state.external_statuses = []
            st.session_state.brief = None
            st.rerun()

with data:
    st.subheader("Your plant, your procurement data")
    st.markdown("Upload one row per material, or edit the working snapshot below. All quantities are metric tonnes; prices and freight are EUR per tonne.")
    st.caption("This session does not persist uploads to disk. Download your snapshot before leaving. Open purchase orders, taxes, carbon charges and changing daily demand schedules are not modeled yet.")
    st.download_button("Download CSV template", csv_export(demo.materials()), "spendwise_material_template.csv", "text/csv")
    uploaded = st.file_uploader("Material inventory and quotes (CSV)", type=["csv"], key="material_upload")
    if uploaded and st.button("Load uploaded data", key="load_upload"):
        try:
            uploaded.seek(0)
            frame = validate_materials(pd.read_csv(uploaded))
            st.session_state.materials = frame
            st.session_state.data_mode = "User-provided"
            st.session_state.brief = None
            st.rerun()
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            st.error(f"Cannot load data: {exc}")
    with st.form("edit_materials"):
        edited = st.data_editor(st.session_state.materials, hide_index=True, num_rows="dynamic", key="editor",
                                column_config={col: st.column_config.NumberColumn(min_value=0, format="%.2f") for col in NUMERIC})
        provenance = st.checkbox("These are actual user-provided figures (not edited demo values)")
        if st.form_submit_button("Apply inventory changes"):
            try:
                st.session_state.materials = validate_materials(edited)
                st.session_state.data_mode = "User-provided" if provenance else "Demo"
                st.session_state.brief = None
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.download_button("Download working snapshot", csv_export(st.session_state.materials), "spendwise_inventory.csv", "text/csv")
    if st.button("Restore demo dataset", key="restore_demo"):
        st.session_state.materials = demo.materials()
        st.session_state.data_mode = "Demo"
        st.session_state.brief = None
        st.rerun()
    st.divider()
    st.markdown("#### Add supplier or policy evidence")
    st.caption("Paste a notice or approved internal policy. Label the date and affected supplier in the text. User documents are not independently verified.")
    with st.form("add_document", clear_on_submit=True):
        title = st.text_input("Document title", max_chars=150)
        body = st.text_area("Document text", max_chars=16000)
        if st.form_submit_button("Add to evidence library"):
            if not title.strip() or len(body.strip()) < 30:
                st.error("Provide a title and at least 30 characters of document text.")
            elif len(st.session_state.user_documents) >= 20:
                st.error("Session limit: 20 documents. Clear evidence to start a new set.")
            else:
                doc_id = "USER-" + hashlib.sha256((title + body).encode()).hexdigest()[:8].upper()
                if any(d["id"] == doc_id for d in st.session_state.user_documents):
                    st.info("This document is already in the library.")
                else:
                    st.session_state.user_documents.append({"id": doc_id, "title": title, "text": body,
                                                            "url": "", "source": "User-provided · unverified", "retrieved_at": now(), "kind": "user"})
                    st.session_state.brief = None
                    st.rerun()
    if st.session_state.user_documents and st.button("Clear uploaded evidence", key="clear_evidence"):
        st.session_state.user_documents = []
        st.session_state.brief = None
        st.rerun()

st.divider()
st.caption("SpendWiseConcreteAI · EU pilot MVP · Free-tier AI optional · Evidence supports decisions; managers approve purchases.")
