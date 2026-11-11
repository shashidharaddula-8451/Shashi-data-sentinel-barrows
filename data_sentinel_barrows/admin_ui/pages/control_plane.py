# pages/control_plane.py

import dash
from dash import html, dcc, Input, Output, State, callback, ctx, MATCH
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
import json
import logging
from datetime import datetime

from db.connection import execute_query
from db.queries import (
    get_control_plane_table_status,
    get_control_plane_trust_trend,
    get_control_plane_stage_status,
    get_control_plane_active_alerts,
    get_control_plane_alert_run,
    get_control_plane_lineage,
    get_control_plane_join_checks,
    get_control_plane_lineage_uc,
    get_control_plane_lineage_native,
    get_validation_results_for_run,
    get_reconciliation_results_for_run,
    get_kpi_validation_results_for_run,
)
from components.alerts import STATUS_EMOJI

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/control-plane", name="Control Plane")

STAGE_LABELS = {
    "UC1": "Raw Ingestion",
    "UC3": "Silver Transform",
    "UC2": "Cross-layer Recon",
    "UC4": "Gold KPI",
}
STAGE_ORDER = ["UC1", "UC3", "UC2", "UC4"]

# Fallback display names when a stage has no run history yet (agent is None),
# so the stepper shows the responsible agent instead of "Unknown Agent".
STAGE_AGENT_NAMES = {
    "UC1": "Validation Agent",
    "UC3": "Transformation Agent",
    "UC2": "Reconciliation Agent",
    "UC4": "KPI Assurance Agent",
}

_STATUS_COLOR = {
    "PASS":     "#2f9e44",
    "WARNING":  "#f08c00",
    "CRITICAL": "#e03131",
    "UNKNOWN":  "#5C5F66",
}

layout = dbc.Container([

    dcc.Interval(
        id="control-plane-refresh-interval",
        interval=5 * 60 * 1000,
        n_intervals=0,
        disabled=True,
    ),
    dcc.Store(id="control-plane-load-trigger", data=True),

    html.Div([
        html.H4("Control Plane", style={"color": "#ffffff", "marginBottom": "0"}),
        html.Div([
            html.Div([
                html.Span(style={
                    "display": "inline-block", "width": "8px", "height": "8px",
                    "borderRadius": "50%", "backgroundColor": color, "marginRight": "5px",
                }),
                html.Span(label, style={"color": "#909296", "fontSize": "11px", "marginRight": "14px"}),
            ], style={"display": "flex", "alignItems": "center"})
            for label, color in [
                ("Pass", _STATUS_COLOR["PASS"]),
                ("Warning", _STATUS_COLOR["WARNING"]),
                ("Critical", _STATUS_COLOR["CRITICAL"]),
                ("Unknown", _STATUS_COLOR["UNKNOWN"]),
            ]
        ], style={"display": "flex", "alignItems": "center"}),
    ], className="mb-3", style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "flexWrap": "wrap", "gap": "8px"}),

    dbc.Row([
        dbc.Col(dcc.Loading(
            type="circle", color="#00c851", parent_style={"minHeight": "160px"},
            children=html.Div(id="cp-trust-content"),
        ), md=4, className="mb-3"),
        dbc.Col(dcc.Loading(
            type="circle", color="#00c851", parent_style={"minHeight": "160px"},
            children=html.Div(id="cp-stepper-content"),
        ), md=8, className="mb-3"),
    ]),
    dbc.Row([
        dbc.Col(dcc.Loading(
            type="circle", color="#00c851", parent_style={"minHeight": "360px"},
            children=html.Div(id="cp-lineage-content-native"),
        ), md=9, className="mb-3"),
        dbc.Col(dcc.Loading(
            type="circle", color="#00c851", parent_style={"minHeight": "360px"},
            target_components={"cp-alerts-content": "children"},
            children=html.Div(id="cp-alerts-content"),
        ), md=3, className="mb-3"),
    ]),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="cp-lineage-modal-title"), close_button=False, style={
            "backgroundColor": "#1A1B1E", "borderBottom": "1px solid #373A40", "color": "#ffffff",
        }),
        dbc.ModalBody(id="cp-lineage-modal-body", style={"backgroundColor": "#1A1B1E"}),
        dbc.ModalFooter(
            dbc.Button("Close", id="cp-lineage-modal-close", size="sm", color="secondary"),
            style={"backgroundColor": "#1A1B1E", "borderTop": "1px solid #373A40"},
        ),
    ], id="cp-lineage-modal", is_open=False, size="lg"),

], fluid=True, style={"padding": "24px"})


