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

st.set_page_config(page_title="SpendWiseConcreteAI", page_icon=":material/domain:", layout="wide")

DEFAULTS = {"materials": demo.materials(), "data_mode": "Demo", "documents": [], "statuses": [],
            "source_country": "", "source_selection": None, "user_documents": [], "brief": None, "brief_signature": ""}
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
        st.caption("Account billing is controlled by your provider. No automatic provider switching. Selected evidence and procurement figures are sent only when you run the brief.")
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
if st.session_state.data_mode == "Demo":
    documents += demo.evidence()
signature = hashlib.sha256(json.dumps({"plan": plans, "docs": documents, "country": country_code}, sort_keys=True).encode()).hexdigest()

overview, market, scenario, copilot, data = st.tabs(["Procurement overview", "Market & evidence", "Scenario planner", "AI briefing", "Data workspace"])

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
