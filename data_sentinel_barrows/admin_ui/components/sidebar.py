# components/sidebar.py — vertical left-nav alternative to navbar_dbc.py

import dash_bootstrap_components as dbc
from dash import html

# Pastel badge / saturated icon color pairs, reused across nav links and
# accordion group headers so each functional area reads as one color story.
_PALETTE = {
    "blue":   {"bg": "#d0ebff", "fg": "#1971c2"},
    "teal":   {"bg": "#c3fae8", "fg": "#0ca678"},
    "green":  {"bg": "#d3f9d8", "fg": "#2f9e44"},
    "orange": {"bg": "#ffe8cc", "fg": "#e8590c"},
    "purple": {"bg": "#e5dbff", "fg": "#7048e8"},
    "red":    {"bg": "#ffe3e3", "fg": "#e03131"},
    "yellow": {"bg": "#fff3bf", "fg": "#f08c00"},
    "gray":   {"bg": "#e9ecef", "fg": "#495057"},
}


def _icon_badge(bi_class, color="blue"):
    tone = _PALETTE.get(color, _PALETTE["gray"])
    return html.Span(
        html.I(className=f"bi {bi_class}"),
        className="ds-icon-badge",
        style={"backgroundColor": tone["bg"], "color": tone["fg"]},
    )


def _link(label, href, bi_class=None, color="blue"):
    children = []
    if bi_class:
        children.append(_icon_badge(bi_class, color))
    children.append(html.Span(label, className="ds-nav-label"))
    return dbc.NavLink(children, href=href, active="exact", className="ds-nav-link-icon")


def _group_title(text, bi_class, color):
    return html.Span(
        [_icon_badge(bi_class, color), html.Span(text, className="ds-group-label")],
        className="ds-group-title",
    )


def _group(title, bi_class, color, links):
    heading = _group_title(title, bi_class, color)
    return dbc.AccordionItem(
        dbc.Nav(links, vertical=True, pills=False),
        title=heading,
        item_id=title,
    )


def create_sidebar():
    return html.Div(
        [
            html.Div(
                [
                    _icon_badge("bi-shield-check", "blue"),
                    html.Span("DataSentinel", style={"fontWeight": "700", "fontSize": "18px", "color": "#ffffff"}),
                ],
                className="ds-sidebar-brand",
            ),

            dbc.Nav(
                [
                    _link("Dashboard", "/", "bi-house-door-fill", "blue"),
                    _link("Control Plane", "/control-plane", "bi-diagram-3-fill", "green"),
                    _link("AI Insights", "/ai-insights", "bi-cpu-fill", "purple"),
                    _link("Quality Score", "/quality-score", "bi-bar-chart-line-fill", "teal"),
                    _link("Status", "/status", "bi-broadcast", "orange"),
                    _link("Pipeline Health", "/pipeline-health", "bi-activity", "red"),
                ],
                vertical=True,
                className="mb-2",
            ),

            html.Div("Wizards", className="ds-sidebar-tier-label"),
            dbc.Accordion(
                [
                    _group("Wizards", "bi-magic", "purple", [
                        _link("Table Onboarding Wizard", "/onboarding", "bi-table"),
                        _link("Layer Recon Wizard", "/layer-onboarding", "bi-link-45deg"),
                        _link("Transformation Wizard", "/transformation-onboarding", "bi-shuffle"),
                        _link("Onboarding History", "/onboarding-history", "bi-clock-history"),
                        _link("Threshold Management", "/threshold-wizard", "bi-sliders"),
                    ]),
                ],
                start_collapsed=True,
                flush=True,
                className="ds-sidebar-accordion",
            ),

            html.Div("Agent Modules", className="ds-sidebar-tier-label"),
            dbc.Accordion(
                [
                    _group("Validation Agent", "bi-patch-check-fill", "green", [
                        _link("Table Registry", "/table-registry"),
                        _link("Column Registry", "/column-registry"),
                        _link("Validations", "/validations"),
                        _link("Baselines", "/baselines"),
                        _link("Baseline Explorer", "/baseline-explorer"),
                        _link("Validation Results", "/validation-results"),
                    ]),
                    _group("Reconciliation Agent", "bi-arrow-repeat", "blue", [
                        _link("Layer Registry", "/layer-registry"),
                        _link("Reconciliation Config", "/recon-config"),
                        _link("Reconciliation Results", "/reconciliation"),
                    ]),
                    _group("Transformation Agent", "bi-gear-wide-connected", "orange", [
                        _link("Transformation Registry", "/transformation-registry"),
                        _link("SQL Review", "/sql-review"),
                    ]),
                    _group("KPI Assurance Agent", "bi-graph-up-arrow", "teal", [
                        _link("KPI Registry", "/kpi-registry"),
                        _link("KPI Baselines", "/kpi-baselines"),
                        _link("KPI Validation", "/kpi-validation"),
                    ]),
                ],
                start_collapsed=True,
                flush=True,
                className="ds-sidebar-accordion",
            ),

            html.Div("Reports", className="ds-sidebar-tier-label"),
            dbc.Accordion(
                [
                    _group("Reports", "bi-folder2-open", "red", [
                        _link("Financial Report", "/financial-report", "bi-cash-coin"),
                        _link("Weekly Report", "/weekly-report", "bi-calendar-week"),
                        _link("Investigation", "/sentinel-investigation", "bi-search"),
                        _link("Cost Analysis", "/cost", "bi-currency-dollar"),
                    ]),
                ],
                start_collapsed=True,
                flush=True,
                className="ds-sidebar-accordion",
            ),

            dbc.Nav(
                [_link("Guide", "/user-guide", "bi-book-half", "gray")],
                vertical=True,
                className="mt-2",
            ),

            html.Div(style={"flex": "1"}),

            dbc.Button(
                "☰ Back to Top Menu",
                id="toggle-to-horizontal-btn",
                size="sm",
                outline=True,
                color="secondary",
                className="w-100 mt-3",
            ),
        ],
        className="ds-sidebar",
    )