def _trust_donut(released, pending, quarantined):
    total = released + pending + quarantined
    trust_pct = round(100 * released / total) if total else 0

    fig = go.Figure(data=[go.Pie(
        values=[released, pending, quarantined] if total else [1],
        hole=0.72,
        marker_colors=["#2f9e44", "#f08c00", "#e03131"] if total else ["#373A40"],
        textinfo="none",
        sort=False,
        direction="clockwise",
    )])
    fig.update_layout(
        showlegend=False,
        margin=dict(l=0, r=0, t=0, b=0),
        height=110, width=110,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(
            text=f"<b>{trust_pct}%</b><br><span style='font-size:9px'>TRUSTED</span>",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color="#ffffff", size=18),
        )],
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "110px", "width": "110px"})


def _trust_sparkline(df_trend):
    """A tiny 7-day trust % trend line, or None if there's not enough data to draw one."""
    if df_trend is None or df_trend.empty or len(df_trend) < 2:
        return None

    values = df_trend["trust_pct"].tolist()
    color = "#2f9e44" if values[-1] >= values[0] else "#e03131"
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

    fig = go.Figure(data=[go.Scatter(
        y=values, mode="lines", line=dict(color=color, width=1.5),
        fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.15)",
        hoverinfo="none",
    )])
    fig.update_layout(
        height=28, width=100,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, range=[0, 100]),
    )
    return html.Div([
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "28px", "width": "100px"}),
        html.Div("7-day trend", style={"color": "#5C5F66", "fontSize": "9px", "marginTop": "2px"}),
    ])


