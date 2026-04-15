from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nbformat
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from nbclient import NotebookClient

# ============================================================
# AT&T Forecasting - Single File Dashboard App
# Place this file in the same folder as:
#   1) ATT_Capstone_Three_Statement_Model_v6_Dashboard_Backend.ipynb
#   2) T_quarterly_statements*.xlsx
#   3) ATNT_Price_Mix*.xlsx
# Run with:
#   streamlit run att_forecasting_single_file.py
# ============================================================

ROOT_DIR = Path(__file__).resolve().parent
NOTEBOOK_NAME = "ATT_Capstone_Three_Statement_Model_v6_Dashboard_Backend.ipynb"
NOTEBOOK_PATH = ROOT_DIR / NOTEBOOK_NAME
DASHBOARD_INPUT_FILE = ROOT_DIR / "dashboard_inputs.json"
EXECUTED_NOTEBOOK_PATH = ROOT_DIR / "executed_dashboard_run.ipynb"

SCENARIOS = [
    "base",
    "downside",
    "upside",
    "energy_cost_strain",
    "interest_rate_strain",
    "custom",
]
FORECAST_YEARS = [2026, 2027, 2028]

INPUT_SCHEMA: dict[str, dict[str, Any]] = {
    "MobilityGrowth": {"min": -0.50, "max": 0.60, "description": "Annual Mobility revenue growth"},
    "BusinessWirelineGrowth": {"min": -0.50, "max": 0.30, "description": "Annual Business Wireline revenue growth"},
    "ConsumerWirelineGrowth": {"min": -0.50, "max": 0.30, "description": "Annual Consumer Wireline revenue growth"},
    "LatinAmericaGrowth": {"min": -0.50, "max": 0.40, "description": "Annual Latin America revenue growth"},
    "OtherRevenueGrowth": {"min": -0.50, "max": 0.30, "description": "Annual Other revenue growth"},
    "InterestRate": {"min": 0.00, "max": 0.20, "description": "Average interest rate applied to average debt"},
    "EBITDA_Margin": {"min": 0.10, "max": 0.60, "description": "EBITDA as a percent of revenue"},
    "DebtAmortizationPct": {"min": 0.00, "max": 0.25, "description": "Mandatory annual debt amortization as a percent of beginning debt"},
    "ExcessCashSweepPct": {"min": 0.00, "max": 1.00, "description": "Percent of excess cash used to repay debt"},
    "CashFloor": {"min": 0.0, "max": 100e9, "description": "Minimum ending cash balance"},
}

st.set_page_config(page_title="AT&T Forecasting", page_icon="📈", layout="wide")


def fmt_billions(value: float) -> str:
    return f"${value / 1e9:,.2f}B"


