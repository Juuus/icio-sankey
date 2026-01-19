"""
Dash version of your IO Sankey Explorer (node-click -> country distribution)

Put these files in the SAME folder as this app.py:
  - 2022.csv
  - codes.xlsx

Run:
  pip install -r requirements.txt
  python app.py

Then open:
  http://127.0.0.1:8050
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go

from dash import Dash, dcc, html, Input, Output, State, no_update


# -------------------------
# Paths
# -------------------------
DATA_PATH  = "2022.csv"
CODES_XLSX = "codes.xlsx"

FINAL_DEMAND_CODES = ["HFCE", "NPISH", "GGFC", "GFCF", "INVNT", "DPABR"]
SPECIAL_ROWS = {"VA", "TLS", "OUT"}
SPECIAL_COLS = {"OUT"}

FD_LABELS = {
    "HFCE": "Household final consumption",
    "NPISH": "NPISH final consumption",
    "GGFC": "Government final consumption",
    "GFCF": "Gross fixed capital formation",
    "INVNT": "Changes in inventories",
    "DPABR": "Direct purchases abroad",
}

SPECIAL_LABELS = {
    "VA":  "Value added",
    "TLS": "Taxes less subsidies",
    "OUT": "Total output",
    "OTHER": "Other",
}


# ==========================================================
# Load data once (fast UI)
# ==========================================================
io = pd.read_csv(DATA_PATH, index_col=0, low_memory=False)
io.index = io.index.astype(str)
io.columns = io.columns.astype(str)

row_labels = pd.Index(io.index)
col_labels = pd.Index(io.columns)


def split_label(lbl: str):
    if lbl in SPECIAL_ROWS or lbl in SPECIAL_COLS:
        return (lbl, None)
    if "_" not in lbl:
        return (lbl, None)
    c, a = lbl.split("_", 1)
    return (c, a)


# rows: suppliers
is_sector_row = row_labels.str.contains("_") & ~row_labels.isin(SPECIAL_ROWS)
row_country  = pd.Series([split_label(x)[0] if "_" in x else None for x in row_labels], index=row_labels)
row_activity = pd.Series([split_label(x)[1] if "_" in x else None for x in row_labels], index=row_labels)

# cols: users
col_has_us = col_labels.str.contains("_")
col_country  = pd.Series([split_label(x)[0] if "_" in x else None for x in col_labels], index=col_labels)
col_activity = pd.Series([split_label(x)[1] if "_" in x else None for x in col_labels], index=col_labels)

is_fd_col     = col_has_us & col_activity.isin(FINAL_DEMAND_CODES) & ~col_labels.isin(SPECIAL_COLS)
is_sector_col = col_has_us & ~is_fd_col & ~col_labels.isin(SPECIAL_COLS)

countries = sorted(row_country[is_sector_row].dropna().unique().tolist())


def activities_for_country(c):
    mask = is_sector_row & row_labels.str.startswith(c + "_")
    return sorted(row_activity[mask].dropna().unique().tolist())


# -------------------------
# Load mappings from codes.xlsx
# -------------------------
def load_codes_mappings(path: str):
    """
    codes.xlsx expected:
      - sheet 'countries' : columns [Code, Country] (maybe with an extra index col)
      - sheet 'industries': columns [Code, Industry, ISIC Rev.4]
    """
    country_map = {}
    industry_map = {}  # code -> (name, isic)

    # Countries
    try:
        dfc = pd.read_excel(path, sheet_name="countries")
        c_code = None
        c_name = None
        for col in dfc.columns:
            if str(col).strip().lower() == "code":
                c_code = col
            if str(col).strip().lower() in {"country", "name"}:
                c_name = col
        if c_code is None or c_name is None:
            c_code = dfc.columns[1]
            c_name = dfc.columns[2]
        for _, r in dfc.iterrows():
            code = str(r[c_code]).strip()
            name = str(r[c_name]).strip()
            if len(code) == 3 and name and name.lower() != "nan":
                country_map[code] = name
    except Exception as e:
        print(f"[WARN] Could not read countries from {path}: {e}")

    # Industries
    try:
        dfi = pd.read_excel(path, sheet_name="industries")
        i_code = None
        i_name = None
        i_isic = None
        for col in dfi.columns:
            cl = str(col).strip().lower()
            if cl == "code":
                i_code = col
            if cl in {"industry", "name"}:
                i_name = col
            if "isic" in cl:
                i_isic = col
        if i_code is None or i_name is None:
            i_code, i_name = dfi.columns[0], dfi.columns[1]
            i_isic = dfi.columns[2] if len(dfi.columns) > 2 else None

        for _, r in dfi.iterrows():
            code = str(r[i_code]).strip()
            name = str(r[i_name]).strip()
            isic = str(r[i_isic]).strip() if i_isic is not None else ""
            if code and code.lower() != "nan" and name and name.lower() != "nan":
                industry_map[code] = (name, isic)
    except Exception as e:
        print(f"[WARN] Could not read industries from {path}: {e}")

    return country_map, industry_map


country_name_map, industry_map = load_codes_mappings(CODES_XLSX)


def country_label(iso3: str) -> str:
    nm = country_name_map.get(iso3)
    return f"{iso3} — {nm}" if nm else iso3


def activity_full(code: str) -> str:
    if code in SPECIAL_LABELS:
        return SPECIAL_LABELS[code]
    if code in FD_LABELS:
        return f"{FD_LABELS[code]} ({code})"

    if code in industry_map:
        name, isic = industry_map[code]
        if isic and isic.lower() != "nan":
            return f"{code} (ISIC {isic}) — {name}"
        return f"{code} — {name}"

    return code


def activity_short(code: str) -> str:
    if code in {"VA", "TLS"}:
        return SPECIAL_LABELS[code]
    if code == "OTHER":
        return SPECIAL_LABELS["OTHER"]
    return code


# -------------------------
# Helper: top + OTHER
# -------------------------
def top_with_other(series: pd.Series, topN: int):
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    s = s[s > 0].sort_values(ascending=False)
    top = s.head(topN)
    other = float(s.sum() - top.sum())
    if other < 1e-10:
        other = 0.0
    return top, other


def sort_by_value(names, vals):
    pairs = sorted(zip(names, vals), key=lambda x: x[1], reverse=True)
    if not pairs:
        return [], []
    n2, v2 = zip(*pairs)
    return list(n2), list(v2)


def y_hybrid(vals, y0=0.06, y1=0.94, min_share=0.02):
    vals = np.array([max(float(v), 0.0) for v in vals], dtype=float)
    n = len(vals)
    if n == 0:
        return []
    H = (y1 - y0)

    min_share_eff = min(min_share, 0.90 / n)
    base = np.full(n, min_share_eff, dtype=float)
    base_sum = base.sum()

    s = vals.sum()
    if s <= 0:
        seg = np.full(n, H / n)
    else:
        extra = max(H - base_sum, 0.0)
        seg = base + extra * (vals / s)

    cum = np.cumsum(seg)
    mids = cum - 0.5 * seg
    return (y0 + mids).tolist()


# ==========================================================
# Build Sankey (returns figure + node metadata so we can map clicks)
# ==========================================================
def build_sankey(c, a, mode, N_in, N_out, drop_self=True, add_va=True, add_tls=True):
    node = f"{c}_{a}"
    col_vec = pd.to_numeric(io[node], errors="coerce").fillna(0.0)      # inputs to node
    row_vec = pd.to_numeric(io.loc[node], errors="coerce").fillna(0.0)  # outputs from node

    # Inputs by activity (aggregated across supplier countries)
    in_sector = col_vec.loc[row_labels[is_sector_row]]
    in_by_act = in_sector.groupby(row_activity.loc[row_labels[is_sector_row]]).sum()
    in_by_act = in_by_act[in_by_act > 0]
    if drop_self:
        in_by_act = in_by_act.drop(index=a, errors="ignore")

    va  = float(pd.to_numeric(io.at["VA",  node], errors="coerce") or 0.0) if ("VA" in io.index and add_va) else 0.0
    tls = float(pd.to_numeric(io.at["TLS", node], errors="coerce") or 0.0) if ("TLS" in io.index and add_tls) else 0.0

    in_top, in_other = top_with_other(in_by_act, N_in)

    # Outputs by activity (intermediate) OR FD code
    if mode == "int":
        out_sector = row_vec.loc[col_labels[is_sector_col]]
        out_by = out_sector.groupby(col_activity.loc[col_labels[is_sector_col]]).sum()
        out_by = out_by[out_by > 0]
        if drop_self:
            out_by = out_by.drop(index=a, errors="ignore")
        out_prefix = "OUT"
        out_title = "Intermediate outputs"
    else:
        out_fd = row_vec.loc[col_labels[is_fd_col]]
        out_by = out_fd.groupby(col_activity.loc[col_labels[is_fd_col]]).sum()
        out_by = out_by[out_by > 0].sort_values(ascending=False)
        out_prefix = "FD"
        out_title = "Final demand"

    out_top, out_other = top_with_other(out_by, N_out)

    # ---- Nodes (internal IDs)
    left_nodes = [f"IN:{x}" for x in in_top.index.astype(str)]
    left_vals  = [float(v) for v in in_top.values]
    if in_other > 0:
        left_nodes.append("IN:OTHER"); left_vals.append(float(in_other))
    if add_tls and tls > 0:
        left_nodes.append("IN:TLS"); left_vals.append(float(tls))
    if add_va and va > 0:
        left_nodes.append("IN:VA"); left_vals.append(float(va))

    center_node = f"SEL:{a}"  # label will be hidden

    right_nodes = [f"{out_prefix}:{x}" for x in out_top.index.astype(str)]
    right_vals  = [float(v) for v in out_top.values]
    if out_other > 0:
        right_nodes.append(f"{out_prefix}:OTHER"); right_vals.append(float(out_other))

    left_nodes_s, left_vals_s   = sort_by_value(left_nodes, left_vals)
    right_nodes_s, right_vals_s = sort_by_value(right_nodes, right_vals)

    nodes = left_nodes_s + [center_node] + right_nodes_s
    idx = {n:i for i,n in enumerate(nodes)}

    # ---- Display labels (short) + hover labels (full)
    def code_from_internal(internal: str) -> str:
        return internal.split(":", 1)[1] if ":" in internal else internal

    labels = []
    hover = []
    for internal in nodes:
        if internal.startswith("SEL:"):
            code = code_from_internal(internal)
            labels.append("")  # hide center
            hover.append(activity_full(code))
        elif internal.startswith(("IN:", "OUT:", "FD:")):
            code = code_from_internal(internal)
            labels.append(activity_short(code))
            hover.append(activity_full(code))
        else:
            labels.append(internal)
            hover.append(internal)

    # ---- Links
    sources, targets, values = [], [], []

    for k, v in in_top.items():
        sources.append(idx[f"IN:{k}"]); targets.append(idx[center_node]); values.append(float(v))
    if in_other > 0:
        sources.append(idx["IN:OTHER"]); targets.append(idx[center_node]); values.append(float(in_other))
    if add_tls and tls > 0:
        sources.append(idx["IN:TLS"]); targets.append(idx[center_node]); values.append(float(tls))
    if add_va and va > 0:
        sources.append(idx["IN:VA"]); targets.append(idx[center_node]); values.append(float(va))

    for k, v in out_top.items():
        sources.append(idx[center_node]); targets.append(idx[f"{out_prefix}:{k}"]); values.append(float(v))
    if out_other > 0:
        sources.append(idx[center_node]); targets.append(idx[f"{out_prefix}:OTHER"]); values.append(float(out_other))

    # ---- Layout
    y0, y1 = 0.06, 0.94
    y_left  = y_hybrid(left_vals_s,  y0=y0, y1=y1, min_share=0.02)
    y_right = y_hybrid(right_vals_s, y0=y0, y1=y1, min_share=0.02)

    y_center = 0.5
    if len(y_left) and np.sum(left_vals_s) > 0:
        y_center = np.average(y_left, weights=np.array(left_vals_s))
    if len(y_right) and np.sum(right_vals_s) > 0:
        y_center = 0.5 * (y_center + np.average(y_right, weights=np.array(right_vals_s)))

    x_left, x_center, x_right = 0.02, 0.50, 0.98
    x = ([x_left]*len(left_nodes_s)) + [x_center] + ([x_right]*len(right_nodes_s))
    y = y_left + [float(y_center)] + y_right

    n_slots = max(len(left_nodes_s), len(right_nodes_s), 8)

    # Make the figure tall enough (browser/Dash can still shrink it if the DIV is small)
    height = max(900, 65 * n_slots)

    base_link_color = "rgba(160,160,160,0.20)"
    link_colors = [base_link_color] * len(values)

    selected_full = activity_full(a)
    title = f"{country_label(c)} — Selected: {selected_full} — {out_title}"

    fig = go.Figure(data=[go.Sankey(
        arrangement="fixed",
        node=dict(
            pad=30,
            thickness=38,
            line=dict(color="black", width=0.5),
            label=labels,
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
            x=x, y=y,
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
            color=link_colors,
            hovertemplate="Value: %{value:,.2f}<extra></extra>"
        )
    )])

    fig.update_layout(
        title_text=title,
        font=dict(size=12),
        height=height,
        margin=dict(l=10, r=10, t=70, b=10),
    )

    meta = {
        "nodes_internal": nodes,
        "sources": sources,
        "targets": targets,
        "values": values,
        "base_link": "rgba(160,160,160,0.18)",
        "hi_link": "rgba(90,90,90,0.85)",
    }
    return fig, meta


# ==========================================================
# Country distribution (bar chart) given clicked INTERNAL node id
# ==========================================================
def country_distribution(c, a, internal, topN):
    node = f"{c}_{a}"
    col_vec = pd.to_numeric(io[node], errors="coerce").fillna(0.0)
    row_vec = pd.to_numeric(io.loc[node], errors="coerce").fillna(0.0)

    def white_layout(fig, title):
        fig.update_layout(
            title=title,
            paper_bgcolor="white",
            plot_bgcolor="white",
            xaxis=dict(gridcolor="rgba(0,0,0,0.10)"),
            yaxis=dict(gridcolor="rgba(0,0,0,0.10)"),
        )
        return fig

    if not internal:
        fig = go.Figure()
        fig.update_layout(title="Click an IN / OUT / FD node to see country distribution", height=420)
        return white_layout(fig, fig.layout.title.text)

    # Input nodes
    if internal.startswith("IN:"):
        code = internal.split(":", 1)[1]

        if code in {"VA", "TLS"}:
            val = float(pd.to_numeric(io.at[code, node], errors="coerce") or 0.0) if code in io.index else 0.0
            s = pd.Series({c: val})
            title = f"{activity_full(code)} (domestic) — {country_label(c)}"
        elif code == "OTHER":
            fig = go.Figure()
            fig = white_layout(fig, "OTHER is an aggregate bucket; no country split available.")
            fig.update_layout(height=420)
            return fig
        else:
            rows = row_labels[is_sector_row & (row_activity == code)]
            vals = pd.to_numeric(col_vec.loc[rows], errors="coerce").fillna(0.0)
            vals = vals[vals > 0]
            s = vals.groupby(row_country.loc[rows]).sum().sort_values(ascending=False)
            title = f"Suppliers by country — {activity_full(code)} → {activity_full(a)} ({country_label(c)})"

    # Intermediate output nodes
    elif internal.startswith("OUT:"):
        code = internal.split(":", 1)[1]
        if code == "OTHER":
            fig = go.Figure()
            fig = white_layout(fig, "OTHER is an aggregate bucket; pick a specific output for country split.")
            fig.update_layout(height=420)
            return fig

        cols = col_labels[is_sector_col & (col_activity == code)]
        vals = pd.to_numeric(row_vec.loc[cols], errors="coerce").fillna(0.0)
        vals = vals[vals > 0]
        s = vals.groupby(col_country.loc[cols]).sum().sort_values(ascending=False)
        title = f"Destinations by country — {activity_full(a)} ({country_label(c)}) → {activity_full(code)}"

    # Final demand nodes
    elif internal.startswith("FD:"):
        code = internal.split(":", 1)[1]
        if code == "OTHER":
            fig = go.Figure()
            fig = white_layout(fig, "OTHER is an aggregate bucket; pick a specific final-demand code for country split.")
            fig.update_layout(height=420)
            return fig

        cols = col_labels[is_fd_col & (col_activity == code)]
        vals = pd.to_numeric(row_vec.loc[cols], errors="coerce").fillna(0.0)
        vals = vals[vals > 0]
        s = vals.groupby(col_country.loc[cols]).sum().sort_values(ascending=False)
        title = f"Destinations by country — {activity_full(a)} ({country_label(c)}) → {activity_full(code)}"

    else:
        fig = go.Figure()
        fig = white_layout(fig, "Click an IN / OUT / FD node")
        fig.update_layout(height=420)
        return fig

    if s.empty:
        fig = go.Figure()
        fig = white_layout(fig, f"{title} (no positive flows)")
        fig.update_layout(height=420)
        return fig

    top = s.head(topN)
    other = float(s.sum() - top.sum())
    if other > 1e-10:
        top = pd.concat([top, pd.Series({"Other": other})])

    y_labels = [country_label(x) if x != "Other" else "Other" for x in top.index.astype(str)]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=top.values, y=y_labels, orientation="h"))
    fig = white_layout(fig, title)
    fig.update_layout(
        height=max(420, 260 + 18*len(top)),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=240, r=20, t=60, b=20),
    )
    return fig


def empty_dist():
    fig = go.Figure()
    fig.update_layout(
        title="Click an IN / OUT / FD node to see country distribution",
        height=420,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


# ==========================================================
# Dash UI
# ==========================================================
app = Dash(__name__)
server = app.server

DEFAULT_COUNTRY = "PHL" if "PHL" in countries else (countries[0] if countries else None)
DEFAULT_ACTIVITY = activities_for_country(DEFAULT_COUNTRY)[0] if DEFAULT_COUNTRY else None

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "padding": "12px"},
    children=[
        html.H3("Inter Country Input Output Tables Sankey"),

        html.Div(
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "alignItems": "center"},
            children=[
                html.Div([
                    html.Label("Country"),
                    dcc.Dropdown(
                        id="country",
                        options=[{"label": country_label(c), "value": c} for c in countries],
                        value=DEFAULT_COUNTRY,
                        clearable=False,
                        style={"minWidth": "360px"},
                    ),
                ]),
                html.Div([
                    html.Label("Activity"),
                    dcc.Dropdown(
                        id="activity",
                        options=[],
                        value=DEFAULT_ACTIVITY,
                        clearable=False,
                        style={"minWidth": "520px"},
                    ),
                ]),
                html.Div([
                    html.Label("Outputs"),
                    dcc.RadioItems(
                        id="mode",
                        options=[
                            {"label": "Intermediate outputs", "value": "int"},
                            {"label": "Final demand", "value": "fd"},
                        ],
                        value="int",
                        inline=True,
                    ),
                ]),
            ],
        ),

        html.Div(
            style={"display": "flex", "gap": "18px", "flexWrap": "wrap", "marginTop": "10px", "alignItems": "center"},
            children=[
                html.Div([
                    html.Label("Top inputs"),
                    dcc.Slider(id="top_in", min=3, max=60, step=1, value=10,
                               marks={3: "3", 10: "10", 20: "20", 40: "40", 60: "60"}),
                ], style={"minWidth": "260px"}),

                html.Div([
                    html.Label("Top outputs"),
                    dcc.Slider(id="top_out", min=3, max=60, step=1, value=6,
                               marks={3: "3", 10: "10", 20: "20", 40: "40", 60: "60"}),
                ], style={"minWidth": "260px"}),

                html.Div([
                    html.Label("Top countries"),
                    dcc.Slider(id="top_cty", min=5, max=50, step=1, value=10,
                               marks={5: "5", 25: "25", 50: "50"}),
                ], style={"minWidth": "320px"}),

                dcc.Checklist(
                    id="checks",
                    options=[
                        {"label": "Exclude self (A→A)", "value": "drop_self"},
                        {"label": "Include value added", "value": "va"},
                        {"label": "Include taxes/subsidies", "value": "tls"},
                    ],
                    value=["drop_self", "va", "tls"],
                    inline=True,
                ),
            ],
        ),

        html.Div(
            style={"marginTop": "10px", "color": "#333"},
            children=[
                html.B("Tip: "),
                html.Span("Click an IN node to see suppliers, or an OUT/FD node to see destinations. "
                          "(Value added / Taxes are clickable too.)"),
            ],
        ),

        # Stores: keep node list + link arrays for mapping click index -> internal id
        dcc.Store(id="sankey_meta"),
        dcc.Store(id="last_clicked_internal"),

        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1.35fr 1fr", "gap": "14px", "marginTop": "12px"},
            children=[
                html.Div(
                    children=[
                        dcc.Graph(
                            id="sankey",
                            figure=go.Figure(),
                            config={"displayModeBar": True},
                            style={"height": "78vh"},  # IMPORTANT: forces the DIV to be tall
                        ),
                    ]
                ),
                html.Div(
                    children=[
                        html.H4("Country distribution"),
                        dcc.Graph(
                            id="dist",
                            figure=empty_dist(),
                            config={"displayModeBar": True},
                            style={"height": "78vh"},
                        ),
                    ]
                ),
            ],
        ),
    ]
)


# ==========================================================
# 1) Update activity dropdown when country changes
# ==========================================================
@app.callback(
    Output("activity", "options"),
    Output("activity", "value"),
    Input("country", "value"),
)
def _update_activity_dd(country):
    if not country:
        return [], None
    acts = activities_for_country(country)
    opts = [{"label": activity_full(code), "value": code} for code in acts]
    val = acts[0] if acts else None
    return opts, val


# ==========================================================
# 2) Build sankey figure and store meta
# ==========================================================
@app.callback(
    Output("sankey", "figure"),
    Output("sankey_meta", "data"),
    Input("country", "value"),
    Input("activity", "value"),
    Input("mode", "value"),
    Input("top_in", "value"),
    Input("top_out", "value"),
    Input("checks", "value"),
)
def _render_sankey(country, activity, mode, top_in, top_out, checks):
    if not country or not activity:
        return go.Figure(), {}

    drop_self = "drop_self" in (checks or [])
    add_va = "va" in (checks or [])
    add_tls = "tls" in (checks or [])

    fig, meta = build_sankey(
        country, activity, mode,
        N_in=int(top_in),
        N_out=int(top_out),
        drop_self=drop_self,
        add_va=add_va,
        add_tls=add_tls,
    )
    return fig, meta



# ==========================================================
# 3) On click: highlight links + update distribution chart
# ==========================================================
@app.callback(
    Output("sankey", "figure", allow_duplicate=True),
    Output("dist", "figure"),
    Output("last_clicked_internal", "data"),
    Input("sankey", "clickData"),
    Input("top_cty", "value"),                # <-- now changing slider updates bar chart
    State("sankey", "figure"),
    State("sankey_meta", "data"),
    State("country", "value"),
    State("activity", "value"),
    State("last_clicked_internal", "data"),   # <-- remember what node was last selected
    prevent_initial_call=True,
)
def _handle_click(clickData, top_cty, fig, meta, country, activity, last_internal):
    if not meta or not country or not activity:
        return no_update, no_update, no_update

    # If user clicked, use that. If not (slider moved), reuse last clicked node.
    internal = None
    node_i = None

    if clickData and (clickData.get("points") or []):
        pt = clickData["points"][0]
        node_i = pt.get("pointNumber", None)
        nodes_internal = meta.get("nodes_internal") or []
        if node_i is not None and 0 <= int(node_i) < len(nodes_internal):
            internal = nodes_internal[int(node_i)]
    else:
        internal = last_internal

    nodes_internal = meta.get("nodes_internal") or []
    if internal and internal not in nodes_internal:
        # user changed country/activity; old selection is no longer valid
        return no_update, empty_dist(), None


    # Nothing selected yet -> keep chart empty
    if not internal or not internal.startswith(("IN:", "OUT:", "FD:")):
        return no_update, empty_dist(), None

    # If this update came from slider (no click), we skip re-highlighting (optional)
    fig2 = fig
    if clickData and node_i is not None:
        src = meta.get("sources") or []
        tgt = meta.get("targets") or []
        base_link = meta.get("base_link", "rgba(160,160,160,0.18)")
        hi_link   = meta.get("hi_link", "rgba(90,90,90,0.85)")

        colors = [base_link] * len(src)
        for j in range(len(src)):
            if src[j] == int(node_i) or tgt[j] == int(node_i):
                colors[j] = hi_link

        try:
            fig2["data"][0]["link"]["color"] = colors
        except Exception:
            fig2 = fig

    dist_fig = country_distribution(country, activity, internal, int(top_cty))
    return fig2, dist_fig, internal


if __name__ == "__main__":
    # debug=True auto reloads when you edit the file
    app.run(host="127.0.0.1", port=8050, debug=True)