def _legend_row(color, label, count):
    return html.Div([
        html.Span(style={
            "display": "inline-block", "width": "10px", "height": "10px",
            "borderRadius": "50%", "backgroundColor": color, "marginRight": "8px",
        }),
        html.Span(label, style={"color": "#C1C2C5", "fontSize": "14px", "marginRight": "8px"}),
        html.Span(str(count), style={"color": "#ffffff", "fontWeight": "700", "fontSize": "14px"}),
    ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"})


def _alert_item(source, agent, table_name, run_id, ts):
    ts_str = ts.strftime("%d %b %H:%M UTC") if isinstance(ts, datetime) and pd.notna(ts) else str(ts or "N/A")
    short_table = table_name.split(".")[-1] if table_name else "unknown"
    short_run = (run_id or "")[:8]

    header = html.Div([
        html.Div([
            html.Span("●", style={"color": "#e03131", "marginRight": "8px", "fontSize": "10px"}),
            html.Span(short_table, style={"color": "#ffffff", "fontWeight": "600", "fontSize": "13px"}),
            html.Span("▾", id={"type": "cp-alert-chevron", "source": source, "run_id": run_id}, style={
                "color": "#5C5F66", "fontSize": "10px", "marginLeft": "auto",
            }),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div(_format_agent_name(agent), style={"color": "#e03131", "fontSize": "11px", "marginTop": "2px"}),
        html.Div(f"run {short_run}  ·  {ts_str}", style={"color": "#5C5F66", "fontSize": "10px", "marginTop": "2px"}),
    ], id={"type": "cp-alert-header", "source": source, "run_id": run_id}, style={
        "cursor": "pointer", "userSelect": "none",
    })

    return html.Div([
        header,
        dbc.Collapse(
            dcc.Loading(
                type="circle",
                color="#00c851",
                parent_style={"marginTop": "8px", "minHeight": "24px"},
                children=html.Div(
                    id={"type": "cp-alert-detail", "source": source, "run_id": run_id},
                ),
            ),
            id={"type": "cp-alert-collapse", "source": source, "run_id": run_id},
            is_open=False,
        ),
    ], className="ds-alert-item")


def _alert_detail_body(source, run):
    """Renders the expanded card contents for one alert, given its parent run row."""
    checks_by_source = {
        "UC1": ("total_checks_run", "total_checks_passed", "total_checks_warned", "total_checks_critical"),
        "UC2": ("total_checks_run", "total_checks_passed", "total_checks_warned", "total_checks_critical"),
        "UC3": ("total_checks_run", "total_checks_passed", "total_checks_warned", "total_checks_critical"),
        "UC4": ("total_kpis_checked", "total_kpis_passed", "total_kpis_warned", "total_kpis_critical"),
    }
    run_col, pass_col, warn_col, crit_col = checks_by_source[source]

    summary = html.Div([
        html.Span(f"{int(run.get(run_col) or 0)} checks", style={"color": "#C1C2C5", "fontSize": "11px", "marginRight": "10px"}),
        html.Span(f"{int(run.get(pass_col) or 0)} pass", style={"color": "#2f9e44", "fontSize": "11px", "marginRight": "10px"}),
        html.Span(f"{int(run.get(warn_col) or 0)} warn", style={"color": "#f08c00", "fontSize": "11px", "marginRight": "10px"}),
        html.Span(f"{int(run.get(crit_col) or 0)} critical", style={"color": "#e03131", "fontSize": "11px"}),
    ], style={"marginBottom": "8px"})

    failed_checks = []
    ai_summary = ai_action = ai_category = None

    try:
        if source == "UC1":
            df = execute_query(*get_validation_results_for_run(run["validation_run_id"]))
        elif source == "UC2":
            df = execute_query(*get_reconciliation_results_for_run(run["reconciliation_run_id"]))
        elif source == "UC4":
            df = execute_query(*get_kpi_validation_results_for_run(run["validation_run_id"]))
        else:
            df = None

        if source == "UC3":
            raw_cr = run.get("check_results", "[]")
            if raw_cr and str(raw_cr).strip() not in ("", "None", "null", "[]"):
                for c in json.loads(str(raw_cr)):
                    if c.get("check_status") in ("CRITICAL", "WARNING"):
                        failed_checks.append({
                            "label": c.get("check_name", ""),
                            "status": c.get("check_status", ""),
                            "detail": "; ".join(c.get("findings", []) or []),
                        })
            ai_summary = run.get("ai_summary") or None
            ai_action = run.get("ai_recommended_action") or None
            ai_category = run.get("ai_failure_category") or None
        elif df is not None and not df.empty:
            for _, r in df.iterrows():
                if r.get("check_status") in ("CRITICAL", "WARNING"):
                    label = r.get("check_type", "") or r.get("kpi_name", "")
                    col = r.get("column_name") or r.get("metric_name") or r.get("kpi_column")
                    observed = r.get("observed_value")
                    deviation = r.get("deviation_percentage")
                    detail_parts = []
                    if observed is not None:
                        detail_parts.append(f"observed {observed}")
                    if deviation is not None:
                        detail_parts.append(f"deviation {deviation}%")
                    failed_checks.append({
                        "label": f"{label} ({col})" if col else str(label),
                        "status": str(r.get("check_status", "")),
                        "detail": ", ".join(detail_parts),
                    })
            ai_rows = df[df["ai_summary"].notna() & (df["ai_summary"] != "")]
            if not ai_rows.empty:
                first = ai_rows.iloc[0]
                ai_summary = str(first.get("ai_summary", ""))
                ai_action = str(first.get("ai_recommended_action", ""))
                ai_category = str(first.get("ai_failure_category", ""))
    except Exception as e:
        logger.error(f"Control plane alert detail fetch failed: {e}")

    check_items = [
        html.Div([
            html.Span(STATUS_EMOJI.get(c["status"], "⚪") + " ", style={"fontSize": "10px"}),
            html.Span(c["label"], style={"color": "#C1C2C5", "fontSize": "11px", "fontWeight": "600"}),
            html.Div(c["detail"], style={"color": "#5C5F66", "fontSize": "10px", "marginTop": "1px"}),
        ], style={"marginBottom": "6px"})
        for c in failed_checks
    ] or [html.Div("No individual check details available.", style={"color": "#5C5F66", "fontSize": "11px"})]

    elements = [summary, html.Div(check_items)]

    if ai_summary:
        elements.append(html.Div([
            html.Div(f"AI: {ai_category or ''}".strip(), style={"color": "#909296", "fontSize": "10px", "marginTop": "8px", "fontWeight": "700"}),
            html.Div(ai_summary, style={"color": "#C1C2C5", "fontSize": "11px", "marginTop": "2px"}),
            html.Div(ai_action or "", style={"color": "#5C5F66", "fontSize": "10px", "marginTop": "2px", "fontStyle": "italic"}),
        ]))

    return html.Div(elements, style={
        "backgroundColor": "#16171a", "border": "1px solid #373A40", "borderRadius": "6px",
        "padding": "10px",
    })


def _format_agent_name(agent):
    """'06_validation_agent' -> 'Validation Agent'; falls back to the raw value."""
    if not agent:
        return "Unknown Agent"
    parts = [p for p in agent.split("_") if not p.isdigit()]
    return " ".join(p.capitalize() for p in parts) if parts else agent


_LAYER_COLUMNS = ["BRONZE", "SILVER", "GOLD"]
_LAYER_TITLES = {"BRONZE": "BRONZE", "SILVER": "SILVER", "GOLD": "GOLD"}

# Plotly-canvas coordinate system for the lineage board. Every row (and the
# header) shares this same x-range, so card edges and connector endpoints are
# drawn from the exact same numbers -- there is no CSS box model involved, so
# there is no possibility of a rendering gap between a card and its connector.
_LAYER_X = {
    "BRONZE": (0.4, 3.6),
    "SILVER": (4.4, 7.6),
    "GOLD":   (8.8, 11.6),
}
_CANVAS_X_RANGE = (0, 12)


def _lineage_connector_color(row):
    if row is None:
        return None
    status = row.get("overall_status") or "UNKNOWN"
    return _STATUS_COLOR.get(status, _STATUS_COLOR["UNKNOWN"])


def _rounded_rect_path(x0, y0, x1, y1, rx, ry):
    """SVG path for a rectangle with rounded corners (Plotly shapes have no radius option)."""
    rx = min(rx, (x1 - x0) / 2)
    ry = min(ry, (y1 - y0) / 2)
    return (
        f"M{x0 + rx},{y0} "
        f"L{x1 - rx},{y0} Q{x1},{y0} {x1},{y0 + ry} "
        f"L{x1},{y1 - ry} Q{x1},{y1} {x1 - rx},{y1} "
        f"L{x0 + rx},{y1} Q{x0},{y1} {x0},{y1 - ry} "
        f"L{x0},{y0 + ry} Q{x0},{y0} {x0 + rx},{y0} Z"
    )


def _lineage_box(x0, x1, yc, half_h, row):
    """Returns (shapes, annotations, color) for one lineage card drawn on a Plotly canvas."""
    radius = 0.10
    if row is None:
        shapes = [dict(
            type="path", path=_rounded_rect_path(x0, yc - half_h, x1, yc + half_h, radius, radius),
            line=dict(color="#373A40", width=1, dash="dot"),
            fillcolor="rgba(0,0,0,0)", layer="above",
        )]
        annotations = [dict(
            x=(x0 + x1) / 2, y=yc, xref="x", yref="y", text="—",
            showarrow=False, font=dict(color="#5C5F66", size=12),
            xanchor="center", yanchor="middle",
        )]
        return shapes, annotations, "#5C5F66"

    status = row.get("overall_status") or "UNKNOWN"
    color = _STATUS_COLOR.get(status, _STATUS_COLOR["UNKNOWN"])
    table_name = row.get("table_name", "")
    ts = row.get("created_timestamp")
    ts_str = ts.strftime("%d %b %H:%M") if isinstance(ts, datetime) and pd.notna(ts) else ""

    shapes = [dict(
        type="path", path=_rounded_rect_path(x0, yc - half_h, x1, yc + half_h, radius, radius),
        line=dict(color=color, width=1.5),
        fillcolor="#16171a", layer="above",
    )]
    annotations = [
        dict(
            x=(x0 + x1) / 2, y=yc + half_h * 0.50, xref="x", yref="y",
            text=f"<b>{table_name}</b>", showarrow=False,
            font=dict(color="#ffffff", size=11), xanchor="center", yanchor="middle",
        ),
        dict(
            x=(x0 + x1) / 2, y=yc - half_h * 0.10, xref="x", yref="y",
            text=status, showarrow=False,
            font=dict(color=color, size=9), xanchor="center", yanchor="middle",
        ),
    ]
    if ts_str:
        annotations.append(dict(
            x=(x0 + x1) / 2, y=yc - half_h * 0.65, xref="x", yref="y",
            text=ts_str, showarrow=False,
            font=dict(color="#5C5F66", size=8), xanchor="center", yanchor="middle",
        ))
    return shapes, annotations, color


def _lineage_curve(x0, y0, x1, y1, color, width=6):
    """A smooth, thick bezier ribbon connector between two exact canvas points."""
    mid = (x0 + x1) / 2
    path = f"M{x0},{y0} C{mid},{y0} {mid},{y1} {x1},{y1}"
    return dict(
        type="path", path=path,
        line=dict(color=color, width=width),
        opacity=0.9, layer="below",
    )


def _lineage_row_graph(shapes, annotations, y_range=(0, 1), height=90, click_targets=None, graph_id=None):
    """
    `click_targets`, if given, is a list of (x0, x1, yc, half_h, customdata) tuples.
    Each becomes an invisible clickable marker so a box can be clicked to open
    its detail modal -- this makes the graph interactive, so callers that pass
    click_targets should also pass a stable `graph_id` to wire a click callback.
    """
    fig = go.Figure()

    if click_targets:
        fig.add_trace(go.Scatter(
            x=[(x0 + x1) / 2 for x0, x1, yc, half_h, _ in click_targets],
            y=[yc for x0, x1, yc, half_h, _ in click_targets],
            mode="markers",
            marker=dict(
                size=[max((x1 - x0), half_h * 2) * 30 for x0, x1, yc, half_h, _ in click_targets],
                opacity=0,
            ),
            customdata=[cd for *_, cd in click_targets],
            hoverinfo="none",
            showlegend=False,
        ))

    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False, range=list(_CANVAS_X_RANGE), fixedrange=True),
        yaxis=dict(visible=False, range=list(y_range), fixedrange=True),
        shapes=shapes,
        annotations=annotations,
        dragmode=False,
        clickmode="event",
    )
    graph_kwargs = dict(id=graph_id) if graph_id else {}
    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False, "staticPlot": not click_targets},
        style={"height": f"{height}px", "width": "100%", "cursor": "pointer" if click_targets else "default"},
        **graph_kwargs,
    )