def to_billions(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") / 1e9
    return out


def write_dashboard_payload(payload: dict[str, Any]) -> None:
    DASHBOARD_INPUT_FILE.write_text(json.dumps(payload, indent=2))


def execute_model() -> Path:
    if not NOTEBOOK_PATH.exists():
        raise FileNotFoundError(
            f"Notebook not found: {NOTEBOOK_PATH.name}. Put this Python file in the same folder as the notebook."
        )

    with NOTEBOOK_PATH.open("r", encoding="utf-8") as f:
        notebook = nbformat.read(f, as_version=4)

    client = NotebookClient(
        notebook,
        timeout=1800,
        kernel_name="python3",
        resources={"metadata": {"path": str(ROOT_DIR)}},
        allow_errors=False,
    )
    client.execute()

    with EXECUTED_NOTEBOOK_PATH.open("w", encoding="utf-8") as f:
        nbformat.write(notebook, f)

    output_dirs = sorted(ROOT_DIR.glob("capstone_outputs_ATT_*"), key=lambda p: p.stat().st_mtime)
    if not output_dirs:
        raise FileNotFoundError(
            "No capstone output folders were created. Make sure the required Excel source files are in the same folder."
        )
    return output_dirs[-1]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Expected file not found: {path.name}")
    return pd.read_csv(path)


def load_run_bundle(output_dir: Path) -> dict[str, Any]:
    authoritative = output_dir / "authoritative"
    dashboard = output_dir / "dashboard"
    diagnostics = output_dir / "diagnostics"
    docs = output_dir / "docs"

    bundle: dict[str, Any] = {
        "output_dir": output_dir,
        "dashboard_feed": read_csv(dashboard / "dashboard_feed.csv"),
        "kpi_table": read_csv(dashboard / "kpi_table.csv"),
        "scenario_meta": read_csv(authoritative / "scenario_meta.csv"),
        "scenario_registry": read_csv(authoritative / "scenario_registry.csv"),
        "forecast_long": read_csv(authoritative / "forecast_long.csv"),
        "forecast_statements_long": read_csv(authoritative / "forecast_statements_long.csv"),
        "diagnostic_table": read_csv(diagnostics / "diagnostic_table.csv"),
        "run_manifest": read_csv(docs / "run_manifest.csv"),
    }

    statement_names = ["income_statement", "balance_sheet", "cash_flow"]
    statements: dict[str, dict[str, pd.DataFrame]] = {}
    for scenario in SCENARIOS:
        statements[scenario] = {}
        for statement_name in statement_names:
            file_path = authoritative / f"{scenario}_forecast_{statement_name}.csv"
            if file_path.exists():
                statements[scenario][statement_name] = read_csv(file_path)
    bundle["statements"] = statements
    return bundle


def build_payload(
    scenario_label: str,
    run_all_scenarios: bool,
    custom_overrides: dict[str, dict[int, float]],
) -> dict[str, Any]:
    cleaned = {
        key: {str(year): float(value) for year, value in values.items()}
        for key, values in custom_overrides.items()
        if values
    }
    return {
        "scenario_label": scenario_label,
        "run_all_scenarios": bool(run_all_scenarios),
        "custom_overrides": cleaned,
    }


def build_custom_override_form() -> dict[str, dict[int, float]]:
    st.sidebar.markdown("### Custom Scenario Inputs")
    st.sidebar.caption(
        "These fields feed the notebook's custom scenario without changing the underlying model code."
    )

    overrides: dict[str, dict[int, float]] = {}
    for assumption, schema in INPUT_SCHEMA.items():
        with st.sidebar.expander(assumption, expanded=False):
            st.caption(schema["description"])
            yearly_values: dict[int, float] = {}
            for year in FORECAST_YEARS:
                default_value = 0.0 if assumption != "CashFloor" else 5_000_000_000.0
                value = st.number_input(
                    f"{assumption} — {year}",
                    min_value=float(schema["min"]),
                    max_value=float(schema["max"]),
                    value=float(default_value),
                    step=(0.005 if assumption != "CashFloor" else 100_000_000.0),
                    format=("%.3f" if assumption != "CashFloor" else "%.0f"),
                    key=f"{assumption}_{year}",
                )
                yearly_values[year] = value
            use_input = st.checkbox(f"Apply {assumption}", value=False, key=f"use_{assumption}")
            if use_input:
                overrides[assumption] = yearly_values
    return overrides


def statement_chart(statement_df: pd.DataFrame, statement_name: str):
    years = [c for c in statement_df.columns if str(c) != "Line Item"]
    long_df = statement_df.melt(id_vars=["Line Item"], value_vars=years, var_name="Year", value_name="Value")
    long_df["Year"] = long_df["Year"].astype(str)
    fig = px.line(
        long_df,
        x="Year",
        y="Value",
        color="Line Item",
        markers=True,
        title=f"AT&T Forecasting — {statement_name}",
    )
    fig.update_layout(height=500, legend_title_text="Line Item")
    return fig


def kpi_cards(kpi_df: pd.DataFrame, selected_scenario: str):
    row = kpi_df[kpi_df["Scenario"] == selected_scenario]
    if row.empty:
        st.warning("No KPI row found for the selected scenario.")
        return
    row = row.iloc[0]
    cols = st.columns(6)
    cols[0].metric("2028 Revenue", fmt_billions(row["Revenue_2028"]))
    cols[1].metric("2028 EBITDA", fmt_billions(row["EBITDA_2028"]))
    cols[2].metric("2028 Net Income", fmt_billions(row["NetIncome_2028"]))
    cols[3].metric("2028 CFO", fmt_billions(row["CFO_2028"]))
    cols[4].metric("2028 Cash", fmt_billions(row["Cash_2028"]))
    cols[5].metric("2028 Total Debt", fmt_billions(row["TotalDebt_2028"]))


def comparison_chart(feed_df: pd.DataFrame):
    latest = feed_df.copy()
    latest["Year"] = latest["Year"].astype(int)
    latest = latest.sort_values(["Scenario", "Year"]).groupby("Scenario", as_index=False).tail(1)
    latest = to_billions(latest, ["Revenue", "EBITDA", "NetIncome", "CFO", "Cash", "TotalDebt"])
    fig = go.Figure()
    fig.add_bar(x=latest["Scenario"], y=latest["Revenue"], name="Revenue")
    fig.add_bar(x=latest["Scenario"], y=latest["EBITDA"], name="EBITDA")
    fig.update_layout(
        barmode="group",
        title="AT&T Forecasting — Final Year Scenario Comparison",
        yaxis_title="USD Billions",
        height=450,
    )
    return fig


def render_statement_section(bundle: dict[str, Any], selected_scenario: str):
    statement_map = {
        "income_statement": "Income Statement",
        "balance_sheet": "Balance Sheet",
        "cash_flow": "Statement of Cash Flows",
    }
    tabs = st.tabs([statement_map[k] for k in statement_map])
    for tab, key in zip(tabs, statement_map):
        with tab:
            statement_df = bundle["statements"].get(selected_scenario, {}).get(key)
            if statement_df is None:
                st.info(f"No {statement_map[key]} file was generated for {selected_scenario}.")
                continue
            numeric_cols = [c for c in statement_df.columns if c != "Line Item"]
            display_df = statement_df.copy()
            for col in numeric_cols:
                display_df[col] = pd.to_numeric(display_df[col], errors="coerce")
            st.plotly_chart(statement_chart(display_df, statement_map[key]), use_container_width=True)
            st.dataframe(display_df.style.format({c: "{:,.2f}" for c in numeric_cols}), use_container_width=True)


def render_diagnostics(bundle: dict[str, Any]):
    st.subheader("Diagnostics")
    st.dataframe(bundle["diagnostic_table"], use_container_width=True)
    st.subheader("Run Manifest")
    st.dataframe(bundle["run_manifest"], use_container_width=True)


def render_history(feed_df: pd.DataFrame, selected_scenario: str):
    scenario_df = feed_df[feed_df["Scenario"] == selected_scenario].copy()
    if scenario_df.empty:
        return
    scenario_df = to_billions(scenario_df, ["Revenue", "EBITDA", "NetIncome", "CFO", "Cash", "TotalDebt"])
    fig = px.line(
        scenario_df,
        x="Year",
        y=["Revenue", "EBITDA", "NetIncome", "CFO", "Cash", "TotalDebt"],
        markers=True,
        title=f"AT&T Forecasting — {selected_scenario} Trend View",
    )
    fig.update_layout(height=500, yaxis_title="USD Billions")
    st.plotly_chart(fig, use_container_width=True)


st.title("AT&T Forecasting")
st.caption("Interactive dashboard wrapper for the existing AT&T three-statement model notebook.")

with st.sidebar:
    st.header("Run Controls")
    selected_scenario = st.selectbox("Display scenario", SCENARIOS, index=0)
    run_all_scenarios = st.toggle("Run all scenarios", value=True)
    run_notebook = st.button("Run forecast engine", type="primary", use_container_width=True)
    st.markdown("---")
    st.markdown(f"**Folder:** `{ROOT_DIR.name}`")
    st.markdown(f"**Notebook expected:** `{NOTEBOOK_NAME}`")

custom_overrides = build_custom_override_form()

if run_notebook:
    payload = build_payload(
        scenario_label=selected_scenario,
        run_all_scenarios=run_all_scenarios,
        custom_overrides=custom_overrides,
    )
    write_dashboard_payload(payload)
    with st.spinner("Running the AT&T forecasting engine..."):
        try:
            output_dir = execute_model()
            bundle = load_run_bundle(output_dir)
            st.session_state["bundle"] = bundle
            st.session_state["payload"] = payload
            st.success(f"Run complete. Results loaded from: {Path(output_dir).name}")
        except Exception as exc:
            st.error(str(exc))

bundle = st.session_state.get("bundle")
payload = st.session_state.get("payload")

if bundle:
    st.subheader("Selected Run")
    left, right = st.columns([2, 3])
    with left:
        st.json(payload, expanded=False)
    with right:
        st.info(f"Output directory: {Path(bundle['output_dir']).name}")

    kpi_cards(bundle["kpi_table"], selected_scenario)
    st.plotly_chart(comparison_chart(bundle["dashboard_feed"]), use_container_width=True)
    render_history(bundle["dashboard_feed"], selected_scenario)
    render_statement_section(bundle, selected_scenario)
    render_diagnostics(bundle)
else:
    st.info(
        "Put this file, your notebook, and the source Excel files in the same GitHub folder, then run: `streamlit run att_forecasting_single_file.py`"
    )