def _lineage_header_graph():
    annotations = []
    for layer in _LAYER_COLUMNS:
        x0, x1 = _LAYER_X[layer]
        annotations.append(dict(
            x=(x0 + x1) / 2, y=0.5, xref="x", yref="y",
            text=f"<b>{_LAYER_TITLES[layer]}</b>", showarrow=False,
            font=dict(color="#5C5F66", size=11), xanchor="center", yanchor="middle",
        ))
    return _lineage_row_graph([], annotations, height=26)


_ROLE_SORT = {"PRIMARY": 0, "SECONDARY": 1, "TERTIARY": 2}


def _join_check_badge(check_status, label, value):
    color = _STATUS_COLOR.get(check_status, _STATUS_COLOR["UNKNOWN"])
    return html.Div([
        html.Span(f"{label}: ", style={"color": "#5C5F66", "fontSize": "9px"}),
        html.Span(value, style={"color": color, "fontSize": "9px", "fontWeight": "700"}),
    ])


def _build_lineage_graph(df, df_joins=None, graph_id="cp-lineage-graph"):
    """
    Render the whole lineage board as a single unified graph on one shared
    canvas: each bronze family is drawn exactly once, with a connector line
    to every downstream target it feeds -- its own dedicated chain AND any
    shared fan-in target (e.g. a dim table fed by multiple sources). This
    avoids ever redrawing the same source box twice.
    """
    join_checks_by_family = {}
    if df_joins is not None and not df_joins.empty:
        for family, group in df_joins.groupby("family", sort=False):
            join_checks_by_family[family] = {r["check_type"]: r for _, r in group.iterrows()}

    fan_in_counts = df.groupby(["layer_name", "fully_qualified_name"])["family"].transform("nunique")
    df = df.assign(_fan_in=fan_in_counts > 1)

    families = sorted(df["family"].unique())
    merge_targets = df.loc[df["_fan_in"], ["layer_name", "fully_qualified_name"]].drop_duplicates()
    merge_targets = list(merge_targets.itertuples(index=False, name=None))

    n_rows = len(families) + len(merge_targets)
    n_rows = max(n_rows, 1)
    row_h = 1.0 / n_rows

    def row_yc(i):
        return 1 - row_h * (i + 0.5)

    family_yc = {family: row_yc(i) for i, family in enumerate(families)}
    merge_yc = {}
    for j, (layer_name, target_fqn) in enumerate(merge_targets):
        merge_yc[(layer_name, target_fqn)] = row_yc(len(families) + j)

    half_h = min(0.32, row_h * 0.42)
    shapes = []
    annotations = []
    click_targets = []

    def _click_target(x0, x1, yc, row):
        if row is None or not row.get("run_id") or not row.get("source"):
            return
        click_targets.append((x0, x1, yc, half_h, {
            "source": row["source"], "run_id": row["run_id"], "table_name": row.get("table_name", ""),
        }))

    # Each family's own (non-fan-in) chain: straight boxes/connectors at its row.
    for family in families:
        fam_group = df[df["family"] == family]
        own_rows = fam_group.loc[~fam_group["_fan_in"]]
        layer_rows = {r["layer_name"]: r for _, r in own_rows.iterrows()}
        yc = family_yc[family]

        present_layers = [l for l in _LAYER_COLUMNS if l in layer_rows]
        for layer in present_layers:
            x0, x1 = _LAYER_X[layer]
            s, a, _ = _lineage_box(x0, x1, yc, half_h, layer_rows.get(layer))
            shapes += s
            annotations += a
            _click_target(x0, x1, yc, layer_rows.get(layer))

        for i in range(len(present_layers) - 1):
            cur, nxt = present_layers[i], present_layers[i + 1]
            if _LAYER_COLUMNS.index(nxt) != _LAYER_COLUMNS.index(cur) + 1:
                continue
            color = _lineage_connector_color(layer_rows.get(nxt)) or "#5C5F66"
            shapes.append(_lineage_curve(_LAYER_X[cur][1], yc, _LAYER_X[nxt][0], yc, color))

    # Shared fan-in targets: one box per target, fed by diagonal connectors
    # from each contributing family's upstream (bronze) box.
    for (layer_name, target_fqn) in merge_targets:
        yc = merge_yc[(layer_name, target_fqn)]
        x0, x1 = _LAYER_X[layer_name]
        upstream_layer = _LAYER_COLUMNS[_LAYER_COLUMNS.index(layer_name) - 1] \
            if _LAYER_COLUMNS.index(layer_name) > 0 else None

        contributors = []
        for family in families:
            fam_group = df[df["family"] == family]
            target_row = fam_group[
                (fam_group["layer_name"] == layer_name) & (fam_group["fully_qualified_name"] == target_fqn)
            ]
            if target_row.empty:
                continue
            contributors.append((family, target_row.iloc[0]))

        contributors = sorted(contributors, key=lambda c: _ROLE_SORT.get(c[1].get("source_role"), 2))
        target_row = contributors[0][1] if contributors else None

        s, a, _ = _lineage_box(x0, x1, yc, half_h, target_row)
        shapes += s
        annotations += a
        _click_target(x0, x1, yc, target_row)

        orphan_badge_check = None
        for family, _ in contributors:
            source_yc = family_yc.get(family)
            if source_yc is None or upstream_layer is None:
                continue
            color = _lineage_connector_color(target_row) or "#5C5F66"
            shapes.append(_lineage_curve(_LAYER_X[upstream_layer][1], source_yc, x0, yc, color))

            orphan_check = join_checks_by_family.get(family, {}).get("JOIN_ORPHAN_RATE")
            if orphan_check is not None and orphan_badge_check is None:
                orphan_badge_check = orphan_check

        if orphan_badge_check is not None:
            color = _STATUS_COLOR.get(orphan_badge_check.get("check_status"), _STATUS_COLOR["UNKNOWN"])
            annotations.append(dict(
                x=x1, y=yc - half_h - 0.02, xref="x", yref="y",
                text=f"orphans: {(orphan_badge_check.get('source_value') or 0):.0f} rows checked",
                showarrow=False, font=dict(color=color, size=8), xanchor="right", yanchor="top",
            ))

    height = max(90 * n_rows, 90)
    return _lineage_row_graph(
        shapes, annotations, y_range=(0, 1), height=height,
        click_targets=click_targets, graph_id=graph_id,
    )


def _stage_pill(stage, status, ts, agent):
    color = _STATUS_COLOR.get(status, _STATUS_COLOR["UNKNOWN"])
    icon = "✓" if status == "PASS" else ("✕" if status == "CRITICAL" else "!")
    ts_str = ts.strftime("%d %b %H:%M UTC") if isinstance(ts, datetime) and pd.notna(ts) else str(ts or "N/A")
    agent_name = _format_agent_name(agent) if agent else STAGE_AGENT_NAMES.get(stage, "Unknown Agent")

    return html.Div([
        html.Div([
            html.Span(icon, style={
                "color": color, "fontWeight": "700", "marginRight": "8px", "fontSize": "14px",
            }),
            html.Span(agent_name, style={
                "color": "#ffffff", "fontWeight": "600", "fontSize": "13px", "marginRight": "10px",
            }),
            html.Span(status, style={
                "color": color, "fontWeight": "700", "fontSize": "11px",
                "border": f"1px solid {color}", "borderRadius": "4px",
                "padding": "1px 8px",
            }),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div(f"{stage} · {STAGE_LABELS.get(stage, stage)}", style={
            "color": "#909296", "fontSize": "11px", "marginTop": "4px",
        }),
        html.Div(f"⏱ {ts_str}", style={"color": "#5C5F66", "fontSize": "11px", "marginTop": "2px"}),
    ], className="ds-stage-pill", style={"borderColor": color})


@callback(
    Output("cp-trust-content", "children"),
    Input("control-plane-load-trigger", "data"),
    Input("control-plane-refresh-interval", "n_intervals"),
)
def load_trust_card(_, __):
    # ── Trust summary (Released / Pending / Quarantined) ────────────────────
    try:
        df_tables = execute_query(get_control_plane_table_status())
        counts = df_tables["overall_status"].value_counts().to_dict() if not df_tables.empty else {}
    except Exception as e:
        logger.error(f"Control plane table status query failed: {e}")
        counts = {}

    try:
        df_trend = execute_query(get_control_plane_trust_trend())
    except Exception as e:
        logger.error(f"Control plane trust trend query failed: {e}")
        df_trend = None

    released    = int(counts.get("PASS", 0))
    pending     = int(counts.get("WARNING", 0))
    quarantined = int(counts.get("CRITICAL", 0))

    sparkline = _trust_sparkline(df_trend)
    body_row = [
        _trust_donut(released, pending, quarantined),
        html.Div([
            _legend_row("#2f9e44", "Released", released),
            _legend_row("#f08c00", "Pending", pending),
            _legend_row("#e03131", "Quarantined", quarantined),
        ], style={"marginLeft": "20px"}),
    ]
    if sparkline is not None:
        body_row.append(html.Div(sparkline, style={"marginLeft": "auto"}))

    return dbc.Card(
        dbc.CardBody(
            html.Div(body_row, style={"display": "flex", "alignItems": "center"})
        ),
        style={"backgroundColor": "#1A1B1E", "border": "1px solid #373A40"},
    )


@callback(
    Output("cp-stepper-content", "children"),
    Input("control-plane-load-trigger", "data"),
    Input("control-plane-refresh-interval", "n_intervals"),
)
def load_stepper_card(_, __):
    # ── Workflow stepper (UC1 -> UC3 -> UC2 -> UC4) ─────────────────────────
    try:
        df_stages = execute_query(get_control_plane_stage_status())
        stage_map = {
            row["stage"]: (row["overall_status"], row["created_timestamp"], row["agent"])
            for _, row in df_stages.iterrows()
        } if not df_stages.empty else {}
    except Exception as e:
        logger.error(f"Control plane stage status query failed: {e}")
        stage_map = {}

    stepper_items = []
    for i, stage in enumerate(STAGE_ORDER):
        status, ts, agent = stage_map.get(stage, ("UNKNOWN", None, None))
        stepper_items.append(_stage_pill(stage, status, ts, agent))
        if i < len(STAGE_ORDER) - 1:
            stepper_items.append(html.Div("→", style={
                "color": "#5C5F66", "fontSize": "18px", "padding": "0 4px",
                "display": "flex", "alignItems": "center",
            }))

    return dbc.Card(
        dbc.CardBody([
            html.Div("Agentic Workflow", style={
                "color": "#5C5F66", "fontSize": "11px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "12px",
            }),
            html.Div(stepper_items, style={
                "display": "flex", "alignItems": "stretch", "flexWrap": "wrap", "gap": "4px",
            }),
        ]),
        style={"backgroundColor": "#1A1B1E", "border": "1px solid #373A40"},
    )


@callback(
    Output("cp-alerts-content", "children"),
    Input("control-plane-load-trigger", "data"),
    Input("control-plane-refresh-interval", "n_intervals"),
)
def load_alerts_card(_, __):
    # ── Active Alerts feed ───────────────────────────────────────────────────
    try:
        df_alerts = execute_query(get_control_plane_active_alerts())
    except Exception as e:
        logger.error(f"Control plane active alerts query failed: {e}")
        df_alerts = None

    if df_alerts is not None and not df_alerts.empty:
        alert_items = [
            _alert_item(r["source"], r["agent"], r["table_name"], r["run_id"], r["created_timestamp"])
            for _, r in df_alerts.iterrows()
        ]
    else:
        alert_items = [html.Div([
            html.Div("✓", style={"color": "#2f9e44", "fontSize": "22px", "marginBottom": "6px"}),
            html.Div("All clear", style={"color": "#C1C2C5", "fontSize": "13px", "fontWeight": "600"}),
            html.Div("No active critical alerts", style={"color": "#5C5F66", "fontSize": "11px", "marginTop": "2px"}),
        ], style={"textAlign": "center", "padding": "24px 0"})]

    return dbc.Card(
        dbc.CardBody([
            html.Div("Active Alerts", style={
                "color": "#5C5F66", "fontSize": "11px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "12px",
            }),
            html.Div(alert_items, style={"maxHeight": "480px", "overflowY": "auto"}),
        ]),
        style={"backgroundColor": "#1A1B1E", "border": "1px solid #373A40", "height": "100%"},
    )


@callback(
    Output("cp-lineage-content", "children"),
    Input("control-plane-load-trigger", "data"),
    Input("control-plane-refresh-interval", "n_intervals"),
)
def load_lineage_card(_, __):
    # ── Lineage board (hand-maintained layer registry) ─────────────────────
    try:
        df_lineage = execute_query(get_control_plane_lineage())
    except Exception as e:
        logger.error(f"Control plane lineage query failed: {e}")
        df_lineage = None

    try:
        df_joins = execute_query(get_control_plane_join_checks())
    except Exception as e:
        logger.error(f"Control plane join checks query failed: {e}")
        df_joins = None

    if df_lineage is not None and not df_lineage.empty:
        lineage_body = _build_lineage_graph(df_lineage, df_joins, graph_id="cp-lineage-graph")
    else:
        lineage_body = html.Div("No lineage data available", style={"color": "#5C5F66", "fontSize": "12px"})

    return dbc.Card(
        dbc.CardBody([
            html.Div("Data Lineage", style={
                "color": "#5C5F66", "fontSize": "11px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "12px",
            }),
            _lineage_header_graph(),
            lineage_body,
        ]),
        style={"backgroundColor": "#1A1B1E", "border": "1px solid #373A40"},
    )


@callback(
    Output("cp-lineage-content-uc", "children"),
    Input("control-plane-load-trigger", "data"),
    Input("control-plane-refresh-interval", "n_intervals"),
)
def load_lineage_card_uc(_, __):
    # ── Lineage board (Unity Catalog system.access.table_lineage) ──────────────
    try:
        df_lineage_uc = execute_query(get_control_plane_lineage_uc())
    except Exception as e:
        logger.error(f"Control plane UC lineage query failed: {e}")
        df_lineage_uc = None

    if df_lineage_uc is not None and not df_lineage_uc.empty:
        lineage_body = _build_lineage_graph(df_lineage_uc, df_joins=None, graph_id="cp-lineage-graph-uc")
    else:
        lineage_body = html.Div("No lineage data available", style={"color": "#5C5F66", "fontSize": "12px"})

    return dbc.Card(
        dbc.CardBody([
            html.Div("Data Lineage (Unity Catalog — Live)", style={
                "color": "#5C5F66", "fontSize": "11px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "12px",
            }),
            _lineage_header_graph(),
            lineage_body,
        ]),
        style={"backgroundColor": "#1A1B1E", "border": "1px solid #373A40"},
    )


@callback(
    Output("cp-lineage-content-native", "children"),
    Input("control-plane-load-trigger", "data"),
    Input("control-plane-refresh-interval", "n_intervals"),
)
def load_lineage_card_native(_, __):
    # ── Lineage board (native-UC-style recursive traversal, all onboarded tables) ──
    try:
        df_lineage_native = execute_query(get_control_plane_lineage_native())
    except Exception as e:
        logger.error(f"Control plane native lineage query failed: {e}")
        df_lineage_native = None

    if df_lineage_native is not None and not df_lineage_native.empty:
        lineage_body = _build_lineage_graph(df_lineage_native, df_joins=None, graph_id="cp-lineage-graph-native")
    else:
        lineage_body = html.Div("No lineage data available", style={"color": "#5C5F66", "fontSize": "12px"})

    return dbc.Card(
        dbc.CardBody([
            html.Div("Data Lineage (Native UC Traversal)", style={
                "color": "#5C5F66", "fontSize": "11px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "12px",
            }),
            _lineage_header_graph(),
            lineage_body,
        ]),
        style={"backgroundColor": "#1A1B1E", "border": "1px solid #373A40"},
    )


@callback(
    Output({"type": "cp-alert-collapse", "source": MATCH, "run_id": MATCH}, "is_open"),
    Output({"type": "cp-alert-chevron", "source": MATCH, "run_id": MATCH}, "children"),
    Input({"type": "cp-alert-header", "source": MATCH, "run_id": MATCH}, "n_clicks"),
    State({"type": "cp-alert-collapse", "source": MATCH, "run_id": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def toggle_alert_open(n_clicks, is_open):
    new_state = not is_open
    chevron = "▴" if new_state else "▾"
    return new_state, chevron


@callback(
    Output({"type": "cp-alert-detail", "source": MATCH, "run_id": MATCH}, "children"),
    Input({"type": "cp-alert-collapse", "source": MATCH, "run_id": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def fetch_alert_detail(is_open):
    if not is_open:
        return dash.no_update

    triggered = ctx.triggered_id
    source, run_id = triggered["source"], triggered["run_id"]

    try:
        df_run = execute_query(*get_control_plane_alert_run(source, run_id))
        if df_run.empty:
            return html.Div("Run details not found.", style={"color": "#5C5F66", "fontSize": "11px"})
        return _alert_detail_body(source, df_run.iloc[0])
    except Exception as e:
        logger.error(f"Control plane alert run fetch failed: {e}")
        return html.Div("Failed to load alert details.", style={"color": "#e03131", "fontSize": "11px"})


@callback(
    Output("cp-lineage-modal", "is_open"),
    Output("cp-lineage-modal-title", "children"),
    Output("cp-lineage-modal-body", "children"),
    Input("cp-lineage-graph", "clickData"),
    Input("cp-lineage-graph-uc", "clickData"),
    Input("cp-lineage-graph-native", "clickData"),
    Input("cp-lineage-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def open_lineage_detail(click_data_old, click_data_uc, click_data_native, _close_clicks):
    if ctx.triggered_id == "cp-lineage-modal-close":
        return False, dash.no_update, dash.no_update

    click_data = {
        "cp-lineage-graph": click_data_old,
        "cp-lineage-graph-uc": click_data_uc,
        "cp-lineage-graph-native": click_data_native,
    }.get(ctx.triggered_id)

    if not click_data or not click_data.get("points"):
        return dash.no_update, dash.no_update, dash.no_update

    point = click_data["points"][0]
    custom = point.get("customdata")
    if not custom:
        return dash.no_update, dash.no_update, dash.no_update

    source, run_id, table_name = custom["source"], custom["run_id"], custom.get("table_name", "")

    try:
        df_run = execute_query(*get_control_plane_alert_run(source, run_id))
        if df_run.empty:
            body = html.Div("Run details not found.", style={"color": "#5C5F66", "fontSize": "11px"})
        else:
            body = _alert_detail_body(source, df_run.iloc[0])
    except Exception as e:
        logger.error(f"Control plane lineage run fetch failed: {e}")
        body = html.Div("Failed to load run details.", style={"color": "#e03131", "fontSize": "11px"})

    return True, table_name, body
